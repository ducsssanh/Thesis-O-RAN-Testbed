#!/usr/bin/env python3
"""Why a KPM-only classifier separates tampered seconds: the same test with one element changed at a time. Usage: tamper_cue_diag.py <rows.parquet>"""
import os, sys, pathlib
os.environ.setdefault("OMP_NUM_THREADS", "2")
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier as HGB
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
K = ["rate_ul_kbps", "rate_dl_kbps", "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
df = pd.read_parquet(sys.argv[1]).dropna(subset=K)
df = df[(df.rate_ul_kbps > 0)]
rng = np.random.default_rng(0)
A = df[df.attack_active == 1]
print("honest seconds with UL: attack %d, benign %d" % (len(A), (df.attack_active == 0).sum()))
print("UL PRB on honest seconds: min %.0f, share at or below 2: %.3f; values not whole: %.4f" % (df.prb_ul_pct.min(), (df.prb_ul_pct <= 2).mean(), (df.prb_ul_pct % 1 != 0).mean()))
print("rate on the 8 B grid, honest: %.4f" % np.isclose((df.rate_ul_kbps / .008) % 1, 0, atol=1e-6).mean())
x, y = df.rate_ul_kbps.to_numpy(), df.prb_ul_pct.to_numpy()
for lo, hi in ((0, 10), (10, 50), (50, 100), (100, 200), (200, 500), (500, 2000)):
    m = (x >= lo) & (x < hi)
    print("  rate %4d-%4d kbit/s: n %5d, UL PRB q10/50/90 %.0f %.0f %.0f" % (lo, hi, m.sum(), *np.percentile(y[m], [10, 50, 90])))


def scale(d, f, prb="linear", pool=None):
    d = d.copy()
    r = d.rate_ul_kbps * f
    if prb == "linear":
        new = np.minimum(np.round(d.prb_ul_pct * f), 100.0)
    else:                          # PRB as honest seconds of about that rate show it
        idx = np.searchsorted(pool[0], r)
        w = 200
        new = np.array([pool[1][min(max(i + rng.integers(-w, w + 1), 0), len(pool[1]) - 1)] for i in idx])
    delta = new - d.prb_ul_pct
    d["rate_ul_kbps"] = np.round(r / .008) * .008
    d["prb_ul_pct"] = new
    d["cell_prb_ul_pct"] = np.clip(d.cell_prb_ul_pct + delta, 0, 100)
    return d


def auc(honest, f, cols=K, prb="linear"):
    o = np.argsort(x); pool = (x[o], y[o])
    runs = honest.groupby(["run_id", "phase", "supi"]).ngroup().to_numpy()
    tam = np.isin(runs, rng.permutation(np.unique(runs))[:len(np.unique(runs)) // 2])
    t = scale(honest[tam], f, prb, pool)
    d = pd.concat([t.assign(_y=1), honest[~tam].assign(_y=0)])
    X, Y, g = d[cols].to_numpy(), d._y.to_numpy(), d.run_id.to_numpy()
    p = np.zeros(len(d))
    for a, b in GroupKFold(5).split(X, Y, g):
        p[b] = HGB(max_iter=60, random_state=0).fit(X[a], Y[a]).predict_proba(X[b])[:, 1]
    return roc_auc_score(Y, p)


rows = [("the test as run: attack seconds only, linear PRB", A, K, "linear"), ("all seconds with UL, linear PRB", df, K, "linear"), ("L2 attack seconds only (no fixed rate levels)", A[A.evasion == "L2"], K, "linear"),
        ("benign seconds only", df[df.attack_active == 0], K, "linear"), ("all seconds, UL rate and PRB columns only", df, ["rate_ul_kbps", "prb_ul_pct"], "linear"), ("all seconds, UL rate column only", df, ["rate_ul_kbps"], "linear"), ("all seconds, no UL rate", df, [c for c in K if c != "rate_ul_kbps"], "linear"),
        ("all seconds, PRB from honest seconds of that rate", df, K, "empirical")]
for name, h, c, p in rows:
    print("%-52s" % name, " ".join("x%s %.3f" % (f, auc(h, f, c, p)) for f in (.1, .33, .8, 1.25, 2, 5)), flush=True)
