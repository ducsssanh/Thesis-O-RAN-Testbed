"""Cluster access for the experiment runner: kubectl, the xApp defense API,
the UPF Security API, UE addressing, preflight checks."""
import json
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/k8s"))
import staged  # noqa: E402  (run id, image locks, values)

CTX = "oai-lab"
DN_IP = "172.30.26.10"
UPF_API = "http://oai-upf-security.oai-core.svc.cluster.local:8095"
# UE name in a scenario -> (deployment, pod label, IMSI)
UES = {
    "ue1": ("oai-nr-ue", "nr-ue", "imsi-001010123456780"),
    "ue2": ("oai-nr-ue2", "nr-ue2", "imsi-001010123456781"),
    "ue3": ("oai-nr-ue3", "nr-ue3", "imsi-001010123456782"),
    "ue4": ("oai-nr-ue4", "nr-ue4", "imsi-001010123456783"),
}


class LabError(RuntimeError):
    pass


def kubectl(*args, timeout=60, check=True, text=True):
    p = subprocess.run(["kubectl", "--context", CTX, *args], capture_output=True, text=text, timeout=timeout,
                       errors="replace" if text else None)
    if check and p.returncode != 0:
        raise LabError("kubectl %s: %s" % (" ".join(args[:6]), (p.stderr or "")[-300:]))
    return p.stdout


def ex(ns, deploy, container, *cmd, timeout=60, check=True):
    return kubectl("-n", ns, "exec", "deploy/" + deploy, "-c", container, "--", *cmd, timeout=timeout, check=check)


def popen_ex(ns, deploy, container, *cmd):
    return subprocess.Popen(["kubectl", "--context", CTX, "-n", ns, "exec", "deploy/" + deploy, "-c", container, "--", *cmd],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)


# ---- HTTP from inside the xApp pod (loopback defense API; cluster Service of the UPF) ----

_HTTP = """
import json,sys,time,urllib.request,urllib.error
out=[]
for m,u,b in json.loads(sys.argv[1]):
    r=urllib.request.Request(u,data=(json.dumps(b).encode() if b is not None else None),method=m)
    try:
        s=urllib.request.urlopen(r,timeout=15);out.append([s.status,s.read().decode()])
    except urllib.error.HTTPError as e:
        out.append([e.code,e.read().decode()])
    except Exception as e:
        out.append([0,str(e)])
print(json.dumps(out))
"""


def http_many(reqs):
    raw = ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", _HTTP, json.dumps(reqs), timeout=90)
    res = []
    for status, body in json.loads(raw.strip().splitlines()[-1]):
        try:
            res.append((status, json.loads(body) if body else {}))
        except ValueError:
            res.append((status, {"raw": body}))
    return res


def defense(method, path, body=None):
    return http_many([[method, "http://127.0.0.1:8090" + path, body]])[0]


def upf(method, path, body=None):
    return http_many([[method, UPF_API + path, body]])[0]


def defense_state():
    s, body = defense("GET", "/v1/defense/state")
    if s != 200:
        raise LabError("defense state HTTP %s" % s)
    return body


# ---- UEs ----

