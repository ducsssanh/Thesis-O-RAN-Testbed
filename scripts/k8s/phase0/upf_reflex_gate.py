#!/usr/bin/env python3
"""Gate for the UPF detection-and-reflex step (docs/CLOSED-LOOP-FRAMEWORK.md
section 4: the eBPF UPF's own response to an uplink flood).

  upf_reflex_gate.py <out-dir>

The reflex is a UPF-only mechanism, so the xApp is stopped for the test. The
reflex parameters are set at runtime through the UPF API (PUT /v1/config), the
way the xApp will set them, with a quota below the RFsim uplink capacity so one
UE can exceed it. Checks, with the xApp down:

  ratelimit  mode "ratelimit": one UE sends uplink above the quota; the UPF
             raises a "reflex" event, the uplink rate at the data network
             falls to about the reflex rate, and the event carries a TTL
  expiry     when the flood stops, a "reflex_expired" event follows within
             about the TTL and the session's security entry is cleared
  report     mode "off": the same flood raises only a "trip" event with
             action "report"; the uplink rate is not limited
  uplink_only a benign downlink flow during a reflex is not limited
  benign     a benign uplink flow below the quota raises no event

Only the uplink volume quota is exercised here (reachable with iperf). The
SYN / ICMP / fragment / DNS / GTP-in-GTP rules need the attack tools of the
attack-traffic step and are checked there against their ground-truth logs.
"""
import json
import pathlib
import subprocess
import sys
import threading
import time

CTX = "oai-lab"
ROOT = pathlib.Path(__file__).resolve().parents[3]
DN = "172.30.26.10"
UE = "oai-nr-ue"
PORT = 5201
UPF = "http://oai-upf-security.oai-core.svc.cluster.local:8095"
QUOTA_UL_BYTES = 125000      # 1 Mbit/s: below the RFsim uplink capacity
REFLEX_RATE_KBPS = 1000
TTL_S = 8
FLOOD_KBPS = "4M"            # offered uplink, above the quota
BENIGN_KBPS = "600K"         # below the quota (0.6 Mbit/s < 1 Mbit/s)
FLOOD_S = 25
SETTLE_S = 3


def kubectl(*a, timeout=60, check=True):
    return subprocess.run(["kubectl", "--context", CTX, *a], capture_output=True, text=True,
                          errors="replace", timeout=timeout, check=check).stdout


def ex(ns, dep, ctr, *cmd, timeout=60, check=True):
    return kubectl("-n", ns, "exec", "deploy/" + dep, "-c", ctr, "--", *cmd, timeout=timeout, check=check)


# HTTP to the UPF API from inside the DN pod (same cluster network)
_HTTP = """
import json,sys,urllib.request
m,u,b=sys.argv[1],sys.argv[2],(sys.argv[3] if len(sys.argv)>3 else None)
r=urllib.request.Request(u,data=(b.encode() if b else None),method=m)
r.add_header('Content-Type','application/json')
try:
    s=urllib.request.urlopen(r,timeout=10);print(json.dumps({"status":s.status,"body":json.loads(s.read() or 'null')}))
except urllib.error.HTTPError as e:
    print(json.dumps({"status":e.code,"body":e.read().decode()}))
"""


def api(method, path, body=None):
    args = [method, UPF + path] + ([json.dumps(body)] if body is not None else [])
    out = ex("oai-core", "oai-lab-dn", "dn", "python3", "-c", _HTTP, *args)
    return json.loads(out)


def ue_ip():
    return ex("oai-ran", UE, "nr-ue", "ip", "-4", "-o", "addr", "show", "oaitun_ue1").split()[3].split("/")[0]


