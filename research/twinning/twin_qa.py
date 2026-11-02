#!/usr/bin/env python3
"""Per-rep QA of benign twin runs: windows kept and dropped, MAC against target per direction, windows with a dead direction (MAC under
half of a target of at least 5 kB, which the run status does not catch), RLC failures, KPM report phase, seconds without a profile, gaps in the features. Usage: twin_qa.py <band> <campaign dir>..."""
import csv, glob, gzip, json, os, pathlib, sys, time
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import validate_twin as V
z = np.load(pathlib.Path(__file__).parent / "benign_windows.npz")
b = sys.argv[1]
for D in sys.argv[2:]:
    print(os.path.basename(D))
    for r in sorted(glob.glob(D + "/runs/*/*")):
        if not os.path.exists(r + "/traffic/flows.json"):
            print(" ", r[-6:], "FAILED, no data"); continue
        u, d, src, drop = V.twin_windows(pathlib.Path(r), b)
        mac = {}
        for x in csv.DictReader(open(r + "/ran/mac_stats.csv")):
            mac.setdefault(x["ue"], []).append((float(x["stat_unix"]), int(x["ul_sdu_bytes"]), int(x["dl_sdu_bytes"])))
        dead = []; tu = td = mu = md = 0
        for f in json.load(open(r + "/traffic/flows.json")):
            if f.get("model") != "real_window":
                continue
            i, s0 = f["v4_meta"]["window"]["index"], f["replay_start_at"]
            if f["ue"] not in mac:
                continue
            m = np.array(mac[f["ue"]]); m = m[(m[:, 0] >= s0) & (m[:, 0] <= s0 + 76)]
            if len(m) < 2:
                continue
            a, c = np.minimum(z["ul_" + b][i], 1e6).sum(), np.minimum(z["dl_" + b][i], 1e6).sum()
            x, y = m[-1, 1] - m[0, 1], m[-1, 2] - m[0, 2]
            tu += a; td += c; mu += x; md += y
            if (a >= 5000 and x < a / 2) or (c >= 5000 and y < c / 2):
                dead.append(f["phase"] + f["ue"])
        feats = [json.loads(l) for l in open(r + "/defense/features.jsonl")]
        off = np.mean([min(x["collect_ms"] % 1000, 1000 - x["collect_ms"] % 1000) > 100 for x in feats])
        noprof = np.mean(["prof_ul_pps" not in x for x in feats])
        at = np.diff(sorted(set(x["at_ms"] for x in feats)))
        retx = [gzip.open(r + "/logs/%s.log.gz" % n, "rt", errors="ignore").read().count("max RETX") for n in ("ue1", "ue2")]
        print("  %s kept %d dropped %d | MAC/target UL %.3f DL %.3f | dead windows %d %s | max RETX %s | KPM phase off %.1f%% no profile %.1f%% gaps>2 s %d | gate usable: %s" % (r[-6:], len(u), drop, mu / max(tu, 1), md / max(td, 1), len(dead), dead[:4], retx, 100 * off, 100 * noprof, int((at > 2000).sum()), "yes" if off < .01 and noprof < .01 else "NO"))
