"""Numbers of one run, computed only from the files of its directory (so a
stored run can be re-evaluated: run.py report <campaign>).

Per phase and UE: offered / delivered rate (iperf receiver), loss, rate seen
at the DN (N6 counter), KPM rate and PRB share, URR rate, highest level.
Per UE over the run: time from the attack start to the first evidence, to
each level, to the first RAN action and to the first UPF block, counts of
evidence / actions / verdicts, UPF drops. Benign UEs: false positives."""
import csv
import json
import statistics

# KPM numbers come from defense/features.jsonl: the xApp's own parse of each
# E2SM-KPM indication (PDCP SDU volume per 1 s period -> kbit/s, PRB share,
# SUPI). ran/kpm.csv is the raw NIST CSV writer output, kept as a record: its
# volume columns are batched per cell report and do not carry the unit of
# their header, so they are not used for numbers.


def _mean(v):
    return round(statistics.mean(v), 3) if v else None


def _jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _csv(path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def compute(run_dir):
    run = json.loads((run_dir / "run.json").read_text())
    ues = run["ues"]                     # name -> {supi, role, ip_history:[[t, ip]]}
    phases = run["phases"]               # [{name, t_start, t_end, flags...}]
    flows = json.loads((run_dir / "traffic/flows.json").read_text()) if (run_dir / "traffic/flows.json").exists() else []
    dn = _csv(run_dir / "dataplane/dn_per_second.csv")
    feats = _jsonl(run_dir / "defense/features.jsonl")
    urr = _jsonl(run_dir / "core/urr_received.jsonl")
    events = _jsonl(run_dir / "defense/events.jsonl")
    timeline = _jsonl(run_dir / "defense/state_timeline.jsonl")
    snaps = {k: json.loads((run_dir / ("meta/snapshot_%s.json" % k)).read_text())
             for k in ("start", "end") if (run_dir / ("meta/snapshot_%s.json" % k)).exists()}

    def ip_of(name, t):
        ip = None
        for ts, addr in ues[name]["ip_history"]:
            if ts <= t:
                ip = addr
        return ip

    attack = next((p for p in phases if p.get("attack")), None)
    t_attack = attack["t_start"] if attack else None
    m = {"phases": {}, "ues": {}, "run": {"duration_s": round(phases[-1]["t_end"] - phases[0]["t_start"], 1) if phases else None}}

    # URR reports: rate over the measurement period (difference of cumulative Duration, OAI)
    urr_by = {}
    last = {}
    for o in urr:
        r = o.get("report", {})
        key = (r.get("supi"), r.get("seid"))
        d = r.get("duration_seconds") or 0
        period = d - last[key] if key in last and 0 < d - last[key] <= 60 else 1
        last[key] = d
        urr_by.setdefault(r.get("supi"), []).append((r.get("end_time_unix") or 0, r.get("ul_bytes", 0) * 8 / 1000 / period,
                                                     r.get("dl_bytes", 0) * 8 / 1000 / period))

    for p in phases:
        t0, t1 = p["t_start"], p["t_end"]
        span = max(t1 - t0, 1e-3)
        pm = {"duration_s": round(span, 1)}
        for name, u in ues.items():
            supi = u["supi"]
            e = {}
            for d in ("ul", "dl"):
                fl = [f for f in flows if f["phase"] == p["name"] and f["ue"] == name and f["dir"] == d]
                rows = [r for f in fl for r in f["rows"] if not r["final"] and t0 <= r["t"] <= t1 + 1.5]
                e["offered_%s_mbps" % d] = round(sum(f["offered_bps"] for f in fl) / 1e6, 3) if fl else 0
                e["delivered_%s_mbps" % d] = round(sum(r["bytes"] or 0 for r in rows) * 8 / span / 1e6, 4) if fl else None
                lost, tot = sum(r["lost"] for r in rows), sum(r["total"] for r in rows)
                e["loss_%s_pct" % d] = round(100.0 * lost / tot, 2) if tot else None
                b = sum(int(r["ip_payload_bytes"]) for r in dn if r["dir"] == d and t0 <= int(r["t"]) < t1
                        and r["ue_ip"] == ip_of(name, int(r["t"])))
                e["dn_%s_mbps" % d] = round(b * 8 / span / 1e6, 4)
            krows = [r for r in feats if r.get("supi") == supi and t0 + 2 <= r.get("collect_ms", 0) / 1000 <= t1]
            e["kpm_ul_kbps"] = _mean([r.get("rate_ul_kbps", 0) for r in krows])
            e["kpm_dl_kbps"] = _mean([r.get("rate_dl_kbps", 0) for r in krows])
            e["kpm_prb_ul_pct"] = _mean([r.get("prb_ul_pct", 0) for r in krows])
            e["kpm_prb_dl_pct"] = _mean([r.get("prb_dl_pct", 0) for r in krows])
            e["kpm_samples"] = len(krows)
            ur = [x for x in urr_by.get(supi, []) if t0 + 2 <= x[0] <= t1]
            e["urr_ul_kbps"] = _mean([x[1] for x in ur])
            e["urr_dl_kbps"] = _mean([x[2] for x in ur])
            lv = [r["ues"].get(supi, {}).get("level") or 0 for r in timeline if t0 <= r["t"] <= t1]
            e["max_level"] = max(lv) if lv else None
            pm[name] = e
        m["phases"][p["name"]] = pm

    for name, u in ues.items():
        supi = u["supi"]
        ev = [x for x in events if x.get("supi") == supi]
        rel = lambda x: round(x["at_ms"] / 1000 - t_attack, 2) if t_attack is not None else None
        first = lambda pred: next((rel(x) for x in ev if pred(x)), None)
        e = {"role": u["role"],
             "evidence": sum(x["type"] == "evidence" for x in ev),
             "max_level": max([x["level"] for x in ev if x["type"] == "level"] + [0]),
             "t_first_evidence_s": first(lambda x: x["type"] == "evidence"),
             "t_ran_limit_s": first(lambda x: x["type"] == "action" and x.get("layer", "ran") == "ran" and x.get("http") == 200
                                    and (x.get("max_prb_ratio") or 100) < 100),
             "t_upf_block_s": first(lambda x: x["type"] == "action" and x.get("layer") == "core" and x.get("action") == "block"
                                    and x.get("http") == 200),
             "rrc_releases": sum(x["type"] == "action" and x.get("action") == "release" and x.get("http") == 200 for x in ev),
             "upf_actions": sum(x["type"] == "action" and x.get("layer") == "core" and x.get("http") == 200 for x in ev),
             "ran_actions": sum(x["type"] == "action" and x.get("layer", "ran") == "ran" and x.get("http") == 200 for x in ev),
             "verified": sum(x["type"] == "verified" for x in ev),
             "unverified": sum(x["type"] == "unverified" for x in ev)}
        for k in range(1, 5):
            e["t_level%d_s" % k] = first(lambda x, k=k: x["type"] == "level" and x["level"] >= k and x.get("from", 0) < k)

        def drops(snap):
            for s in (snap or {}).get("upf__v1_stats", {}).get("stats", []):
                if s["supi"] == supi:
                    return s["total"]
            return {}
        a, b = drops(snaps.get("start")), drops(snaps.get("end"))
        for k in ("drop_ul_pkts", "drop_ul_bytes", "drop_dl_pkts", "drop_dl_bytes"):
            e["upf_" + k] = (b.get(k, 0) - a.get(k, 0)) if b else None
        m["ues"][name] = e

    # headline numbers
    base = next((p for p in phases if p.get("baseline")), None)
    benign = [n for n, u in ues.items() if u["role"] == "benign"]
    attackers = [n for n, u in ues.items() if u["role"] == "attacker"]
    h = {}
    if attack:
        ap = m["phases"][attack["name"]]
        for n in attackers:
            h["attacker_dn_ul_mbps_attack"] = ap[n]["dn_ul_mbps"]
            h["attacker_delivered_ratio_attack"] = (round(ap[n]["delivered_ul_mbps"] / ap[n]["offered_ul_mbps"], 4)
                                                   if ap[n]["offered_ul_mbps"] and ap[n]["delivered_ul_mbps"] is not None else None)
            for k in ("t_first_evidence_s", "t_level1_s", "t_level2_s", "t_level3_s", "t_ran_limit_s", "t_upf_block_s", "max_level"):
                h["attacker_" + k] = m["ues"][n][k]
            h["attacker_upf_drop_ul_mbytes"] = round((m["ues"][n]["upf_drop_ul_bytes"] or 0) / 1e6, 3)
        ratios = [ap[n]["delivered_ul_mbps"] / ap[n]["offered_ul_mbps"] for n in benign
                  if ap[n]["offered_ul_mbps"] and ap[n]["delivered_ul_mbps"] is not None]
        losses = [ap[n]["loss_ul_pct"] for n in benign if ap[n]["loss_ul_pct"] is not None]
        h["benign_delivered_ratio_attack"] = round(min(ratios), 4) if ratios else None   # worst benign UE
        h["benign_loss_pct_attack"] = max(losses) if losses else None
    if benign:
        h["benign_max_level"] = max(m["ues"][n]["max_level"] for n in benign)
        h["benign_evidence"] = sum(m["ues"][n]["evidence"] for n in benign)
    if base:
        bp = m["phases"][base["name"]]
        ratios = [bp[n]["delivered_ul_mbps"] / bp[n]["offered_ul_mbps"] for n in benign
                  if bp[n]["offered_ul_mbps"] and bp[n]["delivered_ul_mbps"] is not None]
        h["benign_delivered_ratio_baseline"] = round(min(ratios), 4) if ratios else None
    rec = next((p for p in phases if p.get("reconnect")), None)
    if rec:
        for n in attackers:
            h["attacker_dn_ul_mbps_after_reconnect"] = m["phases"][rec["name"]][n]["dn_ul_mbps"]
            h["attacker_dn_ul_mbytes_after_reconnect"] = round(m["phases"][rec["name"]][n]["dn_ul_mbps"] * m["phases"][rec["name"]]["duration_s"] / 8, 3)
    m["headline"] = h
    (run_dir / "metrics.json").write_text(json.dumps(m, indent=1) + "\n")
    return m
