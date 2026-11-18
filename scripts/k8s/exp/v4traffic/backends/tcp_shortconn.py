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

Closed loop (plan "closed_loop": {window, down, up, loss_thr}, benign only, 2026-11-13): like a client with a
connection pool, at most the current window of connections are open at once; a scheduled connection that finds no free
slot is skipped (counted). The window adapts once per second as the reactive benign pacer does (AIMD): share of
connections ending in failure (timeout 2 s, refused) > loss_thr (0.05) over the newest two seconds -> window = down
(0.7) x min(window, the most open in those seconds), at least 1; else + up (0.1) x the base window, at most the base;
a pair of seconds with fewer than max(2, min(min_outcomes 20, ceil(window / 2 s))) connections ending keeps the
window (aimd()). With every exchange completing
the client opens exactly the schedule; when the network drops its packets it slows down. Without the key it is open
loop (one thread per scheduled connection whatever happens), as the attack flows.
"""
import json, math, socket, sys, threading, time

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


def aimd(w, base, prev, cur, mino, thr, down, up, tmo):
    """the window after a second (2026-11-13, same rule as dns_client.py aimd(), as the reactive pacer pacer.py: the
    newest two seconds pooled, decided only when the pair carried >= need = max(2, min(mino, ceil(window / timeout))) outcomes
    (a window that times out entirely gives about window / timeout outcomes a second), else the window is kept):
    loss = failed / outcomes of the pair; loss > thr -> down x min(window, peak in flight over the pair), at least 1;
    else + up x base, at most base. prev / cur: (completed, failed, peak in flight). Returns (window, cut)."""
    ok, lost = prev[0] + cur[0], prev[1] + cur[1]
    need = max(2, min(mino, math.ceil(w / tmo)))   # a full window times out at most w / tmo times a second
    if ok + lost < need:
        return w, False
    if lost / (ok + lost) > thr:
        return max(1.0, down * min(w, max(prev[2], cur[2], 1))), True
    return min(base, w + up * base), False


class Pool:
    """closed-loop slots: a connection holds one from start to end; the window adapts per second (AIMD)"""
    def __init__(self, cl):
        self.base = float(cl.get("window", 16)); self.w = self.base
        self.down, self.up, self.thr = float(cl.get("down", 0.7)), float(cl.get("up", 0.1)), float(cl.get("loss_thr", 0.05))
        self.mino = int(cl.get("min_outcomes", 20))
        self.lock, self.busy, self.peak = threading.Lock(), 0, 0
        self.prev = (0, 0, 0)                       # (completed, failed, peak busy) of the previous second

    def try_take(self):
        with self.lock:
            if self.busy >= max(1, int(self.w)):
                return False
            self.busy += 1; self.peak = max(self.peak, self.busy)
            return True

    def run(self, dst, port, bind, stats):
        try:
            _one_conn(dst, port, bind, stats)
        finally:
            with self.lock:
                self.busy -= 1

    def second(self, completed, failed):
        """end of a second: adapt the window (aimd(): the newest two seconds pooled, decided only with >= min_outcomes
        outcomes, as dns_client.py); returns the window used in that second, its loss and whether the window was cut"""
        with self.lock:
            w0, n = self.w, completed + failed
            loss = failed / n if n else 0.0
            cur = (completed, failed, self.peak)
            self.w, cut = aimd(self.w, self.base, self.prev, cur, self.mino, self.thr, self.down, self.up, 2.0)
            self.prev, self.peak = cur, self.busy
            return w0, loss, cut


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
    cl = p.get("closed_loop")
    pool = Pool(cl if isinstance(cl, dict) else {}) if cl else None
    for i, sec in enumerate(p["seconds"]):
        n = int(sec["pps"]) if sec.get("pps") else int(round(float(sec.get("bytes") or 0.0) / BYTES_PER_CONN))
        t_start = mono0 + i
        ts, skipped = [], 0
        for k in range(n):
            due = t_start + (k + 0.5) / n if n else t_start
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            elif now - t_start >= 1.0:
                break
            if pool is not None:
                if not pool.try_take():
                    skipped += 1; continue
                th = threading.Thread(target=pool.run, args=(dst, port, bind, stats), daemon=True)
            else:
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
        if pool is not None:
            w0, loss, cut = pool.second(completed, failed)
            row.update(closed_loop=True, window=round(w0, 2), inflight=pool.busy, timeouts=failed, skipped=skipped, started=len(ts),
                       loss=round(loss, 4), cut=cut)
        gate = p.get("attack_active")
        if gate is not None and i < len(gate):
            row["attack_active"] = int(gate[i])
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
