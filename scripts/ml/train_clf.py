#!/usr/bin/env python3
"""Train one classifier for one outer fold and one seed (Kế hoạch huấn luyện classifier). Writes calibrated logits per
second for (a) the out-of-fold part of the training runs, used later to set alarm thresholds, and (b) the test runs.
Thresholds, alarm rules and metrics are in report_clf.py; this script never looks at test labels.

Steps: outer GroupKFold(5) on run groups (runs that share a twin window are one group); training runs drop L3 phases;
15 % of training groups form the inner split for hyperparameters and early stopping; 4-fold out-of-fold scores over the
training runs; temperature fitted on those scores; final model on all training runs scores the test runs.
Usage: train_clf.py --model lgbm|xgb|mlp|gru --features f15|fcore|fran|fproto|f30 [--win 10] [--fold k] [--seed s]
       [--grid] [--hp '{...}'] --out <dir>"""
import argparse, json, pathlib, pickle, time
import numpy as np
from sklearn.model_selection import GroupKFold
import sys; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from baselines_feat import SUBSETS  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True); ap.add_argument("--features", default="f15"); ap.add_argument("--win", type=int, default=10)
ap.add_argument("--fold", type=int, default=0); ap.add_argument("--seed", type=int, default=0); ap.add_argument("--grid", action="store_true")
ap.add_argument("--hp", default="{}"); ap.add_argument("--threads", type=int, default=4); ap.add_argument("--out", required=True)
ap.add_argument("--l2w", type=float, default=1.0); ap.add_argument("--l3", default="none")
ap.add_argument("--split", default=""); ap.add_argument("--extra", default="")
ap.add_argument("--save-model", action="store_true")
ap.add_argument("--active-labels", action="store_true")   # E1 (2026-11-09): silent seconds after the onset (attack sends nothing) get weight 0         # xgb only: final booster as model.json (xApp export)
ap.add_argument("--data", default="artifacts/clf/episodes31.pkl"); ap.add_argument("--groups", default="artifacts/clf/run_groups.json")
a = ap.parse_args()
rng = np.random.default_rng(a.seed)
D = pickle.load(open(a.data, "rb")); E = D["episodes"]
if a.extra:                                   # episodes of a second campaign (vòng 4), same columns
    E = E + pickle.load(open(a.extra, "rb"))["episodes"]
key = lambda e: "|".join((e["run"], e["phase"], e["supi"]))

# ---------------------------------------------------------------- feature sets (columns of clf_features.py)
PROTO = list(range(12, 19)) + list(range(20, 25))


def cur(raw, fs):
    """Per-second features of one episode and scenario. Derived: PRB UL per kbit/s UL, log DL/UL ratio."""
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))[:, None]
    dlul = (raw[:, 7] - raw[:, 6])[:, None]
    c = lambda idx: raw[:, idx]
    if fs == "f15":
        return np.hstack([c([6, 7, 8, 9, 2, 3]), prbk, c([10, 11]), dlul, c([30, 26, 27, 28, 29])])
    if fs == "fcore":
        return np.hstack([c([6, 7, 8, 9, 10, 11]), dlul, c([28, 29])])
    if fs == "fran":
        return c([0, 1, 2, 3, 30, 26, 27, 28, 29])
    if fs == "fproto":
        return np.hstack([cur(raw, "f15"), c(PROTO)])
    if fs == "f15rate":
        return np.hstack([cur(raw, "f15"), c([0, 1])])
    if fs == "f15cell":
        return np.hstack([cur(raw, "f15"), c([4, 5])])
    if fs == "f15dst":
        return np.hstack([cur(raw, "f15"), c([19])])
    if fs == "f30":
        return c(list(range(30)))
    raise SystemExit("unknown feature set " + fs)


def win_summary(raw, W):
    """10 window features over the last W seconds: mean and max of UL kbit/s, UL packets/s, UL PRB; busy share;
    coefficient of variation of UL kbit/s; peak over mean; longest silence (share of W). Causal, zero-padded."""
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


TREE = a.model in ("lgbm", "xgb")


def ratio_windows(raw):
    """B (vòng 3): DL/UL and PRB per kbit/s over the summed last 10 s and 30 s; per-second ratios are noisy in silent seconds."""
    ul, dl, prb = np.expm1(raw[:, 6]), np.expm1(raw[:, 7]), raw[:, 2] * 100
    cu, cd, cp = [np.r_[0, np.cumsum(v)] for v in (ul, dl, prb)]
    out = np.zeros((len(ul), 4), np.float32)
    for t in range(len(ul)):
        for j, W in enumerate((10, 30)):
            lo = max(0, t - W + 1); su, sd_, sp = cu[t + 1] - cu[lo], cd[t + 1] - cd[lo], cp[t + 1] - cp[lo]
            out[t, j] = np.log1p(sd_) - np.log1p(su)
            out[t, 2 + j] = np.log1p(sp / (1 + su))
    return out


