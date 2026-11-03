#!/usr/bin/env python3
"""LTE sensitivity (TRAFFIC-TWINNING-PLAN 0a row 9): P3 and P4 replayed with every second multiplied by 2 and 4, against the unscaled final2 reps of the same band.
Per set: MAC over the scaled plan, clipped seconds, dead windows, UL and DL lost over the plan by size of second, c_t and KPM masking, PRB use, RLC failures. Run from the repo root."""
import glob, gzip, json, pathlib, sys
import numpy as np
sys.path.insert(0, "research/twinning")
z = np.load("research/twinning/benign_windows.npz")
sys.path.insert(0, "scripts/k8s/exp")
CAP = {"ul": 1e6, "dl": 1e6}
try:
    from v4traffic.planbuilder import REPLAY_CAP_BYTES_S as CAP
except Exception:
    pass
out = {}
for b, k, pat in [(b, k, p) for b in ("P3", "P4") for k, p in ((1, "*_ds-benign-twin-%s_final2" % b), (2, "*_ds-benign-twin-%s-x2_lte" % b), (4, "*_ds-benign-twin-%s-x4_lte" % b))]:
    d = sorted(glob.glob("artifacts/experiments/" + pat))[-1]
    tu = td = mu = md = clip_u = clip_d = n = dead = 0; ct = []; cw = []; mk = []; prb_u = []; prb_d = []; retx = 0; rows = 0
    for r in sorted(glob.glob(d + "/runs/*/*")):
        mac = {}
        for x in open(r + "/ran/mac_stats.csv").read().splitlines()[1:]:
            f = x.split(","); mac.setdefault(f[2], []).append((float(f[0]), int(f[4]), int(f[5])))
        for fl in json.load(open(r + "/traffic/flows.json")):
            if fl.get("model") != "real_window" or fl["ue"] not in mac:
                continue
            i, s0 = fl["v4_meta"]["window"]["index"], fl["replay_start_at"]
            m = np.array(mac[fl["ue"]]); m = m[(m[:, 0] >= s0) & (m[:, 0] <= s0 + 76)]
            if len(m) < 2:
                continue
            su, sd = z["ul_" + b][i] * k, z["dl_" + b][i] * k
            clip_u += int((su > CAP["ul"]).sum()); clip_d += int((sd > CAP["dl"]).sum()); n += su.size
            a, c = np.minimum(su, CAP["ul"]).sum(), np.minimum(sd, CAP["dl"]).sum()
            x, y = m[-1, 1] - m[0, 1], m[-1, 2] - m[0, 2]
            tu += a; td += c; mu += x; md += y
            dead += int((a >= 5000 and x < a / 2) or (c >= 5000 and y < c / 2))
        for l in open(r + "/defense/features.jsonl"):
            x = json.loads(l)
            if "c_t_w" in x and "prof_ul_pps" in x and x["collect_ms"] % 1000 < 50 and (x["rate_ul_kbps"] * 125 >= 1000 or x["prof_ul_kbps"] * 125 >= 1000):
                ct.append(x["c_t"]); cw.append(x["c_t_w"]); mk.append(x["kpm_masked"]); prb_u.append(x["cell_prb_ul_pct"]); prb_d.append(x["cell_prb_dl_pct"])
        retx += sum(gzip.open(r + "/logs/%s.log.gz" % u, "rt", errors="ignore").read().count("max RETX") for u in ("ue1", "ue2"))
    ct, cw, mk, pu, pd = map(np.array, (ct, cw, mk, prb_u, prb_d))
    res = dict(band=b, scale=k, campaign=d.split("/")[-1], seconds=n, mac_ul=round(mu / max(tu, 1), 3), mac_dl=round(md / max(td, 1), 3), clip_ul_pct=round(100 * clip_u / n, 2), clip_dl_pct=round(100 * clip_d / n, 2), dead=dead, retx=retx, gate_s=int(ct.size), out_1s=round(100 * float((abs(ct) > .2).mean()), 2), out_3s=round(100 * float((abs(cw) > .2).mean()), 2), masked=round(100 * float(mk.mean()), 2), prb_ul_q50_q99=[float(np.percentile(pu, q)) for q in (50, 99)], prb_dl_q50_q99=[float(np.percentile(pd, q)) for q in (50, 99)])
    out["%s_x%d" % (b, k)] = res; print(res)
json.dump(out, open("research/twinning/out_lte_sensitivity.json", "w"), indent=1)
