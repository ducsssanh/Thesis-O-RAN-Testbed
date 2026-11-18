#!/usr/bin/env python3
"""Single XGBoost seed vs the 3-seed ensemble (2026-11-11): rules chosen as the deployed ones on out-of-fold scores. Usage (repo root): ensemble_vs_seed.py"""
import glob, json, pickle, sys
import numpy as np
DATA = "artifacts/clf/mimic/episodes31_m.pkl,artifacts/clf/v5/extra_l2_live124_m.pkl"
src = open("scripts/ml/select_block_rule.py").read()
head = src.split("out = {}")[0]
sys.argv = ["select_block_rule.py", "artifacts/clf/v5/R080_v5", DATA, "/dev/null"]
ns = {}; exec(compile(head, "sbr", "exec"), ns)
S, EP, active = ns["S"], ns["EP"], ns["active"]
def run(oof, label):
    ns["EPS"] = [(EP[k], z, active(EP[k]["scen"]["honest"])) for k, z in sorted(oof.items()) if EP[k]["other_evasion"] != "L3"]
    ns["LIVE"] = np.array(["flood-live" in e["run"] for e, _, _ in ns["EPS"]])
    r1 = ns["select"]("thr", 2.0); r2 = ns["select"]("a510", 0.5)
    print("%-10s rate thr>%.2f det %.1f L2 %.1f undet %.2f | block a510>%.2f det %.1f L2 %.1f undet_act %.2f fa %.2f" % (
        label, r1["threshold"], r1["det"], r1["l2"], r1["undet"], r2["threshold"], r2["det"], r2["l2"], r2["undet_act"], r2["fa"]))
    return r1, r2
keys = set.intersection(*[set(s) for s in S])
for i, s in enumerate(S):
    run({k: s[k]["honest"] for k in keys}, "seed %d" % i)
run({k: np.mean([s[k]["honest"] for s in S], 0) for k in keys}, "ensemble")
# how much do single seeds disagree, second by second?
z = np.array([np.concatenate([s[k]["honest"] for k in sorted(keys)]) for s in S])
print("logit std across seeds per second: median %.2f, q90 %.2f; seeds disagree on 'z > 2.20' in %.2f%% of seconds" % (
    np.median(z.std(0)), np.quantile(z.std(0), .9), 100 * np.mean((z > 2.2027).any(0) != (z > 2.2027).all(0))))
