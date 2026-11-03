#!/usr/bin/env python3
"""Short-lived TCP connection client (v4 plan §6.3) — runs in the UE keepalive
sidecar. The benign hard-negative counterpart to a SYN flood: same SYN packets on
the wire, but each connection COMPLETES the handshake, exchanges a short
request/reply with the DN sink, and closes. Attack (SYN flood) sends SYNs that
never complete; the behavioural difference (completed exchanges, RTT, bytes
returned) is the signal — not the packet type. Connection arrivals follow the
per-second schedule (typically Hawkes), so rate and burstiness match the attack
counterpart. Needs dn_sink.py tcp running on the DN.

Plan: pacer-shaped, but the per-second target is a CONNECTION COUNT. We take it
from "pps" if present, else bytes / bytes_per_conn (default 200).
"""
import json, socket, sys, threading, time

BYTES_PER_CONN = 200.0


def _one_conn(dst, port, bind, stats):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if bind:
            s.bind((bind, 0))
        s.settimeout(2.0)
        s.connect((dst, port))
        s.sendall(b"GET\n")
        s.recv(64)
        s.close()
        stats[0] += 1
    except OSError:
        stats[1] += 1


def main():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != "-" else sys.stdin.read()
    p = json.loads(raw)
    dst, bind = p["dst"], p.get("bind")
    port = (p.get("ports") or [5402])[0]

    if p.get("start_at"):
        wait = p["start_at"] - time.time()
        if wait > 0:
            time.sleep(wait)
    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    stats = [0, 0]                                  # [completed, failed], over the run
    done0 = fail0 = 0
    for i, sec in enumerate(p["seconds"]):
        n = int(sec["pps"]) if sec.get("pps") else int(round(float(sec.get("bytes") or 0.0) / BYTES_PER_CONN))
        t_start = mono0 + i
        ts = []
        for k in range(n):
            due = t_start + (k + 0.5) / n if n else t_start
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            elif now - t_start >= 1.0:
                break
            th = threading.Thread(target=_one_conn, args=(dst, port, bind, stats), daemon=True)
            th.start(); ts.append(th)
        # a slow exchange must not eat the next second: it is counted in the second where it ends
        rem = (mono0 + i + 1) - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        completed, failed = stats[0] - done0, stats[1] - fail0
        done0, fail0 = done0 + completed, fail0 + failed
        sent_bytes = int(completed * BYTES_PER_CONN)
        row = {"t": round(start + i, 3), "sec": i, "backend": "tcp_shortconn",
               "target_bytes": round(float(sec.get("bytes") or 0.0), 1), "target_pkts": n,
               "sent_bytes": sent_bytes, "sent_pkts": completed, "conn_failed": failed,
               "achieved_mbps": round(sent_bytes * 8 / 1e6, 4), "achieved_pps": completed}
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
