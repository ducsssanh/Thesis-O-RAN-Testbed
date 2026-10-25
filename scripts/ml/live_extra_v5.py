#!/usr/bin/env python3
"""Extra live analyses of the v5 main campaign (after live_eval_v5.py, which writes live_units_v5.csv).

  .venv-ml/bin/python -I scripts/ml/live_extra_v5.py [--boot 1000]

Writes reports/live_extra_v5.{md,json}:
  A. icmp control pair: icmp_flood detected (L1) / blocked (L3) and icmp_ping wrongly L1 / L3, per config
  B. core_outage: L1 and L3 apart for outage phases (A1-EI adapter down: no URR / profiler) and the
     phases with the core telemetry present; the trust-weighted L3 needs core evidence by design
  C. kpm_hide: time phase start -> L3 (block); attacker UL bytes at the DN before / after the block
     (dataplane/dn_per_second.csv ip_payload_bytes, phase window [t_start, t_end + 2 s])
  D. sensitivity: every cell without the runs flagged by qa_v5 (classifier fallback inside a phase)
  E. failed attempts per cell (all attempts of the main tag; testbed failures, re-run)
  F. hypotheses H1-H4 of the pre-registration, read off the cells
Bracketed values: 95 % bootstrap CI over runs (live_eval_v5.boot).
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


def phase_bytes(units):
    """Per attack unit of kpm_hide: attacker DN UL bytes before / after the block (t_l3)."""
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
        sb, sa = max(1.0, (tb or t1 + 2) - t0), max(1.0, t1 + 2 - tb) if tb else 0.0
        out.append({"run": u.run, "config": u.config, "scenario": u.scenario, "blocked": int(bool(tb)), "t_l3": u.t_l3,
                    "bytes_before": float(bef.ip_payload_bytes.sum()), "bytes_after": float(aft.ip_payload_bytes.sum()),
                    "kbps_before": float(bef.ip_payload_bytes.sum()) * 8 / 1000 / sb,
                    "kbps_after": float(aft.ip_payload_bytes.sum()) * 8 / 1000 / sa if tb else np.nan})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000)
    B = ap.parse_args().boot
    U = pd.read_csv(REP / "live_units_v5.csv")
    M = json.loads(MAN.read_text())
    res, L = {}, ["# v5 live — extra analyses (main campaign, 224 valid runs)\n",
                  "Unit = (run, UE, phase). Brackets: 95 % bootstrap CI over runs. Levels = enforced by the xApp "
                  "(L1 = quarantine slice / UPF monitor, L3 = UPF block).\n"]

    # A. icmp control
    C = U[U.control == 1]
    L += ["## A. icmp control pair (icmp_flood vs icmp_ping, honest telemetry)\n",
          "| config | runs | flood L1 | flood L3 | ping L1 | ping L3 |", "|---|---:|---|---|---|---|"]
    res["icmp"] = {}
    for c in CONFIGS:
        g = C[C.config == c]
        f, p = g[g.mal == 1], g[g.mal == 0]
        row = [g.run.nunique(), rate(f, "l1", B), rate(f, "l3", B), rate(p, "l1", B), rate(p, "l3", B)]
        res["icmp"][c] = row
        L.append("| %s | %s |" % (c, " | ".join(map(str, row))))
    L.append("")

    # B. core outage
    O = U[(U.scenario == "core_outage") & (U.control == 0)]
    L += ["## B. core_outage: L1 vs L3, outage phases vs core-present phases (attacker / benign)\n",
          "Outage phases = 0 and 3 (A1-EI adapter scaled to 0: no URR, no profiler). Trust-weighted v1/v2 need core "
          "evidence for L3 by design (L3 = L1 held ≥ 10 s AND core in 3 of 5 s), so L3 ≈ 0 in outage phases is the "
          "design, not a miss; L1 there comes from the RAN fallback (ct = 0 → z_ran).\n",
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

    # C. kpm_hide: time to block, DN bytes before / after
    H = U[U.scenario.str.startswith("kpm_hide") & (U.control == 0) & (U.mal == 1)]
    PB = phase_bytes(H)
    L += ["## C. kpm_hide: time to block and attacker bytes at the DN\n",
          "t→L3 = phase start → UPF block (median / p90 over blocked phases). Bytes = attacker UL IP payload at the DN "
          "in the phase window; 'after/before' compares the mean rate after the block with the rate before it.\n",
          "| scenario | config | attack phases | blocked | t→L3 med / p90 (s) | rate before block (kbit/s, med) | rate after block (kbit/s, med) | after/before | share of phase bytes after block |",
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
    rows, worst = [], 0.0
    for (s, c), g in U.groupby(["scenario", "config"]):
        gf = Uf[(Uf.scenario == s) & (Uf.config == c)]
        if len(gf) == len(g):
            continue
        a, b = LE.cell(g, 0), LE.cell(gf, 0)
        d = {k: (a.get(k), b.get(k)) for k in keys if a.get(k) is not None}
        worst = max([worst] + [abs(x - y) for x, y in d.values() if y is not None])
        rows.append("| %s | %s | %d → %d | %s |" % (s, c, g.run.nunique(), gf.run.nunique(),
                    ", ".join("%s %.3f → %.3f" % (k, x, y) for k, (x, y) in d.items() if y is not None)))
    L += ["## D. Sensitivity: without the flagged runs %s (classifier fallback inside a phase)\n" % FLAGGED,
          "Largest absolute change of any cell metric: **%.3f**.\n" % worst,
          "| scenario | config | runs | all runs → without flagged |", "|---|---|---|---|"] + rows + [""]
    res["sensitivity_max_abs_change"] = worst

    # E. failed attempts per cell
    ids = S.config_reps(list(range(1, len(M["runs"]) + 1)), M, "rules-v1=1,3")
    at = S.attempts(MAN, "main")
    tab = {}
    for i in ids:
        r = M["runs"][i - 1]
        n, ok = at.get(i, (0, False))
        t = tab.setdefault(r["scenario"], {}).setdefault(r["config"], [0, 0])
        t[0] += n - int(ok)
        t[1] += n
    L += ["## E. Failed attempts per cell (testbed failures, all re-run; valid runs 6 per cell, rules-v1 2)\n",
          "| scenario | " + " | ".join(CONFIGS) + " |", "|---|" + "---:|" * len(CONFIGS)]
    for s in M["scenarios"]:
        L.append("| %s | %s |" % (s, " | ".join("%d/%d" % tuple(tab[s].get(c, [0, 0])) for c in CONFIGS)))
    tot = [sum(tab[s].get(c, [0, 0])[0] for s in tab) for c in CONFIGS]
    L += ["| **all** | %s |" % " | ".join(map(str, tot)), "", "(failed / attempts)\n"]
    res["failures"] = tab

    # F. hypotheses
    R = json.loads((REP / "live_eval_v5.json").read_text())["results"]
    g = lambda s, c, k: R[s][c].get(k)
    h1 = [(s, k, g(s, "xd-trust-v2", k), g(s, "xd-naive", k)) for s in
          ("kpm_hide_x0.1", "kpm_hide_x0.33", "kpm_frame_x2", "kpm_frame_x5", "core_outage") for k in ("attack_L3", "benign_L3")]
    L += ["## F. Pre-registered hypotheses (read off the cells; not targets)\n",
          "- **H1** trust-v2 ≥ naive on kpm_hide, kpm_frame, core_outage — attack L3 (higher better) / benign L3 (lower better):"]
    L += ["  - %s %s: trust-v2 %.3f vs naive %.3f" % x for x in h1]
    L += ["- **H2** ran-only ≈ 0 detection on kpm_hide: attack L1 x0.1 %.3f, x0.33 %.3f"
          % (g("kpm_hide_x0.1", "ran-only", "attack_L1"), g("kpm_hide_x0.33", "ran-only", "attack_L1")),
          "- **H3** framed benign wrongly blocked ≤ ~2 %% under trust-v2: x2 %.3f, x5 %.3f"
          % (g("kpm_frame_x2", "xd-trust-v2", "framed_benign_L3"), g("kpm_frame_x5", "xd-trust-v2", "framed_benign_L3")),
          "- **H4** integrity false alarms ≈ 0 on untampered phases (trust-v2): %s"
          % ", ".join("%s %s" % (s, g(s, "xd-trust-v2", "integrity_false_untampered")) for s in R), ""]
    (REP / "live_extra_v5.md").write_text("\n".join(L) + "\n")
    (REP / "live_extra_v5.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
