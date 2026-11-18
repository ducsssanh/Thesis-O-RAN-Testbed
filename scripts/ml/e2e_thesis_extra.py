#!/usr/bin/env python3
"""Extra end-to-end numbers for the thesis (advisor feedback of 2026-11-15), read from the kept runs of one end-to-end
manifest; nothing is run on the testbed. Reuses the loader and the per-episode logic of e2e_report.py.
  1. every wrong limit on a benign UE: when, how long at the limit level and above level 0, bytes the twin replay of the UE
     planned to send, bytes it sent after its own back-off, bytes that reached the DN, bytes lost (planned - DN); and, where
     the UE also ran the benign closed-loop client of the L3 runs, its requests planned and completed while limited;
  2. attack bytes that reached the DN, split by the attacker's level in that second, over ALL seconds of the capture
     (e2e_report.py splits only the seconds from the onset to the end of the attack phases, so its three shares do not
     add up to 100%): before the first decision, at the limit level, at the block level, after the level ran out;
  3. effect of the quarantine slice on the radio: uplink PRB share of the attacking UE in attack seconds, by its level,
     in the runs whose KPM is not tampered (the PRB share comes from KPM), with the idle PRB share of the same UEs as the
     floor of the measurement; and the E2SM-RC actions sent (slice handover, PRB quota) with their acknowledgements;
  4. the estimate of all wrong blocks per benign UE-hour asked by the advisor:
     wrong escalations per limit (calibration) x wrong limits per UE-hour + the model's own block rate, with exact intervals;
  5. the live false-alarm rate re-weighted to the real band shares.
Usage (repo root): e2e_thesis_extra.py --manifest research/datasets/oran_flooding_e2e2/manifest [--out research/clf/E2E_thesis_extra.txt]"""
import argparse, collections, json, pathlib, sys
import numpy as np
from scipy.stats import beta, chi2

ap = argparse.ArgumentParser(); ap.add_argument("--manifest", required=True); ap.add_argument("--out")
a = ap.parse_args()
src = open(pathlib.Path(__file__).with_name("e2e_report.py")).read().split("\nEP, BEN, FRC")[0]
sys.argv = ["e2e_report.py", "--manifest", a.manifest]
G = {}; exec(compile(src, "e2e_report.py", "exec"), G)
DESIGN, KEPT, load, level_at, lvl, sent_flow, dn_flow, ue_ip = (G[k] for k in ("DESIGN", "KEPT", "load", "level_at", "lvl", "sent_flow", "dn_flow", "ue_ip"))
OUT = []
P = lambda s="": (OUT.append(s), print(s))


def pois(k, T):
    """exact (Garwood) 95% interval of a Poisson rate, k events in T hours"""
    return (chi2.ppf(.025, 2 * k) / 2 / T if k else 0.0), chi2.ppf(.975, 2 * k + 2) / 2 / T


def planned_flow(f):
    """bytes per second the generator planned (before its own back-off); falls back to the bytes sent"""
    out = {}
    for r in f.get("rows", []):
        if r.get("final") or r.get("bytes") is None:
            continue
        t = int(np.floor(r["t"])); out[t] = out.get(t, 0) + float(r.get("target_bytes", r["bytes"]))
    return out


P("Extra end-to-end numbers for the thesis: %s (%d runs kept)" % (a.manifest, len(KEPT)))

