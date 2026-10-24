#!/usr/bin/env python3
"""Live evaluation of the cross-domain defence (v5, stage B) from the run logs.

  .venv-ml/bin/python -I scripts/ml/live_eval_v5.py --manifest <design.json> CAMP_DIR [CAMP_DIR ...]
        [--out research/datasets/oran_flooding_v5_live/reports] [--boot 1000] [--all-runs]

Unit = (run, UE, attack phase); icmp control phases reported apart. Per scenario x configuration, with
95% bootstrap CIs over runs:
  1. attack phases detected (L1: xApp level >= 1) / blocked (L3: level >= 3)    [defense/state_timeline]
  2. benign phases wrongly blocked (L3), framed benign (kpm_frame) apart; benign L1 soft isolation apart
  3. time from phase start to L1, L3 and the KPM integrity alarm (median, p90)    [sidecar.jsonl]
  4. integrity alarms on untampered phases
  5. live only: delivered fraction of the attacker's and the benign UE's UL packets at the DN
     (dn_per_second.csv packets / the generator's tx_packets, divided by the same backend+role's median
     with the defence off in the v4 campaign: 1 = untouched; packets, not bytes, because SYN/ICMP/DNS
     carry ~no payload and tcp_shortconn counts connections), sidecar latency p50/p99, xApp
     classifier fallbacks per run
Levels are the ones the xApp enforced (state timeline, 1 Hz); "decision" columns are the sidecar's own
L1/L3 (the acting configuration, before the xApp's expiry/actuation), to separate decision from action.
Only runs with meta_run_ok=1 count unless --all-runs; failed runs are counted in the report.
"""
import argparse, csv, json, pathlib, sys
import numpy as np, pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "research/datasets/oran_flooding_v5_live/reports"


def jsonl(p):
    p = pathlib.Path(p)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def ip_at(hist, t):
    ip = hist[0][1]
    for t0, x in hist:
        if t0 <= t:
            ip = x
    return ip


V4_CAMPS = ROOT / "artifacts/experiments"


def calibration(cache=OUT / "dn_delivery_calibration_v4.json"):
    """{backend/role: median DN UL packets / tx_packets} over the v4 defence-off runs."""
    if cache.exists():
        return json.loads(cache.read_text())
    vals = {}
    for rd in sorted(V4_CAMPS.glob("*_v4campaign_*/runs/detection-off/rep-*")):
        try:
            m = json.loads((rd / "run.json").read_text())
            fl = json.loads((rd / "traffic/flows.json").read_text())
            dn = pd.read_csv(rd / "dataplane/dn_per_second.csv")
        except (OSError, ValueError):
            continue
        if m.get("meta_run_ok") != 1:
            continue
        for ph in m.get("phases") or []:
            for f in fl:
                if f["phase"] != ph["name"] or f["dir"] != "ul" or not f.get("tx_packets"):
                    continue
                ip = ip_at(m["ues"][f["ue"]]["ip_history"], ph["t_start"])
                d = dn[(dn.ue_ip == ip) & (dn.dir == "ul") & (dn.t >= ph["t_start"] - 1) & (dn.t <= ph["t_end"] + 2)]
                vals.setdefault("%s/%s" % (f.get("backend"), f.get("role")), []).append(d.pkts.sum() / f["tx_packets"])
    cal = {k: round(float(np.median(v)), 4) for k, v in vals.items()}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"_n": {k: len(v) for k, v in vals.items()}, **cal}, indent=1) + "\n")
    return cal


