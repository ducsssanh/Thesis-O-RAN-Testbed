"""Offline tests for the v4 backends that are pure-Python (pacer, tcp_shortconn,
dns_client) against the DN sink over loopback, plus iperf.py against a stub iperf binary
(timing + unknown-count handling). hping and real iperf2 need their binaries +
the live testbed and are covered by runner.py smoke. Run:

    .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/test_backends.py
"""
import json, socket, subprocess, sys, threading, time, pathlib

HERE = pathlib.Path(__file__).resolve().parent
PY = sys.executable


def _free_port(kind=socket.SOCK_DGRAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _run(script, plan, timeout=20):
    r = subprocess.run([PY, "-I", str(HERE / "backends" / script)], input=json.dumps(plan),
                       text=True, capture_output=True, timeout=timeout)
    rows = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
    if not rows:
        sys.stderr.write(r.stderr)
    return rows


def _sink(kind, port, seconds):
    t = threading.Thread(target=lambda: subprocess.run(
        [PY, "-I", str(HERE / "backends" / "dn_sink.py"), kind, "--port", str(port),
         "--seconds", str(seconds)], capture_output=True, timeout=seconds + 5), daemon=True)
    t.start()
    time.sleep(0.6)
    return t


def test_pacer_rate():
    """pacer realises the byte target within 5% and emits one row per second."""
    port = _free_port()
    # a UDP black-hole receiver so sends succeed
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.bind(("127.0.0.1", port))
    plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [port], "sizes": [[256, 1.0]],
            "process": "even", "seconds": [{"bytes": 1e5, "pps": None}] * 3, "seed": 1}
    rows = _run("pacer.py", plan)
    rx.close()
    assert len(rows) == 3, rows
    mbps = sum(r["sent_bytes"] for r in rows) * 8 / 1e6 / 3
    assert abs(mbps - 0.8) / 0.8 < 0.05, mbps
    print(f"  pacer: {mbps:.3f} Mbit/s (target 0.8), rows={len(rows)}  OK")


def test_dns_roundtrip():
    """dns_client gets answers back from the dn_sink resolver."""
    port = _free_port()
    t = _sink("dns", port, 6)
    plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [port],
            "seconds": [{"pps": 50}] * 3, "seed": 1}
    rows = _run("dns_client.py", plan)
    t.join(timeout=8)
    sent = sum(r["sent_pkts"] for r in rows)
    ans = sum(r.get("answers", 0) for r in rows)
    assert sent >= 100, sent
    assert ans >= 0.8 * sent, (ans, sent)
    print(f"  dns_client: sent={sent} answered={ans}  OK")


def test_tcp_shortconn():
    """tcp_shortconn completes real handshakes against the dn_sink TCP listener."""
    port = _free_port(socket.SOCK_STREAM)
    t = _sink("tcp", port, 6)
    plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [port],
            "seconds": [{"pps": 15}] * 3, "seed": 1}
    rows = _run("tcp_shortconn.py", plan)
    t.join(timeout=8)
    done = sum(r["sent_pkts"] for r in rows)
    failed = sum(r.get("conn_failed", 0) for r in rows)
    assert done >= 30, (done, failed)
    assert failed <= 0.2 * (done + failed), (done, failed)
    print(f"  tcp_shortconn: completed={done} failed={failed}  OK")


def test_row_schema():
    """every backend row has the common achieved-schema fields build_dataset_v4 reads."""
    port = _free_port()
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.bind(("127.0.0.1", port))
    plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [port], "sizes": [[256, 1.0]],
            "process": "even", "seconds": [{"bytes": 5e4}] * 2, "seed": 1,
            "attack_active": [1, 0]}
    rows = _run("pacer.py", plan)
    rx.close()
    need = {"t", "sec", "target_bytes", "sent_bytes", "sent_pkts", "achieved_mbps", "achieved_pps"}
    for r in rows:
        assert need <= set(r), set(r)
    assert rows[0]["attack_active"] == 1 and rows[1]["attack_active"] == 0
    print(f"  row schema + attack_active gate  OK")


