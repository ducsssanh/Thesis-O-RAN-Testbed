#!/usr/bin/env python3
"""Experiment runner of the two-layer defense testbed.

  run.py list                                   scenarios in experiments/scenarios/
  run.py run <scenario.yaml> [--reps N] [--variants a,b] [--tag T] [--stop-on-error]
  run.py report <artifacts/experiments/<campaign>>   recompute metrics and summary from stored files
  run.py restore                                defense back to the deployed configuration

A campaign = one scenario invocation: every variant (defense configuration)
x every repetition, interleaved (rep 1 of all variants, then rep 2, ...).
Layout of the results:

  artifacts/experiments/<YYYYmmdd-HHMMSS>_<scenario>[_<tag>]/
    campaign.json  runs.csv  summary.csv  summary.md
    runs/<variant>/rep-NN/
      run.json  phases.csv  metrics.json  error.txt (failed runs)
      meta/       snapshot_start.json, snapshot_end.json (defense state, UPF policies/stats), link_stats.json
      traffic/    flows.json (per-second receiver rows of every flow), <phase>_<ue>_<dir>.csv
      dataplane/  dn_per_second.csv (packets/bytes per UE address at the DN's N6)
      ran/        kpm.csv, kpm_cells.csv, rc_control.jsonl (E2SM-RC requests and acks), mac_stats.csv (gNB MAC counters, 1 s)
      core/       urr_received.jsonl (xApp), producer_normalized.jsonl, producer_smf_raw.jsonl,
                  adapter_delivery.jsonl, upf_audit.jsonl, pfcp.pcap, pfcp_messages.csv, pfcp_usage_reports.csv
      defense/    events.jsonl (evidence, level, action, verdict), features.jsonl, state_timeline.jsonl, db_rows.json
      logs/       xapp, flexric, gnb, upf, smf, amf, ue*.log.gz (since the run start, with timestamps)
"""
import argparse
import base64
import csv
import datetime
import json
import sys
import threading
import time
import traceback

import yaml

import collect
import lab
import metrics
import report
import traffic

SCEN_DIR = lab.ROOT / "experiments/scenarios"
OUT_DIR = lab.ROOT / "artifacts/experiments"
SUBDIRS = ("meta", "traffic", "dataplane", "ran", "core", "defense", "raw", "logs")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- defense config

def apply_defense(cfg, ue_names):
    """Variant defense settings through the xApp run-time API."""
    reqs = []
    base = "http://127.0.0.1:8090/v1/defense/"
    if "actuate" in cfg:                           # first: live detection test in observe mode (decisions logged, no action)
        reqs.append(["POST", base + "actuate", {"actuate": bool(cfg["actuate"])}])
    if "mode" in cfg:
        reqs.append(["POST", base + "mode", {"mode": cfg["mode"]}])
    if "core" in cfg:
        reqs.append(["POST", base + "core", {"enabled": bool(cfg["core"])}])
    if "timing" in cfg:
        reqs.append(["POST", base + "timing", cfg["timing"]])
    if "classifier" in cfg:
        reqs.append(["POST", base + "classifier", {"kind": cfg["classifier"]}])
    if "escalation" in cfg:                        # escalation by response (direction 1)
        reqs.append(["POST", base + "escalation", cfg["escalation"]])
    if cfg.get("clear_tamper"):                    # v5: no KPM tamper left from an earlier run
        reqs.append(["POST", base + "tamper", {"off": True}])
    for ue, cls in (cfg.get("classes") or {}).items():
        reqs.append(["POST", base + "policy", {"supi": lab.UES[ue][2], "class": cls}])
    for ue in ue_names:
        reqs.append(["POST", base + "reset", {"supi": lab.UES[ue][2]}])
    reqs.append(["POST", base + "enabled", {"enabled": bool(cfg.get("enabled", True))}])
    res = lab.http_many(reqs)
    bad = [(r[1], s, b) for r, (s, b) in zip(reqs, res) if s not in (200,) and not (r[1].endswith("reset") and s == 404)]
    if bad:
        raise lab.LabError("defense config rejected: %s" % bad)


