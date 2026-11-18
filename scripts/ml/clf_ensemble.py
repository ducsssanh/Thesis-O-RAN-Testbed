#!/usr/bin/env python3
"""Average the calibrated logits of several configurations that share folds and seeds (same run groups, same inner
splits): out-of-fold and test scores alike. Usage: clf_ensemble.py <out_dir> <dir_A> <dir_B> [...]"""
import glob, os, pickle, sys
out, srcs = sys.argv[1], sys.argv[2:]
for f in sorted(glob.glob(srcs[0] + "/fold*_seed*/scores.pkl")):
    sub = os.path.basename(os.path.dirname(f))
    S = [pickle.load(open(os.path.join(d, sub, "scores.pkl"), "rb")) for d in srcs]
    avg = {part: {k: {s: sum(x[part][k][s] for x in S) / len(S) for s in S[0][part][k]} for k in S[0][part]} for part in ("oof", "test")}
    os.makedirs(os.path.join(out, sub), exist_ok=True)
    pickle.dump(avg, open(os.path.join(out, sub, "scores.pkl"), "wb"))
    import shutil; shutil.copy(os.path.join(srcs[0], sub, "config.json"), os.path.join(out, sub, "config.json"))
print("ensemble", out, "from", srcs)