_IPERF_STUB = """#!%s
import os, sys, time
a = sys.argv[1:]
assert "--no-udp-fin" in a, a
t = float(a[a.index("-t") + 1])
assert 0.1 <= t <= 1.0, t
if os.environ.get("STUB_HANG"):
    time.sleep(30)
time.sleep(t + 0.08)                         # iperf2 process overhead (measured 0.02-0.08 s)
print("[  1] 0.00-%%.2f sec  100 KBytes  800 Kbits/sec  %%d datagrams" %% (t, int(83 * t)))
"""


def _iperf_run(plan, hang=False, timeout=30):
    import os, tempfile
    d = tempfile.mkdtemp()
    stub = pathlib.Path(d) / "iperf"
    stub.write_text(_IPERF_STUB % PY)
    stub.chmod(0o755)
    env = dict(os.environ, PATH=d + os.pathsep + os.environ.get("PATH", ""))
    if hang:
        env["STUB_HANG"] = "1"
    t0 = time.monotonic()
    r = subprocess.run([PY, "-I", str(HERE / "backends" / "iperf.py")], input=json.dumps(plan),
                       text=True, capture_output=True, timeout=timeout, env=env)
    rows = [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]
    if not rows:
        sys.stderr.write(r.stderr)
    return rows, time.monotonic() - t0


def test_iperf_deadline():
    """iperf blocks stay on the 1 s grid despite process overhead (no drift), pass
    --no-udp-fin, and report the parsed datagram count."""
    plan = {"dst": "127.0.0.1", "ports": [5401], "sizes": [[1228, 1.0]],
            "seconds": [{"bytes": 1e5}] * 8}
    rows, el = _iperf_run(plan)
    assert len(rows) == 8, rows
    assert all(r["sent_pkts"] is not None and r["sent_pkts"] > 0 for r in rows), rows
    assert abs(el - 8) < 0.6, el                       # a fixed -t 1 would take ~8.6 s+
    print(f"  iperf: 8 rows in {el:.2f} s, pkts {[r['sent_pkts'] for r in rows]}  OK")


def test_iperf_unknown_is_none():
    """a hung block (silent victim) logs sent_* = None, never the target; later seconds
    the block overran are skipped (stalled), so the row-coverage guard can see them."""
    plan = {"dst": "127.0.0.1", "ports": [5401], "sizes": [[1228, 1.0]],
            "seconds": [{"bytes": 1e5}] * 4}
    rows, el = _iperf_run(plan, hang=True)
    assert len(rows) == 4, rows
    assert all(r["sent_bytes"] is None and r["achieved_mbps"] is None for r in rows), rows
    assert any(r.get("stalled") for r in rows), rows
    print(f"  iperf hang: 4 rows all sent=None, stalled={sum(r.get('stalled', 0) for r in rows)}  OK")


def test_pacer_reactive():
    """Reactive benign (2026-11-13): a fake DN receives the flow on loopback and reports per UNIX second what got
    through; from second 6 on it lets only 4000 B/s through (a 32 kbit/s policer). The multiplier stays 1 while
    nothing is lost, then backs off; a flow that is never limited stays exactly the plain replay."""
    def run(limit_from):
        port, fbp = _free_port(), _free_port()
        rx, stop = {}, threading.Event()
        sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sink.bind(("127.0.0.1", port)); sink.settimeout(0.2)

        def _recv():
            while not stop.is_set():
                try:
                    n = len(sink.recv(65535))
                except OSError:
                    continue
                w = int(time.time()); rx[w] = rx.get(w, 0) + n

        def _report():
            out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); w = int(time.time()); t0 = w
            while not stop.is_set():
                time.sleep(max(0.0, w + 1.5 - time.time()))
                got = rx.get(w, 0)
                if limit_from is not None and w - t0 >= limit_from:
                    got = min(got, 4000)
                out.sendto(json.dumps({"t": w, "rx": got}).encode(), ("127.0.0.1", fbp)); w += 1
        for f in (_recv, _report):
            threading.Thread(target=f, daemon=True).start()
        plan = {"dst": "127.0.0.1", "ports": [port], "sizes": [[1028, 1.0]], "process": "even",
                "seconds": [{"bytes": 40000.0}] * 14, "seed": 3, "reactive": {"port": fbp}}
        rows = _run("pacer.py", plan, timeout=30)
        stop.set(); sink.close()
        return rows
    free = run(None)
    assert all(r["mult"] == 1.0 and r["held_pkts"] == 0 for r in free), [r["mult"] for r in free]
    lim = run(6)
    m = [r["mult"] for r in lim]
    assert all(x == 1.0 for x in m[:6]), m
    assert min(m[9:]) < 0.5, m
    assert sum(r["sent_bytes"] for r in lim[10:]) < 0.6 * sum(r["sent_bytes"] for r in free[10:]), m


