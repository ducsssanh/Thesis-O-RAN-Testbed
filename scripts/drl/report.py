#!/usr/bin/env python3
"""Results of a training set: delay, misses, attack bytes before the alarm, false alarms per benign UE-hour with the benign time really observed (raw and re-weighted to the Madrid band mix), by scenario and evasion level. Classifier + threshold: the point of the sweep whose false alarm rate is nearest the DQN's. Usage: report.py <dir>"""
import glob, json, pickle, sys
import numpy as np
D = sys.argv[1]
E = {"|".join((e["run"], e["phase"], e["supi"])): e for e in pickle.load(open("artifacts/drl/episodes.pkl", "rb"))["episodes"]}
PI = {"P1": .50, "P2": .40, "P3": .09, "P4": .01}
DELTA = .2


def metrics(alarms, want):
    """alarms: {key: {scenario: first alarm}}; want(e, scenario) True to count."""
    d, miss, late_b, tot_b, fa, ben_s, by_band = [], 0, 0.0, 0.0, 0, 0, {}
    n = 0
    for k, sc in alarms.items():
        e = E[k]; lab = e["run_lab"]; on = int(np.argmax(lab)) if lab.any() else len(lab)
        for s, al in sc.items():
            if not want(e, s):
                continue
            stop = al if al >= 0 else len(lab)
            b = min(stop, on)
            ben = b + (1 if al >= 0 and al < on else 0)
            ben_s += ben
            bb = by_band.setdefault(e["band"], [0, 0]); bb[1] += ben
            if al >= 0 and al < on:
                fa += 1; bb[0] += 1
            if e["attack"]:
                n += 1
                if al >= on:
                    d.append(al - on + DELTA)
                elif al < 0:
                    miss += 1
                late_b += float(e["bytes"][:stop].sum()); tot_b += float(e["bytes"].sum())
    h = ben_s / 3600
    real = sum(PI[b] * (v[0] / (v[1] / 3600)) for b, v in by_band.items() if v[1] > 0)
    return dict(n=n, det=len(d), miss=miss, early=n - len(d) - miss if n else 0, delay50=float(np.median(d)) if d else float("nan"), delay90=float(np.quantile(d, .9)) if d else float("nan"), bytes=100 * late_b / max(tot_b, 1), fa=fa, fa_h=fa / h if h else float("nan"), fa_real=real, ben_h=h)


LV = lambda l: (lambda e, s: e["attack"] and e["evasion"] == l)
SC = {"honest": lambda s: s == "honest", "hidden": lambda s: s.startswith("hide"), "swap": lambda s: s == "swap"}
FA = {"benign honest": lambda e, s: not e["attack"] and not e["client"] and s == "honest", "benign framed": lambda e, s: not e["attack"] and not e["client"] and s.startswith("frame"), "L3 client benign": lambda e, s: e["client"] and s == "honest"}


def merge(files):
    out = {}
    for f in files:
        out.update(json.load(open(f))["alarms"])
    return out


dq = {}
for f in glob.glob(D + "/dqn_f*_c*.json"):
    o = json.load(open(f)); dq.setdefault(o["cfa"], []).append(f)
clf = sorted(glob.glob(D + "/clf_f*.json"))
C = [json.load(open(f)) for f in clf]
grid = C[0]["grid"] if C else []
ca = {}
for o in C:
    ca.update(o["alarms"])
for idx in range(len(grid)):
    pass


def clf_at(i):
    return {k: {s: v[i] for s, v in sc.items()} for k, sc in ca.items()}


def row(name, m):
    print("  %-18s n %4d | detected %3d miss %3d early %3d | delay q50/q90 %5.1f %5.1f s | attack bytes before alarm %5.1f%% | FA %3d = %6.1f /UE-h, real mix %6.1f" % (name, m["n"], m["det"], m["miss"], m["early"], m["delay50"], m["delay90"], m["bytes"], m["fa"], m["fa_h"], m["fa_real"]))


for cfa in sorted(dq):
    A = merge(dq[cfa])
    print("DQN C_FA %g, %d folds, %d episodes" % (cfa, len(dq[cfa]), len(A)))
    allben = metrics(A, lambda e, s: not e["client"] and s == "honest")
    for sn, sf in SC.items():
        for l in ("L1", "L2", "L3"):
            row("%s %s" % (sn, l), metrics(A, lambda e, s, l=l, sf=sf: e["attack"] and e["evasion"] == l and sf(s)))
    for fn, ff in FA.items():
        row(fn, metrics(A, ff))
    if C:
        target = metrics(A, FA["benign honest"])["fa_h"]
        vals = [metrics(clf_at(i), FA["benign honest"])["fa_h"] for i in range(len(grid))]
        i = int(np.argmin(np.abs(np.array(vals) - target)))
        print(" Classifier + threshold at the nearest benign false alarm rate (logit > %.1f):" % grid[i])
        B = clf_at(i)
        for l in ("L1", "L2", "L3"):
            row("honest %s" % l, metrics(B, lambda e, s, l=l: e["attack"] and e["evasion"] == l and s == "honest"))
        row("hidden L2", metrics(B, lambda e, s: e["attack"] and e["evasion"] == "L2" and s.startswith("hide")))
        for fn, ff in FA.items():
            row(fn, metrics(B, ff))
