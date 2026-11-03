#!/usr/bin/env python3
"""Attack pilot over the twin (TRAFFIC-TWINNING-PLAN 5, 6.4). Per attack flow: rate at the UPF over the active seconds, minus what the twin of that second planned,
against the anchor; packets per second; packet size at the UPF on seconds where the twin is silent (5G-NIDD comparison, 3.3); protocol counters; c_t at the onset and after; delivery.
Usage: attack_report.py <campaign dir>..."""
import glob, gzip, json, sys
import numpy as np
BETA = 57
PROTO = ("prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp", "prof_ul_dns", "prof_ul_frag")
out = []
for D in sys.argv[1:]:
    for r in sorted(glob.glob(D + "/runs/*/*")):
        print(D.split("/")[-1], r[-6:])
        flows = json.load(open(r + "/traffic/flows.json"))
        F = {}
        for l in open(r + "/defense/features.jsonl"):
            x = json.loads(l)
            if "prof_ul_pps" in x:
                F.setdefault(x["supi"][-3:], {})[x["at_ms"] // 1000] = x
        ue = {"ue1": "780", "ue2": "781"}
        print(" retx", [gzip.open(r + "/logs/%s.log.gz" % n, "rt", errors="ignore").read().count("max RETX") for n in ("ue1", "ue2")])
        for f in flows:
            if f.get("v4_meta", {}).get("model") != "flood_overlay":
                continue
            m = f["v4_meta"]; t0 = int(f["attack_start_at"]); act = np.array(m["attack_active"], bool)
            tw = next(x for x in flows if x["phase"] == f["phase"] and x["ue"] == f["ue"] and x["v4_meta"].get("model") == "real_window")
            ts = int(round(tw["replay_start_at"]))
            S = F[ue[f["ue"]]]
            z = np.load("research/twinning/benign_windows.npz")
            band = tw["v4_meta"]["band"]; twin = z["ul_" + band][tw["v4_meta"]["window"]["index"]]
            rows = []
            for i in np.flatnonzero(act):
                x = S.get(t0 + i)
                if x is None or "c_t" not in x:
                    continue
                j = t0 + i - ts
                twb = float(twin[j]) if 0 <= j < 75 else 0.0
                rows.append((i, x["prof_ul_kbps"] * 125, x["prof_ul_pps"], x["rate_ul_kbps"] * 125, twb, x["prof_ul_mean_bytes"], x["c_t"], x["c_t_w"], x["kpm_masked"], *[x.get(k, 0) for k in PROTO]))
            a = np.array(rows, float)
            core = np.maximum(a[:, 1] - BETA * a[:, 2], 0)
            quiet = a[:, 4] == 0
            on = (t0 + m["onset_s"]) if True else 0
            onset_c = [round(S[on + k]["c_t"], 2) if on + k in S and "c_t" in S[on + k] else None for k in range(3)]
            res = dict(phase=f["phase"], ue=f["ue"], evasion=m["evasion"], backend=f["backend"], mode=f.get("mode"), anchor_kbps=round(m["anchor_bps"] / 1e3, 1), active_s=int(act.sum()), seen_s=len(a),
                       ul_excess_kbps=round(float(np.mean(core - a[:, 4])) * 8 / 1e3, 1), core_kbps=round(float(core.mean()) * 8 / 1e3, 1), pps_q50=round(float(np.median(a[:, 2]))), size_quiet_q50=round(float(np.median(a[quiet, 5])), 1) if quiet.any() else None, quiet_s=int(quiet.sum()),
                       ct_onset=onset_c, ct_out_pct=round(100 * float((abs(a[:, 6]) > .2).mean()), 1), ctw_out_pct=round(100 * float((abs(a[:, 7]) > .2).mean()), 1), masked_pct=round(100 * float(a[:, 8].mean()), 1),
                       kpm_core=round(float(a[:, 3].sum() / max(core.sum(), 1)), 3), proto_share={k[8:]: round(float(a[:, 9 + n].sum() / max(a[:, 2].sum(), 1)), 3) for n, k in enumerate(PROTO)},
                       failed=f.get("backend_failed"), delivered=round(float(np.mean(core - a[:, 4])) * 8 / m["anchor_bps"], 2), conn_failed=f.get("conn_failed"), answers=f.get("answers"), tx=f.get("tx_packets"))
            out.append(res); print(" %s %s %s %-13s %-5s anchor %6.1f | excess %6.1f core %6.1f kbit/s | pps %5d tx %6s | size(quiet) %s n=%d | c_t onset %s | out 1s %.0f%% 3s %.0f%% masked %.0f%% | KPM/core %.3f | %s | fail %s ans %s | delivered %.2f of the anchor%s" % (res["phase"], res["ue"], res["evasion"], res["backend"], res["mode"], res["anchor_kbps"], res["ul_excess_kbps"], res["core_kbps"], res["pps_q50"], res["tx"], res["size_quiet_q50"], res["quiet_s"], res["ct_onset"], res["ct_out_pct"], res["ctw_out_pct"], res["masked_pct"], res["kpm_core"], {k: v for k, v in res["proto_share"].items() if v}, res["conn_failed"], res["answers"], res["delivered"], " BACKEND FAILED" if res["failed"] else ""))
json.dump(out, open("research/twinning/out_attack_pilot.json", "w"), indent=0)
