#!/usr/bin/env python3
"""End-to-end mitigation report (advisor, 2026-11-13): per attack episode of the end-to-end runs (actions on), the four
quantities the advisor asked for, plus the cost on the benign UE.
  1. attack bytes reaching the DN: sent by the attack generator vs counted at the DN's N6 on the attack flow's port
     (IP bytes: UDP payload + 28 per packet; ICMP 28 B and SYN 40 B per packet), split by the attacker's level in that
     second (0 / limit 1-2 / block >= 3);
  2. decision -> effect: decision = level event (at_ms); RAN = E2 control acknowledged (sent_unix_ms + ack_latency_ms);
     UPF = policy written (UPF audit ts_ms); effect at the DN = first second from which the attack bytes stay within the
     level (limit: <= 1.25 x the UPF cap; block: 0) in 3 active seconds (seconds in which the generator sends more than
     that), looked for only while the UE stays at that level (not measurable if there are fewer than 3 such seconds);
  3. escalation at L2: limit -> block transitions, by the block rule or by escalation by response (clf line esc), and
     the time spent at the limit level;
  4. TTL: after the last attack label, when each level ran out (expected the e2e ladder 120 / 60 / 30 s), the UPF policy
     removed, the attacker UE's own benign flow back (DN / sent) and its reactive multiplier back to 1; the second attack
     (p6): delay and level reached.
  Benign UE: seconds above level 0, decisions on it, delivered share of its reactive flow, lowest multiplier.
  Calibration runs with forced limits (benign only): per forced limit, escalation to block (wrong) and the time until
  the reactive flow sends within the cap.
Usage (repo root): e2e_report.py --manifest research/datasets/oran_flooding_e2e/manifest [--out research/clf/E2E_report.txt]"""
import argparse, csv, json, pathlib, sys
import numpy as np

ap = argparse.ArgumentParser(); ap.add_argument("--manifest", required=True); ap.add_argument("--out")
ap.add_argument("--cap-ul-kbps", type=float, default=32.0)
a = ap.parse_args()
M = pathlib.Path(a.manifest)
DESIGN = {r["id"]: r for r in json.loads((M / "design.json").read_text())["runs"]}
KEPT = {}
for l in (M / "campaign_log.jsonl").read_text().splitlines():
    x = json.loads(l)
    if x.get("event") == "kept":
        KEPT[x["id"]] = pathlib.Path(x["run"])
    elif x.get("event") == "rejected":   # rejected after the fact by a later QA check (campaign_twin.done_ids)
        KEPT.pop(x["id"], None)
CAP_B = a.cap_ul_kbps * 125.0                       # bytes/s
IPLEN = {"icmp": 28, "syn": 40}
L = []
P = lambda s="": (L.append(s), print(s))


def jl(p):
    return [json.loads(x) for x in open(p)] if p.exists() and p.stat().st_size else []


def load(run_dir):
    d = run_dir
    meta = json.loads((d / "run.json").read_text())
    ev = jl(d / "defense/events.jsonl")
    clf = jl(d / "defense/clf.jsonl")
    audit = jl(d / "core/upf_audit.jsonl")
    flows = json.loads((d / "traffic/flows.json").read_text())
    ph = {r["phase"]: (float(r["t_start_unix"]), float(r["t_end_unix"])) for r in csv.DictReader(open(d / "phases.csv"))}
    dn = {}
    for r in csv.DictReader(open(d / "dataplane/dn_per_second.csv")):
        k = (int(r["t"]), r["ue_ip"], r["dir"], r.get("proto", ""), r.get("dn_port", ""))
        p, b = dn.get(k, (0, 0)); dn[k] = (p + int(r["pkts"]), b + int(r["ip_payload_bytes"]))
    return meta, ev, clf, audit, flows, ph, dn


def ue_ip(meta, ue):
    h = meta["ues"][ue]["ip_history"]
    return h[-1][1] if h else None


def level_at(ev, supi):
    """step function: list of (t_s, level) for a SUPI"""
    out = [(0.0, 0)]
    for e in ev:
        if e["type"] == "level" and e["supi"] == supi:
            out.append((e["at_ms"] / 1000.0, e["level"]))
    return out


def lvl(steps, t):
    v = 0
    for ts, l in steps:
        if ts <= t:
            v = l
        else:
            break
    return v


