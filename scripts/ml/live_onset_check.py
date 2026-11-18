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


import sys as _s
LS = open("scripts/ml/live_report.py").read().split("rng = np.random.default_rng(0)")[0]
_s.argv = ["live_report.py", "research/datasets/oran_flooding_live5/manifest", "/dev/null"]
lns = {"__file__": "scripts/ml/live_report.py"}; exec(compile(LS, "live_report", "exec"), lns)
LE = {(e["run"], e["phase"], e["supi"]): e for rid, rd in sorted(lns["kept"].items()) for e in lns["episodes"](rd, rid) if e["attack"]}
k0 = next(k for k in EP if "flood-live-lz" in EP[k]["run"]); print("EP key", k0, EP[k0]["run"], EP[k0]["phase"], EP[k0]["supi"])

mis = []; R = {"soft": [], "block": []}; RR = {"soft": [], "block": []}
for k, e in EP.items():
    if not e["attack"] or "flood-live-lz" not in e["run"]: continue
    rid = re.search(r"(l[a-z]\d+)a\d", k).group(1); le = LE.get((rid, e["phase"], e["supi"]))
    if le is None: continue
    on_r = int(np.argmax(e["run_lab"])); on_l = le["on"]
    if on_l != on_r: mis.append((le["ev"], on_r - on_l, int(np.asarray(e["active"])[on_l:on_r].sum()) if on_r > on_l else -1, e["bytes"][on_l:on_r].sum() if on_r > on_l else -1))
    for key in ("soft", "block"):
        fl = next((t for t, v in enumerate(le[key]) if v), -1)
        for on, D in ((on_l, R), (on_r, RR)):
            D[key].append((fl >= on, fl - on + 0.2 if fl >= on else np.nan, 0 <= fl < on))
print("onset mismatches", len(mis), "by level", dict(zip(*np.unique([m[0] for m in mis], return_counts=True))))
print("  replay onset later by (s):", sorted(m[1] for m in mis))
print("  active seconds between scheduled onset and first labelled second:", sorted(m[2] for m in mis))
print("  bytes in that gap (kB):", sorted(round(m[3] / 1e3, 1) for m in mis))
for key in ("soft", "block"):
    for lab, D in (("scheduled onset (live report)", R), ("first labelled second (replay)", RR)):
        a = np.array(D[key], dtype=float)
        print("live %-5s %-32s DR %5.1f%%  d~ %.1f s  alarms before onset %d" % (key, lab, 100 * a[:, 0].mean(), np.nanmedian(a[:, 1]), int(a[:, 2].sum())))
