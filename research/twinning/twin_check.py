#!/usr/bin/env python3
"""Per-band checks on benign twin validation runs, beside validate_twin.py: how MAC bytes follow the target per second, the
active threshold (false active / missed seconds), and the c_t of seconds with traffic (TRAFFIC-TWINNING-PLAN §0a).

Usage: twin_check.py <band> <out.json> <campaign dir>...
c_t is read as the xApp wrote it in defense/features.jsonl, inside the replayed part of each window. A second counts as having
traffic if the profiler saw UL packets or KPM reported UL bytes in it."""
import csv, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/k8s/exp/v4traffic"))
import planbuilder as PB

LEN, THRESHOLDS, BAND = 75, (0, 30, 40, 47), 0.2


def q(x, p=(1, 5, 50, 95, 99)):
    return [round(float(v), 3) for v in np.percentile(x, p)] if len(x) else None


def mac_by_ue(run):
    out = {}
    with open(run / "ran/mac_stats.csv") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r["ue"], []).append((float(r["stat_unix"]), int(r["ul_sdu_bytes"]), int(r["dl_sdu_bytes"])))
    return {k: np.array(v) for k, v in out.items()}


def features_by_supi(run):
    out = {}
    with open(run / "defense/features.jsonl") as fh:
        for line in fh:
            r = json.loads(line)
            out.setdefault(r["supi"], []).append(r)
    return out


def targets(fl, spec):
    """Bytes per second the plan asked for, UL and DL. Rebuilt from the seed the flow recorded."""
    plan, _ = PB.build_plan({**spec, "seed": fl["v4_meta"]["seed"]}, LEN, "x", "x", 1)
    return np.array([x["bytes"] for x in plan["seconds"]], float), np.array([x["bytes"] for x in plan["dl_seconds"]], float)


def check_run(run, band, acc, specs):
    mac, feats = mac_by_ue(run), features_by_supi(run)
    supis = sorted(feats)
    for fl in json.loads((run / "traffic/flows.json").read_text()):
        if fl.get("model") != "real_window" or fl["v4_meta"].get("band") != band:
            continue
        m, s0 = mac[fl["ue"]], fl["replay_start_at"]
        tu, td = targets(fl, specs[fl["phase"], fl["ue"]])
        mu, md, seen = np.zeros(LEN), np.zeros(LEN), np.zeros(LEN, bool)
        du, dd, te = np.diff(m[:, 1]), np.diff(m[:, 2]), m[1:, 0]
        for i in range(LEN):
            k = int(np.argmin(np.abs(te - (s0 + i + 1))))
            if abs(te[k] - (s0 + i + 1)) < 0.5:
                mu[i], md[i], seen[i] = du[k], dd[k], True
        for name, v in (("tu", tu), ("mu", mu), ("td", td), ("md", md), ("seen", seen)):
            acc[name].append(v)
        acc["windows"] += 1
        acc["ul_clip"] += fl["v4_meta"].get("ul_clipped_s", 0)
        acc["dl_clip"] += fl["v4_meta"].get("dl_clipped_s", 0)
        acc["ul_floor"] += fl["v4_meta"].get("ul_floored_s", 0)
        acc["dl_floor"] += fl["v4_meta"].get("dl_floored_s", 0)
        supi = supis[int(fl["ue"][-1]) - 1]
        for r in feats[supi]:
            if s0 * 1000 <= r["at_ms"] < (s0 + LEN) * 1000 and (r.get("prof_ul_pps", 0) > 0 or r["rate_ul_kbps"] > 0):
                acc["ct"].append(r.get("c_t", 0.0))
                acc["trust"].append(r["kpm_trust"])
                acc["prof"].append(r.get("prof_ul_kbps", 0) * 125)


def fidelity(t, m, seen):
    t, m = t[seen], m[seen]
    big = t >= 1000
    out = {"target_MB": round(t.sum() / 1e6, 3), "mac_over_target": round(m.sum() / max(t.sum(), 1), 3),
           "corr": round(float(np.corrcoef(t, m)[0, 1]), 5), "rel_q01_50_99": q(m[big] / t[big], (1, 50, 99)), "n_big": int(big.sum()),
           "active_target": int((t > 0).sum()), "idle_target": int((t == 0).sum())}
    false_b = m[(t == 0) & (m > 0)]
    out["false_bytes_q50_90_100"] = q(false_b, (50, 90, 100))
    out["thresholds"] = {th: {"false": int(((t == 0) & (m > th)).sum()), "miss": int(((t > 0) & (m <= th)).sum())} for th in THRESHOLDS}
    return out


def main():
    band, out, dirs = sys.argv[1], Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]]
    acc = {k: [] for k in ("tu", "mu", "td", "md", "seen", "ct", "trust", "prof")}
    acc.update(windows=0, ul_clip=0, dl_clip=0, ul_floor=0, dl_floor=0)
    for d in dirs:
        scn = json.loads((d / "campaign.json").read_text())["scenario"]
        specs = {(p["name"], u): v["ul"] for p in scn["phases"] for u, v in p.get("flows", {}).items() if "ul" in v}
        for f in sorted(d.rglob("flows.json")):
            check_run(f.parent.parent, band, acc, specs)
    tu, mu, td, md, seen = [np.concatenate(acc[k]) for k in ("tu", "mu", "td", "md")] + [np.concatenate(acc["seen"])]
    ct, prof = np.array(acc["ct"]), np.array(acc["prof"])
    res = {"band": band, "windows": acc["windows"], "seconds_without_sample": int((~seen).sum()),
           "clipped_s": {"ul": acc["ul_clip"], "dl": acc["dl_clip"]}, "floored_s": {"ul": acc["ul_floor"], "dl": acc["dl_floor"]},
           "ul": fidelity(tu, mu, seen), "dl": fidelity(td, md, seen),
           "c_t": {"n": int(ct.size), "q01_05_50_95_99": q(ct), "min_max": [round(float(ct.min()), 3), round(float(ct.max()), 3)],
                   "outside_band": round(float((np.abs(ct) > BAND).mean()), 5),
                   "ge_10kB_n": int((prof >= 1e4).sum()), "ge_10kB_q01_50_99": q(ct[prof >= 1e4], (1, 50, 99)),
                   "ge_10kB_outside": round(float((np.abs(ct[prof >= 1e4]) > BAND).mean()), 5) if (prof >= 1e4).any() else None,
                   "trust_q01_50": q(np.array(acc["trust"]), (1, 50))}}
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