def _lossy_resolver(port, drop, seconds, seed=1):
    """fake DN resolver on loopback that answers (echoes the transaction id) a query with probability 1 - drop"""
    import random
    rnd, stop = random.Random(seed), time.monotonic() + seconds
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", port)); s.settimeout(0.2)

    def _serve():
        while time.monotonic() < stop:
            try:
                d, a = s.recvfrom(512)
            except OSError:
                continue
            if rnd.random() >= drop:
                s.sendto(d[:2] + b"\x81\x80" + d[4:], a)
        s.close()
    threading.Thread(target=_serve, daemon=True).start()


def test_dns_closed_loop():
    """Closed-loop benign DNS client (2026-11-13): sends exactly the schedule while every query is answered; slows
    down when queries are lost (30 % and 100 %: the window shrinks x0.7 per lossy second, the rate falls well below
    the schedule); comes back when the loss stops; the open-loop client (attack flows) keeps sending the schedule at
    100 % loss."""
    cl = {"window": 40, "timeout_s": 1.0}
    def run(drop, closed=True, secs=10, pps=100):
        port = _free_port()
        _lossy_resolver(port, drop, secs + 3)
        plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [port], "seconds": [{"pps": pps}] * secs, "seed": 1}
        if closed:
            plan["closed_loop"] = cl
        return _run("dns_client.py", plan, timeout=secs + 10)
    ok = run(0.0)
    assert all(r["sent_pkts"] == 100 and r["skipped"] == 0 and r["window"] == 40 for r in ok), [(r["sent_pkts"], r["skipped"]) for r in ok]
    assert sum(r["answers"] for r in ok) >= 0.99 * 1000, sum(r["answers"] for r in ok)
    lossy = run(0.3)
    assert sum(r["sent_pkts"] for r in lossy[5:]) < 0.5 * 100 * 5, [r["sent_pkts"] for r in lossy]
    dead = run(1.0)
    assert all(r["sent_pkts"] <= 100 for r in dead), [r["sent_pkts"] for r in dead]
    assert sum(r["sent_pkts"] for r in dead[5:]) < 0.2 * 100 * 5, [(r["sent_pkts"], r["window"]) for r in dead]
    flood = run(1.0, closed=False)
    assert all(r["sent_pkts"] >= 95 for r in flood), [r["sent_pkts"] for r in flood]
    print("  dns closed loop: answered %s/s; 30%% loss %s; 100%% loss %s (window %s); open loop at 100%% loss %s  OK" % (
        [r["sent_pkts"] for r in ok][:3], [r["sent_pkts"] for r in lossy], [r["sent_pkts"] for r in dead],
        [r["window"] for r in dead], [r["sent_pkts"] for r in flood][:3]))


