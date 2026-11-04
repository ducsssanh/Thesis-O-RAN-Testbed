#!/usr/bin/env python3
"""Usage history of a UE, composed offline (DRL-PLAN). Benign episodes measured on the testbed, of the same band, are placed before a recorded episode, so one UE stream reads benign ... benign -> episode. Features at second t use only [t-300, t-10):
the 10 s the policy already sees are left out, so a flood does not raise its own baseline at once. Episodes come from the same fold as the episode they precede. The joined part is not one continuous live measurement: state this wherever results are reported."""
import numpy as np, pandas as pd
HIST_S, GAP_S = 300, 10
HIST = ["hist_prb_ul", "hist_busy", "hist_core_log"]


def series(g):
    """PRB, busy flag, log core rate of one episode, in time order."""
    g = g.sort_values("t_unix")
    core = g.prof_ul_kbps.fillna(0).to_numpy()
    return np.c_[g.prb_ul_pct.fillna(0).to_numpy(), core * 125 >= 1000, np.log1p(core)]


def pool(df):
    """{band: [array per benign episode]}, UEs that ran the twin alone."""
    b = df[(df.role == "benign") & (df.client_role == "")]
    p = {}
    for (r, ph, s, band), g in b.groupby(["run_id", "phase", "supi", "band"]):
        if len(g) >= 60:
            p.setdefault(band, []).append(series(g))
    return p


def add_history(ep, pools, rng, k=4, level=None, near=15):
    """ep: one episode frame in time order. Returns the HIST columns for its seconds. level: UL bytes of the twin window of this episode, known from the plan, never from the flood; history is then drawn from
    the `near` episodes of the band closest to that level, the same rule for benign and attacker UEs (a real user keeps its level: research/twinning/out_usage_persistence.txt)."""
    band = ep.band.iloc[0]
    cand = pools[band]
    if level is None:
        idx = rng.integers(len(cand), size=k)
    else:
        lv = np.array([np.log1p(np.expm1(c[:, 2]).sum() * 125) for c in cand])
        idx = rng.choice(np.argsort(np.abs(lv - np.log1p(level)))[:near], size=k)
    h = np.vstack([cand[i] for i in idx])
    x = np.vstack([h, series(ep)])
    n = len(ep); start = len(h)
    c = np.vstack([np.zeros((1, 3)), np.cumsum(x, axis=0)])
    out = np.zeros((n, 3))
    for i in range(n):
        hi = start + i - GAP_S + 1
        lo = max(0, hi - HIST_S)
        out[i] = (c[hi] - c[lo]) / max(hi - lo, 1)
    return pd.DataFrame(out, columns=HIST, index=ep.index)
