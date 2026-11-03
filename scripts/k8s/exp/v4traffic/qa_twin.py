#!/usr/bin/env python3
"""Per-run QA of a twin campaign run: returns the problems that make it unusable. A run is kept only if it has none. Usage: qa_twin.py <run dir>..."""
import gzip, json, pathlib, sys
import numpy as np
BETA = 57
MIN_DELIVERED = {"L1": .85, "L2": .5, "L3": .85}        # L2 is measured over the bursts of a real window, with bytes spilling over a second


def qa_run(run, expected_phases=6):
    run = pathlib.Path(run); out = []
    if not (run / "traffic/flows.json").exists():
        return ["no data"]
    meta = json.loads((run / "run.json").read_text())
    if meta.get("status") != "ok":
        out.append("status %s" % meta.get("status"))
    flows = json.loads((run / "traffic/flows.json").read_text())
    ue = {u: m["supi"] for u, m in meta["ues"].items()}
    F = {}
    for l in open(run / "defense/features.jsonl"):
        x = json.loads(l)
        F.setdefault(x["supi"], {})[x["at_ms"] // 1000] = x
    all_x = [x for u in F.values() for x in u.values()]
    if np.mean([min(x["collect_ms"] % 1000, 1000 - x["collect_ms"] % 1000) > 100 for x in all_x]) > .01:
        out.append("KPM phase off")
    if np.mean(["prof_ul_pps" not in x for x in all_x]) > .01:
        out.append("profile missing")
    for n in ("ue1", "ue2"):
        if gzip.open(run / ("logs/%s.log.gz" % n), "rt", errors="ignore").read().count("max RETX"):
            out.append("RLC failure " + n)
    if (run / "defense/events.jsonl").exists() and (run / "defense/events.jsonl").stat().st_size:
        out.append("defence acted")
    mac = {}
    for x in open(run / "ran/mac_stats.csv").read().splitlines()[1:]:
        f = x.split(","); mac.setdefault(f[2], []).append((float(f[0]), f[1], int(f[4]), int(f[5])))
    twins = [f for f in flows if (f.get("v4_meta") or {}).get("model") == "real_window"]
    if len(twins) != 2 * expected_phases:
        out.append("twin flows %d" % len(twins))
    for f in twins:
        m = mac.get(f["ue"]) or []
        t = [r for r in m if f["replay_start_at"] <= r[0] <= f["replay_start_at"] + 76]
        if len(t) < 70 or len({r[1] for r in t}) > 1:
            out.append("MAC gap or new RNTI %s %s" % (f["phase"], f["ue"]))
            continue
        target = f["v4_meta"]["target_dl_mean_bytes_s"] * 75
        if target >= 5000 and t[-1][3] - t[0][3] < target / 2:
            out.append("dead DL %s %s" % (f["phase"], f["ue"]))
    for f in flows:
        m = f.get("v4_meta") or {}
        if m.get("model") != "flood_overlay":
            continue
        if f.get("backend_failed"):
            out.append("generator failed %s %s" % (f["phase"], f["ue"]))
        if m.get("role") != "attack":
            continue
        tw = next(x for x in twins if x["phase"] == f["phase"] and x["ue"] == f["ue"])
        z = np.load(pathlib.Path(__file__).resolve().parents[4] / "research/twinning/benign_windows.npz")
        twin = z["ul_" + tw["v4_meta"]["band"]][tw["v4_meta"]["window"]["index"]]
        s0, ts, S = int(f["attack_start_at"]), int(round(tw["replay_start_at"])), F[ue[f["ue"]]]
        ex = []
        for i in np.flatnonzero(m["attack_active"]):
            x = S.get(s0 + i)
            if x and "prof_ul_pps" in x:
                j = s0 + i - ts
                ex.append(max(x["prof_ul_kbps"] * 125 - BETA * x["prof_ul_pps"], 0) - (float(twin[j]) if 0 <= j < 75 else 0.0))
        d = np.mean(ex) * 8 / m["anchor_bps"] if ex else 0.0
        if d < MIN_DELIVERED[m["evasion"]]:
            out.append("attack delivered %.2f %s %s %s" % (d, f["phase"], f["ue"], m["evasion"]))
    return out


if __name__ == "__main__":
    for r in sys.argv[1:]:
        print(r.split("/")[-4][-30:], qa_run(r) or "clean")
