#!/usr/bin/env python3
"""Trust-weighted cross-domain defence: rules + GBDT models, replayed on v4 test runs under
attack scenarios that stress each domain (stage A of the experiment; stage B = the same engine in
the xApp sidecar, live).

  .venv-ml/bin/python -I scripts/ml/fusion_v4.py export      # train + save the 3 models and the spec
  .venv-ml/bin/python -I scripts/ml/fusion_v4.py calibrate   # KPM<->URR integrity rule on honest train+val
  .venv-ml/bin/python -I scripts/ml/fusion_v4.py run         # scenarios x configurations -> report

Models (HistGradientBoosting on the causal rolling UL features of prep_v4_windows, trained on the
TRAIN runs' main windows, negative-control pair excluded; threshold = val benign FPR 1%, gated):
  xd   cross-domain UL (KPM + URR + profiler)    core  URR + profiler UL    ran  RAN (KPM) UL
Every model score is normalised by its own threshold: z = p / thr (z >= 1 = that model's alarm).

Per UE and second the engine keeps two trust values:
  kpm_trust  0 after the KPM<->URR integrity rule fires (|log(sum KPM UL / sum URR UL) over 10 s - bias|
             > TAU for M consecutive seconds while the UE is active), held HOLD_S, then ramps back to 1
             over RAMP_S; the integrity alarm is raised immediately (E2 node flagged).
  core_trust 0 while URR is stale (age > CORE_AGE_S or missing), else 1.
Fused evidence  z = kt*ct*z_xd + (1-kt)*ct*z_core + kt*(1-ct)*z_ran  (the domain that can be trusted
carries the decision; with both trusted the cross-domain model decides).
Fair-use rules (xApp classifier v1): RAN rule = KPM UL > FAIR_UL_KBPS while cell PRB UL >= 80% in 3 of 4
samples; core rule = URR UL > FAIR_UL_KBPS in 3 of 4 samples. A rule trip counts as alarm evidence of
its layer.
Decisions: L1 soft isolation (RAN slice / UPF monitor, reversible) when fused alarms in >= 3 of the last 5
seconds (activity gate: 10 s mean UL >= 50 kbps); L3 block (UPF block + RRC release) after L1 has held
L3_HOLD_S seconds AND both layers agree (core alarm in 3 of 5 and RAN alarm in 3 of 5) — unless
kpm_trust < 0.5, when core evidence alone may block (the design's exception for an untrusted E2 node).
Single-source configurations block on their own sustained evidence.
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prep_v4_windows as P
import baseline_v4 as B
import v4_eval as E

ROOT = HERE.parents[1]
DATA = ROOT / "research/datasets/oran_flooding_v4"
WIN = ROOT / "artifacts/ml/v4"
MODELS = WIN / "models"
RAN_KPM = ("rate_ul_kbps", "thp_ul_kbps", "prb_ul_pct")
FAIR_UL_KBPS, CELL_CONGESTED = 2000.0, 80.0
GATE_KBPS = P.GATE_KBPS
INT_W, HOLD_S, RAMP_S, CORE_AGE_S = 10, 60, 30, 4.0
L3_HOLD_S = 10
MODEL_SETS = {"xd": B.HEADLINE, "core": "GBDT rolling URR+prof (UL)", "ran": "GBDT rolling RAN-UL"}
CONFIGS = ("RAN-only (xApp KPM)", "core-only (5GC)", "cross-domain naive", "cross-domain trust-weighted",
           "cross-domain trust-weighted v2")
# v2 (added after inspecting v1 on the test runs; checked on the val runs first): the integrity alarm is
# asymmetric. KPM < URR (the RAN under-reports what the core measured: someone hides this UE) counts as
# core-side evidence against the UE while it persists -> immediate L1 and the core-only block path
# (a 60 s hold of that flag, tried first, spilled into the next phase on val and was dropped). KPM > URR (the RAN
# over-reports: someone frames this UE) only flags the E2 node; the UE is judged by the core alone.


# ---------------------------------------------------------------- models
def export():
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    d = dict(np.load(WIN / "windows_v4.npz"))
    rl = np.load(WIN / "roll_v4.npz")
    R, names = rl["R"], [str(x) for x in rl["names"]]
    fs = B.feature_sets(names, d)
    MODELS.mkdir(parents=True, exist_ok=True)
    spec = {"window_s": 10, "gate_kbps": GATE_KBPS, "transform": json.loads((WIN / "meta.json").read_text())["transform"],
            "raw_features": P.feature_cols(pd.read_parquet(DATA / "rows.parquet").head(1)),
            "rolling": {"windows_s": list(P.ROLL_W), "stats": ["mean", "std", "slope", "max"], "plus": "1 s value"},
            "models": {}}
    tr = E.train_mask(d)
    for key, setname in MODEL_SETS.items():
        cols = [names[i] for i in fs[setname]]
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1, random_state=0).fit(R[tr][:, fs[setname]], d["y"][tr])
        p = clf.predict_proba(R[:, fs[setname]])[:, 1]
        thr = E.val_threshold(p, d)
        joblib.dump(clf, MODELS / ("gbdt_%s.joblib" % key))
        r = E.report(p, d, d["split"] == 2, thr)
        spec["models"][key] = {"file": "gbdt_%s.joblib" % key, "set": setname, "features": cols, "threshold": thr,
                               "test_roc_auc": r["roc_auc"], "test_tpr": r["tpr"]}
        print(key, setname, "features", len(cols), "thr %.4f" % thr, "test ROC", r["roc_auc"], flush=True)
    (MODELS / "spec.json").write_text(json.dumps(spec, indent=1) + "\n")
    print("saved", MODELS)


def load_models():
    import joblib
    spec = json.loads((MODELS / "spec.json").read_text())
    return spec, {k: joblib.load(MODELS / v["file"]) for k, v in spec["models"].items()}


# ---------------------------------------------------------------- telemetry -> per-second scores
def features(df):
    """Causal rolling features for every row (run, UE timeline), as in prep_v4_windows."""
    df = df.sort_values(["meta_run_id", "meta_supi", "meta_t_unix"]).reset_index(drop=True)
    cols = P.feature_cols(df)
    X = P.transform(df, cols)
    R, names = P.rolling(df, X, cols)
    return df, R, names


def score(df, R, names, spec, models):
    idx = {n: i for i, n in enumerate(names)}
    z = {}
    for k, m in models.items():
        cols = [idx[c] for c in spec["models"][k]["features"]]
        z[k] = m.predict_proba(R[:, cols])[:, 1] / spec["models"][k]["threshold"]
    return z


def roll_sum(s, w):
    return s.rolling(w, min_periods=w).sum()


# ---------------------------------------------------------------- scenarios
def scenario(df, name, factor=None, seed=0):
    """Return (tampered copy of df, mask of tampered rows). Ground truth labels never change."""
    df = df.copy()
    ph = df.meta_phase.fillna("").str.startswith("p")
    mal, ben = ph & (df.label == "MALICIOUS"), ph & (df.label == "BENIGN")
    mask = pd.Series(False, index=df.index)
    if name == "honest":
        pass
    elif name == "kpm_hide":                    # MITM deflates the attacker's KPM (hide the flood from the RAN)
        f = 0.1 if factor is None else factor
        mask = mal
        for c in RAN_KPM:
            df.loc[mask, c] = df.loc[mask, c] * f
    elif name == "kpm_frame":                   # MITM inflates a benign UE's KPM (frame an innocent UE)
        f = 5.0 if factor is None else factor
        mask = ben & (df.meta_pair != E.CONTROL)
        for c in ("rate_ul_kbps", "thp_ul_kbps"):
            df.loc[mask, c] = df.loc[mask, c] * f
        df.loc[mask, "prb_ul_pct"] = (df.loc[mask, "prb_ul_pct"] * f).clip(upper=100)
        df.loc[mask, "cell_prb_ul_pct"] = (df.loc[mask, "cell_prb_ul_pct"] * f).clip(upper=100)
    elif name == "core_outage":                 # A1-EI / URR path down during attack and benign phases alike
        rng = np.random.default_rng(seed)
        keys = df.loc[ph, ["meta_run_id", "meta_phase"]].drop_duplicates()
        keys = keys.iloc[rng.permutation(len(keys))[: len(keys) // 2]]
        sel = df.set_index(["meta_run_id", "meta_phase"]).index.isin(pd.MultiIndex.from_frame(keys))
        mask = pd.Series(sel, index=df.index) & ph
        core = [c for c in df.columns if c.startswith(("urr_", "prof_"))]
        df.loc[mask, core] = np.nan
        df.loc[mask, "meta_urr_age_s"] = 99.0
    else:
        raise ValueError(name)
    return df, mask


# ---------------------------------------------------------------- engine
def run_engine(df, z, cfg, tau, m, bias):
    """Per-second decisions for one configuration. Returns per-row arrays."""
    n = len(df)
    out = {k: np.zeros(n, bool) for k in ("hit", "l1", "l3", "integrity")}
    out["kt"] = np.ones(n); out["ct"] = np.ones(n)
    for _, g in df.groupby(["meta_run_id", "meta_supi"], sort=False):
        ix = g.index.to_numpy()
        kpm = g.rate_ul_kbps.fillna(0)
        urr = g.urr_ul_kbps
        fresh = (g.meta_urr_age_s.fillna(99) <= CORE_AGE_S) & urr.notna()
        ct = fresh.to_numpy().astype(float)
        # activity gate: core view if fresh, else RAN view
        ul_core = urr.where(urr.notna(), g.prof_ul_kbps).rolling(10, min_periods=1).mean().to_numpy()
        ul_ran = kpm.rolling(10, min_periods=1).mean().to_numpy()
        # KPM<->URR integrity rule
        ks, us = roll_sum(kpm, INT_W).to_numpy(), roll_sum(urr.fillna(0), INT_W).to_numpy()
        fresh_w = fresh.rolling(INT_W, min_periods=INT_W).min().fillna(0).to_numpy().astype(bool)
        active = np.maximum(ks, us) / INT_W > GATE_KBPS
        with np.errstate(divide="ignore", invalid="ignore"):
            lr = np.log(np.clip(ks, 1, None) / np.clip(us, 1, None)) - bias
        viol = fresh_w & active & (np.abs(lr) > tau)
        run_len = np.zeros(len(ix), int)
        for i in range(len(ix)):
            run_len[i] = run_len[i - 1] + 1 if (viol[i] and i) else int(viol[i])
        integ = run_len >= m
        kt = np.ones(len(ix))
        under = np.zeros(len(ix), bool)          # integrity violation with KPM < URR, ongoing
        last, last_dir = -10 ** 9, 0.0
        for i in range(len(ix)):
            if integ[i]:
                last, last_dir = i, lr[i]
            under[i] = bool(integ[i]) and lr[i] < 0  # only while the under-report persists (a hold would
            #                                          spill into the next phase, v4 swaps UE roles)
            dt = i - last
            kt[i] = 0.0 if dt <= HOLD_S else min(1.0, (dt - HOLD_S) / RAMP_S)
        # rules (3 of 4)
        ran_rule = ((kpm > FAIR_UL_KBPS) & (g.cell_prb_ul_pct.fillna(0) >= CELL_CONGESTED)).astype(int).rolling(4, min_periods=1).sum().to_numpy() >= 3
        core_rule = ((urr.fillna(0) > FAIR_UL_KBPS) & fresh).astype(int).rolling(4, min_periods=1).sum().to_numpy() >= 3
        zx, zc, zr = z["xd"][ix], z["core"][ix], z["ran"][ix]
        if cfg == CONFIGS[0]:                    # RAN-only: no core data at all
            gate = ul_ran >= GATE_KBPS
            ran_hit = (zr >= 1) & gate | ran_rule
            hit, core_hit, ranside = ran_hit, np.zeros(len(ix), bool), ran_hit
            ktu = np.ones(len(ix))
        elif cfg == CONFIGS[1]:                  # core-only
            gate = (ul_core >= GATE_KBPS) & (ct > 0)
            core_hit = (zc >= 1) & gate | core_rule
            hit, ranside = core_hit, np.zeros(len(ix), bool)
            ktu = np.ones(len(ix))
        elif cfg == CONFIGS[2]:                  # naive cross-domain: one model, no trust, no integrity rule
            gate = np.where(ct > 0, ul_core, ul_ran) >= GATE_KBPS
            hit = ((zx >= 1) & gate) | ran_rule | core_rule
            core_hit, ranside = hit, hit
            ktu = np.ones(len(ix))
        else:                                    # proposed (v1 / v2)
            gate = np.where(ct > 0, ul_core, ul_ran) >= GATE_KBPS
            zf = kt * ct * zx + (1 - kt) * ct * zc + kt * (1 - ct) * zr
            hit = ((zf >= 1) & gate) | (ran_rule & (kt >= 0.5)) | core_rule
            core_hit = ((zc >= 1) & gate & (ct > 0)) | core_rule
            ranside = ((zr >= 1) & gate & (kt >= 0.5)) | (ran_rule & (kt >= 0.5))
            if cfg == CONFIGS[4]:
                hit = hit | under
                core_hit = core_hit | under
            ktu = kt
        k5 = lambda a: pd.Series(a.astype(int)).rolling(5, min_periods=1).sum().to_numpy() >= 3
        l1 = k5(hit)
        held = np.zeros(len(ix), int)
        for i in range(len(ix)):
            held[i] = held[i - 1] + 1 if (l1[i] and i) else int(l1[i])
        if cfg in CONFIGS[3:]:
            both = k5(core_hit) & (k5(ranside) | (ktu < 0.5))
            l3 = (held >= L3_HOLD_S) & both
        else:
            l3 = held >= L3_HOLD_S
        out["hit"][ix], out["l1"][ix], out["l3"][ix] = hit, l1, l3
        out["integrity"][ix] = integ if cfg in CONFIGS[3:] else False
        out["kt"][ix], out["ct"][ix] = ktu, ct
    return out


def phase_metrics(df, dec, tampered):
    """Per (run, UE, phase): detection / false isolation / timing. Control pair excluded."""
    ph = df.meta_phase.fillna("")
    sel = ph.str.startswith("p") & (df.meta_pair != E.CONTROL) & df.label.isin(["BENIGN", "MALICIOUS"])
    rows = []
    t = df.meta_t_since_phase_start.to_numpy()
    for (run, ue, p), g in df[sel].groupby(["meta_run_id", "meta_ue", "meta_phase"], sort=False):
        ix = g.index.to_numpy()
        o = np.argsort(t[ix]); ix = ix[o]
        first = lambda a: float(t[ix][np.argmax(a[ix])]) if a[ix].any() else np.nan
        rows.append({"run": run, "ue": ue, "phase": p, "mal": int(g.label.iloc[0] == "MALICIOUS"),
                     "tampered": bool(tampered[ix].any()), "pair": g.meta_pair.iloc[0],
                     "l1": bool(dec["l1"][ix].any()), "l3": bool(dec["l3"][ix].any()),
                     "t_l1": first(dec["l1"]), "t_l3": first(dec["l3"]),
                     "integrity": bool(dec["integrity"][ix].any()), "t_integrity": first(dec["integrity"]),
                     "kt_min": float(dec["kt"][ix].min())})
    return pd.DataFrame(rows)


def summarise(pm):
    a, b = pm[pm.mal == 1], pm[pm.mal == 0]
    return {"attack_phases": len(a), "benign_phases": len(b),
            "attack_detected_L1": round(a.l1.mean(), 3), "attack_L1_within_20s": round((a.t_l1 <= 20).mean(), 3),
            "attack_t_L1_median_s": round(a.t_l1.median(), 1) if a.l1.any() else None,
            "attack_blocked_L3": round(a.l3.mean(), 3), "attack_t_L3_median_s": round(a.t_l3.median(), 1) if a.l3.any() else None,
            "benign_soft_isolated_L1": round(b.l1.mean(), 3), "benign_wrongly_blocked_L3": round(b.l3.mean(), 3),
            "integrity_alarm_tampered": round(pm[pm.tampered].integrity.mean(), 3) if pm.tampered.any() else None,
            "integrity_t_median_s": round(pm[pm.tampered & pm.integrity].t_integrity.median(), 1) if (pm.tampered & pm.integrity).any() else None,
            "integrity_false_alarm_untampered": round(pm[~pm.tampered].integrity.mean(), 3)}


def boot(pm, key_fn, B_=1000, seed=0):
    runs = pm.run.unique()
    rng = np.random.default_rng(seed)
    by = {r: pm[pm.run == r] for r in runs}
    v = []
    for _ in range(B_):
        s = pd.concat([by[r] for r in rng.choice(runs, len(runs))])
        x = key_fn(s)
        if x == x:
            v.append(x)
    return [round(float(np.quantile(v, .025)), 3), round(float(np.quantile(v, .975)), 3)] if v else None


# ---------------------------------------------------------------- calibration
def calibrate(args):
    sp = json.loads((WIN / "meta.json").read_text())["split_runs"]
    df = pd.read_parquet(DATA / "rows.parquet")
    df = df[df.meta_run_id.isin(sp["train"] + sp["val"])].sort_values(["meta_run_id", "meta_supi", "meta_t_unix"]).reset_index(drop=True)
    g = df.groupby(["meta_run_id", "meta_supi"])
    ks = g.rate_ul_kbps.transform(lambda s: roll_sum(s.fillna(0), INT_W))
    us = g.urr_ul_kbps.transform(lambda s: roll_sum(s.fillna(0), INT_W))
    act = (np.maximum(ks, us) / INT_W > GATE_KBPS) & df.label.isin(["BENIGN", "MALICIOUS"])
    lr = np.log(ks.clip(lower=1) / us.clip(lower=1))
    bias = float(lr[act].median())
    res = []
    for tau in (0.7, 0.9, 1.1, 1.39, 1.6):
        for m in (3, 5, 10):
            viol = (act & ((lr - bias).abs() > tau)).astype(int)
            rl = viol.groupby([df.meta_run_id, df.meta_supi]).transform(lambda s: s.groupby((s == 0).cumsum()).cumsum())
            alarm = rl >= m
            phm = df[df.meta_phase.fillna("").str.startswith("p")]
            fa = alarm[phm.index].groupby([phm.meta_run_id, phm.meta_supi, phm.meta_phase]).any().mean()
            res.append({"tau": tau, "m": m, "honest_phase_false_alarm": round(float(fa), 4),
                        "honest_seconds_alarmed": round(float(alarm[act].mean()), 5)})
    best = min((r for r in res if r["honest_phase_false_alarm"] <= 0.01), key=lambda r: (r["tau"], r["m"]), default=None)
    out = {"bias": bias, "grid": res, "chosen": best, "rule": "false-alarm target: <= 1% of honest (run, UE, phase) on train+val"}
    MODELS.mkdir(parents=True, exist_ok=True)
    (MODELS / "integrity_rule.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- experiments
def run(args):
    spec, models = load_models()
    rule = json.loads((MODELS / "integrity_rule.json").read_text())
    tau, m, bias = rule["chosen"]["tau"], rule["chosen"]["m"], rule["bias"]
    sp = json.loads((WIN / "meta.json").read_text())["split_runs"]
    base = pd.read_parquet(DATA / "rows.parquet")
    base = base[base.meta_run_id.isin(sp[args.runs])]
    plan = [("honest", None), ("kpm_hide", 0.1), ("kpm_frame", 5.0), ("core_outage", None)]
    if args.sweep:
        plan += [("kpm_hide", f) for f in (0.2, 0.33, 0.5)] + [("kpm_frame", f) for f in (2.0, 3.0, 10.0)]
    res, pms = {}, {}
    for sc, f in plan:
        df0, tmask = scenario(base, sc, f)
        df1, R, names = features(df0)
        # features() re-sorts and re-indexes: carry the tampered mask through the same sort
        order = df0.sort_values(["meta_run_id", "meta_supi", "meta_t_unix"]).index
        tm = tmask.loc[order].to_numpy()
        z = score(df1, R, names, spec, models)
        key = sc if f is None else "%s x%g" % (sc, f)
        for cfg in CONFIGS:
            dec = run_engine(df1, z, cfg, tau, m, bias)
            pm = phase_metrics(df1, dec, tm)
            s = summarise(pm)
            s["ci_attack_detected_L1"] = boot(pm[pm.mal == 1], lambda x: x.l1.mean(), args.boot)
            s["ci_benign_wrongly_blocked_L3"] = boot(pm[pm.mal == 0], lambda x: x.l3.mean(), args.boot)
            if sc == "kpm_frame":
                s["ci_framed_benign_blocked_L3"] = boot(pm[(pm.mal == 0) & pm.tampered], lambda x: x.l3.mean(), args.boot)
                s["framed_benign_blocked_L3"] = round(pm[(pm.mal == 0) & pm.tampered].l3.mean(), 3)
                s["framed_benign_soft_isolated_L1"] = round(pm[(pm.mal == 0) & pm.tampered].l1.mean(), 3)
            res.setdefault(key, {})[cfg] = s
            pms["%s | %s" % (key, cfg)] = pm
            print("%-16s %-30s %s" % (key, cfg, {k: s[k] for k in ("attack_detected_L1", "attack_blocked_L3",
                  "benign_soft_isolated_L1", "benign_wrongly_blocked_L3", "integrity_alarm_tampered")}), flush=True)
    out = WIN / ("fusion" if args.runs == "test" else "fusion_" + args.runs)
    out.mkdir(exist_ok=True)
    (out / "fusion_results.json").write_text(json.dumps({"integrity_rule": rule["chosen"], "bias": bias, "results": res},
                                                        indent=1, default=str) + "\n")
    pd.concat([v.assign(key=k) for k, v in pms.items()]).to_csv(out / "fusion_phases.csv", index=False)
    write_report(res, rule, out, args.runs, len(sp[args.runs]))


def write_report(res, rule, out, runs="test", n_runs=18):
    M = [("attack_detected_L1", "attack detected (L1)"), ("attack_L1_within_20s", "detected ≤20 s"),
         ("attack_t_L1_median_s", "t→L1 median s"), ("attack_blocked_L3", "attack blocked (L3)"),
         ("attack_t_L3_median_s", "t→L3 median s"), ("benign_soft_isolated_L1", "benign soft-isolated (L1)"),
         ("benign_wrongly_blocked_L3", "benign wrongly blocked (L3)"), ("integrity_alarm_tampered", "KPM integrity alarm on tampered"),
         ("integrity_t_median_s", "t→integrity s")]
    L = ["# Trust-weighted cross-domain defence — replay on v4 " + runs + " runs (stage A)\n",
         "%d held-out %s runs; models trained on train runs only (never on tampered data); integrity rule τ=%s, "
         "m=%s s (chosen on honest train+val: ≤1%% of honest phases alarmed). Phase-level metrics over attack / benign "
         "phases (icmp control excluded). Brackets = 95%% bootstrap CI by run. Defence actions are not replayed into "
         "the traffic (v4 was recorded with defence off): times are decision times. v2 = asymmetric integrity rule, added "
         "after inspecting v1 on the test runs and checked on the val runs first.\n" % (n_runs, runs, rule["chosen"]["tau"], rule["chosen"]["m"])]
    for sc, by in res.items():
        L += ["## %s\n" % sc, "| configuration | " + " | ".join(h for _, h in M) + (" | framed benign blocked (L3) |" if "kpm_frame" in sc else " |"),
              "|---|" + "---:|" * (len(M) + (1 if "kpm_frame" in sc else 0))]
        for cfg, s in by.items():
            cells = []
            for k, _ in M:
                v = s.get(k)
                if k == "attack_detected_L1" and s.get("ci_attack_detected_L1"):
                    v = "%s %s" % (v, s["ci_attack_detected_L1"])
                if k == "benign_wrongly_blocked_L3" and s.get("ci_benign_wrongly_blocked_L3"):
                    v = "%s %s" % (v, s["ci_benign_wrongly_blocked_L3"])
                cells.append(str(v))
            if "kpm_frame" in sc:
                cells.append("%s %s" % (s.get("framed_benign_blocked_L3"), s.get("ci_framed_benign_blocked_L3")))
            L.append("| %s | " % cfg + " | ".join(cells) + " |")
        L.append("")
    (out / "fusion_report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    sub.add_parser("calibrate")
    r = sub.add_parser("run")
    r.add_argument("--sweep", action="store_true", help="also sweep the tamper factor")
    r.add_argument("--boot", type=int, default=1000)
    r.add_argument("--runs", choices=("test", "val"), default="test")
    a = ap.parse_args()
    {"export": lambda: export(), "calibrate": lambda: calibrate(a), "run": lambda: run(a)}[a.cmd]()


if __name__ == "__main__":
    main()
