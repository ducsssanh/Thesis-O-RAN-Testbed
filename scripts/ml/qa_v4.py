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

try:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold, StratifiedKFold
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import LabelEncoder
    _SK = True
except ImportError:
    _SK = False

FGROUPS = {"RAN": B.KPM, "URR": B.URR, "prof": B.PROF}


def _cv_auc(X, y, groups, n_splits=4):
    """Grouped-CV macro-AUC of predicting y from X. Groups keep a run (or, for a
    1-run pilot, a phase) whole, so the score is not inflated by within-group leakage.
    Chance = 0.5. HGB tolerates NaN features natively."""
    X = X.reset_index(drop=True)
    y = LabelEncoder().fit_transform(np.asarray(y).astype(str))
    groups = np.asarray(groups)
    if len(np.unique(y)) < 2 or len(X) < 20:
        return None
    ng = len(np.unique(groups))
    if ng >= 2:
        k = min(n_splits, ng)
        splits = list(GroupKFold(n_splits=k).split(X, y, groups))
    else:
        splits = list(StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0).split(X, y))
    aucs = []
    for tr, te in splits:
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2 or len(tr) < 10:
            continue
        try:
            clf = HistGradientBoostingClassifier(max_depth=3, max_iter=60,
                                                 min_samples_leaf=max(5, len(tr) // 50), random_state=0)
            clf.fit(X.iloc[tr], y[tr])
            p = clf.predict_proba(X.iloc[te])
            if p.shape[1] == 2:
                aucs.append(roc_auc_score(y[te], p[:, 1]))
            else:
                aucs.append(roc_auc_score(y[te], p, multi_class="ovr", average="macro", labels=clf.classes_))
        except Exception:                             # tiny/degenerate pilot folds: skip, don't crash the report
            continue
    return float(np.mean(aucs)) if aucs else None


def _group_col(df):
    """run_id if ≥2 runs, else phase (so a 1-run pilot still groups sanely)."""
    return ("meta_run_id", False) if df["meta_run_id"].nunique() >= 2 else ("meta_phase", True)


def adversarial_validation(df):
    """Within EACH class, try to predict each nuisance (ue/backend/victim_mode) from
    each telemetry domain. High AUC ⇒ that domain fingerprints that nuisance — a risk
    the detector could exploit as a shortcut. Reported as a finding, not hidden."""
    gcol, fell_back = _group_col(df)
    nb = df[df.label.isin(["BENIGN", "MALICIOUS"])]
    rows = []
    for cls in ("BENIGN", "MALICIOUS"):
        g = nb[nb.label == cls]
        for tgt, nm in (("meta_ue", "ue"), ("meta_backend", "backend"), ("meta_victim_mode", "victim_mode")):
            if tgt not in g or g[tgt].nunique() < 2:
                continue
            rec = {"class": cls, "target": nm, "n_tgt": int(g[tgt].nunique())}
            for dom, feats in FGROUPS.items():
                cols = [f for f in feats if f in g]
                rec[dom] = _cv_auc(g[cols], g[tgt].astype(str), g[gcol])
            rows.append(rec)
    return rows, gcol, fell_back


def nuisance_baseline(df):
    """Predict the LABEL from meta_ only (no telemetry). Two feature sets: 'innocent'
    (ue + timing + load + victim_mode — must-not-leak; target AUC ≈ 0.5) and '+backend'
    (adds backend; benign-only hard-negatives legitimately carry signal)."""
    gcol, _ = _group_col(df)
    nb = df[df.label.isin(["BENIGN", "MALICIOUS"])].copy()
    y = (nb.label == "MALICIOUS").astype(int)
    def enc(cols):
        X = pd.DataFrame(index=nb.index)
        for c in cols:
            if c not in nb:
                continue
            if pd.api.types.is_numeric_dtype(nb[c]):
                X[c] = pd.to_numeric(nb[c], errors="coerce")
            else:
                X[c] = LabelEncoder().fit_transform(nb[c].astype(str))
        return X
    innocent = ["meta_ue", "meta_t_since_phase_start", "meta_load_mbps", "meta_victim_mode"]
    out = {"innocent": _cv_auc(enc(innocent), y, nb[gcol]),
           "with_backend": _cv_auc(enc(innocent + ["meta_backend"]), y, nb[gcol])}
    return out


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

    L.append("\n## 6. Packet-size overlap per attack ↔ counterpart pair\n")
    L.append("Each attack phase pairs the attacker with its load-matched benign counterpart "
             "in the same cell. Overlap of `prof_ul_mean_bytes` (mean packet size) between the two — "
             "a shared size prior should keep UDP pairs high; protocol-fixed pairs (SYN vs short-conn) "
             "differ by design (a *valid* distinguishing signal, not a confound).\n")
    L.append("| phase | attacker (backend/family) | counterpart (backend/class) | size overlap |\n|---|---|---|---:|")
    nbp = df[df.label.isin(["BENIGN", "MALICIOUS"])]
    for ph, g in nbp.groupby("meta_phase"):
        mal, ben = g[g.label == "MALICIOUS"], g[g.label == "BENIGN"]
        if not len(mal) or not len(ben):
            continue
        ov = _ovl(ben["prof_ul_mean_bytes"], mal["prof_ul_mean_bytes"], 12)
        al = f"{mal['meta_backend'].iloc[0]}/{mal['meta_attack_family'].iloc[0]}"
        bl = f"{ben['meta_backend'].iloc[0]}/{ben['meta_benign_class'].iloc[0]}"
        L.append(f"| {ph} | {al} | {bl} | {'—' if ov is None else f'{ov:.2f}'} |")

    L.append("\n## 7. Adversarial validation (nuisance fingerprinting; chance AUC = 0.5)\n")
    if not _SK:
        L.append("_scikit-learn not available — skipped._")
    else:
        rows, gcol, fb = adversarial_validation(df)
        L.append(f"Grouped by `{gcol}`" + (" (1 run → phase groups; campaign will group by run_id)" if fb else "") +
                 ". AUC predicting each nuisance *within* a class, per telemetry domain:\n")
        L.append("| class | nuisance | #vals | RAN | URR | prof |\n|---|---|---:|---:|---:|---:|")
        for r in rows:
            L.append(f"| {r['class']} | {r['target']} | {r['n_tgt']} | "
                     + " | ".join("—" if r.get(d) is None else f"{r[d]:.2f}" for d in ("RAN", "URR", "prof")) + " |")
        L.append("\nHigh AUC ⇒ the domain fingerprints that nuisance. In this 1-run pilot each "
                 "backend occupies a single phase, so `backend` ≈ phase and its AUC is inflated by that "
                 "confound; the campaign (many phases per backend, grouped by run_id) is what makes this "
                 "diagnostic meaningful. `ue | RAN` high would mean RFsim fingerprints the UE.")

    L.append("\n## 8. Nuisance-only baseline (predict label from meta_ only; target AUC ≈ 0.5)\n")
    if not _SK:
        L.append("_scikit-learn not available — skipped._")
    else:
        nbl = nuisance_baseline(df)
        L.append(f"- innocent nuisances (ue + timing + load + victim_mode): **AUC {nbl['innocent']:.2f}**"
                 if nbl["innocent"] is not None else "- innocent: —")
        L.append(f"- + backend: **AUC {nbl['with_backend']:.2f}** (benign-only hard-negative backends "
                 "legitimately carry label signal — expected > 0.5)"
                 if nbl["with_backend"] is not None else "- + backend: —")
        L.append("\nThe innocent-nuisance AUC is the headline confound metric; the Phase-3 campaign "
                 "balance targets drive it to ≈0.5 (the pilot's residual comes from the 0.60/0.40 UE imbalance).")

    if "meta_pair" in df.columns:
        L.append("\n## 9. Per meta_pair (section-6.3 cell)\n")
        L.append("| meta_pair | rows | MAL/BEN | achieved_ok | per-cell size overlap |\n|---|---:|---:|---:|---:|")
        nbp2 = df[df.label.isin(["BENIGN", "MALICIOUS"])]
        for pair, g in nbp2.groupby("meta_pair"):
            mal, ben = int((g.label == "MALICIOUS").sum()), int((g.label == "BENIGN").sum())
            if "meta_achieved_ok" in g:
                ok = g.dropna(subset=["meta_achieved_ok"]).groupby(["meta_phase", "meta_ue"])["meta_achieved_ok"].first()
                okr = f"{ok.mean():.2f}" if len(ok) else "—"
            else:
                okr = "—"
            per = [_ovl(gg[gg.label == "BENIGN"]["prof_ul_mean_bytes"], gg[gg.label == "MALICIOUS"]["prof_ul_mean_bytes"], 12)
                   for _, gg in g.groupby("meta_phase") if gg.label.nunique() == 2]
            per = [x for x in per if x is not None]
            ov = f"{np.median(per):.2f}" if per else "—"
            L.append(f"| {pair} | {len(g)} | {mal}/{ben} | {okr} | {ov} |")

    (root / "qa_report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
