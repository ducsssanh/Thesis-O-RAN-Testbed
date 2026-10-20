#!/usr/bin/env python3
"""QA for a v4 dataset build (subset of v4 plan §7.2 that applies from Phase 1 on).

  .venv-ml/bin/python -I scripts/ml/qa_v4.py --data research/datasets/oran_flooding_v4_pilot RUN_DIR [RUN_DIR ...]

Writes <data>/qa_report.md:
  - independent causality audit: for every row, the URR/profiler/KPM record it used
    is re-located in the RAW files by its source_ts and checked arrival_ts <= t
    (does not trust the builder);
  - C5 comparison: share of the SAME run's v3-style xApp feature rows that used a
    future (+1 s) URR/profiler sample -- the leak v4 removes;
  - age distributions, feature presence by label;
  - design balance (label x UE) -- flags the C1 confound if a UE is single-class;
  - achieved vs offered per (phase, UE) from metrics.json (achieved_ok, +-10%).
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_dataset_v4 as B


def causality_audit(df, runs):
    srcs = {}
    for rd in runs:
        rd = pathlib.Path(rd); rid = "/".join(rd.parts[-4:])
        srcs[rid] = {"kpm": B.load_kpm(rd), "urr": B.load_urr(rd), "prof": B.load_prof(rd)}
    viol, checked = {"kpm": 0, "urr": 0, "prof": 0}, {"kpm": 0, "urr": 0, "prof": 0}
    for _, r in df.iterrows():
        s = srcs.get(r["meta_run_id"])
        if s is None:
            continue
        t = r["meta_t_unix"]
        for kind, agecol in (("kpm", "meta_kpm_age_s"), ("urr", "meta_urr_age_s"), ("prof", "meta_prof_age_s")):
            age = r[agecol]
            if pd.isna(age):
                continue
            src = t - age
            cands = [x for x in s[kind] if x["supi"] == r["meta_supi"] and abs(x["source_ts"] - src) < 1e-4]
            if not cands:
                continue
            checked[kind] += 1
            # the builder picks the latest causal record; if ANY candidate with this source arrived <= t it is causal
            if min(c["arrival_ts"] for c in cands) > t + 1e-9:
                viol[kind] += 1
    return viol, checked


def c5_leak(runs):
    tot = urr_f = prof_f = 0
    for rd in runs:
        for line in (pathlib.Path(rd) / "defense/features.jsonl").read_text().splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            tot += 1
            urr_f += int(o.get("urr_offset_s", 0) == 1)
            prof_f += int(o.get("prof_offset_s", 0) == 1)
            # negative age = record arrived after the KPM sample it was joined to
    return tot, urr_f, prof_f


def _ovl(a, b, bins):
    """Overlap coefficient of two samples over shared histogram bins: Σ min(p_a, p_b)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return None
    edges = np.histogram_bin_edges(np.concatenate([a, b]), bins=bins)
    pa = np.histogram(a, edges)[0] / len(a)
    pb = np.histogram(b, edges)[0] / len(b)
    return float(np.minimum(pa, pb).sum())


def load_overlap(df, feats, bins=12):
    """Overlap coefficient per feature between BENIGN and MALICIOUS, by load level
    (and pooled) — high overlap ⇒ volume/rate alone does not separate the classes."""
    nb = df[df.label.isin(["BENIGN", "MALICIOUS"])]
    rows = []
    groups = [("all", nb)] + [(f"{lv:g} Mbit/s", g) for lv, g in nb.groupby("meta_load_mbps")]
    for name, g in groups:
        ben, mal = g[g.label == "BENIGN"], g[g.label == "MALICIOUS"]
        rec = {"stratum": name, "n_ben": len(ben), "n_mal": len(mal)}
        for f in feats:
            rec[f] = _ovl(ben[f], mal[f], bins)
        rows.append(rec)
    return rows


