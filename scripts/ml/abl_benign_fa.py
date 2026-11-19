#!/usr/bin/env python3
"""False alarms of every model on benign UEs, offline replay of live runs: KPM as recorded and every
UE's KPM tampered offline (frame x1.25/x2/x5, hide x0.8/x0.33/x0.1, mimic, swap; gate recomputed). Each model with its own rules
(chosen as the deployed ones). Per data set and pooled: events / benign UE-hours, exact Poisson 95% CI.
Usage: abl_benign_fa.py <name>=<episodes pkl>:<score dir suffix> ...   e.g. live5=artifacts/clf/live5/episodes31_live5_mall.pkl:live5
Score dirs: deployed artifacts/clf/<suffix>/V5_<suffix>_mall, ablations artifacts/clf/abl/<model>_<suffix>."""
import glob, json, pickle, sys
import numpy as np
from scipy.stats import chi2

SETS = [(a.split("=")[0],) + tuple(a.split("=")[1].split(":")) for a in sys.argv[1:]]
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", ",".join(p for _, p, _ in SETS), "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active = (ns[k] for k in ("EP", "stat", "first", "outcome", "active"))
ns["RULES"].update({"thr": ("all", 1, 1), "k23": ("all", 2, 3), "k35": ("all", 3, 5)})
MODELS = [("cross-domain (deployed)", "artifacts/clf/{s}/V5_{s}_mall", "artifacts/clf/v5/export_v5/clf_model.json"),
          ("core only", "artifacts/clf/abl/R090_core_{s}", "artifacts/clf/abl/R090_core.json"),
          ("no trust/mask/c_t", "artifacts/clf/abl/R091_nogate_{s}", "artifacts/clf/abl/R091_nogate.json"),
          ("no gate at all", "artifacts/clf/abl/R092_nogate_nomask_{s}", "artifacts/clf/abl/R092_nogate_nomask.json")]
RUNS = {name: {e["run"] for e in pickle.load(open(pkl, "rb"))["episodes"]} for name, pkl, _ in SETS}
SCEN = ["honest", "frame1.25", "frame2", "frame5", "hide0.8", "hide0.33", "hide0.1", "mimic", "swap"]


def poisson(n, h):
    lo = chi2.ppf(.025, 2 * n) / 2 if n else 0.0
    return lo / h, chi2.ppf(.975, 2 * n + 2) / 2 / h


def ens(d):
    S = [pickle.load(open(f, "rb"))["test"] for f in sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))]
    assert len(S) == 3, d
    return {k: {s: np.mean([x[k][s] for x in S], 0) for s in S[0][k]} for k in S[0]}


print("Benign-UE false alarms, offline replay; each cell: events / benign UE-h = rate [95% CI]")
for mname, dpat, mj in MODELS:
    m = json.load(open(mj)); tiers = [("rate limit", m["soft"]), ("block", m["block"])]
    Z = {}
    for name, pkl, suf in SETS:
        Z.update(ens(dpat.format(s=suf)))
    for tn, t in tiers:
        print("\n%s, %s (%s > %.2f)" % (mname, tn, t["rule"], t["threshold"]))
        for s in SCEN:
            cells, tot = [], [0, 0.0]
            for name, pkl, suf in SETS:
                ks = [k for k in Z if EP[k]["run"] in RUNS[name]]
                # benign UEs; for the KPM-as-recorded column also the attackers' seconds before the onset (as the live report)
                ks = [k for k in ks if s in Z[k] and (not EP[k]["attack"] or s == "honest")]
                R = []
                for k in ks:
                    e = EP[k]; ac = active(e["scen"][s])
                    R.append(outcome(e, first(stat(Z[k][s], ac, t["rule"], t["prior"]), t["threshold"]), ac))
                ev = sum(r["early"] for r in R); h = sum(r["benign_s"] for r in R) / 3600
                tot[0] += ev; tot[1] += h
                cells.append("%s %2d/%5.2fh=%.2f [%.2f,%.2f]" % ((name, ev, h, ev / h if h else np.nan) + poisson(ev, h)) if h else "%s -" % name)
            if len(SETS) > 1 and tot[1]:
                cells.append("pooled %2d/%5.2fh=%.2f [%.2f,%.2f]" % ((tot[0], tot[1], tot[0] / tot[1]) + poisson(tot[0], tot[1])))
            print("  %-10s %s" % (s, " | ".join(cells)))
