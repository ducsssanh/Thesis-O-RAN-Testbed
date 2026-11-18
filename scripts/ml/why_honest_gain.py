#!/usr/bin/env python3
"""Correction (2026-11-12): where the cross-domain model beats the core-only model at the block tier on GENUINELY honest KPM
(out-of-fold, twin runs and live runs of case honest). SHAP of the deployed ensemble per input group and per input on the attack
seconds of the discordant episodes vs the episodes both block; KPM/core balance and PRB per kbit against benign seconds.
Usage (repo root): why_honest_gain.py"""
import glob, json, re
import numpy as np, xgboost as xgb
src = open("scripts/ml/abl_paired_by_tamper.py").read().rsplit("rng = np.random.default_rng(0)", 1)[0]
exec(compile(src, "pbt", "exec"))
import sys; sys.path.insert(0, "scripts/ml")
from baselines_feat import x31, X31_NAMES as F
A, C = R[MODELS[0][0]][("out-of-fold", "block")], R["core only"][("out-of-fold", "block")]
hon = [k for k in A if case(k).startswith("honest")]
only_a = [k for k in hon if A[k]["det"] and not C[k]["det"]]
both = [k for k in hon if A[k]["det"] and C[k]["det"]]
print("genuinely honest KPM, block: only cross-domain %d (L2 %d), both %d" % (len(only_a), sum(EP[k]["evasion"] == "L2" for k in only_a), len(both)))
for k in only_a:
    e = EP[k]; raw = e["scen"]["honest"]; at = e["run_lab"] == 1
    print("  %-40s %s %s %4.0f kbit/s | masked %3.0f%% | PRB/kbit %.2f | core UL %.0f kbit/s" % (
        e["run"].split("/")[0][-34:] + " " + e["phase"], e["evasion"], e["band"], e["anchor"] / 1e3, 100 * raw[at, 27].mean(),
        x31(raw)[at, F.index("prb_ul_per_kbit")].mean(), np.expm1(raw[at, 6]).mean()))
bst = []
for d in sorted(glob.glob("artifacts/clf/v5/R080_v5/fold9_seed*")):
    b = xgb.Booster(); b.load_model(d + "/model.json"); b.set_param({"nthread": 4}); bst.append((b, json.load(open(d + "/config.json"))["temperature"]))
KPM = [F.index(c) for c in ("prb_ul", "prb_dl", "prb_ul_per_kbit", "w_prb_mean", "w_prb_max", "kpm_age")]
GATE = [F.index(c) for c in ("c_t_w", "trust_ue", "mask_ue")]
def shap(keys):
    X = np.vstack([x31(EP[k]["scen"]["honest"])[EP[k]["run_lab"] == 1] for k in keys])
    Cn = np.mean([b.predict(xgb.DMatrix(X), pred_contribs=True) / T for b, T in bst], 0)
    per = {F[i]: Cn[:, i].mean() for i in range(len(F))}
    top = sorted(per.items(), key=lambda t: -abs(t[1]))[:8]
    return len(X), Cn[:, KPM].sum(1).mean(), Cn[:, GATE].sum(1).mean(), Cn[:, [i for i in range(len(F)) if i not in KPM + GATE]].sum(1).mean(), Cn.sum(1).mean(), top, X
for name, ks in (("only cross-domain blocks", only_a), ("both block", both)):
    n, kp, gt, co, z, top, X = shap(ks)
    print("\nSHAP, %s (%d ep, %d attack s): KPM group %+.2f, gate %+.2f, core and rest %+.2f, mean z %.2f" % (name, len(ks), n, kp, gt, co, z))
    print("  largest mean contributions: " + ", ".join("%s %+.2f" % t for t in top))
    print("  PRB/kbit mean %.2f, PRB UL mean %.1f%%, masked %.1f%%" % (X[:, F.index("prb_ul_per_kbit")].mean(), 100 * X[:, F.index("prb_ul")].mean(), 100 * X[:, F.index("mask_ue")].mean()))
ben = [k for k, e in EP.items() if not e["attack"] and "flood-live-lz" not in k and "flood-live-lb" not in k][:800]
Xb = np.vstack([x31(EP[k]["scen"]["honest"]) for k in ben]); act = np.expm1(Xb[:, 0]) >= 8
print("\nbenign active seconds: PRB/kbit mean %.2f (median %.2f), PRB UL mean %.1f%%, masked %.1f%%" % (
    Xb[act, F.index("prb_ul_per_kbit")].mean(), np.median(Xb[act, F.index("prb_ul_per_kbit")]), 100 * Xb[act, F.index("prb_ul")].mean(), 100 * Xb[:, F.index("mask_ue")].mean()))

# rate-matched: PRB per kbit is naturally high at low rates; compare attack seconds and benign seconds in the same core-UL bins
def bins(keys, attack):
    out = []
    for k in keys:
        raw = EP[k]["scen"]["honest"]; x = x31(raw)
        sel = (EP[k]["run_lab"] == 1) if attack else np.ones(len(raw), bool)
        kb = np.expm1(raw[:, 6])[sel]; pr = raw[:, 2][sel] * 100; pk = np.expm1(raw[:, 8])[sel]
        out += list(zip(kb, pr, pk))
    return np.array(out)
Ab, Bb, Hb = bins(only_a, True), bins(both, True), bins(ben, False)
print("\nrate-matched UL PRB %% and packets/s (mean) per core UL bin:")
for lo, hi in ((8, 30), (30, 60), (60, 100), (100, 150), (150, 300)):
    row = []
    for name, M in (("only-cross attack", Ab), ("both-block attack", Bb), ("benign", Hb)):
        m = (M[:, 0] >= lo) & (M[:, 0] < hi)
        row.append("%s n %5d PRB %4.1f%% pps %5.1f" % (name, m.sum(), M[m, 1].mean() if m.any() else np.nan, M[m, 2].mean() if m.any() else np.nan))
    print("  %3d-%-3d kbit/s | %s" % (lo, hi, " | ".join(row)))
