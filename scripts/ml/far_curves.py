#!/usr/bin/env python3
"""Advisor request (2026-11-13): detection rate and delay as a function of the false-alarm rate, on the out-of-fold scores,
for the cross-domain model and the core-only model, so the two are compared at the same false-alarm rate rather than at
their own operating points. Same episodes, rules and outcome definitions as compare_rules_510.py / abl_paired_by_tamper.py:
out-of-fold ensemble (mean of the seeds' calibrated logits) of the 177 training runs, L3 phases excluded; rate limit =
1 s above the threshold (thr), block = 5 of the last 10 active seconds above it (a510); onset = first attack second;
false alarms per benign UE-hour over all these episodes. The threshold is swept; at each matched false-alarm rate the most
sensitive threshold whose false-alarm rate stays at or below it (scanning from the strictest, stopping at the first one
over, as select() does). Attack episodes: all, genuinely honest KPM, KPM tampered live. The deployed thresholds are not
changed. Usage (repo root): far_curves.py [--fig research/clf/fig/far_curves_oof.png]"""
import argparse, json, re, sys
import numpy as np
from scipy.stats import binomtest, wilcoxon

ap = argparse.ArgumentParser(); ap.add_argument("--fig", default="research/clf/fig/far_curves_oof.png")
args = ap.parse_args(); sys.argv = sys.argv[:1]
exec(compile(open("scripts/ml/compare_rules_510.py").read().split("\ncase = ")[0], "cmp510", "exec"))

CASE = {}
for d in ("oran_flooding_live", "oran_flooding_live2", "oran_flooding_live4"):
    for r in json.load(open("research/datasets/%s/manifest/design.json" % d))["runs"]:
        for p in r["phases"]:
            CASE[(r["id"], p["name"])] = p.get("case", "honest" if "evasion" in p else "benign")


import functools


@functools.lru_cache(None)
def tampered(k):
    m = re.search(r"flood-live-(l[a-z]\d+)_", EP[k]["run"])
    return bool(m) and CASE.get((m.group(1), EP[k]["phase"]), "honest") != "honest"


MODELS = [("cross-domain", ["artifacts/clf/v5/R080_v5"], "artifacts/clf/v5/export_v5/clf_model.json"),
          ("core only", ["artifacts/clf/abl/R090_core"], "artifacts/clf/abl/R090_core.json")]
TIERS = [("rate limit", "soft", [0.5, 1.0, 1.5, 2.0]), ("block", "block", [0.1, 0.23, 0.27, 0.5])]
GROUPS = ("all", "honest KPM", "tampered KPM")
FMAX = {"soft": 3.0, "block": 1.0}


def first_alarms(r, ths):
    """first index with r > th for every th (via the running max), -1 if never"""
    cm = np.maximum.accumulate(np.where(np.isfinite(r), r, -np.inf))
    idx = np.searchsorted(cm, ths, side="right")
    return np.where(idx < len(r), idx, -1)


def metrics(R, ks):
    att = [k for k in ks if EP[k]["attack"]]
    out = {}
    for g in GROUPS:
        a = [k for k in att if g == "all" or (g == "tampered KPM") == tampered(k)]
        det = np.array([R[k]["det"] for k in a])
        d = np.array([R[k]["delay"] for k in a if R[k]["det"]])
        und = np.mean([(R[k]["delay"] - .2) if R[k]["det"] else 75 - int(np.argmax(EP[k]["run_lab"])) for k in a])
        out[g] = dict(n=len(a), dr=100 * det.mean(), med=np.median(d) if d.size else np.nan, p90=np.percentile(d, 90) if d.size else np.nan,
                      und=und, leak=np.mean([R[k]["leak_kB"] for k in a]), keys=a)
    return out


