#!/usr/bin/env bash
# Round 4: build the L2 campaign dataset, then train the final configuration on the old 72 runs plus the
# 24 new training runs, and the comparison on the old runs only; both are scored once on the 12 clean-test runs.
set -eu
cd "$(dirname "$0")/../../.."
P=.venv-ml/bin/python; M=research/datasets/oran_flooding_twin_l2/manifest
RUNS=$($P -c "import json; L=[json.loads(l) for l in open('$M/campaign_log.jsonl')]; k={x['id']:x['run'] for x in L if x['event']=='kept'}; print(' '.join(k[i] for i in sorted(k)))")
$P scripts/ml/build_dataset_twin.py --out research/datasets/oran_flooding_twin_l2 $RUNS
$P scripts/ml/clf_features.py research/datasets/oran_flooding_twin_l2/rows.parquet artifacts/clf/episodes31_l2.pkl
$P scripts/ml/clf_groups.py research/datasets/oran_flooding_twin/rows.parquet,research/datasets/oran_flooding_twin_l2/rows.parquet artifacts/clf/run_groups_all.json
$P - <<'PY'
import json, pickle
d = json.load(open("research/datasets/oran_flooding_twin_l2/manifest/design.json"))
split = {r["id"]: r["split"] for r in d["runs"]}
old = sorted({e["run"] for e in pickle.load(open("artifacts/clf/episodes31.pkl", "rb"))["episodes"]})
new = pickle.load(open("artifacts/clf/episodes31_l2.pkl", "rb"))["episodes"]
rid = lambda r: next((i for i in split if ("_" + i + "a") in r or r.endswith(i)), None)
by = {}
for e in new:
    by.setdefault(split.get(rid(e["run"]) or "", "?"), set()).add(e["run"])
print({k: len(v) for k, v in by.items()})
json.dump({"train": old + sorted(by.get("train", [])), "test": sorted(by.get("clean_test", []))}, open("artifacts/clf/split_final.json", "w"))
json.dump({"train": old, "test": sorted(by.get("clean_test", []))}, open("artifacts/clf/split_oldonly.json", "w"))
PY
for s in 0 1 2; do
  $P scripts/ml/train_clf.py --model xgb --features f15 --grid --l3 all --extra artifacts/clf/episodes31_l2.pkl --groups artifacts/clf/run_groups_all.json --split artifacts/clf/split_final.json --seed $s --threads 6 --out artifacts/clf/R050_final/fold9_seed$s &
  $P scripts/ml/train_clf.py --model xgb --features f15 --grid --l3 all --extra artifacts/clf/episodes31_l2.pkl --groups artifacts/clf/run_groups_all.json --split artifacts/clf/split_oldonly.json --seed $s --threads 6 --out artifacts/clf/R051_oldonly/fold9_seed$s &
  wait
done
D=artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl
for r in R050_final R051_oldonly; do
  $P scripts/ml/report_clf.py "$r soft (best rule)" artifacts/clf/$r --data $D --test --boot 300 > research/clf/${r}_CLEAN_soft.txt 2>&1
  $P scripts/ml/report_clf.py "$r block (20 of 30)" artifacts/clf/$r --data $D --long --rule k2030 --test --boot 300 > research/clf/${r}_CLEAN_block.txt 2>&1
done
echo round4 done