def coupling(raw):
    """E2 (2026-11-09): UL-DL coupling over the last 10 s and 30 s, from core UL/DL kbit/s (cols 6, 7): mean and max DL over 10 s;
    log ratio of summed DL to summed UL over 10 s and 30 s; share of UL bytes sent in seconds with DL below 1 kbit/s (10 s, 30 s).
    Causal, float32 like win_summary. A real application sends and receives together; a one-way flood adds UL that DL does not follow."""
    ul, dl = np.expm1(raw[:, 6]), np.expm1(raw[:, 7])
    T = len(ul); out = np.zeros((T, 6), np.float32)
    for t in range(T):
        u10, d10 = ul[max(0, t - 9):t + 1], dl[max(0, t - 9):t + 1]
        u30, d30 = ul[max(0, t - 29):t + 1], dl[max(0, t - 29):t + 1]
        su10, su30 = u10.sum(), u30.sum()
        out[t] = [np.log1p(d10.mean()), np.log1p(d10.max()), np.log1p(d10.sum()) - np.log1p(su10), np.log1p(d30.sum()) - np.log1p(su30),
                  u10[d10 < 1].sum() / su10 if su10 > 0 else 0, u30[d30 < 1].sum() / su30 if su30 > 0 else 0]
    return out


def episode_x(raw):
    if a.features == "f15c":
        return np.hstack([cur(raw, "f15").astype(np.float32), win_summary(raw, a.win), coupling(raw)]).astype(np.float32)
    if a.features in SUBSETS:                    # advisor ablations (2026-11-10): f15c without KPM and gate inputs, or without the gate inputs
        return np.hstack([cur(raw, "f15").astype(np.float32), win_summary(raw, a.win), coupling(raw)]).astype(np.float32)[:, SUBSETS[a.features]]
    if a.features == "fkpm":                     # baseline B3: KPM only (rates, PRBs) + the same window summary over KPM
        rk = raw.copy(); rk[:, 6] = raw[:, 0]; rk[:, 8] = raw[:, 1]
        return np.hstack([raw[:, [0, 1, 2, 3]], win_summary(rk, a.win)]).astype(np.float32)
    fs = a.features[:-1] if a.features.endswith("w") else a.features
    x = cur(raw, fs).astype(np.float32)
    if a.features.endswith("w"):
        x = np.hstack([x, ratio_windows(raw)])
    return np.hstack([x, win_summary(raw, a.win)]) if TREE else x


X = {key(e): {s: episode_x(f) for s, f in e["scen"].items()} for e in E}
F = next(iter(next(iter(X.values())).values())).shape[1]

# ---------------------------------------------------------------- splits
grp = json.load(open(a.groups))
runs = sorted({e["run"] for e in E}); g_of = np.array([grp[r] for r in runs])
if a.split:                                  # fixed split {"train": [...], "test": [...]}; --fold is ignored
    sp = json.load(open(a.split)); tr_runs, te_runs = [r for r in runs if r in set(sp["train"])], [r for r in runs if r in set(sp["test"])]
else:
    tr_i, te_i = list(GroupKFold(5).split(runs, groups=g_of))[a.fold]
    tr_runs, te_runs = [runs[i] for i in tr_i], [runs[i] for i in te_i]
tg = sorted({grp[r] for r in tr_runs}); rng.shuffle(tg); inner_g = set(tg[:max(1, int(.15 * len(tg)))])
PHASE_VEC = {(e["run"], e["phase"]): e["vector"] for e in E if e["attack"]}
L3APP = {"tcp": "tcp_shortconn", "dns": "dns_client"}


def use(e):
    """Training episodes: no L3 phase (default), or L3 phases of all apps / of one app (Q6)."""
    if e["other_evasion"] != "L3":
        return True
    if a.l3 == "all":
        return True
    return a.l3 in L3APP and PHASE_VEC.get((e["run"], e["phase"])) == L3APP[a.l3]
TR = [e for e in E if e["run"] in set(tr_runs) and use(e)]
FIT = [e for e in TR if grp[e["run"]] not in inner_g]; INN = [e for e in TR if grp[e["run"]] in inner_g]
TE = [e for e in E if e["run"] in set(te_runs)]


def weights(e):
    ks = list(e["scen"]); n = len(ks) - 1; m = a.l2w if (e["attack"] and e["evasion"] == "L2") else 1.0
    return {s: m * (.5 if s == "honest" else .5 / n) for s in ks}


