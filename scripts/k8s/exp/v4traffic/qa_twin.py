#!/usr/bin/env python3
"""Per-run QA of a twin campaign run: returns the problems that make it unusable. A run is kept only if it has none. Usage: qa_twin.py <run dir>..."""
import gzip, json, pathlib, sys
import numpy as np
BETA = 57
MIN_DELIVERED = {"L1": .8, "L2": .7, "L3": .8}


def qa_run(run, expected_phases=6, live=False, e2e=None):
    """e2e: the manifest run of an end-to-end run (actions on). There the attacker UE is limited, blocked and released on
    purpose, so its MAC gaps, new RNTI, RLC failures and dead DL are outcomes, not faults; the attack is checked as sent
    by the generator (what reaches the core is measured, not required); the reactive flows must have run. A UE the
    defence acted on wrongly (benign UE limited or blocked) gets the same treatment in the phases it was acted on:
    rejecting those runs would drop exactly the false actions the end-to-end test has to count."""
    e2e = e2e if isinstance(e2e, dict) and e2e.get("e2e") else None
    att = e2e.get("attacker") if e2e else None
    run = pathlib.Path(run); out = []
    if not (run / "traffic/flows.json").exists():
        return ["no data"]
    meta = json.loads((run / "run.json").read_text())
    if meta.get("status") != "ok":
        out.append("status %s" % meta.get("status"))
    flows = json.loads((run / "traffic/flows.json").read_text())
    ue = {u: m["supi"] for u, m in meta["ues"].items()}
    steps = {}   # e2e: level step function per UE, from the defence's level events
    if e2e and (run / "defense/events.jsonl").exists():
        for l in open(run / "defense/events.jsonl"):
            x = json.loads(l)
            if x.get("type") == "level":
                steps.setdefault(x["supi"], []).append((x["at_ms"] / 1000.0, x.get("from", 0), x["level"]))

    def acted(n, t0=None, t1=None):
        """the defence held UE n above level 0 at some time in [t0, t1] (the whole run if no interval)"""
        st = sorted(steps.get(ue[n], []))
        if t0 is None:
            return any(lv > 0 for _, _, lv in st)
        at_t0 = ([lv for ts, _, lv in st if ts <= t0] or [0])[-1]
        return at_t0 > 0 or any(t0 <= ts <= t1 and lv > 0 for ts, _, lv in st)
    F = {}
    for l in open(run / "defense/features.jsonl"):
        x = json.loads(l)
        F.setdefault(x["supi"], {})[x["at_ms"] // 1000] = x
    all_x = [x for u in F.values() for x in u.values()]
    if np.mean([min(x["collect_ms"] % 1000, 1000 - x["collect_ms"] % 1000) > 100 for x in all_x]) > .01:
        out.append("KPM phase off")
    if np.mean(["prof_ul_pps" not in x for x in all_x]) > .01:
        out.append("profile missing")
    for n in ("ue1", "ue2"):
        if n == att or (e2e and acted(n)):
            continue
        if gzip.open(run / ("logs/%s.log.gz" % n), "rt", errors="ignore").read().count("max RETX"):
            out.append("RLC failure " + n)
    if live or e2e:   # the run's config (classifier, timing, escalation) is set over REST at the start; an xApp that
        # restarted mid-run (FlexRIC assertion, 2026-11-13 lf001) comes back with the default config: the rest is not the test
        x = run / "logs/xapp.log.gz"
        if x.exists() and gzip.open(x, "rt", errors="ignore").read().count("[defense] enabled"):
            out.append("xApp restarted during the run")
    if live:   # live detection test: decisions are expected; the embedded model must have scored the run
        c = run / "defense/clf.jsonl"
        if not c.exists() or not c.stat().st_size:
            out.append("no embedded-model scores (xApp restarted or classifier not xgb)")
    elif (run / "defense/events.jsonl").exists() and (run / "defense/events.jsonl").stat().st_size:
        out.append("defence acted")
    mac = {}
    for x in open(run / "ran/mac_stats.csv").read().splitlines()[1:]:
        f = x.split(","); mac.setdefault(f[2], []).append((float(f[0]), f[1], int(f[4]), int(f[5])))
    twins = [f for f in flows if (f.get("v4_meta") or {}).get("model") == "real_window"]
    if len(twins) != 2 * expected_phases:
        out.append("twin flows %d" % len(twins))
    for f in twins:
        if f["ue"] == att or (e2e and acted(f["ue"], f["replay_start_at"], f["replay_start_at"] + 76)):
            continue
        m = mac.get(f["ue"]) or []
        t = [r for r in m if f["replay_start_at"] <= r[0] <= f["replay_start_at"] + 76]
        if len(t) < 70 or len({r[1] for r in t}) > 1:
            out.append("MAC gap or new RNTI %s %s" % (f["phase"], f["ue"]))
            continue
        target = f["v4_meta"]["target_dl_mean_bytes_s"] * 75
        # a dead DL is near 0 (SMF crash). A single burst of 180 kB can legitimately lose half at the testbed (c027, same on 3 attempts); the ratio is kept per window in the dataset
        if target >= 5000 and t[-1][3] - t[0][3] < target / 4:
            out.append("dead DL %s %s" % (f["phase"], f["ue"]))
    for f in flows:
        m = f.get("v4_meta") or {}
        if m.get("model") != "flood_overlay":
            continue
        if f.get("backend_failed"):
            out.append("generator failed %s %s" % (f["phase"], f["ue"]))
        if m.get("role") != "attack":
            continue
        if e2e:   # sent by the generator, >= 90 % of the plan
            sent = sum((r.get("bytes") or 0) for r in f.get("rows", []))
            plan = m["target_mean_bytes_s"] * len(f.get("rows", [])) if f.get("rows") else 0
            if plan and sent < .9 * plan and m["evasion"] != "L3":
                out.append("attack not sent %.2f %s %s" % (sent / plan, f["phase"], f["ue"]))
            continue
        tw = next(x for x in twins if x["phase"] == f["phase"] and x["ue"] == f["ue"])
        z = np.load(pathlib.Path(__file__).resolve().parents[4] / "research/twinning/benign_windows.npz")
        twin = z["ul_" + tw["v4_meta"]["band"]][tw["v4_meta"]["window"]["index"]]
        # bytes over the whole phase: a row of second t holds [t-1, t), and bytes of a burst can land one second later
        ts, S = int(np.floor(tw["replay_start_at"])) + 1, F[ue[f["ue"]]]
        core = 0.0
        for j in range(77):
            x = S.get(ts + j)
            if x and "prof_ul_pps" in x:
                core += max(x["prof_ul_kbps"] * 125 - BETA * x["prof_ul_pps"], 0)
        plan = m["target_mean_bytes_s"] * 75
        d = (core - float(twin.sum())) / plan if plan else 0.0
        if d < MIN_DELIVERED[m["evasion"]]:
            out.append("attack delivered %.2f %s %s %s" % (d, f["phase"], f["ue"], m["evasion"]))
    if e2e:
        if not (run / "dataplane/dn_per_second.csv").read_text().splitlines()[0].endswith("dn_port"):
            out.append("DN counts without ports")
        for f in twins:
            if max([r.get("reports", 0) for r in f.get("rows", [])] or [0]) < 60:   # about one report a second
                out.append("reactive flow without receive reports %s %s" % (f["phase"], f["ue"]))
        # 2026-11-13: closed-loop benign L3 clients log their window; the relative escalation logs its inputs at level 2;
        # a delayed forced limit is sent within 1 s of its planned second and logged as a forced level event
        for f in flows:
            m = f.get("v4_meta") or {}
            if m.get("model") == "flood_overlay" and m.get("role") == "benign" and m.get("closed_loop"):
                if not any(r.get("closed_loop") and "window" in r for r in f.get("rows", [])):
                    out.append("closed-loop client without its log %s %s" % (f["phase"], f["ue"]))
        # 2026-11-14 (lh001-lh004): a UE whose UL data bearer is dead from the start (gNB LCID 4 RX frozen after slice
        # handovers in the previous run; the generator sends, nothing reaches the UPF or the DN). Checked in p0, before any
        # attack and any action, so it does not depend on the defence; < 5 % = dead (real loss at level 0 stays above:
        # the DNS bursts of design run 009 deliver 17-34 %)
        import csv
        p0 = next((p for p in json.loads((run / "run.json").read_text()).get("phases", []) if p.get("name") == "p0"), None)
        pr = {r["phase"]: (float(r["t_start_unix"]), float(r["t_end_unix"])) for r in csv.DictReader(open(run / "phases.csv"))}
        if "p0" in pr:
            t0, t1 = pr["p0"]
            got = {}
            for r in csv.DictReader(open(run / "dataplane/dn_per_second.csv")):
                if r["dir"] == "ul" and t0 <= int(r["t"]) < t1:
                    got[r["ue_ip"]] = got.get(r["ue_ip"], 0) + int(r["ip_payload_bytes"])
            for n in ("ue1", "ue2"):
                sent = sum(float(r["bytes"]) for f in flows if f["ue"] == n and f.get("dir", "ul") == "ul" and f["phase"] == "p0"
                           for r in f.get("rows", []) if not r.get("final") and r.get("bytes") is not None)
                ip = (meta["ues"][n].get("ip_history") or [[0, None]])[-1][1]
                if sent > 10e3 and got.get(ip, 0) < .05 * sent:
                    out.append("dead UL p0 %s (%.0f of %.0f kB at the DN)" % (n, got.get(ip, 0) / 1e3, sent / 1e3))
        ev = [json.loads(x) for x in open(run / "defense/events.jsonl")] if (run / "defense/events.jsonl").exists() else []
        clf = [json.loads(x) for x in open(run / "defense/clf.jsonl")] if (run / "defense/clf.jsonl").exists() else []
        if any(e.get("type") == "level" and e.get("level") == 2 for e in ev) and not any("esc_offered" in c for c in clf):
            out.append("level 2 reached but no relative-escalation log (esc_offered)")
        rj = json.loads((run / "run.json").read_text())
        for ph in rj.get("phases", []):
            for x in ph.get("force_later", []):
                if x.get("status") != 200 or abs(x.get("sent_unix", 1e18) - x["planned_unix"]) > 1.0:
                    out.append("forced limit late or rejected %s %s %s" % (ph["name"], x["ue"], x.get("status")))
                    continue
                # a UE already at that level (e.g. limited by the model just before) gets no level event: the force
                # only restarts the TTL (defense.c /v1/defense/force -> policy_set_level logs changes only)
                supi = rj["ues"][x["ue"]]["supi"]
                lv = 0
                for e in sorted((e for e in ev if e.get("type") == "level" and e.get("supi") == supi), key=lambda e: e["at_ms"]):
                    if e["at_ms"] / 1000 <= x["sent_unix"]:
                        lv = e["level"]
                forced_level = next((f["level"] for f in (lambda q: q if isinstance(q, list) else [q])(
                    next(p for p in (e2e.get("phases") or []) if p["name"] == ph["name"]).get("force")) if f["ue"] == x["ue"]), 2)
                if lv < forced_level and not any(e.get("type") == "level" and e.get("why") == "forced" and abs(e["at_ms"] / 1000 - x["sent_unix"]) <= 2.0 for e in ev):
                    out.append("forced limit without its level event %s %s" % (ph["name"], x["ue"]))
    return out


if __name__ == "__main__":
    for r in sys.argv[1:]:
        print(r.split("/")[-4][-30:], qa_run(r) or "clean")
