#!/usr/bin/env python3
"""Gate L1 (plan Phase L1): closed loop of both layers with classifier v1.

Usage: l1_gate.py <out-dir> [flood-s=150]

Prerequisite: both UEs attached with SUPI labels, xApp with the L1 defense
(core.enabled, rollout_xapp_defense.py), UPF with C35 (upfSecurity.enabled).
The gate shortens the ladder through POST /v1/defense/timing (expiry
20/30/240/240 s, probation 120 s) and restores the configured timing at the
end; both UEs use the default class (UL 2 Mbit/s).
  flood     UE1 10M UL for flood-s while UE2 sends 1M (benign). A flood that
            goes on climbs the ladder by itself: level 1 (quarantine slice +
            UPF monitor) -> expiry lifts the limits -> the flood (and the OAI
            UE's backlog) is a repeat offense: level 2 (slice + UPF
            ratelimit) -> 2 -> 1 -> 0 -> repeat with KPM and URR agreeing:
            level 3 (UPF block + RRC release)
  reconnect UE1 pod restarted under level 3 (new session; empties its RLC
            buffer) and the xApp restarted (KPM subscription, DB restore):
            not one packet of the new session reaches the DN
  expiry    no traffic: levels run out to 0, the UPF policy and the RAN
            limit are removed, UE1's traffic flows again
Checks:
  1. level 1: RAN slice handover and UPF monitor acknowledged
  2. the RAN limit is confirmed by URR (verified ran/urr_below_class)
  3. level 2 by repeat offense, UPF ratelimit acknowledged
  4. level 3 only with both layers (evidence with KPM and URR window hits
     within fusionS), UPF block + RRC release acknowledged, block enforced
  5. block confirmed by URR (verified core/urr_zero)
  6. reconnect: the new session is blocked from its first packet, level
     restored after the xApp restart
  7. expiry: level 0, no UPF policy, RAN limit removed, traffic flows
  8. benign UE2 never above level 1, never a UPF policy
"""
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import r2_gate as r2  # noqa: E402
import r3_gate as r3  # noqa: E402
import u_gate as ug  # noqa: E402
import staged  # noqa: E402

UE1, UE2 = "oai-nr-ue", "oai-nr-ue2"
SUPI = {UE1: "imsi-001010123456780", UE2: "imsi-001010123456781"}
TIMING = {"expiryS": [20, 30, 240, 240], "probationS": 120, "fusionS": 10}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ue_state(st, supi):
    return next((u for u in st.get("ues", []) if u["supi"] == supi), {})


def upf_policy(supi):
    s, body, _ = ug.api("GET", "/v1/ues/" + supi)
    return body if s == 200 else None


class Recorder(threading.Thread):
    """Polls the defense state and the UPF every ~2 s into a timeline."""

    def __init__(self):
        super().__init__(daemon=True)
        self.rows, self.stop = [], False

    def run(self):
        while not self.stop:
            try:
                st = r3.state()
                row = {"t": round(time.time(), 1)}
                for d, s in SUPI.items():
                    u = ue_state(st, s)
                    row[d] = {k: u.get(k) for k in ("level", "peak", "pending", "core_want", "core_applied", "applied_ratio",
                                                    "rate_ul_kbps", "ran_hit_age_s", "core_hit_age_s")}
                self.rows.append(row)
                if len(self.rows) % 5 == 1:
                    log("timeline", json.dumps({d: (row[d]["level"], row[d]["core_applied"], row[d]["applied_ratio"]) for d in SUPI}))
            except Exception as e:  # keep recording through restarts
                self.rows.append({"t": round(time.time(), 1), "error": str(e)[:120]})
            time.sleep(2)


