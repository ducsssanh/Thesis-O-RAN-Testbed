#!/usr/bin/env python3
"""Export the final classifier (R050) for the xApp: one JSON file the C code in the xApp loads (clf_xgb.c).

Ensemble = mean of the calibrated logits of the seeds (each seed's booster margin / its temperature). Thresholds and alarm
rules are chosen again on the ensemble's out-of-fold training scores, with the selection of report_clf.py (functions copied
below, unchanged): rate limit at 2 false alarms per benign UE-hour (best of thr, k23, k35, cusum by out-of-fold undetected
seconds), block at 0.5 with the 20-of-30 rule. Test scores are never read here.
Also writes a parity file: 2000 random rows (25 features) with the ensemble logit from xgboost, for the C unit test.
Usage: export_clf.py <dir with fold9_seed*/{model.json,config.json,scores.pkl}> <data pkl[,pkl]> <out.json> <parity.csv>"""
import glob, json, pathlib, pickle, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import numpy as np
import xgboost as xgb

D, DATA, OUT, PAR = sys.argv[1:5]
EP = {"|".join((e["run"], e["phase"], e["supi"])): e for f in DATA.split(",") for e in pickle.load(open(f, "rb"))["episodes"]}
DELTA = .2
LONG = {"k610": (6, 10), "k1220": (12, 20), "k2030": (20, 30)}
F15 = ["core_ul_kbps", "core_dl_kbps", "core_ul_pps", "core_dl_pps", "prb_ul", "prb_dl", "prb_ul_per_kbit", "size_ul", "size_dl",
       "dl_over_ul", "c_t_w", "trust_ue", "mask_ue", "kpm_age", "prof_age"]
WIN = ["w_ul_kbps_mean", "w_ul_kbps_max", "w_ul_pps_mean", "w_ul_pps_max", "w_prb_mean", "w_prb_max", "w_busy", "w_cv", "w_peak", "w_silence"]


# ---- copied from report_clf.py (selection only) ----
def stat_series(z, rule, prior):
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
    return dict(attack=e["attack"], det=al >= on and e["attack"], early=early, benign_s=min(stop, on) + int(early),
                undet=((al - on + DELTA) if al >= on else (len(lab) - on)) if e["attack"] else np.nan)


def fa_rate(R):
    h = sum(r["benign_s"] for r in R) / 3600
    return sum(r["early"] for r in R) / h if h else np.nan


def pick(oof, rule, budget):
    eps = [(EP[k], v["honest"]) for k, v in oof.items() if EP[k]["other_evasion"] != "L3"]
    m = np.mean([e["run_lab"].mean() for e, _ in eps]); prior = np.log(m + 1e-9) - np.log(1 - m + 1e-9)
    S = [(e, stat_series(z, rule, prior)) for e, z in eps]
    cand = np.unique(np.concatenate([r[:max(1, int(np.argmax(e["run_lab"])) if e["run_lab"].any() else len(r))] for e, r in S]))
    cand = cand[np.isfinite(cand)]
    cand = np.r_[cand.max() + 1e-6 if cand.size else 0.0, np.quantile(cand, np.linspace(1, .5, 400)) if cand.size else []]
    best = None
    for th in cand:
        R = [outcome(e, first_cross(r, th)) for e, r in S]
        if fa_rate(R) <= budget + 1e-9:
            best = (th, R)
        else:
            break
    if best is None:
        th = cand[0]; best = (th, [outcome(e, first_cross(r, th)) for e, r in S])
    dl = np.nanmean([r["undet"] for r in best[1] if r["attack"]] or [np.nan])
    det = np.mean([r["det"] for r in best[1] if r["attack"]])
    return float(best[0]), float(prior), float(dl), float(det), fa_rate(best[1])
# ---- end of copy ----


dirs = sorted(glob.glob(D.rstrip("/") + "/fold*_seed*"))
cfgs = [json.load(open(d + "/config.json")) for d in dirs]
S = [pickle.load(open(d + "/scores.pkl", "rb"))["oof"] for d in dirs]
keys = set.intersection(*[set(s) for s in S])
oof = {k: {"honest": np.mean([s[k]["honest"] for s in S], 0)} for k in keys}

