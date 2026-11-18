#!/usr/bin/env python3
"""Escalation by response, offline (2026-11-13): replays the level-2 -> level-3 rule of the xApp (classifier.c
escalate(), esc_rule.h) on every level-2 stay of end-to-end runs, for several relative ratios rho:
  over in an active second (offered UL >= 8 kbit/s) when offered > max((1 + over) x cap, rho x ref),
  ref = median of the first refS active seconds at level 2; fires after graceS when this second is over and k of the
  last n active seconds are over.
Input series of a stay:
  - runs with the relative rule (clf lines carry esc_offered / esc_since_ms): exactly the inputs the xApp used, so the
    replay is exact for every rho (in shadow mode the series does not depend on the rule); the online result
    (esc_would, at the rho the run was configured with) and the online reference (esc_ref) are checked against it;
  - older runs: offered UL of features.jsonl per second, from the second after the level event (the xApp scores a
    second before acting on it), time at level 2 counted from there (exact for the absolute rule, rho 0, up to the old
    exit; checked by reproducing the escalations by response of the run).
A stay ends at the next level change of the UE (the replay never looks past it).
Rho choice (fixed before the calibration, nhật ký 2026-11-13): the smallest rho of the list with 0 benign stays
escalated; if none, the one with the fewest, ties to the smaller.
Usage (repo root): esc_calib.py --manifest M [--manifest M2 ...] [--rhos 0,0.3,0.5,0.7] [--out research/clf/ESC_calib.txt]
                   [--export stays.csv]   (series + expected escalation per rho, for tests/xapp/test_esc_rule.c)"""
import argparse, json, pathlib, sys
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", action="append", required=True)
ap.add_argument("--rhos", default="0,0.3,0.5,0.7")
ap.add_argument("--out"); ap.add_argument("--export")
ap.add_argument("--cap-ul-kbps", type=float, default=32.0)
b = ap.parse_args()
RHOS = [float(x) for x in b.rhos.split(",")]
SRC = open("scripts/ml/e2e_report.py").read().split("\nEP, BEN, FRC")[0]   # loaders only
L = []
P = lambda s="": (L.append(s), print(s))


def rule(ser, rho, cap, refS=3, grace=5.0, k=8, n=10, over=0.25):
    """ser: [(seconds since level 2, offered kbit/s or < 0 when late)] -> seconds since level 2 at the escalation, or None"""
    hist, ref = [], []
    for s, v in ser:
        if v >= 8 and len(ref) < refS:
            ref.append(v)
        thr = max((1 + over) * cap, rho * float(np.median(ref)) if ref else 0.0)
        o = cap > 0 and v > thr
        if v >= 8:
            hist.append(o)
        if s < grace or not o or v < 8:
            continue
        h = hist[-n:]
        if len(h) >= n and sum(h) >= k:
            return s
    return None


def esc_cfg(design, r):
    d = r.get("defense") or design.get("defense") or {}
    e = dict(dict(enabled=True, graceS=5, hits=8, samples=10, overRatio=0.25, relRatio=0.0, refS=3, shadow=False), **d.get("escalation", {}))
    return e


