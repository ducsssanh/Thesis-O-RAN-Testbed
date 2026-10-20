#!/usr/bin/env python3
"""User-plane watchdog + auto-recovery for the oai-lab testbed (v4 P0).

The OAI SMF segfaults ~every 5.5h and the Multus race on a cold minikube start
leaves core NFs without their secondary interfaces; neither recovers on its own.
This encodes the VERIFIED recovery procedure (see memory testbed-userplane-fragility
/ research/testbed/phase0_v4.md) so a long v4 capture can survive faults unattended.

  userplane_watchdog.py check                 # one-shot health, exit 0=healthy 1=down
  userplane_watchdog.py recover               # run the full recovery sequence
  userplane_watchdog.py probe                 # active UL iperf probe (ue1->DN), prints loss%
  userplane_watchdog.py watch [--interval S] [--log F] [--recover]
                                              # loop: check every S s, recover on failure
  userplane_watchdog.py guard -- <cmd...>     # run cmd; if it exits non-zero AND the
                                              # user-plane is down, recover and rerun once

Health = minikube running + all oai-core pods Ready + SMF container up + both UEs
have an oaitun_ue1 10.1.0.x address. Recovery = cold-start fix of the Multus race +
recover_ran + re-add UE routes + disable defense + UL verify. Idempotent and safe to
re-run. Never fabricates: every status is read live from the cluster.
"""
import argparse, json, subprocess, sys, time, pathlib

CTX = "oai-lab"
ROOT = pathlib.Path(__file__).resolve().parents[3]
RECOVER_RAN = ROOT / "scripts/k8s/phase0/recover_ran.sh"
RECOVER_CORE = ROOT / "scripts/k8s/phase0/recover_core_ordered.sh"
UES = {"oai-nr-ue": "10.1.0.2", "oai-nr-ue2": "10.1.0.3"}
DN_IP = "172.30.26.10"


