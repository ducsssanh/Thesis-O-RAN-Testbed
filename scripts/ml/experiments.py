#!/usr/bin/env python3
"""Baseline comparison on a (leakage-free) windows.npz.

Trains the LSTM and tabular baselines (LogReg / RandomForest / HistGB) on the same
split and reports detection metrics (AP, ROC-AUC, recall/FPR@thr) and ranking
metrics (P@k for p alone and for p*share), separating detection from
prioritisation. Appends one row per model to research/experiments/results.csv.

  .venv-ml/bin/python -I scripts/ml/experiments.py --data artifacts/ml/ncsrd-v2-dns/windows.npz --tag v2-dns
"""
import argparse, csv, json, os, pathlib, time
import numpy as np, torch
from torch import nn
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier

RESULTS = pathlib.Path(os.environ.get("RESULTS_CSV", "research/experiments/results.csv"))


class WindowLSTM(nn.Module):
    def __init__(self, nf, hidden=64, layers=1):
        super().__init__()
        self.lstm = nn.LSTM(nf, hidden, num_layers=layers, batch_first=True)
        self.head = nn.Linear(hidden, 1)
    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1]).squeeze(-1)


def metrics(y, p, share, name, tag, extra):
    pos = int(y.sum())
    def pk(s, k):
        o = np.argsort(-s); return float(y[o[:k]].mean())
    pred = p >= 0.5
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    rank = p * share
    m = {"tag": tag, "model": name, "n": len(y), "pos": pos,
         "AP": round(average_precision_score(y, p), 4),
         "ROC_AUC": round(roc_auc_score(y, p), 4),
         "recall@0.5": round(tp / max(pos, 1), 4),
         "FPR@0.5": round(fp / max(len(y) - pos, 1), 4),
         "precision@0.5": round(tp / max(tp + fp, 1), 4),
         "P@pos[p]": round(pk(p, pos), 4),
         "P@pos[rank]": round(pk(rank, pos), 4),
         "P@100[p]": round(pk(p, 100), 4),
         "P@100[rank]": round(pk(rank, 100), 4), **extra}
    print(f"  {name:12s} AP={m['AP']:.4f} ROC={m['ROC_AUC']:.4f} "
          f"rec@.5={m['recall@0.5']:.3f} FPR@.5={m['FPR@0.5']:.4f} "
          f"P@pos[p]={m['P@pos[p]']:.3f} P@pos[rank]={m['P@pos[rank]']:.3f}")
    return m


def run_lstm(Xtr, ytr, Xva, yva, epochs, seed):
    torch.manual_seed(seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    pw = torch.tensor([(len(ytr) - ytr.sum()) / max(ytr.sum(), 1)], dtype=torch.float32, device=dev)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pw)
    m = WindowLSTM(Xtr.shape[2]).to(dev)
    opt = torch.optim.Adam(m.parameters(), lr=1e-3)
    Xt = torch.from_numpy(Xtr); yt = torch.from_numpy(ytr.astype(np.float32))
    Xv = torch.from_numpy(Xva)
    g = torch.Generator().manual_seed(seed)
    best_ap, best_p, since = -1, None, 0
    for ep in range(1, epochs + 1):
        m.train(); idx = torch.randperm(len(Xt), generator=g)
        for i in range(0, len(Xt), 512):
            j = idx[i:i+512]
            opt.zero_grad()
            loss = loss_fn(m(Xt[j].to(dev)), yt[j].to(dev)); loss.backward(); opt.step()
        m.eval()
        with torch.no_grad():
            ps = [torch.sigmoid(m(Xv[i:i+4096].to(dev))).cpu() for i in range(0, len(Xv), 4096)]
            p = torch.cat(ps).numpy()
        ap = average_precision_score(yva, p) if yva.any() and not yva.all() else 0.0
        print(f"    epoch {ep:2d} val AP {ap:.4f}")
        if ap > best_ap: best_ap, best_p, since = ap, p, 0
        else:
            since += 1
            if since >= 4: break
    return best_p


def tabular_feats(X):
    # aggregate each [W,F] window -> [mean | last | std] over time
    return np.concatenate([X.mean(1), X[:, -1, :], X.std(1)], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-lstm", action="store_true", help="tabular baselines only (fast)")
    args = ap.parse_args()
    d = np.load(args.data, allow_pickle=True)
    Xtr, ytr = d["X_train"].astype(np.float32), d["y_train"].astype(np.int8)
    Xva, yva = d["X_val"].astype(np.float32), d["y_val"].astype(np.int8)
    share = d["share_val"].astype(np.float32)
    print(f"== {args.tag} == train {len(Xtr)} (pos {int(ytr.sum())}) val {len(Xva)} (pos {int(yva.sum())})")

    rows = []
    if not args.no_lstm:
        t0 = time.time()
        p = run_lstm(Xtr, ytr, Xva, yva, args.epochs, args.seed)
        rows.append(metrics(yva, p, share, "LSTM", args.tag, {"seed": args.seed, "train_s": round(time.time()-t0, 1)}))

    Ftr, Fva = tabular_feats(Xtr), tabular_feats(Xva)
    models = {
        "LogReg": LogisticRegression(max_iter=1000, class_weight="balanced"),
        "RandomForest": RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                               n_jobs=-1, random_state=args.seed),
        "HistGB": HistGradientBoostingClassifier(max_iter=300, random_state=args.seed,
                                                 class_weight="balanced"),
    }
    for name, clf in models.items():
        t0 = time.time(); clf.fit(Ftr, ytr)
        pp = clf.predict_proba(Fva)[:, 1]
        rows.append(metrics(yva, pp, share, name, args.tag, {"seed": args.seed, "train_s": round(time.time()-t0, 1)}))

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    new = not RESULTS.exists()
    keys = list(rows[0].keys())
    with open(RESULTS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        if new: w.writeheader()
        for r in rows: w.writerow(r)
    print("appended", len(rows), "rows to", RESULTS)


if __name__ == "__main__":
    main()
