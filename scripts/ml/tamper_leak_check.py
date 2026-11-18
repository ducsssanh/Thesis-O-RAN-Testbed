#!/usr/bin/env python3
"""Advisor question (2026-11-10): in the live test only the attacking UE's KPM was tampered, and the gate outputs (c_t_w, trust, mask)
are model inputs. Did the model learn "KPM masked -> attacker"? Checks with the deployed model and rules (export_v5/clf_model.json:
rate limit = thr, block = a510, ensemble of the 3 seeds):
A training data: masked share of benign and of attack seconds per scenario (training tampers every UE, attacker or not);
B live benign UEs tampered offline (mimic, hide, frame, swap; per-UE gate recomputed over the run): false alarms per UE-hour
  against the same UEs and seconds honest. If masking were taken as attack evidence, these false alarms would jump;
C the attack episodes of the KPM-honest live runs, tampered offline: detection against the same episodes honest (paired);
D SHAP: mean contribution (calibrated logit) of the gate inputs, the KPM inputs and the core inputs on benign and attack seconds,
  honest and tampered.
Usage (repo root): tamper_leak_check.py  (needs artifacts/clf/live5/episodes31_live5_mall.pkl and V5_live5_mall/)"""
import glob, json, pickle, re, sys
import numpy as np
import xgboost as xgb
sys.path.insert(0, "scripts/ml")
from baselines_feat import x31  # noqa: E402

LIVE = "artifacts/clf/live5/episodes31_live5_mall.pkl"; SC = "artifacts/clf/live5/V5_live5_mall"; MD = "artifacts/clf/v5/R080_v5"
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", LIVE, "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active, fa, RULES = (ns[k] for k in ("EP", "stat", "first", "outcome", "active", "fa", "RULES"))
RULES["thr"] = ("all", 1, 1)
M = json.load(open("artifacts/clf/v5/export_v5/clf_model.json"))
TIERS = [("rate limit", M["soft"]["rule"], M["soft"]["threshold"], M["soft"]["prior"]), ("block", M["block"]["rule"], M["block"]["threshold"], M["block"]["prior"])]
DESIGN = {r["id"]: {p["name"]: p.get("case", "benign") for p in r["phases"]} for r in json.load(open("research/datasets/oran_flooding_live5/manifest/design.json"))["runs"]}
MASK = 27  # raw column "masked" (episodes.py NAMES)
S = [pickle.load(open(f, "rb"))["test"] for f in sorted(glob.glob(SC + "/fold*_seed*/scores.pkl"))]
assert len(S) == 3
Z = {k: {s: np.mean([x[k][s] for x in S], 0) for s in S[0][k]} for k in S[0]}
case = lambda k: DESIGN[re.search(r"(l[a-z]\d+)a\d", k).group(1)][EP[k]["phase"]]


def run(k, s, tier):
    _, rule, th, prior = tier
    e = EP[k]; ac = active(e["scen"][s])
    return outcome(e, first(stat(Z[k][s], ac, rule, prior), th), ac)


# ---- A: training data
print("A. Training data (177 train runs of the deployed model): share of seconds with KPM masked, per scenario")
train_runs = set(json.load(open(MD + "/fold9_seed0/config.json"))["train_runs"])
TR = [e for f in ("artifacts/clf/mimic/episodes31_m.pkl", "artifacts/clf/v5/extra_l2_live124_m.pkl") for e in pickle.load(open(f, "rb"))["episodes"] if e["run"] in train_runs]
print("   %d episodes (%d attack)" % (len(TR), sum(e["attack"] for e in TR)))
print("   %-10s %18s %18s" % ("scenario", "benign UE seconds", "attack seconds"))
tot = {0: [0, 0], 1: [0, 0]}
for s in ("honest", "mimic", "hide0.1", "hide0.33", "hide0.8", "frame1.25", "frame2", "frame5", "swap"):
    b = np.concatenate([e["scen"][s][:, MASK] for e in TR if not e["attack"] and s in e["scen"]])
    a = np.concatenate([e["scen"][s][e["run_lab"] == 1, MASK] for e in TR if e["attack"] and s in e["scen"]])
    if s != "honest":
        tot[0][0] += b.sum(); tot[0][1] += len(b); tot[1][0] += a.sum(); tot[1][1] += len(a)
    print("   %-10s %17.1f%% %17.1f%%" % (s, 100 * b.mean(), 100 * a.mean()))
