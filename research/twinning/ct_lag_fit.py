#!/usr/bin/env python3
"""Lag between the KPM and profiler second counters, from the send plan. The plan sends P[i] bytes evenly over a span, so the send
rate at each UNIX boundary is known. If KPM counts delta seconds later than the profiler, K[L] - C[L] = delta * (r[L-1] - r[L]).
Prints delta and R2 per band and run, then the masking and tamper response of a gate on a rolling sum of 1, 2, 3, 5 s (offline replay
of the gate: KPM scaled by the tamper factor, EWMA 0.1, mask below 0.85, unmask above 0.90, per node). Usage: ct_lag_fit.py"""
import glob, json, sys
import numpy as np
sys.path.insert(0, "scripts/k8s/exp/v4traffic")
import planbuilder as PB
EPS, BETA, LO, HI = 1000, 57, .05, .75
SUP = {"ue1": "imsi-001010123456780", "ue2": "imsi-001010123456781"}


def runs(band):
    d = sorted(glob.glob(f"artifacts/experiments/*_ds-benign-twin-{band}_val2"))[-1]
    return d, sorted(glob.glob(d + "/runs/*/*"))


def series(run):
    by = {}
    for l in open(run + "/defense/features.jsonl"):
        x = json.loads(l)
        by.setdefault(x["supi"], {})[round(x["at_ms"] / 1000)] = (x["rate_ul_kbps"] * 125, max(x["prof_ul_kbps"] * 125 - BETA * x["prof_ul_pps"], 0))
    return by


for band in ("P3", "P4"):
    d, rs = runs(band)
    scn = json.load(open(d + "/campaign.json"))["scenario"]
    sp = {(p["name"], u): v["ul"] for p in scn["phases"] for u, v in p.get("flows", {}).items() if "ul" in v}
    X, Y = [], []
    for r in rs:
        by = series(r)
        x, y = [], []
        for f in json.load(open(r + "/traffic/flows.json")):
            if f.get("model") != "real_window":
                continue
            plan, _ = PB.build_plan({**sp[f["phase"], f["ue"]], "seed": f["v4_meta"]["seed"]}, 75, "x", "x", 1)
            s0 = f["replay_start_at"]
            rate = lambda L: sum(sum(s["pkts"]) / (HI - LO) for i, s in enumerate(plan["seconds"]) if s0 + i + LO <= L < s0 + i + HI)
            m = by[SUP[f["ue"]]]
            for L in range(int(s0) + 1, int(s0) + 76):
                if L in m:
                    x.append(rate(L - 1) - rate(L)); y.append(m[L][0] - m[L][1])
        x, y = np.array(x), np.array(y)
        dl = (x * y).sum() / (x * x).sum()
        print(band, r[-6:], "delta %.1f ms  R2 %.3f  n %d" % (1000 * dl, 1 - ((y - dl * x) ** 2).sum() / (y ** 2).sum(), x.size))
        X.append(x); Y.append(y)
    x, y = np.concatenate(X), np.concatenate(Y)
    dl = (x * y).sum() / (x * x).sum()
    print(band, "ALL delta %.1f ms  R2 %.3f" % (1000 * dl, 1 - ((y - dl * x) ** 2).sum() / (y ** 2).sum()))

print("\nGate replay on the P4 and P3 validation runs: masked share of gate seconds, by rolling sum and tamper factor on UE1 KPM")
for band in ("P3", "P4"):
    for W in (1, 2, 3, 5):
        out = {}
        for fac in (1, .8, 1.25, .33, 2):
            tot = masked = 0
            for r in runs(band)[1]:
                by = series(r)
                secs = sorted(set(by[SUP["ue1"]]) & set(by[SUP["ue2"]]))
                t, m = 1.0, False
                for s in secs:
                    for sup, f in ((SUP["ue1"], fac), (SUP["ue2"], 1)):
                        kk = [by[sup][j][0] * f for j in range(s - W + 1, s + 1) if j in by[sup]]
                        cc = [by[sup][j][1] for j in range(s - W + 1, s + 1) if j in by[sup]]
                        k, c = sum(kk), sum(cc)
                        e = EPS * max(len(kk), 1)
                        if (k >= e or c >= e) and by[sup][s][1] + by[sup][s][0] > 0:
                            t += .1 * ((abs(np.log((k + e) / (c + e))) <= .2) - t)
                            m = t < .9 if m else t < .85
                            if sup == SUP["ue1"]:
                                tot += 1; masked += m
            out[fac] = 100 * masked / max(tot, 1)
        print(band, "sum %d s:" % W, "  ".join("x%s %.1f%%" % (k, v) for k, v in out.items()))
