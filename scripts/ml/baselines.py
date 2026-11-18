#!/usr/bin/env python3
"""Baselines of plan step 3b, scored like the final model so report_clf.py applies unchanged (same budgets, thresholds chosen
on the training runs' scores, same outcomes). Writes <out>/<name>/fold9_seed0/scores.pkl = {"oof": {episode: {scenario: score}},
"test": {...}}; "oof" covers the training runs of the split, "test" its test runs. No test label is read.
  B1  rate     core UL kbit/s of the second (the alarm rules of report_clf.py turn it into thr / k of n)
  B2a ewma     self-reference: log1p core UL minus the UE's own EWMA (lambda 0.1) of the previous seconds of the episode
  B2b cusum    CUSUM of the standardised log1p core UL (mean and sd of benign training seconds, drift k = 0.5)
  B4  iforest  Isolation Forest on the 25 model inputs, fitted on benign seconds of training runs (grouped 4-fold for the
               training runs' own scores); score = minus the sklearn score
B3 (KPM only) is trained with train_clf.py --features fkpm on episodes built with EP_NOMASK=1.
Usage: baselines.py --data a.pkl[,b.pkl] --split split.json --groups groups.json --out artifacts/clf/baselines [--only rate,ewma,cusum,iforest]"""
import argparse, json, pathlib, pickle
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import GroupKFold

ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--split", required=True)
ap.add_argument("--groups", required=True); ap.add_argument("--out", required=True); ap.add_argument("--only", default="rate,ewma,cusum,iforest")
a = ap.parse_args()
E = [e for f in a.data.split(",") for e in pickle.load(open(f, "rb"))["episodes"]]
key = lambda e: "|".join((e["run"], e["phase"], e["supi"]))
sp = json.load(open(a.split)); TR_R, TE_R = set(sp["train"]), set(sp["test"])
grp = json.load(open(a.groups))
TR = [e for e in E if e["run"] in TR_R]; TE = [e for e in E if e["run"] in TE_R]


def cur(raw):  # train_clf.py cur(raw, "f15")
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))[:, None]
    dlul = (raw[:, 7] - raw[:, 6])[:, None]
    return np.hstack([raw[:, [6, 7, 8, 9, 2, 3]], prbk, raw[:, [10, 11]], dlul, raw[:, [30, 26, 27, 28, 29]]])


def win_summary(raw, W=10):  # train_clf.py
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


# benign seconds of the training runs (honest scenario, before any onset): reference statistics for B2b and B4
ben = np.concatenate([e["scen"]["honest"][:, 6][e["run_lab"] == 0] for e in TR if e["other_evasion"] != "L3"])
MU, SD = float(ben.mean()), float(ben.std() + 1e-6)


def rate(raw):
    return np.expm1(raw[:, 6]).astype(np.float32)


def ewma(raw, lam=.1):
    x = raw[:, 6]; out = np.zeros(len(x), np.float32); m = None
    for t, v in enumerate(x):
        out[t] = 0.0 if m is None else v - m
        m = v if m is None else lam * v + (1 - lam) * m
    return out


def cusum(raw, k=.5):
    z = (raw[:, 6] - MU) / SD; out = np.zeros(len(z), np.float32); s = 0.0
    for t, v in enumerate(z):
        s = max(0.0, s + v - k); out[t] = s
    return out


def save(name, oof, test):
    d = pathlib.Path(a.out) / name / "fold9_seed0"; d.mkdir(parents=True, exist_ok=True)
    pickle.dump(dict(oof=oof, test=test), open(d / "scores.pkl", "wb"))
    json.dump(dict(model=name, train_runs=sorted(TR_R), test_runs=sorted(TE_R), mu=MU, sd=SD), open(d / "config.json", "w"))
    print("wrote", d)


only = a.only.split(",")
for name, fn in (("rate", rate), ("ewma", ewma), ("cusum", cusum)):
    if name in only:
        save("B_" + name, {key(e): {s: fn(r) for s, r in e["scen"].items()} for e in TR}, {key(e): {s: fn(r) for s, r in e["scen"].items()} for e in TE})

if "iforest" in only:
    X = lambda e, s: np.hstack([cur(e["scen"][s]), win_summary(e["scen"][s])]).astype(np.float32)

    def fit(eps, seed=0):
        B = np.concatenate([X(e, "honest")[e["run_lab"] == 0] for e in eps if e["other_evasion"] != "L3"])
        rng = np.random.default_rng(seed); B = B[rng.choice(len(B), min(len(B), 200000), replace=False)]
        return IsolationForest(n_estimators=200, max_samples=4096, random_state=seed, n_jobs=6).fit(B)

    g = np.array([grp[e["run"]] for e in TR]); oof = {}
    for a_i, b_i in GroupKFold(4).split(TR, groups=g):
        m = fit([TR[i] for i in a_i])
        for i in b_i:
            e = TR[i]; oof[key(e)] = {s: (-m.score_samples(X(e, s))).astype(np.float32) for s in e["scen"]}
    m = fit(TR)
    save("B_iforest", oof, {key(e): {s: (-m.score_samples(X(e, s))).astype(np.float32) for s in e["scen"]} for e in TE})