soft = []
for rule in ("thr", "k23", "k35"):   # CUSUM excluded: no natural reset in a continuously running xApp
    th, prior, und, det, fa = pick(oof, rule, 2.0)
    soft.append(dict(rule=rule, threshold=th, prior=prior, oof_undetected_s=und, oof_detection=det, oof_fa=fa))
soft.sort(key=lambda r: (r["oof_undetected_s"], -r["oof_detection"]))
th, prior, und, det, fa = pick(oof, "k2030", 0.5)
block = dict(rule="k2030", threshold=th, prior=prior, oof_undetected_s=und, oof_detection=det, oof_fa=fa)

boosters = []
for d, c in zip(dirs, cfgs):
    m = json.load(open(d + "/model.json"))
    L = m["learner"]
    bs = L["learner_model_param"]["base_score"].strip("[]")
    p0 = float(bs)
    trees = []
    for t in L["gradient_booster"]["model"]["trees"]:
        trees.append(dict(left=t["left_children"], right=t["right_children"], feat=t["split_indices"], thr=t["split_conditions"],
                          default_left=t["default_left"]))  # leaf value = split_conditions of a leaf
    boosters.append(dict(seed=c["seed"], temperature=c["temperature"], base_margin=float(np.log(p0 / (1 - p0))), trees=trees,
                         depth=c["hp"].get("depth"), iterations=c["iterations"]))

FS = cfgs[0]["features"]
COUP = ["dl_mean10", "dl_max10", "dlul_10", "dlul_30", "ul_dlidle_10", "ul_dlidle_30"]
out = dict(name=D.rstrip("/").split("/")[-1], feature_set=FS, features=F15 + WIN + (COUP if FS == "f15c" else []), win_s=10, delta_s=DELTA, ensemble="mean of seed logits / T",
           soft=dict(budget=2.0, **soft[0]), soft_candidates=soft, block=dict(budget=0.5, **block), boosters=boosters)
json.dump(out, open(OUT, "w"))
print("soft", soft[0]["rule"], round(soft[0]["threshold"], 4), "oof undet %.1f det %.3f fa %.2f" % (soft[0]["oof_undetected_s"], soft[0]["oof_detection"], soft[0]["oof_fa"]))
print("block k2030", round(block["threshold"], 4), "oof undet %.1f det %.3f fa %.2f" % (und, det, fa))

# parity rows: features built as train_clf.py cur(raw, "f15") + win_summary(raw, 10) (copied), ensemble logit from xgboost itself
def cur(raw):
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))[:, None]
    dlul = (raw[:, 7] - raw[:, 6])[:, None]
    return np.hstack([raw[:, [6, 7, 8, 9, 2, 3]], prbk, raw[:, [10, 11]], dlul, raw[:, [30, 26, 27, 28, 29]]])


def win_summary(raw, W):
    k, p, r = np.expm1(raw[:, 6]), np.expm1(raw[:, 8]), raw[:, 2] * 100
    T = len(k); out = np.zeros((T, 10), np.float32)
    for t in range(T):
        lo = max(0, t - W + 1); kk, pp, rr = k[lo:t + 1], p[lo:t + 1], r[lo:t + 1]
        m = kk.mean(); busy = kk >= 8
        run = best = 0
        for b in busy:
            run = 0 if b else run + 1; best = max(best, run)
        out[t] = [np.log1p(m), np.log1p(kk.max()), np.log1p(pp.mean()), np.log1p(pp.max()), rr.mean() / 100, rr.max() / 100,
                  busy.mean(), kk.std() / m if m > 0 else 0, kk.max() / m if m > 0 else 0, best / W]
    return out


from baselines_feat import coupling  # noqa: E402
rng = np.random.default_rng(0)
ks = sorted(EP); rows = []
for k in rng.choice(ks, 60, replace=False):
    for s, raw in EP[k]["scen"].items():
        x = np.hstack([cur(raw), win_summary(raw, 10)] + ([coupling(raw)] if FS == "f15c" else [])).astype(np.float32)
        rows.append(x[rng.choice(len(x), 2, replace=False)])
X = np.concatenate(rows)[:2000]
z = np.zeros(len(X))
for d, c in zip(dirs, cfgs):
    b = xgb.Booster(); b.load_model(d + "/model.json")
    z += b.predict(xgb.DMatrix(X), output_margin=True) / c["temperature"]
z /= len(dirs)
np.savetxt(PAR, np.c_[X, z], delimiter=",", fmt="%.9g")
print("parity rows", len(X))
