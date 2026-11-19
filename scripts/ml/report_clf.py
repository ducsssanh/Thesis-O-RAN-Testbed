#!/usr/bin/env python3
"""Metrics of the classifier plan at fixed false-alarm budgets.

For every fold and seed of one configuration: alarm rules (threshold, 2 of 3, 3 of 5, CUSUM) on the calibrated logits;
for each budget, the threshold of each rule is the most sensitive one whose false-alarm rate on the out-of-fold
training scores (honest scenario, no L3 phase) stays at or under the budget; the rule with the lowest out-of-fold
median delay is kept. Only then are the test scores read. Metrics pool the test folds; 95 % CI by bootstrap over runs.
Usage: report_clf.py <name> <dir with fold*_seed*/scores.pkl> [--rule thr|k23|k35|cusum|best] [--json out.json]"""
import argparse, glob, json, pickle
import numpy as np
ap = argparse.ArgumentParser(); ap.add_argument("name"); ap.add_argument("dir"); ap.add_argument("--rule", default="best")
ap.add_argument("--json", default=""); ap.add_argument("--data", default="artifacts/clf/episodes31.pkl"); ap.add_argument("--boot", type=int, default=300); ap.add_argument("--test", action="store_true"); ap.add_argument("--l3app", default=""); ap.add_argument("--long", action="store_true")
a = ap.parse_args()
EP = {"|".join((e["run"], e["phase"], e["supi"])): e for f in a.data.split(",") for e in pickle.load(open(f, "rb"))["episodes"]}
PHASE_VEC = {(e["run"], e["phase"]): e["vector"] for e in EP.values() if e["attack"]}
BUDGETS = [0.0, 0.5, 1.0, 2.0, 5.0]; DELTA = .2; PI = {"P1": .50, "P2": .40, "P3": .09, "P4": .01}
LONG = {"k610": (6, 10), "k1220": (12, 20), "k2030": (20, 30)}
ap2 = a.rule
RULES = (["thr", "k23", "k35", "cusum"] + (list(LONG) if a.long else [])) if a.rule == "best" else [a.rule]
rng = np.random.default_rng(0)


def stat_series(z, rule, prior):
    """Statistic whose first crossing of a threshold is the alarm."""
    if rule == "thr":
        return z
    if rule in ("k23", "k35") or rule in LONG:
        k, n = LONG[rule] if rule in LONG else ((2, 3) if rule == "k23" else (3, 5))
        out = np.full(len(z), -np.inf)
        for t in range(len(z)):
            w = np.sort(z[max(0, t - n + 1):t + 1])[::-1]
            if len(w) >= k:
                out[t] = w[k - 1]
        return out
    s = 0.0; out = np.zeros(len(z))
    for t in range(len(z)):
        s = max(0.0, s + z[t] - prior); out[t] = s
    return out


def first_cross(r, th):
    i = np.flatnonzero(r > th)
    return int(i[0]) if i.size else -1


def outcome(e, al):
    lab = e["run_lab"]; on = int(np.argmax(lab)) if lab.any() else len(lab)
    stop = al if al >= 0 else len(lab); early = 0 <= al < on
    benign_s = min(stop, on) + int(early)
    return dict(run=e["run"], attack=e["attack"], ev=e["evasion"], other=e["other_evasion"], client=e["client"], band=e["band"],
                det=al >= on and e["attack"], miss=al < 0 and e["attack"], early=early, delay=(al - on + DELTA) if (al >= on and e["attack"]) else np.nan,
                undet=((al - on + DELTA) if al >= on else (len(lab) - on)) if e["attack"] else np.nan,
                benign_s=benign_s, leak=float(e["bytes"][:stop].sum()), total=float(e["bytes"].sum()))


def fa_rate(R):
    h = sum(r["benign_s"] for r in R) / 3600
    return sum(r["early"] for r in R) / h if h else np.nan