res = {}
for name, dirs, mj in MODELS:
    Z, n_s = ens(dirs, "oof"); m = json.load(open(mj))
    ks = sorted(k for k in Z if k in EP and EP[k]["other_evasion"] != "L3")
    for tn, key, _ in TIERS:
        t = m[key]; AC = {k: active(EP[k]["scen"]["honest"]) for k in ks}
        S = {k: stat(Z[k], AC[k], t["rule"], t["prior"]) for k in ks}
        # the false-alarm count only changes where the threshold crosses an episode's largest pre-onset statistic: those
        # values (alarm needs stat > threshold) are the exact breakpoints, and each is the most sensitive threshold of its level
        bp = []
        for k in ks:
            on = int(np.argmax(EP[k]["run_lab"])) if EP[k]["run_lab"].any() else len(S[k])
            v = S[k][:max(1, on)]; v = v[np.isfinite(v)]
            if v.size:
                bp.append(v.max())
        bp = np.array(bp)
        ths = np.unique(np.r_[bp, bp.max() + 1e-6, t["threshold"]])[::-1]   # strict -> sensitive
        FA = {k: first_alarms(S[k], ths) for k in ks}
        curve = []
        for j, th in enumerate(ths):
            R = {k: outcome(EP[k], int(FA[k][j]), AC[k]) for k in ks}
            f = fa([R[k] for k in ks])
            curve.append(dict(th=th, far=f, R=R, m=metrics(R, ks)))
            if f > FMAX[key] and th < t["threshold"]:
                break
        dep = next(c for c in curve if c["th"] == t["threshold"])
        res[(name, tn)] = dict(curve=curve, dep=dep, seeds=n_s, ks=ks)


def at_far(curve, f):
    best = None
    for c in curve:
        if c["far"] <= f * (1 + 1e-3) + 1e-9:   # same false-alarm count: benign hours differ by a few seconds between models
            best = c
        else:
            break
    return best


def boot(ca, cb, g, rng, B=2000):
    """cluster bootstrap by run of the DR difference and the difference of median delays (a - b)"""
    ka = ca["m"][g]["keys"]; runs = sorted({EP[k]["run"] for k in ka}); by = {r: [k for k in ka if EP[k]["run"] == r] for r in runs}
    dd, dm = [], []
    for _ in range(B):
        s = [k for r in rng.choice(runs, len(runs)) for k in by[r]]
        dd.append(100 * (np.mean([ca["R"][k]["det"] for k in s]) - np.mean([cb["R"][k]["det"] for k in s])))
        xa = [ca["R"][k]["delay"] for k in s if ca["R"][k]["det"]]; xb = [cb["R"][k]["delay"] for k in s if cb["R"][k]["det"]]
        dm.append(np.median(xa) - np.median(xb))
    return np.percentile(dd, [2.5, 97.5]), np.percentile(dm, [2.5, 97.5])


rng = np.random.default_rng(0)
L = []
P = lambda s="": L.append(s)
P("DR and delay vs false-alarm rate, out-of-fold (%d episodes, L3 phases excluded; seeds: cross-domain %d, core only %d)" % (
    len(res[("cross-domain", "block")]["ks"]), res[("cross-domain", "block")]["seeds"], res[("core only", "block")]["seeds"]))