def dn_flow(dn, ip, f):
    """per-second IP bytes at the DN of one UL flow"""
    proto, port, mode = f.get("proto"), str(f.get("port")), f.get("mode")
    out = {}
    for (t, i, d, pr, pt), (p, b) in dn.items():
        if i != ip or d != "ul":
            continue
        if mode == "icmp" and pr == "icmp":
            out[t] = out.get(t, 0) + p * IPLEN["icmp"]
        elif pr == "tcp" and proto == "tcp" and pt == port:
            out[t] = out.get(t, 0) + b + p * 40
        elif pr == "udp" and proto == "udp" and pt == port:
            out[t] = out.get(t, 0) + b + p * 28
    return out


def sent_flow(f):
    out = {}
    for r in f.get("rows", []):
        if r.get("final") or r.get("bytes") is None:
            continue
        t = int(np.floor(r["t"])); out[t] = out.get(t, 0) + float(r["bytes"])
    return out


def first_effect(t_dec, sent, got, limit, end):
    """first active second s >= t_dec (the generator sends above the level in it) such that it and the next 2 active seconds
    in the window all have got <= limit; returns s - t_dec. Active seconds, not calendar seconds: an ON/OFF flood that
    never sends 3 seconds in a row is still measured (2026-11-13 fix: the calendar-second version waited for a 3-second
    burst, e.g. 60.8 s on an ON/OFF mimic flood whose bytes at the DN were 0 throughout the block)."""
    act = [x for x in range(int(np.ceil(t_dec)), end + 1) if sent.get(x, 0) > limit]
    for i in range(len(act) - 2):
        if all(got.get(x, 0) <= limit for x in act[i:i + 3]):
            return act[i] - t_dec, i      # i = active seconds that still got through above the level (the lag counts silent seconds too)
    return None


def episode(name_set, r, meta, ev, clf, audit, flows, ph, dn):
    att = r["attacker"]; supi = meta["ues"][att]["supi"]; ip = ue_ip(meta, att)
    t0, t1 = ph[name_set[0]][0], ph[name_set[-1]][1]
    af = [f for f in flows if f["phase"] in name_set and f["ue"] == att and f.get("role") == "attack"]
    sent, got = {}, {}
    for f in af:
        for t, b in sent_flow(f).items(): sent[t] = sent.get(t, 0) + b
        for t, b in dn_flow(dn, ip, f).items(): got[t] = got.get(t, 0) + b
    act = sorted(t for t, b in sent.items() if b > 0)
    if not act:
        return None
    onset, last = act[0], act[-1]
    steps = level_at(ev, supi)
    lv = {t: lvl(steps, t + .5) for t in range(int(t0), int(t1) + 2)}
    split = {"before": [0, 0], "limit": [0, 0], "block": [0, 0]}
    for t in range(onset, int(t1) + 2):
        k = "before" if lv.get(t, 0) == 0 else "limit" if lv.get(t, 0) < 3 else "block"
        split[k][0] += sent.get(t, 0); split[k][1] += got.get(t, 0)
    S, G = sum(sent.values()), sum(got.values())
    lev = [e for e in ev if e["type"] == "level" and e["supi"] == supi and t0 <= e["at_ms"] / 1000 <= t1 + 1]
    up = [e for e in lev if e["level"] > e.get("from", 0) and e["why"] not in ("expired", "forced")]
    out = dict(run=r["id"], ev=r["evasion"], case=r["case"], onset=onset, sent_kB=S / 1e3, dn_kB=G / 1e3, red=(1 - G / S) if S else np.nan,
               split={k: (v[0] / 1e3, v[1] / 1e3) for k, v in split.items()}, ups=[(e["from"], e["level"], e["why"], e["at_ms"] / 1000 - onset) for e in up])
    out["first_dec"] = up[0]["at_ms"] / 1000 - onset if up else None
    out["exp_during"] = [(e["from"], e["level"], round(e["at_ms"] / 1000 - onset, 1)) for e in lev if e["why"] == "expired" and onset <= e["at_ms"] / 1000 <= last]
    out["peak"] = max([e["level"] for e in lev] + [lvl(steps, t0)])
    # decision -> effect, per first transition into the limit (2) and into the block (>= 3)
    for key, cond, limit, act_name, sd in (("lim", lambda l: l == 2, 1.25 * CAP_B, "ratelimit", "badbad"), ("blk", lambda l: l >= 3, 0.0, "block", "badb10")):
        e = next((x for x in up if cond(x["level"])), None)
        if e is None:
            out[key] = None; continue
        td = e["at_ms"] / 1000
        # the effect is looked for only while the UE stays at this level (a later block or expiry ends the window)
        t_next = next((x["at_ms"] / 1000 for x in lev if x["at_ms"] > e["at_ms"] and cond(x["level"]) != cond(e["level"])), t1 + 1)
        ran = next((x for x in ev if x["type"] == "action" and x["supi"] == supi and x.get("layer") == "ran" and x["at_ms"] >= e["at_ms"] - 1
                    and sd in str(x.get("slice", "")) and x.get("http") == 200), None)
        t_ran = (ran["result"]["sent_unix_ms"] + ran["result"].get("ack_latency_ms", 0)) / 1000 - td if ran and ran.get("result") else None
        upf = next((x for x in audit if x.get("supi") == supi and x.get("op") == "put" and x["ts_ms"] >= e["at_ms"] - 1
                    and (x.get("detail") or {}).get("action") == act_name), None)
        t_upf = upf["ts_ms"] / 1000 - td if upf else None
        # first verification of this action by the xApp's verifier, any layer (a block is verified on the RAN PRB share only)
        ver = next((x for x in ev if x["type"] == "verified" and x["supi"] == supi and e["at_ms"] <= x["at_ms"] <= e["at_ms"] + 60000
                    and cond(x.get("level", 0))), None)
        out[key] = dict(why=e["why"], from_=e["from"], t=td - onset, ran=t_ran, upf=t_upf, eff_leak=first_effect(td, sent, got, limit, min(int(t1) + 1, int(np.floor(t_next)) - 1)),
                        verified=(ver["at_ms"] - e["at_ms"]) / 1000 if ver else None)
        el = out[key].pop("eff_leak")
        out[key]["eff"], out[key]["leak"] = el if el else (None, None)
    # escalation at the limit level: by response (clf esc) or by the block rule
    e2 = next((x for x in up if x["from"] == 2 and x["level"] >= 3), None)
    if e2:
        esc = any(c.get("esc") and c["supi"] == supi and abs(c["scored_ms"] - e2["at_ms"]) <= 1500 for c in clf)
        t2 = next((x["at_ms"] for x in up if x["level"] == 2), None)
        out["esc"] = dict(by="response" if esc else "block rule", at_limit_s=(e2["at_ms"] - t2) / 1000 if t2 else None)
    else:
        out["esc"] = None
    out["last"] = last
    return out


