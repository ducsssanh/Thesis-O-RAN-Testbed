#!/usr/bin/env python3
"""Why the cross-domain model beats the core-only one (2026-11-10), deployed rules of each, ensemble of 3 seeds:
A speed on the same attacks: delay on attacks both detect (median, p75, p90), undetected (active) seconds, attack bytes reaching the
  core before the decision; out-of-fold (177 training runs, outside L3 phases) and the 144 live-test attacks.
B the attacks only one model blocks (out-of-fold): by level, band, vector, anchor; what the KPM inputs add there (SHAP of the deployed
  model, KPM group = PRB UL/DL, PRB per kbit/s, window PRB mean/max, KPM age) and PRB per kbit/s of attack vs benign seconds.
C core telemetry availability: seconds whose profile arrives after t + 0.2 s (the model then sees no core input of that second).
Usage (repo root): abl_why.py"""
import glob, json, pickle, sys
import numpy as np, xgboost as xgb
sys.path.insert(0, "scripts/ml")
from baselines_feat import x31, X31_NAMES  # noqa: E402
DATA = "artifacts/clf/mimic/episodes31_m.pkl,artifacts/clf/v5/extra_l2_live124_m.pkl,artifacts/clf/live5/episodes31_live5_mall.pkl"
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", DATA, "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active = (ns[k] for k in ("EP", "stat", "first", "outcome", "active"))
ns["RULES"].update({"thr": ("all", 1, 1), "k23": ("all", 2, 3), "k35": ("all", 3, 5)})
M = {"cross-domain": ("artifacts/clf/v5/R080_v5", "artifacts/clf/live5/V5_live5_mall", "artifacts/clf/v5/export_v5/clf_model.json"),
     "core only": ("artifacts/clf/abl/R090_core", "artifacts/clf/abl/R090_core_live5", "artifacts/clf/abl/R090_core.json")}


def ens(d, part):
    S = [pickle.load(open(f, "rb"))[part] for f in sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))]
    keys = set.intersection(*[set(s) for s in S])
    return {k: np.mean([s[k]["honest"] for s in S], 0) for k in keys}


O = {}
for n, (md, ld, mj) in M.items():
    m = json.load(open(mj))
    for part, Z in (("out-of-fold", ens(md, "oof")), ("live test", ens(ld, "test"))):
        ks = sorted(k for k in Z if EP[k]["attack"] and (part == "live test" or EP[k]["other_evasion"] != "L3"))
        for tn, t in (("rate limit", m["soft"]), ("block", m["block"])):
            O[(n, part, tn)] = {k: outcome(EP[k], first(stat(Z[k], active(EP[k]["scen"]["honest"]), t["rule"], t["prior"]), t["threshold"]),
                                           active(EP[k]["scen"]["honest"])) for k in ks}
print("A. Speed on the same attacks (cross-domain vs core only)")
print("%-12s %-10s %4s | %-30s | %-22s | %-26s" % ("set", "tier", "n", "delay s, both detect: med/p75/p90", "undetected s (active)", "attack kB before decision"))
for part in ("out-of-fold", "live test"):
    for tn in ("rate limit", "block"):
        A, B = O[("cross-domain", part, tn)], O[("core only", part, tn)]
        ks = sorted(A); both = [k for k in ks if A[k]["det"] and B[k]["det"]]
        da, db = np.array([A[k]["delay"] for k in both]), np.array([B[k]["delay"] for k in both])
        und = lambda R, k: (R[k]["delay"] - .2) if R[k]["det"] else 75 - int(np.argmax(EP[k]["run_lab"]))
        la, lb = sum(A[k]["leak_kB"] for k in ks), sum(B[k]["leak_kB"] for k in ks); tot = sum(A[k]["tot_kB"] for k in ks)
        faster, slower = int((da < db).sum()), int((da > db).sum())
        print("%-12s %-10s %4d | %4.1f/%4.1f/%4.1f vs %4.1f/%4.1f/%4.1f (%d faster, %d slower) | %4.1f (%4.1f) vs %4.1f (%4.1f) | %6.0f vs %6.0f (%4.1f%% vs %4.1f%% of %0.f)" % (
            part, tn, len(ks), *np.percentile(da, [50, 75, 90]), *np.percentile(db, [50, 75, 90]), faster, slower,
            np.mean([und(A, k) for k in ks]), np.mean([A[k]["undet_act"] for k in ks]), np.mean([und(B, k) for k in ks]), np.mean([B[k]["undet_act"] for k in ks]),
            la / len(ks), lb / len(ks), 100 * la / tot, 100 * lb / tot, tot / len(ks)))

