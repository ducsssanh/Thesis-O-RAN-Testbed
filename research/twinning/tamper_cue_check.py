#!/usr/bin/env python3
"""Does the KPM tamper injection leave its own cue? A classifier on the 6 KPM features only, honest against tampered seconds of the same attack episodes, cross-validated by run. Usage: tamper_cue_check.py <rows.parquet>"""
import sys, pathlib
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier as HGB
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts/ml"))
import tamper_replay as TR
KPM = ["rate_ul_kbps", "rate_dl_kbps", "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
df = pd.read_parquet(sys.argv[1]).dropna(subset=KPM)
rng = np.random.default_rng(0)
for f in (.1, .33, .8, 1.25, 2, 5):
    parts, y = [], []
    for (run, phase), g in df[df.attack_active == 1].groupby(["run_id", "phase"]):
        g = g.sort_values("t_unix")
        half = rng.random() < .5                     # each episode appears once, honest or tampered, so a value cannot be matched to its own copy
        t = TR.tamper(df[(df.run_id == run)], g.supi.iloc[0], int(g.t_unix.iloc[0]), int(g.t_unix.iloc[-1]) + 1, factor=f, on_only=True) if half else None
        parts.append((t[t.index.isin(g.index)] if half else g).assign(_y=int(half)))
    d = pd.concat(parts)
    X, y, grp = d[KPM].to_numpy(), d._y.to_numpy(), d.run_id.to_numpy()
    n = min(5, len(set(grp)))
    p = np.zeros(len(d))
    for tr, te in GroupKFold(n).split(X, y, grp):
        p[te] = HGB(max_iter=100, random_state=0).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    print("x%-5s seconds %d tampered share %.2f KPM-only AUC %.3f" % (f, len(d), y.mean(), roc_auc_score(y, p)))
