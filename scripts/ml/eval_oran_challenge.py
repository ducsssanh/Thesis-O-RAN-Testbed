#!/usr/bin/env python3
"""Volume-matched challenge — a STRICT control for "behaviour vs volume".

The v3 eval's "load-matched" set only bands thp_ul_kbps, so volume-only still wins
(other volume axes differ). This builds a genuinely volume-matched test set:
1-NN matching of each malicious test row to a benign test row on the standardised
MULTI-AXIS volume vector (rates+pps across KPM/URR/profiler, +PRB) within a
caliper. On that set the classes have ~identical volume, so:
  - a VOLUME-ONLY model must fall toward chance (AUC ~0.5) if matching worked;
  - NORMALISED BEHAVIOUR (protocol *shares* = pkt-type/total-pps, + mean packet
    size, + fan-out) is volume-invariant; if it stays high, separation is
    genuinely behavioural, not volumetric.

Leakage-aware: StratifiedGroupKFold by (campaign,run,supi); scaler/matching fit on
TRAIN stats; matching applied within each test fold; predictions pooled.

  .venv-ml/bin/python -I scripts/ml/eval_oran_challenge.py --data research/datasets/oran_flooding_v3
"""
import argparse, json, pathlib, warnings
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.neighbors import NearestNeighbors
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import roc_auc_score, f1_score, balanced_accuracy_score
warnings.filterwarnings("ignore")

VOLUME = ["rate_ul_kbps","rate_dl_kbps","thp_ul_kbps","thp_dl_kbps",
          "prb_ul_pct","prb_dl_pct","cell_prb_ul_pct","cell_prb_dl_pct",
          "urr_ul_kbps","urr_dl_kbps","urr_ul_pps","urr_dl_pps",
          "prof_ul_kbps","prof_dl_kbps","prof_ul_pps","prof_dl_pps"]
MATCH = list(VOLUME)   # match on ALL volume/PRB axes so volume carries ~no marginal signal
PROTO = ["prof_ul_tcp","prof_ul_tcp_syn","prof_ul_udp","prof_ul_icmp",
         "prof_ul_frag","prof_ul_dns","prof_ul_gtp_in_gtp"]


def behaviour_norm(df):
    """Volume-invariant behaviour: protocol shares + mean pkt size + fan-out."""
    tot = df["prof_ul_pps"].to_numpy(float)
    tot = np.where(tot > 1e-6, tot, np.nan)
    out = {f"share_{c}": df[c].to_numpy(float) / tot for c in PROTO}
    out["mean_bytes_ul"] = df["prof_ul_mean_bytes"].to_numpy(float)
    out["mean_bytes_dl"] = df["prof_dl_mean_bytes"].to_numpy(float)
    out["dst_estimate"] = df["prof_ul_dst_estimate"].to_numpy(float)
    X = pd.DataFrame(out)
    return X.fillna(0.0).to_numpy()


def fit_score(Xtr, ytr, Xte):
    m = np.nanmean(Xtr, 0); s = np.nanstd(Xtr, 0); s[s < 1e-9] = 1.0
    clf = HistGradientBoostingClassifier(max_iter=300, class_weight="balanced", random_state=0)
    clf.fit(np.nan_to_num((Xtr - m) / s), ytr)
    return clf.predict_proba(np.nan_to_num((Xte - m) / s))[:, 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--caliper", type=float, default=0.5, help="max std L2 dist for a match")
    args = ap.parse_args()
    root = pathlib.Path(args.data)
    df = pd.read_csv(root / "synchronized" / "records.csv")
    df = df[df["label"].isin(["BENIGN", "MALICIOUS"])].reset_index(drop=True)
    y = (df["label"] == "MALICIOUS").astype(int).to_numpy()
    groups = (df["campaign"] + "|" + df["run"].astype(str) + "|" + df["supi"].astype(str)).to_numpy()
    Vol = df[VOLUME].to_numpy(float)
    Mat = df[MATCH].to_numpy(float)
    Beh = behaviour_norm(df)

    skf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=0)
    pooled = {k: {"y": [], "p": []} for k in ("vol_full", "beh_full", "vol_match", "beh_match")}
    match_quality = []
    for tr, te in skf.split(Vol, y, groups):
        # train on full train fold
        p_vol = fit_score(Vol[tr], y[tr], Vol[te])
        p_beh = fit_score(Beh[tr], y[tr], Beh[te])
        for k, p in (("vol_full", p_vol), ("beh_full", p_beh)):
            pooled[k]["y"].append(y[te]); pooled[k]["p"].append(p)
        # volume-matched subset within the TEST fold (scale by train stats)
        m = np.nanmean(Mat[tr], 0); s = np.nanstd(Mat[tr], 0); s[s < 1e-9] = 1.0
        Z = np.nan_to_num((Mat[te] - m) / s)
        yte = y[te]
        bi = np.where(yte == 0)[0]; mi = np.where(yte == 1)[0]
        if len(bi) == 0 or len(mi) == 0:
            continue
        nn = NearestNeighbors(n_neighbors=min(5, len(bi))).fit(Z[bi])
        dist, idx = nn.kneighbors(Z[mi])
        used = set(); keep_m = []; keep_b = []
        for row_m, (ds, ix) in enumerate(zip(dist, idx)):
            for d, j in zip(ds, ix):
                if d <= args.caliper and bi[j] not in used:
                    used.add(bi[j]); keep_m.append(mi[row_m]); keep_b.append(bi[j]); break
        if not keep_m:
            continue
        sel = np.array(keep_m + keep_b)
        # residual volume imbalance after matching (mean |std diff| across MATCH axes)
        md = np.abs(Z[keep_m].mean(0) - Z[keep_b].mean(0)).mean()
        match_quality.append((len(keep_m), md))
        for k, p in (("vol_match", p_vol), ("beh_match", p_beh)):
            pooled[k]["y"].append(yte[sel]); pooled[k]["p"].append(p[sel])

    def agg(k):
        yy = np.concatenate(pooled[k]["y"]); pp = np.concatenate(pooled[k]["p"])
        return {"n": int(len(yy)), "pos": int(yy.sum()),
                "AUC": round(roc_auc_score(yy, pp), 4) if yy.any() and not yy.all() else None,
                "F1@0.5": round(f1_score(yy, pp >= 0.5), 4),
                "bal_acc@0.5": round(balanced_accuracy_score(yy, pp >= 0.5), 4)}

    npairs = int(sum(n for n, _ in match_quality))
    res = {"caliper": args.caliper, "matched_pairs_total": npairs,
           "residual_volume_imbalance_std_mean": round(float(np.mean([d for _, d in match_quality])), 4) if match_quality else None,
           "volume_only": {"full_test": agg("vol_full"), "volume_matched": agg("vol_match")},
           "behaviour_norm": {"full_test": agg("beh_full"), "volume_matched": agg("beh_match")}}
    out = root / "reports" / "challenge_volume_matched.json"
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    print("\nINTERPRETATION:")
    vm = res["volume_only"]["volume_matched"]["AUC"]; bm = res["behaviour_norm"]["volume_matched"]["AUC"]
    print(f"  volume-only on volume-matched set: AUC {vm}  (want ~0.5 if matching neutralised volume)")
    print(f"  behaviour-norm on volume-matched set: AUC {bm}  (want >>0.5 if separation is behavioural)")


if __name__ == "__main__":
    main()