mu = sd = None


def rows(eps):
    """Training matrix: one row per second and scenario (trees, MLP) or one window per second (GRU, MLP)."""
    xs, ys, ws = [], [], []
    for e in eps:
        wt = weights(e)
        keep = np.ones(len(e["run_lab"]), np.float32)
        if a.active_labels and e["attack"]:
            keep[(e["run_lab"] == 1) & (e["active"] == 0)] = 0.0
        for s, x in X[key(e)].items():
            xs.append(shape(x)); ys.append(e["run_lab"].astype(np.float32)); ws.append(np.full(len(x), wt[s], np.float32) * keep)
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(ws)


def shape(x):
    if TREE:
        return x
    z = (x - mu) / sd
    T = len(z); w = np.zeros((T, a.win, F), np.float32)
    for t in range(T):
        seg = z[max(0, t - a.win + 1):t + 1]; w[t, a.win - len(seg):] = seg
    return w.reshape(T, -1) if a.model == "mlp" else w


base = np.vstack([X[key(e)]["honest"] for e in FIT]); mu, sd = base.mean(0), base.std(0) + 1e-6

# ---------------------------------------------------------------- models
import torch, torch.nn as nn
torch.set_num_threads(a.threads); torch.manual_seed(a.seed)


class GRU(nn.Module):
    def __init__(s, h=64):
        super().__init__(); s.g = nn.GRU(F, h, batch_first=True); s.o = nn.Linear(h, 1)

    def forward(s, x):
        return s.o(s.g(x)[0][:, -1]).squeeze(1)


def make_nn():
    if a.model == "gru":
        return GRU()
    d = a.win * F; L = []
    for u in (128, 64):
        L += [nn.Linear(d, u), nn.ReLU(), nn.Dropout(.1)]; d = u
    return nn.Sequential(*L, nn.Linear(d, 1), nn.Flatten(0))


def nn_logits(m, x):
    m.eval(); out = []
    with torch.no_grad():
        for j in range(0, len(x), 8192):
            out.append(m(torch.from_numpy(x[j:j + 8192])).numpy())
    return np.concatenate(out) if out else np.zeros(0)


def fit(hp, Xa, ya, wa, Xv=None, yv=None, wv=None, n_iter=None):
    """Returns (predict_fn, iterations used). With a validation set: early stopping; without: n_iter fixed."""
    if a.model == "lgbm":
        import lightgbm as lgb
        p = dict(objective="binary", learning_rate=hp.get("lr", .05), num_leaves=hp.get("leaves", 31), min_child_samples=hp.get("minc", 100),
                 feature_fraction=.8, bagging_fraction=.8, bagging_freq=1, seed=a.seed, num_threads=a.threads, verbose=-1)
        dt = lgb.Dataset(Xa, ya, weight=wa)
        if Xv is not None:
            b = lgb.train(p, dt, 2000, valid_sets=[lgb.Dataset(Xv, yv, weight=wv)], callbacks=[lgb.early_stopping(100, verbose=False)])
            it = b.best_iteration
        else:
            b = lgb.train(p, dt, n_iter); it = n_iter
        return (lambda x: b.predict(x, num_iteration=it, raw_score=True)), it
    if a.model == "xgb":
        import xgboost as xgb
        p = dict(objective="binary:logistic", eta=hp.get("lr", .05), max_depth=hp.get("depth", 6), subsample=.8, colsample_bytree=.8,
                 tree_method="hist", nthread=a.threads, seed=a.seed)
        dt = xgb.DMatrix(Xa, ya, weight=wa)
        if Xv is not None:
            b = xgb.train(p, dt, 2000, evals=[(xgb.DMatrix(Xv, yv, weight=wv), "v")], early_stopping_rounds=100, verbose_eval=False)
            it = b.best_iteration + 1
        else:
            b = xgb.train(p, dt, n_iter); it = n_iter
        global LAST_BOOSTER; LAST_BOOSTER = (b, it)
        return (lambda x: b.predict(xgb.DMatrix(x), iteration_range=(0, it), output_margin=True)), it
    m = make_nn(); opt = torch.optim.Adam(m.parameters(), lr=hp.get("lr", 3e-4)); lossf = nn.BCEWithLogitsLoss(reduction="none")
    Xt, yt, wt = torch.from_numpy(Xa), torch.from_numpy(ya), torch.from_numpy(wa)
    best, best_sd, bad, it = 1e9, None, 0, 0
    epochs = n_iter or 30
    for ep in range(epochs):
        m.train(); o = torch.from_numpy(rng.permutation(len(Xa)))
        for j in range(0, len(o), 512):
            i = o[j:j + 512]; l = (lossf(m(Xt[i]), yt[i]) * wt[i]).sum() / wt[i].sum()
            opt.zero_grad(); l.backward(); opt.step()
        if Xv is not None:
            z = nn_logits(m, Xv); v = float((wv * (np.logaddexp(0, z) - yv * z)).sum() / wv.sum())
            if v < best - 1e-4:
                best, best_sd, bad, it = v, {k: t.clone() for k, t in m.state_dict().items()}, 0, ep + 1
            else:
                bad += 1
                if bad >= 5:
                    break
    if Xv is not None:
        m.load_state_dict(best_sd)
    else:
        it = epochs
    return (lambda x: nn_logits(m, x)), it


