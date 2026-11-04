#!/usr/bin/env python3
"""The objective the policy is trained for: mean return per episode (-1 per second of attack not alarmed, -C_FA per false alarm), test folds only. Classifier and CUSUM at the operating point picked on the inner split of each fold for that C_FA. Difference policy - classifier with 95 % CI by bootstrap over runs. Usage: cost_report.py <dir>"""
import glob, json, pickle, sys
import numpy as np
E = {"|".join((e["run"], e["phase"], e["supi"])): e for e in pickle.load(open("artifacts/drl/episodes.pkl", "rb"))["episodes"]}
D = sys.argv[1]; rng = np.random.default_rng(0)
GROUPS = {"all, without L3 phases": lambda e, s: e["other_evasion"] != "L3", "honest, without L3 phases": lambda e, s: e["other_evasion"] != "L3" and s == "honest", "honest L1 + benign": lambda e, s: s == "honest" and e["other_evasion"] == "L1", "honest L2 + benign": lambda e, s: s == "honest" and e["other_evasion"] == "L2", "tampered L1, L2 phases": lambda e, s: e["other_evasion"] != "L3" and s != "honest", "all with L3 phases": lambda e, s: True, "honest L3 phases, with the benign client": lambda e, s: s == "honest" and e["other_evasion"] == "L3"}


def ret(e, al, c):
    lab = e["run_lab"]; stop = len(lab) if al < 0 else al
    return -float(lab[:stop].sum()) - (c if al >= 0 and not lab[al] else 0.0)


P, C, U = {}, {}, {}
for f in glob.glob(D + "/dqn_f*.json"):
    o = json.load(open(f))
    for k, sc in o["alarms"].items():
        for s, al in sc.items():
            P.setdefault((o["cfa"], o["seed"], k, s), al)
for f in glob.glob(D + "/clf_f*.json"):
    o = json.load(open(f))
    for cfa, pk in o["pick"].items():
        for k, sc in o["alarms"].items():
            for s, v in sc.items():
                C[(float(cfa), o["seed"], k, s)] = v[pk["clf"]]
        for k, sc in o["cusum"].items():
            for s, v in sc.items():
                U[(float(cfa), o["seed"], k, s)] = v[pk["cusum"]]
for cfa in sorted({k[0] for k in P}):
    print("C_FA %g, seeds %s" % (cfa, sorted({k[1] for k in P if k[0] == cfa})))
    for gn, gf in GROUPS.items():
        by = {}
        for (c, sd, k, s), al in P.items():
            if c != cfa or (c, sd, k, s) not in C:
                continue
            e = E[k]
            if gf(e, s):
                by.setdefault(e["run"], []).append((ret(e, al, cfa), ret(e, C[(c, sd, k, s)], cfa), ret(e, U[(c, sd, k, s)], cfa)))
        if not by:
            continue
        rr = list(by); A = np.vstack([np.array(by[r]) for r in rr])
        bs = []
        for _ in range(1000):
            x = np.vstack([np.array(by[rr[i]]) for i in rng.integers(len(rr), size=len(rr))]); bs.append((x[:, 0] - x[:, 1]).mean())
        print("  %-42s n %6d | policy %7.2f classifier %7.2f CUSUM %7.2f | policy - classifier %+6.2f [%+.2f, %+.2f]" % (gn, len(A), A[:, 0].mean(), A[:, 1].mean(), A[:, 2].mean(), (A[:, 0] - A[:, 1]).mean(), *np.percentile(bs, [2.5, 97.5])), flush=True)
