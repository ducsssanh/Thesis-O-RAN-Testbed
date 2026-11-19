#!/usr/bin/env bash
# Inputs of the round-v5 training (v5_train.sh), built from the rows of the earlier rounds:
#   1. training side of the live v2 and live v4 runs (the benign-only runs of live v4 are kept out: they are the donor pool of
#      the mimic scenario in the blind test)
#   2. episodes of live v2 and live v4 with the mimic scenario and the run-level gate
#   3. run groups (runs that replay the same Madrid window are one group), the split, and one file with the extra episodes
# Needs: clf_round4.sh (split_final.json), after_live.sh, after_live2.sh, after_live4.sh (rows.parquet of each live campaign,
# run_groups_live.json) and mimic_build.sh + mimic_train.sh (episodes31_l2live_m.pkl).
set -eu
cd "$(dirname "$0")/../../.."
P=.venv-ml/bin/python; V=artifacts/clf/v5
mkdir -p $V

$P - <<'PY'
import json, re
import pandas as pd
d4 = {r["id"]: r for r in json.load(open("research/datasets/oran_flooding_live4/manifest/design.json"))["runs"]}
r4 = sorted(pd.read_parquet("artifacts/clf/live4/rows.parquet", columns=["run_id"]).run_id.unique())
r2 = sorted(pd.read_parquet("artifacts/clf/live2/rows.parquet", columns=["run_id"]).run_id.unique())
rid = lambda r: re.search(r"flood-live-(l[a-z]\d{3})_", r).group(1)
bo = [r for r in r4 if d4[rid(r)].get("benign_only")]
print("live v4 runs", len(r4), "benign-only", len(bo), "; live v2 runs", len(r2))
json.dump({"train": [r for r in r4 if r not in bo], "test": bo}, open("artifacts/clf/live4/split_live4_trainside.json", "w"))
json.dump({"train": r2, "test": []}, open("artifacts/clf/live2/split_live2_trainside.json", "w"))
PY

export EP_MIMIC=1 EP_MIMIC_POOL=all EP_GATE=run
for x in live2 live4; do
  EP_SPLIT=artifacts/clf/$x/split_${x}_trainside.json $P scripts/ml/clf_features.py artifacts/clf/$x/rows.parquet $V/episodes31_${x}_m.pkl &
done
wait

$P - <<'PY'
import collections, json, pickle
import pandas as pd
# windows per run (band + window index of the benign twin), for every dataset that enters training
W = {}
for f in ("research/datasets/oran_flooding_twin/rows.parquet", "research/datasets/oran_flooding_twin_l2/rows.parquet",
          "artifacts/clf/live/rows.parquet", "artifacts/clf/live2/rows.parquet", "artifacts/clf/live4/rows.parquet"):
    df = pd.read_parquet(f, columns=["run_id", "band", "window_index"]).dropna().drop_duplicates()
    for r, g in df.groupby("run_id"):
        W.setdefault(r, set()).update((b, int(i)) for b, i in zip(g.band, g.window_index) if i >= 0)
old = json.load(open("artifacts/clf/live/run_groups_live.json"))     # twin, L2 campaign, live 1: groups by Madrid session
# union-find: runs sharing a window are one group; the existing groups stay together
par = {r: r for r in W}
def find(x):
    while par[x] != x:
        par[x] = par[par[x]]; x = par[x]
    return x
def union(a, b): par[find(a)] = find(b)
byw = collections.defaultdict(list)
for r, ws in W.items():
    for w in ws: byw[w].append(r)
for rs in byw.values():
    for r in rs[1:]: union(rs[0], r)
byg = collections.defaultdict(list)
for r, name in old.items():
    if r in par: byg[name].append(r)
for rs in byg.values():
    for r in rs[1:]: union(rs[0], r)
groups = {r: "g:" + find(r) for r in W}
json.dump(groups, open("artifacts/clf/v5/run_groups_v5.json", "w"))
camp = lambda r: "live4" if "-live-ly" in r else "live2" if "-live-lw" in r else "live1" if "-live-lv" in r else "l2c" if "l2c" in r else "twin"
# split: final training runs (twin + L2 campaign) + attack runs of live 1, v2, v4; test = the clean L2 test
fin = json.load(open("artifacts/clf/split_final.json"))
bo = set(json.load(open("artifacts/clf/live4/split_live4_trainside.json"))["test"])
live = [r for r in W if camp(r) in ("live1", "live2", "live4") and r not in bo]
sp = {"train": fin["train"] + sorted(live), "test": fin["test"]}
leak = {groups[r] for r in sp["test"]} & {groups[r] for r in sp["train"]}
print("runs", len(W), "groups", len(set(groups.values())), "train", len(sp["train"]), "test", len(sp["test"]), "test groups also in train:", len(leak))
assert not leak
json.dump(sp, open("artifacts/clf/v5/split_v5.json", "w"))
E = []
for p in ("artifacts/clf/mimic/episodes31_l2live_m.pkl", "artifacts/clf/v5/episodes31_live2_m.pkl", "artifacts/clf/v5/episodes31_live4_m.pkl"):
    d = pickle.load(open(p, "rb")); E += d["episodes"]
assert not {e["run"] for e in E} - set(groups)
pickle.dump(dict(names=d["names"], groups=d["groups"], protocol=d["protocol"], episodes=E), open("artifacts/clf/v5/extra_l2_live124_m.pkl", "wb"))
print("extra episodes", len(E))
PY