STAYS, CLIENT = [], []
for man in b.manifest:
    ns = {}
    sys.argv = [sys.argv[0], "--manifest", man, "--cap-ul-kbps", str(b.cap_ul_kbps)]
    exec(SRC, ns)
    design = json.loads((pathlib.Path(man) / "design.json").read_text())
    for rid in sorted(ns["KEPT"]):
        r = ns["DESIGN"][rid]; d = ns["KEPT"][rid]
        meta, ev, clf, audit, flows, ph, dn = ns["load"](d)
        cfg = esc_cfg(design, r)
        new = any("esc_offered" in c for c in clf)
        F = {}
        if not new:
            for l in open(d / "defense/features.jsonl"):
                x = json.loads(l); F.setdefault(x["supi"], {})[int(x["collect_ms"] // 1000)] = x.get("prof_ul_kbps", 0.0)
        # benign L3 client seconds at level 0 (closed-loop criteria; features vs the open-loop clients of older runs)
        Fx = {}
        for l in open(d / "defense/features.jsonl"):
            x = json.loads(l); Fx[(x["supi"], int(x["collect_ms"] // 1000))] = x
        Z = {(c["supi"], int(c["t"])): c.get("z") for c in clf}
        # attack bytes sent per second in the run (the other UE's flood shares the cell, the UPF and the DN with the client)
        AS = {}
        for f in flows:
            if (f.get("v4_meta") or {}).get("role") == "attack":
                for t, v in ns["sent_flow"](f).items():
                    AS[t] = AS.get(t, 0) + v
        for f in flows:
            m = f.get("v4_meta") or {}
            if m.get("model") != "flood_overlay" or m.get("role") != "benign" or not str(f.get("dir", "")).startswith("ul"):
                continue
            supi = meta["ues"][f["ue"]]["supi"]; steps = ns["level_at"](ev, supi)
            for row in f.get("rows", []):
                t = int(np.floor(row["t"]))
                if ns["lvl"](steps, t + .5) != 0:
                    continue
                x = Fx.get((supi, t + 1), {})                 # a row of second t is counted in the profile second t+1 (as qa_twin)
                CLIENT.append(dict(man=pathlib.Path(man).parent.name, run=rid, backend=m.get("backend"), closed=bool(row.get("closed_loop")),
                                   target=row.get("target_pkts"),
                                   # sent: queries sent (dns) / connections opened (tcp: "started"; sent_pkts counts the
                                   # exchanges that ENDED in the second, one second late for a connection opened near its end)
                                   sent=row.get("started", row.get("sent_pkts")), skipped=row.get("skipped"),
                                   bytes=row.get("bytes") or 0, ul=x.get("prof_ul_kbps"), pps=x.get("prof_ul_pps"), z=Z.get((supi, t + 1)),
                                   attack_on=AS.get(t, 0) > 0))
        for ue in ("ue1", "ue2"):
            supi = meta["ues"][ue]["supi"]
            role = "attack" if ue == r.get("attacker") else "benign"
            LV = [e for e in ev if e["type"] == "level" and e["supi"] == supi]
            C = sorted((c for c in clf if c["supi"] == supi), key=lambda c: c["scored_ms"])
            for i, e in enumerate(LV):
                if e["level"] != 2:
                    continue
                t0 = e["at_ms"] / 1000; nx = LV[i + 1] if i + 1 < len(LV) else None
                t1 = nx["at_ms"] / 1000 if nx else ph["p7"][1]
                # the phase of the stay and, for a forced limit, its kind (design phase "force")
                pn = next((k for k, (x0, x1) in ph.items() if x0 - 10 <= t0 < x1), None)
                pd = next((p for p in r["phases"] if p["name"] == pn), {})
                fo = pd.get("force") or {}
                fo = next((f for f in (fo if isinstance(fo, list) else [fo]) if f.get("ue") == ue), {}) if fo else {}
                kind = fo.get("kind", "twin") if e["why"] == "forced" else e["why"]
                on_esc = nx is not None and nx["level"] >= 3 and any(
                    c.get("esc") and abs(c["scored_ms"] - nx["at_ms"]) <= 1500 for c in C)
                on_blk = nx is not None and nx["level"] >= 3 and not on_esc
                if new:
                    rows = [c for c in C if t0 * 1000 <= c["scored_ms"] <= t1 * 1000 + 500 and c.get("esc_since_ms", -1) >= 0]
                    ser = [(c["esc_since_ms"] / 1000.0, float(c["esc_offered"])) for c in rows]
                    would = next((c["esc_since_ms"] / 1000.0 for c in rows if c.get("esc_would")), None)
                    refs = [(c["esc_ref"], c["esc_ref_n"]) for c in rows]
                else:
                    # as the xApp: escalate() runs before the decision of a second, so the second of the level event is
                    # not counted and the time at level 2 starts one second later (esc_since_ms of the new runs)
                    ser = [(float(s - 1), F[supi].get(int(t0) + s, 0.0)) for s in range(1, int(round(t1 - t0)) + 1)]
                    would, refs = None, []
                STAYS.append(dict(man=pathlib.Path(man).parent.name, run=rid, ue=ue, role=role, evasion=r.get("evasion") or pd.get("evasion"),
                                  why=e["why"], kind=kind, t0=t0, dur=t1 - t0, ser=ser, new=new, cfg=cfg, on_esc=on_esc, on_blk=on_blk,
                                  would=would, refs=refs, next=(nx or {}).get("level")))

CAP = b.cap_ul_kbps
kw = lambda s: dict(refS=int(s["cfg"]["refS"]), grace=float(s["cfg"]["graceS"]), k=int(s["cfg"]["hits"]), n=int(s["cfg"]["samples"]),
                    over=float(s["cfg"]["overRatio"]))
for s in STAYS:
    s["sim"] = {rho: rule(s["ser"], rho, CAP, **kw(s)) for rho in RHOS}

P("Escalation by response, offline replay of the xApp rule; manifests: %s" % ", ".join(b.manifest))
P("level-2 stays: %d (attack %d, benign %d); cap %.0f kbit/s; rhos %s" % (
    len(STAYS), sum(s["role"] == "attack" for s in STAYS), sum(s["role"] == "benign" for s in STAYS), CAP, RHOS))

# checks: the replay against what the xApp did
P("\n== Checks against the runs")
old = [s for s in STAYS if not s["new"] and not s["cfg"].get("shadow") and float(s["cfg"].get("relRatio", 0)) == 0 and s["cfg"].get("enabled")]
if old:
    ok = sum((s["sim"].get(0.0) is not None) == s["on_esc"] for s in old)
    P("absolute-rule runs: replay at rho 0 escalates exactly the stays the xApp escalated by response: %d of %d" % (ok, len(old)))
    for s in old:
        if (s["sim"].get(0.0) is not None) != s["on_esc"]:
            P("  differs: %s %s %s why %s, xApp %s, replay %s" % (s["man"], s["run"], s["ue"], s["why"], s["on_esc"], s["sim"].get(0.0)))
nw = [s for s in STAYS if s["new"]]
if nw:
    bad = 0
    for s in nw:
        rho = float(s["cfg"].get("relRatio", 0))
        sim = rule(s["ser"], rho, CAP, **kw(s))
        if (sim is None) != (s["would"] is None) or (sim is not None and abs(sim - s["would"]) > 1e-6):
            bad += 1; P("  online/replay differ: %s %s %s why %s, online %s, replay %s" % (s["man"], s["run"], s["ue"], s["why"], s["would"], sim))
    P("relative-rule runs: online result (esc_would at the configured rho) equals the replay: %d of %d" % (len(nw) - bad, len(nw)))
    dref, nsec, nbad, ex = 0.0, 0, 0, []
    for s in nw:
        ref = []
        for (sec, v), (cref, cn) in zip(s["ser"], s["refs"]):
            if v >= 8 and len(ref) < int(s["cfg"]["refS"]):
                ref.append(v)
            nsec += 1
            if cn != len(ref):
                nbad += 1; ex.append((s["run"], s["ue"], sec, v, cn, len(ref)))
            else:
                dref = max(dref, abs((float(np.median(ref)) if ref else 0.0) - cref))
    P("online reference (esc_ref) vs replay: %d of %d seconds with the same count, max difference %.6f kbit/s" % (nsec - nbad, nsec, dref))
    for e in ex[:1] + [x for x in ex if x[:2] != ex[0][:2]][:4]:
        P("  count differs: %s %s at %.0f s (offered %.1f): online n %d, replay n %d" % e)


def table(sel, title):
    P("\n== " + title)
    P("%-34s %5s " % ("group", "stays") + " ".join("rho %-4s" % r for r in RHOS))
    groups = {}
    for s in sel:
        groups.setdefault(s["grp"], []).append(s)
    for g in sorted(groups):
        G = groups[g]
        P("%-34s %5d " % (g, len(G)) + " ".join("%8d" % sum(s["sim"][r] is not None for s in G) for r in RHOS))
    P("%-34s %5d " % ("all", len(sel)) + " ".join("%8d" % sum(s["sim"][r] is not None for s in sel) for r in RHOS))


B = [s for s in STAYS if s["role"] == "benign"]
for s in B:
    s["grp"] = "%s / %s" % (s["man"], s["kind"])
table(B, "Benign stays escalated (wrong), by kind of level-2 entry")
for s in B:
    hits = ["rho %s at %.0f s" % (r, s["sim"][r]) for r in RHOS if s["sim"][r] is not None]
    if hits:
        P("  %s %s %s %s (%s): %s" % (s["man"], s["run"], s["ue"], s["kind"], "%.0f s at level 2" % s["dur"], ", ".join(hits)))
A = [s for s in STAYS if s["role"] == "attack"]
for s in A:
    s["grp"] = "%s / %s / %s" % (s["man"], s["evasion"], s["why"])
table(A, "Attacker stays escalated (right), by level of evasion and entry")
for r in RHOS:
    t = [s["sim"][r] for s in A if s["sim"][r] is not None]
    P("rho %s: time at level 2 before the escalation, attacker: median %s s, max %s s" % (
        r, "%.0f" % np.median(t) if t else "-", "%.0f" % max(t) if t else "-"))

cnt = {r: sum(s["sim"][r] is not None for s in B) for r in RHOS}
zero = [r for r in RHOS if cnt[r] == 0]
pick = min(zero) if zero else min(RHOS, key=lambda r: (cnt[r], r))
P("\n== Rho by the fixed rule: %s (benign stays escalated per rho: %s)" % (pick, ", ".join("%s: %d" % (r, cnt[r]) for r in RHOS)))

if CLIENT:
    P("\n== Benign L3 clients at level 0 (closed loop: criteria fixed before the calibration)")
    cl = [c for c in CLIENT if c["closed"] and c["target"]]
    if cl:
        for be in sorted({c["backend"] for c in cl}) + ["all"]:
            G = [c for c in cl if be in ("all", c["backend"])]
            ok = np.mean([c["sent"] >= 0.98 * c["target"] for c in G]); sk = np.mean([not c["skipped"] for c in G])
            P("closed loop %-14s seconds %5d: sent >= 0.98 x schedule in %.4f (need >= 0.99); skipped 0 in %.4f (need >= 0.99) -> %s" % (
                be, len(G), ok, sk, "PASS" if ok >= 0.99 and sk >= 0.99 else "FAIL"))
        P("  split by whether a flood is sent in the same second (descriptive; the criterion above is the fixed one):")
        for be in sorted({c["backend"] for c in cl}):
            for on in (False, True):
                G = [c for c in cl if c["backend"] == be and c["attack_on"] == on]
                if G:
                    P("    %-14s flood %-3s seconds %5d: sent >= 0.98 x schedule in %.4f; skipped 0 in %.4f" % (
                        be, "on" if on else "off", len(G), np.mean([c["sent"] >= 0.98 * c["target"] for c in G]), np.mean([not c["skipped"] for c in G])))
    P("features of the UE in the seconds its benign L3 client sends, level 0 (median / p90):")
    for man in sorted({c["man"] for c in CLIENT}):
        for be in sorted({c["backend"] for c in CLIENT}):
            G = [c for c in CLIENT if c["man"] == man and c["backend"] == be and c["bytes"] > 0 and c["ul"] is not None]
            if not G:
                continue
            q = lambda k: "%.1f / %.1f" % tuple(np.percentile([c[k] for c in G if c[k] is not None], [50, 90]))
            P("  %-26s %-14s %s  n %5d  UL kbit/s %s  pps %s  z %s" % (man, be, "closed" if G[0]["closed"] else "open  ", len(G), q("ul"), q("pps"), q("z")))

if b.export:
    with open(b.export, "w") as f:
        f.write("stay,since_ms,offered\n")
        for i, s in enumerate(STAYS):
            for sec, v in s["ser"]:
                f.write("%d,%d,%.6f\n" % (i, round(sec * 1000), v))
    with open(b.export.replace(".csv", "_expected.csv"), "w") as f:
        f.write("stay,rho,fire_ms,refS,graceS,hits,samples,overRatio,cap\n")
        for i, s in enumerate(STAYS):
            for r in RHOS:
                x = s["sim"][r]
                f.write("%d,%s,%d,%d,%s,%d,%d,%s,%s\n" % (i, r, -1 if x is None else round(x * 1000), int(s["cfg"]["refS"]), s["cfg"]["graceS"],
                                                         int(s["cfg"]["hits"]), int(s["cfg"]["samples"]), s["cfg"]["overRatio"], CAP))
    P("exported %d stays to %s" % (len(STAYS), b.export))
if b.out:
    pathlib.Path(b.out).write_text("\n".join(L) + "\n")
