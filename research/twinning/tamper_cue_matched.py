#!/usr/bin/env python3
"""Tamper cue test that asks the right question. Scaling a rate moves its level, and any classifier sees a level shift, so AUC of 0.5 against unmatched honest seconds is impossible by construction. Here honest seconds are resampled to the same UL rate
distribution as the tampered ones, per bin of log rate: what is left is a cue of the injection itself. Control: factor 1 must give 0.5. Compares the linear PRB of tamper_replay with PRB drawn from honest seconds of the tampered rate. Usage: tamper_cue_matched.py <rows.parquet>"""
import os, sys
os.environ.setdefault("OMP_NUM_THREADS", "2")
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier as HGB
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
K = ["rate_ul_kbps", "rate_dl_kbps", "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
df = pd.read_parquet(sys.argv[1]).dropna(subset=K)
df = df[df.rate_ul_kbps > 0].reset_index(drop=True)
EDGES = np.geomspace(.1, 8000, 41)
B = lambda r: np.searchsorted(EDGES, r)
x, y = df.rate_ul_kbps.to_numpy(), df.prb_ul_pct.to_numpy()
bins = {b: y[B(x) == b] for b in np.unique(B(x))}


def scale(d, f, prb, rng):
    d = d.copy()
    r = np.round(d.rate_ul_kbps.to_numpy() * f / .008) * .008
    if prb == "linear":
        new = np.minimum(np.round(d.prb_ul_pct.to_numpy() * f), 100.0)
    else:
        new = np.array([rng.choice(bins[b]) if b in bins else min(round(p * f), 100.0) for b, p in zip(B(r), d.prb_ul_pct.to_numpy())], float)
    d["cell_prb_ul_pct"] = np.clip(d.cell_prb_ul_pct.to_numpy() + new - d.prb_ul_pct.to_numpy(), 0, 100)
    d["rate_ul_kbps"], d["prb_ul_pct"] = r, new
    return d


def test(h, f, prb, cols=K, seed=0):
    rng = np.random.default_rng(seed)
    ep = h.groupby(["run_id", "phase", "supi"]).ngroup().to_numpy()
    u = np.unique(ep); tam = np.isin(ep, rng.permutation(u)[:len(u) // 2])
    t, o = scale(h[tam], f, prb, rng), h[~tam]
    bt, bo = B(t.rate_ul_kbps.to_numpy()), B(o.rate_ul_kbps.to_numpy())
    keep_t, keep_o = [], []
    for b in np.intersect1d(bt, bo):
        i, j = np.flatnonzero(bt == b), np.flatnonzero(bo == b)
        n = min(len(i), len(j))
        keep_t.append(rng.choice(i, n, replace=False)); keep_o.append(rng.choice(j, n, replace=False))
    t, o = t.iloc[np.concatenate(keep_t)], o.iloc[np.concatenate(keep_o)]
    d = pd.concat([t.assign(_y=1), o.assign(_y=0)])
    X, Y, g = d[cols].to_numpy(), d._y.to_numpy(), d.run_id.to_numpy()
    p = np.zeros(len(d))
    for a, c in GroupKFold(5).split(X, Y, g):
        p[c] = HGB(max_iter=60, random_state=0).fit(X[a], Y[a]).predict_proba(X[c])[:, 1]
    return roc_auc_score(Y, p), len(d)


FS = (1, .1, .33, .8, 1.25, 2, 5)
for name, h in (("all seconds with UL", df), ("attack seconds", df[df.attack_active == 1]), ("benign seconds", df[df.attack_active == 0])):
    for prb in ("linear", "empirical"):
        print("%-20s PRB %-9s " % (name, prb) + " ".join("x%s %.3f(%dk)" % (f, *(lambda a: (a[0], a[1] // 1000))(test(h, f, prb))) for f in FS), flush=True)
print("all seconds, without UL PRB columns: " + " ".join("x%s %.3f" % (f, test(df, f, "linear", ["rate_ul_kbps", "rate_dl_kbps", "prb_dl_pct", "cell_prb_dl_pct"])[0]) for f in FS), flush=True)
