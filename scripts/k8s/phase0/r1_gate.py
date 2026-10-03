#!/usr/bin/env python3
"""Gate R1 (plan): two UEs, the xApp binds KPM <-> URR <-> SUPI for each UE.

Usage: r1_gate.py <out-dir> [duration-s=40]

Prerequisite: both UEs attached (oai-nr-ue, oai-nr-ue2 = IMSI + 1), producer
with the AMF UE table watcher, xApp with the identity join.
UE1 sends 4 Mbit/s and UE2 1 Mbit/s uplink at the same time, so a swapped
SUPI binding shows up as a ~4x volume mismatch.
Checks:
  1. AMF table: both SUPIs registered with distinct AMF UE NGAP IDs.
  2. URR at the xApp: each SUPI's reports carry ran_identity equal to the AMF
     table and the PFCP End Time.
  3. KPM at the xApp: every per-UE row of the traffic window whose UE ID
     (AMF UE NGAP ID) is in the AMF table carries that UE's SUPI; rows of
     stale gNB contexts (UE ID no longer in the table) carry none.
  4. Volume: per SUPI, KPM UL vs URR UL - c_UL * packets (A.7) within 10 %;
     the swapped pairing must be off by far more.
"""
import csv
import io
import json
import pathlib
import subprocess
import sys
import threading
import time

CTX = "oai-lab"
C_UL = 16.3  # A.7: URR UL overhead per packet (bytes)
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/k8s"))


def kubectl(*args, timeout=60):
    return subprocess.run(["kubectl", "--context", CTX, *args], check=True, capture_output=True,
                          text=True, timeout=timeout).stdout


def ex(ns, dep, ctr, *cmd, timeout=60):
    return kubectl("-n", ns, "exec", "deploy/" + dep, "-c", ctr, "--", *cmd, timeout=timeout)


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


