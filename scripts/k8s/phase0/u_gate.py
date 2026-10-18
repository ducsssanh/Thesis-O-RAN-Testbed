#!/usr/bin/env python3
"""Gate U (plan Phase U): per-SUPI block / ratelimit / monitor in the eBPF UPF.

Usage: u_gate.py <out-dir> [--phases block,reconnect,ratelimit,monitor,limits,restart,delete]

Prerequisite: UPF image with C35 and global.lab.defense.upfSecurity.enabled,
both UEs attached (oai-nr-ue, oai-nr-ue2). The API is called from the xApp
pod (near-rt-ric -> Service oai-upf-security.oai-core), the path the xApp
will use in L1; the xApp RAN defense is switched off during the gate and
restored at the end. Packets reaching the DN are counted with tcpdump on its
N6 interface (src net of the UEs), so "blocked" means none of the UE's
packets left the UPF; sec_stats proves the UE kept sending.

Phases and checks:
  block      PUT block UE1 while both UEs send UL: UE1's last packet at the DN
             <= 1 s after the PUT returned, UE2 keeps flowing, DL to UE1 gets
             nothing, sec_stats drop counters grow, rules_match_pdr unchanged,
             no SMF error lines.
  reconnect  UE1 pod restarted under the block: new SEID enforced, not one
             packet from UE1's new session at the DN although it sends.
  ratelimit  PUT ratelimit 500 kbit/s UL+DL, UE1 offers 2 Mbit/s UL: DN rate
             limited (0.15-0.75 Mbit/s; v1 is minimal, outer bytes counted).
  monitor    PUT monitor: no drop (DN rate >= 85 % of offered), seen counters grow.
  limits     2nd block (ratio 1.0 > 0.5) -> 403; ttl > maxTtlS -> 403;
             burst over maxCmdsPerS -> 429.
  restart    PUT block UE1, UEs to 0, lab.sh restart-upf, UEs back: boot_id
             changed, policy reloaded from SQLite, UE1's new session blocked.
  delete     DELETE UE1: UL reaches the DN again (>= 85 % of offered).
"""
import json
import pathlib
import subprocess
import sys
import threading
import time

