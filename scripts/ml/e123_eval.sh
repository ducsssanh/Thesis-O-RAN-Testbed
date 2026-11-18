#!/usr/bin/env bash
# Evaluate R060 (reference), R070 (E1), R071 (E2), R072 (E3): out-of-fold block rules, clean test, live 1 (in the scores), live v2
# (scored on the rebuilt live v2 episodes). Status in artifacts/clf/jobs/e123eval_*.status.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; O=artifacts/clf/mimic; L2=artifacts/clf/live2; J=artifacts/clf/jobs; OUT=research/clf/E123
mkdir -p $OUT
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
D=$O/episodes31_m.pkl,$O/episodes31_l2_m.pkl,$O/episodes31_live_m.pkl,$L2/episodes31_live2.pkl
for m in R060:f15 R070_E1:f15 R071_E2:f15c R072_E3:f15c; do
  n=${m%%:*}; k=${m##*:}
  job e123eval_$n "$P scripts/ml/score_models_on.py $O/$n $L2/episodes31_live2.pkl xgb_$k $L2/${n}_live2 && \
    RULES=k2030,a1020,a1220 $P scripts/ml/eval_block_rules.py --data $D --scen honest clean=$O/$n:l2c live1=$O/$n:flood-live-lv live2=$L2/${n}_live2:flood-live-lw > $OUT/${n}_block.txt && \
    $P scripts/ml/eval_by_scen.py --data $D --runs l2c --scen honest,mimic $n=$O/$n > $OUT/${n}_clean_scen.txt && \
    $P scripts/ml/eval_by_scen.py --data $D --runs flood-live-lw --scen honest $n=$L2/${n}_live2 > $OUT/${n}_live2_rate.txt" &
  job e123oof_$n "RULES=k2030,a1020,a1220 MODEL_DIR=$O/$n $P ${JOB_TMP:-/tmp}/oof_rules_dir.py > $OUT/${n}_oof.txt" &
done
wait
grep -H . $J/e123eval_*.status $J/e123oof_*.status
