#!/usr/bin/env python3
"""X3, X4 of the history-free framing (plan step 3c), from the Madrid traces only (same sessions as madrid_usage_persistence.py:
one RNTI, cut at the cell's gap). X4: how much own past a UE has: distribution of session lengths (share shorter than 30 s, 1, 5,
15 min). X3: does a real user keep its level: Spearman of UL bytes of the first 75 s stretch against the stretch k x 75 s later
(k = 1..4), overall and per band, on sessions long enough for each lag. Usage: run from research/twinning; out to stdout."""
import json
import numpy as np, pandas as pd
from scipy.stats import spearmanr
L = json.load(open("benign_profiles.json"))
edges = np.array(L["band_edges_bps"])
walls, rate = [], []
S = {k: ([], []) for k in (1, 2, 3, 4)}; RB = {k: [] for k in (1, 2, 3, 4)}
for c in L["cells"]:
    r = pd.read_parquet(c["file"], columns=["rnti", "sec", "ul_bytes", "dl_bytes"])
    r["ul_bytes"] /= 8; r["dl_bytes"] /= 8
    r = r[(r.ul_bytes > 0) | (r.dl_bytes > 0)].sort_values(["rnti", "sec"])
    rn, s = r.rnti.to_numpy(), r.sec.to_numpy(); ul = r.ul_bytes.to_numpy()
    new = np.r_[True, (rn[1:] != rn[:-1]) | (np.diff(s) > c["gap_s"])]
    first = np.flatnonzero(new); last = np.r_[first[1:], len(s)] - 1
    wall = s[last] - s[first] + 1
    walls.append(wall)
    for i in np.flatnonzero(wall >= 150):
        m = np.arange(first[i], last[i] + 1); t = s[m] - s[first[i]]
        a = ul[m][t < 75].sum(); R = 8 * ul[m].sum() / wall[i]
        for k in S:
            if wall[i] >= 75 * (k + 1):
                S[k][0].append(a); S[k][1].append(ul[m][(t >= 75 * k) & (t < 75 * (k + 1))].sum()); RB[k].append(R)
w = np.concatenate(walls)
print("X4 sessions (RNTI, cut at the cell gap): %d, median %.0f s, mean %.0f s" % (len(w), np.median(w), w.mean()))
for lim in (30, 60, 300, 900):
    print("  shorter than %4d s: %.1f %% of sessions" % (lim, 100 * np.mean(w < lim)))
print("X3 Spearman of UL bytes, first 75 s stretch against the stretch k x 75 s later")
for k in S:
    A, B, R = map(np.array, (S[k][0], S[k][1], RB[k]))
    line = "  lag %3d s  n %7d  all %.3f" % (75 * k, len(A), spearmanr(A, B).statistic)
    for j, n in enumerate(("P1", "P2", "P3", "P4")):
        m = np.searchsorted(edges, R, side="right") == j
        line += "  %s %s" % (n, ("%.3f" % spearmanr(A[m], B[m]).statistic) if m.sum() > 50 else "  -  ")
    print(line)