def ttl(r, meta, ev, clf, audit, after, until):
    att = r["attacker"]; supi = meta["ues"][att]["supi"]
    lab = [c["scored_ms"] / 1000 for c in clf if c["supi"] == supi and c.get("label") in ("attack", 1, "1") and c["scored_ms"] / 1000 <= until]
    exp = [(e["from"], e["level"], e["at_ms"] / 1000) for e in ev if e["type"] == "level" and e["supi"] == supi and e["why"] == "expired" and after <= e["at_ms"] / 1000 <= until]
    if not exp:
        return None
    ups = [e["at_ms"] / 1000 for e in ev if e["type"] == "level" and e["supi"] == supi and e["level"] > e.get("from", 0) and e["why"] != "expired"]
    steps, prev = [], after
    for f, t, ts in exp:
        # each step is timed from the latest of: the previous expiry, the last attack label, the last level-up (re-escalation)
        ref = max([prev] + [x for x in lab if x <= ts] + [x for x in ups if x <= ts])
        steps.append((f, t, ts - ref)); prev = ts
    dele = next((x["ts_ms"] / 1000 for x in audit if x.get("supi") == supi and x.get("op") == "delete" and x["ts_ms"] / 1000 >= exp[0][2]), None)
    zero = next((ts for f, t, ts in exp if t == 0), None)
    return dict(steps=steps, upf_removed=(dele - zero) if dele and zero else None, zero=zero)


def own_benign(r, meta, flows, dn, ph, phases):
    """attacker UE's own reactive benign flow in the given phases: DN / sent and mean multiplier"""
    att = r["attacker"]; ip = ue_ip(meta, att)
    S = G = 0.0; m = []
    for f in flows:
        if f["phase"] in phases and f["ue"] == att and f.get("role") == "benign" and f.get("dir") == "ul":
            s = sent_flow(f); g = dn_flow(dn, ip, f)
            S += sum(s.values()); G += sum(g.values()); m += [x["mult"] for x in f.get("rows", []) if "mult" in x]
    return (G / S if S else np.nan), (np.mean(m) if m else np.nan), (min(m) if m else np.nan)


