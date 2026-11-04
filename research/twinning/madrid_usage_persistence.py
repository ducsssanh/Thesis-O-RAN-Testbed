#!/usr/bin/env python3
"""Does a real user keep its usage level over time? Build cells, same session (cut at T), two consecutive 75 s stretches: Spearman of UL bytes, and of the level inside band P4. This supports matching a composed history to the level of the window. Usage: run from research/twinning"""
import json
import numpy as np, pandas as pd
from scipy.stats import spearmanr
L = json.load(open("benign_profiles.json"))
edges = np.array(L["band_edges_bps"])
A, B, R = [], [], []
for c in L["cells"]:
    r = pd.read_parquet(c["file"], columns=["rnti", "sec", "ul_bytes", "dl_bytes"])
    r["ul_bytes"] /= 8; r["dl_bytes"] /= 8
    r = r[(r.ul_bytes > 0) | (r.dl_bytes > 0)].sort_values(["rnti", "sec"])
    rn, s = r.rnti.to_numpy(), r.sec.to_numpy(); ul = r.ul_bytes.to_numpy()
    new = np.r_[True, (rn[1:] != rn[:-1]) | (np.diff(s) > c["gap_s"])]
    sid = np.cumsum(new) - 1
    first = np.flatnonzero(new); last = np.r_[first[1:], len(s)] - 1
    wall = s[last] - s[first] + 1
    for i in np.flatnonzero(wall >= 150):
        m = np.arange(first[i], last[i] + 1); t = s[m] - s[first[i]]
        a, b = ul[m][t < 75].sum(), ul[m][(t >= 75) & (t < 150)].sum()
        A.append(a); B.append(b); R.append(8 * ul[m].sum() / wall[i])
A, B, R = map(np.array, (A, B, R))
print("sessions of at least 150 s:", len(A))
print("Spearman, UL bytes of stretch 1 and stretch 2: %.3f" % spearmanr(A, B).statistic)
for k, n in enumerate(("P1", "P2", "P3", "P4")):
    m = np.searchsorted(edges, R, side="right") == k
    if m.sum() > 50:
        print(" ", n, "n", m.sum(), "Spearman %.3f" % spearmanr(A[m], B[m]).statistic)
