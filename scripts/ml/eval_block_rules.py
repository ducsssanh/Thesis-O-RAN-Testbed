#!/usr/bin/env python3
"""Plan step 3d: block rules that count ACTIVE seconds (core UL >= 8 kbit/s) instead of all seconds, against the current
20-of-30. Same selection as report_clf.py: per rule, the most sensitive threshold whose false-alarm rate on the out-of-fold
training scores (honest, outside L3 phases) stays within the budget (0.5 per benign UE-hour); among rules the one with the
fewest out-of-fold undetected seconds is the "best". Test sets are read after.
Rules: k2030 (current, all seconds); a2030, a1220, a1020 (k of the last n active seconds); acusum (CUSUM of logit - prior,
updated in active seconds only). Metrics per test set, scenario and level: detection, median delay, false alarms per UE-hour,
and (step 2) undetected ACTIVE seconds per episode and attack bytes reaching the core before the block (kB, % of the episode's).
Usage: eval_block_rules.py --data a.pkl,b.pkl,... --budget 0.5 name=<scores dir>:<substring of test run ids> ..."""
import argparse, glob, os, pickle
import numpy as np
ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--budget", type=float, default=0.5)
ap.add_argument("--scen", default="honest,mimic"); ap.add_argument("sets", nargs="+")
a = ap.parse_args()
EP = {"|".join((e["run"], e["phase"], e["supi"])): e for f in a.data.split(",") for e in pickle.load(open(f, "rb"))["episodes"]}
DELTA = .2; ACT_KBPS = 8.0
RULES = {"k2030": ("all", 20, 30), "a2030": ("act", 20, 30), "a1220": ("act", 12, 20), "a1020": ("act", 10, 20), "acusum": ("cusum", 0, 0),
         # evidence averaged over active seconds (2026-11-09): mean / median of the last n active-second logits, at least m of them
         "mean2010": ("mean", 10, 20), "mean3010": ("mean", 10, 30), "med2010": ("med", 10, 20), "mean1010": ("mean", 10, 10),
         # shorter evidence (2026-11-10, live v4: 6 of 11 missed L2 episodes had only 10-14 active attack seconds)
         "a510": ("act", 5, 10), "a612": ("act", 6, 12), "a815": ("act", 8, 15), "a816": ("act", 8, 16), "a1015": ("act", 10, 15),
         "mean66": ("mean", 6, 6), "mean610": ("mean", 6, 10), "mean812": ("mean", 8, 12)}


def active(raw):
    return np.expm1(raw[:, 6]) >= ACT_KBPS


def stat(z, act, rule, prior):
    kind, k, n = RULES[rule]
    out = np.full(len(z), -np.inf)
    if kind == "all":
        for t in range(len(z)):
            w = np.sort(z[max(0, t - n + 1):t + 1])[::-1]
            if len(w) >= k:
                out[t] = w[k - 1]
        return out
    if kind == "act":
        hist = []
        for t in range(len(z)):
            if act[t]:
                hist.append(z[t]); hist = hist[-n:]
            if len(hist) >= k:
                out[t] = np.sort(hist)[::-1][k - 1]
        return out
    if kind in ("mean", "med"):
        hist = []
        for t in range(len(z)):
            if act[t]:
                hist.append(z[t]); hist = hist[-n:]
            if len(hist) >= k:
                out[t] = np.mean(hist) if kind == "mean" else np.median(hist)
        return out
    s = 0.0
    for t in range(len(z)):
        if act[t]:
            s = max(0.0, s + z[t] - prior)
        out[t] = s
    return out


def first(r, th):
    i = np.flatnonzero(r > th)
    return int(i[0]) if i.size else -1