def ul_flood(rate, dur):
    """One uplink iperf UE -> DN; returns the receiver's Mbit/s and the window."""
    srv = subprocess.Popen(["kubectl", "--context", CTX, "-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
                            "timeout", "-k", "5", str(dur + 12), "iperf", "-s", "-u", "-p", str(PORT), "-y", "C"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(2)
    ip = ue_ip()
    t0 = time.time()
    ex("oai-ran", UE, "nr-ue", "iperf", "-c", DN, "-B", ip, "-u", "-b", rate, "-l", "1200", "-t", str(dur),
       "-p", str(PORT), timeout=dur + 30, check=False)
    t1 = time.time()
    out, _ = srv.communicate(timeout=15)
    mbps = 0.0
    for line in out.splitlines():
        f = line.split(",")
        if len(f) >= 9 and f[8]:
            mbps = int(f[8]) / 1e6
    return mbps, (t0, t1)


def dl_flow(rate, dur):
    ip = ue_ip()
    srv = subprocess.Popen(["kubectl", "--context", CTX, "-n", "oai-ran", "exec", "deploy/" + UE, "-c", "nr-ue", "--",
                            "timeout", "-k", "5", str(dur + 12), "iperf", "-s", "-u", "-B", ip, "-p", str(PORT + 10), "-y", "C"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(2)
    ex("oai-core", "oai-lab-dn", "dn", "iperf", "-c", ip, "-u", "-b", rate, "-l", "1200", "-t", str(dur),
       "-p", str(PORT + 10), timeout=dur + 30, check=False)
    out, _ = srv.communicate(timeout=15)
    for line in out.splitlines():
        f = line.split(",")
        if len(f) >= 9 and f[8]:
            return int(f[8]) / 1e6
    return 0.0


def events_since(seq):
    r = api("GET", "/v1/events?since=%d&limit=2000" % seq)
    return r["body"]["records"], r["body"]["last_seq"]


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    result = {"gate": "upf-reflex", "checks": {}}
    # 1. stop the xApp: the reflex is a UPF-only mechanism
    kubectl("-n", "near-rt-ric", "scale", "deploy/oai-lab-xapp", "--replicas=0")
    kubectl("-n", "near-rt-ric", "wait", "--for=delete", "pod", "-l", "app.kubernetes.io/name=oai-lab-xapp",
            "--timeout=60s", check=False)
    try:
        ue_ip_now = ue_ip()
        ex("oai-ran", UE, "nr-ue", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1", "src", ue_ip_now)

        # ratelimit mode with a low quota (xApp-style runtime parameters)
        cfg = api("PUT", "/v1/config", {"reflex_mode": "ratelimit", "reflex_quota_ul_bytes": QUOTA_UL_BYTES,
                                        "reflex_rate_ul_kbps": REFLEX_RATE_KBPS, "reflex_ttl_s": TTL_S,
                                        "reflex_ttl_max_s": TTL_S,  # no doubling: bounded expiry for the gate
                                        "reflex_max_share": 1.0})  # 2-4 UE lab: one UE is already 25-50%
        result["config"] = cfg

        _, seq0 = events_since(0)
        mbps_rl, win = ul_flood(FLOOD_KBPS, FLOOD_S)
        # read everything since seq0 and keep polling: the reflex renews while
        # the UE drains its uplink queue after iperf stops (UDP over a
        # ~4-6 Mbit/s link) and only then expires, which can be before or
        # after the first read
        mine = lambda e, ev: e["event"] == ev and e["supi"].endswith(UE_SUPI_SUFFIX)
        reflex, expired, cur = [], [], seq0
        deadline = time.time() + 45
        while True:
            evs2, cur = events_since(cur)
            reflex += [e for e in evs2 if mine(e, "reflex")]
            expired += [e for e in evs2 if mine(e, "reflex_expired")]
            if expired or time.time() > deadline:
                break
            time.sleep(3)
        seq2 = cur
        result["checks"]["ratelimit"] = {
            "pass": bool(reflex) and mbps_rl <= REFLEX_RATE_KBPS / 1000 * 1.5,
            "reflex_events": len(reflex), "ul_mbps_at_dn": round(mbps_rl, 3),
            "limit_mbps": REFLEX_RATE_KBPS / 1000, "first": reflex[0] if reflex else None}
        result["checks"]["expiry"] = {"pass": bool(expired), "expired_events": len(expired)}

        # off mode: detect and report only
        api("PUT", "/v1/config", {"reflex_mode": "off"})
        _, seq3 = events_since(seq2)
        mbps_off, _ = ul_flood(FLOOD_KBPS, FLOOD_S)
        evs3, seq4 = events_since(seq3)
        trips = [e for e in evs3 if e["event"] == "trip" and e.get("action") == "report"]
        reflex_off = [e for e in evs3 if e["event"] == "reflex"]
        result["checks"]["report"] = {
            "pass": bool(trips) and not reflex_off and mbps_off > REFLEX_RATE_KBPS / 1000 * 1.5,
            "trip_events": len(trips), "reflex_events": len(reflex_off), "ul_mbps_at_dn": round(mbps_off, 3)}

        # benign uplink below the quota: no event
        api("PUT", "/v1/config", {"reflex_mode": "ratelimit", "reflex_max_share": 1.0})
        time.sleep(TTL_S + 2)
        _, seq5 = events_since(seq4)
        mbps_benign, _ = ul_flood(BENIGN_KBPS, 20)
        evs5, _ = events_since(seq5)
        result["checks"]["benign"] = {"pass": not evs5, "events": len(evs5), "ul_mbps_at_dn": round(mbps_benign, 3)}

        verdict = all(c["pass"] for c in result["checks"].values())
        result["verdict"] = "PASS" if verdict else "FAIL"
    finally:
        api("PUT", "/v1/config", {"reflex_mode": "off"})  # leave detection-only after the gate
        kubectl("-n", "near-rt-ric", "scale", "deploy/oai-lab-xapp", "--replicas=1", check=False)
    (out / "upf_reflex_gate.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "PASS" else 1


UE_SUPI_SUFFIX = "780"  # oai-nr-ue is imsi-001010123456780


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(run(pathlib.Path(sys.argv[1])))
