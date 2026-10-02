"""Two-pod network checks: Multus interfaces, UDP on every network, SCTP and DNS."""

import ipaddress, json, os, selectors, socket, subprocess, time

cfg = json.load(open("/config/lab.json"))
side = os.environ["SIDE"]
offset = 250 if side == "server" else 251
address = lambda net, n: str(ipaddress.ip_network(net["subnet"]).network_address + n)
interfaces = json.loads(subprocess.check_output(["ip", "-j", "address"], text=True))
for name, net in cfg["networks"].items():
    own = next(i for i in interfaces if i["ifname"] == name)
    assert any(a.get("local") == address(net, offset) for a in own["addr_info"]), name
routes = json.loads(subprocess.check_output(["ip", "-j", "route"], text=True))
assert all(
    r["dev"] == "eth0" for r in routes if r.get("dst") == "default"
), "secondary default route"
assert socket.gethostbyname("kubernetes.default.svc.cluster.local")
assert socket.gethostbyname("oai-lab-db")
assert socket.gethostbyname("oai-gnb-rfsim")
if side == "server":
    sel = selectors.DefaultSelector()
    for name, net in cfg["networks"].items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((address(net, offset), 49000))
        sel.register(sock, selectors.EVENT_READ, name)
    sctp = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_SCTP)
    sctp.bind((address(cfg["networks"]["n2"], offset), 49001))
    sctp.listen(1)
    sel.register(sctp, selectors.EVENT_READ, "sctp")
    seen = set()
    deadline = time.monotonic() + 120
    while len(seen) < 6 and time.monotonic() < deadline:
        for key, _ in sel.select(2):
            if key.data == "sctp":
                conn, _ = key.fileobj.accept()
                assert conn.recv(32) == b"oai-lab"
                conn.sendall(b"ok")
                conn.close()
            else:
                data, peer = key.fileobj.recvfrom(64)
                assert data == b"oai-lab"
                key.fileobj.sendto(b"ok", peer)
            seen.add(key.data)
    assert len(seen) == 6, "secondary/SCTP peers timed out"
else:
    for name, net in cfg["networks"].items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((address(net, offset), 0))
        sock.settimeout(2)
        for attempt in range(30):
            try:
                sock.sendto(b"oai-lab", (address(net, 250), 49000))
                assert sock.recv(32) == b"ok"
                break
            except (socket.timeout, ConnectionRefusedError):
                time.sleep(1)
        else:
            raise RuntimeError("UDP network failed: " + name)
        sock.close()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_SCTP) as sock:
        sock.settimeout(10)
        sock.connect((address(cfg["networks"]["n2"], 250), 49001))
        sock.sendall(b"oai-lab")
        assert sock.recv(32) == b"ok"
print(
    json.dumps(
        {
            "status": "PASS",
            "side": side,
            "interfaces": list(cfg["networks"]),
            "dns": True,
            "sctp": True,
            "secondaryDefaultRoute": False,
        }
    )
)
