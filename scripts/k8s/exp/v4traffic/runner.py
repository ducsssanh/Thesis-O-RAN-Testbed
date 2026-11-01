"""Phase-plan runner (v4 plan §5.1) — executes a per-UE pacer plan on the shared
keepalive sidecar and returns the achieved-per-second rows.

Host-side: copies pacer.py + the plan into the sidecar, runs it, parses its JSON
rows. Both classes use this same path from the same container/egress. Also a
`calibrate_pps` helper for the §3.2 per-backend pps ceiling (small packets).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/runner.py calibrate   # pps + rate sweep
"""
import json, pathlib, subprocess, sys, tempfile, threading, time

CTX = "oai-lab"
HERE = pathlib.Path(__file__).resolve().parent
BACKENDS = {name: (HERE / f"backends/{name}.py").read_text()
            for name in ("pacer", "hping", "iperf", "tcp_shortconn", "dns_client", "synflood")}
DN_SINK = (HERE / "backends/dn_sink.py").read_text()
UES = {"ue1": ("oai-nr-ue", "10.1.0.2"), "ue2": ("oai-nr-ue2", "10.1.0.3")}
DN = "172.30.26.10"
DN_N6 = "172.30.26.10"

# a tiny UDP sink (UE side) so designed DL feedback is absorbed rather than
# answered with ICMP port-unreachable (which would add spurious UL).
_UE_SINK = (
    "import socket,sys,time\n"
    "s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n"
    "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
    "s.bind(('0.0.0.0',int(sys.argv[1])));s.settimeout(0.5)\n"
    "end=time.monotonic()+float(sys.argv[2])\n"
    "while time.monotonic()<end:\n"
    "  try:\n    s.recvfrom(4096)\n  except OSError:\n    pass\n")


