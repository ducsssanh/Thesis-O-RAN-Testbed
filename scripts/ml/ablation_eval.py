#!/usr/bin/env python3
"""Advisor steps 1-3 (2026-11-10) on the 30 live-test runs rebuilt offline: the deployed cross-domain model against (1) core only
(no KPM, no gate input), (2) without the gate inputs c_t_w/trust/mask (KPM still masked by the gate, as in the xApp) and
(2b) without any gate (KPM as reported, no gate input). Every model uses its own rate-limit and block rules, chosen exactly as the
deployed ones (select_block_rule.py: ensemble out-of-fold, fixed candidates, budgets 2 and 0.5 per benign UE-hour on all and on
live out-of-fold episodes). Sections:
 a out-of-fold result of the chosen rules;
 b live test as recorded, per level and KPM case; false alarms with an exact Poisson 95% CI;
 c step 3: every UE's KPM tampered offline over the whole phase, gate recomputed (frame = KPM inflated, hide = KPM scaled down):
   false alarms of the 216 benign UEs; detection of the 48 attacks of the KPM-honest runs, paired against the same attacks honest
   (exact McNemar).
Usage (repo root): ablation_eval.py"""
import glob, json, pickle, re, sys
import numpy as np
from scipy.stats import binomtest, chi2

LIVE = "artifacts/clf/live5/episodes31_live5_mall.pkl"
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", LIVE, "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active, fa, RULES = (ns[k] for k in ("EP", "stat", "first", "outcome", "active", "fa", "RULES"))
RULES.update({"thr": ("all", 1, 1), "k23": ("all", 2, 3), "k35": ("all", 3, 5)})
DESIGN = {r["id"]: {p["name"]: p.get("case", "benign") for p in r["phases"]} for r in json.load(open("research/datasets/oran_flooding_live5/manifest/design.json"))["runs"]}
case = lambda k: DESIGN[re.search(r"(l[a-z]\d+)a\d", k).group(1)][EP[k]["phase"]]
MASK = 27
MODELS = [("cross-domain (deployed)", "artifacts/clf/live5/V5_live5_mall", "artifacts/clf/v5/export_v5/clf_model.json"),
          ("core only", "artifacts/clf/abl/R090_core_live5", "artifacts/clf/abl/R090_core.json"),
          ("no trust/mask/c_t", "artifacts/clf/abl/R091_nogate_live5", "artifacts/clf/abl/R091_nogate.json"),
          ("no gate at all", "artifacts/clf/abl/R092_nogate_nomask_live5", "artifacts/clf/abl/R092_nogate_nomask.json")]
BEN = sorted(k for k in EP if not EP[k]["attack"])
ATT = sorted(k for k in EP if EP[k]["attack"] and case(k) == "honest")
TAMPER = ["honest", "frame1.25", "frame2", "frame5", "hide0.8", "hide0.33", "hide0.1", "mimic", "swap"]


def poisson(n, h):
    lo = chi2.ppf(.025, 2 * n) / 2 if n else 0.0
    return lo / h, chi2.ppf(.975, 2 * n + 2) / 2 / h


def load(d, mj):
    S = [pickle.load(open(f, "rb"))["test"] for f in sorted(glob.glob(d + "/fold*_seed*/scores.pkl"))]
    assert len(S) == 3, d
    m = json.load(open(mj))
    tiers = [("rate limit", m["soft"]), ("block", m["block"])]
    cand = {t: next(c for c in m[t + "_candidates"] if c["rule"] == m[t]["rule"]) for t in ("soft", "block")}
    return {k: {s: np.mean([x[k][s] for x in S], 0) for s in S[0][k]} for k in S[0]}, tiers, cand, m


def res(Z, k, s, t):
    e = EP[k]; ac = active(e["scen"][s])
    return outcome(e, first(stat(Z[k][s], ac, t["rule"], t["prior"]), t["threshold"]), ac)


M = {name: load(d, mj) for name, d, mj in MODELS}
print("Models: %s. Live-test episodes: %d (%d attack), benign UEs %d, attacks of KPM-honest runs %d." % (
    ", ".join("%s (%d inputs)" % (n, len(M[n][3]["features"])) for n in M), len(EP), sum(e["attack"] for e in EP.values()), len(BEN), len(ATT)))

