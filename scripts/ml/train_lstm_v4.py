#!/usr/bin/env python3
"""Train the per-UE LSTM classifier on the v4 windows (local or Kaggle; GPU if available).

  python train_lstm_v4.py --win DIR --out OUT [--features ul|urr_prof_ul|all] [--seed 0]
                          [--split-seed K] [--transfer NAME]

DIR holds windows_v4.npz + meta.json (scripts/ml/prep_v4_windows.py); v4_eval.py sits next to
this script and is the SAME evaluation code as the GBDT baselines (scripts/ml/baseline_v4.py).
- Detector is UL-only by design: --features ul (default) = the 17 UL columns; urr_prof_ul = URR +
  profiler UL only (no RAN); all = incl. DL, appendix only (DL is a designed near-label proxy).
- Train = TRAIN main windows, negative-control pair icmp_flood~icmp_ping excluded; early stop on
  VAL main PR-AUC; threshold frozen on VAL at benign FPR --fpr; report on TEST (main headline,
  per-pair macro, mimicry, pulsing, control AUC, TTD, idle FPR, gated operating point) + 95%
  bootstrap CI by run.
- --split-seed K re-splits the runs (v4_eval.split_from_windows); --transfer NAME trains/thresholds
  on one condition and tests on the other (v4_eval.transfer_protocols names).
- Shuffle test: the time order inside every test window is permuted; if the AUC does not drop, the
  LSTM does not use temporal information.
Inputs are re-standardised on the training windows of the split in use. Outputs: model.pt,
metrics.json, scores.npz.
"""
import argparse, json, pathlib, sys
import numpy as np
import torch
from torch import nn
from sklearn.metrics import average_precision_score, roc_auc_score

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


def select(names, which):
    if which == "all":
        return list(range(len(names)))
    ul = [i for i, n in enumerate(names) if "_dl" not in n]
    if which == "ul":
        return ul
    return [i for i in ul if names[i].startswith(("urr_", "prof_"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--features", choices=("ul", "urr_prof_ul", "all"), default="ul")
    ap.add_argument("--split-seed", type=int, default=None)
    ap.add_argument("--transfer", default=None)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=6)
    ap.add_argument("--fpr", type=float, default=0.01)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    win = pathlib.Path(a.win)
    d = dict(np.load(win / "windows_v4.npz"))
    meta = json.loads((win / "meta.json").read_text())
    if a.split_seed is not None:
        d["split"] = E.split_from_windows(d, 20261023 + 100 * a.split_seed)
    ftrain, ftest = None, None
    if a.transfer:
        P = {n: (tr, te) for n, tr, te in E.all_transfer_protocols(d)}
        ftrain, ftest = P[a.transfer]
    names = meta["features"]
    keep = select(names, a.features)
    Xn = d["X"][:, :, keep].astype(np.float32)
    tr = np.flatnonzero(E.train_mask(d, ftrain))
    mu = Xn[tr].reshape(-1, len(keep)).mean(0); sd = Xn[tr].reshape(-1, len(keep)).std(0) + 1e-6
    X = torch.from_numpy((Xn - mu) / sd)
    y = d["y"].astype(np.float32)
    va = E.headline_mask(d, d["split"] == 1)
    if ftrain is not None:
        va &= ftrain
    Xtr, ytr = X[tr], torch.from_numpy(y[tr])
    model = WindowLSTM(len(keep), a.hidden, a.layers, a.dropout).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    loss_fn = nn.BCEWithLogitsLoss()
    gen = torch.Generator().manual_seed(a.seed)
    print("device %s features %s (%d) split-seed %s transfer %s train %d (pos %d) val %d" % (
        device, a.features, len(keep), a.split_seed, a.transfer, len(tr), int(ytr.sum()), int(va.sum())), flush=True)
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
    thr = E.val_threshold(p, d, a.fpr, extra=ftrain)
    sel = d["split"] == 2
    if ftest is not None:
        sel &= ftest
    test = E.report(p, d, sel, thr)
    # shuffle test: permute the time axis inside every test window
    hm = E.headline_mask(d, sel)
    rng = np.random.default_rng(a.seed)
    Xs = X[hm].clone()
    perm = torch.from_numpy(np.argsort(rng.random((Xs.shape[0], Xs.shape[1])), axis=1))
    Xs = torch.gather(Xs, 1, perm.unsqueeze(-1).expand_as(Xs))
    ps = scores(model, Xs, device)
    test["shuffled_time_roc_auc"] = round(float(roc_auc_score(d["y"][hm], ps)), 4)
    res = {"model": "LSTM", "features": a.features, "feature_names": [names[i] for i in keep],
           "split_seed": a.split_seed, "transfer": a.transfer, "best_val_pr_auc": round(best, 4),
           "test": test, "bootstrap_ci": E.bootstrap_ci(p, d, sel, thr, B=a.boot) if not a.transfer else None,
           "args": vars(a), "history": hist}
    torch.save({"state_dict": model.state_dict(), "n_features": len(keep), "hidden": a.hidden, "layers": a.layers,
                "features": res["feature_names"], "window_s": meta["window_s"], "threshold": thr,
                "scaler_mean": [float(d["mean"][i]) for i in keep], "scaler_std": [float(d["std"][i]) for i in keep],
                "restandardise_mean": mu.tolist(), "restandardise_std": sd.tolist(),
                "transform": meta["transform"], "gate": meta.get("gate")}, out / "model.pt")
    np.savez_compressed(out / "scores.npz", p=p, y=d["y"], split=d["split"], kind=d["kind"])
    (out / "metrics.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(E.md_table({"LSTM %s seed %d" % (a.features, a.seed): test}, {"LSTM %s seed %d" % (a.features, a.seed): res["bootstrap_ci"]}))
    print("shuffled-time ROC-AUC %s (unshuffled %s)" % (test["shuffled_time_roc_auc"], test["roc_auc"]))


if __name__ == "__main__":
    main()
