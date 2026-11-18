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
Benign twin (real window replay) adds:
   "seconds": [{"bytes": 500.0, "pkts": [58, 58, 300]}, ...]   # exact IP lengths of that second; no "sizes"
   "start_at": 1793539600.42,               # wall-clock time of second 0 (first row reports late_s)
   "span": [0.05, 0.75]                     # part of each second the packets are sent in
Reactive benign (end-to-end runs, 2026-11-13), optional:
   "reactive": {"port": 7401, "thr": 0.05, "down": 0.7, "up": 0.1, "floor": 0.02, "min_bytes": 1500}
   The DN reports the UDP payload bytes it received from this flow per UNIX second (dn_sink.py feedback, over the
   pod network). Once a second the pacer takes the newest two reported seconds: loss = 1 - received / sent; if the
   pair carried >= min_bytes and loss > thr the send multiplier m goes to max(floor, m x down), otherwise to
   min(1, m + up) (AIMD, as a TCP-like application backs off). Packets are kept with probability m, so the size
   mix of the window stays; m = 1 is exactly the plain replay. Rows add m, the loss used and the packets held back.
   "seconds": [{..., "offs": [0.012, 0.012, 0.407]}, ...]   # send time of each packet in its second (TTI replay); span unused

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
    bins = p.get("sizes") or [[256, 1.0]]              # [[ip_len, weight], ...]; unused when a second has "pkts"
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
    span0, span1 = p.get("span") or [0.0, 1.0]
    # fan-out: rotate the destination host over <dst_base>.1 .. .N (dst_estimate signal)
    fanout = int(p.get("fanout", 0) or 0)
    if fanout > 1:
        net = ".".join(dst.split(".")[:3])
        first = int(p.get("fanout_base", 1))          # first host octet (DN aliases start here)
        dsts = [f"{net}.{first + k}" for k in range(fanout)]
    else:
        dsts = [dst]

    react = p.get("reactive")
    fb, mult, last_loss, sent_w, rx_w, eval_w, held, nrep = None, 1.0, None, {}, {}, None, 0, [0]
    if react:
        fb = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        fb.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        fb.bind(("0.0.0.0", int(react["port"])))
        fb.setblocking(False)
        krng = random.Random(p.get("seed", 0) ^ 0x7EAC)

    late = None
    if p.get("start_at"):
        wait = p["start_at"] - time.time()
        if wait > 0:
            time.sleep(wait)
        late = round(max(-wait, 0.0), 3)
    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    for i, sec in enumerate(p["seconds"]):
        target_bytes = float(sec.get("bytes") or 0.0)
        exact = sec.get("pkts")
        if exact is not None:
            n = len(exact)
        elif sec.get("pps"):
            n = int(round(sec["pps"]))
        else:
            n = int(round(target_bytes / mean_size)) if mean_size > 0 else 0
        t_sec_start = mono0 + i
        # intra-second schedule of send offsets (seconds from t_sec_start)
        if n <= 0:
            offsets = []
        elif sec.get("offs") is not None:
            offsets = sec["offs"]
        elif process == "poisson":
            # given n arrivals in the second, Poisson arrival times are uniform order statistics
            offsets = sorted(span0 + (span1 - span0) * rng.random() for _ in range(n))
        else:
            offsets = [span0 + (span1 - span0) * (k + 0.5) / n for k in range(n)]
        if fb is not None:
            mult, last_loss, eval_w = _react(fb, react, mult, last_loss, sent_w, rx_w, eval_w, nrep)
        held = 0
        sent_pkts = sent_bytes = 0
        szs = exact if exact is not None else [lens[_weighted(rng, weights)] for _ in range(n)]
        for k in range(n):
            due = t_sec_start + offsets[k]
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            elif now - t_sec_start >= 1.0:
                break                                    # out of budget for this second; record shortfall
            L = szs[k]
            if fb is not None and mult < 1.0 and krng.random() >= mult:
                held += 1
                continue
            try:
                s.sendto(payloads[L] if L in payloads else bytes(max(L - 28, 1)), (dsts[k % len(dsts)], ports[k % len(ports)]))
                sent_pkts += 1
                sent_bytes += L
                if fb is not None:
                    w = int(time.time())
                    sent_w[w] = sent_w.get(w, 0) + max(L - 28, 1)
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
        if late is not None and i == 0:
            row["late_s"] = late
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        if fb is not None:
            row["mult"] = round(mult, 4)
            row["loss"] = None if last_loss is None else round(last_loss, 4)
            row["held_pkts"] = held
            row["reports"] = nrep[0]
        print(json.dumps(row), flush=True)
    s.close()


def _react(fb, react, mult, last_loss, sent_w, rx_w, eval_w, nrep):
    """drain the DN's receive reports, then one AIMD step on the newest pair of reported seconds"""
    while True:
        try:
            m = json.loads(fb.recv(2048).decode())
            rx_w[int(m["t"])] = int(m["rx"])
            nrep[0] += 1
        except (BlockingIOError, InterruptedError):
            break
        except (ValueError, KeyError, OSError):
            continue
    if not rx_w:
        return mult, last_loss, eval_w
    w = max(rx_w)
    if w == eval_w or (w - 1) not in rx_w:
        return mult, last_loss, eval_w
    sent = sent_w.get(w - 1, 0) + sent_w.get(w, 0)
    if sent >= react.get("min_bytes", 1500):
        loss = 1.0 - (rx_w[w - 1] + rx_w[w]) / sent
        if loss > react.get("thr", 0.05):
            mult = max(react.get("floor", 0.02), mult * react.get("down", 0.7))
        else:
            mult = min(1.0, mult + react.get("up", 0.1))
        last_loss = loss
    else:
        mult = min(1.0, mult + react.get("up", 0.1))   # nothing to judge on: recover
    for k in [k for k in sent_w if k < w - 5]:
        sent_w.pop(k, None)
    for k in [k for k in rx_w if k < w - 5]:
        rx_w.pop(k, None)
    return mult, last_loss, w


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
