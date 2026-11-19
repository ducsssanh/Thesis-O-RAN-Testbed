#!/usr/bin/env python3
"""False alarms of the live xApp decisions (observe mode), pooled over live campaigns: per campaign and
pooled, rate limit (want level >= 2) and block (want level 3), events / benign UE-hours with an exact Poisson 95% CI, and per band.
Same episode and false-alarm definitions as live_report.py (functions loaded from it): first decision of an episode before the onset
is a false alarm; the benign time of the episode stops there.
Usage: live_benign_fa.py <manifest dir> [<manifest dir> ...]"""
import sys
import numpy as np
from scipy.stats import chi2

SRC = open("scripts/ml/live_report.py").read().split("rng = np.random.default_rng(0)")[0]


def poisson(n, h):
    lo = chi2.ppf(.025, 2 * n) / 2 if n else 0.0
    return lo / h, chi2.ppf(.975, 2 * n + 2) / 2 / h


def load(man):
    argv = sys.argv; sys.argv = ["live_report.py", man, "/dev/null"]
    ns = {"__file__": "scripts/ml/live_report.py"}; exec(compile(SRC, "live_report", "exec"), ns); sys.argv = argv
    E = [e for rid, rd in sorted(ns["kept"].items()) for e in ns["episodes"](rd, rid)]
    return E, ns["outcome"], len(ns["kept"])


ALL = []
for man in sys.argv[1:]:
    E, outcome, nk = load(man)
    ALL.append((man, E, outcome, nk))


def report(name, parts):
    print("%s" % name)
    miss = sum(e["missing"] for _, E, _, _ in parts for e in E); n = sum(len(E) for _, E, _, _ in parts)
    print("  runs kept %d, episodes %d (%d attack), missing decisions %.2f%%" % (sum(k for *_, k in parts), n, sum(e["attack"] for _, E, _, _ in parts for e in E), 100 * miss / (75 * n)))
    for key, tier in (("soft", "rate limit"), ("block", "block")):
        R = [(e, out(e, e[key])) for _, E, out, _ in parts for e in E]
        ev = sum(r["early"] for _, r in R); h = sum(r["benign_s"] for _, r in R) / 3600
        lo, hi = poisson(ev, h)
        bands = {}
        for e, r in R:
            v = bands.setdefault(e["band"], [0, 0.0]); v[0] += r["early"]; v[1] += r["benign_s"] / 3600
        print("  %-10s %3d false alarms / %6.2f benign UE-h = %.2f /UE-h, 95%% CI [%.2f, %.2f] | by band: %s" % (
            tier, ev, h, ev / h, lo, hi, ", ".join("%s %d/%.2fh" % (b, v[0], v[1]) for b, v in sorted(bands.items()))))


for p in ALL:
    report(p[0], [p])
if len(ALL) > 1:
    report("pooled", ALL)
