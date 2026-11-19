#!/usr/bin/env python3
"""Paired comparison of the ablation models against the deployed cross-domain model, on the same
attack episodes: (1) ensemble out-of-fold scores of the 177 training runs (outside L3 phases, as rule selection), (2) the 144 attacks
of the 30 live-test runs (offline replay). Each model with its own chosen rules. Per tier: detected, mean undetected (active) seconds,
exact McNemar p, and a 95% bootstrap CI over runs of the detection difference.
Usage (repo root): abl_paired.py"""
import glob, json, pickle, re, sys
import numpy as np
from scipy.stats import binomtest
DATA = "artifacts/clf/mimic/episodes31_m.pkl,artifacts/clf/v5/extra_l2_live124_m.pkl,artifacts/clf/live5/episodes31_live5_mall.pkl"
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", DATA, "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active = (ns[k] for k in ("EP", "stat", "first", "outcome", "active"))
ns["RULES"].update({"thr": ("all", 1, 1), "k23": ("all", 2, 3), "k35": ("all", 3, 5)})
MODELS = [("cross-domain (deployed)", "artifacts/clf/v5/R080_v5", "artifacts/clf/live5/V5_live5_mall", "artifacts/clf/v5/export_v5/clf_model.json"),
          ("core only", "artifacts/clf/abl/R090_core", "artifacts/clf/abl/R090_core_live5", "artifacts/clf/abl/R090_core.json"),
          ("no trust/mask/c_t", "artifacts/clf/abl/R091_nogate", "artifacts/clf/abl/R091_nogate_live5", "artifacts/clf/abl/R091_nogate.json"),
          ("no gate at all", "artifacts/clf/abl/R092_nogate_nomask", "artifacts/clf/abl/R092_nogate_nomask_live5", "artifacts/clf/abl/R092_nogate_nomask.json")]


def ens(d, part):
    S = [pickle.load(open(f, "rb"))[part] for f in sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))]
    keys = set.intersection(*[set(s) for s in S])
    return {k: np.mean([s[k]["honest"] for s in S], 0) for k in keys}


R = {}
for name, md, ld, mj in MODELS:
    m = json.load(open(mj)); R[name] = {}
    for part, Z in (("out-of-fold", ens(md, "oof")), ("live test", ens(ld, "test"))):
        ks = sorted(k for k in Z if EP[k]["attack"] and (part == "live test" or EP[k]["other_evasion"] != "L3"))
        for tn, t in (("rate limit", m["soft"]), ("block", m["block"])):
            out = {}
            for k in ks:
                e = EP[k]; ac = active(e["scen"]["honest"])
                out[k] = outcome(e, first(stat(Z[k], ac, t["rule"], t["prior"]), t["threshold"]), ac)
            R[name][(part, tn)] = out
rng = np.random.default_rng(0)
base = MODELS[0][0]
for part in ("out-of-fold", "live test"):
    for tn in ("rate limit", "block"):
        B = R[base][(part, tn)]; ks = sorted(B); runs = sorted({EP[k]["run"] for k in ks})
        byrun = {r: [k for k in ks if EP[k]["run"] == r] for r in runs}
        print("\n%s, %s: %d attack episodes in %d runs (L2 %d)" % (part, tn, len(ks), len(runs), sum(EP[k]["evasion"] == "L2" for k in ks)))
        print("  %-24s %8s %8s %9s %10s %22s %16s" % ("model", "det %", "L2 %", "undet s", "undet act", "vs deployed (only/only)", "diff [95% CI]"))
        for name in R:
            O = R[name][(part, tn)]
            d = np.array([O[k]["det"] for k in ks]); b0 = np.array([B[k]["det"] for k in ks]); l2 = np.array([EP[k]["evasion"] == "L2" for k in ks])
            und = np.mean([(O[k]["delay"] - .2) if O[k]["det"] else 75 - int(np.argmax(EP[k]["run_lab"])) for k in ks])
            ua = np.mean([O[k]["undet_act"] for k in ks])
            x, y = int((b0 & ~d).sum()), int((~b0 & d).sum())
            p = binomtest(min(x, y), x + y, .5).pvalue if x + y else 1.0
            diffs = []
            for _ in range(1000):
                sk = [k for i in rng.integers(len(runs), size=len(runs)) for k in byrun[runs[i]]]
                diffs.append(100 * (np.mean([O[k]["det"] for k in sk]) - np.mean([B[k]["det"] for k in sk])))
            lo, hi = np.percentile(diffs, [2.5, 97.5])
            print("  %-24s %8.1f %8.1f %9.1f %10.1f %12s p=%.3f %+6.1f [%+.1f, %+.1f]" % (name, 100 * d.mean(), 100 * d[l2].mean(), und, ua,
                  "%d/%d" % (x, y) if name != base else "-", p, 100 * (d.mean() - b0.mean()), lo, hi))