def ue_ip(name, wait=0):
    deploy = UES[name][0]
    t_end = time.time() + wait
    while True:
        out = ex("oai-ran", deploy, "nr-ue", "ip", "-4", "-br", "addr", "show", "oaitun_ue1", check=False, timeout=20)
        f = out.split()
        if len(f) >= 3 and "/" in f[2]:
            ip = f[2].split("/")[0]
            ex("oai-ran", deploy, "nr-ue", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1", check=False)
            return ip
        if time.time() > t_end:
            return None
        time.sleep(2)


def amf_ids():
    """SUPI -> AMF UE NGAP ID as the xApp knows it (R1 mapping)."""
    return {u["supi"]: u.get("amf_ue_ngap_id") for u in defense_state().get("ues", [])}


def ues_no_forward(ue_names):
    """A real UE does not route. With ip_forward=1 (the image default) a DL packet of the other UE that reaches this UE goes back
    UL with an ICMP redirect: KPM counts it, the profiler does not (research/twinning/ct_root_cause/ip_forward_result.txt).
    /proc/sys is read-only in the pods, so it is set from the node. A restarted UE needs it again.
    pgrep -x: with -f the matching shell itself is hit, and that sets the NODE's ip_forward to 0 (2026-11-02), which breaks Services."""
    state = lambda: [ex("oai-ran", UES[n][0], "nr-ue", "cat", "/proc/sys/net/ipv4/ip_forward").strip() for n in ue_names]
    if set(state()) == {"0"}:
        return
    subprocess.run(["minikube", "-p", "oai-lab", "ssh", "--", "for p in $(sudo pgrep -x nr-uesoftmodem); do sudo nsenter -t $p -n "
                    "sysctl -qw net.ipv4.ip_forward=0 net.ipv4.conf.all.send_redirects=0 2>/dev/null; done"], capture_output=True, text=True, timeout=60)
    if set(state()) != {"0"}:
        raise LabError("ip_forward is still on in a UE")
    node = subprocess.run(["minikube", "-p", "oai-lab", "ssh", "--", "cat /proc/sys/net/ipv4/ip_forward"], capture_output=True, text=True, timeout=30).stdout.strip()
    if node != "1":
        raise LabError("ip_forward is off on the node: pod services stop working")


def restart_ue(name, timeout=180):
    deploy, label, supi = UES[name]
    kubectl("-n", "oai-ran", "delete", "pod", "-l", "oai-lab/component=" + label, "--wait=true", timeout=timeout)
    kubectl("-n", "oai-ran", "rollout", "status", "deploy/" + deploy, "--timeout=%ds" % timeout, timeout=timeout + 20)
    ip = ue_ip(name, wait=timeout)
    if not ip:
        raise LabError(name + " has no tunnel IP after restart")
    return ip


def wait_amf_registered(supi, timeout=90):
    imsi = supi.split("-", 1)[1]
    t_end = time.time() + timeout
    while time.time() < t_end:
        log = kubectl("-n", "oai-core", "logs", "deploy/oai-amf", "-c", "amf", "--since=25s", check=False)
        if "5GMM-REGISTERED" in log and imsi in log:
            return True
        time.sleep(3)
    return False


def restart_xapp():
    kubectl("-n", "near-rt-ric", "rollout", "restart", "deploy/oai-lab-xapp")
    kubectl("-n", "near-rt-ric", "rollout", "status", "deploy/oai-lab-xapp", "--timeout=150s", timeout=170)
    for _ in range(60):
        log = kubectl("-n", "near-rt-ric", "logs", "deploy/oai-lab-xapp", "-c", "xapp", check=False)
        if "Assertion" in log:
            raise LabError("xApp asserted after restart (FlexRIC stuck: run scripts/k8s/phase0/recover_ran.sh)")
        if "RAN control on" in log:
            return
        time.sleep(3)
    raise LabError("xApp did not come up")


# ---- preflight ----

def preflight(ue_names):
    """Refuse to run on a broken lab; returns facts recorded in run.json."""
    facts = {"run_id": staged.run_id()}
    free = shutil.disk_usage("/").free / 2**30
    facts["disk_free_gib"] = round(free, 1)
    if free < 5:
        raise LabError("only %.1f GiB free on / (clean up first, see docs/SESSION-HANDOFF.md section 7)" % free)
    st = defense_state()
    facts["defense"] = {k: st.get(k) for k in ("enabled", "profile", "action_mode", "timing", "unlabelled_samples")}
    facts["defense"]["core"] = st.get("core", {}).get("enabled")
    known = {u["supi"]: u for u in st.get("ues", [])}
    facts["ues"] = {}
    for n in ue_names:
        deploy, _, supi = UES[n]
        ip = ue_ip(n)
        if not ip:
            raise LabError("%s (%s) has no tunnel IP" % (n, deploy))
        if supi not in known or not known[supi].get("amf_ue_ngap_id"):
            raise LabError("%s (%s) is not known to the xApp (KPM/SUPI mapping): restart the xApp" % (n, supi))
        facts["ues"][n] = {"deployment": deploy, "supi": supi, "ip": ip, "amf_ue_ngap_id": known[supi]["amf_ue_ngap_id"]}
    s, info = upf("GET", "/v1/info")
    if s != 200:
        raise LabError("UPF Security API unreachable (HTTP %s)" % s)
    facts["upf"] = {"boot_id": info.get("boot_id"), "policies": info.get("policies"), "limits": info.get("limits")}
    return facts


def images():
    st = staged.STATE / "state"
    out = {}
    for name in ("images.json", "ei-images.json", "xapp-image.json"):
        p = st / name
        if p.exists():
            out[name] = json.loads(p.read_text())
    return out
