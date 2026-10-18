#!/usr/bin/env python3
"""Gate CL-1 (docs/CLOSED-LOOP-FRAMEWORK.md 11): the A1-EI path carries more
than one information type, losing and duplicating nothing.

Usage: cl1_gate.py <out-dir> [--minutes N] [--keep]
       cl1_gate.py --evaluate <out-dir>

Turns on the producer's synthetic type oai-test_1.0.0 (one record per second
per UE, one sequence for all UEs) and the adapter stream
test=oai-test-nearrt@oai-test_1.0.0, waits until the EI job is ENABLED,
samples N minutes (default 10), then compares what the producer published
(envelopes.jsonl) with what the xApp stored (core-received.jsonl):
  loss       every published record of the window reached the xApp
  duplicate  no event ID stored twice
  rate       >= 0.95 records / s per UE
  latency    producer generation -> xApp storage, p95 <= 4 s
  errors     no envelope rejected by the xApp
  urr        URR still delivered during the window (>= 0.45 / s per UE: the
             idle period of OAI is ~2 s and the gate runs without traffic)
Without --keep the test type and stream are turned off again (Helm values
producer.testInfoType, adapter.testJob;
the ICS job stays, DISABLED, as the producer no longer offers the type).
"""
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/k8s"))
sys.path.insert(0, str(ROOT / "scripts/k8s/exp"))
import staged  # noqa: E402
from lab import ex  # noqa: E402

TEST_TYPE = "oai-test_1.0.0"
STREAM = "test=oai-test-nearrt@oai-test_1.0.0"
JOB = "oai-test-nearrt"
RATE_MIN = 0.95
# URR without traffic: OAI reports every ~2 s (idle phase of
# 20261010-161707_ingest-two-sources_fix: 15 reports / 30 s per UE); the gate
# runs without traffic, so URR must keep at least that idle rate
URR_IDLE_MIN = 0.45
LAT_P95_MS = 4000
DRAIN_S = 15

GET = """
import json,ssl,sys,urllib.request
c=ssl.create_default_context();c.check_hostname=False;c.verify_mode=ssl.CERT_NONE
out={}
for name,u in json.loads(sys.argv[1]).items():
    try:out[name]=json.loads(urllib.request.urlopen(u,timeout=10,context=c).read())
    except Exception as e:out[name]={"error":str(e)}
print(json.dumps(out))
"""


def status():
    urls = {"urr": "https://127.0.0.1:8443/v1/urr/status", "core": "https://127.0.0.1:8443/v1/core/status",
            "adapter": "https://a1-ei-adapter.near-rt-ric.svc.cluster.local:8443/v1/delivery/status"}
    return json.loads(ex("near-rt-ric", "oai-lab-xapp", "xapp", "python3", "-c", GET, json.dumps(urls)))


def configure(on):
    staged.helm("non-rt-ric", "upgrade", "non-rt-ric", staged.DEPLOY / "charts/non-rt-ric", "--reuse-values",
                "--set", "producer.testInfoType=" + (TEST_TYPE if on else ""), "--timeout", "5m", timeout=360)
    staged.helm("near-rt-ric", "upgrade", "near-rt-ric", staged.DEPLOY / "charts/near-rt-ric", "--reuse-values",
                "--set", "adapter.testJob=" + (STREAM if on else ""), "--timeout", "5m", timeout=360)
    staged.ready("non-rt-ric", "deployment", "urr-ei-producer")
    staged.ready("near-rt-ric", "deployment", "a1-ei-adapter")


def tail(ns, deploy, container, path):
    return ex(ns, deploy, container, "tail", "-c", "30000000", path, timeout=180, check=False)


