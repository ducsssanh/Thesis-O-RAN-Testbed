#!/usr/bin/env python3
"""Train the LSTM that ranks UEs by safety x volume (docs/AI-DEFENSE-MODEL-DESIGN.md).

  .venv-ml/bin/python -I scripts/ml/train_lstm.py --data artifacts/ml/ncsrd/windows.npz --out artifacts/ml/ncsrd

Reads the windows built by prep_ncsrd.py (the train/val split is already
leave-one-attack-out: prep_ncsrd.py --val-attack k holds out attack k). Trains
a small LSTM with one head, p_attack in [0,1], and saves model.pt plus
metrics.json. The rank is not learned: it is p_attack x the UE's observed cell
uplink share (saved per window as share_*), formed and reported here.

Only the safety head is trained. The volume-forecast head of the design needs
a "next-window volume" target built in preprocessing and is left for later; the
rank uses the observed share, so it works without it.

Class imbalance (~1.7% positive) is handled with a positive class weight in the
loss, and the metrics are PR-AUC (average precision) and per-attack recall, not
accuracy, which would be meaningless here.

Pure CPU, no GPU needed; this dataset trains in a few minutes.
"""
import argparse
import json
import pathlib

import numpy as np
import torch
from torch import nn
from sklearn.metrics import average_precision_score, roc_auc_score

ATTACK_NAME = {0: "benign", 1: "syn", 2: "icmp", 3: "udp_frag", 4: "dns", 5: "gtpu"}


class WindowLSTM(nn.Module):
    """1-2 LSTM layers over the window, then a linear head to one logit."""

    def __init__(self, n_features, hidden=64, layers=1, dropout=0.0):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden, num_layers=layers, batch_first=True,
                            dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):            # x: [batch, window, features]
        out, _ = self.lstm(x)        # out: [batch, window, hidden]
        return self.head(out[:, -1]).squeeze(-1)  # last step -> one logit


def batches(X, y, size, shuffle, gen):
    idx = torch.randperm(len(X), generator=gen) if shuffle else torch.arange(len(X))
    for i in range(0, len(X), size):
        j = idx[i:i + size]
        yield X[j], y[j]


def evaluate(model, X, y, an, share, device, out_dir):
    model.eval()
    with torch.no_grad():
        scores = []
        for xb, _ in batches(X, y, 4096, False, None):
            scores.append(torch.sigmoid(model(xb.to(device))).cpu())
        p = torch.cat(scores).numpy()
    yv = y.numpy().astype(int)
    anv = an.numpy()
    m = {"n": int(len(yv)), "positives": int(yv.sum()),
         "pr_auc": round(float(average_precision_score(yv, p)), 4) if yv.any() and not yv.all() else None,
         "roc_auc": round(float(roc_auc_score(yv, p)), 4) if yv.any() and not yv.all() else None}
    # recall per attack at a fixed threshold, and false positives on benign
    thr = 0.5
    pred = p >= thr
    benign = anv == 0
    m["false_positive_rate_benign"] = round(float(pred[benign].mean()), 4) if benign.any() else None
    m["recall_per_attack"] = {}
    for k in sorted(set(anv.tolist())):
        if k == 0:
            continue
        pos = (anv == k) & (yv == 1)
        if pos.any():
            m["recall_per_attack"][ATTACK_NAME[k]] = round(float(pred[pos].mean()), 4)
    # rank = p_attack x observed cell uplink share; does it put attackers on top?
    rank = p * share.numpy()
    order = np.argsort(-rank)
    k = int(yv.sum())
    if k:
        topk = order[:k]
        m["rank_precision_at_positives"] = round(float(yv[topk].mean()), 4)
    np.savez_compressed(out_dir / "val_scores.npz", p_attack=p, y=yv, attack_number=anv, rank=rank)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="windows.npz from prep_ncsrd.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--layers", type=int, default=1)
    ap.add_argument("--dropout", type=float, default=0.0)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=5, help="early stop on val PR-AUC")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(args.seed)
    gen = torch.Generator().manual_seed(args.seed)
    # GPU if available (e.g. Kaggle T4/P100), else CPU; the dataset is small
    # enough that CPU finishes in minutes
    device = "cuda" if torch.cuda.is_available() else "cpu"

    d = np.load(args.data, allow_pickle=True)
    Xtr = torch.from_numpy(d["X_train"].astype(np.float32))
    ytr = torch.from_numpy(d["y_train"].astype(np.float32))
    Xva = torch.from_numpy(d["X_val"].astype(np.float32))
    yva = torch.from_numpy(d["y_val"].astype(np.float32))
    an_va = torch.from_numpy(d["an_val"])
    share_va = torch.from_numpy(d["share_val"].astype(np.float32))
    n_features = Xtr.shape[2]

    # positive class weight = (#neg / #pos) so the rare attack class counts
    pos = float(ytr.sum())
    neg = float(len(ytr) - pos)
    pos_weight = torch.tensor([neg / max(pos, 1.0)], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    model = WindowLSTM(n_features, args.hidden, args.layers, args.dropout).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    print("device", device, flush=True)
    print("train %d (pos %d), val %d (pos %d), features %d, pos_weight %.1f"
          % (len(Xtr), int(pos), len(Xva), int(yva.sum()), n_features, pos_weight.item()), flush=True)

    best_ap, best_state, since = -1.0, None, 0
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for xb, yb in batches(Xtr, ytr, args.batch, True, gen):
            opt.zero_grad()
            loss = loss_fn(model(xb.to(device)), yb.to(device))
            loss.backward()
            opt.step()
            total += loss.item() * len(xb)
        m = evaluate(model, Xva, yva, an_va, share_va, device, out)
        history.append({"epoch": epoch, "train_loss": round(total / len(Xtr), 4), **m})
        print("epoch %2d loss %.4f val PR-AUC %s ROC-AUC %s FPR_benign %s"
              % (epoch, total / len(Xtr), m["pr_auc"], m["roc_auc"], m["false_positive_rate_benign"]), flush=True)
        ap_now = m["pr_auc"] or 0.0
        if ap_now > best_ap:
            best_ap, best_state, since = ap_now, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            since += 1
            if since >= args.patience:
                print("early stop (val PR-AUC did not improve for %d epochs)" % args.patience, flush=True)
                break

    if best_state:
        model.load_state_dict(best_state)
    final = evaluate(model, Xva, yva, an_va, share_va, device, out)
    torch.save({"state_dict": model.state_dict(),
                "config": {"n_features": n_features, "hidden": args.hidden, "layers": args.layers},
                "features": list(d["mean"].shape and []) or None,  # feature names live in meta.json
                "scaler_mean": d["mean"].tolist(), "scaler_std": d["std"].tolist()},
               out / "model.pt")
    (out / "metrics.json").write_text(json.dumps(
        {"best_val_pr_auc": round(best_ap, 4), "final": final,
         "args": vars(args), "history": history}, indent=2) + "\n")
    print("\nbest val PR-AUC %.4f" % best_ap)
    print(json.dumps(final, indent=2))
    print("written", out / "model.pt", "and", out / "metrics.json")


if __name__ == "__main__":
    main()
