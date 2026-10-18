#!/usr/bin/env python3
"""Gate X (plan Phase X): the layered xApp, its classifier interface and the dataset.

Usage: x_gate.py <out-dir>
       x_gate.py --evaluate <out-dir>

Gate R3 (r3_gate.py, slice mode) is the regression part of Gate X and is
run on its own. This gate checks the classifier path with light benign
traffic only (both UEs at 0.5 Mbit/s UL), the stub model
(scripts/k8s/classifier/stub_classifier.py) running on the xApp loopback:
  external  the stub labels UE2 "attack": the policy and actuators act on
            it exactly as on a rule decision (evidence from "external",
            level 1, quarantine handover acknowledged); UE1 untouched
  unknown   the stub answers "unknown": the rules decide (source
            "fallback"), no evidence for benign traffic
  sleep     the stub answers after 2 s (> timeoutMs): failures counted,
            the worker keeps up (a vector per UE and second, no sample dropped)
  down      no stub: failures counted, same as above
Checks also the dataset (KPI_Metrics_Features.jsonl): one vector per KPM
row of each SUPI, every field present, URR of the SUPI in the vectors.
"""
import csv
import io
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import r2_gate as r2  # noqa: E402
import r3_gate as r3  # noqa: E402

ROOT = r2.ROOT
STUB = ROOT / "scripts/k8s/classifier/stub_classifier.py"
FIELDS = ["supi", "seq", "at_ms", "collect_ms", "amf_ue_ngap_id", "rate_ul_kbps", "rate_dl_kbps", "prb_ul_pct", "prb_dl_pct",
          "cell_prb_ul_pct", "cell_prb_dl_pct", "others_ul", "others_dl", "class", "limit_ul_kbps", "limit_dl_kbps", "level",
          "limited", "label", "source"]
PHASE_S = 20


def xapp_sh(cmd, check=True):
    return r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "sh", "-c", cmd, check=check)


def stub(mode, attack=()):
    xapp_sh("pkill -f stub_classifier.py; true", check=False)
    if mode == "down":
        return
    xapp_sh("nohup python3 /tmp/stub_classifier.py --mode %s %s >/tmp/stub.log 2>&1 &"
            % (mode, ("--attack " + " ".join(attack)) if attack else ""))
    time.sleep(2)


def phase(result, name, mode, attack=()):
    stub(mode, attack)
    before = r3.state()
    t0 = time.time()
    r2.run_flows("ul", PHASE_S, {"oai-nr-ue": "500K", "oai-nr-ue2": "500K"})
    after = r3.state()
    result["phases"][name] = {"window_unix": [round(t0, 3), round(time.time(), 3)], "mode": mode,
                              "classifier_before": before["classifier"], "classifier_after": after["classifier"],
                              "dropped": [before["dropped_samples"], after["dropped_samples"]],
                              "levels": {u["supi"]: u["level"] for u in after["ues"]}}
    print("%-9s %s levels %s" % (name, after["classifier"], result["phases"][name]["levels"]), flush=True)