def _k(args, inp=None, timeout=120):
    p = subprocess.run(["kubectl", "--context", CTX, *args], input=inp, text=True,
                       capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def _push_backend(dep, backend):
    _k(["-n", "oai-ran", "exec", "-i", f"deploy/{dep}", "-c", "keepalive", "--",
        "sh", "-c", f"cat > /tmp/{backend}.py"], inp=BACKENDS[backend])


def run_backend(dep, plan, timeout=None):
    """Run the plan's backend (default 'pacer') on dep's sidecar; return achieved rows."""
    backend = plan.get("backend", "pacer")
    _push_backend(dep, backend)
    pj = json.dumps(plan)
    rc, out, err = _k(["-n", "oai-ran", "exec", "-i", f"deploy/{dep}", "-c", "keepalive", "--",
                       "sh", "-c", f"cat > /tmp/plan.json && python3 /tmp/{backend}.py /tmp/plan.json"],
                      inp=pj, timeout=timeout or (len(plan["seconds"]) + 30))
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    if not rows and err:
        sys.stderr.write(err)
    return rows


run_pacer = run_backend                              # back-compat alias


# ---- DN-side servers (one attached, timeout-bounded process; no orphans) --------
def _dn_push_sink():
    _k(["-n", "oai-core", "exec", "-i", "deploy/oai-lab-dn", "-c", "dn", "--",
        "sh", "-c", "cat > /tmp/dn_sink.py"], inp=DN_SINK)


def _dn_server_cmd(backend, port, seconds):
    """The DN-side command a backend needs, bounded by `timeout`/--seconds."""
    if backend == "iperf":
        return ["-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
                "timeout", str(seconds), "iperf", "-s", "-u", "-p", str(port)]
    kind = {"tcp_shortconn": "tcp", "dns_client": "dns"}.get(backend)
    if kind:
        return ["-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
                "python3", "/tmp/dn_sink.py", kind, "--port", str(port), "--seconds", str(seconds)]
    return None


# ---- designed DL feedback for benign (§5.5, C2 fix) --------------------------
def gnb_stats_offset():
    """Fraction of the UNIX second at which the gNB rewrites nrMAC_stats.log (its 1 s stats grid)."""
    rc, out, err = _k(["-n", "oai-ran", "exec", "deploy/oai-gnb", "-c", "gnb", "--",
                       "stat", "-c", "%.3Y", "/opt/oai/ran/nrMAC_stats.log"])
    if rc != 0:
        raise RuntimeError("cannot read nrMAC_stats.log: " + err.strip())
    t = float(out.strip())
    return t - int(t)


def start_dl_feedback(ue_dep, ue_ip, port, rate_bytes_s, seconds, seed=7, dl_seconds=None, start_at=None, span=None, rows=None):
    """Downlink feedback DN -> UE at `rate_bytes_s` (a fraction of the UL level),
    so a benign UE has a realistic DL channel. Returns threads to join. A UE-side
    UDP sink on `port` absorbs it; the DN runs the pacer DN -> UE:port.
    Benign twin: dl_seconds = per-second packets of the same real window, sent from start_at;
    `seconds` must then include the lead time up to start_at. The achieved rows go to `rows`."""
    threads = []
    # UE sink (shares the UE netns via the keepalive sidecar)
    _k(["-n", "oai-ran", "exec", "-i", f"deploy/{ue_dep}", "-c", "keepalive", "--",
        "sh", "-c", "cat > /tmp/ue_sink.py"], inp=_UE_SINK)
    t_sink = threading.Thread(target=lambda: _k(
        ["-n", "oai-ran", "exec", f"deploy/{ue_dep}", "-c", "keepalive", "--",
         "timeout", str(seconds + 3), "python3", "/tmp/ue_sink.py", str(port), str(seconds + 2)],
        timeout=seconds + 12), daemon=True)
    t_sink.start()
    threads.append(t_sink)
    # DN pacer: UDP DN_N6 -> ue_ip:port at the feedback rate
    _k(["-n", "oai-core", "exec", "-i", "deploy/oai-lab-dn", "-c", "dn", "--",
        "sh", "-c", "cat > /tmp/pacer.py"], inp=BACKENDS["pacer"])
    plan = {"dst": ue_ip, "bind": DN_N6, "ports": [port], "sizes": [[256, 1.0]],
            "process": "even", "seed": seed,
            "seconds": dl_seconds if dl_seconds is not None else [{"bytes": float(rate_bytes_s), "pps": None}] * seconds}
    if dl_seconds is not None:
        plan.update({"start_at": start_at, "span": span, "process": "poisson"})
    pj = json.dumps(plan)

    def _dn_pacer():
        _, out, _ = _k(["-n", "oai-core", "exec", "-i", "deploy/oai-lab-dn", "-c", "dn", "--",
                        "sh", "-c", "cat > /tmp/dlplan-%d.json && timeout %d python3 /tmp/pacer.py /tmp/dlplan-%d.json" % (port, seconds + 3, port)],
                       inp=pj, timeout=seconds + 12)
        if rows is not None:
            rows.extend(json.loads(x) for x in out.splitlines() if x.startswith("{"))
    t_dn = threading.Thread(target=_dn_pacer, daemon=True)
    t_dn.start()
    threads.append(t_dn)
    return threads


# ---- victim mode (§6.1, C2 fix): silent DROP vs responsive on the DN ---------
def _victim_rule(attacker_ip, proto, dport):
    return ["INPUT", "-s", attacker_ip, "-p", proto, "--dport", str(dport), "-j", "DROP"]


def set_victim_silent(attacker_ip, proto, dport):
    """Silent victim: DROP the attack on the DN so no ICMP-unreachable/RST (no DL)."""
    rule = " ".join(_victim_rule(attacker_ip, proto, dport))
    _dn(f"iptables -C {rule} 2>/dev/null || iptables -I {rule}")


def clear_victim_silent(attacker_ip, proto, dport):
    _dn(f"while iptables -D {' '.join(_victim_rule(attacker_ip, proto, dport))} 2>/dev/null; do :; done")


# ---- congestion intervention (§6.1): tc tbf on the UPF N6 egress -------------
def _upf(cmd):
    return _k(["-n", "oai-core", "exec", "deploy/oai-upf", "-c", "upf", "--", "sh", "-c", cmd])


def set_congestion(rate="6mbit", burst="32kb", latency="50ms", iface="n6"):
    """Shape the UPF N6 egress (DL toward the DN side is n6 tx) to `rate` for a window."""
    _upf(f"tc qdisc replace dev {iface} root tbf rate {rate} burst {burst} latency {latency}")


def clear_congestion(iface="n6"):
    _upf(f"tc qdisc del dev {iface} root 2>/dev/null; true")


# ---- fan-out responsive destinations (§6.3): DN n6 IP aliases ----------------
FANOUT_BASE = 201                                  # alias hosts 172.30.26.201 ..


def start_udpecho_sink(port, seconds):
    """UDP echo responder on the DN (0.0.0.0:port serves every alias) for fan-out
    application-layer replies. Returns the server thread (join at the end)."""
    _dn_push_sink()
    t = threading.Thread(target=lambda: _k(
        ["-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
         "python3", "/tmp/dn_sink.py", "udpecho", "--port", str(port), "--seconds", str(seconds)],
        timeout=seconds + 10), daemon=True)
    t.start()
    time.sleep(1.0)
    return t


def add_dn_aliases(n, base=FANOUT_BASE, iface="n6", net="172.30.26"):
    """Add n IP aliases on the DN N6 so fan-out destinations EXIST and reply (closed
    port -> ICMP-unreachable per dst = per-destination bidirectionality). Idempotent."""
    cmd = "; ".join(f"ip addr add {net}.{base + k}/24 dev {iface} 2>/dev/null" for k in range(n)) + "; true"
    _dn(cmd)


def del_dn_aliases(n, base=FANOUT_BASE, iface="n6", net="172.30.26"):
    cmd = "; ".join(f"ip addr del {net}.{base + k}/24 dev {iface} 2>/dev/null" for k in range(n)) + "; true"
    _dn(cmd)


def _start_dn_server(backend, port, seconds):
    """Launch the DN server in a background thread; returns the thread (join at the end)."""
    cmd = _dn_server_cmd(backend, port, seconds)
    if cmd is None:
        return None
    if backend in ("tcp_shortconn", "dns_client"):
        _dn_push_sink()
    t = threading.Thread(target=lambda: _k(cmd, timeout=seconds + 10), daemon=True)
    t.start()
    time.sleep(1.0)                                  # let the server bind before clients connect
    return t


def run_concurrent(plans, timeout=None):
    """plans: {ue: plan}; run all UEs at once (concurrent-load scenarios)."""
    res = {}
    ts = []
    for ue, plan in plans.items():
        dep = UES[ue][0]
        t = threading.Thread(target=lambda u=ue, d=dep, p=plan: res.__setitem__(u, run_pacer(d, p, timeout)))
        t.start(); ts.append(t)
    for t in ts:
        t.join()
    return res


def run_phase(plans, seconds=None):
    """plans: {ue: plan}. Start the DN server the backend(s) need, run all UEs
    concurrently, then join the server. Assumes all plans share one backend/port."""
    any_plan = next(iter(plans.values()))
    backend = any_plan.get("backend", "pacer")
    port = (any_plan.get("ports") or [5401])[0]
    dur = seconds or len(any_plan["seconds"])
    srv = _start_dn_server(backend, port, dur + 4)
    try:
        res = run_concurrent(plans, timeout=dur + 30)
    finally:
        if srv is not None:
            srv.join(timeout=dur + 12)
    return res


def _plan(bind, size, seconds_targets, process="even", pps=None, ports=None, seed=1, backend="pacer", mode=None):
    secs = [{"bytes": b, "pps": pps} for b in seconds_targets]
    plan = {"dst": DN, "bind": bind, "ports": ports or [5401], "sizes": [[size, 1.0]],
            "process": process, "seconds": secs, "seed": seed, "backend": backend}
    if mode:
        plan["mode"] = mode
    return plan


CAL_PORT = 5401
_DN_RULE = ["INPUT", "-p", "udp", "--dport", str(CAL_PORT), "-j", "DROP"]


def _dn(cmd):
    return _k(["-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--", "sh", "-c", cmd])


def dn_counter_install():
    """Silent sink on the DN: DROP+count udp/CAL_PORT (IP-level pkts/bytes, no ICMP back)."""
    rule = " ".join(_DN_RULE)
    _dn(f"iptables -C {rule} 2>/dev/null || iptables -I {rule}")


def dn_counter_remove():
    _dn(f"while iptables -D {' '.join(_DN_RULE)} 2>/dev/null; do :; done")


def dn_counter_read():
    """(pkts, bytes) on the DN rule — IP length incl. headers, same unit as the pacer."""
    _, out, _ = _dn("iptables -nvxL INPUT")
    for line in out.splitlines():
        f = line.split()
        if len(f) > 2 and f[2] == "DROP" and f"dpt:{CAL_PORT}" in line:
            return int(f[0]), int(f[1])
    return 0, 0


def _measure(plan, dep="oai-nr-ue"):
    """Run plan; return sent (pacer) and delivered (DN counter) rates over the run."""
    p0, b0 = dn_counter_read()
    rows = run_pacer(dep, plan)
    time.sleep(3)                                   # let queued packets drain before the read
    p1, b1 = dn_counter_read()
    dur = len(plan["seconds"])
    sent_p = sum(r["sent_pkts"] or 0 for r in rows)
    sent_b = sum(r["sent_bytes"] or 0 for r in rows)
    return {"secs_logged": len(rows),
            "sent_pps": round(sent_p / dur, 1), "sent_mbps": round(sent_b * 8 / 1e6 / dur, 4),
            "dlv_pps": round((p1 - p0) / dur, 1), "dlv_mbps": round((b1 - b0) * 8 / 1e6 / dur, 4),
            "loss_pct": round(100 * (1 - (p1 - p0) / sent_p), 2) if sent_p else None}


def calibrate_pps(dur=8):
    """Per the plan §3.2: push small (64 B) and large (1228 B) packets to find the pps
    ceiling and the rate linear region, single UE (ue1). Delivery is counted on the DN
    (the pacer's own numbers are only what left the socket)."""
    out = {"host": "oai-lab", "dur_s": dur, "unit": "IP bytes", "pps_small_64B": [], "rate_1228B": []}
    dn_counter_install()
    try:
        for target_pps in (500, 1000, 2000, 4000, 8000, 12000, 16000):
            plan = _plan("10.1.0.2", 64, [None] * dur, pps=target_pps, ports=[CAL_PORT])
            r = {"target_pps": target_pps, **_measure(plan)}
            out["pps_small_64B"].append(r); print(json.dumps(r), flush=True)
        for mbps in (0.4, 0.8, 1.2, 2.0, 4.0, 8.0, 10.0, 12.0):
            plan = _plan("10.1.0.2", 1228, [mbps * 1e6 / 8] * dur, ports=[CAL_PORT])
            r = {"offered_mbps": mbps, **_measure(plan)}
            out["rate_1228B"].append(r); print(json.dumps(r), flush=True)
    finally:
        dn_counter_remove()
    return out


def smoke(dur=5):
    """Short live check of every backend from ue1 (both classes share this path).
    Each runs a flat ~0.8 Mbit/s-equivalent schedule for `dur` s; prints a one-line
    summary per backend (sent vs the DN-counted delivery where it applies)."""
    cases = [
        ("pacer",         _plan("10.1.0.2", 256, [1e5] * dur, process="poisson", ports=[5401])),
        ("hping-udp",     _plan("10.1.0.2", 256, [1e5] * dur, backend="hping", mode="udp", ports=[5401])),
        ("hping-syn",     _plan("10.1.0.2", 60, [None] * dur, pps=100, backend="hping", mode="syn", ports=[5402])),
        ("iperf-udp",     _plan("10.1.0.2", 1228, [1e5] * dur, backend="iperf", ports=[5401])),
        ("tcp_shortconn", _plan("10.1.0.2", 0, [None] * dur, pps=20, backend="tcp_shortconn", ports=[5402])),
        ("dns_client",    _plan("10.1.0.2", 0, [None] * dur, pps=50, backend="dns_client", ports=[5353])),
    ]
    out = []
    for name, plan in cases:
        port = plan["ports"][0]
        udp_counted = plan.get("backend") in (None, "pacer", "hping", "iperf") and plan.get("mode") != "syn"
        if udp_counted:
            dn_counter_install()
            p0, b0 = dn_counter_read()
        srv = _start_dn_server(plan.get("backend", "pacer"), port, dur + 6)
        rows = run_backend("oai-nr-ue", plan, timeout=dur + 30)
        time.sleep(2)
        rec = {"backend": name, "secs": len(rows),
               "sent_pps": round(sum(r["sent_pkts"] or 0 for r in rows) / dur, 1) if rows else 0,
               "sent_mbps": round(sum(r["sent_bytes"] or 0 for r in rows) * 8 / 1e6 / dur, 3) if rows else 0}
        if udp_counted:
            p1, b1 = dn_counter_read()
            rec["dlv_pps"] = round((p1 - p0) / dur, 1)
            dn_counter_remove()
        if any("answers" in r for r in rows):
            rec["answers"] = sum(r.get("answers", 0) for r in rows)
        if any("conn_failed" in r for r in rows):
            rec["conn_completed"] = sum(r["sent_pkts"] or 0 for r in rows)
            rec["conn_failed"] = sum(r.get("conn_failed", 0) for r in rows)
        if srv is not None:
            srv.join(timeout=dur + 10)
        out.append(rec)
        print(json.dumps(rec), flush=True)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "calibrate":
        r = calibrate_pps()
        pathlib.Path("research/testbed/calib_pps_v4.json").write_text(json.dumps(r, indent=2) + "\n")
    elif cmd == "smoke":
        smoke()
    else:
        print(__doc__)
