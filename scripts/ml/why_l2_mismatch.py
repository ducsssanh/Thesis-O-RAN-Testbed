#!/usr/bin/env python3
"""Why do KPM and the UPF profile disagree during L2 floods with honest KPM? (2026-11-12). Per second, raw rows of the training
runs: KPM UL (rate_ul_kbps) against the UPF profile UL bytes corrected for the per-packet overhead (the gate's beta = 57 B).
Groups: the out-of-fold L2 attack episodes only the cross-domain model blocks (vs the core-only model), all L2 attack episodes,
L1 attack episodes, benign UEs. Tests:
  T1 whole-episode byte balance: sum KPM / sum core over the episode (accounting or loss if far from 1);
  T2 timing: per-second correlation of KPM(t) with core(t + lag), lag -2..2 s, and |c_t| with the best lag;
  T3 burst structure: c_t on ON seconds, OFF seconds and ON/OFF transition seconds of the flood;
  T4 packet size and per-packet overhead: core bytes per packet, KPM/core ratio by packet-size bin.
Usage (repo root): why_l2_mismatch.py"""
import glob, json, pickle, sys
import numpy as np, pandas as pd

ROWS = ["research/datasets/oran_flooding_twin/rows.parquet", "research/datasets/oran_flooding_twin_l2/rows.parquet",
        "artifacts/clf/live/rows.parquet", "artifacts/clf/live2/rows.parquet", "artifacts/clf/live4/rows.parquet"]
BETA, EPS = 57.0, 1000.0
D = pd.concat([pd.read_parquet(p) for p in ROWS], ignore_index=True)
D = D.sort_values(["run_id", "phase", "supi", "t_unix"])
D["kpm_B"] = D.rate_ul_kbps.fillna(0) * 125.0
D["core_B"] = np.maximum(D.prof_ul_bytes.fillna(0) - BETA * D.prof_ul_pkts.fillna(0), 0) / D.prof_window_s.fillna(1.0)
D["size"] = D.prof_ul_bytes / D.prof_ul_pkts.replace(0, np.nan)
G = {k: g for k, g in D.groupby(["run_id", "phase", "supi"], sort=False)}

# the 32 / 4 discordant out-of-fold block decisions (as abl_why.py)
src = open("scripts/ml/abl_why.py").read().split('print("A. Speed')[0]
ns = {}; exec(compile(src, "abl_why", "exec"), ns)
O, EP = ns["O"], ns["EP"]
A, B = O[("cross-domain", "out-of-fold", "block")], O[("core only", "out-of-fold", "block")]
only_a = [k for k in A if A[k]["det"] and not B[k]["det"]]
groups = {"L2 only cross-domain blocks": [k for k in only_a if EP[k]["evasion"] == "L2"],
          "L2 all (out-of-fold)": [k for k in A if EP[k]["evasion"] == "L2"],
          "L1 all (out-of-fold)": [k for k in A if EP[k]["evasion"] == "L1"]}
ben = [k for k, e in EP.items() if not e["attack"] and "flood-live-lz" not in k and "flood-live-lb" not in k]
groups["benign UEs"] = ben[:1500]


def frame(k):
    run, ph, supi = k.split("|")
    g = G.get((run, ph, supi))
    return None if g is None else g.reset_index(drop=True)


def ct(kpm, core):
    return np.log((kpm + EPS) / (core + EPS))


print("T1-T4 on honest KPM, active seconds = core UL >= 8 kbit/s")
for name, keys in groups.items():
    tot_k = tot_c = 0.0; corr = {l: [] for l in (-2, -1, 0, 1, 2)}; ctabs = {l: [] for l in (-1, 0, 1)}
    on, off, trans, sizes, ratio_by_size, mask = [], [], [], [], [], []
    n = 0
    for k in keys:
        g = frame(k)
        if g is None or len(g) < 20:
            continue
        att = EP[k]["attack"]
        sel = (g.attack_active.to_numpy() >= 0) if not att else (g.t_unix.to_numpy() >= np.nanmin(g.onset_t.to_numpy()))
        g = g[sel].reset_index(drop=True)
        if len(g) < 10:
            continue
        n += 1
        kb, cb = g.kpm_B.to_numpy(), g.core_B.to_numpy()
        actv = cb * 8 / 1000 >= 8
        tot_k += kb.sum(); tot_c += cb.sum()
        for l in corr:
            if l >= 0:
                a, b = kb[:len(kb) - l], cb[l:]
            else:
                a, b = kb[-l:], cb[:len(cb) + l]
            if len(a) > 5 and a.std() > 0 and b.std() > 0:
                corr[l].append(np.corrcoef(a, b)[0, 1])
        for l in ctabs:
            if l >= 0:
                a, b, m = kb[:len(kb) - l], cb[l:], actv[l:]
            else:
                a, b, m = kb[-l:], cb[:len(cb) + l], actv[:len(actv) + l]
            ctabs[l] += list(np.abs(ct(a, b))[m])
        c = ct(kb, cb)
        mask += list(g.kpm_masked.to_numpy()[actv].astype(float))
        if att:
            aa = g.attack_active.to_numpy().astype(int)
            tr = np.r_[False, np.diff(aa) != 0] | np.r_[np.diff(aa) != 0, False]
            on += list(c[(aa == 1) & ~tr & actv]); off += list(c[(aa == 0) & actv]); trans += list(c[tr & actv])
        s = g["size"].to_numpy()
        sizes += list(s[actv & np.isfinite(s)])
        ratio_by_size += list(zip(s[actv & np.isfinite(s)], (kb / np.maximum(cb, 1))[actv & np.isfinite(s)]))
    q = lambda v: "%.2f" % np.nanmedian(v) if len(v) else "-"
    print("\n== %s (%d episodes)" % (name, n))
    print("  T1 episode byte balance sum(KPM)/sum(core): %.3f" % (tot_k / tot_c if tot_c else np.nan))
    print("  T2 corr KPM(t) vs core(t+lag): " + ", ".join("lag %+d: %s" % (l, q(v)) for l, v in corr.items()))
    print("     median |c_t| on active s: " + ", ".join("lag %+d: %s" % (l, q(v)) for l, v in ctabs.items()) + "; masked share %.1f%%" % (100 * np.mean(mask) if mask else np.nan))
    if on:
        print("  T3 median c_t: flood ON %s (n %d), flood OFF but active %s (n %d), ON/OFF transition %s (n %d)" % (q(on), len(on), q(off), len(off), q(trans), len(trans)))
    if ratio_by_size:
        rs = np.array(ratio_by_size)
        bins = [(0, 200), (200, 600), (600, 1000), (1000, 1600)]
        print("  T4 core bytes/packet median %s; KPM/core by packet size: %s" % (q(sizes), ", ".join(
            "%d-%d B: %s (n %d)" % (lo, hi, q(rs[(rs[:, 0] >= lo) & (rs[:, 0] < hi), 1]), ((rs[:, 0] >= lo) & (rs[:, 0] < hi)).sum()) for lo, hi in bins)))
