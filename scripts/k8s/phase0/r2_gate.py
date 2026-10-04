#!/usr/bin/env python3
"""Gate R2 (plan): RAN actions in the gNB through E2SM-RC CONTROL from the xApp.

Usage: r2_gate.py <out-dir> [ratio-percent=10] [phase-s=20] [--no-release]
       r2_gate.py --evaluate <out-dir>   (re-check a stored run, no traffic)

Prerequisite: both UEs attached (oai-nr-ue, oai-nr-ue2), gNB with the RC
enforcement patch (C29), xApp with the RAN control endpoint (127.0.0.1:8090
in its pod), KPM flowing with SUPI labels (R1).
For UL and then DL, three phases of <phase-s> each, both UEs sending at once
(UE1 well above the cell capacity, UE2 at a moderate fixed rate):
  base     no quota
  quota    UE1 Max PRB Policy Ratio = <ratio> (style 2, Slice-level PRB quota)
  restore  UE1 quota removed (ratio 100)
Then UE2 is released (style 4, RRC Connection Release) while UE1 keeps a
moderate flow.
Checks (per direction):
  1. quota binds: UE1's KPM PRB share (RRU.PrbTot*, % of the cell PRBs) is
     <= ratio + 3 in the quota phase and was > ratio + 10 in the base phase.
  2. throughput drops by the right amount: UE1 quota/base KPM throughput
     (DRB.UEThp*, same rows and window as the PRB share) within 50 % of its
     PRB-share ratio, and below 0.6. The iperf ratio is recorded too; it
     also counts ramp-up and queue drain outside the KPM window.
  3. UE2 unaffected: its throughput in the quota phase >= 90 % of base.
  4. restore: UE1 throughput back to >= 80 % of base.
Release:
  5. the gNB logs the release request for UE2's RNTI, UE2 receives RRCRelease,
     the gNB stops reporting UE2 in KPM, and UE1's flow loses < 2 %.
"""
import csv
import io
import json
import pathlib
import re
import subprocess
import sys
import threading
import time

CTX = "oai-lab"
ROOT = pathlib.Path(__file__).resolve().parents[3]
DN = "172.30.26.10"
UES = {"oai-nr-ue": {"port": 5201}, "oai-nr-ue2": {"port": 5202}}
# offered load: UE1 above the cell capacity, UE2 moderate
RATES = {"ul": {"oai-nr-ue": "30M", "oai-nr-ue2": "3M"}, "dl": {"oai-nr-ue": "80M", "oai-nr-ue2": "5M"}}
PRB_COL = {"ul": "RRU.PrbTotUl (%)", "dl": "RRU.PrbTotDl (%)"}
THP_COL = {"ul": "DRB.UEThpUl (kbps)", "dl": "DRB.UEThpDl (kbps)"}
# Throughput/PRB-share ratio drift accepted. Set after four runs (04/10) whose
# quota/base throughput was 0.91-1.43x the PRB-share ratio: per-PRB
# efficiency changes with the allocation size and 20 s windows are noisy.
LEVEL_TOLERANCE = 0.5


def kubectl(*args, timeout=60, check=True):
    return subprocess.run(["kubectl", "--context", CTX, *args], check=check, capture_output=True, errors="replace",
                          text=True, timeout=timeout).stdout


def ex(ns, dep, ctr, *cmd, timeout=60, check=True):
    return kubectl("-n", ns, "exec", "deploy/" + dep, "-c", ctr, "--", *cmd, timeout=timeout, check=check)


def amf_table():
    """Last complete OAI AMF "UEs' Information" table: SUPI -> AMF UE NGAP ID."""
    rows, cur, inside = None, None, False
    for line in kubectl("-n", "oai-core", "logs", "deploy/oai-amf", "-c", "amf", "--since=90s").splitlines():
        if "UEs' Information" in line:
            cur, inside = {}, True
            continue
        if not inside:
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 10:
            if "-----" in line:
                rows, inside = cur, False
            continue
        if cols[1] in ("Index", "-") or cols[2] != "5GMM-REGISTERED":
            continue
        cur["imsi-" + cols[3]] = int(cols[6], 16)
    return rows or {}