def test_tcp_closed_loop():
    """Closed-loop benign TCP client (2026-11-13): every scheduled connection is opened while the DN sink answers; with
    every exchange timing out (a listener that never answers) the window shrinks x0.7 per second and the client opens far fewer; the
    open-loop client keeps opening the schedule."""
    port = _free_port(socket.SOCK_STREAM)
    t = _sink("tcp", port, 6)
    plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [port], "seconds": [{"pps": 15}] * 3, "seed": 1,
            "closed_loop": {"window": 16}}
    ok = _run("tcp_shortconn.py", plan)
    t.join(timeout=8)
    assert all(r["skipped"] == 0 and r["started"] == 15 for r in ok), [(r["started"], r["skipped"]) for r in ok]
    # a listener that never accepts nor answers: its backlog fills, later SYNs are dropped, every exchange times out
    # after 2 s, as when the UPF drops the flow
    hole = socket.socket(socket.AF_INET, socket.SOCK_STREAM); hole.bind(("127.0.0.1", 0)); hole.listen(0)
    plan = {"dst": "127.0.0.1", "bind": "127.0.0.1", "ports": [hole.getsockname()[1]], "seconds": [{"pps": 15}] * 8, "seed": 1,
            "closed_loop": {"window": 16}}
    dead = _run("tcp_shortconn.py", plan, timeout=20)
    st = [r["started"] for r in dead]
    # failures show 2 s after the SYN (connect timeout), so the window shrinks in steps of two seconds
    assert sum(st[4:]) < 0.5 * sum(st[:4]) and dead[-1]["window"] <= 0.3 * 16, (st, [r["window"] for r in dead])
    plan.pop("closed_loop")
    flood = _run("tcp_shortconn.py", plan, timeout=20)
    hole.close()
    assert all(r["sent_pkts"] == 0 for r in flood) and sum(r["conn_failed"] for r in flood) >= 80, [(r["sent_pkts"], r["conn_failed"]) for r in flood]
    print("  tcp closed loop: started %s with the sink; %s with every exchange timing out (window %s)  OK" % (
        [r["started"] for r in ok], st, [r["window"] for r in dead]))


def test_closed_loop_aimd():
    """The window rule of both closed-loop clients (dns_client.py / tcp_shortconn.py aimd(), 2026-11-13). Regression
    of the fault found in the calibration oran_flooding_e2e_calib4: in a quiet second (5 queries) one answer later
    than the timeout made the loss 1/6 > 5 % and the window went to 0.7 x the peak in flight of that second (1), so
    the burst that followed (lk009 ue1: 1878 queries scheduled) was skipped almost entirely. Now the newest two
    seconds are pooled and judged only with >= 20 outcomes; a cut starts from the peak in flight over the pair."""
    import importlib.util
    for name in ("dns_client", "tcp_shortconn"):
        spec = importlib.util.spec_from_file_location(name, str(HERE / "backends" / (name + ".py")))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        tmo = 1.0 if name == "dns_client" else 2.0
        a = lambda w, prev, cur: m.aimd(w, 198.0, prev, cur, 20, 0.05, 0.7, 0.1, tmo)
        assert a(198.0, (6, 0, 1), (5, 1, 1)) == (198.0, False)                 # quiet pair, 12 outcomes: kept
        assert a(198.0, (0, 0, 0), (0, 0, 0)) == (198.0, False)                 # no outcome: kept
        w, cut = a(1278.0, (929, 0, 300), (41, 61, 102))                        # burst then 61 timeouts: cut from the burst's flight
        assert cut and abs(w - 0.7 * 300) < 1e-9, w
        assert a(100.0, (20, 0, 5), (20, 0, 5)) == (100.0 + 19.8, False)            # clean pair: + 0.1 x base
        # a small window that times out entirely still backs off: need = ceil(window / timeout) outcomes
        assert a(16.0, (0, 8 if tmo == 2.0 else 16, 16), (0, 0, 16))[1], name
        assert abs(a(5.0, (0, 3, 3), (0, 2, 0))[0] - 2.1) < 1e-9                        # 100 % loss: 0.7 x peak 3
        assert a(1.0, (0, 1, 1), (0, 1, 0))[0] == 1.0                           # never below 1
    print("  closed-loop window rule (both clients)  OK")

if __name__ == "__main__":
    for fn in (test_pacer_rate, test_row_schema, test_dns_roundtrip, test_tcp_shortconn,
               test_iperf_deadline, test_iperf_unknown_is_none, test_pacer_reactive, test_dns_closed_loop, test_tcp_closed_loop, test_closed_loop_aimd):
        fn()
    print("all offline backend tests passed")
