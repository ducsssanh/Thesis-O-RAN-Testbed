#!/usr/bin/env python3
"""Detection on the live runs per KPM case (honest, hide0.33, hide0.1) for detectors scored offline on the rebuilt live episodes
(R050 ensemble, baselines): thresholds chosen exactly as report_clf.py (functions loaded from it, out-of-fold training scores),
then the live honest-scenario scores (the real live traffic, tamper included) are read per case.
Usage: live_by_case.py <data pkl list> <design.json> name=<dir> ..."""
import glob, json, pickle, re, sys
import numpy as np
src = open("scripts/ml/report_clf.py").read().split("dump = {}")[0]
sys_argv = sys.argv; sys.argv = ["report_clf.py", "x", "x", "--data", sys_argv[1], "--long"]
ns = {}; exec(compile(src, "report_clf", "exec"), ns); sys.argv = sys_argv
EP, pick, stat_series, first_cross, outcome = ns["EP"], ns["pick"], ns["stat_series"], ns["first_cross"], ns["outcome"]
D = {r["id"]: {p["name"]: p.get("case", "benign") for p in r["phases"]} for r in json.load(open(sys.argv[2]))["runs"]}
print("%-12s %-6s %-10s %s" % ("detector", "point", "case", "n  detected %  median delay s"))
for arg in sys.argv[3:]:
    name, d = arg.split("=")
    for pt, rules, budget in (("rate", ["thr", "k23", "k35", "cusum"], 2.0), ("block", ["k2030"], 0.5)):
        R = {}
        for f in sorted(glob.glob(d.rstrip("/") + "/fold*_seed*/scores.pkl")):
            S = pickle.load(open(f, "rb"))
            opts = [(pick(S["oof"], r, budget), r) for r in rules]
            (th, prior, *_), rule = min(opts, key=lambda o: (np.nan_to_num(o[0][2], nan=1e9), -o[0][3]))
            for k, sc in S["test"].items():
                e = EP[k]
                if not e["attack"] or "live" not in k:   # also matches flood-live2 run ids
                    continue
                case = D[re.search(r"(l[a-z]\d+)a\d", k).group(1)][e["phase"]]
                R.setdefault(case, []).append(outcome(e, first_cross(stat_series(sc["honest"], rule, prior), th)))
        for case in ("honest", "mimic", "hide0.33", "hide0.1"):
            o = R.get(case, [])
            if o:
                print("%-12s %-6s %-10s %3d  %5.1f  %5.1f" % (name, pt, case, len(o), 100 * np.mean([x["det"] for x in o]), np.nanmedian([x["delay"] for x in o])))
