#!/usr/bin/env python3
"""How different is the live test data from the training data? (2026-11-10) Adversarial validation: a classifier learns to tell
training seconds from live-test seconds on the 31 model inputs (honest scenario as recorded); AUC 0.5 = indistinguishable
(test drawn from the training distribution), AUC near 1 = clearly different. Grouped 5-fold by run, classes weighted equally.
Separately for benign UE seconds and for attack seconds after the onset, plus the inputs that differ most (KS statistic).
Usage: adv_validation.py <train pkl list> <train split json or -> <test pkl> <name>"""
import json, pickle, sys
import numpy as np
import xgboost as xgb
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
sys.path.insert(0, __import__("os").path.dirname(__file__))
from baselines_feat import x31  # noqa: E402
TR, SPLIT, TE, NAME = sys.argv[1:5]
MODEL = json.load(open("artifacts/clf/mimic/export_e3/clf_model.json"))["features"]
train_runs = set(json.load(open(SPLIT))["train"]) if SPLIT != "-" else None
rng = np.random.default_rng(0)


def rows(eps, kind):
    X, G = [], []
    for e in eps:
        if kind == "benign" and e["attack"]:
            continue
        if kind == "attack" and not e["attack"]:
            continue
        x = x31(e["scen"]["honest"])
        if kind == "attack":
            x = x[e["run_lab"] == 1]
        idx = rng.choice(len(x), min(len(x), 25), replace=False) if len(x) else []
        X.append(x[idx]); G += [e["run"]] * len(idx)
    return np.concatenate(X), np.array(G)


A = [e for f in TR.split(",") for e in pickle.load(open(f, "rb"))["episodes"] if train_runs is None or e["run"] in train_runs]
B = pickle.load(open(TE, "rb"))["episodes"]
print("%s: train episodes %d (%d runs), test episodes %d (%d runs)" % (NAME, len(A), len({e["run"] for e in A}), len(B), len({e["run"] for e in B})))
for kind in ("benign", "attack"):
    Xa, Ga = rows(A, kind); Xb, Gb = rows(B, kind)
    X = np.vstack([Xa, Xb]); y = np.r_[np.zeros(len(Xa)), np.ones(len(Xb))]; g = np.r_[Ga, Gb]
    w = np.where(y == 1, len(Xa) / len(Xb), 1.0)
    p = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(X, y, g):
        m = xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.1, subsample=0.8, n_jobs=4, verbosity=0)
        m.fit(X[tr], y[tr], sample_weight=w[tr]); p[te] = m.predict_proba(X[te])[:, 1]
    auc = roc_auc_score(y, p, sample_weight=w)
    ks = sorted(((ks_2samp(Xa[:, j], Xb[:, j]).statistic, MODEL[j]) for j in range(X.shape[1])), reverse=True)
    print("  %-6s seconds: train %6d, test %6d | adversarial AUC %.3f | largest KS: %s" % (
        kind, len(Xa), len(Xb), auc, ", ".join("%s %.2f" % (n, s) for s, n in ks[:5])))
