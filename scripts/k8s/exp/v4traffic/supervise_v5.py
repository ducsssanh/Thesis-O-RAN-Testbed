#!/usr/bin/env python3
"""Run v5 live manifest entries until each has a valid attempt (meta_run_ok=1), recovering the
testbed in between. Unattended driver around campaign.py (which stops on a failed preflight or
2 failed runs in a row).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/supervise_v5.py --manifest <json> --tag pilot \
        [--ids 1-42] [--max-attempts 3] [--config-reps rules-v1=1,3] [--chunk 50]

Loop: wait while another campaign.py runs -> runs still lacking a valid attempt (all campaigns
artifacts/experiments/*_v5live_<tag>* of this manifest) -> preflight (PFCP + fresh URR of both
sessions + xApp knows 2 SUPIs + fresh KPM/URR of both UEs); if it fails: save core/RAN logs, recover_ran.sh, UE routes,
defence off; still failing: recover_core_ordered.sh; still failing: stop (human needed) ->
campaign.py --reps <next --chunk missing> -> qa_v5 over that chunk's attempts (STOP on a QA
failure: human needed) -> repeat. A run is given up after --max-attempts failed attempts.
--config-reps CONFIG=REPS keeps only those manifest reps of CONFIG (main campaign: rules-v1 = reference).
Every action is logged to artifacts/experiments/supervise_v5_<tag>.log.
"""
import argparse, json, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
PY = str(ROOT / ".venv-ml/bin/python")
EXP = ROOT / "artifacts/experiments"
LOG = None


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def sh(cmd, timeout=1200):
    p = subprocess.run(cmd, shell=True, executable="/bin/bash", capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def attempts(manifest, tag):
    """{manifest id: (n attempts, ok)} over every campaign of this tag and manifest."""
    out = {}
    for c in sorted(EXP.glob("*_v5live_%s*" % tag)):
        try:
            if pathlib.Path(json.loads((c / "campaign.json").read_text())["manifest"]).resolve() != manifest.resolve():
                continue
        except (OSError, ValueError, KeyError):
            continue
        for rj in c.glob("runs/*/rep-*/run.json"):
            try:
                m = json.loads(rj.read_text())
            except (OSError, ValueError):
                continue
            i = m.get("manifest_id") or int(rj.parent.name.split("-")[1])
            n, ok = out.get(i, (0, False))
            out[i] = (n + 1, ok or m.get("meta_run_ok") == 1)
    return out


def other_campaign_running():
    """A campaign or a recovery started by someone else is still running."""
    # anchored to the process's own command (python ... / bash ...): a shell whose command line
    # merely mentions these names (pgrep's own, a wrapper) must not count
    rc, out = sh("pgrep -f '^[^ ]*python[^ ]* .*v4traffic/campaign\\.py run|^bash [^ ]*recover_(ran|core_ordered)\\.sh' || true")
    return bool(out.strip())


def xapp(path, body=None):
    py = ("import urllib.request,json,sys;b=sys.argv[2] if len(sys.argv)>2 else None;"
          "r=urllib.request.Request('http://127.0.0.1:8090'+sys.argv[1],data=b.encode() if b else None,"
          "headers={'Content-Type':'application/json'},method='POST' if b else 'GET');"
          "print(urllib.request.urlopen(r,timeout=5).read().decode())")
    args = [path] + ([json.dumps(body)] if body is not None else [])
    rc, out = sh("kubectl --context oai-lab -n near-rt-ric exec deploy/oai-lab-xapp -c xapp -- python3 -c %s %s"
                 % (json.dumps(py), " ".join("'%s'" % a for a in args)), timeout=60)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def healthy():
    import campaign
    ok, reasons = campaign.extra_preflight({})
    st = xapp("/v1/defense/state")
    n = len((st or {}).get("ues") or [])
    if n < 2:
        ok, reasons = False, reasons + ["xApp knows %d SUPIs" % n]
    import run                                     # KPM + URR fresh for both UEs (a UE after a radio-link failure)
    try:
        run.readiness(["ue1", "ue2"], **campaign.READINESS)
    except Exception as e:
        ok, reasons = False, reasons + [str(e)[:200]]
    return ok, reasons


def after_recovery():
    """UE->DN routes, defence off, wait for both SUPIs at the xApp."""
    for d in ("oai-nr-ue", "oai-nr-ue2"):
        sh("kubectl --context oai-lab -n oai-ran exec deploy/%s -c nr-ue -- ip route replace 172.30.26.0/24 dev oaitun_ue1" % d)
    for _ in range(30):
        if (xapp("/v1/defense/enabled", {"enabled": False}) or {}).get("enabled") is False:
            break
        time.sleep(3)
    for _ in range(40):
        if len(((xapp("/v1/defense/state") or {}).get("ues")) or []) >= 2:
            return
        time.sleep(3)


def save_logs(n):
    d = ROOT / ("artifacts/k8s/diagnostics/v5-live-supervise/%s-%02d" % (time.strftime("%Y%m%d-%H%M%S"), n))
    d.mkdir(parents=True, exist_ok=True)
    for ns, dep, c in [("oai-core", "oai-amf", "amf"), ("oai-core", "oai-smf", "smf"), ("oai-core", "oai-upf", "upf"),
                       ("oai-ran", "oai-gnb", "gnb"), ("oai-ran", "oai-nr-ue", "nr-ue"), ("oai-ran", "oai-nr-ue2", "nr-ue"),
                       ("near-rt-ric", "oai-flexric", "flexric"), ("near-rt-ric", "oai-lab-xapp", "xapp")]:
        sh("kubectl --context oai-lab -n %s logs deploy/%s -c %s --since=30m | gzip > %s/%s.log.gz" % (ns, dep, c, d, dep))
    return d


def recover(n):
    d = save_logs(n)
    log("recovery %d: logs saved to %s; recover_ran.sh" % (n, d.relative_to(ROOT)))
    rc, out = sh("bash %s" % (ROOT / "scripts/k8s/phase0/recover_ran.sh"), timeout=900)
    after_recovery()
    ok, reasons = healthy()
    if ok:
        log("recovery %d: healthy after recover_ran" % n)
        return True
    log("recovery %d: still unhealthy (%s); recover_core_ordered.sh" % (n, "; ".join(reasons)))
    rc, out = sh("bash %s" % (ROOT / "scripts/k8s/phase0/recover_core_ordered.sh"), timeout=1200)
    log("recover_core_ordered rc=%d: %s" % (rc, out.strip().splitlines()[-1] if out.strip() else ""))
    after_recovery()
    ok, reasons = healthy()
    log("recovery %d: %s" % (n, "healthy" if ok else "STILL UNHEALTHY: " + "; ".join(reasons)))
    return ok


def parse_ids(s, n):
    if not s:
        return list(range(1, n + 1))
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def config_reps(ids, man, spec):
    """Drop the manifest runs of a config whose rep is not listed (spec 'rules-v1=1,3;...')."""
    keep = {}
    for part in filter(None, (spec or "").split(";")):
        c, _, r = part.partition("=")
        keep[c] = {int(x) for x in r.split(",")}
    runs = man["runs"]
    return [i for i in ids if runs[i - 1]["config"] not in keep or runs[i - 1]["rep"] in keep[runs[i - 1]["config"]]]


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--ids", default="")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--max-recoveries", type=int, default=6)
    ap.add_argument("--config-reps", default="")
    ap.add_argument("--chunk", type=int, default=0, help="runs per campaign.py call, QA after each (0: all, no QA)")
    a = ap.parse_args()
    man = pathlib.Path(a.manifest)
    LOG = EXP / ("supervise_v5_%s.log" % a.tag)
    M = json.loads(man.read_text())
    ids = config_reps(parse_ids(a.ids, len(M["runs"])), M, a.config_reps)
    log("manifest %s: %d runs selected (config-reps %r), chunk %d" % (man.name, len(ids), a.config_reps, a.chunk))
    rec, batch = 0, 0
    T0 = time.strftime("%Y%m%d-%H%M%S")              # QA report names stay unique across supervisor restarts
    while True:
        while other_campaign_running():
            time.sleep(30)
        at = attempts(man, a.tag)
        todo = [i for i in ids if not at.get(i, (0, False))[1] and at.get(i, (0, False))[0] < a.max_attempts]
        gave_up = [i for i in ids if not at.get(i, (0, False))[1] and at.get(i, (0, False))[0] >= a.max_attempts]
        log("valid %d/%d, to run %d, given up %s" % (sum(1 for i in ids if at.get(i, (0, False))[1]), len(ids), len(todo), gave_up))
        if not todo:
            log("DONE")
            return 0
        ok, reasons = healthy()
        if not ok:
            log("preflight failed: %s" % "; ".join(reasons))
            rec += 1
            if rec > a.max_recoveries or not recover(rec):
                log("STOP: testbed not recoverable automatically (recoveries %d)" % rec)
                return 2
        batch += 1
        if a.chunk:
            todo = todo[:a.chunk]
        log("batch %d: runs %s" % (batch, todo))
        rc, out = sh("systemd-inhibit --what=sleep:idle --why='v5 %s' %s -I %s run --variant manifest --manifest %s --reps %s --tag %s_s%d"
                     % (a.tag, PY, HERE / "campaign.py", man, " ".join(map(str, todo)), a.tag, batch), timeout=48 * 3600)
        log("batch %d ended rc=%d: %s" % (batch, rc, " ".join(out.strip().splitlines()[-3:])[:300]))
        if a.chunk:
            camps = sorted(EXP.glob("*_v5live_%s_s%d" % (a.tag, batch)))
            qdir = EXP / ("qa_v5_%s" % a.tag)
            qdir.mkdir(exist_ok=True)
            rc, out = sh("%s -I %s %s --out %s" % (PY, HERE / "qa_v5.py", " ".join(map(str, camps)), qdir / ("%s_batch%02d.md" % (T0, batch))))
            log("QA batch %d rc=%d: %s" % (batch, rc, out.strip().splitlines()[-1] if out.strip() else ""))
            if rc != 0:
                log("STOP: QA failed after batch %d (report %s)" % (batch, (qdir / ("%s_batch%02d.md" % (T0, batch))).relative_to(ROOT)))
                return 3


if __name__ == "__main__":
    sys.exit(main())
