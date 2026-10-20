#!/usr/bin/env python3
"""iperf2 UDP backend (v4 plan §5.4) — runs INSIDE the UE keepalive sidecar.

Third generator for the cross-backend matrix: the canonical UDP load tool, used
for BOTH classes. iperf2's client reconfigures only per invocation, so a varying
per-second schedule is realised as consecutive 1 s constant-bitrate blocks
(`-u -b <bps> -l <payload> -t 1`); fine schedule shape is the pacer's job. The DN
must run `iperf -s -u` on the chosen port (runner.py starts one attached per run).

Rows match the pacer/hping format. iperf2 reports the client-side sent datagrams;
delivery ground-truth is the DN counter in runner.py.
"""
import json, re, subprocess, sys, time

_SENT = re.compile(r"(\d+)\s+datagrams")


def _mean_size(bins):
    lens = [b[0] for b in bins]
    ws = [b[1] for b in bins]
    return sum(l * w for l, w in zip(lens, ws)) / sum(ws)


def main():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 and sys.argv[1] != "-" else sys.stdin.read()
    p = json.loads(raw)
    dst = p["dst"]
    port = (p.get("ports") or [5401])[0]
    bind = p.get("bind")
    mean_size = _mean_size(p["sizes"]) if p.get("sizes") else 1228.0
    payload = max(int(round(mean_size)) - 28, 1)      # iperf -l is UDP payload length

    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    for i, sec in enumerate(p["seconds"]):
        tgt_b = float(sec.get("bytes") or 0.0)
        # the target is IP-level bytes/s (what URR counts); iperf2 -b is the PAYLOAD
        # bitrate, so scale by payload/(payload+28) to put the IP-level rate on target.
        bps = tgt_b * 8 * payload / (payload + 28)
        tx = 0
        if bps > 0:
            argv = ["iperf", "-u", "-c", dst, "-p", str(port), "-b", str(int(bps)),
                    "-l", str(payload), "-t", "1"]
            if bind:
                argv += ["-B", bind]
            try:
                r = subprocess.run(argv, capture_output=True, text=True, timeout=3)
                m = _SENT.search((r.stdout or "") + (r.stderr or ""))
                tx = int(m.group(1)) if m else int(round(tgt_b / mean_size))
            except subprocess.TimeoutExpired:
                tx = int(round(tgt_b / mean_size))
        rem = (mono0 + i + 1) - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        sent_bytes = tx * int(round(mean_size))
        row = {"t": round(start + i, 3), "sec": i, "backend": "iperf",
               "target_bytes": round(tgt_b, 1), "target_pkts": int(round(tgt_b / mean_size)) if mean_size else 0,
               "sent_bytes": sent_bytes, "sent_pkts": tx,
               "achieved_mbps": round(sent_bytes * 8 / 1e6, 4), "achieved_pps": tx}
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
