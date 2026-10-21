#!/usr/bin/env python3
"""Acceptance §7.3 "re-run any run from manifest + seed -> identical target schedule".

For every captured run dir, rebuild each flow's plan from the design manifest alone
(planbuilder.build_plan, the same call traffic.V4Flow makes) and compare it with the
v4_meta recorded in that run's traffic/flows.json (schedule params, mean size, target
mean). Also rebuilds every plan twice and asserts the per-second target series are
bit-identical (determinism of the seeded generators).

  .venv-ml/bin/python scripts/k8s/exp/v4traffic/check_reproducible.py <run_dir>...
Run dirs are .../runs/detection-off/rep-NN; rep-NN is manifest run NN-1.
"""
import json, math, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import planbuilder

MANIFEST = ROOT / "research/datasets/oran_flooding_v4/manifest/design.json"


def _close(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    return a == b


def _spec(flow):
    s = {k: v for k, v in flow.items() if k != "v4"}
    if "level_mbps" in s and "level" not in s:
        s["level"] = float(s.pop("level_mbps")) * 1e6 / 8.0
    s.setdefault("seed", 1)
    return s


def check_run(run_dir, runs):
    rep = int(re.search(r"rep-(\d+)", str(run_dir)).group(1))
    phases = runs[rep - 1]
    rec = json.loads((pathlib.Path(run_dir) / "traffic/flows.json").read_text())
    by_key = {(f["phase"], f["ue"]): f for f in rec}
    n, bad = 0, []
    for j, ph in enumerate(phases):
        pname = "p%02d_%s" % (j, ph["family"])
        for ue, dirs in ph["flows"].items():
            spec = _spec(dirs["ul"])
            got = by_key.get((pname, ue))
            if got is None:
                bad.append("%s/%s missing in flows.json" % (pname, ue)); continue
            T = int(ph["duration"])
            p1, m1 = planbuilder.build_plan(dict(spec), T, "dn", "ue", got["port"])
            p2, _ = planbuilder.build_plan(dict(spec), T, "dn", "ue", got["port"])
            n += 1
            if json.dumps(p1["seconds"]) != json.dumps(p2["seconds"]):
                bad.append("%s/%s non-deterministic plan" % (pname, ue))
            r = got.get("v4_meta", {})
            for k in ("seed", "model", "role", "backend", "mean_size", "params", "target_mean_bytes_s"):
                if not _close(m1.get(k), r.get(k)):
                    bad.append("%s/%s %s: rebuilt=%r recorded=%r" % (pname, ue, k, m1.get(k), r.get(k)))
    return rep, n, bad


def main(argv):
    runs = json.loads(MANIFEST.read_text())["runs"]
    total, fails = 0, 0
    for d in argv:
        rep, n, bad = check_run(d, runs)
        total += n
        fails += len(bad)
        print("rep-%02d: %d flows %s" % (rep, n, "OK" if not bad else "MISMATCH"))
        for b in bad:
            print("   ", b)
    print("REPRODUCIBLE: %s (%d flows, %d mismatches)" % ("PASS" if fails == 0 else "FAIL", total, fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
