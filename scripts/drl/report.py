#!/usr/bin/env python3
"""Results over seeds: per method, the rate of detection, misses, delay, attack bytes before the alarm, false alarms per benign UE-hour with the benign time really observed (raw and re-weighted to the Madrid band mix), by scenario and level, 95 % CI by bootstrap over runs. Sweeps (classifier, CUSUM) are read at the point nearest the DQN's benign false alarm rate. Usage: report.py <dir> [C_FA ...]"""
import glob, json, pickle, sys
import numpy as np
E = {"|".join((e["run"], e["phase"], e["supi"])): e for e in pickle.load(open("artifacts/drl/episodes.pkl", "rb"))["episodes"]}
PI = {"P1": .50, "P2": .40, "P3": .09, "P4": .01}
DELTA = .2
D = sys.argv[1]; rng = np.random.default_rng(0)


def rows(alarms, seeds):
    """Outcome of each episode and scenario, per seed."""
    out = []
    for sd, A in zip(seeds, alarms):
        for k, sc in A.items():
            e = E[k]; lab = e["run_lab"]; on = int(np.argmax(lab)) if lab.any() else len(lab)
            for s, al in sc.items():
                stop = al if al >= 0 else len(lab)
                early = 0 <= al < on
                out.append((e["run"], sd, e, s, al, on, min(stop, on) + int(early), early, float(e["bytes"][:stop].sum()), float(e["bytes"].sum())))
    return out


def stat(R):
    if not R:
        return None
    n = [r for r in R if r[2]["attack"]]
    det = [r for r in n if r[4] >= r[5]]
    fa = sum(r[7] for r in R); h = sum(r[6] for r in R) / 3600
    bb = {}
    for r in R:
        v = bb.setdefault(r[2]["band"], [0, 0]); v[0] += r[7]; v[1] += r[6] / 3600
    return dict(n=len(n), det=100 * len(det) / max(len(n), 1), miss=100 * sum(r[4] < 0 for r in n) / max(len(n), 1), early=100 * sum(r[7] for r in n) / max(len(n), 1), delay=float(np.median([r[4] - r[5] + DELTA for r in det])) if det else float("nan"), bytes=100 * sum(r[8] for r in n) / max(sum(r[9] for r in n), 1), fa=fa, fa_h=fa / h if h else float("nan"), fa_real=sum(PI[b] * (v[0] / v[1]) for b, v in bb.items() if v[1]))


def ci(R, key, B=300):
    by = {}
    for r in R:
        by.setdefault(r[0], []).append(r)
    runs = list(by)
    v = []
    for _ in range(B):
        S = [x for i in rng.integers(len(runs), size=len(runs)) for x in by[runs[i]]]
        v.append(stat(S)[key])
    return np.nanpercentile(v, [2.5, 97.5])


def line(name, R, keys=("det", "bytes")):
    s = stat(R)
    if s is None:
        return
    extra = " ".join("%s [%.1f, %.1f]" % (k, *ci(R, k)) for k in keys)
    print("  %-20s n %5d | det %5.1f%% miss %5.1f%% early %5.1f%% | delay %5.1f s | bytes %5.1f%% | FA %5d = %6.1f /UE-h, real %6.1f | %s" % (name, s["n"], s["det"], s["miss"], s["early"], s["delay"], s["bytes"], s["fa"], s["fa_h"], s["fa_real"], extra), flush=True)


G = [("honest", lambda s: s == "honest"), ("hidden", lambda s: s.startswith("hide")), ("framed", lambda s: s.startswith("frame")), ("swap", lambda s: s == "swap")]


def table(R):
    for gn, gf in G:
        for l in ("L1", "L2", "L3"):
            line("%s %s" % (gn, l), [r for r in R if r[2]["attack"] and r[2]["evasion"] == l and gf(r[3])])
        line("%s benign" % gn, [r for r in R if not r[2]["attack"] and not r[2]["client"] and gf(r[3])], ("fa_h",))
    line("L3 client benign", [r for r in R if r[2]["client"] and r[3] == "honest"], ("fa_h",))


BEN = lambda R: [r for r in R if not r[2]["attack"] and not r[2]["client"] and r[3] == "honest"]
fs = sorted(glob.glob(D + "/dqn_f*.json"))
cfa = {}
for f in fs:
    o = json.load(open(f)); cfa.setdefault(o["cfa"], {}).setdefault(o["seed"], {}).update(o["alarms"])
CL = {}
for f in sorted(glob.glob(D + "/clf_f*.json")):
    o = json.load(open(f)); c = CL.setdefault(o["seed"], {"alarms": {}, "cusum": {}, "grid": o["grid"], "hgrid": o["hgrid"]}); c["alarms"].update(o["alarms"]); c["cusum"].update(o["cusum"])


def sweep(kind, gridname, target):
    seeds = sorted(CL)
    n = len(CL[seeds[0]][gridname])
    best, bv = None, 1e18
    for i in range(n):
        R = rows([{k: {s: v[i] for s, v in sc.items()} for k, sc in CL[sd][kind].items()} for sd in seeds], seeds)
        f = stat(BEN(R))["fa_h"]
        if abs(f - target) < bv:
            best, bv, keep = i, abs(f - target), R
    return best, keep


if len(sys.argv) > 2:
    cfa = {float(c): v for c, v in cfa.items() if str(int(c)) in sys.argv[2:]}
for c in sorted(cfa):
    seeds = sorted(cfa[c]); R = rows([cfa[c][s] for s in seeds], seeds)
    t = stat(BEN(R))["fa_h"]
    print("DQN C_FA %g, seeds %s, episodes %d" % (c, seeds, len(cfa[c][seeds[0]])))
    table(R)
    if CL:
        i, Rc = sweep("alarms", "grid", t)
        print(" Classifier + threshold, logit > %.1f" % CL[sorted(CL)[0]]["grid"][i]); table(Rc)
        i, Rc = sweep("cusum", "hgrid", t)
        print(" CUSUM, h = %.0f" % CL[sorted(CL)[0]]["hgrid"][i]); table(Rc)
# rules of the xApp, ported from classifier.c: rate at or above the class limit while the cell is busy, 3 of the last 4 samples, KPM or core
def rule_alarm(e, f):
    rate, cell, core = np.expm1(f[:, 0]), f[:, 4] * 100, np.expm1(f[:, 6])
    masked = f[:, 27] > .5
    busy = (cell >= 80) & (e["other_ul"] >= 100)
    v = ((rate >= 2000) & busy & ~masked & ~(f[:, 25] > .2)) | ((core >= 2000) & busy)
    for t in range(3, len(v)):
        if v[t - 3:t + 1].sum() >= 3:
            return t
    return -1
A = {k: {s: rule_alarm(e, f) for s, f in e["scen"].items()} for k, e in E.items()}
print("xApp rules, offline port, default class"); table(rows([A], [0]))
print("Oracle: alarm at the onset, delay %.1f s" % DELTA)