print("   all tampered scenarios: benign %.1f%% of %d s, attack %.1f%% of %d s; masked seconds that are benign: %.1f%%" % (
    100 * tot[0][0] / tot[0][1], tot[0][1], 100 * tot[1][0] / tot[1][1], tot[1][1], 100 * tot[0][0] / (tot[0][0] + tot[1][0])))
del TR

# ---- B: live benign UEs tampered offline
BEN = [k for k in Z if not EP[k]["attack"]]
print("\nB. Live test, the %d benign UE episodes (%.2f UE-hours), KPM tampered offline over the whole phase; deployed model and rules" % (len(BEN), len(BEN) * 75 / 3600))
print("   %-10s %4s %9s %8s %12s %12s %10s" % ("scenario", "n", "masked %", "mean z", "FA rate /h", "FA block /h", "z>thr s %"))
for s in ("honest", "mimic", "hide0.1", "hide0.33", "frame2", "frame5", "swap"):
    ks = [k for k in BEN if s in Z[k]]
    m = np.mean(np.concatenate([EP[k]["scen"][s][:, MASK] for k in ks]))
    z = np.concatenate([Z[k][s] for k in ks])
    f = [fa([run(k, s, t) for k in ks]) for t in TIERS]
    print("   %-10s %4d %8.1f%% %8.2f %12.2f %12.2f %9.2f%%" % (s, len(ks), 100 * m, z.mean(), f[0], f[1], 100 * np.mean(z > TIERS[0][2])))
# masked seconds only, paired with the same seconds honest
for s in ("mimic", "hide0.1"):
    zm, zh = [], []
    for k in BEN:
        mk = EP[k]["scen"][s][:, MASK] > 0
        zm.append(Z[k][s][mk]); zh.append(Z[k]["honest"][mk])
    zm, zh = np.concatenate(zm), np.concatenate(zh)
    print("   benign seconds masked under %-8s n=%5d: mean z %.2f tampered vs %.2f same seconds honest; above rate threshold %.2f%% vs %.2f%%" % (
        s, len(zm), zm.mean(), zh.mean(), 100 * np.mean(zm > TIERS[0][2]), 100 * np.mean(zh > TIERS[0][2])))

# ---- C: same attacks, honest vs tampered offline
ATT = [k for k in Z if EP[k]["attack"] and case(k) == "honest"]
print("\nC. Live test, the %d attack episodes of the KPM-honest runs, tampered offline (paired: same attacks)" % len(ATT))
print("   %-10s %-6s %4s %9s %13s %13s %10s" % ("scenario", "level", "n", "masked %", "rate det %", "block det %", "mean z att"))
for s in ("honest", "mimic", "hide0.1", "hide0.33"):
    for lev in ("all", "L1", "L2", "L3"):
        ks = [k for k in ATT if lev == "all" or EP[k]["evasion"] == lev]
        m = np.mean(np.concatenate([EP[k]["scen"][s][EP[k]["run_lab"] == 1, MASK] for k in ks]))
        d = [100 * np.mean([run(k, s, t)["det"] for k in ks]) for t in TIERS]
        za = np.concatenate([Z[k][s][EP[k]["run_lab"] == 1] for k in ks])
        print("   %-10s %-6s %4d %8.1f%% %13.1f %13.1f %10.2f" % (s, lev, len(ks), 100 * m, d[0], d[1], za.mean()))

# ---- D: SHAP of the gate inputs
F = M["features"]
G = {"gate (c_t_w, trust, mask)": [F.index(c) for c in ("c_t_w", "trust_ue", "mask_ue")],
     "KPM (PRB, PRB/kbit, w_prb, kpm_age)": [F.index(c) for c in ("prb_ul", "prb_dl", "prb_ul_per_kbit", "w_prb_mean", "w_prb_max", "kpm_age")]}
G["core and the rest"] = [i for i in range(len(F)) if not any(i in v for v in G.values())]
B = []
for d in sorted(glob.glob(MD + "/fold9_seed*")):
    b = xgb.Booster(); b.load_model(d + "/model.json"); B.append((b, json.load(open(d + "/config.json"))["temperature"]))