def main():
    out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    dur = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    run = (ROOT / "artifacts/k8s/state/current-staged-run").read_text().strip()
    dn = "172.30.26.10"
    result = {"run": run, "checks": {}}

    ues = {"oai-nr-ue": {"rate": "4M", "port": 5201}, "oai-nr-ue2": {"rate": "1M", "port": 5202}}
    for dep, u in ues.items():
        u["ip"] = ex("oai-ran", dep, "nr-ue", "ip", "-4", "-o", "addr", "show", "oaitun_ue1").split()[3].split("/")[0]
        ex("oai-ran", dep, "nr-ue", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1", "src", u["ip"])
    result["ue_ips"] = {d: u["ip"] for d, u in ues.items()}

    # Concurrent uplink at different rates
    servers = [subprocess.Popen(["kubectl", "--context", CTX, "-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
                                 "timeout", str(dur + 15), "iperf", "-s", "-u", "-p", str(u["port"])],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for u in ues.values()]
    time.sleep(2)
    t0 = time.time()
    threads = [threading.Thread(target=ex, args=("oai-ran", d, "nr-ue", "iperf", "-c", dn, "-B", u["ip"], "-u", "-b", u["rate"],
                                                 "-l", "1200", "-t", str(dur), "-p", str(u["port"])), kwargs={"timeout": dur + 30})
               for d, u in ues.items()]
    for t in threads: t.start()
    for t in threads: t.join()
    t1 = time.time()
    for s in servers: s.wait(timeout=30)
    time.sleep(8)  # last reports and KPM indications
    result["window_unix"] = [round(t0, 3), round(t1, 3)]

    # 1. AMF table
    table = amf_table()
    (out / "amf-table.json").write_text(json.dumps(table, indent=2) + "\n")
    ok1 = len(table) >= 2 and len(set(table.values())) == len(table)
    result["checks"]["amf_table_two_ues"] = {"ok": ok1, "table": table}

    # Data at the xApp
    base = "/artifacts/runs/" + run
    kpm_raw = ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", base + "/KPI_Metrics.csv")
    urr_raw = ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", base + "/urr-received.jsonl")
    (out / "KPI_Metrics.csv").write_text(kpm_raw); (out / "urr-received.jsonl").write_text(urr_raw)
    urr = [json.loads(l)["report"] for l in urr_raw.splitlines() if l.strip()]
    kpm = list(csv.DictReader(io.StringIO(kpm_raw)))

    # 2. URR carries the RAN identity of the AMF table and the End Time
    lo, hi = t0 + 3, t1 - 3
    win_urr = [r for r in urr if r.get("end_time_unix") and lo <= r["end_time_unix"] <= hi]
    per = {}
    for r in win_urr:
        p = per.setdefault(r["supi"], {"reports": 0, "with_identity": 0, "identity_match": 0, "ul_bytes": 0, "ul_packets": 0})
        p["reports"] += 1
        ri = r.get("ran_identity")
        if ri:
            p["with_identity"] += 1
            p["identity_match"] += int(table.get(r["supi"]) == ri["amf_ue_ngap_id"])
        p["ul_bytes"] += r["ul_bytes"]; p["ul_packets"] += r["ul_packets"]
    ok2 = len(per) >= 2 and all(v["reports"] > 0 and v["identity_match"] == v["reports"] for v in per.values())
    result["checks"]["urr_identity_and_end_time"] = {"ok": ok2, "per_supi": per,
                                                     "reports_without_end_time": sum(1 for r in urr if not r.get("end_time_unix"))}

    # 3. KPM rows carry the SUPI bound to their UE ID
    by_id = {v: k for k, v in table.items()}
    col_t = "Collect Time (UNIX us)"
    win_kpm = [r for r in kpm if r.get("UE ID") and r.get(col_t) and lo <= int(r[col_t]) / 1e6 <= hi]
    # Rows of UE IDs in the AMF table must carry their SUPI; rows of UE IDs
    # absent from it (stale gNB contexts of earlier registrations) must not
    live = [r for r in win_kpm if int(r["UE ID"]) in by_id]
    stale = [r for r in win_kpm if int(r["UE ID"]) not in by_id]
    labelled = sum(1 for r in live if r.get("SUPI"))
    wrong = [r["UE ID"] + "->" + r.get("SUPI", "") for r in win_kpm
             if r.get("SUPI") and by_id.get(int(r["UE ID"])) != r["SUPI"]]
    ok3 = len(live) > 0 and labelled == len(live) and not wrong and len({r["SUPI"] for r in live}) >= 2
    result["checks"]["kpm_rows_labelled"] = {"ok": ok3, "rows_live_ues": len(live), "labelled": labelled,
                                             "rows_stale_ue_ids": len(stale), "wrong": wrong[:10]}
    win_kpm = live

    # 4. Volume consistency per SUPI (and the swapped pairing)
    kul = {}
    for r in win_kpm:
        kul[r["SUPI"]] = kul.get(r["SUPI"], 0) + float(r["DRB.PdcpSduVolumeUL (bytes)"] or 0)
    exp = {s: v["ul_bytes"] - C_UL * v["ul_packets"] for s, v in per.items()}
    err = {s: round((kul.get(s, 0) - exp[s]) / exp[s], 4) for s in exp if exp[s] > 0}
    supis = sorted(exp)
    swapped = {}
    if len(supis) == 2:
        a, b = supis
        swapped = {a: round((kul.get(b, 0) - exp[a]) / exp[a], 4), b: round((kul.get(a, 0) - exp[b]) / exp[b], 4)}
    ok4 = len(err) >= 2 and all(abs(e) < 0.10 for e in err.values()) and all(abs(e) > 0.5 for e in swapped.values())
    result["checks"]["volume_per_supi"] = {"ok": ok4, "kpm_ul": kul, "urr_expected_ul": exp,
                                           "relative_error": err, "relative_error_if_swapped": swapped}

    result["status"] = "PASS" if all(c["ok"] for c in result["checks"].values()) else "FAIL"
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
