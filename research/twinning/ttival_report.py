#!/usr/bin/env python3
"""Validation report of the TTI-timed twin, excluding reps with known faults. Writes out_validate_tti_<band>.json, out_check_tti_<band>.json,
prints validate_twin results, MAC fidelity, threshold, c_t per second and over the gate window, KPM masking on seconds with traffic."""
import glob, json, pathlib, subprocess, sys
import numpy as np
sys.path.insert(0, "research/twinning")
import twin_check as TC
last = lambda p: sorted(glob.glob("artifacts/experiments/" + p))[-1]
TAG = sys.argv[1] if len(sys.argv) > 1 else "final2"
SETS = {b: [(last("*_ds-benign-twin-%s_%s" % (b, TAG)), None)] for b in ("P1", "P2", "P3", "P4")}
for b, sets in SETS.items():
    runs, acc = [], {k: [] for k in ("tu", "mu", "td", "md", "seen", "ct", "trust", "prof")}
    acc.update(windows=0, ul_clip=0, dl_clip=0, ul_floor=0, dl_floor=0)
    cw, ct, mk = [], [], []
    for d, skip in sets:
        scn = json.load(open(d + "/campaign.json"))["scenario"]
        specs = {(p["name"], u): v["ul"] for p in scn["phases"] for u, v in p.get("flows", {}).items() if "ul" in v}
        for r in sorted(glob.glob(d + "/runs/*/*")):
            if skip and r.split("/")[-1] in skip:
                continue
            runs.append(r)
            TC.check_run(pathlib.Path(r), b, acc, specs)
            for l in open(r + "/defense/features.jsonl"):
                x = json.loads(l)
                if "c_t_w" in x and "prof_ul_pps" in x and x["collect_ms"] % 1000 < 50 and (x["rate_ul_kbps"] * 125 >= 1000 or x["prof_ul_kbps"] * 125 >= 1000):  # KPM on its second phase only (stall at 15:35 moved it to 401 ms)
                    ct.append(x["c_t"]); cw.append(x["c_t_w"]); mk.append(x["kpm_masked"])
    out = subprocess.run([sys.executable, "research/twinning/validate_twin.py", b, "research/twinning/out_validate_%s_%s.json" % (TAG, b)] + runs, capture_output=True, text=True).stdout
    print(out.strip())
    tu, mu, td, md, seen = [np.concatenate(acc[k]) for k in ("tu", "mu", "td", "md", "seen")]
    ul, dl = TC.fidelity(tu, mu, seen), TC.fidelity(td, md, seen)
    ct, cw, mk = np.array(ct), np.array(cw), np.array(mk)
    res = {"band": b, "runs": runs, "windows": acc["windows"], "ul": ul, "dl": dl, "gate_seconds": int(ct.size), "ct_1s_q01_q99": TC.q(ct, (1, 99)), "ct_1s_outside": round(float((abs(ct) > .2).mean()), 4), "ct_w_q01_q99": TC.q(cw, (1, 99)), "ct_w_outside": round(float((abs(cw) > .2).mean()), 4), "masked_share": round(float(mk.mean()), 4)}
    pathlib.Path("research/twinning/out_check_%s_%s.json" % (TAG, b)).write_text(json.dumps(res, indent=1) + "\n")
    print(" MAC/target UL %.3f corr %.3f rel q01/50/99 %s | DL %.3f corr %.3f rel %s" % (ul["mac_over_target"], ul["corr"], ul["rel_q01_50_99"], dl["mac_over_target"], dl["corr"], dl["rel_q01_50_99"]))
    print(" thr 30 B: UL false %d miss %d | DL false %d miss %d (active UL %d DL %d)" % (ul["thresholds"][30]["false"], ul["thresholds"][30]["miss"], dl["thresholds"][30]["false"], dl["thresholds"][30]["miss"], ul["active_target"], dl["active_target"]))
    print(" gate seconds %d | c_t 1 s q01/q99 %s outside %.2f%% | 3 s q01/q99 %s outside %.2f%% | KPM masked %.2f%%" % (ct.size, res["ct_1s_q01_q99"], 100 * res["ct_1s_outside"], res["ct_w_q01_q99"], 100 * res["ct_w_outside"], 100 * res["masked_share"]))