def cem_support(df, feats, k=5):
    """Coarsened exact matching on `feats`: coarsen each to k quantile bins, form the
    joint cell, and report the share of MALICIOUS (and BENIGN) rows that fall in a cell
    containing BOTH classes (common support), plus the L1 imbalance before/after."""
    nb = df[df.label.isin(["BENIGN", "MALICIOUS"])].copy()
    use = [f for f in feats if nb[f].notna().sum() > 10]
    if not use:
        return None
    codes = []
    for f in use:
        q = pd.qcut(nb[f].rank(method="first"), k, labels=False, duplicates="drop")
        codes.append(q.astype("Int64").astype(str))
    nb["_cell"] = codes[0].str.cat(codes[1:], sep="|") if len(codes) > 1 else codes[0]
    cell_lab = nb.groupby("_cell")["label"].nunique()
    common = set(cell_lab[cell_lab == 2].index)
    mal, ben = nb[nb.label == "MALICIOUS"], nb[nb.label == "BENIGN"]
    share_mal = float(mal["_cell"].isin(common).mean()) if len(mal) else 0.0
    share_ben = float(ben["_cell"].isin(common).mean()) if len(ben) else 0.0
    # L1 imbalance of the cell distributions (before vs restricted to common support)
    def l1(a, b):
        cells = set(a.index) | set(b.index)
        pa = a.reindex(cells, fill_value=0) / a.sum()
        pb = b.reindex(cells, fill_value=0) / b.sum()
        return float((pa - pb).abs().sum())
    m_all, b_all = mal["_cell"].value_counts(), ben["_cell"].value_counts()
    m_c = mal[mal["_cell"].isin(common)]["_cell"].value_counts()
    b_c = ben[ben["_cell"].isin(common)]["_cell"].value_counts()
    return {"feats": use, "k": k, "share_mal": share_mal, "share_ben": share_ben,
            "l1_before": l1(m_all, b_all), "l1_after": l1(m_c, b_c) if len(common) else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    root = pathlib.Path(a.data)
    df = pd.read_parquet(root / "rows.parquet")
    L = []
    L.append(f"# v4 QA report — `{root}`\n")
    L.append(f"Rows: {len(df)} · " + " · ".join(f"{k} {v}" for k, v in df['label'].value_counts().items()) + "\n")

    viol, checked = causality_audit(df, a.runs)
    L.append("## 1. Causality audit (independent of the builder)\n")
    L.append("| stream | rows checked | violations (arrival_ts > t) |\n|---|---:|---:|")
    for k in ("kpm", "urr", "prof"):
        L.append(f"| {k} | {checked[k]} | **{viol[k]}** |")
    tot, uf, pf = c5_leak(a.runs)
    L.append(f"\nFor comparison, the v3-style xApp join (`defense/features.jsonl`) of the same run: {tot} rows, "
             f"**{uf} ({100*uf/max(tot,1):.1f}%) used a future (+1 s) URR sample and {pf} ({100*pf/max(tot,1):.1f}%) "
             f"a future profiler sample** — the C5 leak the v4 build removes.\n")

    L.append("## 2. Data age (s) at the row's second\n")
    L.append("| stream | median | p90 | max | present % |\n|---|---:|---:|---:|---:|")
    for k, f in (("kpm", "rate_ul_kbps"), ("urr", "urr_ul_kbps"), ("prof", "prof_ul_kbps")):
        s = df[f"meta_{k}_age_s"].dropna()
        L.append(f"| {k} | {s.median():.2f} | {s.quantile(.9):.2f} | {s.max():.2f} | {100*df[f].notna().mean():.1f} |")
    L.append("\nPresence by label (URR / profiler):\n")
    L.append("| label | URR % | prof % |\n|---|---:|---:|")
    for lab, g in df.groupby("label"):
        L.append(f"| {lab} | {100*g['urr_ul_kbps'].notna().mean():.1f} | {100*g['prof_ul_kbps'].notna().mean():.1f} |")

    L.append("\n## 3. Design balance (excl. IDLE)\n")
    nb = df[df.label != "IDLE"]
    ct = pd.crosstab(nb["meta_ue"], nb["label"])
    try:
        L.append(ct.to_markdown())
    except ImportError:
        L.append("```\n" + ct.to_string() + "\n```")
    pm = (nb.label == "MALICIOUS").groupby(nb["meta_ue"]).mean()
    flag = [ue for ue, p in pm.items() if not 0.45 <= p <= 0.55]
    L.append(f"\nP(malicious | UE): " + ", ".join(f"{u} {p:.2f}" for u, p in pm.items()) +
             (f"\n\n**UE-balance not yet met** — {flag} outside [0.45, 0.55]: label still tracks UE. "
              "Full per-phase role-swap balance is the Phase-3 campaign-design job." if flag else "\n\nBalanced on UE."))
    # balance on the other nuisances the design must decorrelate from the label
    for col, lo, hi, nm in (("meta_backend", 0.4, 0.6, "backend"),
                            ("meta_victim_mode", 0.4, 0.6, "victim mode"),
                            ("meta_load_mbps", 0.0, 1.0, "load level")):
        if col in nb and nb[col].notna().any():
            pmc = (nb.label == "MALICIOUS").groupby(nb[col]).mean()
            # only dual-use categories are expected ~0.5; benign-only hard-negatives
            # (dns_client, tcp_shortconn) are 0 by design and not a confound.
            dual = {k for k, g in nb.groupby(col) if g["label"].nunique() == 2} if col == "meta_backend" else set(pmc.index)
            fl = [str(k) for k, p in pmc.items() if k in dual and not lo <= p <= hi] if hi < 1.0 else []
            note = {"meta_backend": " (benign-only backends excluded)"}.get(col, "")
            L.append(f"\nP(malicious | {nm}): " + ", ".join(f"{k} {p:.2f}" for k, p in pmc.items()) +
                     (f"  — **dual-use outside [{lo}, {hi}]: {fl}**{note}" if fl else
                      (f"  — dual-use in band{note}" if hi < 1.0 else "  (load distribution should match across classes)")))

    L.append("\n## 4. Achieved vs target (URR ground truth, ±10%, per native unit)\n")
    av = nb[~nb["meta_guard"].astype(bool)].dropna(subset=["meta_achieved_ok"]) if "meta_achieved_ok" in nb else nb.iloc[0:0]
    pair = av.groupby(["meta_phase", "meta_ue"]).agg(
        backend=("meta_backend", "first"), unit=("meta_native_unit", "first"),
        ok=("meta_achieved_ok", "first")).reset_index()
    L.append("| phase | ue | backend | unit | achieved_ok |\n|---|---|---|---|---|")
    for _, r in pair.iterrows():
        L.append(f"| {r['meta_phase']} | {r['meta_ue']} | {r['backend']} | {r['unit']} | {'yes' if r['ok'] == 1 else '**no**'} |")
    nconn = int((nb["meta_native_unit"] == "conn").any()) if "meta_native_unit" in nb else 0
    ok = int(pair["ok"].sum()); tot = len(pair)
    L.append(f"\nachieved_ok: {ok}/{tot} phase-UE pairs (target ≥ 90%)."
             + (" conn-rate backends (tcp_shortconn) are checked by connection completion, not URR." if nconn else ""))

    L.append("\n## 5. Load overlap between classes (volume cannot separate them)\n")
    ovf = [("thp_ul_kbps", "RAN UL thp"), ("urr_ul_pps", "URR UL pps"),
           ("prof_ul_mean_bytes", "pkt mean B"), ("urr_dl_kbps", "URR DL")]
    have = [(f, nm) for f, nm in ovf if f in df]
    rows = load_overlap(df, [f for f, _ in have])
    L.append("Overlap coefficient (Σ min of the two normalised histograms; 1 = identical, 0 = disjoint):\n")
    L.append("| stratum | n ben | n mal | " + " | ".join(nm for _, nm in have) + " |")
    L.append("|---|---:|---:|" + "|".join("---:" for _ in have) + "|")
    for r in rows:
        L.append(f"| {r['stratum']} | {r['n_ben']} | {r['n_mal']} | "
                 + " | ".join("—" if r[f] is None else f"{r[f]:.2f}" for f, _ in have) + " |")
    cem = cem_support(df, ["urr_ul_kbps", "urr_ul_pps", "urr_dl_kbps"])
    if cem:
        L.append(f"\nCoarsened exact matching on UL bytes/UL pps/DL bytes ({cem['k']} bins each): "
                 f"**{100*cem['share_mal']:.0f}% of MALICIOUS** and **{100*cem['share_ben']:.0f}% of BENIGN** rows fall in a "
                 f"cell containing BOTH classes (common support). Cell-distribution L1 imbalance "
                 f"{cem['l1_before']:.2f} → {('%.2f' % cem['l1_after']) if cem['l1_after'] is not None else 'n/a'} after "
                 f"restricting to common support. High common support ⇒ a volume-matched control exists for the thesis.")

    (root / "qa_report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
