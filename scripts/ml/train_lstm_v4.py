#!/usr/bin/env python3
"""Train the per-UE LSTM classifier on the v4 windows (local or Kaggle; GPU if available).

  python train_lstm_v4.py --win DIR --out OUT [--features all|no_dl] [--seed 0]

DIR holds windows_v4.npz + meta.json (scripts/ml/prep_v4_windows.py) and v4_eval.py sits
next to this script. Train = TRAIN main windows only (IDLE is never a target); early stop on
VAL main PR-AUC; threshold frozen on VAL at benign FPR --fpr; TEST reported with the same
v4_eval metrics as the tabular baselines (main windows headline, per-pair, idle false alarms,
time-to-detect from edge windows).
  --features no_dl drops every downlink column (*_dl_*): the designed benign DL feedback is a
  near-label proxy in v4 (DL-only baseline AUC 0.96), so no_dl is the robustness headline.
Outputs: model.pt (weights + feature list + scaler), metrics.json, scores.npz (all windows).
"""
import argparse, json, pathlib, sys
import numpy as np
import torch
from torch import nn
from sklearn.metrics import average_precision_score

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v4_eval as E


class WindowLSTM(nn.Module):
    def __init__(self, n_features, hidden=64, layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden, num_layers=layers, batch_first=True,
                            dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, 1))

    def forward(self, x):                      # x: [batch, window, features], oldest first
        out, _ = self.lstm(x)
        return self.head(out[:, -1]).squeeze(-1)


def scores(model, X, device, bs=4096):
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            out.append(torch.sigmoid(model(X[i:i + bs].to(device))).cpu())
    return torch.cat(out).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--features", choices=("all", "no_dl"), default="all")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--fpr", type=float, default=0.01)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    win = pathlib.Path(a.win)
    d = dict(np.load(win / "windows_v4.npz"))
    meta = json.loads((win / "meta.json").read_text())
    names = meta["features"]
    keep = [i for i, n in enumerate(names) if a.features == "all" or "_dl" not in n]
    X = torch.from_numpy(d["X"][:, :, keep].astype(np.float32))
    y = d["y"].astype(np.float32)
    tr = np.where((d["split"] == 0) & (d["kind"] == E.MAIN))[0]
    va = (d["split"] == 1) & (d["kind"] == E.MAIN)
    Xtr, ytr = X[tr], torch.from_numpy(y[tr])
    model = WindowLSTM(len(keep), a.hidden, a.layers, a.dropout).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    loss_fn = nn.BCEWithLogitsLoss()
    gen = torch.Generator().manual_seed(a.seed)
    print("device %s features %s (%d) train %d (pos %d) val %d" % (device, a.features, len(keep), len(tr),
          int(ytr.sum()), int(va.sum())), flush=True)
    best, best_state, since, hist = -1.0, None, 0, []
    for ep in range(1, a.epochs + 1):
        model.train()
        tot = 0.0
        for j in torch.randperm(len(Xtr), generator=gen).split(a.batch):
            opt.zero_grad()
            loss = loss_fn(model(Xtr[j].to(device)), ytr[j].to(device))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(j)
        pv = scores(model, X[va], device)
        apv = float(average_precision_score(y[va], pv))
        hist.append({"epoch": ep, "train_loss": round(tot / len(tr), 4), "val_pr_auc": round(apv, 4)})
        print("epoch %2d loss %.4f val PR-AUC %.4f" % (ep, tot / len(tr), apv), flush=True)
        if apv > best:
            best, since = apv, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            since += 1
            if since >= a.patience:
                print("early stop", flush=True)
                break
    model.load_state_dict(best_state)
    p = scores(model, X, device)
    thr = E.threshold_at_fpr(p[va], d["y"][va], a.fpr)
    res = {"features": a.features, "feature_names": [names[i] for i in keep], "best_val_pr_auc": round(best, 4),
           "val": E.report(p, d, 1, thr), "test": E.report(p, d, 2, thr), "args": vars(a), "history": hist}
    torch.save({"state_dict": model.state_dict(), "n_features": len(keep), "hidden": a.hidden, "layers": a.layers,
                "features": res["feature_names"], "window_s": meta["window_s"], "threshold": thr,
                "scaler_mean": [float(d["mean"][i]) for i in keep], "scaler_std": [float(d["std"][i]) for i in keep],
                "transform": meta["transform"]}, out / "model.pt")
    np.savez_compressed(out / "scores.npz", p=p, y=d["y"], split=d["split"], kind=d["kind"])
    (out / "metrics.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(E.md_table({"LSTM %s seed %d" % (a.features, a.seed): res["test"]}))


if __name__ == "__main__":
    main()
