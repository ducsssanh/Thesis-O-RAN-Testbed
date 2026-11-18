#!/usr/bin/env bash
# Section 7.4 rerun (2026-11-12): every compared method on the same 177 training runs, rules fixed for all (rate limit: 1 s;
# block: 5 of 10 active s), thresholds on each method's own out-of-fold scores. Status: artifacts/clf/jobs/cmp_<step>.status.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; O=artifacts/clf/abl; J=artifacts/clf/jobs; V=artifacts/clf/v5; L5=artifacts/clf/live5; L6=artifacts/clf/live6
st() { echo "$2" > $J/cmp_$1.status; }
fail() { st $1 "FAILED $2"; exit 1; }
DN=artifacts/clf/mimic/episodes31_m_nomask.pkl,$O/extra_l2_live124_m_nomask.pkl
# 1. KPM-only XGBoost (baseline B3), KPM as reported, no gate input, same split and data as the deployed model
st kpm running
C="--model xgb --grid --l3 all --groups $V/run_groups_v5.json --split $V/split_v5.json --threads 5 --save-model --active-labels --features fkpm"
pids=()
for s in 0 1 2; do
  ( $P scripts/ml/train_clf.py $C --data ${DN%%,*} --extra ${DN#*,} --seed $s --out $O/R093_kpm/fold9_seed$s > $O/train_R093_kpm_s$s.log 2>&1 ) & pids+=($!)
done
for p in "${pids[@]}"; do wait $p || fail kpm "a seed failed"; done
$P -c "import json; json.dump(dict(name='R093_kpm', feature_set='fkpm', features=['kpm']), open('$O/R093_kpm.json','w'))"
$P scripts/ml/select_block_rule.py $O/R093_kpm $DN $O/R093_kpm.json > $O/R093_kpm_rules.txt 2>&1 || fail kpm "rules"
$P scripts/ml/score_models_on.py $O/R093_kpm $L5/episodes31_live5_mall_nomask.pkl xgb_fkpm $O/R093_kpm_live5 > $O/score_kpm.log 2>&1 || fail kpm "score live5"
$P scripts/ml/score_models_on.py $O/R093_kpm $L6/episodes31_live6_mall_nomask.pkl xgb_fkpm $O/R093_kpm_live6 >> $O/score_kpm.log 2>&1 || fail kpm "score live6"
st kpm ok
# 2. statistical baselines and Isolation Forest on the same training runs; test = both parts of the live test
st base running
$P - <<PY || fail base "split"
import json, pickle
sp = json.load(open("$V/split_v5.json")); g = json.load(open("$V/run_groups_v5.json"))
test = sorted({e["run"] for f in ("$L5/episodes31_live5_mall.pkl", "$L6/episodes31_live6_mall.pkl") for e in pickle.load(open(f, "rb"))["episodes"]})
json.dump({"train": sp["train"], "test": test}, open("$O/split_cmp.json", "w"))
g.update({r: "test:" + r for r in test}); json.dump(g, open("$O/groups_cmp.json", "w"))
print(len(sp["train"]), "train runs,", len(test), "test runs")
PY
$P scripts/ml/baselines.py --data artifacts/clf/mimic/episodes31_m.pkl,$V/extra_l2_live124_m.pkl,$L5/episodes31_live5_mall.pkl,$L6/episodes31_live6_mall.pkl \
  --split $O/split_cmp.json --groups $O/groups_cmp.json --out $O/base_cmp > $O/base_cmp.log 2>&1 || fail base "baselines rc=$?"
st base ok