def run_units(rd, man, cal):
    meta = json.loads((rd / "run.json").read_text())
    meta["_latency"], meta["_fallbacks"] = [], None
    if "manifest_id" not in meta or "phases" not in meta:
        return [], meta
    e = man["runs"][meta["manifest_id"] - 1]
    ues = meta["ues"]
    tl = jsonl(rd / "defense/state_timeline.jsonl")
    sc = [r for r in jsonl(rd / "defense/sidecar.jsonl") if "row" in r]
    dn = pd.read_csv(rd / "dataplane/dn_per_second.csv") if (rd / "dataplane/dn_per_second.csv").exists() else pd.DataFrame()
    flows = json.loads((rd / "traffic/flows.json").read_text()) if (rd / "traffic/flows.json").exists() else []
    units = []
    plan = {"p%02d_%s" % (j, ph["family"]): ph for j, ph in enumerate(e["phases"])}
    for ph in meta["phases"]:
        if ph["name"] not in plan:
            continue
        mp, t0, t1 = plan[ph["name"]], ph["t_start"], ph["t_end"]
        for ue, u in ues.items():
            supi = u["supi"]
            lv = [(r["t"] - t0, (r["ues"].get(supi) or {}).get("level") or 0) for r in tl if t0 <= r["t"] <= t1]
            first = lambda c: next((t for t, l in lv if c(l)), np.nan)
            srows = [r for r in sc if r["supi"] == supi and t0 <= r["ts"] <= t1]
            sfirst = lambda c: next((r["ts"] - t0 for r in srows if c(r)), np.nan)
            ip = ip_at(u["ip_history"], t0)
            d = dn[(dn.ue_ip == ip) & (dn.dir == "ul") & (dn.t >= t0 - 1) & (dn.t <= t1 + 2)] if len(dn) else dn
            fl = [f for f in flows if f["phase"] == ph["name"] and f["ue"] == ue and f["dir"] == "ul"]
            tx = sum(f.get("tx_packets") or 0 for f in fl)
            c = cal.get("%s/%s" % (fl[0].get("backend"), fl[0].get("role"))) if fl else None
            tam = mp.get("tamper") or {}
            units.append({
                "run": str(rd), "manifest_id": e["id"], "rep": e["rep"], "scenario": e["scenario"], "config": e["config"],
                "phase": ph["name"], "ue": ue, "mal": int(mp["attacker_ue"] == ue), "control": int(mp["family"] == "icmp"),
                "tampered": int(tam.get("ue") == ue), "core_outage": int(bool(mp.get("core_outage"))), "family": mp["family"],
                "l1": int(any(l >= 1 for _, l in lv)), "l3": int(any(l >= 3 for _, l in lv)),
                "t_l1": first(lambda l: l >= 1), "t_l3": first(lambda l: l >= 3),
                "dec_l1": int(any(r["configs"][e["config"]]["l1"] for r in srows)) if srows and e["config"] in srows[0]["configs"] else np.nan,
                "dec_l3": int(any(r["configs"][e["config"]]["l3"] for r in srows)) if srows and e["config"] in srows[0]["configs"] else np.nan,
                "integrity": int(any(r["integrity"] for r in srows)) if srows else np.nan,
                "t_integrity": sfirst(lambda r: r["integrity"]),
                "kt_min": min((r["kt"] for r in srows), default=np.nan),
                "dn_ul_pkts": float(d.pkts.sum()) if len(d) else 0.0, "tx_pkts": tx,
                "delivered_frac": (float(d.pkts.sum()) / tx / c) if tx and c else np.nan,
            })
    meta["_latency"] = [r["latency_ms"] for r in sc]
    s0, s1 = [json.loads((rd / ("meta/snapshot_%s.json" % k)).read_text()) if (rd / ("meta/snapshot_%s.json" % k)).exists() else {}
              for k in ("start", "end")]
    fb = lambda s: ((s.get("defense_state") or {}).get("classifier") or {}).get("fallbacks")
    meta["_fallbacks"] = (fb(s1) - fb(s0)) if fb(s1) is not None and fb(s0) is not None else None
    return units, meta


def boot(df, fn, B, seed=0):
    runs = df.run.unique()
    if len(runs) < 2:
        return None
    rng = np.random.default_rng(seed)
    by = {r: df[df.run == r] for r in runs}
    v = [fn(pd.concat([by[r] for r in rng.choice(runs, len(runs))])) for _ in range(B)]
    v = [x for x in v if x == x]
    return [round(float(np.quantile(v, .025)), 3), round(float(np.quantile(v, .975)), 3)] if v else None