def fa_real(R):
    by = {}
    for r in R:
        v = by.setdefault(r["band"], [0, 0]); v[0] += r["early"]; v[1] += r["benign_s"] / 3600
    return sum(PI[b] * v[0] / v[1] for b, v in by.items() if v[1] > 0)


def pick(oof, rule, budget):
    """Most sensitive threshold meeting the budget on out-of-fold honest episodes outside L3 phases."""
    eps = [(EP[k], v["honest"]) for k, v in oof.items() if EP[k]["other_evasion"] != "L3"]
    prior = np.log(np.mean([e["run_lab"].mean() for e, _ in eps]) + 1e-9) - np.log(1 - np.mean([e["run_lab"].mean() for e, _ in eps]) + 1e-9)
    S = [(e, stat_series(z, rule, prior)) for e, z in eps]
    # the alarm threshold only matters through the values the statistics take before onset
    cand = np.unique(np.concatenate([r[:max(1, int(np.argmax(e["run_lab"])) if e["run_lab"].any() else len(r))] for e, r in S]))
    cand = cand[np.isfinite(cand)]
    cand = np.r_[cand.max() + 1e-6 if cand.size else 0.0, np.quantile(cand, np.linspace(1, .5, 400)) if cand.size else []]
    best = None
    for th in cand:                                      # from strict to sensitive
        R = [outcome(e, first_cross(r, th)) for e, r in S]
        if fa_rate(R) <= budget + 1e-9:
            best = (th, R)
        else:
            break
    if best is None:
        th = cand[0]; best = (th, [outcome(e, first_cross(r, th)) for e, r in S])
    dl = np.nanmean([r["undet"] for r in best[1] if r["attack"]] or [np.nan])
    det = np.mean([r["det"] for r in best[1] if r["attack"]])
    return best[0], prior, dl, det, best[1]


def summarise(R):
    att = [r for r in R if r["attack"]]
    out = dict(n_att=len(att), fa=fa_rate(R), fa_real=fa_real(R), undet=float(np.nanmean([r["undet"] for r in att])) if att else np.nan,
               delay=float(np.nanmedian([r["delay"] for r in att])) if any(r["det"] for r in att) else np.nan,
               leak=100 * sum(r["leak"] for r in att) / max(sum(r["total"] for r in att), 1))
    for L in ("L1", "L2", "L3"):
        s = [r for r in att if r["ev"] == L]
        out["det_" + L] = 100 * np.mean([r["det"] for r in s]) if s else np.nan
        out["delay_" + L] = float(np.nanmedian([r["delay"] for r in s])) if any(r["det"] for r in s) else np.nan
        out["undet_" + L] = float(np.nanmean([r["undet"] for r in s])) if s else np.nan
    p4 = [r for r in R if not r["attack"] and r["band"] == "P4"]
    out["fa_P4"] = fa_rate(p4) if p4 else np.nan
    return out


def boot(R, key, B):
    by = {}
    for r in R:
        by.setdefault(r["run"], []).append(r)
    runs = list(by); v = []
    for _ in range(B):
        S = [x for i in rng.integers(len(runs), size=len(runs)) for x in by[runs[i]]]
        v.append(summarise(S)[key])
    return [float(x) for x in np.nanpercentile(v, [2.5, 97.5])]


