#!/usr/bin/env python3
"""Rate-limit tier with the rule chosen among thr / k23 / k35 only (CUSUM excluded: it accumulates without a natural reset in a
continuously running xApp, while offline episodes reset it). Out-of-fold selection at budget 2 as report_clf.py; then test.
Usage: eval_rate_norules.py --data <pkls> <name>=<scores dir>:<run substring> ..."""
import argparse, glob, pickle, sys
import numpy as np
ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("sets", nargs="+"); a = ap.parse_args()
argv = sys.argv; sys.argv = ["report_clf.py", "x", "x", "--data", a.data]
ns = {}; exec(compile(open("scripts/ml/report_clf.py").read().split("dump = {}")[0], "rc", "exec"), ns); sys.argv = argv
EP, pick, stat_series, first_cross, outcome, fa_rate = ns["EP"], ns["pick"], ns["stat_series"], ns["first_cross"], ns["outcome"], ns["fa_rate"]
for spec in a.sets:
    name, rest = spec.split("=", 1); d, sub = rest.split(":")
    oofR, R, chosen = [], {"honest": [], "mimic": []}, []
    for f in sorted(glob.glob(d.rstrip("/") + "/fold*_seed*/scores.pkl")):
        S = pickle.load(open(f, "rb"))
        opts = [(pick(S["oof"], r, 2.0), r) for r in ("thr", "k23", "k35")]
        (th, prior, und, det, Ro), rule = min(opts, key=lambda o: (np.nan_to_num(o[0][2], nan=1e9), -o[0][3])); chosen.append(rule); oofR += Ro
        for k, sc in S["test"].items():
            if sub not in k: continue
            for s in R:
                if s in sc: R[s].append(outcome(EP[k], first_cross(stat_series(sc[s], rule, prior), th)))
    A = [r for r in oofR if r["attack"]]
    print("%-12s OOF: undetected %.1f s, det L2 %.1f%%, FA %.2f, rules %s" % (name, np.nanmean([r["undet"] for r in A]), 100 * np.mean([r["det"] for r in A if r["ev"] == "L2"]), fa_rate(oofR), chosen))
    for s, O in R.items():
        if O:
            At = [r for r in O if r["attack"]]
            print("   %-6s %-7s det %.1f%% (L2 %.1f%%), undetected %.1f s, FA %.2f /UE-h" % (sub, s, 100 * np.mean([r["det"] for r in At]), 100 * np.mean([r["det"] for r in At if r["ev"] == "L2"]), np.nanmean([r["undet"] for r in At]), fa_rate(O)))