# ---- 1. wrong limits on benign UEs
P("\n1. Wrong limits on benign UEs (level 2 raised by the defence on a UE that never attacks)")
P("   run  ue  band  phase  L3 client  attack phase  at limit s  above level 0 s  planned kB  sent kB  at DN kB  lost kB (share)")
WL, HOURS = [], 0.0
for rid in sorted(KEPT):
    r = DESIGN[rid]; d = KEPT[rid]
    meta, ev, clf, audit, flows, ph, dn = load(d)
    t_run0, t_run1 = ph["p0"][0], ph["p7"][1]
    for u in ("ue1", "ue2"):
        if u == r.get("attacker"):
            continue
        HOURS += (t_run1 - t_run0) / 3600
        supi = meta["ues"][u]["supi"]; ip = ue_ip(meta, u)
        lev = [e for e in ev if e["type"] == "level" and e["supi"] == supi]
        ups = [e for e in lev if e["level"] >= 2 and e.get("from", 0) < 2 and e["why"] not in ("expired", "forced")]
        plan, sent, got = {}, {}, {}
        bf = [f for f in flows if f["ue"] == u and f.get("role") == "benign" and f.get("dir") == "ul"]
        for f in bf:
            for t, b in planned_flow(f).items(): plan[t] = plan.get(t, 0) + b
            for t, b in sent_flow(f).items(): sent[t] = sent.get(t, 0) + b
            for t, b in dn_flow(dn, ip, f).items(): got[t] = got.get(t, 0) + b
        for e in ups:
            t_in = e["at_ms"] / 1000
            t_out2 = next((x["at_ms"] / 1000 for x in lev if x["at_ms"] > e["at_ms"] and x["level"] < 2), t_run1)   # leaves the limit level
            t_out0 = next((x["at_ms"] / 1000 for x in lev if x["at_ms"] > e["at_ms"] and x["level"] == 0), t_run1)   # back at level 0
            peak = max([e["level"]] + [x["level"] for x in lev if t_in < x["at_ms"] / 1000 <= t_out0])
            secs = set(range(int(np.ceil(t_in)), int(np.floor(t_out2)) + 1))
            pl, se, go = (sum(x.get(t, 0) for t in secs) for x in (plan, sent, got))
            phase = next((p for p, (s0, s1) in ph.items() if s0 <= t_in < s1), "?")
            pd = next((p for p in r["phases"] if p["name"] == phase), {})
            # benign closed-loop client of the L3 runs (dir "ul_client"): requests planned (started + skipped by the closed loop) and completed
            cf = [f for f in flows if f["ue"] == u and f.get("role") == "benign" and f.get("dir") == "ul_client"]
            creq = [(int(np.floor(x["t"])), x.get("started", 0) + x.get("skipped", 0), x.get("sent_pkts", 0)) for f in cf for x in f.get("rows", []) if not x.get("final")]
            c_plan, c_done = sum(a_ for t, a_, b_ in creq if t in secs), sum(b_ for t, a_, b_ in creq if t in secs)
            client = c_plan > 0
            other_attacks = phase in ("p1", "p2", "p6")     # the attack phases of the end-to-end design
            WL.append(dict(run=rid, ue=u, band=(pd.get("bands") or {}).get(u, "?"), phase=phase, client=client, attack=other_attacks,
                           at_limit=t_out2 - t_in, above=t_out0 - t_in, planned=pl / 1e3, sent=se / 1e3, dn=go / 1e3, peak=peak, why=e["why"], c_plan=c_plan, c_done=c_done))
            w = WL[-1]
            P("   %s  %s  %s  %s  %-3s  %-3s  %5.0f  %5.0f  %8.1f  %8.1f  %8.1f  %8.1f (%.0f%%)  peak level %d, %s" % (
                rid, u, w["band"], phase, "yes" if client else "no", "yes" if other_attacks else "no", w["at_limit"], w["above"],
                w["planned"], w["sent"], w["dn"], w["planned"] - w["dn"], 100 * (1 - w["dn"] / w["planned"]) if w["planned"] else float("nan"), peak, e["why"])
              + ("; benign client: %d of %d planned requests completed" % (c_done, c_plan) if client else ""))
n = len(WL); nb = sum(w["peak"] >= 3 for w in WL)
lo, hi = pois(n, HOURS); lob, hib = pois(nb, HOURS)
P("   %d wrong limits and %d wrong blocks over %.2f benign UE-hours: %.2f [%.2f, %.2f] and %.2f [%.2f, %.2f] per UE-hour (exact Poisson, two-sided 95%%)" % (
    n, nb, HOURS, n / HOURS, lo, hi, nb / HOURS, lob, hib))