dump = {}
files = sorted(glob.glob(a.dir.rstrip("/") + "/fold*_seed*/scores.pkl"))
res = {"name": a.name, "runs": len(files), "budgets": {}}
chosen = {}
for b in BUDGETS:
    main, l3, client, scen, oofR = [], [], [], {}, []
    for f in files:
        S = pickle.load(open(f, "rb"))
        opts = [(pick(S["oof"], r, b), r) for r in RULES]
        (th, prior, _, _, Ro), rule = min(opts, key=lambda o: (np.nan_to_num(o[0][2], nan=1e9), -o[0][3]))
        chosen.setdefault(b, []).append(rule); oofR.extend(Ro)
        if not a.test:
            continue
        for k, sc in S["test"].items():
            e = EP[k]
            for s, z in sc.items():
                o = outcome(e, first_cross(stat_series(z, rule, prior), th))
                o["scen"] = s
                if e["other_evasion"] == "L3":
                    if a.l3app and PHASE_VEC.get((e["run"], e["phase"])) != a.l3app:
                        continue
                    (client if (e["client"] and not e["attack"]) else l3).append(o) if s == "honest" else None
                    continue
                scen.setdefault(s, []).append(o)
                if s == "honest":
                    main.append(o)
    so = summarise(oofR)
    so["ci_delay"] = boot(oofR, "delay", a.boot); so["ci_undet"] = boot(oofR, "undet", a.boot)
    if not a.test:
        res["budgets"][str(b)] = dict(oof=so, rules={r: chosen[b].count(r) for r in set(chosen[b])})
        dump[str(b)] = [(r["run"], r["undet"]) for r in oofR if r["attack"]]
        continue
    m = summarise(main); m["oof"] = so
    m["ci_delay"] = boot(main, "delay", a.boot); m["ci_undet"] = boot(main, "undet", a.boot); m["ci_fa"] = boot(main, "fa", a.boot)
    for L in ("L1", "L2"):
        m["ci_det_" + L] = boot(main, "det_" + L, a.boot)
    m["L3"] = summarise(l3) if l3 else {}
    m["client_fa_episodes"] = [int(sum(r["early"] for r in client)), len(client)]
    m["by_scenario"] = {s: {k: v for k, v in summarise(R).items() if k in ("delay", "fa", "det_L1", "det_L2")} for s, R in scen.items()}
    m["rules"] = {r: chosen[b].count(r) for r in set(chosen[b])}
    res["budgets"][str(b)] = m
lat = [json.load(open(f.replace("scores.pkl", "config.json"))).get("latency_ms", np.nan) for f in files]
res["latency_ms"] = float(np.nanmedian(lat))
print("%s  (%d fold x seed)  latency %.3f ms" % (a.name, len(files), res["latency_ms"]))
print("  OUT-OF-FOLD on training runs (used for selection)")
print("  budget | FA /UE-h | undetected s/episode [CI] | L1 / L2 undet s | median delay s | det L1 / L2      | rules")
for b, m in res["budgets"].items():
    o = m["oof"]
    print("  %5s  | %5.2f    | %5.1f [%5.1f,%5.1f]      | %4.1f / %4.1f     | %4.1f           | %5.1f / %5.1f | %s" % (b, o["fa"], o["undet"], *o["ci_undet"], o["undet_L1"], o["undet_L2"], o["delay"], o["det_L1"], o["det_L2"], m["rules"]))
if not a.test:
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1, default=float)
        pickle.dump(dump, open(a.json.replace(".json", ".pkl"), "wb"))
    raise SystemExit
print("  TEST (read once, chosen configuration only)")
print("  budget | FA test /UE-h [CI]   real | undet s [CI]         | delay s [CI]      | det L1 / L2 / L3     | leak % | FA P4 | client FA | rules")
for b, m in res["budgets"].items():
    print("  %5s  | %5.2f [%4.2f,%4.2f] %5.2f | %5.1f [%5.1f,%5.1f] | %4.1f [%4.1f,%4.1f] | %5.1f / %5.1f / %5.1f | %5.1f | %5.2f | %d/%d | %s" % (
        b, m["fa"], *m["ci_fa"], m["fa_real"], m["undet"], *m["ci_undet"], m["delay"], *m["ci_delay"], m["det_L1"], m["det_L2"], m["L3"].get("det_L3", np.nan),
        m["leak"], m["fa_P4"], *m["client_fa_episodes"], m["rules"]))
if a.json:
    json.dump(res, open(a.json, "w"), indent=1, default=float)
