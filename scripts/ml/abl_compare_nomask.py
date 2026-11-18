#!/usr/bin/env python3
"""Check that a KPM-as-reported episode file (EP_NOMASK) matches its masked build: same episodes and scenarios, identical non-KPM
columns, identical KPM where the gate did not mask. Exit 1 on any difference. Usage: abl_compare_nomask.py <masked.pkl> <nomask.pkl>"""
import pickle, sys, numpy as np
k = lambda e: "|".join((e["run"], e["phase"], e["supi"]))
A = {k(e): e for e in pickle.load(open(sys.argv[1], "rb"))["episodes"]}
B = {k(e): e for e in pickle.load(open(sys.argv[2], "rb"))["episodes"]}
print("keys equal:", set(A) == set(B), len(A), len(B))
NONKPM = list(range(6, 27)) + [28, 29, 30]
bad = {}
for x in A:
    if x not in B: bad["missing"] = bad.get("missing", 0) + 1; continue
    if set(A[x]["scen"]) != set(B[x]["scen"]): bad["scenset"] = bad.get("scenset", 0) + 1
    for s in set(A[x]["scen"]) & set(B[x]["scen"]):
        if not np.allclose(A[x]["scen"][s][:, NONKPM], B[x]["scen"][s][:, NONKPM]): bad[s] = bad.get(s, 0) + 1
    for s in set(A[x]["scen"]) & set(B[x]["scen"]):
        m = A[x]["scen"][s][:, 27] > 0
        if not np.allclose(A[x]["scen"][s][~m, :6], B[x]["scen"][s][~m, :6]): bad["kpm_unmasked_" + s] = bad.get("kpm_unmasked_" + s, 0) + 1
print(sys.argv[2], "vs", sys.argv[1], "mismatches:", bad or "none"); sys.exit(1 if bad or set(A) != set(B) else 0)