if n:
    tot_p, tot_d = sum(w["planned"] for w in WL), sum(w["dn"] for w in WL)
    P("   at the limit level: %.0f s in total (median %.0f s per limit); planned %.1f kB, at the DN %.1f kB, lost %.1f kB (%.0f%% of what the limited UEs planned to send while limited)" % (
        sum(w["at_limit"] for w in WL), np.median([w["at_limit"] for w in WL]), tot_p, tot_d, tot_p - tot_d, 100 * (1 - tot_d / tot_p)))

# ---- 2. attack bytes at the DN by the attacker's level, all seconds
P("\n2. Attack bytes that reached the DN, by the attacker's level in that second (all seconds of the capture)")
for tag, names in (("first attack p1-p2", ("p1", "p2")), ("second attack p6", ("p6",))):
    S = collections.Counter(); sent_tot = 0.0
    for rid in sorted(KEPT):
        r = DESIGN[rid]; d = KEPT[rid]
        meta, ev, clf, audit, flows, ph, dn = load(d)
        att = r["attacker"]; supi = meta["ues"][att]["supi"]; ip = ue_ip(meta, att)
        steps = level_at(ev, supi); sent, got = {}, {}
        for f in flows:
            if f["phase"] in names and f["ue"] == att and f.get("role") == "attack":
                for t, b in sent_flow(f).items(): sent[t] = sent.get(t, 0) + b
                for t, b in dn_flow(dn, ip, f).items(): got[t] = got.get(t, 0) + b
        act = sorted(t for t, b in sent.items() if b > 0)
        if not act:
            continue
        sent_tot += sum(sent.values())
        first_up = next((e["at_ms"] / 1000 for e in ev if e["type"] == "level" and e["supi"] == supi and e["level"] > e.get("from", 0)
                         and e["why"] not in ("expired", "forced") and e["at_ms"] / 1000 >= act[0] - 1), None)
        for t, b in got.items():
            L = lvl(steps, t + .5)
            if L >= 3: k = "block"
            elif L == 2: k = "limit"
            elif first_up is None or t + .5 < first_up: k = "before the first decision"
            else: k = "after the level ran out (levels 0-1)"
            S[k] += b
    tot = sum(S.values())
    P("   %s: sent %.1f kB, at the DN %.1f kB (%.1f%% stopped)" % (tag, sent_tot / 1e3, tot / 1e3, 100 * (1 - tot / sent_tot)))
    for k in ("before the first decision", "limit", "block", "after the level ran out (levels 0-1)"):
        P("      %-40s %8.1f kB  %5.1f%% of the bytes at the DN" % (k, S[k] / 1e3, 100 * S[k] / tot))

