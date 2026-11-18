#!/usr/bin/env python3
"""Score episodes with the exported R050 ensemble (mean over seeds of booster margin / temperature, as the xApp does) and write a
report_clf.py-compatible scores.pkl: oof = mean of the seeds' out-of-fold scores (thresholds), test = the given episodes.
Usage: score_ens.py <R050_final_m dir> <episodes pkl> <out dir>"""
import glob, json, pathlib, pickle, sys
import numpy as np
import xgboost as xgb
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from baselines_feat import x25  # noqa: E402

D, P, O = sys.argv[1:4]
dirs = sorted(glob.glob(D.rstrip("/") + "/fold*_seed*"))
B = []
for d in dirs:
    b = xgb.Booster(); b.load_model(d + "/model.json"); B.append((b, json.load(open(d + "/config.json"))["temperature"]))
S = [pickle.load(open(d + "/scores.pkl", "rb"))["oof"] for d in dirs]
oof = {k: {s: np.mean([x[k][s] for x in S], 0) for s in S[0][k]} for k in set.intersection(*[set(x) for x in S])}
E = pickle.load(open(P, "rb"))["episodes"]
key = lambda e: "|".join((e["run"], e["phase"], e["supi"]))
test = {}
for e in E:
    test[key(e)] = {}
    for s, raw in e["scen"].items():
        X = x25(raw)
        test[key(e)][s] = np.mean([b.predict(xgb.DMatrix(X), output_margin=True) / T for b, T in B], 0).astype(np.float32)
o = pathlib.Path(O) / "fold9_seed0"; o.mkdir(parents=True, exist_ok=True)
pickle.dump(dict(oof=oof, test=test), open(o / "scores.pkl", "wb"))
json.dump(dict(model="R050 ensemble", seeds=len(dirs), test_episodes=P, latency_ms=float("nan")), open(o / "config.json", "w"))
print("scored", len(test), "episodes ->", o)
