#!/usr/bin/env python3
"""Rebuild the kept live runs offline as dataset episodes, so offline detectors (R050 ensemble, baselines) are scored on the
same traffic as the live xApp. Writes rows.parquet, episodes (masked and, with EP_NOMASK=1 semantics, unmasked for the
KPM-only baseline), split_live.json (train = the final training runs, test = the live runs) and run_groups_live.json.
Only the honest scenario of an episode is real live traffic (the KPM tamper of a live run is already in its KPM); the other
scenarios are the usual offline injections and are not used for the live tables.
Usage: live_episodes.py <manifest dir> <out dir>"""
import json, os, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
M, O = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); O.mkdir(parents=True, exist_ok=True)
L = [json.loads(l) for l in open(M / "campaign_log.jsonl")]
runs = {}
for x in L:
    if x["event"] == "kept":
        runs[x["id"]] = x["run"]
runs = [runs[k] for k in sorted(runs)]
py = sys.executable
subprocess.run([py, str(ROOT / "scripts/ml/build_dataset_twin.py"), "--out", str(O)] + runs, check=True)
subprocess.run([py, str(ROOT / "scripts/ml/clf_features.py"), str(O / "rows.parquet"), str(O / "episodes31_live.pkl")], check=True)
subprocess.run([py, str(ROOT / "scripts/ml/clf_features.py"), str(O / "rows.parquet"), str(O / "episodes31_live_nomask.pkl")], check=True,
               env=dict(os.environ, EP_NOMASK="1"))
ids = ["/".join(pathlib.Path(r).parts[-4:]) for r in runs]
final = json.load(open(ROOT / "artifacts/clf/split_final.json"))
json.dump({"train": final["train"], "test": ids}, open(O / "split_live.json", "w"))
g = json.load(open(ROOT / "artifacts/clf/run_groups_all.json"))
g.update({r: "live:" + r for r in ids})
json.dump(g, open(O / "run_groups_live.json", "w"))
print("live runs", len(ids))