def run(out, minutes, keep):
    out.mkdir(parents=True, exist_ok=True)
    configure(True)
    deadline = time.time() + 180
    while True:
        st = status()
        if st.get("adapter", {}).get("jobs", {}).get(JOB) == "ENABLED":
            break
        if time.time() > deadline:
            raise SystemExit("EI job %s not ENABLED: %s" % (JOB, st.get("adapter")))
        time.sleep(5)
    time.sleep(5)  # first records of the new producer pod settle
    before, t0 = status(), time.time()
    print("sampling %d min" % minutes, flush=True)
    time.sleep(minutes * 60)
    t1 = time.time()
    time.sleep(DRAIN_S)
    after = status()
    (out / "status.json").write_text(json.dumps({"window_unix": [t0, t1], "before": before, "after": after}, indent=2) + "\n")
    (out / "producer_envelopes.jsonl").write_text(tail("non-rt-ric", "urr-ei-producer", "artifacts", "/var/lib/urr-ei/envelopes.jsonl"))
    (out / "xapp_core_received.jsonl").write_text(
        tail("near-rt-ric", "oai-lab-xapp", "xapp", "/artifacts/runs/%s/core-received.jsonl" % staged.run_id()))
    if not keep:
        configure(False)
    return evaluate(out)


def jsonl(p):
    rows = []
    for line in p.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def evaluate(out):
    st = json.loads((out / "status.json").read_text())
    t0, t1 = st["window_unix"]
    key = lambda r: (r["source"], r["source_epoch"], r["seq"])
    produced = {key(r): r for r in jsonl(out / "producer_envelopes.jsonl")
                if r.get("type") == TEST_TYPE and t0 * 1000 <= r["body"]["generated_unix_ms"] <= t1 * 1000}
    stored = [x for x in jsonl(out / "xapp_core_received.jsonl") if x.get("kind") == "test"]
    ids = [x["event_id"] for x in stored]
    received = {key(x["report"]): x for x in stored}
    missing = sorted(k for k in produced if k not in received)
    lat = [received[k]["received_unix_ms"] - r["body"]["generated_unix_ms"] for k, r in produced.items() if k in received]
    dur = t1 - t0
    per_supi = {}
    for r in produced.values():
        per_supi[r["supi"]] = per_supi.get(r["supi"], 0) + 1
    rcv_supi = {}
    for k, r in produced.items():
        if k in received:
            rcv_supi[r["supi"]] = rcv_supi.get(r["supi"], 0) + 1
    err = lambda s: s.get("core", {}).get("test", {}).get("errors", 0)
    urr = st["after"]["urr"].get("received", 0) - st["before"]["urr"].get("received", 0)
    n_ue = max(1, len(per_supi))
    checks = {
        "loss": {"pass": bool(produced) and not missing, "published": len(produced), "missing": len(missing), "first_missing": [list(m) for m in missing[:5]]},
        "duplicate": {"pass": len(ids) == len(set(ids)), "stored_lines": len(ids), "unique": len(set(ids)),
                      "transport_duplicates": st["after"]["core"].get("test", {}).get("duplicates", 0) - st["before"]["core"].get("test", {}).get("duplicates", 0)},
        "rate": {"pass": bool(rcv_supi) and all(n / dur >= RATE_MIN for n in rcv_supi.values()),
                 "per_supi_per_s": {s: round(n / dur, 3) for s, n in rcv_supi.items()}},
        "latency": {"pass": bool(lat) and pct(lat, 0.95) <= LAT_P95_MS, "p50_ms": pct(lat, 0.5), "p95_ms": pct(lat, 0.95),
                    "max_ms": max(lat) if lat else None, "mean_ms": round(statistics.mean(lat), 1) if lat else None},
        "errors": {"pass": err(st["after"]) - err(st["before"]) == 0, "rejected": err(st["after"]) - err(st["before"])},
        "urr": {"pass": urr / dur / n_ue >= URR_IDLE_MIN, "min_per_ue_per_s": URR_IDLE_MIN, "received": urr, "per_ue_per_s": round(urr / dur / n_ue, 3)},
    }
    verdict = all(c["pass"] for c in checks.values())
    result = {"gate": "CL-1", "verdict": "PASS" if verdict else "FAIL", "window_s": round(dur, 1), "ues": sorted(per_supi), "checks": checks}
    (out / "cl1_gate.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if verdict else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--evaluate"]:
        sys.exit(evaluate(pathlib.Path(a[1])))
    if not a:
        sys.exit(__doc__)
    minutes = int(a[a.index("--minutes") + 1]) if "--minutes" in a else 10
    sys.exit(run(pathlib.Path(a[0]), minutes, "--keep" in a))
