#!/usr/bin/env python3
"""v5 live: latency of one control-loop iteration (one KPM report -> action), from the run logs.

  .venv-ml/bin/python -I scripts/ml/loop_latency_v5.py      -> reports/loop_latency_v5.json

Valid main-campaign runs; detection-triggered actions only (level >= 1; expiry / gap-reset actions are
timer driven). Each action is matched to the newest KPM report that reached the xApp before the command
left it (events' at_ms is stamped at KPM ingest, before the sidecar call). All pods share one node clock.
  e2_ind       gNB KPM source_ts -> xApp arrival
  xapp_proc    KPM arrival -> E2SM-RC control sent (features + sidecar + policy)
  rc_ack       E2SM-RC sent -> gNB ack
  ran_e2e      gNB KPM source_ts -> RC ack                      (RAN loop)
  upf_put      decision -> UPF Security API PUT accepted
  core_e2e_dec gNB KPM source_ts -> UPF policy in force          (core loop)
  sidecar      /classify server time; kpm_period / urr_period: report spacing
  urr_deliv    URR observed_at (SMF) -> xApp receipt (core telemetry path, A1-EI; core_outage runs excluded)
"""
import json, glob, bisect, datetime, numpy as np
def jl(p):
    try:
        for l in open(p):
            try: yield json.loads(l)
            except ValueError: pass
    except OSError: return
def iso(s):
    s = s.rstrip("Z"); a, _, f = s.partition(".")
    return datetime.datetime.fromisoformat(a + "+00:00").timestamp() + (float("0." + f) if f else 0.0)
A = {k: [] for k in ["e2_ind", "xapp_proc", "rc_send", "rc_ack", "ran_e2e", "upf_put", "core_e2e_dec", "sidecar", "kpm_period", "urr_deliv", "urr_period"]}
n_runs = 0
for rj in glob.glob("artifacts/experiments/*_v5live_main_s*/runs/*/rep-*/run.json"):
    m = json.load(open(rj))
    if m.get("meta_run_ok") != 1: continue
    d = rj[:-9]; n_runs += 1
    kpm = {}
    for o in jl(d + "/raw/kpm.jsonl"): kpm.setdefault(o["supi"], []).append((o["arrival_ts"], o["source_ts"]))
    for s, v in kpm.items():
        v.sort(); a = [x[0] for x in v]
        A["kpm_period"] += list(np.diff(a))
        A["e2_ind"] += [(x[0] - x[1]) * 1000 for x in v]
    urr = {}
    for o in (jl(d + "/core/urr_received.jsonl") if m.get("scenario") != "core_outage" else []):
        r = o["report"]; t = iso(r["observed_at"]); urr.setdefault(r["supi"], []).append(t)
        A["urr_deliv"].append(o["received_unix_ms"] - t * 1000)
    for v in urr.values(): A["urr_period"] += list(np.diff(sorted(v)))
    for o in jl(d + "/defense/sidecar.jsonl"):
        if "latency_ms" in o: A["sidecar"].append(o["latency_ms"])
    audit = sorted((o["ts_ms"], o["supi"]) for o in jl(d + "/core/upf_audit.jsonl") if o.get("op") == "put" and o.get("status") == 200)
    for e in jl(d + "/defense/events.jsonl"):
        if e.get("type") != "action" or (e.get("level") or 0) < 1: continue   # detection-triggered only
        v = kpm.get(e["supi"], []); r = e.get("result") or {}
        def trig(t_ms):                   # newest KPM that arrived before the command left the xApp
            i = bisect.bisect_right([x[0] for x in v], t_ms / 1000) - 1
            return v[i] if i >= 0 else (None, None)
        if e.get("layer") == "ran" and r.get("sent_unix_ms") and r.get("action") == "slice_handover":
            arr, src = trig(r["sent_unix_ms"])
            if arr is None: continue
            A["xapp_proc"].append(r["sent_unix_ms"] - arr * 1000)
            A["rc_send"].append(r["sent_unix_ms"] - e["at_ms"])   # = sidecar call + policy (at_ms = KPM ingest)
            A["rc_ack"].append(r["ack_latency_ms"])
            A["ran_e2e"].append(r["sent_unix_ms"] + r["ack_latency_ms"] - src * 1000)
        elif e.get("layer") == "core" and e.get("http") == 200:
            nxt = next((ts for ts, s in audit if s == e["supi"] and ts >= e["at_ms"] - 50), None)
            if nxt is not None and nxt - e["at_ms"] < 2000:
                arr, src = trig(nxt)
                if arr is None: continue
                A["upf_put"].append(nxt - e["at_ms"])
                A["core_e2e_dec"].append(nxt - src * 1000)
out = {"valid_runs": n_runs}
for k, v in A.items():
    v = np.array(v, float)
    if k.endswith("period"): v = v * 1000
    if len(v):
        out[k] = {"n": int(len(v)), "p50": round(float(np.percentile(v, 50)), 1), "p90": round(float(np.percentile(v, 90)), 1),
                  "p99": round(float(np.percentile(v, 99)), 1), "max": round(float(v.max()), 1)}
        print("%-13s n=%6d  p50 %8.1f  p90 %8.1f  p99 %8.1f  max %8.1f ms" % (k, len(v), *np.percentile(v, [50, 90, 99]), v.max()))
import pathlib
(pathlib.Path(__file__).resolve().parents[2] / "research/datasets/oran_flooding_v5_live/reports/loop_latency_v5.json").write_text(json.dumps(out, indent=1) + "\n")
