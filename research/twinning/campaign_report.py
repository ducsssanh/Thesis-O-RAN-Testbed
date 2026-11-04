#!/usr/bin/env python3
"""Whole-campaign report (TRAFFIC-TWINNING-PLAN 6, 6.4). QA of every kept run, delivery per level, DL and UL delivered per twin window, the twin of the UEs without an attack or client flow validated again on the build cells
(sidecar at 1 core, unlike final2), shape at the UPF against 5G-NIDD (3.3), gate on honest seconds per band. Usage: campaign_report.py"""
import json, pathlib, sys, collections
import numpy as np, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts/k8s/exp/v4traffic"), str(ROOT / "research/twinning"), str(ROOT / "scripts/ml")]
import qa_twin, validate_twin as V
OUT = ROOT / "research/datasets/oran_flooding_twin"
L = [json.loads(l) for l in open(OUT / "manifest/campaign_log.jsonl")]
kept = {}
for x in L:
    if x["event"] == "kept":
        kept[x["id"]] = x
print("events", dict(collections.Counter(x["event"] for x in L)), "kept", len(kept), "repeatable notes", {k: v["note"][:70] for k, v in kept.items() if v.get("note")})
bad = {k: qa_twin.qa_run(v["run"]) for k, v in kept.items()}
print("QA with the final rules, runs with problems:", {k: v for k, v in bad.items() if v})
z = np.load(ROOT / "research/twinning/benign_windows.npz")
U, D, ratio = collections.defaultdict(list), collections.defaultdict(list), []
for k, v in sorted(kept.items()):
    run = pathlib.Path(v["run"])
    fl = json.loads((run / "traffic/flows.json").read_text())
    other = {(f["phase"], f["ue"]) for f in fl if (f.get("v4_meta") or {}).get("model") == "flood_overlay"}
    for band in ("P1", "P2", "P3", "P4"):
        u, d, src, drop = V.twin_windows(run, band)
        for a, b, s in zip(u, d, src):
            if (s[1], s[2]) not in other:
                U[band].append(a); D[band].append(b)
    for f in fl:
        m = f.get("v4_meta") or {}
        if m.get("model") == "real_window":
            ratio.append(dict(id=k, phase=f["phase"], ue=f["ue"], band=m["band"], index=m["window"]["index"], dl_target=m["target_dl_mean_bytes_s"] * 75, attacker=(f["phase"], f["ue"]) in other))
print("windows without attack or client flow", {b: len(U[b]) for b in U})
res = {}
for band in ("P1", "P2", "P3", "P4"):
    r = V.validate(band, np.array(U[band]), np.array(D[band]), z["ul_" + band], z["dl_" + band], z["src_" + band][:, 0], 30, 1000)
    res[band] = r
    print(band, "n", r["n_windows"], "tau* %.3f pass %s worst %s" % (r["tau_star"], r["pass"], r["worst"]), {k: t["percentile"] for k, t in r["tests"].items()})
(ROOT / "research/twinning/out_campaign_validate.json").write_text(json.dumps(res, indent=1) + "\n")
df = pd.read_parquet(OUT / "rows.parquet")
g = (df.rate_ul_kbps * 125 >= 1000) | (df.prof_ul_kbps * 125 >= 1000)
print("rows", len(df), "runs", df.run_id.nunique(), "attack s", int(df.attack_active.sum()), "no KPM %.4f no profile %.4f" % (df.rate_ul_kbps.isna().mean(), df.prof_ul_kbps.isna().mean()), "age q99 KPM %.3f profile %.3f" % (df.kpm_age_s.quantile(.99), df.prof_age_s.quantile(.99)))
h = df[g & (df.role == "benign") & (df.client_role == "")]
print("honest gate seconds, UE with the twin only, band: n, out 1 s, out 3 s, masked node, masked UE")
for b, x in h.groupby("band"):
    print(" ", b, len(x), "%.2f%% %.2f%% %.2f%% %.2f%%" % (100 * (x.c_t.abs() > .2).mean(), 100 * (x.c_t_w.abs() > .2).mean(), 100 * x.kpm_masked.mean(), 100 * x.kpm_masked_ue.mean()))
a = df[df.attack_active == 1]
print("attack: gate seconds out 1 s %.2f%%, out 3 s %.2f%%, masked node %.2f%% UE %.2f%%" % (100 * (a.c_t.abs() > .2).mean(), 100 * (a.c_t_w.abs() > .2).mean(), 100 * a.kpm_masked.mean(), 100 * a.kpm_masked_ue.mean()))
e = df[df.role == "attack"].groupby(["run_id", "phase"]).agg(ev=("evasion", "first"), vec=("vector", "first"), anc=("anchor_bps", "first"), sent=("attack_bytes", "sum"), core=("attack_bytes_core", "sum"), act=("attack_active", "sum"))
print(e.groupby("ev").agg(n=("sent", "size"), active_s=("act", "mean"), sent_kB=("sent", lambda s: s.mean() / 1e3), core_kB=("core", lambda s: s.mean() / 1e3)).round(1).to_string())
print("episodes where core is under 70 % of sent:", int((e.core < .7 * e.sent).sum()), "of", len(e), dict(e[e.core < .7 * e.sent].groupby("ev").size()))
quiet = df[(df.attack_active == 1) & (df.prof_ul_pps > 0)]
tw = np.array([float(z["ul_" + b][i][t]) for b, i, t in zip(quiet.band, quiet.window_index, quiet.t_window)])
q = quiet[(tw == 0) & (quiet.t_window > 0)]
print("5G-NIDD shape on attack seconds with a silent twin; IP length at the UPF = mean - 57; 5G-NIDD frame - 14 B: SYN 40, UDP 28, ICMP 28, HTTP flood p50 52")
for (ev, v), x in q.groupby(["evasion", "vector"]):
    s = x.prof_ul_mean_bytes - 57
    tot = x.prof_ul_pps.clip(lower=1)
    print("  %s %-14s s %5d | IP len q05/50/95 %.1f %.1f %.1f | TCP %.3f SYN %.3f UDP %.3f ICMP %.3f DNS %.3f | pps q50 %.0f" % (ev, v, len(x), s.quantile(.05), s.median(), s.quantile(.95), (x.prof_ul_tcp / tot).mean(), (x.prof_ul_tcp_syn / tot).mean(), (x.prof_ul_udp / tot).mean(), (x.prof_ul_icmp / tot).mean(), (x.prof_ul_dns / tot).mean(), x.prof_ul_pps.median()))