def sh(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def k(args, timeout=60):
    return sh(f"kubectl --context {CTX} {args}", timeout)


def log(ev, logf=None, **kw):
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": ev, **kw}
    line = json.dumps(rec)
    print(line, flush=True)
    if logf:
        with open(logf, "a") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------- health checks
def minikube_running():
    rc, out, _ = sh(f"minikube status -p {CTX} -o json", 30)
    if rc != 0:
        return False
    try:
        return json.loads(out).get("Host") == "Running"
    except Exception:
        return "Running" in out


def core_ready():
    rc, out, _ = k("get pods -n oai-core -o json", 40)
    if rc != 0:
        return False, ["kubectl failed"]
    bad = []
    for p in json.loads(out).get("items", []):
        name = p["metadata"]["name"]
        conds = {c["type"]: c["status"] for c in p.get("status", {}).get("conditions", [])}
        if conds.get("Ready") != "True":
            bad.append(name)
    return (len(bad) == 0), bad


def ue_oaitun(dep):
    rc, out, _ = k(f"-n oai-ran exec deploy/{dep} -c nr-ue -- ip -4 -o addr show oaitun_ue1", 30)
    if rc != 0:
        return None
    import re
    m = re.search(r"10\.1\.0\.\d+", out)
    return m.group(0) if m else None


def check(verbose=True):
    reasons = []
    if not minikube_running():
        reasons.append("minikube not running")
        if verbose:
            log("check", healthy=False, reasons=reasons)
        return False, reasons
    ok, bad = core_ready()
    if not ok:
        reasons.append("core pods not ready: " + ",".join(bad))
    for dep in UES:
        if ue_oaitun(dep) is None:
            reasons.append(f"{dep} has no oaitun")
    healthy = len(reasons) == 0
    if verbose:
        log("check", healthy=healthy, reasons=reasons)
    return healthy, reasons


# ---------------------------------------------------------------- active probe
def probe():
    srv = subprocess.Popen(
        f"kubectl --context {CTX} -n oai-core exec deploy/oai-lab-dn -c dn -- "
        f"timeout 9 iperf -s -u -p 5001", shell=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    rc, out, _ = k("-n oai-ran exec deploy/oai-nr-ue -c nr-ue -- "
                   f"iperf -c {DN_IP} -u -b 4m -l 1200 -t 4 -p 5001 -B {UES['oai-nr-ue']}", 30)
    srv.wait(timeout=12)
    loss = None
    for ln in out.splitlines():
        if "%" in ln and "/" in ln:
            import re
            m = re.search(r"\(([\d.]+)%\)", ln)
            if m:
                loss = float(m.group(1))
    return loss


# ---------------------------------------------------------------- recovery
def disable_defense():
    body = json.dumps({"enabled": False})
    py = ('import urllib.request,json;'
          'urllib.request.urlopen(urllib.request.Request('
          '"http://127.0.0.1:8090/v1/defense/enabled",'
          f'data={body!r}.encode(),headers={{"Content-Type":"application/json"}},method="POST"),timeout=10)')
    k(f"-n near-rt-ric exec deploy/oai-lab-xapp -c xapp -- python3 -c '{py}'", 30)


def readd_routes():
    for dep in UES:
        k(f"-n oai-ran exec deploy/{dep} -c nr-ue -- ip route replace 172.30.26.0/24 dev oaitun_ue1", 30)


def recover(logf=None):
    log("recover_start", logf)
    if not minikube_running():
        log("minikube_start", logf)
        sh(f"minikube start -p {CTX}", 600)
        # wait for multus
        for _ in range(40):
            rc, out, _ = k("get pods -n kube-system --no-headers", 30)
            if rc == 0 and "multus" in out and all(
                    ("Running" in ln or "Completed" in ln) for ln in out.splitlines()):
                break
            time.sleep(5)
    # Ordered core recovery (NEVER a simultaneous rollout restart — that re-races the
    # SMF<->UPF PFCP association, see memory testbed-userplane-fragility FAILURE MODE 2).
    # recover_core_ordered: NRF -> UPF/AMF -> SMF -> verify PFCP assoc -> UEs -> routes ->
    # defense off -> verify 2 SUPIs. Falls back to recover_ran if the RIC/E2 side is down.
    log("recover_core_ordered", logf)
    rc = sh(f"bash {RECOVER_CORE}", 900)[0]
    if rc != 0:
        log("recover_core_failed_fallback_recover_ran", logf, rc=rc)
        sh(f"bash {RECOVER_RAN}", 600)
        for _ in range(40):
            if all(ue_oaitun(d) for d in UES):
                break
            time.sleep(3)
        readd_routes()
        disable_defense()
    loss = probe()
    healthy, reasons = check(verbose=False)
    log("recover_done", logf, healthy=healthy, probe_loss_pct=loss, reasons=reasons)
    return healthy


# ---------------------------------------------------------------- loops
def watch(interval, logf, auto_recover, fail_ticks=3):
    """Recover only after `fail_ticks` consecutive unhealthy ticks, so a harness
    preflight that briefly restarts a UE does not trigger a core restart mid-run."""
    log("watch_start", logf, interval=interval, auto_recover=auto_recover, fail_ticks=fail_ticks)
    bad = 0
    while True:
        healthy, reasons = check(verbose=False)
        bad = 0 if healthy else bad + 1
        log("tick", logf, healthy=healthy, reasons=reasons, consecutive_bad=bad)
        if bad >= fail_ticks and auto_recover:
            recover(logf)
            bad = 0
        time.sleep(interval)


def guard(cmd, logf):
    rc, out, err = sh(cmd, timeout=86400)
    print(out)
    if rc != 0:
        healthy, _ = check(verbose=False)
        if not healthy:
            log("guard_recover", logf, cmd=cmd, rc=rc)
            recover(logf)
            rc, out, err = sh(cmd, timeout=86400)
            print(out)
    return rc


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("recover")
    sub.add_parser("probe")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=int, default=60)
    w.add_argument("--log", default=None)
    w.add_argument("--recover", action="store_true")
    w.add_argument("--fail-ticks", type=int, default=3, help="consecutive unhealthy ticks before recovering")
    g = sub.add_parser("guard")
    g.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "check":
        ok, _ = check()
        sys.exit(0 if ok else 1)
    elif a.cmd == "recover":
        sys.exit(0 if recover() else 1)
    elif a.cmd == "probe":
        loss = probe()
        log("probe", loss_pct=loss)
        sys.exit(0 if (loss is not None and loss < 50) else 1)
    elif a.cmd == "watch":
        watch(a.interval, a.log, a.recover, a.fail_ticks)
    elif a.cmd == "guard":
        rest = a.rest[1:] if a.rest and a.rest[0] == "--" else a.rest
        sys.exit(guard(" ".join(rest), None))


if __name__ == "__main__":
    main()