def phase_hooks(p, run, ue_names):
    """v5 live phase annotations, before the phase's traffic starts: defence reset (gaps), KPM
    tamper of one UE, core-telemetry outage (A1-EI adapter scaled to 0). Returns what was done."""
    done, reqs = {}, []
    base = "http://127.0.0.1:8090/v1/defense/"
    if p.get("reset_defense"):
        reqs += [["POST", base + "reset", {"supi": lab.UES[n][2]}] for n in ue_names]
        reqs.append(["POST", base + "tamper", {"off": True}])
        done["reset_defense"] = True
    if p.get("force"):
        # end-to-end calibration (2026-11-13): put a benign UE at a level without a decision (POST /v1/defense/force);
        # a force with "at_s" is sent later, at_s seconds after second 0 of the phase's schedule (force_later())
        now_f = [f for f in (p["force"] if isinstance(p["force"], list) else [p["force"]]) if f.get("at_s") is None]
        for f in now_f:
            reqs.append(["POST", base + "force", {"supi": lab.UES[f["ue"]][2], "level": int(f["level"]), "ttl_s": int(f.get("ttl_s", 0))}])
        done["force"] = p["force"]
    if p.get("tamper"):
        t = p["tamper"]
        body = {"supi": lab.UES[t["ue"]][2], **{k: v for k, v in t.items() if k != "ue"}}   # factor, or series (replay of a benign KPM trace)
        reqs.append(["POST", base + "tamper", body])
        done["tamper"] = {**{k: v for k, v in t.items() if k != "series"}, "supi": lab.UES[t["ue"]][2], "series_len": len(t.get("series") or [])}
    if reqs:
        res = lab.http_many(reqs)
        bad = [(r[1], s) for r, (s, _) in zip(reqs, res) if s != 200 and not (r[1].endswith("reset") and s == 404)]
        if bad:
            raise lab.LabError("phase hook rejected: %s" % bad)
    if p.get("core_outage"):
        t0 = time.time()
        lab.kubectl("-n", "near-rt-ric", "scale", "deploy/a1-ei-adapter", "--replicas=0")
        lab.kubectl("-n", "near-rt-ric", "wait", "--for=delete", "pod", "-l", "app.kubernetes.io/name=a1-ei-adapter",
                    "--timeout=60s", check=False, timeout=70)
        done["core_outage"] = {"down_at": round(time.time(), 3), "down_s": round(time.time() - t0, 1)}
    return done


def force_later(p, flows, t_start):
    """forces with "at_s" (2026-11-13 calibration): a timer per force, at_s after second 0 of the schedule of that UE
    (start_at of its replay flow; else the phase start). Returns the timers and their log (filled when they fire)."""
    timers, log_ = [], []
    for f in (p.get("force") if isinstance(p.get("force"), list) else [p["force"]] if p.get("force") else []):
        if f.get("at_s") is None:
            continue
        t0 = min([x.start_at for x in flows if getattr(x, "start_at", None) and x.ue == f["ue"]] or [t_start])
        rec_ = {"ue": f["ue"], "at_s": f["at_s"], "planned_unix": round(t0 + float(f["at_s"]), 3)}
        log_.append(rec_)

        def fire(f=f, rec_=rec_):
            rec_["sent_unix"] = round(time.time(), 3)
            s_, _ = lab.defense("POST", "/v1/defense/force", {"supi": lab.UES[f["ue"]][2], "level": int(f["level"]), "ttl_s": int(f.get("ttl_s", 0))})
            rec_["status"] = s_
        t = threading.Timer(max(0.0, t0 + float(f["at_s"]) - time.time()), fire)
        t.daemon = True; t.start(); timers.append(t)
    return timers, log_


def phase_unhooks(p, done):
    """Undo phase_hooks after the phase: tamper off, adapter back (waits until it is ready)."""
    if done.get("tamper"):
        s, _ = lab.defense("POST", "/v1/defense/tamper", {"off": True})
        if s != 200:
            raise lab.LabError("tamper off rejected: HTTP %s" % s)
    if done.get("core_outage"):
        lab.kubectl("-n", "near-rt-ric", "scale", "deploy/a1-ei-adapter", "--replicas=1")
        lab.kubectl("-n", "near-rt-ric", "rollout", "status", "deploy/a1-ei-adapter", "--timeout=180s", timeout=190)
        done["core_outage"]["up_at"] = round(time.time(), 3)