def wait_level(supi, pred, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            u = ue_state(r3.state(), supi)
            if pred(u):
                return u, round(time.time() - t0, 1)
        except Exception:
            pass
        time.sleep(2)
    return None, timeout


def events(run):
    raw = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", "/artifacts/runs/" + run + "/KPI_Metrics_Defense.jsonl", check=False)
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def check(result, name, ok, **detail):
    result["checks"][name] = {"ok": bool(ok), **detail}
    log(("PASS " if ok else "FAIL ") + name, json.dumps(detail)[:400])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    out = pathlib.Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    flood_s = int(args[1]) if len(args) > 1 else 150
    run = staged.run_id()
    result = {"started_unix": time.time(), "run": run, "timing": TIMING, "checks": {}}
    st0 = r3.state()
    if not st0.get("core", {}).get("enabled"):
        print("xApp core layer is off (defense.xapp.core.enabled)")
        return 2
    saved = {"expiryS": st0["timing"]["expiry_s"], "probationS": st0["timing"]["probation_s"], "fusionS": st0["timing"]["fusion_s"]}
    result["saved_timing"] = saved
    ips = {d: ug.ue_ip(d, wait=60) for d in SUPI}
    for d in SUPI:
        r2.UES[d]["ip"] = ips[d]
    log("UE IPs", ips, "run", run)
    r3.http("POST", "/v1/defense/enabled", {"enabled": True})
    r3.http("POST", "/v1/defense/mode", {"mode": "slice"})
    for d, s in SUPI.items():
        r3.http("POST", "/v1/defense/policy", {"supi": s, "class": "default"})
    r3.reset_both()
    r3.http("POST", "/v1/defense/timing", TIMING)
    log("drain", r3.wait_drain_all())
    t_start = time.time()
    rec = Recorder()
    rec.start()
    try:
        # ---- flood: the ladder 1 -> 2 -> 3 ----
        log("flood", flood_s, "s: UE1 10M + UE2 1M")
        holder = {}
        def flood():
            try:
                holder["flows"] = r3.load({UE1: "10M", UE2: "1M"}, flood_s)
            except Exception as e:  # servers cut short below
                holder["flows"] = ({}, str(e)[:120])
        th = threading.Thread(target=flood)
        th.start()
        u3, t3 = wait_level(SUPI[UE1], lambda u: u.get("level", 0) >= 3, flood_s + 30, "level 3")
        log("level 3 after", t3, "s" if u3 else "s: NOT reached")
        time.sleep(12)  # block verification by URR
        pol3 = upf_policy(SUPI[UE1])
        # the flood has done its job: stop it so level 3 is still in force at the reconnect
        for d in (UE1, UE2):
            r2.ex("oai-ran", d, "nr-ue", "pkill", "iperf", check=False)
        r2.ex("oai-core", "oai-lab-dn", "dn", "pkill", "-INT", "iperf", check=False)
        th.join()
        result["flood_mbps"] = holder.get("flows", [{}])[0]
        result["level3"] = {"reached_s": t3 if u3 else None, "upf_policy": pol3}

        # ---- reconnect under level 3 ----
        cap = ug.Capture(170)
        ug.restart_ue1(result)
        ips[UE1] = ug.ue_ip(UE1, wait=120)
        r2.UES[UE1]["ip"] = ips[UE1]
        time.sleep(25)  # AMF UE table -> SUPI of the new UE ID
        xlog = r3.restart_xapp()
        r3.http("POST", "/v1/defense/timing", TIMING)  # runtime timing is not persisted
        mb = ug.iperf_ul(UE1, ips[UE1], "1M", 10) if ips[UE1] else None
        pk = cap.packets()
        from_new = [t for t, a in pk if a == ips[UE1]]
        st = ug.api("GET", "/v1/stats?supi=" + SUPI[UE1])[1]["stats"]
        live = [s["seid"] for s in ug.api("GET", "/v1/sessions")[1]["sessions"] if s["supi"] == SUPI[UE1]]
        cur = [x["stats"] for x in (st[0]["sessions"] if st else []) if x["seid"] in live]
        result["reconnect"] = {"ue1_ip": ips[UE1], "dn_pkts_from_ue1": len(from_new), "iperf_mbps": mb,
                               "new_session_stats": cur[0] if cur else None,
                               "restored": [l for l in xlog.splitlines() if "[defense] restored" in l],
                               "level_after": ue_state(r3.state(), SUPI[UE1]).get("level")}
        log("reconnect", json.dumps(result["reconnect"])[:300])

        # ---- expiry back to 0 ----
        u0, t0 = wait_level(SUPI[UE1], lambda u: u.get("level", 9) == 0 and u.get("applied_ratio", 1) == 0
                            and u.get("core_applied") == "none", 400, "level 0")
        time.sleep(3)
        pol0 = upf_policy(SUPI[UE1])
        # a block longer than T2 (UPIR after upInactivityS without forwarded
        # packets + deactivatedReleaseS) lets the SMF release the session; the
        # OAI UE is not told (design 8), so it attaches again first
        live = [x for x in ug.api("GET", "/v1/sessions")[1]["sessions"] if x["supi"] == SUPI[UE1]]
        reattached = not live
        if reattached:
            ug.restart_ue1(result)
            ips[UE1] = ug.ue_ip(UE1, wait=120)
            live = [x for x in ug.api("GET", "/v1/sessions")[1]["sessions"] if x["supi"] == SUPI[UE1]]
        mb0 = ug.iperf_ul(UE1, ips[UE1], "1M", 10) if ips[UE1] else None
        result["expiry"] = {"reached_s": t0 if u0 else None, "upf_policy": pol0, "ue1_mbps": mb0,
                            "session_released_by_t2": reattached, "sessions": live}
    finally:
        rec.stop = True
        rec.join(timeout=10)
        r3.http("POST", "/v1/defense/timing", saved)
        result["timeline"] = rec.rows

    # ---- evaluate from the defense event log ----
    ev = [e for e in events(run) if e.get("at_ms", 0) / 1000 >= t_start - 1]
    (out / "defense.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))
    e1 = [e for e in ev if e.get("supi") == SUPI[UE1]]
    lv = [e for e in e1 if e["type"] == "level"]
    acts = [e for e in e1 if e["type"] == "action"]
    ver = [e for e in e1 if e["type"] in ("verified", "unverified")]

    def first_level(n):
        return next((e for e in lv if e["level"] == n and e.get("from", 0) < n), None)

    def act_after(e, layer, action):
        return next((a for a in acts if e and a["at_ms"] >= e["at_ms"] and a.get("layer") == layer and a.get("action") == action), None)

    l1, l2, l3 = first_level(1), first_level(2), first_level(3)
    a1r, a1c = act_after(l1, "ran", "slice_handover"), act_after(l1, "core", "monitor")
    check(result, "l1_ran_slice_and_upf_monitor", l1 and a1r and a1r["http"] == 200 and a1c and a1c["http"] == 200,
          level_event=l1, ran=a1r and a1r.get("http"), core=a1c and a1c.get("http"))
    v_ran = [v for v in ver if v.get("layer") == "ran" and v.get("check") == "urr_below_class"]
    check(result, "ran_limit_confirmed_by_urr", any(v["type"] == "verified" for v in v_ran),
          verdicts=[(v["type"], v.get("urr_ul_kbps")) for v in v_ran])
    a2c = act_after(l2, "core", "ratelimit")
    check(result, "l2_repeat_offense_upf_ratelimit", l2 and l2.get("why") == "repeat_offense" and a2c and a2c["http"] == 200,
          level_event=l2, core=a2c and {k: a2c.get(k) for k in ("http", "rate_ul_kbps", "ttl_s")})
    ev3 = next((e for e in reversed(e1) if l3 and e["type"] == "evidence" and e["at_ms"] <= l3["at_ms"]), None)
    fus = TIMING["fusionS"]
    both = ev3 and 0 <= ev3.get("ran_hit_age_s", -1) <= fus and 0 <= ev3.get("core_hit_age_s", -1) <= fus
    a3c, a3r = act_after(l3, "core", "block"), act_after(l3, "ran", "release")
    check(result, "l3_both_layers_block_and_release",
          l3 and both and a3c and a3c["http"] == 200 and a3r and a3r["http"] == 200 and pol3 and pol3.get("action") == "block",
          level_event=l3, evidence={k: ev3.get(k) for k in ("kind", "layer", "ran_hit_age_s", "core_hit_age_s", "urr_ul_kbps")} if ev3 else None,
          core=a3c and a3c.get("http"), release=a3r and a3r.get("http"), upf=pol3 and {k: pol3.get(k) for k in ("action", "enforced", "level")})
    v_core = [v for v in ver if v.get("layer") == "core" and v.get("check") == "urr_zero"]
    check(result, "block_confirmed_by_urr", any(v["type"] == "verified" for v in v_core),
          verdicts=[(v["type"], v.get("urr_ul_kbps"), v.get("urr_age_s")) for v in v_core])
    rc = result.get("reconnect", {})
    check(result, "reconnect_blocked_level_restored", rc.get("ue1_ip") and rc.get("dn_pkts_from_ue1") == 0 and not rc.get("iperf_mbps")
          and (rc.get("new_session_stats") or {}).get("drop_ul_pkts", 0) > 100 and rc.get("restored"), **rc)
    ex = result.get("expiry", {})
    check(result, "expiry_clears_both_layers", ex.get("reached_s") is not None and ex.get("upf_policy") is None
          and (ex.get("ue1_mbps") or 0) >= 0.85 and not any(x["policy_in_map"] for x in ex.get("sessions", [])), **ex)
    ue2_levels = [r[UE2]["level"] for r in result["timeline"] if UE2 in r and r[UE2]["level"] is not None]
    ue2_core = [r[UE2]["core_applied"] for r in result["timeline"] if UE2 in r]
    check(result, "benign_ue2_not_above_1", ue2_levels and max(ue2_levels) <= 1 and not any(c in ("ratelimit", "block") for c in ue2_core),
          max_level=max(ue2_levels) if ue2_levels else None, core=sorted(set(c for c in ue2_core if c)))
    result["status"] = "PASS" if all(c["ok"] for c in result["checks"].values()) else "FAIL"
    (out / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    log("Gate L1", result["status"], "->", out / "result.json")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