def outcome(e, al, act):
    lab = e["run_lab"]; on = int(np.argmax(lab)) if lab.any() else len(lab)
    stop = al if al >= 0 else len(lab); early = 0 <= al < on
    o = dict(run=e["run"], attack=e["attack"], ev=e["evasion"], det=al >= on and e["attack"], early=early, benign_s=min(stop, on) + int(early),
             delay=(al - on + DELTA) if (al >= on and e["attack"]) else np.nan)
    if e["attack"]:
        end = al if al >= on else len(lab)
        o["undet_act"] = int(act[on:end].sum()); o["act_total"] = int(act[on:].sum())
        b = e["bytes"]; o["leak_kB"] = float(b[on:end].sum()) / 1e3; o["tot_kB"] = float(b[on:].sum()) / 1e3
    return o


def fa(R):
    h = sum(r["benign_s"] for r in R) / 3600
    return sum(r["early"] for r in R) / h if h else np.nan


def pick(oof, rule, budget):
    eps = [(EP[k], v["honest"]) for k, v in oof.items() if EP[k]["other_evasion"] != "L3"]
    m = np.mean([e["run_lab"].mean() for e, _ in eps]); prior = np.log(m + 1e-9) - np.log(1 - m + 1e-9)
    S = [(e, stat(z, active(e["scen"]["honest"]), rule, prior), active(e["scen"]["honest"])) for e, z in eps]
    cand = np.unique(np.concatenate([r[:max(1, int(np.argmax(e["run_lab"])) if e["run_lab"].any() else len(r))] for e, r, _ in S]))
    cand = cand[np.isfinite(cand)]
    cand = np.r_[cand.max() + 1e-6 if cand.size else 0.0, np.quantile(cand, np.linspace(1, .5, 400)) if cand.size else []]
    best = None
    for th in cand:
        R = [outcome(e, first(r, th), ac) for e, r, ac in S]
        if fa(R) <= budget + 1e-9:
            best = (th, R)
        else:
            break
    if best is None:
        th = cand[0]; best = (th, [outcome(e, first(r, th), ac) for e, r, ac in S])
    und = np.mean([((r["delay"] - DELTA) if r["det"] else 75 - 0) for r in best[1] if r["attack"]])
    return best[0], prior, und


print("budget %.2f per benign UE-hour; rule chosen per seed on out-of-fold scores" % a.budget)
print("%-10s %-7s %-7s %-6s %4s  %6s %7s %7s  %10s  %12s" % ("set", "rule", "scen", "level", "n", "det %", "delay s", "FA/UE-h", "undet act s", "leak kB (%)"))
for spec in a.sets:
    name, rest = spec.split("=", 1); d, sub = rest.split(":")
    files = sorted(glob.glob(d.rstrip("/") + "/fold*_seed*/scores.pkl"))
    for rule in (os.environ.get("RULES", ",".join(RULES))).split(","):
        R = {s: [] for s in a.scen.split(",")}
        for f in files:
            S = pickle.load(open(f, "rb"))
            th, prior, _ = pick(S["oof"], rule, a.budget)
            for k, sc in S["test"].items():
                if sub not in k:
                    continue
                e = EP[k]
                for s in R:
                    if s in sc:
                        ac = active(e["scen"][s])
                        R[s].append(outcome(e, first(stat(sc[s], ac, rule, prior), th), ac))
        for s, O in R.items():
            for lev in ("all", "L1", "L2", "L3"):
                A = [o for o in O if o["attack"] and (lev == "all" or o["ev"] == lev)]
                if not A:
                    continue
                lk, tk = sum(o["leak_kB"] for o in A), sum(o["tot_kB"] for o in A)
                print("%-10s %-7s %-7s %-6s %4d  %6.1f %7.1f %7s  %10.1f  %7.0f (%2.0f%%)" % (
                    name, rule, s, lev, len(A), 100 * np.mean([o["det"] for o in A]),
                    np.nanmedian([o["delay"] for o in A]) if any(o["det"] for o in A) else np.nan,
                    ("%.2f" % fa(O)) if lev == "all" else "", np.mean([o["undet_act"] for o in A]), lk / len(A), 100 * lk / tk if tk else 0))
