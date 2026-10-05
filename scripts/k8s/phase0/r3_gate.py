#!/usr/bin/env python3
"""Gate R3 (plan 14): the automatic RAN layer of the defense in the xApp (C31, C32).

Usage: r3_gate.py <out-dir> [flood-s=90] [--no-control] [--no-reconnect] [--no-expiry]
       r3_gate.py --evaluate <out-dir>   (re-check a stored run, no traffic)

Prerequisite: both UEs attached with SUPI labels (R1), xApp with defense
(rollout_xapp_defense.py). The gate sets the fair-use classes: UE1 default
(3 Mbit/s UL), UE2 heavy (5 Mbit/s UL: a legitimate heavy user at 3 Mbit/s, which the default class
would flag in a busy cell); UE2 offers less than it gets, so no backlog;
UE2 goes back to default at the end.
Uplink:
  idle     UE1 4M alone (20 s)          above the default class but nobody else
                                        sends: no evidence (congestion rule)
  warmup   UE1 1M + UE2 1M (15 s)       OAI UL link adaptation drops an idle
                                        UE's MCS to 0 within ~8 s and ramps it
                                        up slowly; a UE entering a busy cell at
                                        MCS 0 buffers and later bursts
  benign   UE1 1M + UE2 3M (30 s)       no evidence for either UE
  flood    UE1 30M + UE2 3M (flood-s)   UE1 to level 1 (PRB quota); the quota
                                        is lifted at the level-1 expiry (60 s)
                                        and the flood still running is a
                                        repeat offense: level 2
  reconnect UE1 pod restarted (new AMF UE NGAP ID; also empties the OAI UE's
           50 MB RLC buffer) + xApp restarted, UE1 at 0.5M (30 s): level
           restored from the DB, quota on the new UE ID
  expiry   no traffic                   level falls to 0, quota removed
A control run (defense off: benign + flood) comes first and shows the harm.
The OAI UE buffers up to 50 MB UL (RLC AM, RLC_TX_MAXSIZE x 5) and keeps
sending it after iperf stops, so the gate waits for both UEs' KPM rates to
fall before the next run (drain time recorded).
Checks:
  1. no false positive: no evidence in idle/warmup/benign, none ever for UE2
  2. idle cell: UE1 above its class while the cell is not busy is counted in
     uncongested_samples and is not evidence
  3. quota applied <= 2 s after the decision sample (the evidence's KPM
     sample); the time from flood start is reported separately
  4. quota holds: UE1's UL PRB share while a quota is in force <= ratio + 3 (mean)
  5. repeat offense: quota lifted at the level-1 expiry, then level 2
  6. UE2 unaffected: its flood-phase rate >= 90 % of its benign-phase rate
     (the control run's ratio shows the harm without the defense)
  7. level never above 2 (RAN evidence alone)
  8. reconnect: quota re-applied on UE1's new UE ID
  9. expiry: level back to 0 and quota removed (ratio 100, HTTP 200)
 10. DB: evidence and actions rows for UE1 in /urr-state/defense.db
"""
import csv
import io
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import r2_gate as r2  # noqa: E402  (kubectl helpers, AMF table, iperf flows)

ROOT = r2.ROOT
SUPI = {"oai-nr-ue": "imsi-001010123456780", "oai-nr-ue2": "imsi-001010123456781"}
PRB = "RRU.PrbTotUl (%)"
CLASS = {"oai-nr-ue": "default", "oai-nr-ue2": "heavy"}
DECISION_S = 2.0
HOLD_MARGIN = 3
QUIET_KBPS = 300


def http(method, path, body=None):
    """Defense/RAN-control endpoint on the xApp loopback."""
    code = ("import json,sys,urllib.request,urllib.error\n"
            "b=sys.argv[3].encode() if sys.argv[3] else None\n"
            "r=urllib.request.Request('http://127.0.0.1:8090'+sys.argv[2],data=b,method=sys.argv[1])\n"
            "try:\n s=urllib.request.urlopen(r,timeout=20);print(s.status,s.read().decode())\n"
            "except urllib.error.HTTPError as e:print(e.code,e.read().decode())\n")
    out = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", code, method, path,
                json.dumps(body) if body is not None else "", timeout=40).strip()
    status, _, text = out.partition(" ")
    return int(status), json.loads(text)