def benign_ue(r, meta, ev, clf, flows, dn, ph):
    other = [u for u in ("ue1", "ue2") if u != r.get("attacker")]
    out = []
    for u in other:
        supi = meta["ues"][u]["supi"]; ip = ue_ip(meta, u)
        steps = level_at(ev, supi); t0, t1 = ph["p0"][0], ph["p7"][1]
        above = sum(lvl(steps, t + .5) > 0 for t in range(int(t0), int(t1)))
        dec = [e for e in ev if e["type"] == "level" and e["supi"] == supi and e["level"] > e.get("from", 0) and e["why"] not in ("expired",)]
        S = G = 0.0; m = []
        for f in flows:
            if f["ue"] == u and f.get("role") == "benign" and f.get("dir") == "ul":
                s = sent_flow(f); g = dn_flow(dn, ip, f); S += sum(s.values()); G += sum(g.values())
                m += [x["mult"] for x in f.get("rows", []) if "mult" in x]
        nat = [e for e in dec if e["why"] != "forced"]   # the defence's own decisions (forced limits are the calibration's)
        blk = [("response" if any(c.get("esc") and c["supi"] == supi and abs(c["scored_ms"] - e["at_ms"]) <= 1500 for c in clf) else "block rule")
               for e in nat if e["level"] >= 3]
        out.append(dict(ue=u, above_s=above, decisions=[(e["from"], e["level"], e["why"]) for e in dec], delivered=G / S if S else np.nan,
                        mult_min=min(m) if m else np.nan, mult_lt1=np.mean([x < 1 for x in m]) if m else np.nan,
                        n_lim=sum(e["level"] == 2 for e in nat), blk=blk, hours=(t1 - t0) / 3600))
    return out


def forced(r, meta, ev, clf, flows, ph):
    """benign-only calibration run: per forced limit, escalation to block and time until the reactive flow is within the cap"""
    out = []
    for p in r["phases"]:
        if not p.get("force"):
            continue
        u = p["force"]["ue"]; supi = meta["ues"][u]["supi"]; t0, t1 = ph[p["name"]]
        fe = next((e for e in ev if e["type"] == "level" and e["supi"] == supi and e["why"] == "forced" and t0 - 10 <= e["at_ms"] / 1000 <= t1), None)
        if not fe:
            out.append(dict(phase=p["name"], ue=u, note="no forced event")); continue
        tf = fe["at_ms"] / 1000
        esc = [e for e in ev if e["type"] == "level" and e["supi"] == supi and e["level"] >= 3 and tf <= e["at_ms"] / 1000 <= tf + 61]
        f = next((x for x in flows if x["phase"] == p["name"] and x["ue"] == u and x.get("role") == "benign" and x.get("dir") == "ul"), None)
        s = sent_flow(f) if f else {}
        busy = [t for t in range(int(tf), int(tf) + 60) if s.get(t, 0) > 1.25 * CAP_B]
        # back-off: from the first second the reactive flow sends above the cap to the first of 3 seconds in a row within it
        within = None
        if busy:
            within = next((t - busy[0] for t in range(busy[0], int(tf) + 60) if all(s.get(x, 0) <= 1.25 * CAP_B for x in range(t, t + 3))), None)
        by = ["response" if any(c.get("esc") and c["supi"] == supi and abs(c["scored_ms"] - e["at_ms"]) <= 1500 for c in clf) else "block rule" for e in esc]
        out.append(dict(phase=p["name"], ue=u, escalated=bool(esc), why=by, over_cap_s=len(busy), within_cap_after=within))
    return out


def fmt(x, n=1):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else ("%.*f" % (n, x))