def ran_control(body):
    """POST to the xApp RAN control endpoint (loopback in the xApp pod)."""
    code = ("import json,sys,urllib.request,urllib.error\n"
            "r=urllib.request.Request('http://127.0.0.1:8090/v1/ran/control',data=sys.argv[1].encode(),method='POST')\n"
            "try:\n s=urllib.request.urlopen(r,timeout=20);print(s.status,s.read().decode())\n"
            "except urllib.error.HTTPError as e:print(e.code,e.read().decode())\n")
    out = ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", code, json.dumps(body), timeout=40).strip()
    status, _, text = out.partition(" ")
    return int(status), json.loads(text)


def iperf_csv(text):
    """Final iperf2 UDP server report (-y C): bits/s, lost, total."""
    best = None
    for line in text.splitlines():
        f = line.strip().split(",")
        if len(f) >= 14:
            best = {"bps": float(f[8]), "lost": int(f[10]), "total": int(f[11])}
    return best


def run_flows(direction, dur, rates):
    """Both UEs send at once; returns per-UE receiver report and the window."""
    servers, results = {}, {}
    for dep, u in UES.items():
        if dep not in rates:
            continue
        if direction == "ul":
            cmd = ["-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--"]
            bind = []
        else:
            cmd = ["-n", "oai-ran", "exec", "deploy/" + dep, "-c", "nr-ue", "--"]
            bind = ["-B", u["ip"]]
        servers[dep] = subprocess.Popen(["kubectl", "--context", CTX, *cmd, "timeout", "-k", "5", str(dur + 12), "iperf", "-s", "-u",
                                         *bind, "-p", str(u["port"]), "-y", "C"],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(2)

    def client(dep):
        u = UES[dep]
        if direction == "ul":
            ex("oai-ran", dep, "nr-ue", "iperf", "-c", DN, "-B", u["ip"], "-u", "-b", rates[dep], "-l", "1200",
               "-t", str(dur), "-p", str(u["port"]), timeout=dur + 30, check=False)
        else:
            ex("oai-core", "oai-lab-dn", "dn", "iperf", "-c", u["ip"], "-u", "-b", rates[dep], "-l", "1200",
               "-t", str(dur), "-p", str(u["port"]), timeout=dur + 30, check=False)

    t0 = time.time()
    threads = [threading.Thread(target=client, args=(d,)) for d in servers]
    for t in threads: t.start()
    for t in threads: t.join()
    t1 = time.time()
    for dep, s in servers.items():
        out, _ = s.communicate(timeout=30)
        results[dep] = iperf_csv(out)
    return results, (t0, t1)


def kpm_rows(run):
    raw = ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", "/artifacts/runs/" + run + "/KPI_Metrics.csv", timeout=60)
    return raw, list(csv.DictReader(io.StringIO(raw)))


def kpm_mean(rows, amf_id, col, window):
    lo, hi = window[0] + 3, window[1] - 2
    v = [float(r[col] or 0) for r in rows
         if r.get("UE ID") == str(amf_id) and r.get("Collect Time (UNIX us)") and lo <= int(r["Collect Time (UNIX us)"]) / 1e6 <= hi]
    return {"mean": round(sum(v) / len(v), 2) if v else None, "max": max(v) if v else None, "samples": len(v)}


def mbps(rep):
    return round(rep["bps"] / 1e6, 3) if rep else None


def evaluate(result, rows, ratio, amf):
    """PRB-quota checks of every direction from the stored phases and KPM rows."""
    for direction, ph in result["phases"].items():
        col = PRB_COL[direction]
        for phase, p in ph.items():
            p["prb_share"] = {d: kpm_mean(rows, amf[d], col, p["window_unix"]) for d in amf}
            p["kpm_thp_kbps"] = {d: kpm_mean(rows, amf[d], THP_COL[direction], p["window_unix"]) for d in amf}
        b, q, r = ph["base"], ph["quota"], ph["restore"]
        u1b, u1q, u1r = b["mbps"]["oai-nr-ue"], q["mbps"]["oai-nr-ue"], r["mbps"]["oai-nr-ue"]
        u2b, u2q = b["mbps"]["oai-nr-ue2"], q["mbps"]["oai-nr-ue2"]
        pb, pq = b["prb_share"]["oai-nr-ue"]["mean"], q["prb_share"]["oai-nr-ue"]["mean"]
        ok_bind = pb is not None and pq is not None and pq <= ratio + 3 and pb > ratio + 10
        kb, kq = b["kpm_thp_kbps"]["oai-nr-ue"]["mean"], q["kpm_thp_kbps"]["oai-nr-ue"]["mean"]
        thr_ratio = kq / kb if kb else None
        iperf_ratio = u1q / u1b if u1b and u1q is not None else None
        prb_ratio = pq / pb if pb else None
        ok_level = thr_ratio is not None and prb_ratio and thr_ratio < 0.6 and abs(thr_ratio / prb_ratio - 1) <= LEVEL_TOLERANCE
        ok_other = bool(u2b) and u2q is not None and u2q >= 0.9 * u2b
        ok_restore = bool(u1b) and u1r is not None and u1r >= 0.8 * u1b
        result["checks"][direction + "_quota_binds"] = {"ok": ok_bind, "ue1_prb_share_base": pb, "ue1_prb_share_quota": pq,
                                                        "ue1_prb_share_quota_max": q["prb_share"]["oai-nr-ue"]["max"]}
        result["checks"][direction + "_throughput_level"] = {
            "ok": bool(ok_level), "ue1_kpm_kbps": [kb, kq], "throughput_ratio": round(thr_ratio, 3) if thr_ratio else None,
            "ue1_iperf_mbps": [u1b, u1q], "iperf_ratio": round(iperf_ratio, 3) if iperf_ratio else None,
            "prb_share_ratio": round(prb_ratio, 3) if prb_ratio else None}
        result["checks"][direction + "_other_ue_unaffected"] = {"ok": ok_other, "ue2_mbps": [u2b, u2q]}
        result["checks"][direction + "_restore"] = {"ok": ok_restore, "ue1_mbps": [u1b, u1r]}



def reevaluate(out):
    result = json.loads((out / "result.json").read_text())
    rows = list(csv.DictReader(io.StringIO((out / "KPI_Metrics.csv").read_text())))
    amf = {d: u["amf"] for d, u in result["ues"].items()}
    evaluate(result, rows, result["ratio"], amf)
    result["status"] = "PASS" if all(c["ok"] for c in result["checks"].values()) else "FAIL"
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": result["checks"]}, indent=2))
    return 0 if result["status"] == "PASS" else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--evaluate" in sys.argv:
        return reevaluate(pathlib.Path(args[0]))
    out = pathlib.Path(args[0]); out.mkdir(parents=True, exist_ok=True)
    ratio = int(args[1]) if len(args) > 1 else 10
    dur = int(args[2]) if len(args) > 2 else 20
    do_release = "--no-release" not in sys.argv
    run = (ROOT / "artifacts/k8s/state/current-staged-run").read_text().strip()
    result = {"run": run, "ratio": ratio, "phase_s": dur, "checks": {}, "phases": {}}

    for dep, u in UES.items():
        u["ip"] = ex("oai-ran", dep, "nr-ue", "ip", "-4", "-o", "addr", "show", "oaitun_ue1").split()[3].split("/")[0]
        ex("oai-ran", dep, "nr-ue", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1", "src", u["ip"])
    table = amf_table()
    supi = {"oai-nr-ue": "imsi-001010123456780", "oai-nr-ue2": "imsi-001010123456781"}
    for dep in UES:
        UES[dep]["supi"] = supi[dep]
        UES[dep]["amf"] = table.get(supi[dep])
    result["ues"] = {d: {k: u.get(k) for k in ("ip", "supi", "amf")} for d, u in UES.items()}
    if any(u["amf"] is None for u in UES.values()):
        result["status"] = "FAIL"; result["error"] = "AMF table lacks a UE"
        print(json.dumps(result, indent=2)); return 1
    ue1 = UES["oai-nr-ue"]
    gnb_since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    controls = []
    for direction in ("ul", "dl"):
        ph = {}
        for phase in ("base", "quota", "restore"):
            if phase != "base":
                status, body = ran_control({"supi": ue1["supi"], "action": "prb_quota",
                                            "max_prb_ratio": ratio if phase == "quota" else 100})
                controls.append({"direction": direction, "phase": phase, "http": status, "response": body})
                if status != 200:
                    raise SystemExit("RAN control failed: %s %s" % (status, body))
                time.sleep(1)
            rep, window = run_flows(direction, dur, RATES[direction])
            ph[phase] = {"window_unix": [round(window[0], 3), round(window[1], 3)],
                         "mbps": {d: mbps(r) for d, r in rep.items()}, "receiver": rep}
            time.sleep(1)
        result["phases"][direction] = ph

    time.sleep(6)  # last KPM indications
    raw, rows = kpm_rows(run)
    evaluate(result, rows, ratio, {d: u["amf"] for d, u in UES.items()})

    if do_release:
        ue2 = UES["oai-nr-ue2"]
        rel = {}
        flow = {}

        def ue1_flow():
            flow["rep"], flow["window"] = run_flows("ul", dur, {"oai-nr-ue": "1M"})

        t = threading.Thread(target=ue1_flow); t.start()
        time.sleep(5)
        t_rel = time.time()
        status, body = ran_control({"supi": ue2["supi"], "action": "release"})
        controls.append({"phase": "release", "http": status, "response": body})
        t.join()
        time.sleep(8)
        gnb_log = kubectl("-n", "oai-ran", "logs", "deploy/oai-gnb", "--since-time=" + gnb_since)
        ue2_log = kubectl("-n", "oai-ran", "logs", "deploy/oai-nr-ue2", "-c", "nr-ue", "--since-time=" + gnb_since)
        (out / "gnb.log").write_text(gnb_log); (out / "ue2.log").write_text(ue2_log)
        m = re.search(r"RC CONTROL RRC release: UE ([0-9a-f]{4}) \(AMF UE NGAP ID %d\) release requested" % ue2["amf"], gnb_log)
        rel["gnb_release_requested"] = bool(m)
        rel["rnti"] = m.group(1) if m else None
        rel["ue2_rrc_release"] = bool(re.search(r"RRCRelease", ue2_log))
        raw, rows = kpm_rows(run)
        after = [r for r in rows if r.get("Collect Time (UNIX us)") and int(r["Collect Time (UNIX us)"]) / 1e6 > t_rel + 3]
        rel["kpm_rows_after"] = len(after)
        rel["kpm_rows_ue2_after"] = sum(1 for r in after if r.get("UE ID") == str(ue2["amf"]))
        rep = flow["rep"].get("oai-nr-ue")
        rel["ue1_loss"] = round(rep["lost"] / rep["total"], 4) if rep and rep["total"] else None
        ok_rel = (status == 200 and rel["gnb_release_requested"] and rel["ue2_rrc_release"] and rel["kpm_rows_after"] > 0
                  and rel["kpm_rows_ue2_after"] == 0 and rel["ue1_loss"] is not None and rel["ue1_loss"] < 0.02)
        result["checks"]["release"] = {"ok": ok_rel, **rel}

    result["controls"] = controls
    (out / "KPI_Metrics.csv").write_text(raw)
    log = ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", "/artifacts/runs/" + run + "/KPI_Metrics_RAN_Control.jsonl", check=False)
    (out / "ran-control.jsonl").write_text(log)
    result["status"] = "PASS" if all(c["ok"] for c in result["checks"].values()) else "FAIL"
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": result["checks"]}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
