#!/usr/bin/env python3
"""KPM trust gate check on the live testbed: c_t of honest traffic, then each tamper level (TRAFFIC-TWINNING-PLAN §0a).

Defense actions are off for the whole check; the gate runs on the features anyway. Traffic: UE1 steady UDP with large
packets, UE2 UDP bursts (3 s on, 2 s off) with small packets, so that per-packet overhead matters. Phases: honest, then
hiding on UE1 and framing on UE2 through the xApp's tamper API (KPM scaled at ingest, ground truth logged by the xApp).
Prints, per phase and UE, the KPM window phase, the c_t quantiles of seconds with traffic, the share outside the band and
the node trust. Pass: honest c_t inside the band for >= 98 % of seconds, and every large tamper level outside it in
>= 90 % of the tampered UE's seconds with traffic. Near-threshold levels are reported only.

Usage: ct_gate.py <out.json> [honest_s=120] [tamper_s=30]"""
import json, subprocess, sys, time
import numpy as np

K = ["kubectl", "--context", "oai-lab"]
RUN = "/artifacts/runs/20261003T164156Z-m35"
DN = "172.30.26.10"
UES = {"oai-nr-ue": "imsi-001010123456780", "oai-nr-ue2": "imsi-001010123456781"}
LO, HI, EPS = -0.2, 0.2, 1000
LARGE = {0.33, 0.1, 2, 5}

SENDER = """
import socket,time,sys
kbps,size,on,off,T=float(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4]),float(sys.argv[5])
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);d=(sys.argv[6],5001);p=b'x'*size
gap=size*8/(kbps*1000);t0=time.time();n=time.time()
while time.time()-t0<T:
    if off==0 or (time.time()-t0)%(on+off)<on:
        s.sendto(p,d);n+=gap;time.sleep(max(0,n-time.time()))
    else:
        time.sleep(0.05);n=time.time()
"""


def xapp_api(path, body=None):
    code = ("import urllib.request,json,sys;b=sys.argv[2];r=urllib.request.Request('http://127.0.0.1:8090'+sys.argv[1],"
            "data=b.encode() if b else None,headers={'Content-Type':'application/json'},method='POST' if b else 'GET');"
            "print(urllib.request.urlopen(r,timeout=5).read().decode())")
    return subprocess.run(K + ["-n", "near-rt-ric", "exec", "deploy/oai-lab-xapp", "-c", "xapp", "--", "python3", "-c", code, path,
                               json.dumps(body) if body else ""], capture_output=True, text=True, check=True).stdout


def sender(ue, kbps, size, on, off, seconds):
    return subprocess.Popen(K + ["-n", "oai-ran", "exec", f"deploy/{ue}", "-c", "nr-ue", "--", "python3", "-c", SENDER, str(kbps), str(size),
                                 str(on), str(off), str(seconds), DN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


out = sys.argv[1]
honest_s = int(sys.argv[2]) if len(sys.argv) > 2 else 120
tamper_s = int(sys.argv[3]) if len(sys.argv) > 3 else 30
ue1, ue2 = UES["oai-nr-ue"], UES["oai-nr-ue2"]
steps = [("hide", ue1, 0.33), ("hide", ue1, 0.1), ("hide", ue1, 0.8), ("frame", ue2, 2), ("frame", ue2, 5), ("frame", ue2, 1.25)]
total = honest_s + len(steps) * (tamper_s + 10) + 20
xapp_api("/v1/defense/enabled", {"enabled": False})
xapp_api("/v1/defense/tamper", {"off": True})
procs = [sender("oai-nr-ue", 400, 1000, 1, 0, total), sender("oai-nr-ue2", 150, 120, 3, 2, total)]
time.sleep(10)
marks = [("honest", None, None, time.time())]
time.sleep(honest_s)
marks[-1] += (time.time(),)
for name, supi, factor in steps:
    xapp_api("/v1/defense/tamper", {"supi": supi, "factor": factor})
    time.sleep(2)
    t0 = time.time()
    time.sleep(tamper_s - 2)
    xapp_api("/v1/defense/tamper", {"supi": supi, "off": True})
    marks.append((f"{name} x{factor}", supi, factor, t0, time.time()))
    time.sleep(10)
for p in procs:
    p.wait()
n_lines = (total + 60) * 2
raw = subprocess.run(K + ["-n", "near-rt-ric", "exec", "deploy/oai-lab-xapp", "-c", "xapp", "--", "tail", "-n", str(n_lines),
                          f"{RUN}/KPI_Metrics_Features.jsonl"], capture_output=True, text=True, check=True).stdout
rows = []
for line in raw.splitlines():
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        pass

report, ok = [], True
for name, supi, factor, t0, t1 in marks:
    for s in ([ue1, ue2] if supi is None else [supi]):
        v = [r for r in rows if r["supi"] == s and t0 * 1000 <= r["collect_ms"] <= t1 * 1000 and "c_t" in r]
        act = [r for r in v if r["rate_ul_kbps"] * 125 >= EPS or r.get("prof_ul_kbps", 0) * 125 >= EPS]
        ct = np.array([r["c_t"] for r in act]) if act else np.array([0.0])
        out_share = float(np.mean((ct < LO) | (ct > HI)))
        phase = float(np.median([r["collect_ms"] % 1000 for r in v])) if v else float("nan")
        row = {"phase": name, "supi": s[-3:], "seconds": len(v), "with_traffic": len(act), "kpm_phase_ms": phase,
               "ct_q01": round(float(np.quantile(ct, .01)), 2), "ct_q50": round(float(np.quantile(ct, .5)), 2),
               "ct_q99": round(float(np.quantile(ct, .99)), 2), "out_of_band": round(out_share, 3),
               "min_trust": round(min((r["kpm_trust"] for r in v), default=1.0), 2), "masked": any(r["kpm_masked"] for r in v),
               "prof_age_p99_s": round(float(np.quantile([r.get("prof_age_s", 0) for r in v], .99)), 3) if v else None}
        report.append(row)
        print(row)
        if supi is None and out_share > 0.02:
            ok = False
        if factor in LARGE and out_share < 0.9:
            ok = False
json.dump({"pass": ok, "rows": report}, open(out, "w"), indent=1)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
