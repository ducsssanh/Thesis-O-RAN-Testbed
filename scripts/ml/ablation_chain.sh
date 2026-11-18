#!/usr/bin/env bash
# Advisor steps 1-3 (2026-11-10), offline on existing data: (1) XGBoost core only (no KPM, no gate input), (2) without the gate inputs
# c_t_w/trust/mask (KPM still masked by the gate, as in the xApp) and (2b) without any gate (KPM as reported, no gate input); same 177
# training runs, same tamper scenarios, same rule selection as the deployed model; (3) every UE's KPM tampered offline on the 30
# live-test runs (frame x1.25/x2/x5, hide x0.8, ...). Status per step: artifacts/clf/jobs/abl_<step>.status; stops at the first failure.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; O=artifacts/clf/abl; J=artifacts/clf/jobs; V=artifacts/clf/v5; L=artifacts/clf/live5; T=${JOB_TMP:-/tmp}
mkdir -p $O $T
st() { echo "$2" > $J/abl_$1.status; }
fail() { st $1 "FAILED $2"; exit 1; }
DM=artifacts/clf/mimic/episodes31_m.pkl,$V/extra_l2_live124_m.pkl
DN=artifacts/clf/mimic/episodes31_m_nomask.pkl,$O/extra_l2_live124_m_nomask.pkl
CMP=scripts/ml/abl_compare_nomask.py

# 1. data: KPM-as-reported copies (EP_NOMASK) built exactly like the training data (donors on the split's side, run-level gate)
st data running
for x in live2 live4; do
  EP_SPLIT=$V/split_v5.json EP_NOMASK=1 EP_MIMIC=1 EP_MIMIC_POOL=all EP_GATE=run $P scripts/ml/clf_features.py artifacts/clf/$x/rows.parquet $O/episodes31_${x}_m_nomask.pkl > $O/data_$x.log 2>&1 || fail data "$x rc=$?"
  $P $CMP $V/episodes31_${x}_m.pkl $O/episodes31_${x}_m_nomask.pkl >> $O/data_check.txt || fail data "$x differs from the training build"
done
$P $CMP artifacts/clf/mimic/episodes31_l2live_m.pkl artifacts/clf/mimic/episodes31_l2live_m_nomask.pkl >> $O/data_check.txt || fail data "l2live nomask differs"
$P $CMP artifacts/clf/mimic/episodes31_m.pkl artifacts/clf/mimic/episodes31_m_nomask.pkl >> $O/data_check.txt || fail data "twin nomask differs"
$P - <<PY || fail data "assemble extra nomask"
import pickle
parts = ["artifacts/clf/mimic/episodes31_l2live_m_nomask.pkl", "$O/episodes31_live2_m_nomask.pkl", "$O/episodes31_live4_m_nomask.pkl"]
ref = pickle.load(open("$V/extra_l2_live124_m.pkl", "rb"))
eps = [e for f in parts for e in pickle.load(open(f, "rb"))["episodes"]]
k = lambda e: (e["run"], e["phase"], e["supi"])
assert [k(e) for e in eps] == [k(e) for e in ref["episodes"]], "episode order differs from the training extra"
pickle.dump(dict(names=ref["names"], groups=ref["groups"], protocol=ref["protocol"], episodes=eps), open("$O/extra_l2_live124_m_nomask.pkl", "wb"))
print("extra nomask", len(eps))
PY
EP_NOMASK=1 EP_MIMIC=1 EP_MIMIC_POOL=all EP_GATE=run $P scripts/ml/clf_features.py $L/rows.parquet $L/episodes31_live5_mall_nomask.pkl > $O/data_live5.log 2>&1 || fail data "live5 rc=$?"
$P $CMP $L/episodes31_live5_mall.pkl $L/episodes31_live5_mall_nomask.pkl >> $O/data_check.txt || fail data "live5 nomask differs"
st data ok

# 2. training: 3 seeds in parallel per configuration, configurations one after the other
C="--model xgb --grid --l3 all --groups $V/run_groups_v5.json --split $V/split_v5.json --threads 5 --save-model --active-labels"
train() {  # name features data
  local n=$1 f=$2 d=$3 pids=()
  st train_$n running
  for s in 0 1 2; do
    ( $P scripts/ml/train_clf.py $C --features $f --data ${d%%,*} --extra ${d#*,} --seed $s --out $O/$n/fold9_seed$s > $O/train_${n}_s$s.log 2>&1 ) & pids+=($!)
  done
  for p in "${pids[@]}"; do wait $p || fail train_$n "a seed failed (see $O/train_${n}_s*.log)"; done
  for s in 0 1 2; do [ -s $O/$n/fold9_seed$s/model.json ] && [ -s $O/$n/fold9_seed$s/scores.pkl ] || fail train_$n "seed $s: model or scores missing"; done
  st train_$n "ok $(grep -h '^done' $O/train_${n}_s*.log | awk '{print $NF}' | paste -sd/) s"
}
train R090_core f15c_core $DM
train R091_nogate f15c_nogate $DM
train R092_nogate_nomask f15c_nogate $DN

# 3. rules, chosen exactly as for the deployed model (ensemble out-of-fold, fixed candidates, budgets 2 and 0.5 on all and on live)
st rules running
for n in R090_core:f15c_core:$DM R091_nogate:f15c_nogate:$DM R092_nogate_nomask:f15c_nogate:$DN; do
  IFS=: read -r name fs data <<< "$n"
  $P -c "import json,sys; sys.path.insert(0,'scripts/ml'); from baselines_feat import SUBSETS, X31_NAMES as N; json.dump(dict(name='$name', feature_set='$fs', features=[N[i] for i in SUBSETS['$fs']]), open('$O/$name.json','w'))" || fail rules "$name stub"
  $P scripts/ml/select_block_rule.py $O/$name $data $O/$name.json > $O/${name}_rules.txt 2>&1 || fail rules "$name rc=$?"
done
st rules ok

# 4. scores on the 30 live-test runs, every UE tampered offline (same scenarios and donors for every model)
st score running
$P scripts/ml/score_models_on.py $O/R090_core $L/episodes31_live5_mall.pkl xgb_f15c_core $O/R090_core_live5 > $O/score.log 2>&1 || fail score "R090 rc=$?"
$P scripts/ml/score_models_on.py $O/R091_nogate $L/episodes31_live5_mall.pkl xgb_f15c_nogate $O/R091_nogate_live5 >> $O/score.log 2>&1 || fail score "R091 rc=$?"
$P scripts/ml/score_models_on.py $O/R092_nogate_nomask $L/episodes31_live5_mall_nomask.pkl xgb_f15c_nogate $O/R092_nogate_nomask_live5 >> $O/score.log 2>&1 || fail score "R092 rc=$?"
st score ok

# 5. evaluation
st eval running
$P scripts/ml/ablation_eval.py > research/clf/ABL_eval.txt 2> $O/eval.err || fail eval "ablation_eval rc=$?"
DL=$DM,$L/episodes31_live5_mall.pkl
{ $P scripts/ml/live_by_case.py $DL research/datasets/oran_flooding_live5/manifest/design.json \
    deployed=$L/V5_live5_mall core=$O/R090_core_live5 nogate=$O/R091_nogate_live5 nogate_nomask=$O/R092_nogate_nomask_live5; } \
  > research/clf/ABL_by_case.txt 2>> $O/eval.err || fail eval "live_by_case rc=$?"
st eval ok
