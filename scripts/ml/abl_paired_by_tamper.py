#!/usr/bin/env python3
"""Correction (2026-11-12): in the training data the "honest" scenario of the live runs (live 1, v2, v4) is the KPM as recorded,
which includes the tamper injected live on the attacker (design case hide0.33 / hide0.1 / mimic). The out-of-fold comparison of
the cross-domain model with the core-only model, split into attack episodes whose KPM was genuinely honest (twin runs and live
runs of case honest) and attack episodes tampered live. Same rules and thresholds as abl_paired.py. Usage: abl_paired_by_tamper.py"""
import json, re, sys
import numpy as np
from scipy.stats import binomtest
src = open("scripts/ml/abl_paired.py").read().split("rng = np.random.default_rng(0)")[0]
exec(compile(src, "abl_paired", "exec"))
CASE = {}
for d in ("oran_flooding_live", "oran_flooding_live2", "oran_flooding_live4"):
    for r in json.load(open("research/datasets/%s/manifest/design.json" % d))["runs"]:
        for p in r["phases"]:
            CASE[(r["id"], p["name"])] = p.get("case", "honest" if "evasion" in p else "benign")


def case(k):
    e = EP[k]
    m = re.search(r"flood-live-(l[a-z]\d+)_", e["run"])
    return "honest (twin)" if not m else ("honest (live)" if CASE.get((m.group(1), e["phase"]), "honest") == "honest" else "tampered live: " + CASE[(m.group(1), e["phase"])])


rng = np.random.default_rng(0)
base = MODELS[0][0]
for tn in ("rate limit", "block"):
    Bd = R[base][("out-of-fold", tn)]; ks_all = sorted(Bd)
    cases = {}
    for k in ks_all:
        cases.setdefault(case(k), []).append(k)
    groups = [("all", ks_all), ("genuinely honest KPM", [k for k in ks_all if case(k).startswith("honest")]),
              ("tampered live", [k for k in ks_all if case(k).startswith("tampered")])] + sorted(cases.items())
    print("\nout-of-fold, %s" % tn)
    print("  %-28s %5s %5s | %-15s %-15s | %s" % ("attack episodes", "n", "L2", "cross-domain", "core only", "only cross / only core, McNemar p, diff [95% CI]"))
    for gname, ks in groups:
        if not ks:
            continue
        runs = sorted({EP[k]["run"] for k in ks}); byrun = {r: [k for k in ks if EP[k]["run"] == r] for r in runs}
        C = R["core only"][("out-of-fold", tn)]
        a = np.array([Bd[k]["det"] for k in ks]); c = np.array([C[k]["det"] for k in ks]); l2 = np.array([EP[k]["evasion"] == "L2" for k in ks])
        x, y = int((a & ~c).sum()), int((~a & c).sum())
        p = binomtest(min(x, y), x + y, .5).pvalue if x + y else 1.0
        diffs = []
        for _ in range(1000):
            sk = [k for i in rng.integers(len(runs), size=len(runs)) for k in byrun[runs[i]]]
            diffs.append(100 * (np.mean([Bd[k]["det"] for k in sk]) - np.mean([C[k]["det"] for k in sk])))
        lo, hi = np.percentile(diffs, [2.5, 97.5])
        miss_a, miss_c = 1 - a.mean(), 1 - c.mean()
        print("  %-28s %5d %5d | %5.1f%% (L2 %5.1f) | %5.1f%% (L2 %5.1f) | %d / %d, p=%.3f, %+.1f [%+.1f, %+.1f], fewer misses %.0f%%" % (
            gname, len(ks), l2.sum(), 100 * a.mean(), 100 * a[l2].mean() if l2.any() else np.nan, 100 * c.mean(), 100 * c[l2].mean() if l2.any() else np.nan,
            x, y, p, 100 * (a.mean() - c.mean()), lo, hi, 100 * (1 - miss_a / miss_c) if miss_c else np.nan))