print("\na. Out-of-fold (training data), the chosen rules")
print("%-24s %-8s %10s %8s %8s %8s %8s" % ("model", "tier", "rule", "det %", "L2 %", "FA/UE-h", "FA live"))
for n, (Z, tiers, cand, m) in M.items():
    for t, key in (("rate limit", "soft"), ("block", "block")):
        c = cand[key]
        print("%-24s %-8s %10s %8.1f %8.1f %8.2f %8.2f" % (n, t[:8], "%s>%.2f" % (c["rule"], c["threshold"]), c["det"], c["l2"], c["fa"], c["fa_live"]))

print("\nb. Live test as recorded (offline replay of the 30 runs); detection % (median delay s) per level and KPM case")
print("%-24s %-8s %-9s %5s %14s %14s %14s %14s" % ("model", "tier", "KPM case", "n", "L1", "L2", "L3", "all"))
for n, (Z, tiers, cand, m) in M.items():
    for tn, t in tiers:
        for c in ("honest", "mimic", "hide0.1", "all cases"):
            cells = []
            for lev in ("L1", "L2", "L3", "all"):
                ks = [k for k in EP if EP[k]["attack"] and (c == "all cases" or case(k) == c) and (lev == "all" or EP[k]["evasion"] == lev)]
                R = [res(Z, k, "honest", t) for k in ks]
                d = [r["delay"] for r in R if r["det"]]
                cells.append("%5.1f (%4.1f)" % (100 * np.mean([r["det"] for r in R]), np.median(d) if d else np.nan))
            print("%-24s %-8s %-9s %5d %s" % (n, tn[:8], c, len([k for k in EP if EP[k]["attack"] and (c == "all cases" or case(k) == c)]), " ".join("%14s" % x for x in cells)))
        R = [res(Z, k, "honest", t) for k in EP]
        ev = sum(r["early"] for r in R); h = sum(r["benign_s"] for r in R) / 3600
        print("%-24s %-8s false alarms: %d in %.2f benign UE-h = %.2f /UE-h, 95%% CI [%.2f, %.2f]" % ((n, tn[:8], ev, h, ev / h) + poisson(ev, h)))

print("\nc1. Step 3, benign UEs (%d, %.2f UE-h): KPM tampered offline over the whole phase; false alarms /UE-h (events)" % (len(BEN), len(BEN) * 75 / 3600))
print("%-24s %-8s %s" % ("model", "tier", " ".join("%11s" % s for s in TAMPER)))
for n, (Z, tiers, cand, m) in M.items():
    for tn, t in tiers:
        cells = []
        for s in TAMPER:
            ks = [k for k in BEN if s in Z[k]]
            R = [res(Z, k, s, t) for k in ks]
            cells.append("%5.2f (%2d)" % (fa(R), sum(r["early"] for r in R)) if ks else "")
        print("%-24s %-8s %s" % (n, tn[:8], " ".join("%11s" % x for x in cells)))
print("%-24s %-8s %s" % ("share of seconds masked", "", " ".join("%10.1f%%" % (100 * np.mean(np.concatenate([EP[k]["scen"][s][:, MASK] for k in BEN if s in EP[k]["scen"]]))) for s in TAMPER)))

print("\nc2. Step 3, the %d attacks of the KPM-honest runs, attacker KPM tampered offline: detected / %d (L2 detected / %d); "
      "McNemar p against the same attacks honest" % (len(ATT), len(ATT), sum(EP[k]["evasion"] == "L2" for k in ATT)))
print("%-24s %-8s %s" % ("model", "tier", " ".join("%15s" % s for s in TAMPER)))
for n, (Z, tiers, cand, m) in M.items():
    for tn, t in tiers:
        h = np.array([res(Z, k, "honest", t)["det"] for k in ATT])
        cells = []
        for s in TAMPER:
            x = np.array([res(Z, k, s, t)["det"] for k in ATT])
            l2 = np.array([EP[k]["evasion"] == "L2" for k in ATT])
            b, c = int((h & ~x).sum()), int((~h & x).sum())
            p = binomtest(min(b, c), b + c, .5).pvalue if b + c else 1.0
            cells.append("%2d (%2d) p%.2f" % (x.sum(), x[l2].sum(), p))
        print("%-24s %-8s %s" % (n, tn[:8], " ".join("%15s" % x for x in cells)))
print("%-24s %-8s %s" % ("share of attack s masked", "", " ".join("%14.1f%%" % (100 * np.mean(np.concatenate([EP[k]["scen"][s][EP[k]["run_lab"] == 1, MASK] for k in ATT]))) for s in TAMPER)))
