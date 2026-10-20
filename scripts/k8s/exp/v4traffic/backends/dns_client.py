#!/usr/bin/env python3
"""DNS query client (v4 plan §6.3) — runs in the UE keepalive sidecar. The benign
hard-negative counterpart to a UDP small-packet flood: small UDP packets at a
paced/bursty rate, same size class as a 64-byte flood, but each query gets an
answer back from the DN resolver (dn_sink.py dns) — a completed request/response
exchange, which the flood lacks. Query arrivals follow the per-second schedule.

Plan: pacer-shaped; per-second target is a QUERY COUNT (from "pps" else
bytes / mean query size). Needs dn_sink.py dns running on the DN.
"""
import json, socket, struct, sys, time

QNAME = b"\x03svc\x05local\x00"                     # svc.local


def _query(tid):
    header = struct.pack(">HHHHHH", tid & 0xFFFF, 0x0100, 1, 0, 0, 0)
    return header + QNAME + struct.pack(">HH", 1, 1)  # QTYPE A, QCLASS IN


def main():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != "-" else sys.stdin.read()
    p = json.loads(raw)
    dst, bind = p["dst"], p.get("bind")
    port = (p.get("ports") or [5353])[0]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if bind:
        s.bind((bind, 0))
    s.setblocking(False)
    pkt_len = 28 + len(_query(0))                   # IP+UDP + DNS query, for the byte count

    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    for i, sec in enumerate(p["seconds"]):
        n = int(sec["pps"]) if sec.get("pps") else int(round(float(sec.get("bytes") or 0.0) / pkt_len))
        t_start = mono0 + i
        sent = ans = 0
        for k in range(n):
            due = t_start + (k + 0.5) / n if n else t_start
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            elif now - t_start >= 1.0:
                break
            try:
                s.sendto(_query(sent), (dst, port)); sent += 1
            except OSError:
                pass
            try:                                    # drain any replies that have arrived
                while True:
                    s.recv(512); ans += 1
            except OSError:
                pass
        time.sleep(min(0.05, max(0.0, (mono0 + i + 1) - time.monotonic())))
        try:
            while True:
                s.recv(512); ans += 1
        except OSError:
            pass
        rem = (mono0 + i + 1) - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        sent_bytes = sent * pkt_len
        row = {"t": round(start + i, 3), "sec": i, "backend": "dns_client",
               "target_bytes": round(float(sec.get("bytes") or 0.0), 1), "target_pkts": n,
               "sent_bytes": sent_bytes, "sent_pkts": sent, "answers": ans,
               "achieved_mbps": round(sent_bytes * 8 / 1e6, 4), "achieved_pps": sent}
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)
    s.close()


if __name__ == "__main__":
    main()
