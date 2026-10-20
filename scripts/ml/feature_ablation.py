#!/usr/bin/env python3
"""Feature ablation on ONE leakage-free split (apples-to-apples).

Trains RF + LogReg on chosen feature subsets of the SAME windows.npz, so AP
differences are attributable to the features alone. Built to answer:
  * is resid_dl a shortcut? -> compare all vs drop-resid_dl vs drop-both-residuals
  * how much does UL share carry? -> share-only, drop-share
Also reports the effective independence of the high-load-benign set (distinct
segments), to check the "0 FPR on N windows" is not a few correlated sessions.

  .venv-ml/bin/python -I scripts/ml/feature_ablation.py --data artifacts/ml/ncsrd-v2-dns/windows.npz --tag v2-dns
"""
import argparse, csv, json, os, pathlib
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier

FEATURES = ["ran_ul_kbps","ran_dl_kbps","core_ul_kbps","core_dl_kbps","cell_ul_kbps",
            "resid_ul","resid_dl","ue_cell_ul_share","ul_mcs","dl_mcs",
            "ul_retx","dl_retx","ul_err","dl_err","cqi","pusch_snr"]
IDX = {f: i for i, f in enumerate(FEATURES)}
RESULTS = pathlib.Path(os.environ.get("ABLATION_CSV", "research/experiments/results_ablation.csv"))

SUBSETS = {
    "all16": FEATURES,
    "drop_resid_dl": [f for f in FEATURES if f != "resid_dl"],
    "drop_both_resid": [f for f in FEATURES if f not in ("resid_dl", "resid_ul")],
    "only_resid": ["resid_ul", "resid_dl"],
    "only_resid_dl": ["resid_dl"],
    "drop_share": [f for f in FEATURES if f != "ue_cell_ul_share"],
    "share_only": ["ue_cell_ul_share"],
    "volume_only": ["ran_ul_kbps", "ran_dl_kbps", "core_ul_kbps", "core_dl_kbps", "cell_ul_kbps"],
    "no_volume": [f for f in FEATURES if f not in
                  ("ran_ul_kbps","ran_dl_kbps","core_ul_kbps","core_dl_kbps","cell_ul_kbps")],
}


def agg(X, keep_idx):
    Xk = X[:, :, keep_idx]
    return np.concatenate([Xk.mean(1), Xk[:, -1, :], Xk.std(1)], axis=1)


def evaluate(y, p):
    pos = int(y.sum()); o = np.argsort(-p)
    return (round(average_precision_score(y, p), 4), round(roc_auc_score(y, p), 4),
            round(float(y[o[:pos]].mean()), 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--only", default="", help="comma subset names to run (default: all)")
    args = ap.parse_args()
    d = np.load(args.data, allow_pickle=True)
    Xtr, ytr = d["X_train"].astype(np.float32), d["y_train"].astype(np.int8)
    Xva, yva = d["X_val"].astype(np.float32), d["y_val"].astype(np.int8)
    nfeat = Xtr.shape[2]
    names = FEATURES[:nfeat]

    # independence of the high-load-benign set
    seg = d["seg_val"] if "seg_val" in d.files else None
    ul = Xva[:, -1, 0]; ben = yva == 0
    hi_ben = ben & (ul >= np.quantile(ul[ben], 0.9))
    indep = {"highload_benign_windows": int(hi_ben.sum()),
             "highload_benign_distinct_segments": int(len(set(seg[hi_ben].tolist()))) if seg is not None else None,
             "distinct_val_segments_total": int(len(set(seg.tolist()))) if seg is not None else None}

    todo = args.only.split(",") if args.only else list(SUBSETS)
    rows = []
    for name in todo:
        feats = [f for f in SUBSETS[name] if f in names]
        idx = [IDX[f] for f in feats]
        Ftr, Fva = agg(Xtr, idx), agg(Xva, idx)
        for mdl, clf in [("RF", RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                                        n_jobs=-1, random_state=0)),
                         ("LogReg", LogisticRegression(max_iter=1000, class_weight="balanced"))]:
            clf.fit(Ftr, ytr); p = clf.predict_proba(Fva)[:, 1]
            apv, roc, ppos = evaluate(yva, p)
            r = {"tag": args.tag, "subset": name, "n_features": len(feats), "model": mdl,
                 "AP": apv, "ROC_AUC": roc, "P@pos": ppos}
            rows.append(r)
            print(f"  {name:16s} {mdl:7s} nf={len(feats):2d} AP={apv:.4f} ROC={roc:.4f} P@pos={ppos:.4f}")

    print("  independence:", json.dumps(indep))
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    new = not RESULTS.exists()
    with open(RESULTS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new: w.writeheader()
        for r in rows: w.writerow(r)
    pathlib.Path(f"research/experiments/independence_{args.tag}.json").write_text(json.dumps(indep, indent=2) + "\n")


if __name__ == "__main__":
    main()
