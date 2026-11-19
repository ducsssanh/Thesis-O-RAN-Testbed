#!/usr/bin/env python3
"""Live detection report (plan step 3): the decisions of the whole xApp (gate, embedded model, guards, escalation ladder) in
observe mode, per attack episode, read from each run's defense/clf.jsonl. Episode = one UE in one 75 s phase, as offline:
the alarm of an operating point is its first decision in the episode; before the onset it is a false alarm, and the benign
time of the episode stops there. Rate limit = an attack decision (want level >= 2), block = want level 3.
Live against offline on the same runs: scripts/ml/live_parity.py.
Usage: live_report.py <manifest dir> <out.txt> [--json out.json] [--boot 300]"""
import argparse, glob, json, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ml"))
ap = argparse.ArgumentParser(); ap.add_argument("manifest"); ap.add_argument("out"); ap.add_argument("--json", default=""); ap.add_argument("--boot", type=int, default=300)
a = ap.parse_args()
DELTA, PI = .2, {"P1": .50, "P2": .40, "P3": .09, "P4": .01}
L = [json.loads(l) for l in open(pathlib.Path(a.manifest) / "campaign_log.jsonl")]
kept = {}
for x in L:
    if x["event"] == "kept":
        kept[x["id"]] = x["run"]
design = {r["id"]: r for r in json.load(open(pathlib.Path(a.manifest) / "design.json"))["runs"]}


def episodes(run_dir, rid):
    """Episodes of one run from flows.json (twin seconds, onset) and the run's xApp decisions (clf.jsonl)."""
    run = pathlib.Path(run_dir)
    meta = json.loads((run / "run.json").read_text()); supi = {u: m["supi"] for u, m in meta["ues"].items()}
    flows = json.loads((run / "traffic/flows.json").read_text())
    D = {}
    for l in open(run / "defense/clf.jsonl"):
        o = json.loads(l); D[(o["supi"], o["t"])] = o
    man = {p["name"]: p for p in design[rid]["phases"]}
    out = []
    for f in flows:
        m = f.get("v4_meta") or {}
        if m.get("model") != "real_window":
            continue
        ph = man[f["phase"]]; s0 = int(np.floor(f["replay_start_at"])) + 1
        att = next((g for g in flows if g["phase"] == f["phase"] and g["ue"] == f["ue"] and (g.get("v4_meta") or {}).get("model") == "flood_overlay"
                    and (g.get("v4_meta") or {}).get("role", "attack") == "attack"), None)
        on = (int(att["attack_start_at"]) + 1 + att["v4_meta"]["onset_s"] - s0) if att else 75
        dec = [D.get((supi[f["ue"]], s0 + i)) for i in range(75)]
        soft = [bool(d and d["label"] == "attack" and d["want_level"] >= 2) for d in dec]
        block = [bool(d and d["want_level"] >= 3) for d in dec]
        act = [bool(d and np.expm1(d["x"][0]) >= 8.0) for d in dec]   # step 2: active seconds (core UL >= 8 kbit/s, as the xApp)
        out.append(dict(active=act, run=rid, phase=f["phase"], ue=f["ue"], supi=supi[f["ue"]], attack=att is not None, ev=ph.get("evasion", "") if att else "",
                        case=ph.get("case", "") if att else "", other_case=ph.get("case", "benign_only") if not att else "", band=m["band"], on=on,
                        soft=soft, block=block, missing=sum(d is None for d in dec), masked=[bool(d and d["masked"]) for d in dec],
                        z=[d["z"] if d else np.nan for d in dec]))
    return out


def outcome(e, al):
    on = e["on"]; first = next((t for t, v in enumerate(al) if v), -1)
    stop = first if first >= 0 else 75; early = 0 <= first < on
    end = first if first >= on else 75
    return dict(undet_act=sum(e["active"][on:end]) if e["attack"] else np.nan, det=e["attack"] and first >= on, early=early, benign_s=min(stop, on) + int(early), delay=(first - on + DELTA) if e["attack"] and first >= on else np.nan,
                undet=((first - on + DELTA) if first >= on else 75 - on) if e["attack"] else np.nan)