def wlogloss(z, y, w):
    return float((w * (np.logaddexp(0, z) - y * z)).sum() / w.sum())


t0 = time.time()
Xf, yf, wf = rows(FIT); Xi, yi, wi = rows(INN)
grid = {"lgbm": [dict(leaves=l, minc=c) for l in (15, 63) for c in (50, 200)], "xgb": [dict(depth=d) for d in (4, 8)],
        "mlp": [dict()], "gru": [dict()]}[a.model] if a.grid else [json.loads(a.hp)]
scores = []
for hp in grid:
    pred, it = fit(hp, Xf, yf, wf, Xi, yi, wi)
    scores.append((wlogloss(pred(Xi), yi, wi), hp, it))
scores.sort(key=lambda s: s[0]); inner_loss, HP, ITER = scores[0]
del Xf, yf, wf, Xi, yi, wi

# out-of-fold scores over all training runs (inner included), fixed iterations
tr_g = np.array([grp[e["run"]] for e in TR]); oof = {}
for k, (a_i, b_i) in enumerate(GroupKFold(4).split(TR, groups=tr_g)):
    A = [TR[i] for i in a_i]; B = [TR[i] for i in b_i]
    Xa, ya, wa = rows(A); pred, _ = fit(HP, Xa, ya, wa, n_iter=ITER); del Xa, ya, wa
    for e in B:
        oof[key(e)] = {s: pred(shape(x)).astype(np.float32) for s, x in X[key(e)].items()}

# temperature on the out-of-fold scores
from scipy.optimize import minimize_scalar
zs = np.concatenate([np.concatenate(list(v.values())) for v in oof.values()])
E_by = {key(e): e for e in E}
ys = np.concatenate([np.tile(E_by[k]["run_lab"], len(v)) for k, v in oof.items()]).astype(np.float32)
wt_T = np.ones_like(ys)
if a.active_labels:   # E1: silent post-onset seconds do not pull the calibration either
    wt_T = np.concatenate([np.tile(np.where((E_by[k]["run_lab"] == 1) & (E_by[k]["active"] == 0) & E_by[k]["attack"], 0.0, 1.0), len(v)) for k, v in oof.items()]).astype(np.float32)
Tm = float(minimize_scalar(lambda T: wlogloss(zs / T, ys, wt_T), bounds=(.05, 20), method="bounded").x)

# final model on all training runs
Xa, ya, wa = rows(TR); pred, _ = fit(HP, Xa, ya, wa, n_iter=ITER); del Xa, ya, wa
test = {key(e): {s: (pred(shape(x)) / Tm).astype(np.float32) for s, x in X[key(e)].items()} for e in TE}
oof = {k: {s: (v / Tm).astype(np.float32) for s, v in d.items()} for k, d in oof.items()}
one = shape(X[key(TE[0])]["honest"])[:1]; t1 = time.perf_counter()
for _ in range(200):
    pred(one)
lat_ms = (time.perf_counter() - t1) / 200 * 1000

o = pathlib.Path(a.out); o.mkdir(parents=True, exist_ok=True)
cfg = dict(active_labels=a.active_labels, model=a.model, features=a.features, win=a.win, l2w=a.l2w, l3=a.l3, n_features=F, fold=a.fold, seed=a.seed, hp=HP, iterations=ITER, inner_logloss=inner_loss,
           temperature=Tm, grid=[(s, h, i) for s, h, i in scores], train_runs=tr_runs, test_runs=te_runs, latency_ms=lat_ms, seconds=time.time() - t0)
json.dump(cfg, open(o / "config.json", "w"), indent=1)
pickle.dump(dict(oof=oof, test=test), open(o / "scores.pkl", "wb"))
if a.save_model and a.model == "xgb":
    b, it = LAST_BOOSTER; b[:it].save_model(str(o / "model.json"))
print("done", a.model, a.features, "fold", a.fold, "seed", a.seed, "hp", HP, "iter", ITER, "T %.2f" % Tm, "lat %.2f ms" % lat_ms, "%.0f s" % (time.time() - t0), flush=True)
