#!/usr/bin/env python3
"""Section 7.4 rerun (2026-11-12): every method with the deployed rules and the deployed threshold procedure.
Rules: rate limit = 1 s above the threshold; block = at least 5 of the last 10 active seconds above the threshold.
Thresholds: on each method's own out-of-fold scores of the same 177 training runs (outside L3 phases), the most sensitive one
whose false-alarm rate stays within the budget (2 and 0.5 per benign UE-hour) on all out-of-fold episodes and on those of the
live training runs (select_block_rule.py). Learned models are the mean of their seeds' calibrated logits. Then the live test:
detection per KPM case of the 144 attacks (KPM as recorded live), median delay, and false alarms over both parts of the test
(25.8 benign UE-hours) with an exact Poisson 95% CI. Usage (repo root): compare_rules_510.py"""
import glob, json, pickle, re, sys
import numpy as np
from scipy.stats import chi2

DATA = ["artifacts/clf/mimic/episodes31_m.pkl", "artifacts/clf/v5/extra_l2_live124_m.pkl",
        "artifacts/clf/live5/episodes31_live5_mall.pkl", "artifacts/clf/live6/episodes31_live6_mall.pkl"]
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", ",".join(DATA), "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active, fa, RULES = (ns[k] for k in ("EP", "stat", "first", "outcome", "active", "fa", "RULES"))
RULES["thr"] = ("all", 1, 1)
DESIGN = {r["id"]: {p["name"]: p.get("case", "benign") for p in r["phases"]} for r in json.load(open("research/datasets/oran_flooding_live5/manifest/design.json"))["runs"]}
O = "artifacts/clf/abl"
METHODS = [  # name, inputs, out-of-fold score dirs, test score dirs
    ("Cross-domain (proposed)", "KPM + core + gate", ["artifacts/clf/v5/R080_v5"], ["artifacts/clf/live5/V5_live5_mall", "artifacts/clf/live6/V5_live6_mall"]),
    ("XGBoost, core only", "core", [O + "/R090_core"], [O + "/R090_core_live5", O + "/R090_core_live6"]),
    ("XGBoost, KPM only", "KPM", [O + "/R093_kpm"], [O + "/R093_kpm_live5", O + "/R093_kpm_live6"]),
    ("Rate threshold", "core UL", [O + "/base_cmp/B_rate"], [O + "/base_cmp/B_rate"]),
    ("EWMA (self-reference)", "core UL", [O + "/base_cmp/B_ewma"], [O + "/base_cmp/B_ewma"]),
    ("CUSUM", "core UL", [O + "/base_cmp/B_cusum"], [O + "/base_cmp/B_cusum"]),
    ("Isolation Forest", "25 inputs", [O + "/base_cmp/B_iforest"], [O + "/base_cmp/B_iforest"]),
]


def ens(dirs, part):
    S = []
    for d in dirs:
        S += [pickle.load(open(f, "rb"))[part] for f in sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))]
    if part == "test":  # test dirs hold different episodes (live5, live6): union per seed position
        by = {}
        for d in dirs:
            for i, f in enumerate(sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))):
                by.setdefault(i, {}).update(pickle.load(open(f, "rb"))["test"])
        S = list(by.values())
    keys = set.intersection(*[set(s) for s in S])
    return {k: np.mean([s[k]["honest"] for s in S], 0) for k in keys}, len(S)


def select(oof, rule, budget):
    eps = [(EP[k], z, active(EP[k]["scen"]["honest"])) for k, z in sorted(oof.items()) if k in EP and EP[k]["other_evasion"] != "L3"]
    live = np.array(["flood-live" in e["run"] for e, _, _ in eps])
    m = np.mean([e["run_lab"].mean() for e, _, _ in eps]); prior = float(np.log(m + 1e-9) - np.log(1 - m + 1e-9))
    St = [stat(z, ac, rule, prior) for e, z, ac in eps]
    cand = np.unique(np.concatenate([r[:max(1, int(np.argmax(e["run_lab"])) if e["run_lab"].any() else len(r))] for (e, _, _), r in zip(eps, St)]))
    cand = cand[np.isfinite(cand)]
    cand = np.r_[cand.max() + 1e-6, np.quantile(cand, np.linspace(1, .5, 400))]
    best = cand[0]
    for th in cand:
        R = [outcome(e, first(r, th), ac) for (e, _, ac), r in zip(eps, St)]
        if fa(R) <= budget + 1e-9 and (not live.any() or fa([o for o, l in zip(R, live) if l]) <= budget + 1e-9):
            best = th
        else:
            break
    return best, prior


def poisson(n, h):
    lo = chi2.ppf(.025, 2 * n) / 2 if n else 0.0
    return lo / h, chi2.ppf(.975, 2 * n + 2) / 2 / h


SCEN = ["honest", "frame1.25", "frame2", "frame5", "hide0.8", "hide0.33", "hide0.1", "mimic"]
def ens_s(dirs, sc):
    by = {}
    for d in dirs:
        for i, f in enumerate(sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))):
            for k, v in pickle.load(open(f, "rb"))["test"].items():
                if sc in v: by.setdefault(i, {})[k] = v[sc]
    S = list(by.values()); keys = set.intersection(*[set(x) for x in S])
    return {k: np.mean([x[k] for x in S], 0) for k in keys}
print("benign UEs tampered offline (tampered rows: benign UEs only, as section 7.3); deployed rules; thresholds as 7.4 rerun")
for name, inp, od, td in [m for m in METHODS if m[0].startswith(("Cross", "XGBoost, core", "Isolation"))]:
    oof, _ = ens(od, "oof")
    th = {"rate": select(oof, "thr", 2.0), "block": select(oof, "a510", 0.5)}
    hon = ens_s(td, "honest")
    for sc in SCEN:
        z = ens_s(td, sc); out = []
        for tier, rule in (("rate", "thr"), ("block", "a510")):
            t, pr = th[tier]; ev = 0; h = 0.0
            for k in hon:
                if k not in EP: continue
                zz = (hon[k] if EP[k]["attack"] else z.get(k)) if sc == "honest" else (None if EP[k]["attack"] else z.get(k))
                if zz is None: continue
                ac = active(EP[k]["scen"]["honest"])
                r = outcome(EP[k], first(stat(zz, ac, rule, pr), t), ac); ev += r["early"]; h += r["benign_s"] / 3600
            out.append("%s %2d/%4.1fh=%.2f" % (tier, ev, h, ev / h))
        print("%-24s %-10s %s" % (name[:24], sc, " | ".join(out)))