def summarise(E, key):
    R = [dict(e, **outcome(e, e[key])) for e in E]
    att = [r for r in R if r["attack"]]
    h = sum(r["benign_s"] for r in R) / 3600
    by = {}
    for r in R:
        v = by.setdefault(r["band"], [0, 0]); v[0] += r["early"]; v[1] += r["benign_s"] / 3600
    return dict(n=len(att), det=100 * np.mean([r["det"] for r in att]) if att else np.nan,
                delay=float(np.nanmedian([r["delay"] for r in att])) if any(r["det"] for r in att) else np.nan,
                undet=float(np.nanmean([r["undet"] for r in att])) if att else np.nan,
                undet_act=float(np.nanmean([r["undet_act"] for r in att])) if att else np.nan,
                fa=sum(r["early"] for r in R) / h if h else np.nan, fa_real=sum(PI[b] * v[0] / v[1] for b, v in by.items() if v[1] > 0), benign_h=h)


rng = np.random.default_rng(0)


def ci(E, key, stat):
    runs = sorted({e["run"] for e in E}); by = {r: [e for e in E if e["run"] == r] for r in runs}; v = []
    for _ in range(a.boot):
        S = [x for i in rng.integers(len(runs), size=len(runs)) for x in by[runs[i]]]
        v.append(summarise(S, key)[stat])
    return np.nanpercentile(v, [2.5, 97.5])


E = [e for rid, rd in sorted(kept.items()) for e in episodes(rd, rid)]
lines = ["Live detection, observe mode: %d runs kept, %d episodes (%d attack), missing decisions %.2f%%" % (
    len(kept), len(E), sum(e["attack"] for e in E), 100 * sum(e["missing"] for e in E) / (75 * len(E)))]
CASES = [c for c in ("honest", "mimic", "hide0.33", "hide0.1") if any(e["case"] == c for e in E)]
res = {}
for key, name in (("soft", "Rate limit (budget 2)"), ("block", "Block (0.5, 20 of 30 s)")):
    lines.append("\n" + name)
    lines.append("  group            n   detected [95% CI]       median delay s   undetected s (active s)   FA /UE-h (real)")
    for g, sel in [("all", lambda e: True)] + [(L_ + " " + c, (lambda L_, c: lambda e: (not e["attack"]) or (e["ev"] == L_ and e["case"] == c))(L_, c))
                                                for L_ in ("L1", "L2", "L3") for c in CASES]:
        S = [e for e in E if sel(e)]
        if not any(e["attack"] for e in S):
            continue
        s = summarise(S, key); lo, hi = ci(S, key, "det")
        res.setdefault(key, {})[g] = dict(s, det_ci=[float(lo), float(hi)])
        lines.append("  %-14s %4d   %5.1f [%5.1f, %5.1f]      %5.1f           %5.1f (%5.1f)        %s" % (
            g, s["n"], s["det"], lo, hi, s["delay"], s["undet"], s["undet_act"], ("%.2f (%.2f) over %.1f h" % (s["fa"], s["fa_real"], s["benign_h"])) if g == "all" else ""))
# X1: detection and delay by the UE's own past before the onset (seconds of its episode before the attack)
lines.append("\nX1 by own past before the onset (rate limit / block): bin  n  detected  median delay")
for lo, hi in ((0, 4), (4, 8), (8, 12), (12, 16)):
    S = [e for e in E if e["attack"] and lo <= e["on"] < hi]
    if S:
        a1, b1 = summarise(S, "soft"), summarise(S, "block")
        lines.append("  %2d-%2d s  %3d   %5.1f / %5.1f   %4.1f / %4.1f s" % (lo, hi - 1, len(S), a1["det"], b1["det"], a1["delay"], b1["delay"]))
# X8: by band of the UE (attack: its own twin band; false alarms per band on benign time)
lines.append("\nX8 by band: attack episodes detected (rate limit / block) | false alarms per benign UE-hour (rate limit / block)")
for b in ("P1", "P2", "P3", "P4"):
    S = [e for e in E if e["band"] == b]
    if S:
        a1, b1 = summarise(S, "soft"), summarise(S, "block")
        lines.append("  %s  n_att %3d  %5.1f / %5.1f  |  %.2f / %.2f over %.2f h" % (b, a1["n"], a1["det"], b1["det"], a1["fa"], b1["fa"], a1["benign_h"]))
# gate under hiding: share of attack seconds with the attacker's KPM masked
for c in CASES:
    S = [e for e in E if e["attack"] and e["case"] == c]
    if S:
        m = np.mean([np.mean(e["masked"][e["on"]:]) for e in S if e["on"] < 75])
        lines.append("gate, %s: attacker KPM masked in %.0f%% of attack seconds" % (c, 100 * m))
pathlib.Path(a.out).write_text("\n".join(lines) + "\n"); print("\n".join(lines))
if a.json:
    json.dump(res, open(a.json, "w"), indent=1, default=float)
