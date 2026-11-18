#!/usr/bin/env python3
"""Redrawn figure of far_curves.py (2026-11-14): the same curves (same computation, imported from far_curves.py), drawn
so the two models are easier to tell apart. One panel per KPM group (honest | tampered) so each panel holds two lines,
the curve at each false-alarm rate is the operating point at_far() takes (most sensitive threshold with FAR <= x: no
vertical zig-zags), the gap between the models is shaded by which model is better, and each y-axis is fitted to the data
in the plotted range (same range for the two KPM groups of a row). Numbers unchanged; the text report stays
research/clf/FAR_curves_oof.txt. Usage (repo root): far_curves_fig.py [--fig research/clf/fig/far_curves_oof_v2.png] [--pooled]
--pooled: all attack episodes together (741: 525 honest + 216 tampered KPM), rows = tier, columns = DR | delay.
--thesis: the thesis figure (2026-11-15): detection only, rows = tier (block, rate limit), columns = honest | tampered KPM,
serif face, sized for a 16 cm text width; write a .pdf path to get a vector file."""
import argparse, os, sys
import numpy as np

ap = argparse.ArgumentParser(); ap.add_argument("--fig", default="research/clf/fig/far_curves_oof_v2.png")
ap.add_argument("--ran", action="store_true", help="add the RAN-only model (KPM only, artifacts/clf/abl/R093_kpm, same pipeline)")
ap.add_argument("--vs-ran", action="store_true", help="cross-domain vs RAN only (core-only model left out)")
ap.add_argument("--pooled", action="store_true", help="one curve per model over all attack episodes (honest + tampered KPM), 2 x 2 panels")
ap.add_argument("--thesis", action="store_true", help="thesis figure: detection only, tier x KPM group, serif, 16 cm wide")
args = ap.parse_args(); sys.argv = sys.argv[:1]
_fig, _pooled, _ran, _vsran, _thesis = args.fig, args.pooled, args.ran or args.vs_ran, args.vs_ran, args.thesis
_src = open("scripts/ml/far_curves.py").read().split("\nrng = np.random.default_rng(0)")[0]
if _ran:   # third model: KPM only (RAN), trained and its rules chosen by the same pipeline (report section 7.4)
    _a = '("core only", ["artifacts/clf/abl/R090_core"], "artifacts/clf/abl/R090_core.json")]'
    assert _src.count(_a) == 1
    _src = _src.replace(_a, _a[:-1] + ',\n          ("RAN only", ["artifacts/clf/abl/R093_kpm"], "artifacts/clf/abl/R093_kpm.json")]')
exec(compile(_src, "far_curves", "exec"))
if _vsran:
    MODELS = [m for m in MODELS if m[0] != "core only"]

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

COL = {"cross-domain": "#2a78d6", "core only": "#eb6834", "RAN only": "#1a9e77"}   # validated (dataviz validate_palette.js, light)
FILL = COL
KPM = ("honest KPM", "tampered KPM")
plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#b5b4ae", "axes.labelcolor": "#52514e", "xtick.color": "#52514e",
                     "ytick.color": "#52514e"})
