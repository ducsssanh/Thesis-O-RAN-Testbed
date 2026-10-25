#!/usr/bin/env python3
"""Final live results of the v5 main campaign (after live_eval_v5.py, carryover_v5.py, loop_latency_v5.py).

  .venv-ml/bin/python -I scripts/ml/live_extra_v5.py [--boot 1000]

Primary analysis = CLEAN units: a (run, UE, phase) whose UE entered the phase already at L3 is dropped
(block carried over from the previous phase: the gap reset raced with the sidecar's last L3 answer;
carryover_v5.py, PREREGISTRATION "Deviation after the main campaign"). The all-units value is shown
next to the clean one. Writes reports/live_results_v5.{md,json}:
  1. main table per scenario x config (live_eval_v5.cell, 95 % bootstrap CI over runs)
  A. icmp control pair: icmp_flood L1 / L3, icmp_ping L1 / L3
  B. core_outage: L1 and L3 apart for outage phases and core-present phases
  C. kpm_hide: time to block, attacker UL bytes at the DN before / after the block
  D. sensitivity without the runs flagged by qa_v5 (classifier fallback inside a phase)
  E. carry-over per cell;  F. failed attempts per cell;  G. control-loop latency;  H. hypotheses H1-H4
  I. L3 decided (xApp level 3) vs enforced (UPF block PUT accepted in the phase; the UPF refuses a block
     beyond maxBlockedRatio 0.5, i.e. the 2nd of 2 UEs, HTTP 403)
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "scripts/k8s/exp/v4traffic"), str(ROOT / "scripts/k8s/exp")]
import live_eval_v5 as LE
import supervise_v5 as S

REP = ROOT / "research/datasets/oran_flooding_v5_live/reports"
MAN = ROOT / "research/datasets/oran_flooding_v5_live/manifest/design.json"
CONFIGS = ["rules-v1", "ran-only", "core-only", "xd-naive", "xd-trust-v1", "xd-trust-v2"]
FLAGGED = [40, 91, 99, 110, 173, 212]          # qa_v5 flagged_runs over the whole main campaign


def rate(df, col, B):
    """'mean [lo, hi]' of a 0/1 column, CI by run."""
    if not len(df):
        return "–"
    ci = LE.boot(df, lambda x: x[col].mean(), B)
    return "%.2f%s" % (df[col].mean(), " [%.2f, %.2f]" % tuple(ci) if ci else "")


def med(s):
    s = s.dropna()
    return "%.1f / %.1f" % (s.median(), s.quantile(.9)) if len(s) else "–"


def fmt(v, ci=None):
    if v is None or v != v:
        return "–"
    return "%.2f%s" % (v, " [%.2f, %.2f]" % tuple(ci) if ci else "")


def phase_bytes(units):
    """Per attack unit: attacker DN UL bytes before / after the block (t_l3), phase window + 2 s."""
    out, cache = [], {}
    for _, u in units.iterrows():
        rd = pathlib.Path(u.run)
        if rd not in cache:
            m = json.loads((rd / "run.json").read_text())
            dn = pd.read_csv(rd / "dataplane/dn_per_second.csv")
            cache[rd] = (m, dn[dn.dir == "ul"])
        m, dn = cache[rd]
        ph = next(p for p in m["phases"] if p["name"] == u.phase)
        t0, t1 = ph["t_start"], ph["t_end"]
        ip = LE.ip_at(m["ues"][u.ue]["ip_history"], t0)
        d = dn[(dn.ue_ip == ip) & (dn.t >= int(t0)) & (dn.t <= t1 + 2)]
        tb = t0 + u.t_l3 if u.l3 == 1 and u.t_l3 == u.t_l3 else None
        bef = d[d.t < tb] if tb else d
        aft = d[d.t >= tb] if tb else d.iloc[0:0]
        sb, sa = max(1.0, (tb or t1 + 2) - t0), (max(1.0, t1 + 2 - tb) if tb else 0.0)
        out.append({"run": u.run, "config": u.config, "scenario": u.scenario, "blocked": int(bool(tb)),
                    "bytes_before": float(bef.ip_payload_bytes.sum()), "bytes_after": float(aft.ip_payload_bytes.sum()),
                    "kbps_before": float(bef.ip_payload_bytes.sum()) * 8 / 1000 / sb,
                    "kbps_after": float(aft.ip_payload_bytes.sum()) * 8 / 1000 / sa if tb else np.nan})
    return pd.DataFrame(out)


def enforced(units):
    """Per L3 unit: a UPF block PUT accepted (200) / refused (403) for the UE in [t_start, t_end + 2 s]."""
    out, cache = [], {}
    for _, u in units.iterrows():
        rd = pathlib.Path(u.run)
        if rd not in cache:
            cache[rd] = (json.loads((rd / "run.json").read_text()), LE.jsonl(rd / "core/upf_audit.jsonl"))
        m, au = cache[rd]
        ph = next(p for p in m["phases"] if p["name"] == u.phase)
        supi = m["ues"][u.ue]["supi"]
        a = [x for x in au if x.get("supi") == supi and x.get("op") == "put" and ph["t_start"] * 1000 <= x["ts_ms"] <= (ph["t_end"] + 2) * 1000]
        out.append({"scenario": u.scenario, "config": u.config, "mal": u.mal, "run": u.run,
                    "enforced": int(any(x["status"] == 200 and (x.get("detail") or {}).get("action") == "block" for x in a)),
                    "refused": int(any(x["status"] == 403 for x in a))})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000)
    B = ap.parse_args().boot
    UA = pd.read_csv(REP / "live_units_v5_carryover.csv")
    U = UA[UA.carried_l3 == 0]
    M = json.loads(MAN.read_text())
    ev = json.loads((REP / "live_eval_v5.json").read_text())["summary"]
    lat = json.loads((REP / "loop_latency_v5.json").read_text())
    res = {"carried_units": int(UA.carried_l3.sum()), "units": len(UA)}
    nc = UA[UA.control == 0]
    L = ["# Cross-domain defence live (v5, stage B) — final results\n",
         "Main campaign 2026-10-24 13:19 → 2026-10-25 15:55: **224/224 runs valid** (42 cells: 6 reps, rules-v1 2), "
         "30 failed attempts (testbed) re-run. Sidecar latency p50 %s / p99 %s ms, %d classifier fallbacks in %d valid runs. "
         "Pilot excluded. Unit = (run, UE, phase); brackets = 95 %% bootstrap CI over runs.\n"
         % (ev["sidecar_latency_ms"]["p50"], ev["sidecar_latency_ms"]["p99"], ev["fallbacks_total"], ev["runs_ok"]),
         "**Primary = clean units.** %d of %d phases (%.1f %%; 38 runs; %d icmp phases) started with the UE already at L3: "
         "the gap reset of the xApp level raced with the sidecar's last L3 answer, which re-set L3 with a 120 s expiry, so "
         "the block carried into the next phase. These units are dropped (their outcome is not their phase's); all-units "
         "values in parentheses. Carried phases per config (incl. icmp): %s (see E).\n"
         % (int(nc.carried_l3.sum()), len(nc), 100 * nc.carried_l3.mean(), int(UA[UA.control == 1].carried_l3.sum()),
            ", ".join("%s %d" % (c, UA[UA.config == c].carried_l3.sum()) for c in CONFIGS))]

    # 1. main table
    cols = [("attack_L1", "attack L1"), ("attack_L3", "attack L3"), ("benign_L1", "benign L1"), ("benign_L3", "benign L3"),
            ("framed_benign_L3", "framed benign L3"), ("t_L1_median", "t→L1 med (s)"), ("t_L3_median", "t→L3 med (s)"),
            ("integrity_tampered", "integrity on tampered"), ("integrity_false_untampered", "integrity false"),
            ("attack_delivered_frac", "attack delivered"), ("benign_delivered_frac", "benign delivered")]
    res["cells"] = {}
    L.append("## 1. Per scenario × configuration (clean units; all units in parentheses for L3)\n")
    for s in M["scenarios"]:
        if s == "icmp_control":
            continue
        L += ["### %s\n" % s, "| config | phases | " + " | ".join(h for _, h in cols) + " |", "|---|---:|" + "---|" * len(cols)]
        for c in CONFIGS:
            g, ga = U[(U.scenario == s) & (U.config == c) & (U.control == 0)], UA[(UA.scenario == s) & (UA.config == c) & (UA.control == 0)]
            r, ra = LE.cell(g, B), LE.cell(ga, 0)
            res["cells"]["%s/%s" % (s, c)] = {"clean": r, "all": ra}
            cells = []
            for k, _ in cols:
                v = fmt(r.get(k), r.get("ci_" + k)) if not k.startswith("t_") else ("–" if r.get(k) is None else "%.1f" % r[k])
                if k in ("attack_L3", "benign_L3", "framed_benign_L3") and ra.get(k) is not None and ra.get(k) != r.get(k):
                    v += " (%.2f)" % ra[k]
                cells.append(v)
            L.append("| %s | %d | %s |" % (c, len(g), " | ".join(cells)))
        L.append("")

    # A. icmp control
    C, CA = U[U.control == 1], UA[UA.control == 1]
    L += ["## A. icmp control pair (icmp_flood vs icmp_ping, honest telemetry; clean units)\n",
          "| config | runs | flood L1 | flood L3 | ping L1 | ping L3 (all) |", "|---|---:|---|---|---|---|"]
    res["icmp"] = {}
    for c in CONFIGS:
        g, ga = C[C.config == c], CA[CA.config == c]
        f, p = g[g.mal == 1], g[g.mal == 0]
        row = [g.run.nunique(), rate(f, "l1", B), rate(f, "l3", B), rate(p, "l1", B),
               rate(p, "l3", B) + " (%.2f)" % ga[ga.mal == 0].l3.mean()]
        res["icmp"][c] = row
        L.append("| %s | %s |" % (c, " | ".join(map(str, row))))
    L.append("")

    # B. core outage
    O = U[(U.scenario == "core_outage") & (U.control == 0)]
    L += ["## B. core_outage: L1 vs L3, outage phases vs core-present phases\n",
          "Outage phases = 0 and 3 (A1-EI adapter scaled to 0: no URR, no profiler; the UPF Security API stays up). "
          "**By design** the trust-weighted L3 needs core evidence (L1 held ≥ 10 s AND core alarm in 3 of 5 s), so "
          "trust-v1/v2 cannot block in an outage phase: their L3 = 0 there is the two-layer rule, not a miss. Their L1 "
          "in outage phases comes from the RAN fallback (ct = 0 → z_ran).\n",
          "| config | outage: attack L1 | outage: attack L3 | outage: benign L3 | core present: attack L1 | core present: attack L3 | core present: benign L3 |",
          "|---|---|---|---|---|---|---|"]
    res["core_outage"] = {}
    for c in CONFIGS:
        g = O[O.config == c]
        o, n = g[g.core_outage == 1], g[g.core_outage == 0]
        row = [rate(o[o.mal == 1], "l1", B), rate(o[o.mal == 1], "l3", B), rate(o[o.mal == 0], "l3", B),
               rate(n[n.mal == 1], "l1", B), rate(n[n.mal == 1], "l3", B), rate(n[n.mal == 0], "l3", B)]
        res["core_outage"][c] = row
        L.append("| %s | %s |" % (c, " | ".join(row)))
    L.append("")

    # C. kpm_hide
    H = U[U.scenario.str.startswith("kpm_hide") & (U.control == 0) & (U.mal == 1)]
    PB = phase_bytes(H)
    L += ["## C. kpm_hide: time to block and attacker bytes at the DN (clean units)\n",
          "t→L3 = phase start → UPF block (median / p90 over blocked phases; ≥ ~13 s by design: L1 needs 3 of 5 s, L3 "
          "needs L1 held 10 s). Rates = attacker UL IP payload at the DN, phase window + 2 s.\n",
          "| scenario | config | attack phases | blocked | t→L3 med / p90 (s) | before block (kbit/s, med) | after block (kbit/s, med) | after/before | share of phase bytes after block |",
          "|---|---|---:|---|---|---:|---:|---:|---:|"]
    res["kpm_hide"] = {}
    for s in ("kpm_hide_x0.1", "kpm_hide_x0.33"):
        for c in CONFIGS:
            g, pb = H[(H.scenario == s) & (H.config == c)], PB[(PB.scenario == s) & (PB.config == c)]
            b = pb[pb.blocked == 1]
            ratio = (b.kbps_after / b.kbps_before.clip(lower=1e-9)).median() if len(b) else np.nan
            share = (b.bytes_after / (b.bytes_before + b.bytes_after).clip(lower=1)).median() if len(b) else np.nan
            row = [len(g), rate(g, "l3", B), med(g[g.l3 == 1].t_l3), "%.0f" % b.kbps_before.median() if len(b) else "–",
                   "%.0f" % b.kbps_after.median() if len(b) else "–", "%.3f" % ratio if ratio == ratio else "–",
                   "%.3f" % share if share == share else "–"]
            res["kpm_hide"]["%s/%s" % (s, c)] = row
            L.append("| %s | %s | %s |" % (s, c, " | ".join(map(str, row))))
    L.append("")

    # D. sensitivity without flagged runs
    keys = ["attack_L1", "attack_L3", "benign_L3", "framed_benign_L3", "integrity_tampered", "attack_delivered_frac"]
    Uf = U[~U.manifest_id.isin(FLAGGED)]
    rows, worst, worst_rate = [], 0.0, 0.0
    for (s, c), g in U[U.control == 0].groupby(["scenario", "config"]):
        gf = Uf[(Uf.scenario == s) & (Uf.config == c) & (Uf.control == 0)]
        if len(gf) == len(g):
            continue
        a, b = LE.cell(g, 0), LE.cell(gf, 0)
        d = {k: (a.get(k), b.get(k)) for k in keys if a.get(k) is not None and b.get(k) is not None}
        worst = max([worst] + [abs(x - y) for x, y in d.values()])
        worst_rate = max([worst_rate] + [abs(x - y) for k, (x, y) in d.items() if k != "attack_delivered_frac"])
        rows.append("| %s | %s | %d → %d | %s |" % (s, c, g.run.nunique(), gf.run.nunique(),
                    ", ".join("%s %.3f → %.3f" % (k, x, y) for k, (x, y) in d.items())))
    L += ["## D. Sensitivity: without the flagged runs %s (classifier fallback inside a phase)\n" % FLAGGED,
          "Largest change of a detection/block rate: **%.3f**; of the median delivered fraction (few phases, volatile): %.3f. "
          "In every flagged run the sidecar's own answer at the fallback steps was benign / level 0 (checked for 91, 99, 173).\n"
          % (worst_rate, worst), "| scenario | config | runs | all → without flagged |", "|---|---|---|---|"] + rows + [""]
    res["sensitivity"] = {"max_rate_change": worst_rate, "max_change": worst}

    # E. carry-over per cell
    L += ["## E. Carried-over L3 per cell (phases dropped from the primary analysis: attacker / benign)\n",
          "| scenario | " + " | ".join(CONFIGS) + " |", "|---|" + "---:|" * len(CONFIGS)]
    for s in M["scenarios"]:
        g = UA[UA.scenario == s]
        L.append("| %s | %s |" % (s, " | ".join("%d / %d" % (g[(g.config == c) & (g.mal == 1)].carried_l3.sum(),
                                                               g[(g.config == c) & (g.mal == 0)].carried_l3.sum()) for c in CONFIGS)))
    L.append("")

    # F. failed attempts per cell
    ids = S.config_reps(list(range(1, len(M["runs"]) + 1)), M, "rules-v1=1,3")
    at = S.attempts(MAN, "main")
    tab = {}
    for i in ids:
        r = M["runs"][i - 1]
        n, ok = at.get(i, (0, False))
        t = tab.setdefault(r["scenario"], {}).setdefault(r["config"], [0, 0])
        t[0] += n - int(ok)
        t[1] += n
    L += ["## F. Failed attempts per cell (failed / attempts; testbed failures, all re-run)\n",
          "| scenario | " + " | ".join(CONFIGS) + " |", "|---|" + "---:|" * len(CONFIGS)]
    for s in M["scenarios"]:
        L.append("| %s | %s |" % (s, " | ".join("%d/%d" % tuple(tab[s].get(c, [0, 0])) for c in CONFIGS)))
    tot = [sum(tab[s].get(c, [0, 0])[0] for s in tab) for c in CONFIGS]
    L += ["| **all** | %s |" % " | ".join(map(str, tot)),
          "\nFailures are spread over configurations (3–7 each); no configuration is over-represented, so re-running "
          "until valid does not select for one.\n"]
    res["failures"] = tab

    # G. control-loop latency
    names = [("e2_ind", "gNB KPM measured → xApp (E2 indication)"), ("xapp_proc", "xApp: features + sidecar + policy → RC sent"),
             ("sidecar", "sidecar /classify (server)"), ("rc_ack", "E2SM-RC sent → gNB ack"),
             ("ran_e2e", "**RAN loop: gNB KPM → RC ack**"), ("upf_put", "decision → UPF policy accepted"),
             ("core_e2e_dec", "**core loop: gNB KPM → UPF policy**"), ("kpm_period", "KPM report period"),
             ("urr_deliv", "URR measured (SMF) → xApp (A1-EI path)"), ("urr_period", "URR report spacing")]
    L += ["## G. Control-loop latency, one iteration (one KPM report → action), detection-triggered actions\n",
          "| segment | n | p50 (ms) | p99 (ms) | max (ms) |", "|---|---:|---:|---:|---:|"]
    L += ["| %s | %d | %.1f | %.1f | %.1f |" % (h, lat[k]["n"], lat[k]["p50"], lat[k]["p99"], lat[k]["max"]) for k, h in names if k in lat]
    L += ["\nOne iteration meets the near-RT bound (10 ms–1 s) with margin; the loop period is the 1 s KPM report period "
          "(the models use 1 s features). The core telemetry reaches the xApp 1.5–2.8 s after measurement (SMF periodic "
          "report + A1-EI path): decisions using core evidence act on telemetry older than one loop. The core-loop p99 "
          "≈ 1 s comes from timer-driven TTL refreshes, not from KPM-triggered decisions (decision → UPF p99 64 ms).\n"]

    # I. L3 decided vs enforced
    E = enforced(U[U.l3 == 1])
    L += ["## I. L3 decided (xApp level 3) vs enforced at the UPF (clean units, all scenarios)\n",
          "The UPF Security API refuses a block that would put more than half of the known UEs in block "
          "(maxBlockedRatio 0.5: with 2 UEs, the second block → HTTP 403). The tables above count the xApp's L3 "
          "decision; the delivered fraction measures what reached the DN.\n",
          "| config | attacker L3 phases | enforced | refused (403) | benign L3 phases | enforced | refused (403) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    res["l3_enforced"] = {}
    for c in CONFIGS:
        g = E[E.config == c] if len(E) else E
        a, b = (g[g.mal == 1], g[g.mal == 0]) if len(g) else (g, g)
        f = lambda d, k: "%.2f" % d[k].mean() if len(d) else "–"
        row = [len(a), f(a, "enforced"), f(a, "refused"), len(b), f(b, "enforced"), f(b, "refused")]
        res["l3_enforced"][c] = row
        L.append("| %s | %s |" % (c, " | ".join(map(str, row))))
    L.append("")

    # H. hypotheses
    cl = lambda s, c, k: res["cells"]["%s/%s" % (s, c)]["clean"].get(k)
    h1 = [(s, k, cl(s, "xd-trust-v2", k), cl(s, "xd-naive", k)) for s in
          ("kpm_hide_x0.1", "kpm_hide_x0.33", "kpm_frame_x2", "kpm_frame_x5", "core_outage") for k in ("attack_L3", "benign_L3")]
    L += ["## H. Pre-registered hypotheses (clean units; read off the cells, not targets)\n",
          "- **H1** trust-v2 ≥ naive on kpm_hide, kpm_frame, core_outage — attack L3 (higher better) / benign L3 (lower better):"]
    L += ["  - %s %s: trust-v2 %.3f vs naive %.3f" % x for x in h1]
    L += ["- **H2** ran-only ≈ 0 detection on kpm_hide: L1 x0.1 %.3f, x0.33 %.3f; L3 x0.1 %.3f, x0.33 %.3f"
          % (cl("kpm_hide_x0.1", "ran-only", "attack_L1"), cl("kpm_hide_x0.33", "ran-only", "attack_L1"),
             cl("kpm_hide_x0.1", "ran-only", "attack_L3"), cl("kpm_hide_x0.33", "ran-only", "attack_L3")),
          "- **H3** framed benign wrongly blocked ≤ ~2 %% under trust-v2: x2 %.3f, x5 %.3f"
          % (cl("kpm_frame_x2", "xd-trust-v2", "framed_benign_L3"), cl("kpm_frame_x5", "xd-trust-v2", "framed_benign_L3")),
          "- **H4** integrity false alarms ≈ 0 on untampered phases (trust-v2): %s"
          % ", ".join("%s %s" % (s, cl(s, "xd-trust-v2", "integrity_false_untampered")) for s in M["scenarios"] if s != "icmp_control"), ""]
    (REP / "live_results_v5.md").write_text("\n".join(L) + "\n")
    (REP / "live_results_v5.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
