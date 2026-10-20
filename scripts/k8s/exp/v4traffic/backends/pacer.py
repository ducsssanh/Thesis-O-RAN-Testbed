#!/usr/bin/env python3
"""UDP pacer backend (v4 plan §5.4) — runs INSIDE the UE keepalive sidecar.

Stdlib only (python3 is present on the sidecar). Reads a per-second plan and
sends UDP so the realised IP-level byte/packet rate follows the schedule, then
prints achieved per-second rows (JSON) to stdout so the host runner can log them.
This is the single backend that follows ANY schedule, used for BOTH classes
(benign and attack) from the same container and egress — the C4/C1 fix.

Plan (JSON on argv[1] or stdin):
  {"dst": "172.30.26.10", "bind": "10.1.0.2", "ports": [5401,...],
   "sizes": [[64,0.5],[1228,0.5]],          # IP-length bins + weights (payload = len-28)
   "process": "even"|"poisson",
   "seconds": [{"bytes": 100000.0, "pps": null}, ...],  # per-second targets
   "seed": 1, "attack_active": [1,0,...]}    # optional per-second gate (for the log)

Rate control: each second, derive a packet count from target bytes and the mean
sampled size (or from "pps" if given), draw sizes from the bin weights, schedule
sends evenly (or with exponential gaps) across the second with a monotonic clock,
and never block — if the host can't keep up it records the shortfall rather than
spilling into the next second. Timestamps are CLOCK_REALTIME so they align with
the KPM/URR/profiler arrival stamps used by build_dataset_v4.
"""
import json, random, socket, struct, sys, time


def load_plan():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != "-" else sys.stdin.read()
    return json.loads(raw)


def main():
    p = load_plan()
    rng = random.Random(p.get("seed", 0))
    dst = p["dst"]
    ports = p.get("ports") or [p.get("port", 5401)]
    bins = p["sizes"]                                  # [[ip_len, weight], ...]
    lens = [b[0] for b in bins]
    weights = [b[1] for b in bins]
    mean_size = sum(l * w for l, w in zip(lens, weights)) / sum(weights)
    process = p.get("process", "even")
    gate = p.get("attack_active")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if p.get("bind"):
        s.bind((p["bind"], 0))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
    payloads = {l: bytes(max(l - 28, 1)) for l in lens}   # IP len -> UDP payload bytes

    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    for i, sec in enumerate(p["seconds"]):
        target_bytes = float(sec.get("bytes") or 0.0)
        if sec.get("pps"):
            n = int(round(sec["pps"]))
        else:
            n = int(round(target_bytes / mean_size)) if mean_size > 0 else 0
        t_sec_start = mono0 + i
        # intra-second schedule of send offsets (seconds from t_sec_start)
        if n <= 0:
            offsets = []
        elif process == "poisson":
            # given n arrivals in the second, Poisson arrival times are uniform order statistics
            offsets = sorted(rng.random() for _ in range(n))
        else:
            offsets = [(k + 0.5) / n for k in range(n)]
        sent_pkts = sent_bytes = 0
        szs = [lens[_weighted(rng, weights)] for _ in range(n)]
        for k in range(n):
            due = t_sec_start + offsets[k]
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            elif now - t_sec_start >= 1.0:
                break                                    # out of budget for this second; record shortfall
            L = szs[k]
            try:
                s.sendto(payloads[L], (dst, ports[k % len(ports)]))
                sent_pkts += 1
                sent_bytes += L
            except OSError:
                pass
        # hold to the second boundary so the next second starts aligned
        rem = (mono0 + i + 1) - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        row = {"t": round(start + i, 3), "sec": i,
               "target_bytes": round(target_bytes, 1), "target_pkts": n,
               "sent_bytes": sent_bytes, "sent_pkts": sent_pkts,
               "achieved_mbps": round(sent_bytes * 8 / 1e6, 4), "achieved_pps": sent_pkts}
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)
    s.close()


def _weighted(rng, weights):
    x = rng.random() * sum(weights)
    c = 0.0
    for i, w in enumerate(weights):
        c += w
        if x <= c:
            return i
    return len(weights) - 1


if __name__ == "__main__":
    main()
