#!/usr/bin/env python3
"""Per-second raw features for the classifier plan (Kế hoạch huấn luyện classifier): the episodes and tamper scenarios of
scripts/drl/episodes.py, with one more column, c_t over 3 s. Feature sets are cut from these columns in train_clf.py.
Columns 0-29 are the 30 features of episodes.py (KPM zeroed when the per-UE gate masks it, profiler zeroed when it arrives
after t + 0.2 s); column 30 is c_t_w clipped to [-3, 3], zeroed like c_t.
Usage: clf_features.py <rows.parquet> <out.pkl>"""
import pathlib, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "drl"))
import episodes as EP

_old = EP.features


def features(g):
    f = _old(g)
    late = (g.prof_age_s.to_numpy() > EP.DELTA) | np.isnan(g.prof_age_s.to_numpy())
    cw = np.clip(np.nan_to_num(g.c_t_w.to_numpy()), -3, 3).astype(np.float32)
    cw[late] = 0
    return np.c_[f, cw].astype(np.float32)


EP.features = features
EP.NAMES = EP.NAMES + ["c_t_w"]
if __name__ == "__main__":
    EP.main()
