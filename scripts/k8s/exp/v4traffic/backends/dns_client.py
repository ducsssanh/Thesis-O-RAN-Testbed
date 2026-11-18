#!/usr/bin/env python3
"""DNS query client (v4 plan §6.3) — runs in the UE keepalive sidecar. The benign
hard-negative counterpart to a UDP small-packet flood: small UDP packets at a
paced/bursty rate, same size class as a 64-byte flood, but each query gets an
answer back from the DN resolver (dn_sink.py dns) — a completed request/response
exchange, which the flood lacks. Query arrivals follow the per-second schedule.

Plan: pacer-shaped; per-second target is a QUERY COUNT (from "pps" else
bytes / mean query size). Needs dn_sink.py dns running on the DN.

Closed loop (plan "closed_loop": {window, timeout_s, down, up, loss_thr}, benign only, 2026-11-13): a real resolver
client waits for its answers and limits what it has outstanding. A scheduled query is sent only while fewer than the
current window are outstanding, else it is skipped (counted); a query without an answer after timeout_s is lost. The
window adapts once per second as the reactive benign pacer does (AIMD, aimd()): lost share over the newest two
seconds > loss_thr (0.05) -> window = down (0.7) x min(window, the most outstanding in those seconds), at least 1;
else + up (0.1) x the base window, at most the base; a pair with fewer than max(2, min(min_outcomes 20,
ceil(window / timeout_s))) answers and losses keeps the window. With every answer back in time the client sends exactly the schedule; when the network drops its queries it
slows down. Without the key the client is open loop (sends the schedule whatever comes back), as the attack flows.
"""
import json, math, socket, struct, sys, time

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

    if p.get("start_at"):
        wait = p["start_at"] - time.time()
        if wait > 0:
            time.sleep(wait)
    start = time.clock_gettime(time.CLOCK_REALTIME)
    mono0 = time.monotonic()
    if p.get("closed_loop"):
        return closed_loop(p, s, dst, port, pkt_len, start, mono0)
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


def aimd(w, base, prev, cur, mino, thr, down, up, tmo):
    """the window after a second (2026-11-13, as the reactive pacer pacer.py: the newest two seconds pooled, decided
    only when the pair carried >= need = max(2, min(mino, ceil(window / timeout))) outcomes, a window that times out
    entirely giving about window / timeout outcomes a second; else the window is kept): loss = timeouts / outcomes;
    loss > thr -> down x min(window, peak in flight over the pair), at least 1; else + up x base, at most base.
    prev / cur: (answers, timeouts, peak in flight) of the previous / this second. Returns (window, cut)."""
    ans, lost = prev[0] + cur[0], prev[1] + cur[1]
    need = max(2, min(mino, math.ceil(w / tmo)))   # a full window times out at most w / tmo times a second
    if ans + lost < need:
        return w, False
    if lost / (ans + lost) > thr:
        return max(1.0, down * min(w, max(prev[2], cur[2], 1))), True
    return min(base, w + up * base), False


def closed_loop(p, s, dst, port, pkt_len, start, mono0):
    cl = p["closed_loop"] if isinstance(p["closed_loop"], dict) else {}
    base, tmo = float(cl.get("window", 16)), float(cl.get("timeout_s", 1.0))
    down, up, thr = float(cl.get("down", 0.7)), float(cl.get("up", 0.1)), float(cl.get("loss_thr", 0.05))
    mino = int(cl.get("min_outcomes", 20))
    w, pending, tid = base, {}, 0                   # current window; tid -> send time
    st = {"ans": 0, "tmo": 0}
    prev = (0, 0, 0)                                # (answers, timeouts, peak in flight) of the previous second

    def service(now):
        try:                                        # answers: the DN resolver echoes the transaction id
            while True:
                d = s.recv(512)
                if len(d) >= 2 and pending.pop(struct.unpack(">H", d[:2])[0], None) is not None:
                    st["ans"] += 1
        except OSError:
            pass
        for k in [k for k, t in pending.items() if now - t > tmo]:
            del pending[k]; st["tmo"] += 1

    for i, sec in enumerate(p["seconds"]):
        n = int(sec["pps"]) if sec.get("pps") else int(round(float(sec.get("bytes") or 0.0) / pkt_len))
        t_start = mono0 + i
        sent = skipped = 0
        peak = len(pending)                         # in flight: carried over from the previous second too
        a0, t0 = st["ans"], st["tmo"]
        for k in range(n):
            due = t_start + (k + 0.5) / n
            while True:                             # wait for the due time, serving answers meanwhile
                now = time.monotonic()
                service(now)
                if due <= now:
                    break
                time.sleep(min(0.005, due - now))
            if now - t_start >= 1.0:
                break
            if len(pending) >= max(1, int(w)):
                skipped += 1; continue
            tid = (tid + 1) & 0xFFFF
            try:
                s.sendto(_query(tid), (dst, port)); pending[tid] = now; sent += 1
            except OSError:
                skipped += 1
            peak = max(peak, len(pending))
        while time.monotonic() < mono0 + i + 1:
            service(time.monotonic()); time.sleep(0.005)
        ans, lost = st["ans"] - a0, st["tmo"] - t0
        loss = lost / (ans + lost) if ans + lost else 0.0
        w0, w, cut = w, *aimd(w, base, prev, (ans, lost, peak), mino, thr, down, up, tmo)
        prev = (ans, lost, peak)
        sent_bytes = sent * pkt_len
        row = {"t": round(start + i, 3), "sec": i, "backend": "dns_client",
               "target_bytes": round(float(sec.get("bytes") or 0.0), 1), "target_pkts": n,
               "sent_bytes": sent_bytes, "sent_pkts": sent, "answers": ans,
               "achieved_mbps": round(sent_bytes * 8 / 1e6, 4), "achieved_pps": sent,
               "closed_loop": True, "window": round(w0, 2), "inflight": len(pending), "timeouts": lost, "skipped": skipped,
               "loss": round(loss, 4), "cut": cut}
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)
    s.close()

if __name__ == "__main__":
    main()
