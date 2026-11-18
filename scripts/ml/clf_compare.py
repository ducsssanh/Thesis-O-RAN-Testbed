#!/usr/bin/env python3
"""Paired comparison of two configurations on the out-of-fold training scores: mean undetected attack seconds per
episode, B minus A, 95 % CI by bootstrap over runs (both configurations see the same runs, folds and seeds).
Usage: clf_compare.py <A_oof.pkl> <B_oof.pkl> [budget ...]"""
import pickle, sys
import numpy as np
A, B = pickle.load(open(sys.argv[1], "rb")), pickle.load(open(sys.argv[2], "rb"))
rng = np.random.default_rng(0)
for b in (sys.argv[3:] or list(A)):
    da, db = {}, {}
    for r, u in A[b]:
        da.setdefault(r, []).append(u)
    for r, u in B[b]:
        db.setdefault(r, []).append(u)
    runs = sorted(set(da) & set(db))
    def diff(rs):
        return np.mean([u for r in rs for u in db[r]]) - np.mean([u for r in rs for u in da[r]])
    v = [diff([runs[i] for i in rng.integers(len(runs), size=len(runs))]) for _ in range(1000)]
    lo, hi = np.percentile(v, [2.5, 97.5])
    print("budget %4s  B - A = %+5.2f s [%+5.2f, %+5.2f]  %s" % (b, diff(runs), lo, hi, "B better" if hi < 0 else "A better" if lo > 0 else "tie"))
