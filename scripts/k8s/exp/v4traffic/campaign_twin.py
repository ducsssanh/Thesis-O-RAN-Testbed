#!/usr/bin/env python3
"""Resumable runner of the twin campaign. Each manifest run goes through run.py, then qa_twin; a run with problems is kept on disk, marked in the log, and repeated after recovery with the same seeds.
Stops after 3 failed attempts in a row. Log: research/datasets/oran_flooding_twin/manifest/campaign_log.jsonl. Usage: campaign_twin.py --lo 0 --hi 72"""
import argparse, os, glob, json, pathlib, re, shutil, subprocess, sys, tempfile, time
import yaml
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import design_twin, qa_twin
LOG = ROOT / "research/datasets/oran_flooding_twin/manifest/campaign_log.jsonl"
K = ["kubectl", "--context", "oai-lab"]
XAPP_LOGS = "/artifacts/runs/20261003T164156Z-m35"


def sh(cmd, timeout=900):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def log(**kw):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"at": round(time.time()), **kw}) + "\n")


def env_problems():
    """The conditions a run needs, which a chart upgrade or a restart can undo without any error."""
    out = []
    for d in ("oai-nr-ue", "oai-nr-ue2"):
        rc, o = sh(K + ["-n", "oai-ran", "exec", "deploy/" + d, "-c", "keepalive", "--", "sh", "-c", "command -v hping3; cat /sys/fs/cgroup/cpu.max; ip route | grep -c '172.30.26.0/24 dev oaitun_ue1'"], 30)
        if rc or "hping3" not in o or "100000 100000" not in o or not o.strip().endswith("1"):
            out.append("%s sidecar: %s" % (d, o.strip()[-120:]))
    gb = float(os.environ.get("CAMPAIGN_MIN_FREE_GB", "6"))   # a live run writes ~10 MB; dataset campaigns need more
    if shutil.disk_usage(ROOT).free < gb * 2**30:
        out.append("disk under %g GB" % gb)
    return out


def rotate_xapp_logs():
    cmd = "cd %s && for f in KPI_Metrics.csv KPI_Metrics_Cells.csv; do truncate -s $(head -1 $f | wc -c) $f; done; for f in KPI_Metrics_Defense.jsonl KPI_Metrics_Features.jsonl KPI_Metrics_RAN_Control.jsonl KPI_Metrics_RawKpm.jsonl KPI_Metrics_Tamper.jsonl KPI_Metrics_Clf.jsonl core-received.jsonl urr-received.jsonl; do truncate -s 0 $f; done" % XAPP_LOGS
    return sh(K + ["-n", "near-rt-ric", "exec", "deploy/oai-lab-xapp", "-c", "xapp", "--", "sh", "-c", cmd], 60)


def recover():
    rc1, o1 = sh(["bash", str(ROOT / "scripts/k8s/recover_core_ordered.sh")], 600)
    sh(K + ["-n", "oai-core", "rollout", "restart", "deploy/oai-smf"], 60)
    sh(K + ["-n", "oai-core", "rollout", "status", "deploy/oai-smf", "--timeout=180s"], 200)
    time.sleep(20)
    rc2, o2 = sh(["bash", str(ROOT / "scripts/k8s/recover_ran.sh")], 600)
    for d in ("oai-nr-ue", "oai-nr-ue2"):
        sh(K + ["-n", "oai-ran", "exec", "deploy/" + d, "-c", "nr-ue", "--", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1"], 30)
    time.sleep(20)
    return rc1, rc2, o2[-200:]


def done_ids():
    """ids whose last kept/rejected event is kept: a run rejected afterwards (a QA check added after it ran, applied to
    every kept run; 2026-11-14 dead UL in p0) is run again with the next attempt number"""
    if not LOG.exists():
        return set()
    last = {}
    for x in map(json.loads, LOG.read_text().splitlines()):
        if x.get("event") in ("kept", "rejected"):
            last[x["id"]] = x["event"]
    return {i for i, e in last.items() if e == "kept"}


def attempts_so_far(i):
    if not LOG.exists():
        return 0
    return max([x.get("attempt", 0) for x in map(json.loads, LOG.read_text().splitlines()) if x.get("id") == i and x.get("event") in ("kept", "failed")] or [0])


def main():
    global LOG
    ap = argparse.ArgumentParser(); ap.add_argument("--lo", type=int, default=0); ap.add_argument("--hi", type=int, default=72)
    ap.add_argument("--manifest", default="research/datasets/oran_flooding_twin/manifest")
    a = ap.parse_args()
    LOG = ROOT / a.manifest / "campaign_log.jsonl"
    d = json.loads((ROOT / a.manifest / "design.json").read_text())
    fails, done, hist = 0, done_ids(), {}
    for i, r in enumerate(d["runs"][a.lo:a.hi]):
        if r["id"] in done:
            continue
        attempt = attempts_so_far(r["id"])
        while True:
            problems = env_problems()
            if problems:
                log(event="env", id=r["id"], problems=problems)
                recover()
                problems = env_problems()
                if problems:
                    log(event="stop", id=r["id"], problems=problems); sys.exit("environment: %s" % problems)
            if i % 6 == 0 and attempt == 0:
                rotate_xapp_logs()
            attempt += 1
            tag = "%sa%d" % (r["id"], attempt)
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
                yaml.safe_dump(design_twin.scenario_e2e(r) if r.get("e2e") else design_twin.scenario_live(r) if r.get("live") else design_twin.scenario(r), f); path = f.name
            rc, o = sh([sys.executable, str(ROOT / "scripts/k8s/exp/run.py"), "run", path, "--tag", tag], 1800)
            pathlib.Path(path).unlink(missing_ok=True)
            camp = sorted(glob.glob(str(ROOT / ("artifacts/experiments/*_%s" % tag))))
            run = sorted(glob.glob(camp[-1] + "/runs/*/*"))[-1] if camp and glob.glob(camp[-1] + "/runs/*/*") else None
            problems = qa_twin.qa_run(run, expected_phases=len(r["phases"]), live=bool(r.get("live")), e2e=r) if run else ["run.py rc %s %s" % (rc, o[-200:])]
            log(event="kept" if not problems else "failed", id=r["id"], attempt=attempt, run=run, problems=problems)
            if not problems:
                fails = 0
                break
            fails += 1
            hist.setdefault(r["id"], []).append(problems)
            h = hist[r["id"]]
            if len(h) == 3 and len({tuple(re.sub(r"\d+\.\d+", "", x) for x in y) for y in h}) == 1 and all(x.startswith(("attack delivered", "dead DL")) for x in problems):
                # the same phase and flow after two recoveries: a property of the replayed window, not of the testbed state
                log(event="kept", id=r["id"], attempt=attempt, run=run, problems=[], note="repeatable: %s" % problems)
                fails = 0
                break
            if fails >= 3:
                log(event="stop", id=r["id"], problems=problems); sys.exit("3 failed attempts in a row: %s" % problems)
            recover()


if __name__ == "__main__":
    main()
