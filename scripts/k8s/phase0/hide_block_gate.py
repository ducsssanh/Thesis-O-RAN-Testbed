#!/usr/bin/env python3
"""A gNB hiding an attacker must not keep it out of a UPF block (TRAFFIC-TWINNING-PLAN §0a, Methodology §7.4).

UE1 sends above its fair-use class while its KPM UL is scaled by HIDE at ingest, UE2 stays below its class. The ladder is
shortened through /v1/defense/timing (its logic is untouched) and RRC release is off, because the OAI UE does not come
back within a run. Pass: UE1 reaches level >= 3 with core evidence, the UPF applies a block, URR falls to about 0 while
the profiler (counted before the policy) still sees the UE sending, and UE2 stays at level 0. Timing and release are put
back at the end.

Usage: hide_block_gate.py <out.json> [seconds=150]"""
import json, subprocess, sys, time

K = ["kubectl", "--context", "oai-lab"]
RUN = "/artifacts/runs/20261003T164156Z-m35"
DN = "172.30.26.10"
U1, U2 = "imsi-001010123456780", "imsi-001010123456781"
HIDE = 0.1
SENDER = """
import socket,time,sys
kbps,size,T=float(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3])
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);d=(sys.argv[4],5001);p=b'x'*size
gap=size*8/(kbps*1000);t0=time.time();n=t0
while time.time()-t0<T:
    s.sendto(p,d);n+=gap;time.sleep(max(0,n-time.time()))
"""


def xapp(args):
    return subprocess.run(K + ["-n", "near-rt-ric", "exec", "deploy/oai-lab-xapp", "-c", "xapp", "--"] + args, capture_output=True, text=True, check=True).stdout


def api(path, body=None):
    code = ("import urllib.request,json,sys;b=sys.argv[2];r=urllib.request.Request('http://127.0.0.1:8090'+sys.argv[1],"
            "data=b.encode() if b else None,headers={'Content-Type':'application/json'},method='POST' if b else 'GET');"
            "print(urllib.request.urlopen(r,timeout=5).read().decode())")
    return xapp(["python3", "-c", code, path, json.dumps(body) if body else ""])


def send(ue, kbps, seconds):
    return subprocess.Popen(K + ["-n", "oai-ran", "exec", f"deploy/{ue}", "-c", "nr-ue", "--", "python3", "-c", SENDER, str(kbps), "1000", str(seconds), DN],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


out = sys.argv[1]
seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 150
for s in (U1, U2):
    api("/v1/defense/reset", {"supi": s})
api("/v1/defense/timing", {"expiryS": [15, 15, 60, 0], "releaseOnBlock": False})
api("/v1/defense/enabled", {"enabled": True})
t0 = time.time()
procs = [send("oai-nr-ue", 3000, seconds), send("oai-nr-ue2", 500, seconds)]
time.sleep(5)
api("/v1/defense/tamper", {"supi": U1, "factor": HIDE})
trace, first = [], {}
while time.time() - t0 < seconds:
    st = {u["supi"]: u for u in json.loads(api("/v1/defense/state"))["ues"]}
    lvl, core, lvl2 = st[U1].get("level"), st[U1].get("core_applied"), st[U2].get("level")
    t = round(time.time() - t0)
    trace.append({"t": t, "ue1_level": lvl, "ue1_core": core, "ue2_level": lvl2})
    first.setdefault(f"level{lvl}", t)
    print(trace[-1], flush=True)
    time.sleep(5)
for p in procs:
    p.wait()
raw = xapp(["tail", "-n", str((seconds + 30) * 2), f"{RUN}/KPI_Metrics_Features.jsonl"])
rows = []
for line in raw.splitlines():
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    if r["supi"] == U1 and r["collect_ms"] >= t0 * 1000:
        rows.append(r)
blocked = [r for r in rows if r.get("core_action") == "block"][3:]
mean = lambda k: round(sum(r.get(k, 0) for r in blocked) / len(blocked), 1) if blocked else None
raw_ev = xapp(["tail", "-n", "300", f"{RUN}/KPI_Metrics_Defense.jsonl"])
ev = []
for line in raw_ev.splitlines():
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        continue
    if e.get("type") in ("evidence", "level", "verdict", "verified") and e.get("supi") == U1:
        ev.append({k: e.get(k) for k in ("type", "at", "kind", "layer", "level", "why", "what", "ok") if k in e})
api("/v1/defense/tamper", {"off": True})
api("/v1/defense/enabled", {"enabled": False})
for s in (U1, U2):
    api("/v1/defense/reset", {"supi": s})
api("/v1/defense/timing", {"expiryS": [60, 180, 600, 0], "releaseOnBlock": True})
res = {"first_seen_s": first, "blocked_seconds": len(blocked), "while_blocked": {"kpm_rate_ul_kbps": mean("rate_ul_kbps"), "prof_ul_kbps": mean("prof_ul_kbps"),
       "urr_ul_kbps": mean("urr_ul_kbps")}, "ue2_max_level": max(x["ue2_level"] for x in trace), "events": ev[-14:], "trace": trace}
ok = bool(blocked) and res["ue2_max_level"] == 0 and res["while_blocked"]["urr_ul_kbps"] < 50 and res["while_blocked"]["prof_ul_kbps"] > 1000
res["pass"] = ok
json.dump(res, open(out, "w"), indent=1)
print({k: res[k] for k in ("first_seen_s", "blocked_seconds", "while_blocked", "ue2_max_level", "pass")})
for e in res["events"]:
    print(e)
sys.exit(0 if ok else 1)
