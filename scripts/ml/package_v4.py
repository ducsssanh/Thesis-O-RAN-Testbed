#!/usr/bin/env python3
"""Package the v4 campaign into the plan-§7.1 layout.

  .venv-ml/bin/python scripts/ml/package_v4.py --out research/datasets/oran_flooding_v4 CAMP_DIR [CAMP_DIR ...]

For every manifest run it picks the newest meta_run_ok=1 attempt (by t_start) and
records EVERY attempt -- failed ones too, with their reason -- in manifest/runs_index.json
(failed runs are kept, never dropped silently). Then, into --out:
  manifest/runs/<run_id>.json   per-run plan: manifest phases (seed, assignments) + attempt
  raw/<run_id>/                 kpm.jsonl, urr.jsonl, prof.jsonl, achieved.jsonl, flows.json
  rows.parquet / rows.csv       build_dataset_v4 over the selected runs
  reproducibility.txt           check_reproducible.py
  unit_tests.txt                test_build_dataset_v4 + test_schedules + test_backends
  qa_report.md                  qa_v4 (with the reproducibility result)
  calibration.md                measured calibration (phase0_v4.md) + arrival-lag from the rows
"""
import argparse, csv, json, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv-ml/bin/python")
V4 = ROOT / "scripts/k8s/exp/v4traffic"
MANIFEST = ROOT / "research/datasets/oran_flooding_v4/manifest/design.json"


def attempts(camps):
    """All rep dirs of all camp dirs, oldest camp first."""
    out = []
    for c in sorted((pathlib.Path(x).resolve() for x in camps), key=lambda p: p.name):
        for rd in sorted((c / "runs" / "detection-off").glob("rep-*")):
            try:
                meta = json.loads((rd / "run.json").read_text())
            except (OSError, ValueError):
                meta = {}
            err = (rd / "error.txt").read_text().strip()[:300] if (rd / "error.txt").exists() else ""
            rep = int(rd.name.split("-")[1])
            t0 = meta.get("t_start") or 0
            integ = meta.get("integrity") or {}
            out.append({"rep": rep, "dir": str(rd.relative_to(ROOT)),
                        "attempt_id": meta.get("attempt_id") or "%s_rep-%02d@%d" % (c.name, rep, t0),
                        "t_start": t0, "camp": c.name, "meta_run_ok": meta.get("meta_run_ok", 0),
                        "invalid_reason": "; ".join(integ.get("reasons") or []) if not meta.get("meta_run_ok") else "",
                        "status": meta.get("status"), "error": err,
                        "prof_assert": meta.get("prof_assert")})
    return out


def run_id(a):
    return "%s_rep-%02d" % (a["camp"], a["rep"])


def copy_raw(rd, dst):
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rd / "raw/kpm.jsonl", dst / "kpm.jsonl")
    shutil.copy2(rd / "core/urr_received.jsonl", dst / "urr.jsonl")
    with open(rd / "core/core_received.jsonl") as f, open(dst / "prof.jsonl", "w") as g:
        for line in f:
            if '"kind": "profile"' in line or '"kind":"profile"' in line:
                g.write(line)
    shutil.copy2(rd / "traffic/flows.json", dst / "flows.json")
    with open(dst / "achieved.jsonl", "w") as g:          # per-second achieved, per flow
        for p in sorted((rd / "traffic").glob("*.csv")):
            with open(p) as f:
                for r in csv.DictReader(f):
                    g.write(json.dumps({"flow": p.stem, **r}) + "\n")


def sh(args, out_file=None):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if out_file:
        pathlib.Path(out_file).write_text(r.stdout + r.stderr)
    return r.returncode, r.stdout


def calibration_md(out, df):
    src = (ROOT / "research/testbed/phase0_v4.md").read_text()
    measured = src[src.index("### §3.2 Calibration — now MEASURED"):]
    L = ["# v4 calibration (measured on the testbed)\n",
         "All numbers below come from live measurement; sources are `research/testbed/phase0_v4.md`, "
         "`research/testbed/calib_v4.jsonl`, `research/testbed/calib_pps_v4.json` and, for the arrival "
         "lag, the campaign rows themselves.\n",
         "## Arrival lag of URR / profiler at the row's second (this campaign)\n",
         "`*_age_s` = t − source_ts of the latest record with arrival_ts ≤ t (causal as-of join).\n",
         "| stream | n | median | p90 | p99 | max |\n|---|---:|---:|---:|---:|---:|"]
    for k in ("kpm", "urr", "prof"):
        s = df[f"meta_{k}_age_s"].dropna()
        L.append(f"| {k} | {len(s)} | {s.median():.2f} | {s.quantile(.9):.2f} | {s.quantile(.99):.2f} | {s.max():.2f} |")
    L.append("\n## Rate, MTU, pps ceilings and load levels (Phase 0, 2026-10-20)\n")
    L.append(measured.replace("### ", "### "))
    (out / "calibration.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("camps", nargs="+")
    a = ap.parse_args()
    out = ROOT / a.out if not pathlib.Path(a.out).is_absolute() else pathlib.Path(a.out)
    man = json.loads(MANIFEST.read_text())
    att = attempts(a.camps)
    chosen = {}
    for x in sorted(att, key=lambda a: a["t_start"]):     # newest VALID attempt (by start time) wins
        if x["meta_run_ok"] == 1:
            chosen[x["rep"]] = x
    for x in att:
        x["selected"] = chosen.get(x["rep"]) is x
    n_runs = man["n_runs"]
    missing = [r for r in range(1, n_runs + 1) if r not in chosen]
    (out / "manifest/runs").mkdir(parents=True, exist_ok=True)
    (out / "manifest/runs_index.json").write_text(json.dumps(
        {"n_manifest_runs": n_runs, "n_selected": len(chosen), "missing_reps": missing,
         "attempts": att}, indent=1) + "\n")
    sel_dirs = []
    for rep, x in sorted(chosen.items()):
        rd = ROOT / x["dir"]
        rid = run_id(x)
        (out / "manifest/runs" / (rid + ".json")).write_text(json.dumps(
            {"run_id": rid, "rep": rep, "manifest_index": rep - 1, "design_seed": man["seed"],
             "phases": man["runs"][rep - 1], "attempt": x}, indent=1) + "\n")
        copy_raw(rd, out / "raw" / rid)
        sel_dirs.append(str(rd))
    print("selected %d/%d runs; missing reps %s" % (len(chosen), n_runs, missing))

    rc, o = sh([PY, "-I", "scripts/ml/build_dataset_v4.py", "--out", str(out), *sel_dirs])
    print(o)
    if rc:
        sys.exit("build failed")
    rc_r, _ = sh([PY, str(V4 / "check_reproducible.py"), *sel_dirs], out / "reproducibility.txt")
    ut = []
    for t in ("scripts/ml/test_build_dataset_v4.py", str(V4 / "test_schedules.py"), str(V4 / "test_backends.py")):
        rc_t, o_t = sh([PY, t])
        ut.append("## %s  (exit %d)\n%s" % (t, rc_t, o_t.strip().splitlines()[-1] if o_t.strip() else ""))
    (out / "unit_tests.txt").write_text("\n\n".join(ut) + "\n")
    import pandas as pd
    calibration_md(out, pd.read_parquet(out / "rows.parquet"))
    rc_q, _ = sh([PY, "scripts/ml/qa_v4.py", "--data", str(out), "--repro", str(out / "reproducibility.txt"), *sel_dirs])
    print("repro exit %d, qa exit %d; unit tests:\n%s" % (rc_r, rc_q, "\n".join(ut)))


if __name__ == "__main__":
    main()
