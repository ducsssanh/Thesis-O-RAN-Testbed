#!/usr/bin/env python3
"""NCSRD -> windows, v3 = v2 (leakage-free, segment-atomic) + Feature Set B:
cell-level PRB-utilisation context joined from enb_counters.

Adds 4 CELL-level context features (not per-UE PRB, which NCSRD lacks -- see
research/audits/prb_feature_investigation.md): cell_ul_use, cell_dl_use,
cell_ul_sched_users, cell_ue_active. Joined by time (merge_asof) for the UE's
cell_id. cell_id==2 has no enb counter column -> filled 0 (documented).

  .venv-ml/bin/python -I scripts/ml/prep_ncsrd_v3.py \
      --merged data/NCSRD_5GDDOS_V3/amari_ue_data_merged_with_attack_number.csv \
      --enb data/NCSRD_5GDDOS_V3/enb_counters_data_classic_tabular.csv \
      --out artifacts/ml/ncsrd-v3-dns --split attack --val-attack 4
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import prep_ncsrd_v2 as v2

CELL_FEATS = ["cell_ul_use", "cell_dl_use", "cell_ul_sched_users", "cell_ue_active"]


def join_enb(df, enb_path):
    cols = {}
    for c in [1, 3]:
        cols[c] = {f"cell_{c}_ul_use_avg": "cell_ul_use", f"cell_{c}_dl_use_avg": "cell_dl_use",
                   f"cell_{c}_ul_sched_users_avg": "cell_ul_sched_users",
                   f"cell_{c}_ue_active_count_avg": "cell_ue_active"}
    use = ["_time"] + [k for c in cols for k in cols[c]]
    e = pd.read_csv(enb_path, usecols=use)
    e["_time"] = pd.to_datetime(e["_time"], errors="coerce", utc=True).dt.tz_localize(None)
    e = e.dropna(subset=["_time"]).sort_values("_time")
    for f in CELL_FEATS:
        df[f] = 0.0
    df = df.sort_values("_time").reset_index(drop=True)
    for c in [1, 3]:
        sub = e[["_time"] + list(cols[c])].rename(columns=cols[c]).sort_values("_time")
        m = pd.merge_asof(df[["_time"]].reset_index(), sub, on="_time",
                          direction="nearest", tolerance=pd.Timedelta("6s"))
        sel = (df["cell_id"].values == c)
        for f in CELL_FEATS:
            vals = m[f].values
            df.loc[sel, f] = np.nan_to_num(vals[sel], nan=0.0)
    return df.sort_values(["imeisv", "_time"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--enb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=6)
    ap.add_argument("--split", choices=["attack", "ue"], default="attack")
    ap.add_argument("--val-attack", type=int, default=4)
    ap.add_argument("--val-ue", default="8642840401612300")
    args = ap.parse_args()
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)

    df = v2.load(args.merged)
    df = v2.relabel(df)
    df = v2.per_step(df)
    df = v2.cell_share(df)
    df = join_enb(df, args.enb)

    # extend the feature list seen by v2.windows (cell-use are not rates -> no log1p)
    v2.FEATURES = v2.RATE_COLS + v2.OTHER_COLS + CELL_FEATS
    X, y, an, im, cell, share, t, seg = v2.windows(df, args.window)
    if len(X) == 0:
        sys.exit("no windows")

    if args.split == "attack":
        seg_touch = {s for s in np.unique(seg[an == args.val_attack])}
        val = np.array([s in seg_touch for s in seg]); held = v2.ATTACK_NAME.get(args.val_attack)
    else:
        val = (im == args.val_ue); held = f"ue:{args.val_ue}"
    train = ~val
    flat = X[train].reshape(-1, X.shape[2]); mean, std = flat.mean(0), flat.std(0); std[std < 1e-6] = 1.0
    Xs = (X - mean) / std
    cross = len(set(seg[train].tolist()) & set(seg[val].tolist()))
    meta = {"dataset": "NCSRD-DS-5GDDoS", "prep": "v3-featureB-cellPRB",
            "features": v2.FEATURES, "n_features": len(v2.FEATURES),
            "split": args.split, "held_out": held,
            "train_windows": int(train.sum()), "val_windows": int(val.sum()),
            "train_positives": int(y[train].sum()), "val_positives": int(y[val].sum()),
            "segments_on_both_sides": cross,
            "added_features": CELL_FEATS, "note": "cell-level context, not per-UE PRB; cell_id==2 -> 0",
            "scaler_mean": mean.tolist(), "scaler_std": std.tolist()}
    np.savez_compressed(out / "windows.npz",
        X_train=Xs[train], y_train=y[train], X_val=Xs[val], y_val=y[val],
        an_train=an[train], an_val=an[val], share_train=share[train], share_val=share[val],
        imeisv_train=im[train], imeisv_val=im[val], seg_train=seg[train], seg_val=seg[val],
        t_train=t[train], t_val=t[val], mean=mean, std=std)
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: v for k, v in meta.items() if k not in ("scaler_mean", "scaler_std", "features")}, indent=2))
    print("segments_on_both_sides =", cross)


if __name__ == "__main__":
    main()