def cell(u, B):
    a, b = u[(u.mal == 1) & (u.control == 0)], u[(u.mal == 0) & (u.control == 0)]
    fr = b[b.tampered == 1]
    q = lambda s, p: round(float(s.quantile(p)), 1) if s.notna().any() else None
    r = {"runs": int(u.run.nunique()), "attack_phases": len(a), "benign_phases": len(b),
         "attack_L1": round(a.l1.mean(), 3) if len(a) else None, "ci_attack_L1": boot(a, lambda x: x.l1.mean(), B),
         "attack_L3": round(a.l3.mean(), 3) if len(a) else None, "ci_attack_L3": boot(a, lambda x: x.l3.mean(), B),
         "benign_L1": round(b.l1.mean(), 3) if len(b) else None,
         "benign_L3": round(b.l3.mean(), 3) if len(b) else None, "ci_benign_L3": boot(b, lambda x: x.l3.mean(), B),
         "framed_benign_L3": round(fr.l3.mean(), 3) if len(fr) else None,
         "ci_framed_benign_L3": boot(fr, lambda x: x.l3.mean(), B) if len(fr) else None,
         "t_L1_median": q(a.t_l1, .5), "t_L1_p90": q(a.t_l1, .9), "t_L3_median": q(a.t_l3, .5), "t_L3_p90": q(a.t_l3, .9),
         "integrity_tampered": round(u[u.tampered == 1].integrity.mean(), 3) if (u.tampered == 1).any() and u.integrity.notna().any() else None,
         "t_integrity_median": q(u[u.tampered == 1].t_integrity, .5), "t_integrity_p90": q(u[u.tampered == 1].t_integrity, .9),
         "integrity_false_untampered": round(u[(u.tampered == 0)].integrity.mean(), 3) if u.integrity.notna().any() else None,
         "attack_delivered_frac": round(a.delivered_frac.median(), 3) if len(a) else None,
         "benign_delivered_frac": round(b.delivered_frac.median(), 3) if len(b) else None,
         "decision_attack_L1": round(a.dec_l1.mean(), 3) if a.dec_l1.notna().any() else None,
         "decision_attack_L3": round(a.dec_l3.mean(), 3) if a.dec_l3.notna().any() else None,
         "decision_benign_L3": round(b.dec_l3.mean(), 3) if b.dec_l3.notna().any() else None}
    c = u[u.control == 1]
    if len(c):
        r.update({"control_attack_L1": round(c[c.mal == 1].l1.mean(), 3), "control_benign_L3": round(c[c.mal == 0].l3.mean(), 3)})
    return r


OFFLINE = ROOT / "artifacts/ml/v4/fusion/fusion_results.json"
SCN_OFF = {"honest": "honest", "kpm_hide_x0.1": "kpm_hide x0.1", "kpm_hide_x0.33": "kpm_hide x0.33",
           "kpm_frame_x2": "kpm_frame x2", "kpm_frame_x5": "kpm_frame x5", "core_outage": "core_outage"}
CFG_OFF = {"ran-only": "RAN-only (xApp KPM)", "core-only": "core-only (5GC)", "xd-naive": "cross-domain naive",
           "xd-trust-v1": "cross-domain trust-weighted", "xd-trust-v2": "cross-domain trust-weighted v2"}
PAIRS = [("attack_L1", "attack_detected_L1"), ("attack_L3", "attack_blocked_L3"), ("benign_L3", "benign_wrongly_blocked_L3"),
         ("framed_benign_L3", "framed_benign_blocked_L3"), ("integrity_tampered", "integrity_alarm_tampered"),
         ("t_L1_median", "attack_t_L1_median_s"), ("t_L3_median", "attack_t_L3_median_s"), ("t_integrity_median", "integrity_t_median_s")]


def offline_vs_live(res):
    """Rows (scenario, config, metric, offline replay on the v4 test runs, live)."""
    off = json.loads(OFFLINE.read_text())["results"] if OFFLINE.exists() else {}
    rows = []
    for s, by in res.items():
        for c, r in by.items():
            o = (off.get(SCN_OFF.get(s, ""), {}) or {}).get(CFG_OFF.get(c, ""), {})
            for lk, ok in PAIRS:
                if r.get(lk) is not None or o.get(ok) is not None:
                    rows.append({"scenario": s, "config": c, "metric": lk, "offline": o.get(ok), "live": r.get(lk)})
    return rows


