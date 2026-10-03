#!/usr/bin/env python3
"""A.7 calibration of URR (UPF) against KPM PDCP SDU volume (gNB).

Usage: calibrate.py <out-dir> <experiment-dir>...

KPM DRB.PdcpSduVolume counts IP packets; the UPF URR counts each packet with
a fixed per-packet header overhead that differs per direction (UL: Ethernet,
DL: Ethernet + outer IP/UDP/GTP-U). A plain ratio KPM/URR therefore depends
on the packet size, so the consistency check uses
    KPM_bytes ~= URR_bytes - c_dir * URR_packets
with c_dir fitted by least squares over all benign windows. For each window
length W the relative residual |KPM - expected| / expected gives epsilon
(p99, max); the plain-ratio model is reported alongside for comparison.
"""
import csv
import json
import math
import pathlib
import subprocess
import sys
from collections import defaultdict

WINDOWS = (1, 2, 5, 10)
MIN_BYTES_PER_S = 20000  # windows below this carry only keep-alives


def urr_reports(pcap):
    out = subprocess.run(
        ["tshark", "-r", str(pcap), "-Y", "pfcp.msg_type == 56 && pfcp.volume_measurement.tovol",
         "-T", "fields", "-E", "separator=,", "-e", "frame.time_epoch",
         "-e", "pfcp.volume_measurement.ulvol", "-e", "pfcp.volume_measurement.dlvol",
         "-e", "pfcp.volume_measurement.ulnop", "-e", "pfcp.volume_measurement.dlnop"],
        check=True, capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        t, ul, dl, ulp, dlp = (line.split(",") + [""] * 5)[:5]
        rows.append((float(t), int(ul or 0), int(dl or 0), int(ulp or 0), int(dlp or 0)))
    return rows


def kpm_rows(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r.get("UE ID"):
                rows.append((int(r["Time (UNIX ms)"]) / 1000,
                             float(r["DRB.PdcpSduVolumeUL (bytes)"] or 0),
                             float(r["DRB.PdcpSduVolumeDL (bytes)"] or 0)))
    return rows


def load(d):
    d = pathlib.Path(d)
    prof = json.loads((d / "profile.json").read_text()) if (d / "profile.json").exists() \
        else {"rate": "10M", "udpPayloadBytes": 1200}
    with open(d / "phases.csv") as f:
        phases = [p for p in csv.DictReader(f) if p["status"] == "ok"]
    return {"dir": d.name, "profile": prof, "phases": phases,
            "urr": urr_reports(d / "pfcp.pcap"), "kpm": kpm_rows(d / "KPI_Metrics.csv")}


def kpm_gaps(run, limit=1.5):
    t = [x[0] for x in run["kpm"]]
    return [(a, b) for a, b in zip(t, t[1:]) if b - a > limit]


def bins(run, w, lag=None):
    """Per window: KPM bytes, URR bytes and packets, per direction, restricted
    to the phase carrying traffic in that direction. KPM timestamps are
    shifted by the run's estimated lag (KPM is stamped by the xApp on receipt,
    URR by the UPF at report time); windows touching a KPM gap are dropped."""
    lag = run.get("lag", 0.0) if lag is None else lag
    gaps = kpm_gaps(run)
    b = defaultdict(lambda: [0.0] * 6)  # kul, kdl, uul, udl, pul, pdl
    for t, ul, dl in run["kpm"]:
        t -= lag
        b[int(t // w)][0] += ul; b[int(t // w)][1] += dl
    for t, ul, dl, pu, pd in run["urr"]:
        x = b[int(t // w)]
        x[2] += ul; x[3] += dl; x[4] += pu; x[5] += pd
    out = []
    for p in run["phases"]:
        lo, hi = int(p["start_unix_ms"]) / 1000, int(p["end_unix_ms"]) / 1000
        i = 0 if p["direction"] == "ul" else 1
        # Active span from the URR itself (iperf starts 1-3 s after the
        # phase timestamp): 1 s windows with at least half the median rate,
        # then one second of margin at each end
        per_s = defaultdict(float)
        for t, ul, dl, pu, pd in run["urr"]:
            if lo <= t <= hi + 3:
                per_s[int(t)] += ul if i == 0 else dl
        if not per_s:
            continue
        med = sorted(per_s.values())[len(per_s) // 2]
        active = [t for t, v in per_s.items() if v >= med / 2]
        lo, hi = min(active) + 1, max(active) - 1
        for k in range(int(lo // w) + 1, int(hi // w)):
            if any(a - lag - 1 < (k + 1) * w and b_ - lag > k * w for a, b_ in gaps):
                continue
            x = b.get(k)
            if x and x[2 + i] >= MIN_BYTES_PER_S * w:
                out.append((p["direction"], x[0 + i], x[2 + i], x[4 + i]))
    return out


def estimate_lag(run):
    """Lag (s) of KPM behind URR minimising the 1 s mismatch of total bytes."""
    best = (float("inf"), 0.0)
    for i in range(-30, 31):
        lag = i / 10
        s = bins(run, 1, lag)
        if len(s) < 10:
            continue
        cost = sum(abs(k - u) for _, k, u, n in s) / sum(u for _, k, u, n in s)
        best = min(best, (cost, lag))
    return best[1]


def fit_c(samples):
    num = sum((u - k) * n for _, k, u, n in samples)
    den = sum(n * n for _, k, u, n in samples)
    return num / den if den else 0.0


def eps(errors):
    if not errors:
        return None
    e = sorted(abs(x) for x in errors)
    p99 = e[min(len(e) - 1, math.ceil(0.99 * len(e)) - 1)]
    return {"n": len(e), "p50": round(e[len(e) // 2], 5), "p99": round(p99, 5), "max": round(e[-1], 5)}


def load_cpu(run_dir, duration):
    p = pathlib.Path(run_dir) / "cpu.json"
    if not p.exists():
        return None
    c = json.loads(p.read_text())
    dt = c["after"]["t"] - c["before"]["t"]
    return {k: round((c["after"][k] - c["before"][k]) / 1e6 / dt * 100, 2)
            for k in c["before"] if k != "t" and c["before"][k] is not None and c["after"].get(k) is not None}


def main():
    out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    runs = [load(d) for d in sys.argv[2:]]
    for r in runs:
        r["lag"] = estimate_lag(r)
    result = {"model": "KPM_bytes = URR_bytes - c_dir * URR_packets", "windows": {}, "profiles": []}
    # c from 1 s windows of all runs (the estimate does not depend on W)
    s1 = [s for r in runs for s in bins(r, 1)]
    c = {d: fit_c([s for s in s1 if s[0] == d]) for d in ("ul", "dl")}
    result["c_bytes_per_packet"] = {d: round(v, 2) for d, v in c.items()}
    ratio = {d: sum(k for x, k, u, n in s1 if x == d) / max(1, sum(u for x, k, u, n in s1 if x == d)) for d in ("ul", "dl")}
    result["ratio_model_r_hat"] = {d: round(v, 5) for d, v in ratio.items()}
    for w in WINDOWS:
        s = [x for r in runs for x in bins(r, w)]
        res = {}
        for d in ("ul", "dl"):
            sd = [x for x in s if x[0] == d]
            res[d] = {"packet_model": eps([(k - (u - c[d] * n)) / (u - c[d] * n) for _, k, u, n in sd]),
                      "ratio_model": eps([(k - ratio[d] * u) / (ratio[d] * u) for _, k, u, n in sd])}
        result["windows"][str(w)] = res
    # False positive rate on benign traffic for a mismatch threshold epsilon:
    # one window over epsilon, or two consecutive windows (same run, phase)
    result["false_positive_rate"] = {}
    for w in WINDOWS:
        fw = {}
        for d in ("ul", "dl"):
            seqs = []
            for r in runs:
                e = [abs((k - (u - c[d] * n)) / (u - c[d] * n)) for x, k, u, n in bins(r, w) if x == d]
                if e:
                    seqs.append(e)
            n_win = sum(len(q) for q in seqs)
            n_pair = sum(max(0, len(q) - 1) for q in seqs)
            fw[d] = {str(t): {"single": round(sum(v > t for q in seqs for v in q) / max(1, n_win), 4),
                              "consecutive2": round(sum(q[i] > t and q[i + 1] > t for q in seqs for i in range(len(q) - 1)) / max(1, n_pair), 4)}
                     for t in (0.02, 0.05, 0.10, 0.15, 0.20)}
        result["false_positive_rate"][str(w)] = fw
    for r in runs:
        s = bins(r, 1)
        prof = {"run": r["dir"], **r["profile"], "reports": len(r["urr"]),
                "kpm_lag_s": r["lag"], "kpm_gaps": len(kpm_gaps(r))}
        for d in ("ul", "dl"):
            sd = [x for x in s if x[0] == d]
            if sd:
                k = sum(x[1] for x in sd); u = sum(x[2] for x in sd); n = sum(x[3] for x in sd)
                prof[d] = {"kpm_over_urr": round(k / u, 4), "bytes_per_packet_kpm": round(k / n, 1),
                           "bytes_per_packet_urr": round(u / n, 1),
                           "residual_packet_model": round((k - (u - c[d] * n)) / (u - c[d] * n), 5)}
        dur = sum((int(p["end_unix_ms"]) - int(p["start_unix_ms"])) / 1000 for p in r["phases"])
        prof["reports_per_s"] = round(len(r["urr"]) / dur, 3) if dur else None
        prof["cpu_percent"] = load_cpu(pathlib.Path(sys.argv[2 + runs.index(r)]), dur)
        result["profiles"].append(prof)
    (out / "calibration.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
