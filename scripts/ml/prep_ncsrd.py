#!/usr/bin/env python3
"""Preprocess NCSRD-DS-5GDDoS into per-UE time-series windows for the LSTM.

  .venv-ml/bin/python -I scripts/ml/prep_ncsrd.py \
      --merged data/NCSRD_5GDDOS_V3/amari_ue_data_merged_with_attack_number.csv \
      --out artifacts/ml/ncsrd

What it produces and why (docs/AI-DEFENSE-MODEL-DESIGN.md, CLOSED-LOOP-FRAMEWORK.md):

- Labels are rebuilt from the attack schedule (summary_report.xlsx), not the
  dataset's `attack` / `malicious` columns. `attack` is set for every UE in an
  attack's time window and `malicious` is a static per-device flag, so both
  mark idle malicious devices and benign UEs as positive. A sample is positive
  only when its device is one that actually attacked in that attack
  (attack_number -> attacking IMEISVs below).

- Each UE has two volume sources, like the testbed's KPM and URR: `ul_bitrate`
  / `dl_bitrate` (the RAN's view) and the bearer byte counters (the core's
  view, differenced over the sample period). Their relative difference is kept
  as `resid_ul` / `resid_dl`, the NCSRD analogue of the KPM<->URR residual, so
  a model trained here already uses a consistency feature.

- The rank the thesis wants (safety x volume) is not a training target: the
  LSTM predicts p_attack, and the rank is p_attack x the UE's share of its
  cell's uplink volume. `ue_cell_ul_share` is saved per window so the rank can
  be formed at inference and evaluated.

Output (npz + json): windows X [n, W, F], labels y [n], and per-window meta
(attack_number for leave-one-attack-out splits, imeisv, cell, time, the cell
share). The scaler is fit on the training split only.

NCSRD has no per-UE packet-mix counters (SYN/ICMP/... shares); those exist only
in the testbed. A model pretrained here uses the shared features and is
fine-tuned on testbed data, where the packet-mix columns are added.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import pandas as pd

# attack_number -> IMEISVs that actually attacked (summary_report.xlsx).
# Attacks 1-4 (SYN, ICMP, UDP-frag, DNS): 10.20.10.2 and .4 only. Attack 5
# (GTP-U): all five malicious devices.
ATTACKERS = {
    1: {"8642840401612300", "8642840401624200"},
    2: {"8642840401612300", "8642840401624200"},
    3: {"8642840401612300", "8642840401624200"},
    4: {"8642840401612300", "8642840401624200"},
    5: {"8642840401612300", "8642840401624200", "8642840401594200",
        "8677660403123800", "3557821101183501"},
}
ATTACK_NAME = {0: "benign", 1: "syn", 2: "icmp", 3: "udp_frag", 4: "dns", 5: "gtpu"}

# Per-step features mapped onto the xApp vector. Rates are log1p'd (they span
# zero to tens of Mbit/s); the rest are standardised as-is.
RATE_COLS = ["ran_ul_kbps", "ran_dl_kbps", "core_ul_kbps", "core_dl_kbps", "cell_ul_kbps"]
OTHER_COLS = ["resid_ul", "resid_dl", "ue_cell_ul_share", "ul_mcs", "dl_mcs",
              "ul_retx", "dl_retx", "ul_err", "dl_err", "cqi", "pusch_snr"]
FEATURES = RATE_COLS + OTHER_COLS

LOAD_COLS = ["_time", "imeisv", "ul_bitrate", "dl_bitrate",
             "bearer_0_ul_total_bytes", "bearer_0_dl_total_bytes",
             "bearer_1_ul_total_bytes", "bearer_1_dl_total_bytes",
             "ul_mcs", "dl_mcs", "ul_retx", "dl_retx", "ul_err", "dl_err",
             "cqi", "pusch_snr", "cell_id", "attack_number"]

GAP_S = 15.0        # a step gap above this starts a new segment (session break)
STEP_S = 5.14       # nominal sample period, for rates when a step is isolated


def load(merged):
    df = pd.read_csv(merged, usecols=LOAD_COLS)
    df["imeisv"] = df["imeisv"].astype("Int64").astype(str)
    df["_time"] = pd.to_datetime(df["_time"], errors="coerce")
    df = df.dropna(subset=["_time"]).sort_values(["imeisv", "_time"]).reset_index(drop=True)
    df["attack_number"] = df["attack_number"].fillna(0).astype(int)
    return df


def relabel(df):
    """Per-attacker label from the schedule (not the dataset's columns)."""
    y = np.zeros(len(df), dtype=np.int8)
    for an, devs in ATTACKERS.items():
        y[(df["attack_number"].values == an) & df["imeisv"].isin(devs).values] = 1
    df["y"] = y
    return df


def per_step(df):
    """dt, segment ids, two volume sources, residuals, per the sample period."""
    for c in ["bearer_1_ul_total_bytes", "bearer_1_dl_total_bytes"]:
        df[c] = df[c].fillna(0.0)
    df["b_ul"] = df["bearer_0_ul_total_bytes"] + df["bearer_1_ul_total_bytes"]
    df["b_dl"] = df["bearer_0_dl_total_bytes"] + df["bearer_1_dl_total_bytes"]
    g = df.groupby("imeisv", sort=False)
    dt = g["_time"].diff().dt.total_seconds()
    # new segment at a gap or the first row of a UE
    seg_break = dt.isna() | (dt > GAP_S)
    df["segment"] = (df["imeisv"] + ":" + seg_break.cumsum().astype(str))
    dt = dt.where((dt > 0) & (dt <= GAP_S), STEP_S)
    df["dt"] = dt.values
    # core view: bearer byte counters differenced over the period (bit/s -> kbit/s)
    for src, out in [("b_ul", "core_ul_kbps"), ("b_dl", "core_dl_kbps")]:
        d = g[src].diff()
        d = d.where(d >= 0, 0.0)  # counter reset / reattach
        df[out] = (d.values / df["dt"].values) * 8.0 / 1000.0
        df.loc[seg_break.values, out] = 0.0
    # RAN view (bit/s -> kbit/s)
    df["ran_ul_kbps"] = df["ul_bitrate"] / 1000.0
    df["ran_dl_kbps"] = df["dl_bitrate"] / 1000.0
    # consistency residual (RAN vs core), the KPM<->URR analogue
    df["resid_ul"] = (df["ran_ul_kbps"] - df["core_ul_kbps"]) / (df["core_ul_kbps"] + 1.0)
    df["resid_dl"] = (df["ran_dl_kbps"] - df["core_dl_kbps"]) / (df["core_dl_kbps"] + 1.0)
    return df


def cell_share(df):
    """UE share of its cell's uplink in the same 5 s bucket (for the rank)."""
    df["bucket"] = df["_time"].dt.floor("5s")
    cell_ul = df.groupby(["cell_id", "bucket"])["ran_ul_kbps"].transform("sum")
    df["cell_ul_kbps"] = cell_ul.values
    df["ue_cell_ul_share"] = df["ran_ul_kbps"].values / np.maximum(cell_ul.values, 1e-6)
    return df


def windows(df, w):
    """Sliding windows of length w within each segment; label = last step."""
    feat = df[FEATURES].astype(np.float32)
    for c in RATE_COLS:
        feat[c] = np.log1p(feat[c].clip(lower=0))
    feat = feat.fillna(0.0).values
    y = df["y"].values
    an = df["attack_number"].values
    imeisv = df["imeisv"].values
    cell = df["cell_id"].values
    share = df["ue_cell_ul_share"].values
    t = (df["_time"].astype("int64") // 10**9).values
    Xs, ys, ans, ims, cs, shs, ts = [], [], [], [], [], [], []
    for _, idx in df.groupby("segment", sort=False).indices.items():
        idx = np.sort(idx)
        if len(idx) < w:
            continue
        fseg = feat[idx]
        for i in range(w - 1, len(idx)):
            j = idx[i]
            Xs.append(fseg[i - w + 1:i + 1])
            ys.append(y[j]); ans.append(an[j]); ims.append(imeisv[j])
            cs.append(cell[j]); shs.append(share[j]); ts.append(t[j])
    return (np.asarray(Xs, np.float32), np.asarray(ys, np.int8), np.asarray(ans, np.int16),
            np.asarray(ims), np.asarray(cs, np.float32), np.asarray(shs, np.float32), np.asarray(ts, np.int64))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=6, help="steps per window (6 = 30 s at 5 s)")
    ap.add_argument("--val-attack", type=int, default=4,
                    help="attack_number held out for validation (leave-one-attack-out); 0 = time split")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = load(args.merged)
    df = relabel(df)
    df = per_step(df)
    df = cell_share(df)
    X, y, an, im, cell, share, t = windows(df, args.window)
    if len(X) == 0:
        sys.exit("no windows built")

    # Split: validation = the held-out attack's windows plus a time-tail slice
    # of benign windows (so the benign class is represented in both splits).
    if args.val_attack:
        val_attack = (an == args.val_attack)
        benign = (an == 0)
        tcut = np.quantile(t[benign], 0.8) if benign.any() else t.max()
        val = val_attack | (benign & (t >= tcut))
    else:
        tcut = np.quantile(t, 0.8)
        val = t >= tcut
    train = ~val

    # Scale: fit on the training split only
    flat = X[train].reshape(-1, X.shape[2])
    mean = flat.mean(0)
    std = flat.std(0)
    std[std < 1e-6] = 1.0
    Xs = (X - mean) / std

    meta = {
        "dataset": "NCSRD-DS-5GDDoS", "windows": int(len(X)), "window_steps": args.window,
        "step_seconds_nominal": STEP_S, "features": FEATURES, "n_features": len(FEATURES),
        "label": "per-attacker from schedule (attack_number x attacking IMEISV)",
        "positives": int(y.sum()), "positive_rate": round(float(y.mean()), 5),
        "val_attack": args.val_attack, "val_attack_name": ATTACK_NAME.get(args.val_attack),
        "train_windows": int(train.sum()), "val_windows": int(val.sum()),
        "train_positives": int(y[train].sum()), "val_positives": int(y[val].sum()),
        "by_attack": {ATTACK_NAME[k]: int((an == k).sum()) for k in sorted(set(an.tolist()))},
        "scaler_mean": mean.tolist(), "scaler_std": std.tolist(),
        "rank": "risk = p_attack * ue_cell_ul_share (saved per window)",
        "note": "no per-UE packet-mix features in NCSRD; added only for testbed fine-tuning",
    }
    np.savez_compressed(out / "windows.npz",
                        X_train=Xs[train], y_train=y[train], X_val=Xs[val], y_val=y[val],
                        an_train=an[train], an_val=an[val], share_train=share[train], share_val=share[val],
                        imeisv_train=im[train], imeisv_val=im[val], cell_train=cell[train], cell_val=cell[val],
                        t_train=t[train], t_val=t[val], mean=mean, std=std)
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({k: v for k, v in meta.items() if k not in ("scaler_mean", "scaler_std", "features")}, indent=2))
    print("written", out / "windows.npz", "and", out / "meta.json")


if __name__ == "__main__":
    main()