def write_report(path, summ, res, ovl, man):
    M = [("runs", "runs"), ("attack_L1", "attack L1"), ("attack_L3", "attack L3"), ("benign_L1", "benign L1"),
         ("benign_L3", "benign L3"), ("framed_benign_L3", "framed benign L3"), ("t_L1_median", "t→L1 med"),
         ("t_L3_median", "t→L3 med"), ("integrity_tampered", "integrity on tampered"), ("t_integrity_median", "t→integrity"),
         ("integrity_false_untampered", "integrity false (untampered)"), ("attack_delivered_frac", "attack delivered"),
         ("benign_delivered_frac", "benign delivered")]
    L = ["# Cross-domain defence live (v5, stage B) — results\n",
         "Runs: %d (%d with meta_run_ok=1). Sidecar latency %s ms. xApp classifier fallbacks: %s. Unit = (run, UE, "
         "attack phase), icmp control apart; brackets = 95%% bootstrap CI by run. Levels = enforced by the xApp; "
         "delivered = DN UL packets / sent, calibrated to the v4 defence-off median (1 = untouched).\n"
         % (summ["runs"], summ["runs_ok"], summ["sidecar_latency_ms"], summ["fallbacks_total"])]
    for sc in man["scenarios"]:
        if sc not in res:
            continue
        L += ["## %s\n" % sc, "| config | " + " | ".join(h for _, h in M) + " |", "|---|" + "---:|" * len(M)]
        for c in man["configs"]:
            r = res[sc].get(c)
            if not r:
                continue
            cells = []
            for k, _ in M:
                v = r.get(k)
                ci = r.get("ci_" + k)
                cells.append("–" if v is None else ("%s %s" % (v, ci) if ci else str(v)))
            L.append("| %s | %s |" % (c, " | ".join(cells)))
        L.append("")
    L += ["## Offline replay (v4 test runs) vs live\n", "| scenario | config | metric | offline | live |", "|---|---|---|---:|---:|"]
    L += ["| %s | %s | %s | %s | %s |" % (r["scenario"], r["config"], r["metric"], r["offline"], r["live"]) for r in ovl]
    path.write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("camps", nargs="+")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--all-runs", action="store_true")
    a = ap.parse_args()
    man = json.loads(pathlib.Path(a.manifest).read_text())
    cal = calibration()
    units, metas = [], []
    for c in a.camps:                     # pilot data never enters a main analysis: other manifest -> refuse
        cm = pathlib.Path(json.loads((pathlib.Path(c) / "campaign.json").read_text())["manifest"]).resolve()
        if cm != pathlib.Path(a.manifest).resolve():
            raise SystemExit("%s ran manifest %s, not %s" % (c, cm, a.manifest))
        for rd in sorted(pathlib.Path(c).glob("runs/*/rep-*")):
            u, m = run_units(rd, man, cal)
            m["_dir"] = str(rd)
            metas.append(m)
            if a.all_runs or m.get("meta_run_ok") == 1:
                units += u
    dup = pd.Series([m.get("manifest_id") for m in metas if m.get("meta_run_ok") == 1]).value_counts()
    if not a.all_runs and (dup > 1).any():
        raise SystemExit("manifest runs with more than one valid attempt: %s" % list(dup[dup > 1].index))
    U = pd.DataFrame(units)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    U.to_csv(out / "live_units_v5.csv", index=False)
    res = {}
    for (s, c), g in U.groupby(["scenario", "config"]):
        res.setdefault(s, {})[c] = cell(g, a.boot)
    lat = np.concatenate([m["_latency"] for m in metas if m.get("_latency")]) if any(m.get("_latency") for m in metas) else np.array([])
    runs_tbl = [{"dir": m["_dir"], "scenario": m.get("scenario"), "config": m.get("config"), "ok": m.get("meta_run_ok"),
                 "fallbacks": m.get("_fallbacks"), "integrity": (m.get("integrity") or {}).get("reasons")} for m in metas]
    summ = {"runs": len(metas), "runs_ok": sum(1 for m in metas if m.get("meta_run_ok") == 1),
            "sidecar_latency_ms": {"p50": round(float(np.percentile(lat, 50)), 2), "p99": round(float(np.percentile(lat, 99)), 2)} if len(lat) else None,
            "fallbacks_total": sum(m["_fallbacks"] or 0 for m in metas)}
    ovl = offline_vs_live(res)
    (out / "live_eval_v5.json").write_text(json.dumps({"summary": summ, "results": res, "offline_vs_live": ovl, "runs": runs_tbl},
                                                      indent=1, default=str) + "\n")
    write_report(out / "live_eval_v5.md", summ, res, ovl, man)
    print(json.dumps(summ))
    for s, by in res.items():
        for c, r in by.items():
            print("%-16s %-12s %s" % (s, c, {k: r[k] for k in ("runs", "attack_L1", "attack_L3", "benign_L3", "framed_benign_L3",
                                                               "integrity_tampered", "attack_delivered_frac", "benign_delivered_frac")}))


if __name__ == "__main__":
    main()
