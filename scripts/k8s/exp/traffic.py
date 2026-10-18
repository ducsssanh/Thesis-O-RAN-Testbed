"""Traffic and live probes of one run: iperf2 UDP flows with per-second
receiver reports, a per-second packet counter on the DN's N6, a PFCP
capture on the SMF's N4 and a 1 s recorder of the defense state."""
import json
import re
import threading
import time

from lab import DN_IP, UES, ex, popen_ex, defense_state

RATE = re.compile(r"^(\d+(?:\.\d+)?)([kKmMgG]?)$")


def rate_bps(text):
    m = RATE.match(str(text))
    if not m:
        raise ValueError("bad rate " + str(text))
    # iperf2: upper-case suffixes are binary (1M = 2^20 bit/s), lower-case decimal
    return float(m.group(1)) * {"": 1, "k": 1e3, "K": 2**10, "m": 1e6, "M": 2**20, "g": 1e9, "G": 2**30}[m.group(2)]


def parse_iperf_row(line):
    """iperf2 -y C -e receiver row -> dict (None for other lines)."""
    f = line.strip().split(",")
    if len(f) < 14 or "-" not in f[6]:
        return None
    ts = f[0].split(":", 1)[-1]  # "+0000:YYYYmmddHHMMSS.mmm" or "YYYYmmddHHMMSS"
    try:
        t = time.mktime(time.strptime(ts.split(".")[0], "%Y%m%d%H%M%S")) - time.timezone
        t += float("0." + ts.split(".")[1]) if "." in ts else 0
        a, b = (float(x) for x in f[6].split("-"))
        return {"t": round(t, 3), "interval": [a, b], "bytes": int(f[7]), "bps": float(f[8]), "jitter_ms": float(f[9] or 0),
                "lost": int(f[10]), "total": int(f[11]), "final": a == 0 and b - a > 1.5}
    except (ValueError, IndexError):
        return None


class Flow:
    """One UDP flow UE->DN (ul) or DN->UE (dl); the receiver streams 1 s rows."""

    def __init__(self, ue, direction, rate, length, duration, port, ip):
        self.ue, self.dir, self.rate, self.length, self.duration, self.port, self.ip = ue, direction, rate, length, duration, port, ip
        self.rows, self.client_out, self.started = [], "", None
        self._srv = self._cli = None
        self._threads = []

    def start_server(self):
        deploy = UES[self.ue][0]
        t = str(self.duration + 15)
        if self.dir == "ul":
            self._srv = popen_ex("oai-core", "oai-lab-dn", "dn", "timeout", "-s", "INT", t, "iperf", "-s", "-u", "-p", str(self.port),
                                 "-i", "1", "-y", "C", "-e")
        else:
            self._srv = popen_ex("oai-ran", deploy, "nr-ue", "timeout", "-s", "INT", t, "iperf", "-s", "-u", "-B", self.ip, "-p",
                                 str(self.port), "-i", "1", "-y", "C", "-e")
        self._threads.append(threading.Thread(target=self._read, daemon=True))
        self._threads[-1].start()

    def start_client(self):
        deploy = UES[self.ue][0]
        self.started = time.time()
        if self.dir == "ul":
            cmd = ("oai-ran", deploy, "nr-ue", "iperf", "-c", DN_IP, "-B", self.ip)
        else:
            cmd = ("oai-core", "oai-lab-dn", "dn", "iperf", "-c", self.ip)
        self._cli = popen_ex(*cmd, "-u", "-b", str(self.rate), "-l", str(self.length), "-t", str(self.duration), "-p", str(self.port))

    def _read(self):
        for line in self._srv.stdout:
            r = parse_iperf_row(line)
            if r:
                self.rows.append(r)

    def stop(self):
        """Stop the client early (stop_when); the receiver ends by itself."""
        if self._cli and self._cli.poll() is None:
            deploy = UES[self.ue][0]
            if self.dir == "ul":
                ex("oai-ran", deploy, "nr-ue", "pkill", "-INT", "-f", "iperf -c %s" % DN_IP, check=False)
            else:
                ex("oai-core", "oai-lab-dn", "dn", "pkill", "-INT", "-f", "iperf -c %s" % self.ip, check=False)

    def finish(self, timeout=30):
        if self._cli:
            try:
                self.client_out = self._cli.communicate(timeout=self.duration + 30)[0] or ""
            except Exception:
                self._cli.kill()
        # the receiver prints its final row when the client's FIN arrives or at the timeout
        deadline = time.time() + timeout
        while self._srv.poll() is None and time.time() < deadline:
            time.sleep(0.5)
        if self._srv.poll() is None:
            self._srv.terminate()
        for t in self._threads:
            t.join(timeout=5)

    def summary(self):
        per_s = [r for r in self.rows if not r["final"]]
        fin = next((r for r in reversed(self.rows) if r["final"]), None)
        rx = sum(r["bytes"] for r in per_s)
        span = max(len(per_s), 1)
        return {"ue": self.ue, "dir": self.dir, "offered_bps": rate_bps(self.rate), "payload_bytes": self.length,
                "port": self.port, "started": self.started, "rx_bytes": rx, "rx_mbps_mean": round(rx * 8 / span / 1e6, 4),
                "seconds_with_data": len(per_s),
                "loss_pct": round(100.0 * fin["lost"] / fin["total"], 3) if fin and fin["total"] else None}


