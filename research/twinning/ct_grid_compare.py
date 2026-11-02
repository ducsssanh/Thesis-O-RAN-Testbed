#!/usr/bin/env python3
"""Root cause of benign c_t gaps: same real windows (same seeds), no tamper, sent on two grids.
gnb grid: each second's bytes are sent across a UNIX second boundary. unix grid: inside one UNIX second, as the KPM and the
profiler count. Usage: ct_grid_compare.py <gnb run dir> <unix run dir>"""
import json, os, sys
import numpy as np
EPS, BETA, A, TM = 1000, 57, 0.1, 0.85
SUP = {"ue1": "imsi-001010123456780", "ue2": "imsi-001010123456781"}


def load(run):
    print(run, "tamper.jsonl bytes", os.path.getsize(run + "/defense/tamper.jsonl"))
    by = {}
    with open(run + "/defense/features.jsonl") as fh:
        for l in fh:
            x = json.loads(l)
            by.setdefault(x["supi"], []).append((x["at_ms"] / 1000, x["rate_ul_kbps"] * 125, max(x["prof_ul_kbps"] * 125 - BETA * x["prof_ul_pps"], 0), x["kpm_masked"]))
    flows = [f for f in json.load(open(run + "/traffic/flows.json")) if f.get("model") == "real_window"]
    K, C, M, W, seeds, adj = [], [], [], [], [], []
    for f in flows:
        a = np.array(by[SUP[f["ue"]]], float)
        s0 = f["replay_start_at"]
        m = (a[:, 0] > s0) & (a[:, 0] <= s0 + 76)
        k, c = a[m, 1], a[m, 2]
        K.append(k); C.append(c); M.append(a[m, 3]); seeds.append(f["v4_meta"]["seed"]); W.append(s0 % 1)
    return K, C, M, seeds, W


def report(name, K, C, M, W):
    k, c = np.concatenate(K), np.concatenate(C)
    g = (k >= EPS) | (c >= EPS)
    q = np.log((k + EPS) / (c + EPS))[g]
    print("%s: send start frac %.2f-%.2f | KPM/core total %.4f | gate secs %d | outside +-0.2 %.2f%% | +-0.35 %.2f%% | q01/q99 %.3f/%.3f | min/max %.3f/%.3f | masked rows %.2f%%" % (
        name, min(W), max(W), k.sum() / c.sum(), g.sum(), 100 * (abs(q) > .2).mean(), 100 * (abs(q) > .35).mean(), *np.percentile(q, [1, 99]), q.min(), q.max(), 100 * np.concatenate(M).mean()))
    t, rows = [], []
    for kk, cc in zip(K, C):
        qq = np.log((kk + EPS) / (cc + EPS))
        gg = (kk >= EPS) | (cc >= EPS)
        for i in np.flatnonzero(gg & (abs(qq) > .2)):
            nb = [j for j in (i - 1, i + 1) if 0 <= j < len(qq)]
            j = max(nb, key=lambda j: abs(kk[j] - cc[j]))
            r = (kk[j] - cc[j]) / (kk[i] - cc[i])
            t.append(r)
            rows.append((int(kk[i]), int(cc[i]), round(qq[i], 2), int(kk[j]), int(cc[j])))
    t = np.array(t)
    if t.size:
        print("  outliers %d, neighbour cancels (ratio -0.5..-1.5) %.0f%%" % (t.size, 100 * ((t < -.5) & (t > -1.5)).mean()))
    return rows


if __name__ == "__main__":
    a, b = load(sys.argv[1]), load(sys.argv[2])
    print("same windows:", a[3] == b[3], len(a[3]))
    report("gnb grid ", a[0], a[1], a[2], a[4])
    rows = report("unix grid", b[0], b[1], b[2], b[4])
    print("remaining unix-grid outliers (KPM, core, c_t, neighbour KPM, neighbour core):")
    for r in rows[:25]:
        print("  ", r)
