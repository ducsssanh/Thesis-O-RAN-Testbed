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


if __name__ == "__main__":
    for fn in (test_pacer_rate, test_row_schema, test_dns_roundtrip, test_tcp_shortconn,
               test_iperf_deadline, test_iperf_unknown_is_none):
        fn()
    print("all offline backend tests passed")
