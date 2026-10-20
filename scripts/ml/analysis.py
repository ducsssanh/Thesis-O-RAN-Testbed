#!/usr/bin/env python3
"""Deep analysis on a leakage-free windows.npz: the high-load-benign challenge,
feature importance, and leakage-free threshold selection.

Addresses the ultimate goal: does the detector separate MALICIOUS behaviour from
LEGITIMATE HIGH-LOAD traffic, rather than just flagging heavy UEs?

Uses the strongest tabular baseline (HistGB) + RandomForest (for importances) on
per-window [mean|last|std] aggregates. Threshold is chosen on the TRAIN split
(1% train-benign FPR), never on val.

  .venv-ml/bin/python -I scripts/ml/analysis.py --data artifacts/ml/ncsrd-v2-dns/windows.npz --tag v2-dns
"""
import argparse, json, pathlib
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

FEATURES = ["ran_ul_kbps","ran_dl_kbps","core_ul_kbps","core_dl_kbps","cell_ul_kbps",
            "resid_ul","resid_dl","ue_cell_ul_share","ul_mcs","dl_mcs",
            "ul_retx","dl_retx","ul_err","dl_err","cqi","pusch_snr"]


def agg(X):
    return np.concatenate([X.mean(1), X[:, -1, :], X.std(1)], axis=1)


def thr_at_train_fpr(ptr, ytr, target=0.01):
    neg = ptr[ytr == 0]
    return float(np.quantile(neg, 1 - target)) if len(neg) else 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--load-q", type=float, default=0.90, help="high-load benign = top (1-q) by UL")
    args = ap.parse_args()
    d = np.load(args.data, allow_pickle=True)
    Xtr, ytr = d["X_train"].astype(np.float32), d["y_train"].astype(np.int8)
    Xva, yva = d["X_val"].astype(np.float32), d["y_val"].astype(np.int8)
    nfeat = Xtr.shape[2]
    names = FEATURES[:nfeat] + [f"extra{ i }" for i in range(nfeat - len(FEATURES))] if nfeat > len(FEATURES) else FEATURES[:nfeat]
    Ftr, Fva = agg(Xtr), agg(Xva)

    clf = HistGradientBoostingClassifier(max_iter=300, class_weight="balanced", random_state=0)
    clf.fit(Ftr, ytr)
    ptr = clf.predict_proba(Ftr)[:, 1]; p = clf.predict_proba(Fva)[:, 1]
    thr = thr_at_train_fpr(ptr, ytr, 0.01)

    pos = yva == 1; ben = yva == 0
    ul = Xva[:, -1, 0]                       # last-step ran_ul (standardised, monotonic w/ throughput)
    hi_cut = np.quantile(ul[ben], args.load_q)
    hi_ben = ben & (ul >= hi_cut)            # high-load benign (the challenge)
    lo_ben = ben & (ul < hi_cut)

    def fpr(mask): return float((p[mask] >= thr).mean()) if mask.any() else None
    def rec(mask): return float((p[mask] >= thr).mean()) if mask.any() else None

    # load-matched: attackers vs benign within the top-2 UL deciles
    dec = np.quantile(ul, 0.8)
    hi_all = ul >= dec
    out = {
        "tag": args.tag, "n_features": nfeat, "threshold@1%trainFPR": round(thr, 4),
        "AP": round(average_precision_score(yva, p), 4),
        "ROC_AUC": round(roc_auc_score(yva, p), 4),
        "recall_attackers": round(rec(pos), 4),
        "FPR_all_benign": round(fpr(ben), 4),
        "FPR_highload_benign": round(fpr(hi_ben), 4),
        "FPR_normal_benign": round(fpr(lo_ben), 4),
        "mean_score_attacker": round(float(p[pos].mean()), 4) if pos.any() else None,
        "mean_score_highload_benign": round(float(p[hi_ben].mean()), 4) if hi_ben.any() else None,
        "mean_score_normal_benign": round(float(p[lo_ben].mean()), 4) if lo_ben.any() else None,
        "load_matched_top20pct": {
            "recall_attackers": round(rec(pos & hi_all), 4) if (pos & hi_all).any() else None,
            "FPR_benign": round(fpr(ben & hi_all), 4) if (ben & hi_all).any() else None,
            "n_attackers": int((pos & hi_all).sum()), "n_benign": int((ben & hi_all).sum()),
        },
    }

    # feature importance via RandomForest impurity, aggregated to base features
    rf = RandomForestClassifier(n_estimators=150, class_weight="balanced", n_jobs=-1, random_state=0)
    rf.fit(Ftr, ytr)
    imp = rf.feature_importances_            # length 3*nfeat (mean|last|std)
    base = np.zeros(nfeat)
    for b in range(nfeat):
        base[b] = imp[b] + imp[nfeat + b] + imp[2 * nfeat + b]
    order = np.argsort(-base)
    out["top_features"] = [(names[i], round(float(base[i]), 4)) for i in order[:8]]

    pathlib.Path("research/experiments").mkdir(parents=True, exist_ok=True)
    pathlib.Path(f"research/experiments/analysis_{args.tag}.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