if _thesis:
    plt.rcParams.update({"font.family": "serif", "font.serif": ["TeX Gyre Termes", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
                         "mathtext.fontset": "stix", "pdf.fonttype": 42})


def envelope(cv, g, col, xmax):
    """value at each distinct FAR: the last (most sensitive) threshold at that FAR, as at_far() picks"""
    far, val = [], []
    for c in cv:
        if far and c["far"] <= far[-1] * (1 + 1e-3) + 1e-9:   # same false-alarm count (benign hours differ by seconds), as at_far()
            val[-1] = c["m"][g][col]
        else:
            far.append(c["far"]); val.append(c["m"][g][col])
    far, val = np.array(far), np.array(val)
    keep = far <= xmax + 1e-9
    far, val = far[keep], val[keep]
    return np.r_[far, xmax], np.r_[val, val[-1]]   # hold the last level to the right edge


def on_grid(x, y, grid):
    """step function (post) of (x, y) evaluated on grid"""
    return y[np.searchsorted(x, grid, side="right") - 1]


XMAX = {"rate limit": 3.0, "block": 1.0}


def panel(a, tn, col, g):
    """two model curves, the shaded gap and the deployed points; returns the data range right of FAR 0"""
    xmax = XMAX[tn]
    grid = np.linspace(0, xmax, 3001)
    Y, lo, hi = {}, np.inf, -np.inf
    for name, *_ in MODELS:
        x, y = envelope(res[(name, tn)]["curve"], g, col, xmax)
        a.step(x, y, where="post", color=COL[name], lw=2.2, zorder=3)
        Y[name] = on_grid(x, y, grid)
        v = y[x > 0]   # at FAR 0 the curves start far lower
        lo, hi = min(lo, v.min()), max(hi, v.max())
        d = res[(name, tn)]["dep"]
        if d["far"] <= xmax:
            a.plot(d["far"], d["m"][g][col], "o", ms=7.5, color=COL[name], mec="white", mew=1.6, zorder=5)
    # shade the gap between the cross-domain model and the best of the others, in the colour of whichever is better
    cd = Y["cross-domain"]
    others = [n for n in Y if n != "cross-domain"]
    O = np.array([Y[n] for n in others])
    k = O.argmax(0) if col == "dr" else O.argmin(0)
    best = O[k, np.arange(O.shape[1])]
    better = cd > best if col == "dr" else cd < best
    a.fill_between(grid, cd, best, where=better, color=FILL["cross-domain"], alpha=.18, lw=0, zorder=1)
    for i, n in enumerate(others):
        a.fill_between(grid, cd, best, where=~better & (k == i) & (cd != best), color=FILL[n], alpha=.18, lw=0, zorder=1)
    a.set_xlim(0, xmax)
    a.grid(True, color="#e6e5e0", lw=.6, zorder=0); a.spines[["top", "right"]].set_visible(False)
    return lo, hi


def ylim(axes, col, lo, hi):
    pad = .06 * (hi - lo)
    for a in axes:
        a.set_ylim(max(0, lo - pad), min(100, hi + pad) if col == "dr" else hi + pad)


XL = "false alarms per benign UE-hour (out-of-fold)"
YL = {"dr": "detection rate (%)", "med": "median delay (s)"}
if _pooled:
    fig, ax = plt.subplots(2, 2, figsize=(9, 6.6))
    for i, tn in enumerate(("rate limit", "block")):
        for j, col in enumerate(("dr", "med")):
            a = ax[i, j]
            lo, hi = panel(a, tn, col, "all")
            ylim([a], col, lo, hi)
            a.set_title("%s: %s, all attack episodes (n = %d)" % (tn, "detection" if col == "dr" else "delay",
                        res[("cross-domain", tn)]["dep"]["m"]["all"]["n"]), loc="left", fontsize=9.5, color="#0b0b0b")
            a.set_ylabel(YL[col]); a.set_xlabel(XL)
    top = .925 if _ran and not _vsran else .955
elif _thesis:
    fig, ax = plt.subplots(2, 2, figsize=(6.3, 4.9))
    for i, tn in enumerate(("block", "rate limit")):
        lo, hi = np.inf, -np.inf
        for j, g in enumerate(KPM):
            a = ax[i, j]
            l, h = panel(a, tn, "dr", g)
            lo, hi = min(lo, l), max(hi, h)
            a.set_title("%s tier, %s (n = %d)" % ("Block" if tn == "block" else "Rate-limit", g, res[("cross-domain", tn)]["dep"]["m"][g]["n"]),
                        loc="left", fontsize=9, color="#0b0b0b")
            if j == 0:
                a.set_ylabel("detection rate (%)")
            a.set_xlabel("false alarms per benign UE-hour (out-of-fold)")
        ylim(ax[i], "dr", lo, hi)
    top = .93
else:
    ROWS = [("rate limit", "dr"), ("rate limit", "med"), ("block", "dr"), ("block", "med")]
    fig, ax = plt.subplots(4, 2, figsize=(9, 11.6))
    for i, (tn, col) in enumerate(ROWS):
        lo, hi = np.inf, -np.inf
        for j, g in enumerate(KPM):
            a = ax[i, j]
            l, h = panel(a, tn, col, g)
            lo, hi = min(lo, l), max(hi, h)
            a.set_title("%s: %s, %s" % (tn, "detection" if col == "dr" else "delay", g), loc="left", fontsize=9.5, color="#0b0b0b")
            if j == 0:
                a.set_ylabel(YL[col])
            if i in (1, 3):
                a.set_xlabel(XL)
        ylim(ax[i], col, lo, hi)
    top = .96 if _ran and not _vsran else .975
h = [Line2D([], [], color=COL[n], lw=2.2, label=n + (" (KPM)" if n == "RAN only" else "")) for n, *_ in MODELS] + [
     Patch(color=FILL["cross-domain"], alpha=.3, label="cross-domain best" if _ran and not _vsran else "cross-domain better")] + (
     [] if _vsran else [Patch(color=FILL["core only"], alpha=.3, label="core only better")]) + (
     [Patch(color=FILL["RAN only"], alpha=.3, label="RAN only better")] if _ran else []) + [
     Line2D([], [], marker="o", ls="", color="#52514e", mec="white", ms=7, label="deployed threshold")]
fig.legend(handles=h, loc="upper center", ncol=4 if _ran and not _vsran else 5, frameon=False, fontsize=7.6 if _thesis else 8.5, bbox_to_anchor=(.5, 1.0),
           columnspacing=1.0 if _thesis else 2.0, handlelength=1.5 if _thesis else 2.0)
if not _thesis:
    fig.text(.01, .004, "Each point: the most sensitive threshold whose false-alarm rate is at most x. Y-axes start at the data, "
             "not at 0. Same episodes, rules and onset as section 7.2.", fontsize=7.5, color="#52514e")
fig.tight_layout(rect=(0, 0 if _thesis else .02 if _pooled else .012, 1, top))
os.makedirs(os.path.dirname(_fig) or ".", exist_ok=True)
fig.savefig(_fig, dpi=200)
print("figure:", _fig)