print("\nB. Out-of-fold, block: attacks only one model blocks")
A, B = O[("cross-domain", "out-of-fold", "block")], O[("core only", "out-of-fold", "block")]
only_a = [k for k in A if A[k]["det"] and not B[k]["det"]]; only_b = [k for k in A if B[k]["det"] and not A[k]["det"]]
both = [k for k in A if A[k]["det"] and B[k]["det"]]
for name, f in (("level", lambda e: e["evasion"]), ("band", lambda e: e["band"]), ("vector", lambda e: e["vector"] or "-"), ("anchor kbit/s", lambda e: "%.0f" % (e["anchor"] / 1e3))):
    ca = {}; cb = {}; call = {}
    for k in only_a: ca[f(EP[k])] = ca.get(f(EP[k]), 0) + 1
    for k in only_b: cb[f(EP[k])] = cb.get(f(EP[k]), 0) + 1
    for k in A: call[f(EP[k])] = call.get(f(EP[k]), 0) + 1
    print("  %-14s only cross-domain %s | only core %s | all attacks %s" % (name, dict(sorted(ca.items())), dict(sorted(cb.items())), dict(sorted(call.items()))))
F = X31_NAMES; KPM = [F.index(c) for c in ("prb_ul", "prb_dl", "prb_ul_per_kbit", "w_prb_mean", "w_prb_max", "kpm_age")]
GATE = [F.index(c) for c in ("c_t_w", "trust_ue", "mask_ue")]
bst = []
for d in sorted(glob.glob(M["cross-domain"][0] + "/fold9_seed*")):
    b = xgb.Booster(); b.load_model(d + "/model.json"); b.set_param({"nthread": 2}); bst.append((b, json.load(open(d + "/config.json"))["temperature"]))


def shap(keys):
    X = np.vstack([x31(EP[k]["scen"]["honest"])[EP[k]["run_lab"] == 1] for k in keys])
    C = np.mean([b.predict(xgb.DMatrix(X), pred_contribs=True) / T for b, T in bst], 0)
    per = C[:, :-1][:, KPM].mean(0)
    return len(X), C[:, KPM].sum(1).mean(), C[:, GATE].sum(1).mean(), {F[i]: round(float(v), 2) for i, v in zip(KPM, per)}, X
for name, ks in (("only cross-domain blocks", only_a), ("both block", both), ("only core blocks", only_b)):
    n, kp, gt, per, X = shap(ks)
    print("  SHAP on attack seconds, %-24s (%d ep, %5d s): KPM group %+.2f, gate %+.2f; per KPM input %s; PRB/kbit mean %.2f" % (name, len(ks), n, kp, gt, per, X[:, F.index("prb_ul_per_kbit")].mean()))
ben = [k for k in O[("cross-domain", "out-of-fold", "block")] if False]
BEN = [k for k in EP if not EP[k]["attack"] and "flood-live-lz" not in k and "flood-live-lb" not in k][:600]
Xb = np.vstack([x31(EP[k]["scen"]["honest"]) for k in BEN])
act_b = np.expm1(Xb[:, 0]) >= 8
print("  PRB per kbit/s (log1p of PRB%% x100 / (1 + kbit/s)), benign active seconds: mean %.2f, median %.2f (n %d)" % (Xb[act_b, F.index("prb_ul_per_kbit")].mean(), np.median(Xb[act_b, F.index("prb_ul_per_kbit")]), act_b.sum()))

print("\nC. Core telemetry availability: seconds whose profile is late (> t + 0.2 s) or missing, so the model has no core input that second")
for name, sel in (("training (twin + live 1/2/4)", lambda k: "flood-live-lz" not in k), ("live test", lambda k: "flood-live-lz" in k)):
    ks = [k for k in EP if sel(k)]
    late = np.concatenate([EP[k]["scen"]["honest"][:, 29] > .2 for k in ks])
    att = np.concatenate([(EP[k]["scen"]["honest"][:, 29] > .2)[EP[k]["run_lab"] == 1] for k in ks if EP[k]["attack"]])
    print("  %-30s all seconds %.2f%% late, attack seconds %.2f%% late" % (name, 100 * late.mean(), 100 * att.mean()))
