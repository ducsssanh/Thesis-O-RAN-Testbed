#!/usr/bin/env python3
"""Resumable runner of the twin campaign. Each manifest run goes through run.py, then qa_twin; a run with problems is kept on disk, marked in the log, and repeated after recovery with the same seeds.
Stops after 3 failed attempts in a row. Log: research/datasets/oran_flooding_twin/manifest/campaign_log.jsonl. Usage: campaign_twin.py --lo 0 --hi 72"""
import argparse, glob, json, pathlib, shutil, subprocess, sys, tempfile, time
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
    if shutil.disk_usage(ROOT).free < 6 * 2**30:
        out.append("disk under 6 GB")
    return out


def rotate_xapp_logs():
    cmd = "cd %s && for f in KPI_Metrics.csv KPI_Metrics_Cells.csv; do truncate -s $(head -1 $f | wc -c) $f; done; for f in KPI_Metrics_Defense.jsonl KPI_Metrics_Features.jsonl KPI_Metrics_RAN_Control.jsonl KPI_Metrics_RawKpm.jsonl KPI_Metrics_Sidecar.jsonl KPI_Metrics_Tamper.jsonl core-received.jsonl urr-received.jsonl; do truncate -s 0 $f; done" % XAPP_LOGS
    return sh(K + ["-n", "near-rt-ric", "exec", "deploy/oai-lab-xapp", "-c", "xapp", "--", "sh", "-c", cmd], 60)


def recover():
    rc1, o1 = sh(["bash", str(ROOT / "scripts/k8s/phase0/recover_core_ordered.sh")], 600)
    sh(K + ["-n", "oai-core", "rollout", "restart", "deploy/oai-smf"], 60)
    sh(K + ["-n", "oai-core", "rollout", "status", "deploy/oai-smf", "--timeout=180s"], 200)
    time.sleep(20)
    rc2, o2 = sh(["bash", str(ROOT / "scripts/k8s/phase0/recover_ran.sh")], 600)
    for d in ("oai-nr-ue", "oai-nr-ue2"):
        sh(K + ["-n", "oai-ran", "exec", "deploy/" + d, "-c", "nr-ue", "--", "ip", "route", "replace", "172.30.26.0/24", "dev", "oaitun_ue1"], 30)
    time.sleep(20)
    return rc1, rc2, o2[-200:]


def done_ids():
    if not LOG.exists():
        return set()
    return {x["id"] for x in map(json.loads, LOG.read_text().splitlines()) if x.get("event") == "kept"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--lo", type=int, default=0); ap.add_argument("--hi", type=int, default=72)
    a = ap.parse_args()
    d = json.loads((ROOT / "research/datasets/oran_flooding_twin/manifest/design.json").read_text())
    fails, done = 0, done_ids()
    for i, r in enumerate(d["runs"][a.lo:a.hi]):
        if r["id"] in done:
            continue
        attempt = 0
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
                yaml.safe_dump(design_twin.scenario(r), f); path = f.name
            rc, o = sh([sys.executable, str(ROOT / "scripts/k8s/exp/run.py"), "run", path, "--tag", tag], 1800)
            pathlib.Path(path).unlink(missing_ok=True)
            camp = sorted(glob.glob(str(ROOT / ("artifacts/experiments/*_%s" % tag))))
            run = sorted(glob.glob(camp[-1] + "/runs/*/*"))[-1] if camp and glob.glob(camp[-1] + "/runs/*/*") else None
            problems = qa_twin.qa_run(run) if run else ["run.py rc %s %s" % (rc, o[-200:])]
            log(event="kept" if not problems else "failed", id=r["id"], attempt=attempt, run=run, problems=problems)
            if not problems:
                fails = 0
                break
            fails += 1
            if fails >= 3:
                log(event="stop", id=r["id"], problems=problems); sys.exit("3 failed attempts in a row: %s" % problems)
            recover()


if __name__ == "__main__":
    main()
