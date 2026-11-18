#!/usr/bin/env python3
"""Sequences for the C parity test of the embedded classifier (tests/xapp/test_clf_parity.c): for a sample of episodes and
scenarios, per second the 15 per-second inputs (train_clf.py cur("f15")), the 25 model inputs (+ win_summary(.., 10)) and the
ensemble logit computed by xgboost from the boosters of the export. One row per second: ep, 15 inputs, 25 inputs, z.
Usage: clf_parity_seq.py <export dir with fold*_seed*> <data pkl[,pkl]> <out.csv> [n_episodes]"""
import glob, json, pickle, sys
import numpy as np
import xgboost as xgb

D, DATA, OUT = sys.argv[1:4]; N = int(sys.argv[4]) if len(sys.argv) > 4 else 40
E = [e for f in DATA.split(",") for e in pickle.load(open(f, "rb"))["episodes"]]


def cur(raw):  # train_clf.py cur(raw, "f15")
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))[:, None]
    dlul = (raw[:, 7] - raw[:, 6])[:, None]
    return np.hstack([raw[:, [6, 7, 8, 9, 2, 3]], prbk, raw[:, [10, 11]], dlul, raw[:, [30, 26, 27, 28, 29]]])


def win_summary(raw, W):  # train_clf.py
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


dirs = sorted(glob.glob(D.rstrip("/") + "/fold*_seed*"))
FS = json.load(open(dirs[0] + "/config.json"))["features"]
sys.path.insert(0, __import__("os").path.dirname(__file__))
from baselines_feat import coupling  # noqa: E402
B = []
for d in dirs:
    b = xgb.Booster(); b.load_model(d + "/model.json"); B.append((b, json.load(open(d + "/config.json"))["temperature"]))
rng = np.random.default_rng(1)
rows = []
for j, i in enumerate(rng.choice(len(E), N, replace=False)):
    e = E[i]; s = rng.choice(list(e["scen"])); raw = e["scen"][s]
    c = cur(raw).astype(np.float32); x = np.hstack([c, win_summary(raw, 10)] + ([coupling(raw)] if FS == "f15c" else [])).astype(np.float32)
    z = np.mean([b.predict(xgb.DMatrix(x), output_margin=True) / T for b, T in B], 0)
    rows.append(np.c_[np.full(len(x), j), c, x, z])   # columns: ep, 15 per-second, NF model inputs, z
np.savetxt(OUT, np.concatenate(rows), delimiter=",", fmt="%.9g")
print("rows", sum(len(r) for r in rows))