EP, BEN, FRC, TT, OWN = [], [], [], [], []
P("End-to-end mitigation report: %s (%d runs kept of %d)" % (M, len(KEPT), len(DESIGN)))
P("UPF cap at the limit level %.0f kbit/s; effect = attack bytes at the DN within 1.25 x cap (limit) or 0 (block) for 3 s" % a.cap_ul_kbps)
for rid in sorted(KEPT):
    r = DESIGN[rid]; d = KEPT[rid]
    meta, ev, clf, audit, flows, ph, dn = load(d)
    P("\n== %s  %s  KPM %s  attacker %s  (%s)" % (rid, r.get("evasion", "benign only"), r["case"], r.get("attacker", "-"), d))
    if r.get("benign_only"):
        for x in forced(r, meta, ev, clf, flows, ph):
            FRC.append(x)
            P("  forced limit %s %s: escalated to block %s %s, seconds over the cap %s, within the cap after %s s" % (
                x["phase"], x["ue"], x.get("escalated"), x.get("why", ""), x.get("over_cap_s"), fmt(x.get("within_cap_after"))))
        for b in benign_ue(dict(r, attacker=None), meta, ev, clf, flows, dn, ph):
            P("  benign %s: %d s above level 0, decisions %s, delivered %.3f, mult min %s, share of seconds with mult < 1 %s" % (
                b["ue"], b["above_s"], b["decisions"], b["delivered"], fmt(b["mult_min"], 2), fmt(b["mult_lt1"], 3)))
            BEN.append(b)
        continue
    for tag, names in (("first attack p1-p2", ("p1", "p2")), ("second attack p6", ("p6",))):
        e = episode(names, r, meta, ev, clf, audit, flows, ph, dn)
        if e is None:
            P("  %s: no attack sent" % tag); continue
        e["tag"] = tag; EP.append(e)
        P("  %s: sent %.1f kB, at the DN %.1f kB (reduction %.1f%%); first decision %s s after onset, peak level %d" % (
            tag, e["sent_kB"], e["dn_kB"], 100 * e["red"], fmt(e["first_dec"]), e["peak"]))
        P("    bytes sent / at the DN by level: before %.1f / %.1f kB, limit %.1f / %.1f kB, block %.1f / %.1f kB" % (
            *e["split"]["before"], *e["split"]["limit"], *e["split"]["block"]))
        for key, nm in (("lim", "limit"), ("blk", "block")):
            x = e[key]
            if x:
                P("    -> %s (%s, from %d) at +%.1f s: RAN acknowledged %s s, UPF written %s s, verified %s s, effect at the DN %s s (%s active seconds through)" % (
                    nm, x["why"], x["from_"], x["t"], fmt(x["ran"], 3), fmt(x["upf"], 3), fmt(x["verified"]), fmt(x["eff"]), x["leak"] if x["leak"] is not None else "-"))
        if e["esc"]:
            P("    limit -> block by %s after %s s at the limit" % (e["esc"]["by"], fmt(e["esc"]["at_limit_s"])))
        P("    level changes: %s" % [(f, l, w, round(t, 1)) for f, l, w, t in e["ups"]])
        if e["exp_during"]:
            P("    expired while the attack was still being sent (from, to, s after onset): %s" % e["exp_during"])
    end1 = ph["p2"][1]
    t = ttl(r, meta, ev, clf, audit, ph["p1"][0], ph["p6"][0])
    if t:
        TT.append(dict(run=rid, **t))
        P("  TTL after the first attack: %s; UPF policy removed %s s after level 0" % (
            ", ".join("%d->%d after %.1f s" % s for s in t["steps"]), fmt(t["upf_removed"])))
    else:
        P("  TTL after the first attack: no expiry before p6 (level still in force)")
    dl, mm, mn = own_benign(r, meta, flows, dn, ph, ("p3", "p4", "p5"))
    dl0, _, _ = own_benign(r, meta, flows, dn, ph, ("p0",))
    OWN.append(dict(run=rid, p0=dl0, quiet=dl, mult=mm, mult_min=mn))
    P("  attacker's own benign flow: delivered %.3f in p0, %.3f in p3-p5; multiplier mean %s, min %s in p3-p5" % (dl0, dl, fmt(mm, 2), fmt(mn, 2)))
    for b in benign_ue(r, meta, ev, clf, flows, dn, ph):
        P("  benign %s: %d s above level 0, decisions %s, delivered %.3f, mult min %s, share of seconds with mult < 1 %s" % (
            b["ue"], b["above_s"], b["decisions"], b["delivered"], fmt(b["mult_min"], 2), fmt(b["mult_lt1"], 3)))
        BEN.append(b)

