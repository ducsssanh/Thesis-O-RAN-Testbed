#!/usr/bin/env python3
"""M0: the fair-use rule of the xApp (2 Mbit/s while the cell is busy, 3 of the last 4 seconds, KPM or core), ported
offline as in scripts/drl/report.py, on every episode (it has no training). Same outcome definitions as report_clf.py.
Usage: clf_rule_baseline.py <episodes31.pkl>"""
import pickle, sys
import numpy as np
E = pickle.load(open(sys.argv[1], "rb"))["episodes"]; DELTA = .2


def alarm(e, f):
    rate, cell, core = np.expm1(f[:, 0]), f[:, 4] * 100, np.expm1(f[:, 6])
    masked = f[:, 27] > .5
    busy = (cell >= 80) & (e["other_ul"] >= 100)
    v = ((rate >= 2000) & busy & ~masked & ~(f[:, 25] > .2)) | ((core >= 2000) & busy)
    for t in range(3, len(v)):
        if v[t - 3:t + 1].sum() >= 3:
            return t
    return -1


fa = h = 0; det = {"L1": [], "L2": [], "L3": []}
for e in E:
    al = alarm(e, e["scen"]["honest"]); lab = e["run_lab"]; on = int(np.argmax(lab)) if lab.any() else len(lab)
    stop = al if al >= 0 else len(lab); early = 0 <= al < on
    if e["other_evasion"] != "L3":
        fa += early; h += (min(stop, on) + early) / 3600
    if e["attack"]:
        det[e["evasion"]].append(al >= on)
print("M0 rule: FA %.2f /UE-h over %.2f h; detection L1 %.1f%% L2 %.1f%% L3 %.1f%%" % (fa / h, h, *[100 * np.mean(det[k]) for k in ("L1", "L2", "L3")]))
