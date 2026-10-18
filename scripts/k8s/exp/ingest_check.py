#!/usr/bin/env python3
"""Check that the xApp receives both report sources, complete and correct.

  ingest_check.py <campaign dir | run dir>

Reads only the files of a stored run (scenario experiments/scenarios/
ingest-two-sources.yaml, but any run works) and writes ingest_check.json next
to each run, ingest_check.md in the campaign directory.

Sources: KPM (gNB -> E2 -> FlexRIC -> xApp, defense/features.jsonl = the
xApp's own parse, ran/kpm.csv for rows without SUPI) and URR (eBPF UPF ->
PFCP -> SMF -> producer -> ICS/A1-EI -> adapter -> xApp, one file per hop).

Criteria (thresholds below):
  hops      every Usage Report on N4 (PCAP) reaches SMF raw, producer,
            adapter and xApp; no duplicate at the xApp
  kpm       one KPM vector per second per SUPI in the traffic phases
  coverage  KPM vector with the URR of the same measured second
  latency   URR End Time -> received by the xApp
  volume    per SUPI and direction, KPM vs URR - c * packets (A.7 model);
            the swapped pairing (UE1 KPM with UE2 URR) must be far off
  identity  UE ID of every KPM vector = ran_identity of the SUPI's URR
  idle      URR still periodic without traffic, KPM ~ 0
  reconnect new UE ID and new PFCP session bound to the same SUPI in time
  dataset   the dataset line carries the URR of its second, equal to the
            URR the xApp received (needs the deferred dataset write; older
            xApp images: skipped)
  session   (gate CL-2, oai-session records) every new PDU session seen in
            URR has SESSION_BOUND with its SEID and epoch at the xApp; a
            re-attach has PDU_SES_EST within the epoch tolerance of the new
            session; session record latency; vectors carry seid and
            session_epoch, equal to the URR's when it is there (older
            images / no session records: skipped)
  profile   (gate CL-3, oai-upf-profile records) every published profile
            record of the run reached the xApp; UPF profile packets = URR
            packets summed over the traffic phases (both counted in the UPF;
            per second URR reads ~3 % high: OAI's report timer drifts, 58
            reports per 60 s with Duration in whole seconds, so per-second
            errors are reported, not graded); vectors of
            traffic phases carry the profile of their second; the iperf UDP
            phases show as UDP (no profile records: skipped)
"""
import bisect
import csv
import datetime
import json
import pathlib
import statistics
import sys

C_UL, C_DL = 16.3, 57.3          # A.7: URR bytes per packet above PDCP (UL, DL)
KPM_PER_S_MIN = 0.95             # KPM vectors / s / SUPI in traffic phases
COVERAGE_SAME_S = 0.95           # vectors with the URR of the same second
COVERAGE_PM1_S = 0.99            # ... same second or one second off
LAT_P95_S, LAT_MAX_S = 3.0, 8.0  # URR End Time -> xApp (1 s resolution on both sides)
VOLUME_ERR_MAX = 0.10            # |median relative error| per SUPI and direction
SWAP_ERR_MIN = 0.50              # swapped pairing must be at least this far off
MIN_RATE_KBPS = 200              # seconds compared for volume (URR model rate)
IDLE_URR_GAP_MAX_S = 3           # URR period without traffic (OAI: 1-2 s)
IDLE_KPM_MAX_KBPS = 50
RECONNECT_KPM_MAX_S = 45         # new UE ID labelled (xApp restart + AMF table <= 20 s)
RECONNECT_URR_MAX_S = 45         # first URR of the new session at the xApp
DATASET_URR_MIN = 0.95           # dataset lines with URR in traffic phases
EPOCH_TOL_S = 3                  # producer epochTolerance
SESSION_LAT_P95_S = 3.0          # session record time (1 s resolution) -> xApp
VECTOR_SESSION_MIN = 0.99        # vectors in traffic phases with seid + session_epoch
PROFILE_URR_ERR_MAX = 0.02       # |relative error| profile vs URR packets, traffic phases summed, per SUPI and direction
PROFILE_SAME_S_MIN = 0.95        # vectors in traffic phases with the profile of their second
UDP_SHARE_MIN = 0.98             # UL/DL UDP share in the iperf UDP phases
RAMP_S = 2                       # skipped at each phase start (iperf ramp, KPM period)


