#!/usr/bin/env python3
"""iperf2 UDP backend (v4 plan §5.4) — runs INSIDE the UE keepalive sidecar.

Third generator for the cross-backend matrix: the canonical UDP load tool, used
for BOTH classes. iperf2's client reconfigures only per invocation, so a varying
per-second schedule is realised as consecutive 1 s constant-bitrate blocks
(`-u -b <bps> -l <payload> -t 1`); fine schedule shape is the pacer's job. The DN
must run `iperf -s -u` on the chosen port (runner.py starts one attached per run).

Rows match the pacer/hping format. iperf2 reports the client-side sent datagrams;
delivery ground-truth is the DN counter in runner.py.

Fixes (2026-10-22), applied to both classes alike:
  * `--no-udp-fin`: without it the client waits for the server's final UDP stats; a
    silent victim (DROP on the DN) never answers, so every block hung until the 3 s
    timeout -> ~1 s ON / 2 s OFF pulses that only the malicious flow showed.
  * deadline-driven blocks: each block runs `-t` = time left to the next 1 s boundary
    minus the measured process overhead, so one row per wall second (a fixed `-t 1`
    took 1.03-1.19 s per block and drifted ~10% behind the phase clock). `-b` is kept,
    so the per-second volume stays that of the pre-fix responsive blocks.
  * a block whose sent count is unknown (timeout / unparsable) or a second skipped
    because the previous block overran logs sent_* = None, never the target.
"""
import json, re, subprocess, sys, time

_SENT = re.compile(r"(\d+)\s+datagrams")
_MIN_BLOCK = 0.10          # s; iperf2 -t has 10 ms resolution
_OVH0 = 0.06               # s; initial process-overhead estimate (measured 0.02-0.08 s)


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
    ovh = _OVH0
    for i, sec in enumerate(p["seconds"]):
        tgt_b = float(sec.get("bytes") or 0.0)
        # the target is IP-level bytes/s (what URR counts); iperf2 -b is the PAYLOAD
        # bitrate, so scale by payload/(payload+28) to put the IP-level rate on target.
        bps = tgt_b * 8 * payload / (payload + 28)
        tx, stalled = 0, False
        deadline = mono0 + i + 1
        if bps > 0:
            blk = int((deadline - time.monotonic() - ovh) * 100) / 100.0
            if blk < _MIN_BLOCK:                          # behind schedule: skip, do not drift
                tx, stalled = None, True
            else:
                argv = ["iperf", "-u", "-c", dst, "-p", str(port), "-b", str(int(bps)),
                        "-l", str(payload), "-t", "%.2f" % min(blk, 1.0), "--no-udp-fin"]
                if bind:
                    argv += ["-B", bind]
                t0 = time.monotonic()
                try:
                    r = subprocess.run(argv, capture_output=True, text=True, timeout=min(blk, 1.0) + 2)
                    m = _SENT.search((r.stdout or "") + (r.stderr or ""))
                    tx = int(m.group(1)) if m else None
                    ovh = 0.7 * ovh + 0.3 * max(time.monotonic() - t0 - min(blk, 1.0), 0.0)
                except subprocess.TimeoutExpired:
                    tx = None
        rem = deadline - time.monotonic()
        if rem > 0:
            time.sleep(rem)
        sent_bytes = None if tx is None else tx * int(round(mean_size))
        row = {"t": round(start + i, 3), "sec": i, "backend": "iperf",
               "target_bytes": round(tgt_b, 1), "target_pkts": int(round(tgt_b / mean_size)) if mean_size else 0,
               "sent_bytes": sent_bytes, "sent_pkts": tx,
               "achieved_mbps": None if sent_bytes is None else round(sent_bytes * 8 / 1e6, 4), "achieved_pps": tx}
        if stalled:
            row["stalled"] = 1
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
