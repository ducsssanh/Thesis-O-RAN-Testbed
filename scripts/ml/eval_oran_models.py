#!/usr/bin/env python3
"""Phase L — baseline detection models + ablations on the O-RAN flooding dataset.

Answers the central question: can a detector tell malicious user-plane flooding
from legitimate high-load traffic, or does it merely learn traffic VOLUME?

Method (leakage-aware by construction):
  - Rows = per-SUPI-per-second records from build_oran_dataset.py (online
    features only; decision outputs already excluded there).
  - Split is GROUPED by independent session = (campaign, run, supi) via
    StratifiedGroupKFold, so no session appears in both train and test. Never a
    random row split (that would leak a session across the fold boundary).
  - FEATURE ABLATIONS isolate what the signal comes from:
      volume-only   pure byte/packet rate across all layers (KPM+URR+profiler)
      ran-only      E2SM-KPM RAN counters (rate/throughput/PRB)
      ran+upf       RAN + PFCP/URR core usage counters
      behaviour     profiler protocol-mix + mean_bytes + fan-out (NO volume)
      full          everything
  - LOAD-MATCHED CHALLENGE SET: re-score the SAME models on only the test rows
    inside the throughput band where both classes are dense (overlap band). If a
    model rode volume, it collapses here; a behavioural model should hold.

Expected result if the dataset is honest: volume-only ~ chance on the challenge
set, behaviour/full stay high -> separation is behavioural, not volumetric.

Runs on CPU in seconds. No GPU, no external services.
"""
import argparse
import json
import pathlib
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import (
    f1_score, roc_auc_score, balanced_accuracy_score, recall_score,
    precision_score, confusion_matrix,
)

warnings.filterwarnings("ignore")

# ---- feature groups (mirror build_oran_dataset.py; X = online features only) --
# Decomposed so the ablation attributes the signal to the RIGHT axis. The first
# run lumped packet-rate (pps) into "volume-only" and it scored ~1.0 on the
# challenge set — but pps/packet-size are packet STRUCTURE, not byte-rate. These
# groups separate pure byte-rate (bytes-only) from structure (pps/size) from
# protocol-mix, so "does it just learn VOLUME (bytes/sec)?" is answered honestly.
BYTES = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
         "urr_ul_kbps", "urr_dl_kbps", "prof_ul_kbps", "prof_dl_kbps"]
PPS = ["urr_ul_pps", "urr_dl_pps", "prof_ul_pps", "prof_dl_pps"]
SIZE = ["prof_ul_mean_bytes", "prof_dl_mean_bytes"]
PROTOCOL = ["prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp",
            "prof_ul_frag", "prof_ul_dns", "prof_ul_gtp_in_gtp",
            "prof_dl_tcp", "prof_dl_tcp_syn", "prof_dl_udp", "prof_dl_icmp",
            "prof_dl_frag", "prof_ul_dst_estimate"]
RAN = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
       "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
URR = ["urr_ul_kbps", "urr_dl_kbps", "urr_ul_pps", "urr_dl_pps"]
# behaviour = packet structure + protocol mix + fan-out, NO raw byte-rate.
BEHAVIOUR = SIZE + PROTOCOL
FULL = sorted(set(BYTES + PPS + SIZE + PROTOCOL + RAN + URR))

ABLATIONS = {
    "bytes-only": BYTES,          # pure byte-rate (the real "volume" question)
    "pps-only": PPS,              # packet-rate (small-packet flood signature)
    "size-only": SIZE,            # mean packet size
    "protocol-only": PROTOCOL,    # protocol mix + fan-out
    "ran-only": RAN,              # E2SM-KPM RAN counters
    "ran+upf": sorted(set(RAN + URR)),
    "behaviour-only": BEHAVIOUR,  # structure + protocol, no byte-rate
    "full": FULL,
}

# overlap band on the dense KPM throughput axis where both classes live
CHALLENGE_LO, CHALLENGE_HI = 300.0, 1000.0
CHALLENGE_COL = "thp_ul_kbps"
POS_LABEL = "MALICIOUS"
N_SPLITS = 5
SEED = 13


def models():
    return {
        "logreg": make_pipeline(
            SimpleImputer(strategy="constant", fill_value=0.0),
            StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight="balanced"),
        ),
        "random-forest": make_pipeline(
            SimpleImputer(strategy="constant", fill_value=0.0),
            RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                   random_state=SEED, n_jobs=-1),
        ),
        "hist-gbm": HistGradientBoostingClassifier(
            random_state=SEED, class_weight="balanced"),
    }


def score(y_true, y_pred, y_prob):
    out = {
        "f1": f1_score(y_true, y_pred, pos_label=1, zero_division=0),
        "precision": precision_score(y_true, y_pred, pos_label=1, zero_division=0),
        "recall": recall_score(y_true, y_pred, pos_label=1, zero_division=0),
        "bal_acc": balanced_accuracy_score(y_true, y_pred),
    }
    out["auc"] = roc_auc_score(y_true, y_prob) if len(set(y_true)) > 1 else float("nan")
    return out