P("Delay = median seconds from the first attack second to the decision (detected episodes); undet = mean seconds without a decision, a miss counted to the phase end.")
for tn, key, targets in TIERS:
    P("\n== %s ==" % tn)
    for name, *_ in MODELS:
        d = res[(name, tn)]["dep"]
        P("  deployed %-12s threshold %.4f  FAR %.3f /UE-h  | " % (name, d["th"], d["far"]) + "  ".join(
            "%s: DR %.1f%% (n %d) median %.1f s" % (g, d["m"][g]["dr"], d["m"][g]["n"], d["m"][g]["med"]) for g in GROUPS))
    for g in GROUPS:
        P("\n  %s attack episodes (n = %d)" % (g, res[("cross-domain", tn)]["dep"]["m"][g]["n"]))
        P("  %-9s | %-44s | %-44s | %s" % ("FAR <=", "cross-domain: FAR, DR, median/p90 delay, undet", "core only: FAR, DR, median/p90 delay, undet",
                                            "DR diff [95% CI], McNemar (only/only, p) | median delay diff [95% CI], Wilcoxon p"))
        extra = [("x@core", res[("core only", tn)]["dep"]["far"])]
        for lab, f in [(str(x), x) for x in targets] + extra:
            ca, cb = at_far(res[("cross-domain", tn)]["curve"], f), at_far(res[("core only", tn)]["curve"], f)
            if ca is None or cb is None:
                P("  %-9s | no threshold" % lab); continue
            ma, mb = ca["m"][g], cb["m"][g]
            ka = ma["keys"]
            oa = sum(ca["R"][k]["det"] and not cb["R"][k]["det"] for k in ka); ob = sum(cb["R"][k]["det"] and not ca["R"][k]["det"] for k in ka)
            pm = binomtest(oa, oa + ob).pvalue if oa + ob else 1.0
            both = [k for k in ka if ca["R"][k]["det"] and cb["R"][k]["det"]]
            dif = np.array([ca["R"][k]["delay"] - cb["R"][k]["delay"] for k in both])
            pw = wilcoxon(dif).pvalue if np.any(dif != 0) else 1.0
            ci_d, ci_m = boot(ca, cb, g, rng)
            P("  %-9s | %.3f %5.1f%% %5.1f/%5.1f s %5.1f s       | %.3f %5.1f%% %5.1f/%5.1f s %5.1f s       | %+5.1f [%+5.1f, %+5.1f], %d/%d p=%.3g | %+5.1f s [%+5.1f, %+5.1f], p=%.2g (n=%d)" % (
                "%.2f" % f if lab != "x@core" else "%.3f*" % f, ca["far"], ma["dr"], ma["med"], ma["p90"], ma["und"], cb["far"], mb["dr"], mb["med"], mb["p90"], mb["und"],
                ma["dr"] - mb["dr"], *ci_d, oa, ob, pm, ma["med"] - mb["med"], *ci_m, pw, len(both)))
P("\n* = the core-only model's deployed false-alarm rate (both models at the FAR the core-only model runs at)")
open("research/clf/FAR_curves_oof.txt", "w").write("\n".join(L) + "\n")
print("\n".join(L))

# figure: rows = tiers, columns = DR and median delay vs FAR; colour = model, line style = KPM group
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
COL = {"cross-domain": "#2a78d6", "core only": "#eb6834"}
LS = {"honest KPM": "-", "tampered KPM": "--"}
plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#b5b4ae", "axes.labelcolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e"})
fig, ax = plt.subplots(2, 2, figsize=(9, 6.4))
for i, (tn, key, targets) in enumerate(TIERS):
    xmax = 3.0 if key == "soft" else 1.0
    for name, *_ in MODELS:
        cv = res[(name, tn)]["curve"]
        far = np.array([c["far"] for c in cv])
        for g in ("honest KPM", "tampered KPM"):
            dr = np.array([c["m"][g]["dr"] for c in cv]); md = np.array([c["m"][g]["med"] for c in cv])
            sel = far <= xmax
            ax[i, 0].step(far[sel], dr[sel], where="post", color=COL[name], ls=LS[g], lw=2, label="%s, %s" % (name, g))
            ax[i, 1].step(far[sel], md[sel], where="post", color=COL[name], ls=LS[g], lw=2)
        d = res[(name, tn)]["dep"]
        for j, col in ((0, "dr"), (1, "med")):
            ax[i, j].plot(d["far"], d["m"]["honest KPM"][col], "o", ms=7, color=COL[name], mec="white", mew=1.5, zorder=5)
    for j, yl in enumerate(("detection rate (%)", "median delay (s)")):
        a = ax[i, j]
        a.set_xlim(0, xmax); a.set_xlabel("false alarms per benign UE-hour (out-of-fold)"); a.set_ylabel(yl)
        a.set_title("%s: %s" % (tn, "detection" if j == 0 else "delay"), loc="left", fontsize=10, color="#0b0b0b")
        a.grid(True, color="#e6e5e0", lw=.6); a.spines[["top", "right"]].set_visible(False)
    ax[i, 0].set_ylim(60 if key == "block" else 80, 100)
ax[0, 0].legend(frameon=False, fontsize=8, loc="lower right")
fig.text(.01, .005, "Dots: deployed operating points (honest KPM). Same episodes, rules and onset as section 7.2.",
         fontsize=7.5, color="#52514e")
fig.tight_layout(rect=(0, .02, 1, 1))
import os
os.makedirs(os.path.dirname(args.fig), exist_ok=True)
fig.savefig(args.fig, dpi=200)
print("figure:", args.fig)
