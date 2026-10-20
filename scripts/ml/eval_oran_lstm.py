#!/usr/bin/env python3
"""Phase L — temporal (LSTM) baseline on the O-RAN flooding dataset.

Same leakage-aware protocol as eval_oran_models.py, but a sequence model:
  - Each independent session = (campaign, run, supi) is a time series of
    per-second rows (sorted by t_unix).
  - Sliding windows of length W within a session; window label = label of its
    LAST timestep (online causal setting). Windows never cross sessions.
  - GroupKFold by session -> no session in both train and test (no leakage).
  - Scaler fit on TRAIN only. NaN -> 0 (absence = no activity, confirmed
    leak-free by the build's missingness audit).
  - Reported on the full test and on the LOAD-MATCHED challenge subset
    (windows whose last step has thp_ul_kbps in the overlap band), to match the
    tree eval's decisive test.

Two feature sets, to localise the signal the same way the tree ablations do:
  - full      : all online numeric features
  - bytes-only: pure byte-rate counters (the "is it just volume?" control)

CPU-only, a few minutes.
"""
import argparse
import pathlib
import sys
import warnings

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, roc_auc_score, balanced_accuracy_score, recall_score, precision_score

warnings.filterwarnings("ignore")
torch.manual_seed(13)
np.random.seed(13)

BYTES = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
         "urr_ul_kbps", "urr_dl_kbps", "prof_ul_kbps", "prof_dl_kbps"]
FULL = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
        "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct",
        "urr_ul_kbps", "urr_dl_kbps", "urr_ul_pps", "urr_dl_pps",
        "prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps",
        "prof_ul_mean_bytes", "prof_dl_mean_bytes",
        "prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp",
        "prof_ul_frag", "prof_ul_dns", "prof_ul_gtp_in_gtp",
        "prof_dl_tcp", "prof_dl_tcp_syn", "prof_dl_udp", "prof_dl_icmp",
        "prof_dl_frag", "prof_ul_dst_estimate"]
FEATURE_SETS = {"full": FULL, "bytes-only": BYTES}

W = 8                 # window length (seconds)
CHALLENGE_LO, CHALLENGE_HI = 300.0, 1000.0
N_SPLITS = 5
EPOCHS = 14
POS = "MALICIOUS"


class LSTMClf(nn.Module):
    def __init__(self, n_feat, hidden=48):
        super().__init__()
        self.lstm = nn.LSTM(n_feat, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


def make_windows(df, cols):
    """Return X (N,W,F), y (N,), thp_last (N,), group (N,)."""
    X, y, thp, grp = [], [], [], []
    sid = df["campaign"].astype(str) + "|" + df["run"].astype(str) + "|" + df["supi"].astype(str)
    for s, idx in df.groupby(sid).groups.items():
        g = df.loc[idx].sort_values("t_unix")
        feats = g[cols].to_numpy(dtype=float)
        feats = np.nan_to_num(feats, nan=0.0)
        lab = (g["label"].to_numpy() == POS).astype(int)
        thpv = g["thp_ul_kbps"].to_numpy(dtype=float)
        for i in range(len(g) - W + 1):
            X.append(feats[i:i + W])
            y.append(lab[i + W - 1])
            thp.append(thpv[i + W - 1])
            grp.append(s)
    return np.asarray(X, dtype=np.float32), np.asarray(y), np.asarray(thp), np.asarray(grp)


def scores(yt, yp, pr):
    d = {"f1": f1_score(yt, yp, zero_division=0),
         "precision": precision_score(yt, yp, zero_division=0),
         "recall": recall_score(yt, yp, zero_division=0),
         "bal_acc": balanced_accuracy_score(yt, yp),
         "auc": roc_auc_score(yt, pr) if len(set(yt)) > 1 else float("nan")}
    return d


def run_fold(Xtr, ytr, Xte, yte, n_feat):
    sc = StandardScaler().fit(Xtr.reshape(-1, n_feat))
    tr = sc.transform(Xtr.reshape(-1, n_feat)).reshape(Xtr.shape).astype(np.float32)
    te = sc.transform(Xte.reshape(-1, n_feat)).reshape(Xte.shape).astype(np.float32)
    dev = "cpu"
    mdl = LSTMClf(n_feat).to(dev)
    pos_w = torch.tensor([(ytr == 0).sum() / max((ytr == 1).sum(), 1)], dtype=torch.float32)
    lossf = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    opt = torch.optim.Adam(mdl.parameters(), lr=1e-3)
    Xt = torch.tensor(tr); yt = torch.tensor(ytr, dtype=torch.float32)
    n = len(Xt); bs = 256
    for _ in range(EPOCHS):
        mdl.train(); perm = torch.randperm(n)
        for i in range(0, n, bs):
            b = perm[i:i + bs]
            opt.zero_grad()
            out = mdl(Xt[b])
            loss = lossf(out, yt[b])
            loss.backward(); opt.step()
    mdl.eval()
    with torch.no_grad():
        logits = mdl(torch.tensor(te))
        prob = torch.sigmoid(logits).numpy()
    return prob


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="research/datasets/oran_flooding_v3/synchronized/records.csv")
    ap.add_argument("--out", default="research/datasets/oran_flooding_v3/reports/model_eval_lstm.md")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df = df[df["label"].isin(["BENIGN", POS])].copy()

    L = ["# Phase L — temporal LSTM baseline (dataset v3)\n",
         f"Window = {W}s, label = last step. GroupKFold({N_SPLITS}) by "
         f"(campaign, run, supi); scaler fit on train only. CPU. Metrics = mean±std.\n",
         f"Challenge subset = windows whose last step has thp_ul_kbps in "
         f"[{CHALLENGE_LO:.0f},{CHALLENGE_HI:.0f}) kbps.\n",
         "| feature set | split | F1 | AUC | recall | precision | bal_acc |",
         "|---|---|---|---|---|---|---|"]

    for fs_name, cols in FEATURE_SETS.items():
        X, y, thp, grp = make_windows(df, cols)
        gkf = GroupKFold(n_splits=N_SPLITS)
        all_s, chal_s = [], []
        for tr, te in gkf.split(X, y, grp):
            prob = run_fold(X[tr], y[tr], X[te], y[te], len(cols))
            pred = (prob >= 0.5).astype(int)
            all_s.append(scores(y[te], pred, prob))
            m = (thp[te] >= CHALLENGE_LO) & (thp[te] < CHALLENGE_HI)
            if m.sum() > 0 and len(set(y[te][m])) > 1:
                chal_s.append(scores(y[te][m], pred[m], prob[m]))

        def ms(ds, k):
            return float(np.nanmean([d[k] for d in ds])), float(np.nanstd([d[k] for d in ds]))

        for split_name, ds in [("full-test", all_s), ("challenge", chal_s)]:
            if not ds:
                continue
            row = " | ".join(f"{ms(ds,k)[0]:.3f}±{ms(ds,k)[1]:.3f}"
                             for k in ["f1", "auc", "recall", "precision", "bal_acc"])
            L.append(f"| {fs_name} | {split_name} | {row} |")
        print(f"done {fs_name}: windows={len(X)} pos={int(y.sum())}")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    sys.exit(main())