def state():
    return http("GET", "/v1/defense/state")[1]


def ue_ip(dep):
    ip = r2.ex("oai-ran", dep, "nr-ue", "ip", "-4", "-o", "addr", "show", "oaitun_ue1").split()[3].split("/")[0]
    r2.ex("oai-ran", dep, "nr-ue", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1", "src", ip)
    r2.UES[dep]["ip"] = ip
    return ip


# ---- load generation (one place; swap for another traffic generator) ----

def load(rates, dur):
    """UL UDP flows from the UEs in `rates` ({deployment: "2M"}) for dur seconds.
    Returns ({deployment: receiver Mbit/s}, (t0, t1))."""
    rep, window = r2.run_flows("ul", dur, rates)
    return {d: r2.mbps(x) for d, x in rep.items()}, window


def phase(result, name, rates, dur):
    mbps, window = load(rates, dur)
    st = state()
    result["phases"][name] = {"window_unix": [round(window[0], 3), round(window[1], 3)], "mbps": mbps,
                              "offered": rates, "uncongested_samples": st.get("uncongested_samples"),
                              "levels": {u["supi"]: u["level"] for u in st.get("ues", [])}}
    print("%-10s %s  uncongested=%s levels=%s" % (name, mbps, st.get("uncongested_samples"),
                                                 result["phases"][name]["levels"]), flush=True)
    time.sleep(2)


def reset_both():
    for s in SUPI.values():
        http("POST", "/v1/defense/reset", {"supi": s})


def wait_drain(supi, timeout=300):
    """Seconds until the UE's KPM UL rate stays below QUIET_KBPS (3 polls)."""
    t0, quiet = time.time(), 0
    while time.time() - t0 < timeout:
        u = next((x for x in state()["ues"] if x["supi"] == supi), {})
        quiet = quiet + 1 if u.get("rate_ul_kbps", 0) < QUIET_KBPS else 0
        if quiet >= 3:
            return round(time.time() - t0, 1)
        time.sleep(2)
    raise SystemExit("%s still sending after %d s" % (supi, timeout))


def wait_drain_all():
    return {d: wait_drain(SUPI[d]) for d in SUPI}


def wait_ip(dep, tries=60):
    for _ in range(tries):
        try:
            return ue_ip(dep)
        except (subprocess.CalledProcessError, IndexError):
            time.sleep(3)
    raise SystemExit(dep + " has no tunnel IP")


def restart_xapp():
    r2.kubectl("-n", "near-rt-ric", "rollout", "restart", "deploy/oai-lab-xapp")
    r2.kubectl("-n", "near-rt-ric", "rollout", "status", "deploy/oai-lab-xapp", "--timeout=120s", timeout=130)
    for _ in range(40):
        log = r2.kubectl("-n", "near-rt-ric", "logs", "deploy/oai-lab-xapp", check=False)
        if "RAN control on" in log or "Assertion" in log:
            break
        time.sleep(3)
    if "Assertion" in log:
        raise SystemExit("xApp asserted after restart (FlexRIC stuck: run recover_ran.sh)")
    return log


def reconnect(result):
    """New UE ID for UE1's SUPI: UE pod restart, then the xApp (its UE list is
    taken at the KPM subscription)."""
    old = r2.amf_table().get(SUPI["oai-nr-ue"])
    r2.kubectl("-n", "oai-ran", "rollout", "restart", "deploy/oai-nr-ue")
    r2.kubectl("-n", "oai-ran", "rollout", "status", "deploy/oai-nr-ue", "--timeout=180s", timeout=190)
    wait_ip("oai-nr-ue")
    time.sleep(25)  # AMF UE table period
    new = r2.amf_table().get(SUPI["oai-nr-ue"])
    t_restart = time.time()
    log = restart_xapp()
    result["reconnect"] = {"amf_old": old, "amf_new": new, "xapp_restart_unix": round(t_restart, 3),
                           "restored_log": [l for l in log.splitlines() if "[defense] restored" in l]}
    time.sleep(25)  # SUPI mapping of the new UE ID


def fetch(run, out):
    base = "/artifacts/runs/" + run + "/"
    raw = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", base + "KPI_Metrics.csv", timeout=90)
    ev = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", base + "KPI_Metrics_Defense.jsonl", check=False)
    q = ("import sqlite3,json,sys\nc=sqlite3.connect('file:/urr-state/defense.db?mode=ro',uri=True)\n"
         "print(json.dumps({t:[list(r) for r in c.execute('SELECT * FROM '+t+' WHERE supi=? AND at>=?',(sys.argv[1],sys.argv[2]))]"
         " for t in ('evidence','actions')}))\n")
    db = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", q, SUPI["oai-nr-ue"],
               time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(json.loads((out / "result.json").read_text())["started_unix"]))
               if (out / "result.json").exists() else "", check=False)
    (out / "KPI_Metrics.csv").write_text(raw)
    (out / "defense.jsonl").write_text(ev)
    (out / "defense-db.json").write_text(db or "{}")


