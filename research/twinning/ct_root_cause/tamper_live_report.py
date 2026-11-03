#!/usr/bin/env python3
"""Live KPM tamper over the benign twin P4: per episode, time to mask, bytes misreported before the mask, masked share while on, recovery; masks on honest seconds and on the other UE.
A gate second has KPM or core of at least 1 kB, as in ttival_report.py. Usage: tamper_live_report.py"""
import glob, json, pathlib
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
rows = []
for u in ("780", "781"):
    run = glob.glob(str(ROOT / ("artifacts/experiments/*_tamper%s/runs/*/*" % u)))[0]
    marks = json.load(open(HERE / ("tamper_live_marks_%s.json" % u)))
    me = "imsi-001010123456" + u
    F = [json.loads(l) for l in open(run + "/defense/features.jsonl")]
    F = [x for x in F if "c_t_w" in x and "prof_ul_pps" in x]
    raw = {}
    for l in open(run + "/defense/tamper.jsonl"):
        x = json.loads(l)
        if x.get("type") == "sample" and x["supi"] == me:
            raw[round(x["source_ts"])] = (x["raw"]["rate_ul_kbps"] * 125, x["tampered"]["rate_ul_kbps"] * 125)
    S = sorted([x for x in F if x["supi"] == me], key=lambda x: x["at_ms"])
    t = np.array([x["at_ms"] / 1e3 for x in S]); m = np.array([x["kpm_masked"] for x in S])
    gate = np.array([x["rate_ul_kbps"] * 125 >= 1000 or x["prof_ul_kbps"] * 125 >= 1000 for x in S])
    on = np.zeros(t.size, bool)
    print("UE", u, "seconds", t.size, "gate seconds", int(gate.sum()))
    for i, (f, t0, t1) in enumerate(marks):
        w = (t >= t0) & (t < t1); on |= w
        nxt = marks[i + 1][1] if i + 1 < len(marks) else t1 + 30
        j = np.flatnonzero(w & m)
        was = bool(m[np.flatnonzero(t < t0)[-1]]) if (t < t0).any() else False
        ttm = t[j[0]] - t0 if j.size else None
        tend = t[j[0]] if j.size else t1
        ks = [k for k in raw if t0 <= k < t1]
        tot = sum(raw[k][0] for k in ks)
        before = sum(abs(raw[k][0] - raw[k][1]) for k in ks if k < tend)
        gs = int((w & gate).sum()); gb = int((w & gate & (t < tend)).sum())
        share = float(m[w & gate].mean()) if gs else float("nan")
        after = (t >= t1) & (t < nxt) & ~m
        rec = t[after][0] - t1 if after.any() and (m[(t >= t1) & (t < nxt)]).any() else (0.0 if after.any() else None)
        rows.append(dict(ue=u, factor=f, was_masked=was, time_to_mask=ttm, gate_s=gs, gate_s_before=gb, raw_ul=tot, wrong_before=before, share=share, recover=rec))
        print(" x%-5s masked at start %-5s | time to mask %6s s (%d of %d gate s before) | UL %8.0f B | misreported before mask %7.0f B | masked on gate s %5.1f%% | recovery %s s" % (f, was, "%.1f" % ttm if ttm is not None else "never", gb, gs, tot, before, 100 * share, "%.1f" % rec if rec is not None else "no"))
    # first honest stretch ends 1 s before the first episode; honest elsewhere excludes on seconds and the recovery tail of 30 s windows
    pre = t < marks[0][1]
    print(" honest before first episode: gate s %d, masked %.2f%%" % ((pre & gate).sum(), 100 * m[pre & gate].mean() if (pre & gate).any() else 0))
    post = t >= marks[-1][2] + 30
    print(" honest after last episode + 30 s: gate s %d, masked %.2f%%" % ((post & gate).sum(), 100 * m[post & gate].mean() if (post & gate).any() else 0))
    O = [x for x in F if x["supi"] != me]
    ot = np.array([x["at_ms"] / 1e3 for x in O]); om = np.array([x["kpm_masked"] for x in O])
    og = np.array([x["rate_ul_kbps"] * 125 >= 1000 or x["prof_ul_kbps"] * 125 >= 1000 for x in O])
    c = np.array([x["c_t"] for x in O]); cw = np.array([x["c_t_w"] for x in O])
    print(" other UE (honest throughout): gate s %d, masked %.2f%%, 1 s out %.2f%%, 3 s out %.2f%%" % (og.sum(), 100 * om[og].mean(), 100 * (abs(c[og]) > .2).mean(), 100 * (abs(cw[og]) > .2).mean()))
print("\nby factor (both runs, episodes with a mask at start excluded from time to mask):")
for f in sorted({r["factor"] for r in rows}):
    R = [r for r in rows if r["factor"] == f]
    v = [r["time_to_mask"] for r in R if r["time_to_mask"] is not None and not r["was_masked"]]
    print(" x%-5s episodes %d masked %d | fresh time to mask %s | misreported before mask %s B | UL in episode %s B | gate s %s" % (f, len(R), sum(r["time_to_mask"] is not None for r in R), ["%.1f" % x for x in v], [int(r["wrong_before"]) for r in R], [int(r["raw_ul"]) for r in R], [r["gate_s"] for r in R]))
json.dump(rows, open(HERE / "tamper_live_results.json", "w"), indent=0)