if FRC:
    F = [x for x in FRC if "escalated" in x]
    w = [x["within_cap_after"] for x in F if x["within_cap_after"] is not None]
    P("\n== Forced limits on benign UEs (calibration): %d, escalated to block %d %s; back-off to within the cap median %s s, max %s s (n %d with traffic above the cap)" % (
        len(F), sum(x["escalated"] for x in F), [w_ for x in F for w_ in x["why"]], fmt(float(np.median(w)) if w else None), fmt(max(w) if w else None), len(w)))
if BEN:
    h = sum(b["hours"] for b in BEN); nl = sum(b["n_lim"] for b in BEN); bl = [y for b in BEN for y in b["blk"]]
    P("\n== Benign UEs (%d UE-runs, %.2f UE-hours): defence's own limits %d (%.2f per UE-hour), blocks %d (%.2f per UE-hour; by the block rule %d, by response %d); %d s above level 0 in total; delivered share median %.3f" % (
        len(BEN), h, nl, nl / h, len(bl), len(bl) / h, bl.count("block rule"), bl.count("response"), sum(b["above_s"] for b in BEN), np.nanmedian([b["delivered"] for b in BEN])))

if EP:
    P("\n== Summary over %d attack episodes" % len(EP))
    for tag in ("first attack p1-p2", "second attack p6"):
        E = [e for e in EP if e["tag"] == tag]
        if not E:
            continue
        S = sum(e["sent_kB"] for e in E); G = sum(e["dn_kB"] for e in E)
        P("  %s (n %d): attack bytes at the DN %.1f of %.1f kB sent (reduction %.1f%%); median per-episode reduction %.1f%%" % (
            tag, len(E), G, S, 100 * (1 - G / S), 100 * np.nanmedian([e["red"] for e in E])))
        for key, nm in (("lim", "limit"), ("blk", "block")):
            X = [e[key] for e in E if e[key]]
            if X:
                for fld, lab in (("ran", "RAN acknowledged"), ("upf", "UPF written"), ("eff", "effect at the DN (wall clock, includes seconds the generator was silent)")):
                    v = [x[fld] for x in X if x[fld] is not None]
                    if v:
                        P("    %s: %s median %.3f s, p90 %.3f, max %.3f (n %d of %d)" % (nm, lab, np.median(v), np.percentile(v, 90), max(v), len(v), len(X)))
                v = [x["verified"] for x in X if x["verified"] is not None]
                P("    %s: verified by the xApp in %d of %d, median %s s after the decision" % (nm, len(v), len(X), fmt(float(np.median(v)) if v else None)))
                lk = [x["leak"] for x in X if x["leak"] is not None]
                if lk:
                    P("    %s: within the level from the first second the generator sent after the decision in %d of %d measurable; otherwise after %s seconds that still got through" % (
                        nm, sum(k == 0 for k in lk), len(lk), sorted(k for k in lk if k)))
                P("    %s: effect not measurable in %d of %d (fewer than 3 seconds with the generator sending above the level while the UE was at it)" % (
                    nm, sum(x["eff"] is None for x in X), len(X)))
        for ev_ in ("L1", "L2", "L3"):
            Ee = [e for e in E if e["ev"] == ev_]
            if Ee:
                esc = [e["esc"] for e in Ee if e["esc"]]
                P("    %s: %d episodes, reached block %d (by the block rule %d, by response %d), never limited %d" % (
                    ev_, len(Ee), sum(e["peak"] >= 3 for e in Ee), sum(x["by"] == "block rule" for x in esc), sum(x["by"] == "response" for x in esc),
                    sum(e["first_dec"] is None for e in Ee)))


def boot(E, fn, B=2000, seed=0):
    """95% interval by resampling runs (all episodes of a run move together)"""
    rng = np.random.default_rng(seed)
    runs = sorted({e["run"] for e in E}); by = {k: [e for e in E if e["run"] == k] for k in runs}
    v = [fn([e for k in rng.choice(runs, len(runs), replace=True) for e in by[k]]) for _ in range(B)]
    return np.nanpercentile(v, [2.5, 97.5])


def red(E):
    S = sum(e["sent_kB"] for e in E)
    return 100 * (1 - sum(e["dn_kB"] for e in E) / S) if S else np.nan


def med_dec(E):
    v = [e["first_dec"] for e in E if e["first_dec"] is not None]
    return float(np.median(v)) if v else np.nan


