#!/usr/bin/env python3
"""Round v5 (2026-11-10): choose the alarm rules of an exported model among fixed candidate lists, on the ENSEMBLE's
out-of-fold training scores only (mean of the seeds' calibrated logits, as export_clf.py).

Threshold of a candidate: the most sensitive one whose false-alarm rate stays within the budget on ALL out-of-fold episodes AND
on the out-of-fold episodes of the live runs in the training data (live 1, live v2, live v4: unseen Madrid users with the xApp
running, the deployment condition). Added 02:40-02:45 (before the export at 02:46), after the live v4 rule table (live v4 is training data of round v5) showed that
short rules keep the budget on the twin users but not on new users. No live v5 (test) data is read.
Rate limit: candidates thr, k23, k35 at 2 per benign UE-hour, fewest undetected seconds per attack episode (as before).
Block: candidates below at 0.5, fewest undetected ACTIVE seconds per attack episode (criterion fixed at 02:45).
Writes both rules into the model file and prints every candidate.
Usage: select_block_rule.py <model dir with fold*_seed*> <data pkl list> <clf_model.json in/out>"""
import glob, json, pickle, sys
import numpy as np
D, DATA, MJ = sys.argv[1:4]
SOFT = ["thr", "k23", "k35"]
BLOCK = ["a1020", "a1220", "a510", "a612", "a815", "a816", "a1015", "mean66", "mean610", "mean812", "mean1010", "mean2010"]
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", DATA, "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
EP, stat, first, outcome, active, fa, RULES = (ns[k] for k in ("EP", "stat", "first", "outcome", "active", "fa", "RULES"))
RULES.update({"thr": ("all", 1, 1), "k23": ("all", 2, 3), "k35": ("all", 3, 5)})
DELTA = ns["DELTA"]
S = [pickle.load(open(f, "rb"))["oof"] for f in sorted(glob.glob(D.rstrip("/") + "/fold*_seed*/scores.pkl"))]
assert len(S) >= 3, "expected 3 seeds"
oof = {k: np.mean([s[k]["honest"] for s in S], 0) for k in set.intersection(*[set(s) for s in S])}
EPS = [(EP[k], z, active(EP[k]["scen"]["honest"])) for k, z in sorted(oof.items()) if EP[k]["other_evasion"] != "L3"]
LIVE = np.array(["flood-live" in e["run"] for e, _, _ in EPS])
m_ = np.mean([e["run_lab"].mean() for e, _, _ in EPS]); PRIOR = float(np.log(m_ + 1e-9) - np.log(1 - m_ + 1e-9))
print("ensemble out-of-fold: %d episodes (%d of live runs), prior %.3f" % (len(EPS), LIVE.sum(), PRIOR))


def undet_all(e, o):
    lab = e["run_lab"]; on = int(np.argmax(lab)) if lab.any() else len(lab)
    return (o["delay"] - DELTA) if o["det"] else (len(lab) - on)


def select(rule, budget):
    St = [stat(z, ac, rule, PRIOR) for e, z, ac in EPS]
    cand = np.unique(np.concatenate([r[:max(1, int(np.argmax(e["run_lab"])) if e["run_lab"].any() else len(r))] for (e, _, _), r in zip(EPS, St)]))
    cand = cand[np.isfinite(cand)]
    cand = np.r_[cand.max() + 1e-6, np.quantile(cand, np.linspace(1, .5, 400))]
    best = None
    for th in cand:
        R = [outcome(e, first(r, th), ac) for (e, _, ac), r in zip(EPS, St)]
        f_all, f_live = fa(R), (fa([o for o, l in zip(R, LIVE) if l]) if LIVE.any() else 0.0)
        if f_all <= budget + 1e-9 and f_live <= budget + 1e-9:
            best = (th, R)
        else:
            break
    if best is None:
        th = cand[0]; best = (th, [outcome(e, first(r, th), ac) for (e, _, ac), r in zip(EPS, St)])
    th, R = best
    A = [(o, e) for o, (e, _, _) in zip(R, EPS) if o["attack"]]
    return dict(rule=rule, threshold=float(th), prior=PRIOR, det=100 * np.mean([o["det"] for o, _ in A]),
                l2=100 * np.mean([o["det"] for o, e in A if o["ev"] == "L2"]), fa=float(fa(R)),
                fa_live=float(fa([o for o, l in zip(R, LIVE) if l])), fa_twin=float(fa([o for o, l in zip(R, LIVE) if not l])),
                undet=float(np.mean([undet_all(e, o) for o, e in A])), undet_act=float(np.mean([o["undet_act"] for o, _ in A])))


out = {}
for tier, cands, budget, key in (("soft", SOFT, 2.0, "undet"), ("block", BLOCK, 0.5, "undet_act")):
    print("\n%s, budget %.1f per benign UE-hour on all and on live out-of-fold episodes; criterion: fewest %s" % (tier, budget, key))
    print("%-9s %9s %7s %7s %8s %8s %8s %8s %9s" % ("rule", "threshold", "det %", "L2 %", "FA all", "FA live", "FA twin", "undet s", "undet act"))
    res = []
    for rule in cands:
        r = select(rule, budget); res.append(r)
        print("%-9s %9.4f %7.1f %7.1f %8.2f %8.2f %8.2f %8.2f %9.2f" % (rule, r["threshold"], r["det"], r["l2"], r["fa"], r["fa_live"], r["fa_twin"], r["undet"], r["undet_act"]))
    best = min(res, key=lambda r: (r[key], -r["det"]))
    print("chosen %s: %s" % (tier, best["rule"]))
    out[tier] = (best, res)
m = json.load(open(MJ))
sb, sres = out["soft"]; bb, bres = out["block"]
m["soft"] = dict(budget=2.0, rule=sb["rule"], threshold=sb["threshold"], prior=sb["prior"], oof_detection=sb["det"] / 100, oof_fa=sb["fa"],
                 oof_fa_live=sb["fa_live"], oof_undetected_s=sb["undet"], note="round v5: budget on all and on live out-of-fold episodes")
m["soft_candidates"] = sres
m["block"] = dict(budget=0.5, rule=bb["rule"], threshold=bb["threshold"], prior=bb["prior"], oof_detection=bb["det"] / 100, oof_fa=bb["fa"],
                  oof_fa_live=bb["fa_live"], oof_undetected_active_s=bb["undet_act"],
                  note="round v5: fewest out-of-fold undetected active seconds; budget on all and on live out-of-fold episodes")
m["block_candidates"] = bres
json.dump(m, open(MJ, "w"))