def contrib(sel):
    """sel: list of (key, scenario, row mask). Mean SHAP per group over the selected seconds, ensemble of the 3 seeds."""
    X = np.vstack([x31(EP[k]["scen"][s])[r] for k, s, r in sel])
    C = np.mean([b.predict(xgb.DMatrix(X), pred_contribs=True) / T for b, T in B], 0)
    return len(X), C[:, -1].mean(), {g: C[:, ix].sum(1).mean() for g, ix in G.items()}, C.sum(1).mean()


print("\nD. SHAP, mean contribution to the calibrated logit z (ensemble); 'masked' rows = seconds whose KPM the gate masked")
sets = [("benign, honest", [(k, "honest", np.ones(75, bool)) for k in BEN]),
        ("benign, mimic, masked s", [(k, "mimic", EP[k]["scen"]["mimic"][:, MASK] > 0) for k in BEN]),
        ("benign, hide0.1, masked s", [(k, "hide0.1", EP[k]["scen"]["hide0.1"][:, MASK] > 0) for k in BEN]),
        ("attack s, honest", [(k, "honest", EP[k]["run_lab"] == 1) for k in ATT]),
        ("attack s, mimic, masked s", [(k, "mimic", (EP[k]["run_lab"] == 1) & (EP[k]["scen"]["mimic"][:, MASK] > 0)) for k in ATT]),
        ("attack s, hide0.1, masked s", [(k, "hide0.1", (EP[k]["run_lab"] == 1) & (EP[k]["scen"]["hide0.1"][:, MASK] > 0)) for k in ATT])]
print("   %-28s %6s %7s %s %7s" % ("seconds", "n", "bias", "  ".join("%14s" % g.split(" (")[0] for g in G), "mean z"))
for name, sel in sets:
    n, bias, g, z = contrib([x for x in sel if x[2].any()])
    print("   %-28s %6d %7.2f %s %7.2f" % (name, n, bias, "  ".join("%14.2f" % g[x] for x in G), z))

# ---- E: the comparison protocol of the report (section 7.2: per-seed thresholds as report_clf.py, block = 20 of 30), cross-domain
# model vs Isolation Forest: false alarms of the live benign UEs when their KPM is tampered offline, and detection per live case
src = open("scripts/ml/report_clf.py").read().split("dump = {}")[0]
argv = sys.argv; sys.argv = ["report_clf.py", "x", "x", "--data", "artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl,artifacts/clf/mimic/episodes31_m.pkl,artifacts/clf/v5/extra_l2_live124_m.pkl," + LIVE, "--long"]
rc = {}; exec(compile(src, "report_clf", "exec"), rc); sys.argv = argv
print("\nE. Protocol of the report's comparison table (per-seed thresholds, rate point at 2 /UE-h, block 20 of 30 at 0.5 /UE-h)")
print("   %-14s %-6s %-10s %18s %18s" % ("detector", "point", "scenario", "benign FA /UE-h", "attack det % (case)"))
for name, d in (("cross-domain", SC), ("IsolationForest", "artifacts/clf/live5/base/B_iforest")):
    for pt, rules, budget in (("rate", ["thr", "k23", "k35", "cusum"], 2.0), ("block", ["k2030"], 0.5)):
        FA, DET = {}, {}
        for f in sorted(glob.glob(d + "/fold*_seed*/scores.pkl")):
            Sx = pickle.load(open(f, "rb"))
            opts = [(rc["pick"](Sx["oof"], r, budget), r) for r in rules]
            (th, prior, *_), rule = min(opts, key=lambda o: (np.nan_to_num(o[0][2], nan=1e9), -o[0][3]))
            for k, sc in Sx["test"].items():
                e = rc["EP"][k]
                for s, z in sc.items():
                    o = rc["outcome"](e, rc["first_cross"](rc["stat_series"](z, rule, prior), th))
                    if not e["attack"]:
                        FA.setdefault(s, []).append(o)
                    elif s == "honest":
                        DET.setdefault(case(k), []).append(o)
        for s in ("honest", "mimic", "hide0.1", "hide0.33", "frame2", "swap"):
            if s in FA:
                c = {"honest": "honest", "mimic": "mimic", "hide0.1": "hide0.1"}.get(s)
                det = ("%.1f" % (100 * np.mean([o["det"] for o in DET[c]]))) if c in DET else ""
                print("   %-14s %-6s %-10s %18.2f %18s" % (name, pt, s, rc["fa_rate"](FA[s]), det))
