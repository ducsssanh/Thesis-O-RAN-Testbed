#!/usr/bin/env python3
"""Plan step 3d: set the block rule of an exported model to an active-second rule, threshold chosen on the ENSEMBLE's
out-of-fold training scores (mean of the seeds, as export_clf.py) at budget 0.5 with eval_block_rules.py's selection.
Usage: export_block_rule.py <model dir with fold*_seed*> <data pkl list> <clf_model.json in/out> <rule, e.g. a1020>"""
import glob, json, pickle, sys
import numpy as np
D, DATA, MJ, RULE = sys.argv[1:5]
argv = sys.argv; sys.argv = ["eval_block_rules.py", "--data", DATA, "x=y:z"]
ns = {}; exec(compile(open("scripts/ml/eval_block_rules.py").read().split('print("budget')[0], "ebr", "exec"), ns); sys.argv = argv
S = [pickle.load(open(f, "rb"))["oof"] for f in sorted(glob.glob(D.rstrip("/") + "/fold*_seed*/scores.pkl"))]
oof = {k: {"honest": np.mean([s[k]["honest"] for s in S], 0)} for k in set.intersection(*[set(s) for s in S])}
th, prior, _ = ns["pick"](oof, RULE, 0.5)
m = json.load(open(MJ)); old = m["block"]
m["block"] = dict(budget=0.5, rule=RULE, threshold=float(th), prior=float(prior), note="active seconds only (core UL >= 8 kbit/s), plan step 3d", replaced=old.get("rule"))
json.dump(m, open(MJ, "w"))
print("block", old.get("rule"), round(old.get("threshold", np.nan), 4), "->", RULE, round(float(th), 4))
