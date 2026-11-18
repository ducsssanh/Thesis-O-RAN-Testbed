#!/usr/bin/env python3
"""Why L2 and heavy users (P4) are hard: on the training data (mimic episodes, honest scenario) and the R060 out-of-fold scores.
(1) L2 detection by the attacked UE's band; (2) how much the attack adds relative to the UE's own benign load; (3) per-feature
separation (AUC) of L2 attack seconds against benign seconds, P4 vs P1-P3; (4) model score separation by band; (5) gain."""
import glob, json, pickle, sys
import numpy as np
from sklearn.metrics import roc_auc_score
sys.path.insert(0, "scripts/ml")
from baselines_feat import x25
O = "artifacts/clf/mimic"
E = {"|".join((e["run"], e["phase"], e["supi"])): e for f in ("episodes31_m.pkl", "episodes31_l2_m.pkl") for e in pickle.load(open(f"{O}/{f}", "rb"))["episodes"]}
S = [pickle.load(open(f, "rb"))["oof"] for f in sorted(glob.glob(f"{O}/R060/fold*_seed*/scores.pkl"))]
keys = set.intersection(*[set(s) for s in S])
Z = {k: np.mean([s[k]["honest"] for s in S], 0) for k in keys}
NAMES = ["core_ul_kbps", "core_dl_kbps", "core_ul_pps", "core_dl_pps", "prb_ul", "prb_dl", "prb_per_kbit", "size_ul", "size_dl", "dl_over_ul",
         "c_t_w", "trust", "mask", "kpm_age", "prof_age", "w_ul_mean", "w_ul_max", "w_pps_mean", "w_pps_max", "w_prb_mean", "w_prb_max",
         "w_busy", "w_cv", "w_peak", "w_silence"]
L2 = [(k, e) for k, e in E.items() if k in Z and e["attack"] and e["evasion"] == "L2"]
BEN = [(k, e) for k, e in E.items() if k in Z and not e["attack"] and not e["client"]]
print("== (2) attack load relative to the UE's own benign load (L2, active attack seconds), by band")
for b in ("P1", "P2", "P3", "P4"):
    r = []
    for k, e in L2:
        if e["band"] != b: continue
        raw = e["scen"]["honest"]; tot = np.expm1(raw[:, 6]) * 125; att = e["bytes"]; m = (e["active"] == 1) & (tot > 0)
        if m.any(): r.append(np.median(att[m] / np.maximum(tot[m] - att[m], 1)))
    print("  %s  n %3d  median attack/benign bytes per second %.2f" % (b, len(r), np.median(r)))
print("== (4) R060 out-of-fold logit, L2 attack active seconds vs benign seconds of the same band (AUC)")
for b in ("P1", "P2", "P3", "P4"):
    a = np.concatenate([Z[k][(e["active"] == 1)] for k, e in L2 if e["band"] == b])
    n = np.concatenate([Z[k] for k, e in BEN if e["band"] == b])
    print("  %s  attack s %5d  benign s %6d  AUC %.3f  | median z attack %.2f benign %.2f  | block thr 2.61: attack above %.0f%%, benign above %.2f%%" % (
        b, len(a), len(n), roc_auc_score(np.r_[np.ones(len(a)), np.zeros(len(n))], np.r_[a, n]), np.median(a), np.median(n), 100 * (a > 2.61).mean(), 100 * (n > 2.61).mean()))
print("== (3) single-feature AUC (|AUC-0.5| shown as direction-free), L2 attack active seconds vs benign ACTIVE seconds (core UL >= 8 kbit/s)")
def feats(eps, pick):
    out = []
    for k, e in eps:
        x = x25(e["scen"]["honest"]); m = pick(e, x)
        if m.any(): out.append(x[m])
    return np.concatenate(out)
for grp, bands in (("P4", ("P4",)), ("P1-P3", ("P1", "P2", "P3"))):
    A = feats([(k, e) for k, e in L2 if e["band"] in bands], lambda e, x: e["active"] == 1)
    B = feats([(k, e) for k, e in BEN if e["band"] in bands], lambda e, x: np.expm1(x[:, 0]) >= 8)
    y = np.r_[np.ones(len(A)), np.zeros(len(B))]
    au = [roc_auc_score(y, np.r_[A[:, i], B[:, i]]) for i in range(25)]
    top = sorted(range(25), key=lambda i: -abs(au[i] - .5))
    print("  %s (attack %d s, benign active %d s): " % (grp, len(A), len(B)) + ", ".join("%s %.2f" % (NAMES[i], au[i]) for i in top[:12]))
print("== (5) XGBoost total gain share (R060, mean of seeds)")
import xgboost as xgb
g = np.zeros(25)
for d in sorted(glob.glob(f"{O}/R060/fold*_seed*")):
    b = xgb.Booster(); b.load_model(d + "/model.json"); s = b.get_score(importance_type="total_gain")
    v = np.array([s.get("f%d" % i, 0.0) for i in range(25)]); g += v / v.sum()
g /= g.sum()
print("  " + ", ".join("%s %.1f%%" % (NAMES[i], 100 * g[i]) for i in np.argsort(-g)[:12]))
