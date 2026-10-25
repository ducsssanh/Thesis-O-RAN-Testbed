#!/usr/bin/env python3
"""NCSRD -> windows, v2: leakage-free, segment-atomic group split.

Versioned successor to prep_ncsrd.py (v1 is kept unchanged for comparison).
Fixes the leakage found in research/archive/ncsrd-audits/data_leakage_report.md:

  * Windows are built within a `segment` (one UE's contiguous timeline, broken at
    >15 s gaps) exactly as v1.
  * The split assigns WHOLE segments to train or val, so no sliding window ever
    straddles the train/val boundary (v1 split benign by a time quantile, which
    let 73% of val windows overlap a same-UE train window).
  * --split attack  : leave-one-attack-EPISODE-out. val = every segment that
    touches the held-out attack's time window (the whole episode, incl. co-present
    benign), train = all other segments. This is stricter and cleaner than v1.
  * --split ue      : leave-one-UE-out. val = all segments of the held-out UE(s).

Everything else (features, log1p, residual, cell share, scaler-on-train-only) is
identical to v1 so the only changing variable is the split. Labels are still
rebuilt from the schedule, never the leaky `attack`/`malicious` columns.
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

ATTACKERS = {
    1: {"8642840401612300", "8642840401624200"},
    2: {"8642840401612300", "8642840401624200"},
    3: {"8642840401612300", "8642840401624200"},
    4: {"8642840401612300", "8642840401624200"},
    5: {"8642840401612300", "8642840401624200", "8642840401594200",
        "8677660403123800", "3557821101183501"},
}
ATTACK_NAME = {0: "benign", 1: "syn", 2: "icmp", 3: "udp_frag", 4: "dns", 5: "gtpu"}
RATE_COLS = ["ran_ul_kbps", "ran_dl_kbps", "core_ul_kbps", "core_dl_kbps", "cell_ul_kbps"]
OTHER_COLS = ["resid_ul", "resid_dl", "ue_cell_ul_share", "ul_mcs", "dl_mcs",
              "ul_retx", "dl_retx", "ul_err", "dl_err", "cqi", "pusch_snr"]
FEATURES = RATE_COLS + OTHER_COLS
LOAD_COLS = ["_time", "imeisv", "ul_bitrate", "dl_bitrate",
             "bearer_0_ul_total_bytes", "bearer_0_dl_total_bytes",
             "bearer_1_ul_total_bytes", "bearer_1_dl_total_bytes",
             "ul_mcs", "dl_mcs", "ul_retx", "dl_retx", "ul_err", "dl_err",
             "cqi", "pusch_snr", "cell_id", "attack_number"]
GAP_S, STEP_S = 15.0, 5.14


def load(merged):
    df = pd.read_csv(merged, usecols=LOAD_COLS)
    df["imeisv"] = df["imeisv"].astype("Int64").astype(str)
    df["_time"] = pd.to_datetime(df["_time"], errors="coerce")
    df = df.dropna(subset=["_time"]).sort_values(["imeisv", "_time"]).reset_index(drop=True)
    df["attack_number"] = df["attack_number"].fillna(0).astype(int)
    return df


def relabel(df):
    y = np.zeros(len(df), dtype=np.int8)
    for an, devs in ATTACKERS.items():
        y[(df["attack_number"].values == an) & df["imeisv"].isin(devs).values] = 1
    df["y"] = y
    return df


def per_step(df):
    for c in ["bearer_1_ul_total_bytes", "bearer_1_dl_total_bytes"]:
        df[c] = df[c].fillna(0.0)
    df["b_ul"] = df["bearer_0_ul_total_bytes"] + df["bearer_1_ul_total_bytes"]
    df["b_dl"] = df["bearer_0_dl_total_bytes"] + df["bearer_1_dl_total_bytes"]
    g = df.groupby("imeisv", sort=False)
    dt = g["_time"].diff().dt.total_seconds()
    seg_break = dt.isna() | (dt > GAP_S)
    df["segment"] = (df["imeisv"] + ":" + seg_break.cumsum().astype(str))
    dt = dt.where((dt > 0) & (dt <= GAP_S), STEP_S)
    df["dt"] = dt.values
    for src, out in [("b_ul", "core_ul_kbps"), ("b_dl", "core_dl_kbps")]:
        d = g[src].diff(); d = d.where(d >= 0, 0.0)
        df[out] = (d.values / df["dt"].values) * 8.0 / 1000.0
        df.loc[seg_break.values, out] = 0.0
    df["ran_ul_kbps"] = df["ul_bitrate"] / 1000.0
    df["ran_dl_kbps"] = df["dl_bitrate"] / 1000.0
    df["resid_ul"] = (df["ran_ul_kbps"] - df["core_ul_kbps"]) / (df["core_ul_kbps"] + 1.0)
    df["resid_dl"] = (df["ran_dl_kbps"] - df["core_dl_kbps"]) / (df["core_dl_kbps"] + 1.0)
    return df


def cell_share(df):
    df["bucket"] = df["_time"].dt.floor("5s")
    cell_ul = df.groupby(["cell_id", "bucket"])["ran_ul_kbps"].transform("sum")
    df["cell_ul_kbps"] = cell_ul.values
    df["ue_cell_ul_share"] = df["ran_ul_kbps"].values / np.maximum(cell_ul.values, 1e-6)
    return df


def windows(df, w):
    feat = df[FEATURES].astype(np.float32)
    for c in RATE_COLS:
        feat[c] = np.log1p(feat[c].clip(lower=0))
    feat = feat.fillna(0.0).values
    y, an = df["y"].values, df["attack_number"].values
    im, cell, share = df["imeisv"].values, df["cell_id"].values, df["ue_cell_ul_share"].values
    seg = df["segment"].values
    t = (df["_time"].astype("int64") // 10**9).values
    Xs, ys, ans, ims, cs, shs, ts, sgs = ([] for _ in range(8))
    for _, idx in df.groupby("segment", sort=False).indices.items():
        idx = np.sort(idx)
        if len(idx) < w:
            continue
        fseg = feat[idx]
        for i in range(w - 1, len(idx)):
            j = idx[i]
            Xs.append(fseg[i - w + 1:i + 1])
            ys.append(y[j]); ans.append(an[j]); ims.append(im[j])
            cs.append(cell[j]); shs.append(share[j]); ts.append(t[j]); sgs.append(seg[j])
    return (np.asarray(Xs, np.float32), np.asarray(ys, np.int8), np.asarray(ans, np.int16),
            np.asarray(ims), np.asarray(cs, np.float32), np.asarray(shs, np.float32),
            np.asarray(ts, np.int64), np.asarray(sgs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=6)
    ap.add_argument("--split", choices=["attack", "ue"], default="attack")
    ap.add_argument("--val-attack", type=int, default=4, help="held-out attack_number (split=attack)")
    ap.add_argument("--val-ue", default="8642840401612300", help="held-out imeisv (split=ue)")
    args = ap.parse_args()
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)

    df = cell_share(per_step(relabel(load(args.merged))))
    X, y, an, im, cell, share, t, seg = windows(df, args.window)
    if len(X) == 0:
        sys.exit("no windows built")

    # segment-atomic split: whole segments go to one side (no window straddles)
    if args.split == "attack":
        k = args.val_attack
        seg_touch = {s for s in np.unique(seg[an == k])}      # segments in the held-out episode
        val = np.array([s in seg_touch for s in seg])
        held = ATTACK_NAME.get(k)
    else:
        val = (im == args.val_ue)
        held = f"ue:{args.val_ue}"
    train = ~val
    if val.sum() == 0 or train.sum() == 0:
        sys.exit("degenerate split")

    flat = X[train].reshape(-1, X.shape[2])
    mean, std = flat.mean(0), flat.std(0); std[std < 1e-6] = 1.0
    Xs = (X - mean) / std

    # leakage self-check: no segment appears on both sides
    cross = len(set(seg[train].tolist()) & set(seg[val].tolist()))
    meta = {
        "dataset": "NCSRD-DS-5GDDoS", "prep": "v2-segment-atomic", "windows": int(len(X)),
        "window_steps": args.window, "step_seconds_nominal": STEP_S,
        "features": FEATURES, "n_features": len(FEATURES),
        "split": args.split, "held_out": held,
        "label": "per-attacker from schedule (attack_number x attacking IMEISV)",
        "positives": int(y.sum()), "positive_rate": round(float(y.mean()), 5),
        "train_windows": int(train.sum()), "val_windows": int(val.sum()),
        "train_positives": int(y[train].sum()), "val_positives": int(y[val].sum()),
        "train_segments": int(len(set(seg[train].tolist()))),
        "val_segments": int(len(set(seg[val].tolist()))),
        "segments_on_both_sides": cross,   # MUST be 0
        "train_UEs": sorted(set(im[train].tolist())), "val_UEs": sorted(set(im[val].tolist())),
        "by_attack": {ATTACK_NAME[int(kk)]: int((an == kk).sum()) for kk in sorted(set(an.tolist()))},
        "scaler_mean": mean.tolist(), "scaler_std": std.tolist(),
    }
    np.savez_compressed(out / "windows.npz",
        X_train=Xs[train], y_train=y[train], X_val=Xs[val], y_val=y[val],
        an_train=an[train], an_val=an[val], share_train=share[train], share_val=share[val],
        imeisv_train=im[train], imeisv_val=im[val], seg_train=seg[train], seg_val=seg[val],
        t_train=t[train], t_val=t[val], mean=mean, std=std)
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: v for k, v in meta.items()
                      if k not in ("scaler_mean", "scaler_std", "features", "train_UEs", "val_UEs")}, indent=2))
    print("segments_on_both_sides =", cross, "(must be 0)")
    print("written", out / "windows.npz")


if __name__ == "__main__":
    main()
