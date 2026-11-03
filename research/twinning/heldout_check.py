#!/usr/bin/env python3
"""Single held-out check of the twin (TRAFFIC-TWINNING-PLAN 6.6). Refuses to run if the result file exists.
Null: n windows of a build cell against all of the held-out cell of its group; tau* over all bands together.
Usage: heldout_check.py <out.json> <heldout windows npz> [--replicates 1000] [--tag final2]"""
import argparse, glob, json, pathlib, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import validate_twin as V
HERE = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser(usage=__doc__)
ap.add_argument("out"); ap.add_argument("heldout"); ap.add_argument("--replicates", type=int, default=1000); ap.add_argument("--tag", default="final2")
a = ap.parse_args()
if pathlib.Path(a.out).exists():
    sys.exit("result exists, the check is run once: " + a.out)
BUILD, HELD = np.load(HERE / "benign_windows.npz"), np.load(a.heldout)
PAIRS = [(0, 0), (1, 0), (2, 1), (3, 1)]   # build cell, held-out cell: I-2650, I-1815 -> I-796; II-816, II-1835 -> II-2650
per = a.replicates // len(PAIRS)
bands, Ts = {}, []
for band in ("P1", "P2", "P3", "P4"):
    heavy = band == "P4"
    U, D, drop = [], [], 0
    camp = sorted(glob.glob(str(HERE.parents[1] / ("artifacts/experiments/*_ds-benign-twin-%s_%s" % (band, a.tag)))))[-1]
    for r in V.run_dirs([camp]):
        u, d, _, n = V.twin_windows(r, band); U += u; D += d; drop += n
    U, D = np.array(U), np.array(D)
    n = len(U)
    bc = BUILD["src_" + band][:, 0]; hc = HELD["src_" + band][:, 0]
    bu, bd, hu, hd = BUILD["ul_" + band], BUILD["dl_" + band], HELD["ul_" + band], HELD["dl_" + band]
    A = {k: V.Pool(bu[bc == k], bd[bc == k], 0, 0) for k in range(4)}
    B = {k: V.reference(V.Pool(hu[hc == k], hd[hc == k], 0, 0)) for k in range(2)}
    rng = np.random.default_rng(0)
    rows = []
    for ia, ib in PAIRS:
        b, sp, ad = B[ib]
        for _ in range(per):
            rows.append(V.compare(A[ia].take(rng.integers(len(A[ia]), size=n)), b, heavy, sp, ad))
    names = list(rows[0])
    M = np.array([[r[k] for k in names] for r in rows])
    P = np.zeros_like(M)
    for j in range(M.shape[1]):
        ok = np.sort(M[:, j][~np.isnan(M[:, j])])
        P[:, j] = np.where(np.isnan(M[:, j]), 0.0, np.searchsorted(ok, M[:, j], "right") / max(ok.size, 1))
    Ts.append(P.max(axis=1))
    tw = V.Pool(U, D, 30, 30).take()
    b, sp, ad = V.reference(V.Pool(hu, hd, 0, 0))
    s = V.compare(tw, b, heavy, sp, ad)
    tests = {}
    for j, k in enumerate(names):
        col = np.sort(M[:, j][~np.isnan(M[:, j])])
        tests[k] = dict(stat=None if np.isnan(s[k]) else round(float(s[k]), 5), percentile=None if np.isnan(s[k]) or not col.size else round(float(np.searchsorted(col, s[k], "right") / col.size), 4), null_q50=round(float(np.median(col)), 5), null_q95=round(float(np.quantile(col, .95)), 5))
    tag = np.repeat(np.arange(4), per)
    bands[band] = dict(n_windows=n, dropped=drop, real_windows_by_cell=[int((hc == 0).sum()), int((hc == 1).sum())], tau_band=round(float(np.quantile(P.max(axis=1), .95)), 4), tau_per_pair={"%d-%d" % PAIRS[i]: round(float(np.quantile(P.max(axis=1)[tag == i], .95)), 4) for i in range(4)}, tests=tests)
T = np.max(Ts, axis=0)
tau = float(np.quantile(T, .95))
pct = [(b, k, t["percentile"]) for b, r in bands.items() for k, t in r["tests"].items()]
missing = [(b, k) for b, k, p in pct if p is None]
over = [(b, k, p) for b, k, p in pct if p is not None and p > tau]
res = dict(tau_star=round(tau, 4), k=len(pct), replicates=per * 4, tag=a.tag, family_pass=not over and not missing, over=over, missing=missing, bands=bands)
pathlib.Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
print("tau* %.4f k %d family pass %s over %s missing %s" % (tau, len(pct), res["family_pass"], over, missing))
for b, r in bands.items():
    print(b, "n", r["n_windows"], "dropped", r["dropped"], "real windows by cell", r["real_windows_by_cell"], "tau band", r["tau_band"], "per pair", r["tau_per_pair"])
    for k, t in r["tests"].items():
        print("   %-9s stat %-9s pct %-7s null q50/q95 %s/%s" % (k, t["stat"], t["percentile"], t["null_q50"], t["null_q95"]))