def jsonl(p):
    out = []
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def rows(p):
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def iso_s(s):
    s = s.rstrip("Z")
    if "." in s:
        a, b = s.split(".")
        s = a + "." + b[:6]
    return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.timezone.utc).timestamp()


def median(v):
    return statistics.median(v) if v else None


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def r3(x):
    return None if x is None else round(x, 3)


def check_run(run_dir):
    run = json.loads((run_dir / "run.json").read_text())
    if run.get("status") != "ok":
        return {"run": str(run_dir), "status": run.get("status"), "pass": False, "checks": {}}
    ues = run["ues"]                                    # name -> {supi, ip_history}
    supis = {u["supi"]: n for n, u in ues.items()}
    phases = run["phases"]
    flows = json.loads((run_dir / "traffic/flows.json").read_text())
    feats = [f for f in jsonl(run_dir / "defense/features.jsonl") if f.get("supi") in supis]
    xurr = jsonl(run_dir / "core/urr_received.jsonl")
    t_lo, t_hi = phases[0]["t_start"], phases[-1]["t_end"]
    checks = {}

    def phase_of(t):
        return next((p for p in phases if p["t_start"] <= t <= p["t_end"]), None)

    # traffic phases per UE and direction: {(phase, ue): {dir: offered bps}}
    offered = {}
    for f in flows:
        offered.setdefault((f["phase"], f["ue"]), {})[f["dir"]] = f.get("offered_bps", 0)

    # ---- URR at the xApp, rates over the measurement period (cumulative Duration in OAI)
    urr = {s: {} for s in supis}                        # supi -> end_time -> record
    last = {}
    for o in sorted(xurr, key=lambda o: (o["report"].get("seid"), o["report"].get("ur_seqn"))):
        r = o["report"]
        if r.get("supi") not in supis:
            continue
        key = (r["supi"], r.get("session_epoch"), r.get("seid"))
        d = r.get("duration_seconds") or 0
        period = d - last[key] if key in last and 0 < d - last[key] <= 60 else 1
        last[key] = d
        rec = {"end": r.get("end_time_unix") or 0, "recv": iso_s(o["received_at"]), "seid": r.get("seid"),
               "ul": r.get("ul_bytes", 0) * 8 / 1000 / period, "dl": r.get("dl_bytes", 0) * 8 / 1000 / period,
               "ul_pps": r.get("ul_packets", 0) / period, "dl_pps": r.get("dl_packets", 0) / period,
               "amf": (r.get("ran_identity") or {}).get("amf_ue_ngap_id")}
        urr[r["supi"]][rec["end"]] = rec

    def urr_at(supi, t):
        """URR of the second t, else one second off (the xApp's order)."""
        for c in (t, t - 1, t + 1):
            if c in urr[supi]:
                return urr[supi][c], c == t
        return None, False

    def model(rec, d):
        return rec[d] - (C_UL if d == "ul" else C_DL) * rec[d + "_pps"] * 8 / 1000

    # ---- hops: N4 -> SMF raw -> producer -> adapter -> xApp, key (SEID, UR-SEQN)
    pcap = set()
    for r in rows(run_dir / "core/pfcp_usage_reports.csv"):
        try:
            t = float(r["frame.time_epoch"])
            k = (int(r["pfcp.seid"], 16), int(r["pfcp.ur_seqn"]))
        except (ValueError, TypeError):
            continue                                    # several reports in one message: not split
        if t_lo <= t <= t_hi:
            pcap.add(k)
    norm = jsonl(run_dir / "core/producer_normalized.jsonl")
    ours = {r["seid"] for r in norm if r.get("supi") in supis} | {o["report"]["seid"] for o in xurr if o["report"].get("supi") in supis}
    pcap = {k for k in pcap if k[0] in ours}
    hop = {
        "smf_raw": {(n["customized_data"]["Usage Report"]["SEID"], n["customized_data"]["Usage Report"]["UR-SEQN"])
                    for o in jsonl(run_dir / "core/producer_smf_raw.jsonl") for n in o.get("eventNotifs", [])
                    if "Usage Report" in (n.get("customized_data") or {})},
        "producer": {(r["seid"], r["ur_seqn"]) for r in norm},
        "adapter": {(int(e[-3]), int(e[-1])) for e in (o["event_id"].split(":") for o in jsonl(run_dir / "core/adapter_delivery.jsonl")
                                                        if str(o.get("last_status", "")).startswith("HTTP 2"))
                    if e[-3].isdigit()},  # URR events only (CL-1: other types share the log)
        "xapp": {(o["report"]["seid"], o["report"]["ur_seqn"]) for o in xurr},
    }
    keys = [(o["report"].get("session_epoch"), o["report"]["seid"], o["report"]["ur_seqn"]) for o in xurr]
    missing = {h: len(pcap - s) for h, s in hop.items()}
    dup = len(keys) - len(set(keys))
    checks["hops"] = {"pass": bool(pcap) and not any(missing.values()) and dup == 0, "n4_reports": len(pcap),
                      "missing": missing, "xapp_duplicates": dup}

    # ---- KPM rate, coverage, volume, identity per SUPI over its traffic phases
    by_supi = {s: sorted((f for f in feats if f["supi"] == s), key=lambda f: f["collect_ms"]) for s in supis}
    kpm, cov, vol, ident, ds = {}, {}, {}, {}, {}
    pairs = {}                                          # (phase, ue) -> {second: (kpm f, urr rec)}
    for s, name in supis.items():
        n_vec = n_span = same = pm1 = 0
        errs = {"ul": [], "dl": []}
        bad_id = n_id = 0
        ds_n = ds_urr = ds_eq = 0
        for p in phases:
            dirs = offered.get((p["name"], name))
            if not dirs:
                continue
            a, b = p["t_start"] + RAMP_S, p["t_end"]
            vs = [f for f in by_supi[s] if a <= f["collect_ms"] / 1000 <= b]
            n_vec += len(vs)
            n_span += b - a
            for f in vs:
                t = int((f["collect_ms"] + 500) // 1000)
                rec, exact = urr_at(s, t)
                same += exact
                pm1 += rec is not None
                if rec is None:
                    continue
                pairs.setdefault((p["name"], name), {})[t] = (f, rec)
                for d in dirs:
                    m = model(rec, d)
                    if exact and m >= MIN_RATE_KBPS:
                        errs[d].append((f["rate_%s_kbps" % d] - m) / m)
                if rec["amf"] is not None:
                    n_id += 1
                    bad_id += rec["amf"] != f["amf_ue_ngap_id"]
                if "urr_at_decision" in f:
                    ds_n += 1
                    if "urr_ul_kbps" in f:
                        ds_urr += 1
                        ds_eq += abs(f["urr_ul_kbps"] - rec["ul"]) <= max(1.0, 0.01 * rec["ul"]) and \
                            abs(f["urr_dl_kbps"] - rec["dl"]) <= max(1.0, 0.01 * rec["dl"])
        kpm[s] = {"vectors": n_vec, "per_s": r3(n_vec / n_span) if n_span else None}
        cov[s] = {"same_s": r3(same / n_vec) if n_vec else None, "pm1_s": r3(pm1 / n_vec) if n_vec else None}
        vol[s] = {d: {"median_err": r3(median(e)), "n": len(e)} for d, e in errs.items() if e}
        ident[s] = {"compared": n_id, "mismatch": bad_id}
        ds[s] = {"lines": ds_n, "with_urr": r3(ds_urr / ds_n) if ds_n else None, "equal_to_received": r3(ds_eq / ds_urr) if ds_urr else None}
    checks["kpm"] = {"pass": all(v["per_s"] is not None and v["per_s"] >= KPM_PER_S_MIN for v in kpm.values()), "per_supi": kpm}
    checks["coverage"] = {"pass": all(v["same_s"] is not None and v["same_s"] >= COVERAGE_SAME_S and v["pm1_s"] >= COVERAGE_PM1_S
                                      for v in cov.values()), "per_supi": cov}
    checks["volume"] = {"pass": all(v and all(abs(x["median_err"]) <= VOLUME_ERR_MAX for x in v.values()) for v in vol.values()),
                        "per_supi": vol}
    checks["identity"] = {"pass": all(v["compared"] > 0 and v["mismatch"] == 0 for v in ident.values()), "per_supi": ident}

    # swapped pairing: phases where both UEs send at different rates in one direction
    swap = []
    names = list(ues)
    for p in phases:
        if len(names) < 2:
            break
        a, b = names[0], names[1]
        da, db = offered.get((p["name"], a), {}), offered.get((p["name"], b), {})
        pa, pb = pairs.get((p["name"], a), {}), pairs.get((p["name"], b), {})
        for d in set(da) & set(db):
            ka = median([x[0]["rate_%s_kbps" % d] for x in pa.values()])
            kb = median([x[0]["rate_%s_kbps" % d] for x in pb.values()])
            if not ka or not kb or max(ka, kb) < 2 * min(ka, kb):
                continue                                # measured rates too close to tell a swap
            e = []
            for t in set(pa) & set(pb):
                for k, u in ((pa[t][0], pb[t][1]), (pb[t][0], pa[t][1])):
                    m = model(u, d)
                    if m >= MIN_RATE_KBPS:
                        e.append(abs(k["rate_%s_kbps" % d] - m) / m)
            if e:
                swap.append({"phase": p["name"], "dir": d, "median_err": r3(median(e)), "n": len(e)})
    checks["volume"]["swapped"] = swap
    checks["volume"]["pass"] = checks["volume"]["pass"] and bool(swap) and all(x["median_err"] >= SWAP_ERR_MIN for x in swap)
    if not swap:
        checks["volume"]["swapped"] = "no phase with the two UEs' rates >= 2x apart"

    # ---- latency End Time -> xApp
    # reports that fell due while the xApp was restarting (the adapter delivers them late): reported apart
    down = [(p["t_start"] - (p["action"].get("seconds") or 0) - 2, p["t_start"]) for p in phases
            if (p.get("action") or {}).get("restart_xapp")]
    lat, late = [], []
    for s in supis:
        for r in urr[s].values():
            if t_lo <= r["end"] <= t_hi:
                (late if any(a <= r["end"] <= b or a <= r["recv"] <= b + 5 for a, b in down) else lat).append(r["recv"] - r["end"])
    checks["latency"] = {"pass": bool(lat) and pct(lat, 0.95) <= LAT_P95_S and max(lat) <= LAT_MAX_S,
                         "p50_s": r3(pct(lat, 0.5)), "p95_s": r3(pct(lat, 0.95)), "max_s": r3(max(lat)) if lat else None, "n": len(lat),
                         "during_xapp_restart": {"n": len(late), "max_s": r3(max(late)) if late else None}}

    # ---- idle phases: no flow of any UE
    idle = {}
    for p in phases:
        if any(k[0] == p["name"] for k in offered) or p.get("action"):
            continue
        for s in supis:
            ends = sorted(e for e in urr[s] if p["t_start"] <= e <= p["t_end"])
            gaps = [b - a for a, b in zip(ends, ends[1:])]
            k = [max(f["rate_ul_kbps"], f["rate_dl_kbps"]) for f in by_supi[s] if p["t_start"] <= f["collect_ms"] / 1000 <= p["t_end"]]
            idle.setdefault(p["name"], {})[s] = {"urr": len(ends), "max_gap_s": max(gaps) if gaps else None,
                                                 "kpm_max_kbps": r3(max(k)) if k else None}
    checks["idle"] = {"pass": None if not idle else all(v["urr"] >= 2 and v["max_gap_s"] is not None and v["max_gap_s"] <= IDLE_URR_GAP_MAX_S
                                                and v["kpm_max_kbps"] is not None and v["kpm_max_kbps"] <= IDLE_KPM_MAX_KBPS
                                                for ph in idle.values() for v in ph.values()), "phases": idle}

    # ---- reconnect: new UE ID and new session of the same SUPI
    rec_out = []
    kpm_rows = rows(run_dir / "ran/kpm.csv")
    for p in phases:
        n = (p.get("action") or {}).get("restart_ue")
        if not n:
            continue
        s = ues[n]["supi"]
        t_act = p["t_start"] - (p["action"].get("seconds") or 0) - 2   # the UE restart began (phase starts after it)
        t_ip = next((t for t, _ in ues[n]["ip_history"] if t and t_act <= t <= p["t_start"]), None)
        before = [f for f in by_supi[s] if f["collect_ms"] / 1000 < t_act]
        old_amf = before[-1]["amf_ue_ngap_id"] if before else None
        old_seids = {r["seid"] for r in urr[s].values() if r["end"] < t_act}
        new_k = next((f for f in by_supi[s] if t_ip and f["collect_ms"] / 1000 >= t_ip and f["amf_ue_ngap_id"] != old_amf), None)
        new_u = min((r for r in urr[s].values() if r["seid"] not in old_seids and t_ip and r["end"] >= t_ip - 5), key=lambda r: r["recv"], default=None)
        new_amf = new_k["amf_ue_ngap_id"] if new_k else None
        others = [f for f in feats if f["supi"] != s and new_amf is not None and f["amf_ue_ngap_id"] == new_amf]
        unl = [r for r in kpm_rows if not r.get("SUPI") and t_ip and float(r["Time (UNIX ms)"]) / 1000 >= t_ip - 60]
        e = {"ue": n, "old_amf": old_amf, "new_amf": new_amf,
             "kpm_labelled_after_ip_s": r3(new_k["collect_ms"] / 1000 - t_ip) if new_k and t_ip else None,
             "new_seid": new_u["seid"] if new_u else None,
             "urr_new_session_after_ip_s": r3(new_u["recv"] - t_ip) if new_u and t_ip else None,
             "urr_ran_identity_new_amf": bool(new_u) and new_u["amf"] == new_amf,
             "new_amf_under_other_supi": len(others), "kpm_rows_without_supi": len(unl)}
        e["pass"] = (e["kpm_labelled_after_ip_s"] is not None and e["kpm_labelled_after_ip_s"] <= RECONNECT_KPM_MAX_S
                     and e["urr_new_session_after_ip_s"] is not None and e["urr_new_session_after_ip_s"] <= RECONNECT_URR_MAX_S
                     and not others)
        rec_out.append(e)
    checks["reconnect"] = {"pass": None if not rec_out else all(e["pass"] for e in rec_out), "events": rec_out}

    # ---- dataset line = what the xApp received (deferred write only)
    if any(v["lines"] for v in ds.values()):
        checks["dataset"] = {"pass": all(v["with_urr"] is not None and v["with_urr"] >= DATASET_URR_MIN and (v["equal_to_received"] or 0) >= 0.99
                                         for v in ds.values()), "per_supi": ds}
    else:
        checks["dataset"] = {"pass": None, "skipped": "xApp image without the deferred dataset write (no urr_at_decision field)"}

    # ---- session records (CL-2)
    core = jsonl(run_dir / "core/core_received.jsonl")
    sess = [x for x in core if x.get("kind") == "session" and x["report"].get("supi") in supis]
    if not sess:
        checks["session"] = {"pass": None, "skipped": "no oai-session records (producer/adapter/xApp before CL-2)"}
    else:
        ev = lambda x: (x["report"].get("body") or {}).get("event")
        ep_s = lambda e: datetime.datetime.strptime(e, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc).timestamp() if e else None
        bound = {(x["report"]["supi"], x["report"].get("seid"), x["report"].get("session_epoch")) for x in sess if ev(x) == "SESSION_BOUND"}
        urr_sessions = {}
        for o in xurr:
            r = o["report"]
            if r.get("supi") in supis and r.get("session_epoch") and t_lo <= (r.get("end_time_unix") or 0) <= t_hi:
                urr_sessions.setdefault((r["supi"], r["seid"], r["session_epoch"]), iso_s(o["received_at"]))
        # a session that started in this run must be bound
        new_sessions = [k for k in urr_sessions if ep_s(k[2]) and ep_s(k[2]) >= t_lo]
        unbound = [list(k) for k in new_sessions if k not in bound]
        est = [x for x in sess if ev(x) == "PDU_SES_EST"]
        rel = [x for x in sess if ev(x) == "PDU_SES_REL"]
        reatt = []
        for k in new_sessions:
            near = [x for x in est if x["report"]["supi"] == k[0] and abs(ep_s(x["report"].get("session_epoch")) - ep_s(k[2])) <= EPOCH_TOL_S]
            reatt.append({"supi": k[0], "seid": k[1], "epoch": k[2], "est": bool(near),
                          "est_epoch_delta_s": r3(ep_s(near[0]["report"]["session_epoch"]) - ep_s(k[2])) if near else None})
        lat_s = [x["received_unix_ms"] / 1000 - x["report"]["time_unix"] for x in sess
                 if ev(x) in ("PDU_SES_EST", "PDU_SES_REL", "UE_IP_CH")]
        vec = [f for f in feats if phase_of(f["collect_ms"] / 1000) and phase_of(f["collect_ms"] / 1000)["name"] in {k[0] for k in offered}]
        with_sess = [f for f in vec if f.get("session_epoch")]
        mism = [f for f in with_sess if f.get("urr_ul_kbps") is not None and f.get("session_source") != "urr"]
        checks["session"] = {
            "pass": not unbound and all(e["est"] for e in reatt) and bool(lat_s) and pct(lat_s, 0.95) <= SESSION_LAT_P95_S
                    and bool(vec) and len(with_sess) / len(vec) >= VECTOR_SESSION_MIN and not mism,
            "records": {e: sum(1 for x in sess if ev(x) == e) for e in sorted({ev(x) for x in sess})},
            "new_sessions": len(new_sessions), "unbound": unbound, "establishments": reatt, "releases": len(rel),
            "latency_p50_s": r3(pct(lat_s, 0.5)), "latency_p95_s": r3(pct(lat_s, 0.95)),
            "vectors_with_session": r3(len(with_sess) / len(vec)) if vec else None, "vectors_with_urr_not_urr_session": len(mism)}

    # ---- UPF profile records (CL-3)
    prof = [x for x in core if x.get("kind") == "profile" and x["report"].get("supi") in supis]
    if not prof:
        checks["profile"] = {"pass": None, "skipped": "no oai-upf-profile records (UPF/producer/xApp before CL-3)"}
    else:
        published = {(r["source_epoch"], r["seq"]) for r in jsonl(run_dir / "core/producer_envelopes.jsonl")
                     if r.get("type", "").startswith("oai-upf-profile") and r.get("supi") in supis and t_lo <= r["time_unix"] <= t_hi}
        got = {(x["report"]["source_epoch"], x["report"]["seq"]) for x in prof}
        lost = sorted(published - got)
        pmap = {(x["report"]["supi"], x["report"]["time_unix"]): x["report"]["body"] for x in prof}
        err, udp, tot = {}, {}, {}
        for (s, t), b in pmap.items():
            ph = phase_of(t)
            if ph and ph["name"] in {k[0] for k in offered}:
                for d in ("ul", "dl"):
                    tot.setdefault((s, d), [0, 0])[0] += b[d + "_pkts"]
        for o in xurr:
            r = o["report"]
            ph = phase_of(r.get("end_time_unix") or 0)
            if r.get("supi") in supis and ph and ph["name"] in {k[0] for k in offered}:
                for d in ("ul", "dl"):
                    tot.setdefault((r["supi"], d), [0, 0])[1] += r.get(d + "_packets", 0)
        for (s, t), b in pmap.items():
            ph = phase_of(t)
            if not ph or ph["name"] not in {k[0] for k in offered} or t < ph["t_start"] + RAMP_S:
                continue
            u = urr[s].get(t)
            if not u:
                continue
            for d in ("ul", "dl"):
                ref = u[d + "_pps"]
                if ref * 1 >= 50:  # enough packets in the second
                    err.setdefault((s, d), []).append((b[d + "_pkts"] - ref) / ref)
                    if b[d + "_pkts"]:
                        udp.setdefault((s, d), []).append(b[d + "_udp"] / b[d + "_pkts"])
        vec = [f for f in feats if phase_of(f["collect_ms"] / 1000) and phase_of(f["collect_ms"] / 1000)["name"] in {k[0] for k in offered}]
        same = [f for f in vec if f.get("prof_offset_s") == 0]
        per = {"%s/%s" % (supis[s], d): {"n": len(v), "median_err_per_s": r3(median(v))} for (s, d), v in err.items()}
        totals = {"%s/%s" % (supis[s], d): {"profile": a, "urr": b, "err": r3((a - b) / b)} for (s, d), (a, b) in tot.items() if b >= 1000}
        shares = {"%s/%s" % (supis[s], d): r3(median(v)) for (s, d), v in udp.items()}
        checks["profile"] = {
            "pass": not lost and bool(totals) and all(abs(x["err"]) <= PROFILE_URR_ERR_MAX for x in totals.values())
                    and bool(vec) and len(same) / len(vec) >= PROFILE_SAME_S_MIN and all(v >= UDP_SHARE_MIN for v in shares.values()),
            "published": len(published), "lost": len(lost), "first_lost": [list(k) for k in lost[:5]],
            "vs_urr_packets": totals, "per_second": per, "udp_share": shares,
            "vectors_same_second": r3(len(same) / len(vec)) if vec else None}

    graded = [c["pass"] for c in checks.values() if c["pass"] is not None]
    return {"run": str(run_dir), "status": "ok", "pass": all(graded), "checks": checks}


def fmt(res):
    out = ["### %s — %s" % (pathlib.Path(res["run"]).relative_to(pathlib.Path(res["run"]).parents[2]),
                            "PASS" if res["pass"] else "FAIL"), "", "| check | result | detail |", "|---|---|---|"]
    for k, c in res["checks"].items():
        v = "skipped" if c["pass"] is None else "PASS" if c["pass"] else "FAIL"
        out.append("| %s | %s | `%s` |" % (k, v, json.dumps({x: y for x, y in c.items() if x != "pass"}, separators=(",", ":"))))
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    d = pathlib.Path(sys.argv[1]).resolve()
    runs = [d] if (d / "run.json").exists() else sorted(d.glob("runs/*/rep-*"))
    if not runs:
        sys.exit("no run under %s" % d)
    results = []
    for r in runs:
        res = check_run(r)
        (r / "ingest_check.json").write_text(json.dumps(res, indent=1) + "\n")
        results.append(res)
        print(fmt(res) if res["status"] == "ok" else "### %s — %s\n" % (r, res["status"]))
    if not (d / "run.json").exists():
        text = "# Ingest check — %s\n\n%d/%d runs PASS\n\n" % (d.name, sum(x["pass"] for x in results), len(results))
        text += "\n".join(fmt(x) for x in results if x["status"] == "ok")
        (d / "ingest_check.md").write_text(text)
        print("written %s" % (d / "ingest_check.md"))
    sys.exit(0 if all(x["pass"] for x in results) else 1)


if __name__ == "__main__":
    main()
