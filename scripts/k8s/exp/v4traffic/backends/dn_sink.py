#!/usr/bin/env python3
"""DN-side sinks (v4 plan §6.3) — runs INSIDE the oai-lab-dn container.

Pure stdlib (the DN has python3 but no named/socat/iperf3). Provides the two
services the benign hard-negative counterparts need, so a benign client produces a
real request/response exchange that a SYN flood or a UDP small-packet flood does
NOT (same protocol, same packet sizes — the difference is the completed exchange,
which is the behavioural signal the thesis is after):

  tcp  : accept-and-serve TCP listener (reads a short request, writes a short
         reply, closes) — counterpart target for tcp_shortconn vs a SYN flood.
  dns  : minimal UDP DNS responder (answers A queries with a fixed address) —
         counterpart target for dns_client vs a UDP small-packet flood.
  udpecho : UDP responder bound to 0.0.0.0 (so it serves every DN n6 IP alias),
         replies a short payload to each datagram's sender — the application-layer
         feedback for fan-out destinations (per-destination bidirectionality,
         NOT ICMP-unreachable).

  feedback : receive report of a reactive benign flow, sent to the UE sidecar over the pod network.

Usage (one subcommand, foreground, bounded by --seconds so nothing is left
orphaned): dn_sink.py tcp|dns|udpecho --port P --seconds N
         dn_sink.py feedback --port P --seconds N --ue UE_IP --to SIDECAR_IP:PORT
"""
import socket, struct, sys, threading, time


def serve_tcp(port, deadline):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(128)
    srv.settimeout(0.5)
    while time.monotonic() < deadline:
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        threading.Thread(target=_handle_tcp, args=(c,), daemon=True).start()
    srv.close()


def _handle_tcp(c):
    try:
        c.settimeout(2.0)
        c.recv(256)
        c.sendall(b"ok\n")
    except OSError:
        pass
    finally:
        c.close()


def serve_dns(port, deadline):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.settimeout(0.5)
    while time.monotonic() < deadline:
        try:
            data, addr = s.recvfrom(512)
        except socket.timeout:
            continue
        try:
            s.sendto(_dns_reply(data), addr)
        except OSError:
            pass
    s.close()


def serve_udpecho(port, deadline, reply=b"ok"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.settimeout(0.5)
    while time.monotonic() < deadline:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        try:
            s.sendto(reply, addr)
        except OSError:
            pass
    s.close()


def _dns_reply(q):
    """Echo the question, flags=0x8180 (response, no error), one A answer 172.30.26.10."""
    if len(q) < 12:
        return q
    tid = q[:2]
    # question section runs from offset 12 to the end of QNAME + 4 (QTYPE+QCLASS)
    i = 12
    while i < len(q) and q[i] != 0:
        i += 1 + q[i]
    qend = i + 5                                    # null label + QTYPE(2) + QCLASS(2)
    question = q[12:qend]
    header = tid + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0)
    answer = (b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4)  # name ptr, A, IN, ttl, rdlen
              + socket.inet_aton("172.30.26.10"))
    return header + question + answer


def serve_feedback(port, deadline, ue_ip, to_host, to_port):
    """Receive report for a reactive benign flow (end-to-end runs, 2026-11-13): UDP payload bytes that reached the DN
    from ue_ip to the DN port `port`, per UNIX second, sent once a second to the UE sidecar at to_host:to_port over the
    pod network (out of band: no traffic on the RAN/UPF path, and it still reports 0 while the UE is blocked).
    Report of second w goes out at about w + 1.5 s: {"t": w, "rx": bytes, "pkts": n}."""
    import subprocess, threading, json
    rx, pk, lock = {}, {}, threading.Lock()
    cmd = ["tcpdump", "-Z", "root", "-i", "n6", "-nn", "-tt", "-l", "-q", "src host %s and udp dst port %d" % (ue_ip, port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def _read():
        for line in proc.stdout:
            f = line.split()
            try:
                t, n = int(float(f[0])), int(f[-1])
            except (ValueError, IndexError):
                continue
            with lock:
                rx[t] = rx.get(t, 0) + n; pk[t] = pk.get(t, 0) + 1
    threading.Thread(target=_read, daemon=True).start()
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    w = int(time.time())
    while time.monotonic() < deadline:
        due = w + 1.5 - time.time()
        if due > 0:
            time.sleep(due)
        with lock:
            msg = {"t": w, "rx": rx.pop(w, 0), "pkts": pk.pop(w, 0)}
        try:
            out.sendto(json.dumps(msg).encode(), (to_host, to_port))
        except OSError:
            pass
        w += 1
    proc.terminate()


def main():
    kind = sys.argv[1]
    port = int(sys.argv[sys.argv.index("--port") + 1])
    secs = int(sys.argv[sys.argv.index("--seconds") + 1])
    deadline = time.monotonic() + secs
    if kind == "feedback":                          # dn_sink.py feedback --port P --seconds N --ue IP --to HOST:PORT
        host, to = sys.argv[sys.argv.index("--to") + 1].rsplit(":", 1)
        return serve_feedback(port, deadline, sys.argv[sys.argv.index("--ue") + 1], host, int(to))
    {"tcp": serve_tcp, "dns": serve_dns, "udpecho": serve_udpecho}[kind](port, deadline)


if __name__ == "__main__":
    main()