def evaluate(out):
    result = json.loads((out / "result.json").read_text())
    feats = [json.loads(l) for l in (out / "features.jsonl").read_text().splitlines() if l.strip()]
    events = [json.loads(l) for l in (out / "defense.jsonl").read_text().splitlines() if l.strip()]
    rows = list(csv.DictReader(io.StringIO((out / "KPI_Metrics.csv").read_text())))
    s1, s2 = r3.SUPI["oai-nr-ue"], r3.SUPI["oai-nr-ue2"]
    ph, checks = result["phases"], {}

    def inside(ms, name, pad=2000):
        w = ph[name]["window_unix"]
        return w[0] * 1000 <= ms <= w[1] * 1000 + pad

    ev = [e for e in events if e["type"] == "evidence" and inside(e["at_ms"], "external")]
    act = [e for e in events if e["type"] == "action" and e["supi"] == s2 and e["http"] == 200 and e["max_prb_ratio"] < 100
           and inside(e["at_ms"], "external", 5000)]
    checks["external_drives_policy"] = {
        "ok": any(e["supi"] == s2 and e.get("classifier") == "external" for e in ev) and not any(e["supi"] == s1 for e in ev)
              and bool(act) and ph["external"]["levels"].get(s2, 0) >= 1 and ph["external"]["levels"].get(s1, 0) == 0,
        "evidence": [{k: e.get(k) for k in ("supi", "kind", "classifier", "decision_id")} for e in ev],
        "ue2_action": act[0].get("slice") if act else None}

    for name in ("unknown", "sleep", "down"):
        b, a = ph[name]["classifier_before"], ph[name]["classifier_after"]
        lines = [f for f in feats if inside(f["at_ms"], name, 0) and f["at_ms"] >= ph[name]["window_unix"][0] * 1000 + 3000]
        srcs = sorted({f.get("source") for f in lines})
        w = ph[name]["window_unix"]
        per_s = len(lines) / max(1.0, w[1] - w[0] - 3) / 2
        evid = [e for e in events if e["type"] == "evidence" and inside(e["at_ms"], name)]
        failures = a["failures"] - b["failures"]
        ok = (a["fallbacks"] > b["fallbacks"] and srcs == ["fallback"] and not evid
              and ph[name]["dropped"][0] == ph[name]["dropped"][1] and per_s >= 0.8
              and (failures == 0 if name == "unknown" else failures > 0))
        checks["fallback_" + name] = {"ok": ok, "fallbacks": a["fallbacks"] - b["fallbacks"], "failures": failures,
                                      "sources": srcs, "vectors_per_ue_s": round(per_s, 2), "evidence": len(evid),
                                      "last_error": a["last_error"]}

    t0, t1 = result["started_unix"] * 1000, result["ended_unix"] * 1000
    missing = sorted({k for f in feats for k in FIELDS if k not in f and f.get("source") is not None})
    counts = {}
    for supi in (s1, s2):
        k = sum(1 for r in rows if r.get("SUPI") == supi and r.get("Collect Time (UNIX us)")
                and t0 <= int(r["Collect Time (UNIX us)"]) / 1000 <= t1)
        f = sum(1 for x in feats if x["supi"] == supi and t0 <= x["collect_ms"] <= t1)
        u = sum(1 for x in feats if x["supi"] == supi and t0 <= x["collect_ms"] <= t1 and "urr_ul_kbps" in x)
        counts[supi] = {"kpm_rows": k, "vectors": f, "with_urr": u}
    checks["dataset"] = {"ok": not missing and all(c["kpm_rows"] and abs(c["vectors"] - c["kpm_rows"]) <= 2
                                                    and c["with_urr"] >= 0.9 * c["vectors"] for c in counts.values()),
                         "missing_fields": missing, "counts": counts}
    result["checks"] = checks
    result["status"] = "PASS" if all(c["ok"] for c in checks.values()) else "FAIL"
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "checks": checks}, indent=2))
    return 0 if result["status"] == "PASS" else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = pathlib.Path(args[0])
    if "--evaluate" in sys.argv:
        return evaluate(out)
    out.mkdir(parents=True, exist_ok=True)
    run = (ROOT / "artifacts/k8s/state/current-staged-run").read_text().strip()
    for dep in r2.UES:
        r3.wait_ip(dep)
    pod = r2.kubectl("-n", "near-rt-ric", "get", "pod", "-l", "oai-lab/component=xapp", "-o",
                     "jsonpath={.items[0].metadata.name}").strip()
    r2.kubectl("-n", "near-rt-ric", "cp", str(STUB), pod + ":/tmp/stub_classifier.py", "-c", "xapp")
    result = {"run": run, "started_unix": round(time.time(), 3), "phases": {}}
    r3.http("POST", "/v1/defense/enabled", {"enabled": True})
    r3.reset_both()
    for d, c in (("oai-nr-ue", "default"), ("oai-nr-ue2", "default")):
        r3.http("POST", "/v1/defense/policy", {"supi": r3.SUPI[d], "class": c})
    print("drain", r3.wait_drain_all(), flush=True)
    code, body = r3.http("POST", "/v1/defense/classifier", {"kind": "external", "endpoint": "http://127.0.0.1:8091/classify",
                                                           "timeoutMs": 200})
    if code != 200:
        raise SystemExit("classifier endpoint: %s %s" % (code, body))
    try:
        phase(result, "external", "answer", [r3.SUPI["oai-nr-ue2"]])
        r3.reset_both()
        time.sleep(3)
        phase(result, "unknown", "unknown")
        phase(result, "sleep", "sleep")
        phase(result, "down", "down")
    finally:
        stub("down")
        r3.http("POST", "/v1/defense/classifier", {"kind": "rules"})
        r3.reset_both()
    result["ended_unix"] = round(time.time(), 3)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    time.sleep(3)
    base = "/artifacts/runs/" + run + "/"
    t0 = int(result["started_unix"] * 1000)

    def tail(name):
        raw = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", base + name, timeout=90, check=False)
        return "\n".join(l for l in raw.splitlines() if l.strip() and json.loads(l).get("at_ms", 0) >= t0 - 5000) + "\n"

    (out / "features.jsonl").write_text(tail("KPI_Metrics_Features.jsonl"))
    (out / "defense.jsonl").write_text(tail("KPI_Metrics_Defense.jsonl"))
    raw = r2.ex("near-rt-ric", "oai-lab-xapp", "xapp", "cat", base + "KPI_Metrics.csv", timeout=90)
    lines = raw.splitlines(True)
    keep = [lines[0]] + [l for l, r in zip(lines[1:], csv.DictReader(io.StringIO(raw)))
                         if r.get("Collect Time (UNIX us)") and int(r["Collect Time (UNIX us)"]) / 1000 >= t0 - 5000]
    (out / "KPI_Metrics.csv").write_text("".join(keep))
    return evaluate(out)


if __name__ == "__main__":
    sys.exit(main())