def mean_std(dicts):
    keys = dicts[0].keys()
    return {k: (float(np.nanmean([d[k] for d in dicts])),
               float(np.nanstd([d[k] for d in dicts]))) for k in keys}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research/datasets/oran_flooding_v3/synchronized/records.csv")
    ap.add_argument("--out", default="research/datasets/oran_flooding_v3/reports/model_eval.md")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df = df[df["label"].isin(["BENIGN", POS_LABEL])].copy()
    y = (df["label"] == POS_LABEL).astype(int).to_numpy()
    groups = (df["campaign"].astype(str) + "|" + df["run"].astype(str)
              + "|" + df["supi"].astype(str)).to_numpy()
    n_sessions = len(set(groups))

    skf = StratifiedGroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEED)
    folds = list(skf.split(df, y, groups))

    # results[ablation][model] = {"all": mean_std, "challenge": mean_std, ...}
    results = {}
    fam_recall = {}  # ablation -> model -> family -> [recalls over folds]
    for ab, cols in ABLATIONS.items():
        cols = [c for c in cols if c in df.columns]
        X = df[cols].to_numpy(dtype=float)
        results[ab] = {}
        fam_recall[ab] = {}
        for mname, _ in models().items():
            all_s, chal_s = [], []
            fam_rec = {}
            for tr, te in folds:
                mdl = models()[mname]
                mdl.fit(X[tr], y[tr])
                prob = mdl.predict_proba(X[te])[:, 1]
                pred = (prob >= 0.5).astype(int)
                all_s.append(score(y[te], pred, prob))
                # load-matched challenge subset of this test fold
                band = df.iloc[te]
                m = (band[CHALLENGE_COL] >= CHALLENGE_LO) & (band[CHALLENGE_COL] < CHALLENGE_HI)
                m = m.to_numpy()
                if m.sum() > 0 and len(set(y[te][m])) > 1:
                    chal_s.append(score(y[te][m], pred[m], prob[m]))
                # per-family recall on test (malicious families only)
                te_df = df.iloc[te]
                for fam in sorted(te_df.loc[te_df["label"] == POS_LABEL, "attack_family"].dropna().unique()):
                    fm = (te_df["attack_family"] == fam).to_numpy() & (y[te] == 1)
                    if fm.sum() > 0:
                        fam_rec.setdefault(fam, []).append(recall_score(y[te][fm], pred[fm], pos_label=1, zero_division=0))
            results[ab][mname] = {
                "all": mean_std(all_s),
                "challenge": mean_std(chal_s) if chal_s else None,
            }
            fam_recall[ab][mname] = {f: float(np.mean(v)) for f, v in fam_rec.items()}

    # challenge-set class counts (reported once)
    cm = (df[CHALLENGE_COL] >= CHALLENGE_LO) & (df[CHALLENGE_COL] < CHALLENGE_HI)
    chal_b = int(((y == 0) & cm.to_numpy()).sum())
    chal_m = int(((y == 1) & cm.to_numpy()).sum())

    # ---- report -------------------------------------------------------------
    L = []
    L.append("# Phase L — baseline detection + ablations (dataset v3)\n")
    L.append(f"Records: {len(df)} (BENIGN {(y==0).sum()} / MALICIOUS {(y==1).sum()}) · "
             f"independent sessions: {n_sessions}\n")
    L.append(f"Validation: StratifiedGroupKFold(n_splits={N_SPLITS}) grouped by "
             f"(campaign, run, supi) — no session spans train/test. "
             f"Positive class = MALICIOUS. Metrics = mean±std over folds.\n")
    L.append(f"Load-matched challenge set = test rows with {CHALLENGE_COL} in "
             f"[{CHALLENGE_LO:.0f}, {CHALLENGE_HI:.0f}) kbps "
             f"(BENIGN {chal_b} / MALICIOUS {chal_m}) — the band where both classes are dense.\n")

    def fmt(ms, k):
        m, s = ms[k]
        return f"{m:.3f}±{s:.3f}"

    for split_key, title, note in [
        ("all", "Full test set (all throughput bands)",
         "High scores here can still come from volume; the challenge set below is the real test."),
        ("challenge", "Load-matched challenge set (overlap band only)",
         "THE decisive table: a volume-riding model collapses toward chance here; "
         "a behavioural model holds. This is the answer to 'does it just learn volume?'"),
    ]:
        L.append(f"\n## {title}\n")
        L.append(f"_{note}_\n")
        L.append("| ablation | model | F1 | AUC | recall | precision | bal_acc |")
        L.append("|---|---|---|---|---|---|---|")
        for ab in ABLATIONS:
            for mname in models():
                r = results[ab][mname][split_key]
                if r is None:
                    continue
                L.append(f"| {ab} | {mname} | {fmt(r,'f1')} | {fmt(r,'auc')} | "
                         f"{fmt(r,'recall')} | {fmt(r,'precision')} | {fmt(r,'bal_acc')} |")

    # headline comparison: best model per ablation, full vs challenge F1
    L.append("\n## Headline: F1 drop from full test -> load-matched challenge\n")
    L.append("_If volume-only drops hard while behaviour/full stay up, the model is not just reading volume._\n")
    L.append("| ablation | best model | F1 (full) | F1 (challenge) | AUC (challenge) |")
    L.append("|---|---|---|---|---|")
    for ab in ABLATIONS:
        best_m, best_f1 = None, -1
        for mname in models():
            r = results[ab][mname]["all"]["f1"][0]
            if r > best_f1:
                best_f1, best_m = r, mname
        ch = results[ab][best_m]["challenge"]
        ch_f1 = f"{ch['f1'][0]:.3f}" if ch else "n/a"
        ch_auc = f"{ch['auc'][0]:.3f}" if ch else "n/a"
        L.append(f"| {ab} | {best_m} | {best_f1:.3f} | {ch_f1} | {ch_auc} |")

    # per-family recall (full model, best tree) on full test
    L.append("\n## Per-family recall (full feature set, hist-gbm, full test)\n")
    L.append("_Which attack types the detector catches._\n")
    fr = fam_recall["full"]["hist-gbm"]
    if fr:
        L.append("| family | recall |")
        L.append("|---|---|")
        for fam in sorted(fr):
            L.append(f"| {fam} | {fr[fam]:.3f} |")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    sys.exit(main())