CTX = "oai-lab"
ROOT = pathlib.Path(__file__).resolve().parents[3]
DN = "172.30.26.10"
API = "http://oai-upf-security.oai-core.svc.cluster.local:8095"
UE1, UE2 = "oai-nr-ue", "oai-nr-ue2"
SUPI = {UE1: "imsi-001010123456780", UE2: "imsi-001010123456781"}
PORT = {UE1: 5201, UE2: 5202}
ALL_PHASES = ["block", "reconnect", "ratelimit", "monitor", "limits", "restart", "delete"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def kubectl(*args, timeout=60, check=True):
    return subprocess.run(["kubectl", "--context", CTX, *args], check=check, capture_output=True, errors="replace",
                          text=True, timeout=timeout).stdout


def ex(ns, dep, ctr, *cmd, timeout=60, check=True):
    return kubectl("-n", ns, "exec", "deploy/" + dep, "-c", ctr, "--", *cmd, timeout=timeout, check=check)


# Requests run in the xApp pod; t is the pod's time.time() when the reply arrived.
API_CODE = """
import json,sys,time,urllib.request,urllib.error
out=[]
for m,p,b in json.loads(sys.argv[1]):
    r=urllib.request.Request(sys.argv[2]+p,data=(json.dumps(b).encode() if b is not None else None),method=m)
    try:
        s=urllib.request.urlopen(r,timeout=10);out.append([s.status,json.loads(s.read() or b'{}'),time.time()])
    except urllib.error.HTTPError as e:
        out.append([e.code,json.loads(e.read() or b'{}'),time.time()])
print(json.dumps(out))
"""


def api_many(reqs):
    out = ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", API_CODE, json.dumps(reqs), API, timeout=60)
    return json.loads(out.strip().splitlines()[-1])


def api(method, path, body=None):
    return api_many([[method, path, body]])[0]


def defense_enabled(on):
    code = ("import json,urllib.request as u;print(u.urlopen(u.Request('http://127.0.0.1:8090/v1/defense/enabled',"
            "data=json.dumps({'enabled':%s}).encode(),method='POST'),timeout=10).read().decode())" % ("True" if on else "False"))
    return ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", code, check=False)


def ue_ip(dep, wait=0):
    t_end = time.time() + wait
    while True:
        out = ex("oai-ran", dep, "nr-ue", "ip", "-4", "-br", "addr", "show", "oaitun_ue1", check=False, timeout=20)
        f = out.split()
        if len(f) >= 3 and "/" in f[2]:
            ip = f[2].split("/")[0]
            ex("oai-ran", dep, "nr-ue", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1", check=False)
            return ip
        if time.time() > t_end:
            return None
        time.sleep(2)


class Capture:
    """tcpdump on the DN's N6: every packet from the UE subnet, epoch timestamps."""

    def __init__(self, dur):
        self.p = subprocess.Popen(["kubectl", "--context", CTX, "-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
                                   "timeout", "-s", "INT", str(dur), "tcpdump", "-Z", "root", "-i", "n6", "-nn", "-tt", "-l",
                                   "src net 10.1.0.0/16"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(2)

    def packets(self):
        out, _ = self.p.communicate(timeout=600)
        pk = []
        for line in out.splitlines():
            f = line.split()
            if len(f) > 3 and f[1] == "IP":
                pk.append((float(f[0]), ".".join(f[2].split(".")[:4])))
        return pk


def iperf_ul(dep, ip, rate, dur, port=None):
    """UE -> DN UDP; returns the DN receiver's Mbit/s (None if nothing arrived)."""
    port = port or PORT[dep]
    srv = subprocess.Popen(["kubectl", "--context", CTX, "-n", "oai-core", "exec", "deploy/oai-lab-dn", "-c", "dn", "--",
                            "timeout", "-k", "5", str(dur + 10), "iperf", "-s", "-u", "-p", str(port), "-y", "C"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(2)
    ex("oai-ran", dep, "nr-ue", "iperf", "-c", DN, "-B", ip, "-u", "-b", rate, "-l", "1200", "-t", str(dur), "-p", str(port),
       timeout=dur + 30, check=False)
    out, _ = srv.communicate(timeout=dur + 30)
    best = None
    for line in out.splitlines():
        f = line.strip().split(",")
        if len(f) >= 9:
            best = round(float(f[8]) / 1e6, 3)
    return best


def iperf_dl(dep, ip, rate, dur, port=5203):
    srv = subprocess.Popen(["kubectl", "--context", CTX, "-n", "oai-ran", "exec", "deploy/" + dep, "-c", "nr-ue", "--",
                            "timeout", "-k", "3", str(dur + 6), "iperf", "-s", "-u", "-B", ip, "-p", str(port), "-y", "C"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    time.sleep(2)
    ex("oai-core", "oai-lab-dn", "dn", "iperf", "-c", ip, "-u", "-b", rate, "-l", "1200", "-t", str(dur), "-p", str(port),
       timeout=dur + 30, check=False)
    out, _ = srv.communicate(timeout=dur + 30)
    best = None
    for line in out.splitlines():
        f = line.strip().split(",")
        if len(f) >= 9:
            best = round(float(f[8]) / 1e6, 3)
    return best


def stats(supi):
    s = api("GET", "/v1/stats?supi=" + supi)[1]["stats"]
    return s[0]["total"] if s else {}


def policy(supi):
    return api("GET", "/v1/ues/" + supi)


def rules_dump():
    """rules_match_pdr of the live UPF (bpftool on the host kernel; old pods' maps are gone)."""
    bt = [str(ROOT / "scripts/k8s/phase0/bpftool.sh")]
    maps = json.loads(subprocess.run(bt + ["-j", "map", "show"], capture_output=True, text=True, timeout=120).stdout)
    out = {}
    for m in maps:
        if m.get("name") == "rules_match_pdr":
            d = subprocess.run(bt + ["-j", "map", "dump", "id", str(m["id"])], capture_output=True, text=True, timeout=120).stdout
            out[str(m["id"])] = json.loads(d or "[]")
    return out


def check(result, name, ok, **detail):
    result["checks"][name] = {"ok": bool(ok), **detail}
    log(("PASS " if ok else "FAIL ") + name, json.dumps(detail)[:400])


def phase_block(result, ips):
    s1 = SUPI[UE1]
    rules_before = rules_dump()
    t_smf = time.time()
    cap = Capture(34)
    holder = {}

    def put_later():
        time.sleep(10)
        holder["put"] = api("PUT", "/v1/ues/" + s1, {"action": "block", "ttl_s": 600, "level": 3})

    th = threading.Thread(target=put_later)
    th.start()
    ue_threads = [threading.Thread(target=lambda d=d: holder.__setitem__(d, iperf_ul(d, ips[d], "1M", 24))) for d in (UE1, UE2)]
    for t in ue_threads: t.start()
    th.join()
    st_a = stats(s1)
    time.sleep(4)
    st_b = stats(s1)
    for t in ue_threads: t.join()
    pk = cap.packets()
    status, body, t_put = holder["put"]
    ue1 = [t for t, ip in pk if ip == ips[UE1]]
    ue2_after = [t for t, ip in pk if ip == ips[UE2] and t > t_put + 1]
    last = max(ue1) if ue1 else None
    check(result, "block_put_ok", status == 200 and body.get("enforced"), status=status, body=body)
    check(result, "block_ul_stops_within_1s", last is not None and last - t_put <= 1.0 and any(t < t_put for t in ue1),
          last_ue1_pkt_after_put_s=round(last - t_put, 3) if last else None, ue1_pkts_total=len(ue1))
    check(result, "block_other_ue_flows", len(ue2_after) > 100, ue2_pkts_after_put=len(ue2_after), ue2_iperf_mbps=holder.get(UE2))
    dl = iperf_dl(UE1, ips[UE1], "1M", 5)
    st_c = stats(s1)
    check(result, "block_dl_blocked", not dl and st_c.get("drop_dl_pkts", 0) > 0, dl_mbps=dl, drop_dl_pkts=st_c.get("drop_dl_pkts"))
    check(result, "block_sec_stats_grow", st_b.get("drop_ul_pkts", 0) > st_a.get("drop_ul_pkts", 0) > 0,
          drop_ul_pkts=[st_a.get("drop_ul_pkts"), st_b.get("drop_ul_pkts")])
    rules_after = rules_dump()
    check(result, "block_pfcp_rules_unchanged", rules_before == rules_after and rules_before,
          maps=list(rules_before), entries=sum(len(v) for v in rules_before.values()))
    smf = kubectl("-n", "oai-core", "logs", "deploy/oai-smf", "-c", "smf", "--since=%ds" % int(time.time() - t_smf + 5), check=False)
    errs = [l for l in smf.splitlines() if "[error]" in l.lower() or "[critical]" in l.lower()]
    check(result, "block_smf_no_error", not errs, errors=errs[:5])
    result["block"] = {"ue1_iperf_mbps": holder.get(UE1), "t_put": t_put}


def restart_ue1(result):
    old = policy(SUPI[UE1])[1].get("sessions", [])
    pods = [n for n in kubectl("-n", "oai-ran", "get", "pods", "-o", "name").split() if n.startswith("pod/" + UE1 + "-")]
    kubectl("-n", "oai-ran", "delete", *pods, "--wait=true", timeout=180)
    kubectl("-n", "oai-ran", "rollout", "status", "deploy/" + UE1, "--timeout=180s", timeout=200)
    return old


def phase_reconnect(result, ips):
    s1 = SUPI[UE1]
    cap = Capture(150)
    old = restart_ue1(result)
    ip = ue_ip(UE1, wait=120)
    ips[UE1] = ip
    mb = iperf_ul(UE1, ip, "1M", 10) if ip else None
    time.sleep(2)
    pk = cap.packets() if ip else []
    status, body, _ = policy(s1)
    new = body.get("sessions", [])
    new_seids = [s["seid"] for s in new]
    st_all = api("GET", "/v1/stats?supi=" + s1)[1]["stats"]
    sess = next((x for x in (st_all[0]["sessions"] if st_all else []) if x["seid"] in new_seids), None)
    from_new = [t for t, a in pk if a == ip]
    upf_log = kubectl("-n", "oai-core", "logs", "deploy/oai-upf", "--since=200s", check=False)
    applied = [l.strip()[:200] for l in upf_log.splitlines() if "policy applied to new session" in l]
    check(result, "reconnect_new_session_enforced",
          ip and new_seids and set(new_seids) != {s["seid"] for s in old} and all(s["in_map"] for s in new),
          ue1_ip=ip, old=old, new=new, upf_log=applied[-2:])
    check(result, "reconnect_blocked_from_first_packet", ip and not from_new and not mb and sess and sess["stats"]["drop_ul_pkts"] > 0,
          dn_pkts_from_new_session=len(from_new), iperf_mbps=mb, new_session_stats=sess and sess["stats"])


def phase_ratelimit(result, ips):
    s1 = SUPI[UE1]
    status, body, _ = api("PUT", "/v1/ues/" + s1, {"action": "ratelimit", "rate_ul_kbps": 500, "rate_dl_kbps": 500, "ttl_s": 600})
    mb = iperf_ul(UE1, ips[UE1], "2M", 15)
    st = stats(s1)
    check(result, "ratelimit_limits_ul", status == 200 and mb is not None and 0.15 <= mb <= 0.75,
          status=status, dn_mbps=mb, offered_mbps=2, limit_mbps=0.5, drop_ul_pkts=st.get("drop_ul_pkts"))


def phase_monitor(result, ips):
    s1 = SUPI[UE1]
    st0 = stats(s1)
    status, body, _ = api("PUT", "/v1/ues/" + s1, {"action": "monitor", "ttl_s": 600})
    mb = iperf_ul(UE1, ips[UE1], "1M", 10)
    st1 = stats(s1)
    check(result, "monitor_no_drop", status == 200 and mb is not None and mb >= 0.85
          and st1.get("drop_ul_pkts") == st0.get("drop_ul_pkts") and st1.get("seen_ul_pkts", 0) > st0.get("seen_ul_pkts", 0),
          status=status, dn_mbps=mb, drop_ul_pkts=[st0.get("drop_ul_pkts"), st1.get("drop_ul_pkts")],
          seen_ul_pkts=[st0.get("seen_ul_pkts"), st1.get("seen_ul_pkts")])


def phase_limits(result, ips):
    s1, s2 = SUPI[UE1], SUPI[UE2]
    time.sleep(1.2)
    r = api_many([["PUT", "/v1/ues/" + s1, {"action": "block", "ttl_s": 600}],
                  ["PUT", "/v1/ues/" + s2, {"action": "block", "ttl_s": 600}],
                  ["PUT", "/v1/ues/" + s2, {"action": "monitor", "ttl_s": 999999}]])
    check(result, "limit_blocked_ratio_403", r[0][0] == 200 and r[1][0] == 403, statuses=[r[0][0], r[1][0]], body=r[1][1])
    check(result, "limit_max_ttl_403", r[2][0] == 403, status=r[2][0], body=r[2][1])
    time.sleep(1.2)
    burst = api_many([["PUT", "/v1/ues/" + s2, {"action": "monitor", "ttl_s": 60}]] * 15)
    codes = [b[0] for b in burst]
    span = burst[-1][2] - burst[0][2]
    check(result, "limit_cmd_rate_429", codes.count(200) <= 10 and 429 in codes and span < 1.0, codes=codes, span_s=round(span, 3))
    time.sleep(1.2)
    api("DELETE", "/v1/ues/" + s2)


def scale_ues(n):
    for d in (UE1, UE2):
        kubectl("-n", "oai-ran", "scale", "deploy/" + d, "--replicas=%d" % n)
    if n == 0:
        for c in ("nr-ue", "nr-ue2"):
            kubectl("-n", "oai-ran", "wait", "--for=delete", "pod", "-l", "oai-lab/component=" + c, "--timeout=180s", timeout=200,
                    check=False)


def phase_restart(result, ips):
    s1 = SUPI[UE1]
    boot0 = api("GET", "/v1/info")[1]
    status, body, _ = api("PUT", "/v1/ues/" + s1, {"action": "block", "ttl_s": 900, "level": 3})
    scale_ues(0)
    subprocess.run([str(ROOT / "scripts/k8s/lab.sh"), "restart-upf"], check=True, timeout=900)
    info = api("GET", "/v1/info")[1]
    pol = policy(s1)
    check(result, "restart_policy_reloaded", info.get("boot_id") != boot0.get("boot_id") and pol[0] == 200
          and pol[1].get("action") == "block",
          boot_id=[boot0.get("boot_id"), info.get("boot_id")], policies=info.get("policies"), policy=pol[1])
    scale_ues(1)
    for d in (UE1, UE2):
        kubectl("-n", "oai-ran", "rollout", "status", "deploy/" + d, "--timeout=180s", timeout=200)
        ips[d] = ue_ip(d, wait=150)
    cap = Capture(30)
    mb1 = iperf_ul(UE1, ips[UE1], "1M", 10) if ips[UE1] else None
    mb2 = iperf_ul(UE2, ips[UE2], "1M", 10) if ips[UE2] else None
    pk = cap.packets()
    pol = policy(s1)[1]
    from_ue1 = [t for t, a in pk if a == ips[UE1]]
    check(result, "restart_new_session_blocked", ips[UE1] and not from_ue1 and not mb1 and pol.get("enforced"),
          ue1_ip=ips[UE1], dn_pkts_from_ue1=len(from_ue1), ue1_mbps=mb1, sessions=pol.get("sessions"))
    check(result, "restart_other_ue_flows", mb2 is not None and mb2 >= 0.85, ue2_ip=ips[UE2], ue2_mbps=mb2)


def phase_delete(result, ips):
    s1 = SUPI[UE1]
    status, body, _ = api("DELETE", "/v1/ues/" + s1)
    mb = iperf_ul(UE1, ips[UE1], "1M", 10)
    after = api("GET", "/v1/sessions")[1]
    check(result, "delete_traffic_recovers", status == 200 and mb is not None and mb >= 0.85
          and not any(s["policy_in_map"] for s in after["sessions"] if s["supi"] == s1),
          status=status, dn_mbps=mb, sessions=after["sessions"])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    phases = ALL_PHASES
    for a in sys.argv[1:]:
        if a.startswith("--phases="):
            phases = a.split("=", 1)[1].split(",")
    out = pathlib.Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    result = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "phases": phases, "checks": {}}
    ips = {d: ue_ip(d) for d in (UE1, UE2)}
    info = api("GET", "/v1/info")
    log("UE IPs", ips, "API", info[0], info[1].get("boot_id"))
    if info[0] != 200 or not all(ips.values()):
        print("Prerequisite failed: API or UE IPs")
        return 2
    result["info_before"] = info[1]
    for s in SUPI.values():
        api("DELETE", "/v1/ues/" + s)
    time.sleep(1.2)
    log("xApp defense off:", defense_enabled(False).strip()[:120])
    try:
        for p in phases:
            log("== phase", p)
            globals()["phase_" + p](result, ips)
            time.sleep(1.2)  # stay under maxCmdsPerS between phases
    finally:
        for s in SUPI.values():
            api("DELETE", "/v1/ues/" + s)
        log("xApp defense on:", defense_enabled(True).strip()[:120])
        result["ues"] = api("GET", "/v1/ues")[1]
        result["stats"] = api("GET", "/v1/stats")[1]
        result["status"] = "PASS" if result["checks"] and all(c["ok"] for c in result["checks"].values()) else "FAIL"
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        audit = ex("oai-core", "oai-upf", "upf", "tail", "-n", "200", "/upf-sec/audit.jsonl", check=False)
        (out / "audit.jsonl").write_text(audit)
        log("Gate U", result["status"], "->", out / "result.json")
        if any(p in phases for p in ("reconnect", "restart")):
            log("UEs restarted: restart the xApp after both UEs have an IP (SUPI mapping)")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
