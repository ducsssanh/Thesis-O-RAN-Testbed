#!/usr/bin/env python3
"""Expected block decisions of the embedded classifier for the C parity test (tests/xapp/test_clf_parity.c BLOCK_OUT): per row of
the parity sequences (clf_parity_seq.py: ep, 15 per-second inputs, NF model inputs, z from xgboost), the model's block rule as
eval_block_rules.py computes it (active second = core UL >= 8 kbit/s), fresh state per episode. One 0/1 per row.
Usage: clf_block_expected.py <clf_model.json> <seq.csv> <out.txt> [rule threshold]  (rule/threshold override the model's)"""
import json, sys
import numpy as np
MJ, SEQ, OUT = sys.argv[1:4]
m = json.load(open(MJ)); rule = sys.argv[4] if len(sys.argv) > 4 else m["block"]["rule"]
th = float(sys.argv[5]) if len(sys.argv) > 5 else m["block"]["threshold"]
NF = len(m["features"])
src = open("scripts/ml/eval_block_rules.py").read()
ns = {"np": np}
exec(compile(src[src.index("RULES = {"):src.index("def active(")], "rules", "exec"), ns)   # RULES only, no data loaded
exec(compile(src[src.index("def stat("):src.index("def first(")], "stat", "exec"), ns)
d = np.loadtxt(SEQ, delimiter=",", dtype=np.float64)
out = []
for ep in np.unique(d[:, 0]):
    r = d[d[:, 0] == ep]
    z = r[:, 16 + NF].astype(np.float32)
    act = np.expm1(r[:, 1].astype(np.float32)) >= 8.0
    s = ns["stat"](z, act, rule, m["block"].get("prior", 0.0))
    out += [int(v > th) for v in s]
open(OUT, "w").write("\n".join(map(str, out)) + "\n")
print(rule, th, "rows", len(out), "block rows", sum(out))