_READY = r"""
import json, sys, time, datetime
d, supis = sys.argv[1], sys.argv[2].split(",")
def tail(f, n=40000):
    try:
        with open(d + f, "rb") as fh:
            fh.seek(0, 2); fh.seek(max(0, fh.tell() - n)); return fh.read().decode(errors="replace").splitlines()[1:]
    except OSError:
        return []
kpm, urr = {}, {}
for l in tail("KPI_Metrics_RawKpm.jsonl"):
    try: o = json.loads(l); kpm[o["supi"]] = max(kpm.get(o["supi"], 0), o["arrival_ts"])
    except (ValueError, KeyError): pass
for l in tail("urr-received.jsonl"):
    try: o = json.loads(l); urr[o["report"]["supi"]] = max(urr.get(o["report"]["supi"], 0), o["received_unix_ms"] / 1000.0)
    except (ValueError, KeyError): pass
now = time.time()
print(json.dumps({s: [round(now - kpm[s], 2) if s in kpm else None, round(now - urr[s], 2) if s in urr else None] for s in supis}))
"""


def readiness(ue_names, kpm_max=3.0, urr_max=3.0, max_wait=30.0):
    """v5: before a traffic phase, wait until the xApp has a KPM report younger than kpm_max s and a
    URR report received less than urr_max s ago for every UE (what the defence would see). Returns
    {wait_s, ages}; raises LabError (run not valid) after max_wait s."""
    supis = [lab.UES[n][2] for n in ue_names]
    t0, ages = time.time(), {}
    while True:
        try:
            ages = json.loads(lab.ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", _READY, collect.run_dir_xapp(),
                                     ",".join(supis), timeout=20).strip().splitlines()[-1])
        except Exception as e:
            ages = {"error": str(e)[:200]}
        ok = all(isinstance(ages.get(s), list) and ages[s][0] is not None and ages[s][0] < kpm_max
                 and ages[s][1] is not None and ages[s][1] < urr_max for s in supis)
        waited = round(time.time() - t0, 1)
        if ok:
            return {"wait_s": waited, "ages": ages}
        if waited >= max_wait:
            raise lab.LabError("readiness: KPM/URR not fresh after %.0f s (ages [kpm, urr] s: %s)" % (waited, json.dumps(ages)))
        time.sleep(1)


def ensure_alive(ue_names):
    """A UE whose PDU session is gone (e.g. released by T2 after a long block)
    is re-attached, then the xApp restarted (its KPM UE list)."""
    s, body = lab.upf("GET", "/v1/sessions")
    live = {x["supi"] for x in body.get("sessions", [])} if s == 200 else set()
    dead = [n for n in ue_names if lab.UES[n][2] not in live]
    for n in dead:
        log("  %s has no PDU session at the UPF: re-attach" % n)
        lab.restart_ue(n)
        lab.wait_amf_registered(lab.UES[n][2])
    if dead:
        lab.restart_xapp()
        time.sleep(25)
    return dead


def drain(ue_names, quiet_kbps, timeout):
    """Wait until every UE's KPM rate is quiet (the OAI UE buffers up to 50 MB UL)."""
    t0, quiet = time.time(), 0
    supis = [lab.UES[n][2] for n in ue_names]
    while time.time() - t0 < timeout:
        st = {u["supi"]: u for u in lab.defense_state()["ues"]}
        if all((st.get(s, {}).get("rate_ul_kbps") or 0) < quiet_kbps and (st.get(s, {}).get("rate_dl_kbps") or 0) < quiet_kbps
               for s in supis):
            quiet += 1
            if quiet >= 3:
                return round(time.time() - t0, 1)
        else:
            quiet = 0
        time.sleep(2)
    raise lab.LabError("UEs still sending after %d s (buffered UL); restart the UE pods" % timeout)


# ---------------------------------------------------------------- one run