class DnCounter:
    """Per-second packets/bytes per UE address at the DN's N6 (tcpdump headers
    aggregated inside the pod, so only a small CSV leaves it)."""

    AGG = r"""
import sys,collections
c=collections.Counter();b=collections.Counter()
for line in sys.stdin:
    f=line.split()
    if len(f)<6 or f[1]!='IP':continue
    try:
        t=int(float(f[0]));src='.'.join(f[2].split('.')[:4]);dst='.'.join(f[4].rstrip(':').split('.')[:4])
        n=int(f[-1])
    except ValueError:continue
    if src.startswith('10.1.'):k=(t,src,'ul')
    elif dst.startswith('10.1.'):k=(t,dst,'dl')
    else:continue
    c[k]+=1;b[k]+=n
print('t,ue_ip,dir,pkts,ip_payload_bytes')
for k in sorted(c):print('%d,%s,%s,%d,%d'%(k[0],k[1],k[2],c[k],b[k]))
"""

    def __init__(self, seconds):
        self.seconds = seconds
        self.csv = ""

    def start(self):
        # the aggregator reaches python as $0 of sh -c: no quoting of the script needed
        script = "timeout -s INT %d tcpdump -Z root -i n6 -nn -tt -l -q 'net 10.1.0.0/16' 2>/dev/null | python3 -c \"$0\"" % self.seconds
        self._p = popen_ex("oai-core", "oai-lab-dn", "dn", "sh", "-c", script, self.AGG)

    def stop(self):
        ex("oai-core", "oai-lab-dn", "dn", "pkill", "-INT", "-f", "tcpdump -Z root -i n6", check=False)
        try:
            self.csv = self._p.communicate(timeout=60)[0] or ""
        except Exception:
            self._p.kill()


class PfcpCapture:
    """tcpdump on N4 in the SMF's capture container; parsed with tshark there."""

    def __init__(self, tag, seconds):
        self.path = "/tmp/exp-%s.pcap" % tag
        self.seconds = seconds

    def start(self):
        self._p = popen_ex("oai-core", "oai-smf", "capture", "timeout", "-s", "INT", str(self.seconds), "tcpdump", "-i", "n4",
                           "-U", "-w", self.path, "udp", "port", "8805")

    def stop(self):
        ex("oai-core", "oai-smf", "capture", "pkill", "-INT", "-f", self.path, check=False)
        try:
            self._p.communicate(timeout=30)
        except Exception:
            self._p.kill()

    def fields(self, display_filter, names):
        cmd = ["tshark", "-r", self.path, "-Y", display_filter, "-T", "fields", "-E", "separator=,", "-E", "header=y",
               "-E", "occurrence=a", "-E", "aggregator=;"]
        for n in names:
            cmd += ["-e", n]
        return ex("oai-core", "oai-smf", "capture", *cmd, timeout=120, check=False)

    def raw(self):
        return ex("oai-core", "oai-smf", "capture", "base64", "-w0", self.path, timeout=120, check=False)

    def cleanup(self):
        ex("oai-core", "oai-smf", "capture", "rm", "-f", self.path, check=False)


class StateRecorder(threading.Thread):
    """Defense state every ~1 s (levels, rates, UPF policy in force, timers)."""

    KEYS = ("level", "peak", "pending", "class", "amf_ue_ngap_id", "applied_ratio", "rate_ul_kbps", "rate_dl_kbps",
            "core_want", "core_applied", "core_verified", "ran_hit_age_s", "core_hit_age_s", "expires_in_s", "probation_s")

    def __init__(self, period=1.0):
        super().__init__(daemon=True)
        self.period, self.rows, self.stop_flag, self.errors = period, [], False, 0

    def run(self):
        while not self.stop_flag:
            t0 = time.time()
            try:
                st = defense_state()
                self.rows.append({"t": round(t0, 3), "ues": {u["supi"]: {k: u.get(k) for k in self.KEYS} for u in st.get("ues", [])}})
            except Exception:
                self.errors += 1
            time.sleep(max(0.0, self.period - (time.time() - t0)))

    def level(self, supi):
        for r in reversed(self.rows):
            if supi in r["ues"]:
                return r["ues"][supi].get("level") or 0
        return 0

    def jsonl(self):
        return "".join(json.dumps(r) + "\n" for r in self.rows)