# ---- 3. quarantine slice: PRB share of the attacker by level
P("\n3. Quarantine slice: uplink PRB share (%) of the attacking UE, by its level; runs with honest KPM only")
acc = collections.defaultdict(list); idle = []; rc = collections.Counter(); ack = []
for rid in sorted(KEPT):
    r = DESIGN[rid]; d = KEPT[rid]
    for l in open(d / "ran/rc_control.jsonl"):
        x = json.loads(l); rc[(x.get("action"), x.get("max_prb_ratio"), x.get("status"))] += 1
        if x.get("ack_latency_ms") is not None: ack.append(x["ack_latency_ms"])
    if r["case"] != "honest":
        continue
    meta, ev, clf, audit, flows, ph, dn = load(d)
    att = r["attacker"]; supi = meta["ues"][att]["supi"]; steps = level_at(ev, supi)
    ft = {}
    for x in open(d / "defense/features.jsonl"):
        f = json.loads(x)
        if f["supi"] == supi:
            ft[int(f["collect_ms"] // 1000)] = f
    sent = {}
    for f in flows:
        if f["ue"] == att and f.get("role") == "attack":
            for t, b in sent_flow(f).items(): sent[t] = sent.get(t, 0) + b
    for t, f in ft.items():                      # the row of second t holds the traffic of [t-1, t)
        L = lvl(steps, t - .5)
        if sent.get(t - 1, 0) > 0:
            acc[0 if L == 0 else 2 if L < 3 else 3].append((f["prb_ul_pct"], f["rate_ul_kbps"], f["prof_ul_kbps"]))
        elif L == 0 and f["prof_ul_kbps"] == 0 and f["rate_ul_kbps"] == 0:
            idle.append(f["prb_ul_pct"])
P("   E2SM-RC actions over the %d runs (action, PRB quota, status): %s" % (len(KEPT), dict(rc)))
P("   acknowledgement latency of the E2SM-RC actions: median %.2f ms, 99th percentile %.2f ms, n = %d" % (np.median(ack), np.percentile(ack, 99), len(ack)))
P("   idle seconds of the same UEs at level 0 (no uplink at the core, no KPM volume): PRB share median %.1f, 90th percentile %.1f, n = %d" % (
    np.median(idle), np.percentile(idle, 90), len(idle)))
for L, nm in ((0, "attack seconds before the first decision (default slice)"), (2, "attack seconds at the limit level (quarantine slice, quota 5%)"),
              (3, "attack seconds at the block level (quarantine slice, quota 1%)")):
    x = np.array(acc[L])
    P("   %-62s n = %4d  PRB share median %.1f, 90th percentile %.1f, maximum %.1f; KPM uplink rate median %.1f kbit/s; rate at the core (before the UPF policy) median %.1f kbit/s" % (
        nm, len(x), np.median(x[:, 0]), np.percentile(x[:, 0], 90), x[:, 0].max(), np.median(x[:, 1]), np.median(x[:, 2])))

# ---- 4. estimate of all wrong blocks per benign UE-hour
P("\n4. Estimate of wrong blocks per benign UE-hour (escalation by response + the model's block tier)")
k_esc, n_esc = 6, 39                       # calibration replay at rho 0.7: benign stays at the limit that would have been escalated
p = k_esc / n_esc; plo, phi = beta.ppf(.025, k_esc, n_esc - k_esc + 1), beta.ppf(.975, k_esc + 1, n_esc - k_esc)
far_blk_live = 6 / 25.78                   # live blind test, block tier
P("   wrong escalation per limit in the calibration runs: %d/%d = %.3f [%.3f, %.3f] (Clopper-Pearson)" % (k_esc, n_esc, p, plo, phi))
for nm, lim in (("wrong limits of the live blind test, 30 in 25.48 UE-h", 30 / 25.48), ("wrong limits of this campaign", n / HOURS)):
    P("   with the %s (%.2f per UE-h): %.2f + %.2f = %.2f per UE-h; with the interval of the escalation share %.2f to %.2f" % (
        nm, lim, p * lim, far_blk_live, p * lim + far_blk_live, plo * lim + far_blk_live, phi * lim + far_blk_live))

# ---- 5. live false-alarm rate at the real band shares
P("\n5. Live blind test, false alarms re-weighted to the real band shares (P1-P4: 0.50, 0.40, 0.09, 0.01)")
share = dict(P1=.50, P2=.40, P3=.09, P4=.01)
# false alarms and benign UE-hours per band, pooled over both parts of the live test (research/clf/LIVE6_benign_fa.txt, "pooled");
# the hours differ slightly between the tiers because a UE stops counting once it has raised the alarm of that tier
live = {"rate-limit tier": dict(P1=(0, 7.60), P2=(0, 6.40), P3=(6, 4.96), P4=(24, 6.52)),
        "block tier": dict(P1=(0, 7.60), P2=(0, 6.40), P3=(0, 4.99), P4=(6, 6.79))}
for nm, v in live.items():
    P("   %s: %.3f per UE-h at the real shares (pooled over the testbed mix: %.2f)" % (nm, sum(share[b] * v[b][0] / v[b][1] for b in share), sum(x[0] for x in v.values()) / sum(x[1] for x in v.values())))
    for b in ("P1", "P2", "P3", "P4"):
        lo, hi = pois(v[b][0], v[b][1]); P("      %s: %d in %.2f UE-h = %.2f [%.2f, %.2f]" % (b, v[b][0], v[b][1], v[b][0] / v[b][1], lo, hi))

if a.out:
    pathlib.Path(a.out).write_text("\n".join(OUT) + "\n"); print("wrote", a.out)