def run_once(scn, variant, rep, camp_dir):
    ue_names = list(scn["ues"])
    run_dir = camp_dir / "runs" / variant["name"] / ("rep-%02d" % rep)
    for d in SUBDIRS:
        (run_dir / d).mkdir(parents=True, exist_ok=True)
    run = {"scenario": scn["name"], "variant": variant["name"], "rep": rep, "status": "running",
           "defense": {**scn.get("defense_common", {}), **variant.get("defense", {})}}
    (run_dir / "run.json").write_text(json.dumps(run, indent=1) + "\n")
    payload = scn.get("payload_bytes", 1200)
    try:
        log("== %s / %s / rep %d" % (scn["name"], variant["name"], rep))
        healed = ensure_alive(ue_names)
        facts = lab.preflight(ue_names)
        apply_defense(run["defense"], ue_names)
        dr = scn.get("drain", {})
        run["drain_s"] = drain(ue_names, dr.get("quiet_kbps", 300), dr.get("timeout_s", 300))
        run["preflight"], run["healed"] = facts, healed
        run["ues"] = {n: {"supi": lab.UES[n][2], "role": scn["ues"][n], "deployment": lab.UES[n][0],
                          "ip_history": [[0, facts["ues"][n]["ip"]]]} for n in ue_names}
        planned = sum(p.get("duration", 0) for p in scn["phases"]) + 600
        tag = "%s-%s-%02d-%d" % (scn["name"], variant["name"], rep, int(time.time()))
        rec, dn, pf = traffic.StateRecorder(), traffic.DnCounter(planned), traffic.PfcpCapture(tag, planned)
        mac = traffic.MacStats(planned)
        collect.snapshot(run_dir, "start")
        links = {"start": collect.link_stats()}
        t_run0 = time.time()
        rec.start()
        dn.start()
        mac.start()
        pf.start()
        time.sleep(2)
        phases, all_flows, port = [], [], 5400
        for p in scn["phases"]:
            ph = {"name": p["name"], **{k: p[k] for k in ("attack", "baseline", "reconnect") if k in p}}
            act = p.get("action") or {}
            if act.get("restart_ue"):
                n = act["restart_ue"]
                t_a = time.time()
                ip = lab.restart_ue(n)
                run["ues"][n]["ip_history"].append([round(time.time(), 3), ip])
                if act.get("restart_xapp"):
                    lab.wait_amf_registered(lab.UES[n][2])
                    lab.restart_xapp()
                    apply_defense(run["defense"], [])  # run-time settings are not persisted by the xApp
                ph["action"] = {**act, "seconds": round(time.time() - t_a, 1), "new_ip": ip}
            ips = {n: lab.ue_ip(n, wait=30) for n in ue_names}
            lab.ues_no_forward(ue_names)
            if run["defense"].get("readiness") and p.get("flows"):   # v5: fresh telemetry before the hooks
                ph["readiness"] = readiness(ue_names, **run["defense"]["readiness"])
            hooked = phase_hooks(p, run, ue_names)
            if hooked:
                ph["hooks"] = hooked
            flows = []
            cong = p.get("congestion")                 # phase-level env: {rate, burst?, latency?}
            for ue, dirs in (p.get("flows") or {}).items():
                for d, spec in dirs.items():
                    port += 1
                    if isinstance(spec, dict):
                        env = {}
                        if "victim_mode" in p and "victim_mode" not in spec:
                            env["victim_mode"] = p["victim_mode"]
                        if cong and "congestion" not in spec:
                            env["congestion"] = cong
                        if env:
                            spec = {**spec, **env}     # phase-level env properties
                        if spec.get("model") == "real_window" or spec.get("evasion"):
                            spec = {**spec, "seed": spec["seed"] + 100000 * (rep - 1)}  # each rep replays other windows
                    flows.append(traffic.make_flow(ue, d, spec, payload, p["duration"], port, ips[ue]))
            for f in flows:
                f.start_server()
            if flows:
                time.sleep(1.5)
            ph["t_start"] = round(time.time(), 3)
            for f in flows:
                f.start_client()
            f_timers, f_log = force_later(p, flows, ph["t_start"])
            if f_log:
                ph["force_later"] = f_log
            if cong:
                traffic.v4_set_congestion(cong)
                ph["congestion"] = cong
            stop = p.get("stop_when")
            # a real-window replay starts at its start_at, so the phase runs until its last second
            t_end = max([time.time() + p["duration"]] + [f.start_at + p["duration"] + 1 for f in flows if getattr(f, "start_at", None)])
            while time.time() < t_end:
                if stop and rec.level(lab.UES[stop["ue"]][2]) >= stop["level_gte"]:
                    hold = stop.get("hold_s", 0)
                    log("   stop_when met (%s level >= %d), holding %d s" % (stop["ue"], stop["level_gte"], hold))
                    time.sleep(hold)
                    ph["stopped_early"] = True
                    break
                time.sleep(0.5)
            ph["t_end"] = round(time.time(), 3)
            for t in f_timers:                         # a force still pending at the phase end is not sent
                t.cancel()
            if cong:
                traffic.v4_clear_congestion()
            for f in flows:
                f.stop()
            for f in flows:
                f.finish()
            if hooked:
                phase_unhooks(p, hooked)
            for f in flows:
                all_flows.append({"phase": p["name"], **f.summary(), "rows": f.rows, "client": f.client_out[-2000:]})
            phases.append(ph)
            log("   phase %-10s %5.1f s  %s" % (p["name"], ph["t_end"] - ph["t_start"],
                ", ".join("%s %s %.2f/%.2f Mb/s" % (x["ue"], x["dir"], x["rx_mbps_mean"], x["offered_bps"] / 1e6)
                          for x in all_flows if x["phase"] == p["name"])))
        time.sleep(scn.get("tail_s", 8))  # URR arrives 1-2 s after the traffic; final verdicts
        t_run1 = time.time()
        rec.stop_flag = True
        rec.join(timeout=5)
        dn.stop()
        mac.stop()
        pf.stop()
        links["end"] = collect.link_stats()
        collect.snapshot(run_dir, "end")
        w0, w1 = t_run0 - 2, t_run1 + 2
        log("   collecting records")
        (run_dir / "defense/state_timeline.jsonl").write_text(rec.jsonl())
        (run_dir / "dataplane/dn_per_second.csv").write_text(dn.csv)
        (run_dir / "meta/link_stats.json").write_text(json.dumps(links, indent=1) + "\n")
        (run_dir / "traffic/flows.json").write_text(json.dumps(all_flows) + "\n")
        for f in all_flows:
            with (run_dir / ("traffic/%s_%s_%s.csv" % (f["phase"], f["ue"], f["dir"]))).open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["t_unix", "interval_start_s", "interval_end_s", "bytes", "bps", "jitter_ms", "lost", "total", "final"])
                for r in f["rows"]:
                    w.writerow([r["t"], r["interval"][0], r["interval"][1], r["bytes"], r["bps"], r["jitter_ms"], r["lost"], r["total"],
                                int(r["final"])])
        collect.export_ran(run_dir, w0, w1)
        (run_dir / "ran/mac_stats.csv").write_text(collect.parse_mac_stats(mac.raw, collect.ue_rnti(ue_names)))
        collect.export_core(run_dir, w0, w1)
        collect.export_defense(run_dir, w0, w1)
        collect.export_logs(run_dir, w0, ue_names)
        (run_dir / "core/pfcp_messages.csv").write_text(
            pf.fields("pfcp", ["frame.time_epoch", "ip.src", "ip.dst", "pfcp.msg_type", "pfcp.seid", "pfcp.cause"]))
        (run_dir / "core/pfcp_usage_reports.csv").write_text(pf.fields(
            "pfcp.msg_type == 56", ["frame.time_epoch", "pfcp.seid", "pfcp.urr_id", "pfcp.ur_seqn", "pfcp.volume_measurement.ulvol",
                                    "pfcp.volume_measurement.dlvol", "pfcp.volume_measurement.ulnop", "pfcp.volume_measurement.dlnop",
                                    "pfcp.duration_measurement", "pfcp.usage_report_trigger_flags.perio",
                                    "pfcp.usage_report_trigger_flags.upint"]))
        raw = pf.raw()
        if raw.strip():
            (run_dir / "core/pfcp.pcap").write_bytes(base64.b64decode(raw))
        pf.cleanup()
        with (run_dir / "phases.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["phase", "t_start_unix", "t_end_unix", "duration_s", "attack", "baseline", "reconnect", "stopped_early", "action"])
            for ph in phases:
                w.writerow([ph["name"], ph["t_start"], ph["t_end"], round(ph["t_end"] - ph["t_start"], 1), int(bool(ph.get("attack"))),
                            int(bool(ph.get("baseline"))), int(bool(ph.get("reconnect"))), int(bool(ph.get("stopped_early"))),
                            json.dumps(ph.get("action", ""))])
        run.update({"status": "ok", "phases": phases, "t_start": t_run0, "t_end": t_run1, "recorder_errors": rec.errors})
        (run_dir / "run.json").write_text(json.dumps(run, indent=1) + "\n")
        m = metrics.compute(run_dir)
        log("   headline " + json.dumps(m["headline"]))
        return True
    except Exception as e:
        run.update({"status": "failed", "error": str(e)})
        (run_dir / "run.json").write_text(json.dumps(run, indent=1) + "\n")
        (run_dir / "error.txt").write_text(traceback.format_exc())
        for d in (["oai-core", "oai-lab-dn", "dn"],) + tuple(["oai-ran", lab.UES[n][0], "nr-ue"] for n in ue_names):
            lab.ex(*d, "pkill", "iperf", check=False)
        try:
            traffic.v4_clear_congestion()             # never leave tc shaping on the UPF
        except Exception:
            pass
        try:                                          # never leave the core path down or a tamper on
            lab.kubectl("-n", "near-rt-ric", "scale", "deploy/a1-ei-adapter", "--replicas=1", check=False)
            lab.defense("POST", "/v1/defense/tamper", {"off": True})
        except Exception:
            pass
        log("   FAILED: %s" % e)
        return False


# ---------------------------------------------------------------- commands

def cmd_run(args):
    scn_path = args.scenario if args.scenario.endswith(".yaml") else str(SCEN_DIR / (args.scenario + ".yaml"))
    scn = yaml.safe_load(open(scn_path))
    variants = [v for v in scn["variants"] if not args.variants or v["name"] in args.variants.split(",")]
    reps = args.reps or scn.get("reps", 1)
    cid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "_" + scn["name"] + ("_" + args.tag if args.tag else "")
    camp = OUT_DIR / cid
    camp.mkdir(parents=True)
    st = lab.defense_state()
    restore = {"timing": {"expiryS": st["timing"]["expiry_s"], "probationS": st["timing"]["probation_s"],
                          "fusionS": st["timing"]["fusion_s"]}, "mode": st.get("action_mode"), "core": st.get("core", {}).get("enabled"),
               "enabled": st.get("enabled")}
    (camp / "campaign.json").write_text(json.dumps({"id": cid, "scenario_file": scn_path, "scenario": scn, "reps": reps,
                                                     "variants": [v["name"] for v in variants], "started": time.time(),
                                                     "images": lab.images(), "restore": restore}, indent=1) + "\n")
    log("campaign %s: %d variant(s) x %d rep(s) -> %s" % (cid, len(variants), reps, camp))
    try:
        for rep in range(1, reps + 1):
            for v in variants:
                ok = run_once(scn, v, rep, camp)
                if not ok and args.stop_on_error:
                    raise SystemExit(1)
    finally:
        log("restoring defense configuration %s" % json.dumps(restore))
        try:
            apply_defense(restore, list(scn["ues"]))  # also resets the scenario's UEs: level 0, no UPF policy
        except Exception as e:
            log("restore failed: %s" % e)
        text = report.build(camp)
        print(text)
        log("results: %s" % camp)


def cmd_report(args):
    from pathlib import Path
    print(report.build(Path(args.campaign)))


def cmd_list(_):
    for p in sorted(SCEN_DIR.glob("*.yaml")):
        s = yaml.safe_load(open(p))
        print("%-22s %-60s variants: %s, reps %s" % (p.stem, s.get("description", "").strip().splitlines()[0][:60],
                                                    ",".join(v["name"] for v in s["variants"]), s.get("reps", 1)))


def cmd_restore(_):
    import staged
    cfg = yaml.safe_load((staged.DEPLOY / "values/minikube.yaml").read_text())["global"]["lab"]["defense"]["xapp"]
    prof = cfg.get("profile", "lab")
    apply_defense({"enabled": cfg.get("enabled", True), "core": cfg.get("core", {}).get("enabled", False),
                   "mode": cfg.get("action", {}).get("mode", "slice"),
                   "timing": {"expiryS": cfg["expiryS"][prof], "probationS": cfg["confirm"]["probationS"],
                              "fusionS": cfg.get("core", {}).get("fusionS", 10)}}, [])
    print("defense restored to deploy/k8s/values/minikube.yaml")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("scenario")
    r.add_argument("--reps", type=int)
    r.add_argument("--variants")
    r.add_argument("--tag")
    r.add_argument("--stop-on-error", action="store_true")
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("report")
    p.add_argument("campaign")
    p.set_defaults(fn=cmd_report)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("restore").set_defaults(fn=cmd_restore)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
