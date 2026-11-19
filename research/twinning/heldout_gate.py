#!/usr/bin/env python3
"""Held-out check of the gate, run once: I-796 and II-2650 windows replayed on the testbed, honest traffic. Refuses to run if its result file exists. Usage: heldout_gate.py"""
import glob, json, pathlib, sys
import numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/k8s/exp/v4traffic"), str(ROOT / "scripts/ml")]
import qa_twin, build_dataset_twin as B
OUT = ROOT / "research/twinning/out_heldout_gate.json"
if OUT.exists():
    sys.exit("result exists, the check is run once")
res = {}
for band in ("P1", "P2", "P3", "P4"):
    camp = sorted(glob.glob(str(ROOT / ("artifacts/experiments/*_ds-heldout-twin-%s_heldoutgate" % band))))[-1]
    frames, dropped = [], {}
    for r in sorted(glob.glob(camp + "/runs/*/*")):
        q = qa_twin.qa_run(r, 10)
        if q:
            dropped[r[-6:]] = q
            continue
        frames.append(B.build_run(r))
    d = pd.concat(frames)
    g = d[(d.rate_ul_kbps * 125 >= 1000) | (d.prof_ul_kbps * 125 >= 1000)]
    a = dict(reps=len(frames), dropped=dropped, gate_seconds=len(g), out_1s=round(100 * float((g.c_t.abs() > .2).mean()), 2), out_3s=round(100 * float((g.c_t_w.abs() > .2).mean()), 2), masked_node=round(100 * float(g.kpm_masked.mean()), 2), masked_ue=round(100 * float(g.kpm_masked_ue.mean()), 2))
    a["pass"] = bool(a["out_3s"] <= 5 and a["masked_node"] <= 5 and a["masked_ue"] <= 5)
    res[band] = a
    print(band, a)
res["family_pass"] = all(res[b]["pass"] for b in ("P1", "P2", "P3", "P4"))
OUT.write_text(json.dumps(res, indent=1) + "\n")
print("all bands pass:", res["family_pass"])