def evaluate(out):
    result = json.loads((out / "result.json").read_text())
    rows = list(csv.DictReader(io.StringIO((out / "KPI_Metrics.csv").read_text())))
    t0 = result["started_unix"] * 1000
    events = [e for e in (json.loads(l) for l in (out / "defense.jsonl").read_text().splitlines() if l.strip())
              if e.get("at_ms", 0) >= t0]
    db = json.loads((out / "defense-db.json").read_text() or "{}")
    ph = result["phases"]
    s1, s2 = SUPI["oai-nr-ue"], SUPI["oai-nr-ue2"]
    ratio = result["max_prb_ratio"]
    checks = result["checks"] = {}

    def within(e, name):
        w = ph[name]["window_unix"]
        return w[0] * 1000 <= e["at_ms"] <= w[1] * 1000 + 2000

    evid = [e for e in events if e["type"] == "evidence"]
    quiet = [e for e in evid if any(within(e, p) for p in ("idle", "warmup", "benign"))]
    checks["no_false_positive"] = {"ok": not quiet and not any(e["supi"] == s2 for e in evid),
                                   "evidence_benign_idle": len(quiet), "evidence_ue2": sum(e["supi"] == s2 for e in evid)}
    unc = ph["idle"]["uncongested_samples"] - result.get("uncongested_before_idle", 0)
    checks["idle_cell_not_violation"] = {"ok": unc >= 5 and not any(within(e, "idle") for e in evid),
                                         "uncongested_samples_in_idle": unc, "ue1_idle_mbps": ph["idle"]["mbps"].get("oai-nr-ue")}

    fw = ph["flood"]["window_unix"]
    first = next((e for e in evid if e["supi"] == s1 and e["kind"].startswith("kpm_") and e["kind"] != "kpm_quota_full"
                  and fw[0] * 1000 <= e["at_ms"]), None)
    act = next((e for e in events if first and e["type"] == "action" and e["supi"] == s1 and e["max_prb_ratio"] == ratio
                and e["http"] == 200 and e["at_ms"] >= first["at_ms"]), None)
    dec = (act["at_ms"] - first["collect_ms"]) / 1000 if act else None
    checks["quota_after_decision"] = {"ok": dec is not None and dec <= DECISION_S, "s_after_decision_sample": dec,
                                      "s_after_flood_start": round(act["at_ms"] / 1000 - fw[0], 2) if act else None,
                                      "evidence": first and {k: first[k] for k in ("kind", "rate_ul_kbps", "cell_prb_ul_pct", "class")}}

    # quota intervals in the flood: action ratio -> next action 100 (or flood end)
    acts = [e for e in events if e["type"] == "action" and e["supi"] == s1 and e["http"] == 200
            and fw[0] * 1000 <= e["at_ms"] <= fw[1] * 1000]
    spans, start = [], None
    for e in acts:
        if e["max_prb_ratio"] == ratio and start is None: start = e["at_ms"]
        elif e["max_prb_ratio"] == 100 and start is not None: spans.append((start, e["at_ms"])); start = None
    if start is not None: spans.append((start, fw[1] * 1000))
    amf1 = result["ues"]["oai-nr-ue"]["amf"]
    held = [float(r[PRB] or 0) for r in rows if r.get("UE ID") == str(amf1) and r.get("Collect Time (UNIX us)")
            and any(a + 2000 <= int(r["Collect Time (UNIX us)"]) / 1000 <= b for a, b in spans)]
    mean = round(sum(held) / len(held), 2) if held else None
    checks["quota_holds"] = {"ok": mean is not None and mean <= ratio + HOLD_MARGIN, "ue1_prb_share_mean": mean,
                             "max": max(held) if held else None, "samples": len(held), "quota_spans": len(spans)}

    lift = next((e for e in acts if e["max_prb_ratio"] == 100), None)
    rep2 = next((e for e in events if e["type"] == "level" and e["supi"] == s1 and e["level"] == 2
                 and e["why"] == "repeat_offense" and lift and e["at_ms"] >= lift["at_ms"]), None)
    checks["repeat_offense_level_2"] = {"ok": bool(rep2), "s_lift_after_flood_start": round(lift["at_ms"] / 1000 - fw[0], 1) if lift else None,
                                        "s_level_2_after_lift": round((rep2["at_ms"] - lift["at_ms"]) / 1000, 1) if rep2 else None}

    b2, f2 = ph["benign"]["mbps"].get("oai-nr-ue2"), ph["flood"]["mbps"].get("oai-nr-ue2")
    ctl = result.get("control", {})
    cb2, cf2 = (ctl.get(p, {}).get("mbps", {}).get("oai-nr-ue2") for p in ("benign", "flood"))
    checks["ue2_unaffected"] = {"ok": bool(b2) and f2 is not None and f2 >= 0.9 * b2, "ue2_mbps_benign_flood": [b2, f2],
                                "ratio": round(f2 / b2, 3) if b2 and f2 else None,
                                "control_ue2_mbps_benign_flood": [cb2, cf2],
                                "control_ratio": round(cf2 / cb2, 3) if cb2 and cf2 else None,
                                "ue1_mbps_flood_defense_control": [ph["flood"]["mbps"].get("oai-nr-ue"),
                                                                   ctl.get("flood", {}).get("mbps", {}).get("oai-nr-ue")]}

    lv = [e["level"] for e in events if e["type"] == "level"]
    checks["level_at_most_2"] = {"ok": bool(lv) and max(lv) <= 2, "max_level": max(lv) if lv else None,
                                 "reached_2": any(e["type"] == "level" and e["supi"] == s1 and e["level"] == 2 for e in events)}

    if "reconnect" in result:
        rc = result["reconnect"]
        reap = next((e for e in events if e["type"] == "action" and e["supi"] == s1 and e["http"] == 200
                     and e["max_prb_ratio"] == ratio and e["amf_ue_ngap_id"] == rc["amf_new"]
                     and e["at_ms"] >= rc["xapp_restart_unix"] * 1000), None)
        checks["reconnect_reapplied"] = {"ok": bool(reap) and rc["amf_new"] != rc["amf_old"] and bool(rc["restored_log"]),
                                         "amf_old_new": [rc["amf_old"], rc["amf_new"]], "restored": rc["restored_log"],
                                         "s_after_xapp_restart": round(reap["at_ms"] / 1000 - rc["xapp_restart_unix"], 1) if reap else None}
    if "expiry" in result:
        ex = result["expiry"]
        zero = next((e for e in events if e["type"] == "level" and e["supi"] == s1 and e["level"] == 0
                     and e["at_ms"] >= ex["start_unix"] * 1000), None)
        rem = next((e for e in events if zero and e["type"] == "action" and e["supi"] == s1 and e["max_prb_ratio"] == 100
                    and e["http"] == 200 and e["at_ms"] >= zero["at_ms"]), None)
        checks["expiry_removes_quota"] = {"ok": bool(zero and rem and zero["why"] == "expired"),
                                          "s_to_level_0": round(zero["at_ms"] / 1000 - ex["start_unix"], 1) if zero else None,
                                          "quota_removed": bool(rem)}
    checks["db_records"] = {"ok": len(db.get("evidence", [])) >= 2 and len(db.get("actions", [])) >= 1,
                            "evidence_rows": len(db.get("evidence", [])), "action_rows": len(db.get("actions", []))}
    result["status"] = "PASS" if all(c["ok"] for c in checks.values()) else "FAIL"
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": checks}, indent=2))
    return 0 if result["status"] == "PASS" else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = pathlib.Path(args[0])
    if "--evaluate" in sys.argv:
        return evaluate(out)
    out.mkdir(parents=True, exist_ok=True)
    flood = int(args[1]) if len(args) > 1 else 90
    run = (ROOT / "artifacts/k8s/state/current-staged-run").read_text().strip()
    st = state()
    result = {"run": run, "started_unix": round(time.time(), 3), "flood_s": flood, "max_prb_ratio": st["max_prb_ratio"],
              "fair_use": st.get("fair_use"), "phases": {}}
    for dep in r2.UES:
        wait_ip(dep)
    table = r2.amf_table()
    result["ues"] = {d: {"ip": r2.UES[d]["ip"], "supi": SUPI[d], "amf": table.get(SUPI[d])} for d in r2.UES}
    if any(u["amf"] is None for u in result["ues"].values()):
        raise SystemExit("AMF table lacks a UE: %s" % result["ues"])
    for dep, cls in CLASS.items():
        code, body = http("POST", "/v1/defense/policy", {"supi": SUPI[dep], "class": cls})
        if code != 200:
            raise SystemExit("policy %s: %s %s" % (dep, code, body))
    result["classes"] = CLASS
    result["drain_s"] = {"start": wait_drain_all()}
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    if "--no-control" not in sys.argv:
        http("POST", "/v1/defense/enabled", {"enabled": False})
        reset_both()
        time.sleep(3)
        ctl = {"phases": {}}
        phase(ctl, "warmup", {"oai-nr-ue": "1M", "oai-nr-ue2": "1M"}, 15)
        phase(ctl, "benign", {"oai-nr-ue": "1M", "oai-nr-ue2": "3M"}, 20)
        phase(ctl, "flood", {"oai-nr-ue": "30M", "oai-nr-ue2": "3M"}, 30)
        result["control"] = ctl["phases"]
        result["drain_s"]["after_control_flood"] = wait_drain_all()

    http("POST", "/v1/defense/enabled", {"enabled": True})
    reset_both()
    time.sleep(5)
    result["uncongested_before_idle"] = state().get("uncongested_samples", 0)
    phase(result, "idle", {"oai-nr-ue": "4M"}, 20)
    phase(result, "warmup", {"oai-nr-ue": "1M", "oai-nr-ue2": "1M"}, 15)
    phase(result, "benign", {"oai-nr-ue": "1M", "oai-nr-ue2": "3M"}, 30)
    phase(result, "flood", {"oai-nr-ue": "30M", "oai-nr-ue2": "3M"}, flood)
    if "--no-reconnect" not in sys.argv:
        reconnect(result)
        phase(result, "after_reconnect", {"oai-nr-ue": "500K"}, 30)
    if "--no-expiry" not in sys.argv:
        result["expiry"] = {"start_unix": round(time.time(), 3)}
        for _ in range(100):  # level 2 (180 s) + level 1 (60 s) in the lab profile; UE1 idle
            u = next((x for x in state()["ues"] if x["supi"] == SUPI["oai-nr-ue"]), {})
            if u.get("level") == 0 and u.get("applied_ratio") == 0:
                break
            time.sleep(5)
        time.sleep(3)
    http("POST", "/v1/defense/policy", {"supi": SUPI["oai-nr-ue2"], "class": "default"})
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    fetch(run, out)
    return evaluate(out)


if __name__ == "__main__":
    sys.exit(main())
