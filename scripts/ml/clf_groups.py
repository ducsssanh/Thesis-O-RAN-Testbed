#!/usr/bin/env python3
"""Run groups for the outer split: runs that replay the same real twin window (same band and window_index) are put in one
group, so a real user never appears in both train and test. Usage: clf_groups.py <rows.parquet>[,<rows2.parquet>] <out.json>"""
import json, sys
import pandas as pd
d = pd.concat([pd.read_parquet(f, columns=["run_id", "band", "window_index"]) for f in sys.argv[1].split(",")]).dropna().drop_duplicates()
parent = {r: r for r in d.run_id.unique()}


def find(r):
    while parent[r] != r:
        parent[r] = parent[parent[r]]; r = parent[r]
    return r


for _, g in d.groupby(["band", "window_index"]):
    rs = list(g.run_id.unique())
    for r in rs[1:]:
        parent[find(r)] = find(rs[0])
out = {r: find(r) for r in parent}
json.dump(out, open(sys.argv[2], "w"), indent=0)
print("runs", len(out), "groups", len(set(out.values())))
