#!/usr/bin/env python3
"""Detection per KPM scenario (honest, hide, mimic, frame, swap) on a set of test runs, for several detectors, with the
thresholds and alarm rules of report_clf.py (chosen on out-of-fold training scores, honest scenario only; test never used).
Attack episodes: detection %, median delay, undetected seconds per episode; benign episodes: false alarms per benign UE-hour
under the same scenario (e.g. a framed benign UE). Bootstrap CI over runs for detection and undetected seconds.
Usage: eval_by_scen.py --data a.pkl,b.pkl --runs <substring selecting test runs, e.g. l2c or live> name=<scores dir> ..."""
import argparse, glob, pickle, sys
import numpy as np
ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--runs", required=True)
ap.add_argument("--scen", default="honest,hide0.33,hide0.1,mimic,frame2,swap"); ap.add_argument("--boot", type=int, default=300)
ap.add_argument("models", nargs="+")
a = ap.parse_args()
src = open("scripts/ml/report_clf.py").read().split("dump = {}")[0]
argv = sys.argv; sys.argv = ["report_clf.py", "x", "x", "--data", a.data, "--long"]
ns = {}; exec(compile(src, "report_clf", "exec"), ns); sys.argv = argv
EP, pick, stat_series, first_cross, outcome, fa_rate = ns["EP"], ns["pick"], ns["stat_series"], ns["first_cross"], ns["outcome"], ns["fa_rate"]
rng = np.random.default_rng(0)


def summ(R):
    att = [r for r in R if r["attack"]]
    return (100 * np.mean([r["det"] for r in att]) if att else np.nan, float(np.nanmedian([r["delay"] for r in att])) if any(r["det"] for r in att) else np.nan,
            float(np.nanmean([r["undet"] for r in att])) if att else np.nan, fa_rate(R))


def ci(R, i):
    by = {}
    for r in R:
        by.setdefault(r["run"], []).append(r)
    runs = list(by); v = [summ([x for j in rng.integers(len(runs), size=len(runs)) for x in by[runs[j]]])[i] for _ in range(a.boot)]
    return np.nanpercentile(v, [2.5, 97.5])


print("%-14s %-6s %-9s %5s  %-22s %7s  %-20s %s" % ("detector", "point", "scenario", "n", "detected % [CI]", "delay s", "undetected s [CI]", "FA /UE-h"))
for arg in a.models:
    name, d = arg.split("=")
    for pt, rules, budget in (("rate", ["thr", "k23", "k35", "cusum"], 2.0), ("block", ["k2030"], 0.5)):
        R = {s: [] for s in a.scen.split(",")}
        for f in sorted(glob.glob(d.rstrip("/") + "/fold*_seed*/scores.pkl")):
            S = pickle.load(open(f, "rb"))
            opts = [(pick(S["oof"], r, budget), r) for r in rules]
            (th, prior, *_), rule = min(opts, key=lambda o: (np.nan_to_num(o[0][2], nan=1e9), -o[0][3]))
            for k, sc in S["test"].items():
                if a.runs not in k:
                    continue
                e = EP[k]
                for s in R:
                    if s in sc:
                        R[s].append(outcome(e, first_cross(stat_series(sc[s], rule, prior), th)))
        for s, o in R.items():
            if not o:
                continue
            det, dl, und, fa = summ(o); lo, hi = ci(o, 0); ulo, uhi = ci(o, 2)
            print("%-14s %-6s %-9s %5d  %5.1f [%5.1f, %5.1f]    %5.1f  %5.1f [%5.1f, %5.1f]   %.2f" % (name, pt, s, sum(r["attack"] for r in o), det, lo, hi, dl, und, ulo, uhi, fa))
