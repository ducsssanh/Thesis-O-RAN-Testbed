"""Offline test of a byte-conservation gate. D[t] = cumulative core bytes - cumulative KPM bytes of a UE. No bytes are lost between
gNB and UPF, so an honest D only holds the bytes in flight between the two second boundaries; a scaled KPM makes D grow without limit.
D restarts at 0 after a silent second (nothing in flight). Violation: |D| > theta0 + L * (larger of the last two core seconds).
Usage: conservation_gate.py <label>=<run> ..."""
import json, sys, numpy as np
BETA = 57
def load(run):
    by = {}
    for l in open(run + "/defense/features.jsonl"):
        x = json.loads(l)
        by.setdefault(x["supi"], {})[round(x["at_ms"] / 1000)] = (x["rate_ul_kbps"] * 125, max(x["prof_ul_kbps"] * 125 - BETA * x["prof_ul_pps"], 0))
    return {s: np.array([v[t] for t in sorted(v)]) for s, v in by.items()}
def replay(a, fac, th0, L):
    k, c = a[:, 0] * fac, a[:, 1]
    D, out, active, first = 0.0, 0, 0, None
    maxabs = 0.0
    for i in range(len(k)):
        if k[i] == 0 and c[i] == 0:
            D = 0.0
            continue
        D += c[i] - k[i]
        active += 1
        bound = th0 + L * max(c[i], c[i - 1] if i else 0)
        maxabs = max(maxabs, abs(D) / max(bound, 1))
        if abs(D) > bound:
            out += 1
            if first is None:
                first = active
    return out, active, first, maxabs
sets = dict(x.split("=", 1) for x in sys.argv[1:])
runs = {k: list(load(v).values()) for k, v in sets.items()}
for th0, L in ((2000, .1), (2000, .2), (2000, .3), (5000, .1), (5000, .2), (5000, .3)):
    print("theta0 %d B, L %.1f s" % (th0, L))
    for name, rs in runs.items():
        row = []
        for fac in (1, .8, 1.25, .33, 2):
            r = [replay(a, fac, th0, L) for a in rs]
            o, n = sum(x[0] for x in r), sum(x[1] for x in r)
            f = [x[2] for x in r if x[2]]
            row.append("x%s %.2f%% first %s" % (fac, 100 * o / max(n, 1), int(np.median(f)) if f else "-"))
        print("  %-12s %s" % (name, " | ".join(row)))