if EP:
    P("\n== Run-level bootstrap (2000 resamples of runs, seed 0), 95%% intervals; %d runs" % len({e["run"] for e in EP}))
    for tag in ("first attack p1-p2", "second attack p6"):
        E = [e for e in EP if e["tag"] == tag]
        if not E:
            continue
        lo, hi = boot(E, red)
        P("  %s: reduction of attack bytes at the DN %.1f%% [%.1f, %.1f]" % (tag, red(E), lo, hi))
        lo, hi = boot(E, med_dec)
        v = [e["first_dec"] for e in E if e["first_dec"] is not None]
        P("    first decision after onset: median %s s [%s, %s], p90 %s s, decided %d of %d" % (
            fmt(med_dec(E)), fmt(lo), fmt(hi), fmt(float(np.percentile(v, 90)) if v else None), len(v), len(E)))
        G = sum(e["dn_kB"] for e in E)
        if G:
            P("    where the bytes at the DN got through: before the first decision %.1f%%, at the limit %.1f%%, at the block %.1f%%" % tuple(
                100 * sum(e["split"][k][1] for e in E) / G for k in ("before", "limit", "block")))
        xd = [e for e in E if e["exp_during"]]
        P("    a level expired while the attack was still being sent in %d of %d episodes (%s)" % (len(xd), len(E), ", ".join(e["run"] for e in xd)))
        for grp, key in (("level", "ev"), ("KPM", "case")):
            for g in sorted({e[key] for e in E}):
                Eg = [e for e in E if e[key] == g]
                lo, hi = boot(Eg, red)
                P("    %s %s (n %d): reduction %.1f%% [%.1f, %.1f], reached block %d, first decision median %s s" % (
                    grp, g, len(Eg), red(Eg), lo, hi, sum(e["peak"] >= 3 for e in Eg), fmt(med_dec(Eg))))
    L2 = [e for e in EP if e["ev"] == "L2" and e["tag"] == "first attack p1-p2"]
    if L2:
        esc = [e["esc"] for e in L2 if e["esc"]]
        at = [x["at_limit_s"] for x in esc if x["at_limit_s"] is not None]
        lk = [e["split"]["limit"][1] for e in L2]
        P("\n== Escalation at L2 (first attack, n %d): limited %d, then blocked %d (by response %d, by the block rule %d), stayed at the limit %d; time at the limit before the block median %s s (range %s to %s); attack bytes at the DN while at the limit median %.1f kB per episode" % (
            len(L2), sum(e["lim"] is not None for e in L2), len(esc), sum(x["by"] == "response" for x in esc), sum(x["by"] == "block rule" for x in esc),
            sum(e["lim"] is not None and not e["esc"] and e["peak"] < 3 for e in L2), fmt(float(np.median(at)) if at else None),
            fmt(min(at) if at else None), fmt(max(at) if at else None), float(np.median(lk))))
    E6 = [e for e in EP if e["tag"] == "second attack p6"]
    if E6:
        w = [e["ups"][0][2] for e in E6 if e["ups"]]
        P("== Second attack in probation (n %d): first level change by %s; first decision median %s s vs %s s on the first attack" % (
            len(E6), {k: w.count(k) for k in sorted(set(w))}, fmt(med_dec(E6)), fmt(med_dec([e for e in EP if e["tag"] == "first attack p1-p2"]))))
if TT:
    P("\n== TTL after the first attack (%d runs with an expiry before p6)" % len(TT))
    for fr, to in ((3, 2), (2, 1), (1, 0)):
        v = [dt for t in TT for f, l, dt in t["steps"] if (f, l) == (fr, to)]
        if v:
            P("  %d->%d: median %.1f s, min %.1f, max %.1f (n %d)" % (fr, to, np.median(v), min(v), max(v), len(v)))
    u = [t["upf_removed"] for t in TT if t["upf_removed"] is not None]
    if u:
        P("  UPF policy removed after level 0: median %.1f s, max %.1f s (n %d)" % (np.median(u), max(u), len(u)))
if OWN:
    P("== Attacker's own benign flow: delivered share median %.3f in p0, %.3f in p3-p5 (after the attack, while levels expire); multiplier mean median %s" % (
        np.nanmedian([o["p0"] for o in OWN]), np.nanmedian([o["quiet"] for o in OWN]), fmt(float(np.nanmedian([o["mult"] for o in OWN])), 2)))

if a.out:
    pathlib.Path(a.out).write_text("\n".join(L) + "\n")
