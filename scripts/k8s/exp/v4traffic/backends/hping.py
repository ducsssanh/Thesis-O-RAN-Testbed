#!/usr/bin/env python3
"""hping3 backend (v4 plan §5.4) — runs INSIDE the UE keepalive sidecar.

A second generator for the cross-backend matrix: a real packet-crafting tool with
its own code path and real protocol headers, so the detector cannot shortcut on
"which tool / which protocol". Used for BOTH classes — a slow run and a high-rate
run differ only in the plan's mean rate, not the tool.

Modes: udp | syn | icmp. UDP carries a payload = the size-prior mean; SYN/ICMP
have protocol-fixed sizes (sizes.FIXED), shared with their benign counterparts.

hping3 cannot be reconfigured sub-second and tends to overrun a 1 s budget
(it lingers for responses), so this backend realises the PER-PHASE MEAN rate as a
single whole-duration invocation (`-c total -i uINT`); the fine per-second
schedule shape is the pacer's job (documented limitation). It still emits one
per-second achieved row aligned to CLOCK_REALTIME for the causal join; per-second
counts are the modelled even share, and the FINAL row carries hping3's real total
transmitted. Ground-truth delivery is the DN/URR counter, not this self-report.

Plan (JSON argv[1]/stdin): pacer shape + "mode": "udp"|"syn"|"icmp".
Needs CAP_NET_RAW (the sidecar has it).
"""
import json, re, subprocess, sys, threading, time

_TX = re.compile(r"(\d+)\s+packets transmitted")


def _mean_size(bins):
    lens = [b[0] for b in bins]
    ws = [b[1] for b in bins]
    return sum(l * w for l, w in zip(lens, ws)) / sum(ws)


def _argv(mode, dst, port, total, interval_us, payload):
    base = ["hping3", "-I", "oaitun_ue1", "-q", "-c", str(int(total)), "-i", f"u{int(interval_us)}"]
    if mode == "udp":
        return base + ["--udp", "-p", str(port), "-d", str(max(payload - 28, 0)), dst]
    if mode == "syn":
        return base + ["-S", "-p", str(port), dst]
    if mode == "icmp":
        return base + ["--icmp", dst]
    raise ValueError(mode)


def main():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != "-" else sys.stdin.read()
    p = json.loads(raw)
    mode = p.get("mode", "udp")
    dst = p["dst"]
    port = (p.get("ports") or [5401])[0]
    mean_size = _mean_size(p["sizes"]) if p.get("sizes") else 64.0
    payload = int(round(mean_size))
    T = len(p["seconds"])

    # per-second packet targets from the schedule; total + mean interval drive one run
    pps = []
    for sec in p["seconds"]:
        if sec.get("pps"):
            pps.append(int(sec["pps"]))
        else:
            pps.append(int(round(float(sec.get("bytes") or 0.0) / mean_size)) if mean_size > 0 else 0)
    total = sum(pps)
    active = [i for i in range(T) if pps[i] > 0]         # a flood over the twin stays silent before its onset
    mean_pps = total / len(active) if active else 0
    interval_us = max(int(round(1e6 / mean_pps)), 1) if mean_pps > 0 else 1000000

    if p.get("start_at"):
        wait = p["start_at"] - time.time()
        if wait > 0:
            time.sleep(wait)
    hold = {}
    result = {}

    def _run():
        time.sleep(active[0])
        try:
            hold["proc"] = subprocess.Popen(_argv(mode, dst, port, total, interval_us, payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except OSError as e:
            result["error"] = str(e)
            return
        out, err = hold["proc"].communicate()
        m = _TX.search((err or "") + (out or ""))
        if m:
            result["tx"] = int(m.group(1))
        else:
            result["error"] = "no transmit count: rc %s %s" % (hold["proc"].returncode, (err or "")[-200:])

    worker = threading.Thread(target=_run, daemon=True) if total > 0 else None
    if worker:
        worker.start()
    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    for i in range(T):
        tgt_b = float(p["seconds"][i].get("bytes") or (pps[i] * mean_size))
        # modelled per-second send = the even share of the single run
        sent_pkts = int(round(mean_pps)) if pps[i] > 0 else 0
        sent_bytes = sent_pkts * payload
        rem = (mono0 + i + 1) - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        row = {"t": round(start + i, 3), "sec": i, "backend": "hping", "mode": mode,
               "target_bytes": round(tgt_b, 1), "target_pkts": pps[i],
               "sent_bytes": sent_bytes, "sent_pkts": sent_pkts,
               "achieved_mbps": round(sent_bytes * 8 / 1e6, 4), "achieved_pps": sent_pkts}
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)

    if worker:
        worker.join(timeout=5)
        if worker.is_alive() and hold.get("proc"):
            hold["proc"].terminate()
            worker.join(timeout=2)
    # final row: hping3's real total transmitted over the run (for achieved QA)
    if result.get("error") or (total > 0 and "tx" not in result):
        sys.exit("hping3 failed: %s" % result.get("error", "still running"))   # never report the target as sent
    tx = result.get("tx", total)
    print(json.dumps({"t": round(start + T, 3), "sec": T, "backend": "hping", "mode": mode,
                      "final": True, "run_tx_pkts": tx, "run_target_pkts": total,
                      "run_tx_mbps": round(tx * payload * 8 / 1e6 / max(T, 1), 4)}), flush=True)


if __name__ == "__main__":
    main()
