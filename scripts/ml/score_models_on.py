#!/usr/bin/env python3
"""Score episodes with saved per-seed XGBoost models (train_clf.py --save-model) and write report_clf.py-compatible score dirs:
<out>/fold9_seed<s>/scores.pkl with the seed's out-of-fold training scores (thresholds) and test = the given episodes.
kind: xgb_f15 (25 inputs of R050/R060) or xgb_fkpm (KPM-only baseline). Usage: score_models_on.py <model dir> <episodes pkl> <kind> <out dir>"""
import glob, json, pathlib, pickle, sys
import numpy as np
import xgboost as xgb
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from baselines_feat import x25, x31, win_summary, SUBSETS  # noqa: E402

D, P, K, O = sys.argv[1:5]


def fkpm(raw):
    rk = raw.copy(); rk[:, 6] = raw[:, 0]; rk[:, 8] = raw[:, 1]
    return np.hstack([raw[:, [0, 1, 2, 3]], win_summary(rk)]).astype(np.float32)


feat = {"xgb_f15": x25, "xgb_f15c": x31, "xgb_fkpm": fkpm,
        **{"xgb_" + n: (lambda r, ix=ix: x31(r)[:, ix]) for n, ix in SUBSETS.items()}}[K]
E = pickle.load(open(P, "rb"))["episodes"]
key = lambda e: "|".join((e["run"], e["phase"], e["supi"]))
for d in sorted(glob.glob(D.rstrip("/") + "/fold*_seed*")):
    b = xgb.Booster(); b.load_model(d + "/model.json"); T = json.load(open(d + "/config.json"))["temperature"]
    oof = pickle.load(open(d + "/scores.pkl", "rb"))["oof"]
    test = {key(e): {s: (b.predict(xgb.DMatrix(feat(r)), output_margin=True) / T).astype(np.float32) for s, r in e["scen"].items()} for e in E}
    o = pathlib.Path(O) / pathlib.Path(d).name; o.mkdir(parents=True, exist_ok=True)
    pickle.dump(dict(oof=oof, test=test), open(o / "scores.pkl", "wb"))
    json.dump(dict(model=D, test_episodes=P, latency_ms=float("nan")), open(o / "config.json", "w"))
    print("scored", len(test), "->", o)
