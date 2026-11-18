#!/usr/bin/env bash
# E1 (active labels), E2 (UL-DL coupling features), E3 (both); R060 data and split. Status per job in artifacts/clf/jobs/e123_*.status.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; O=artifacts/clf/mimic; J=artifacts/clf/jobs
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
C="--model xgb --grid --l3 all --data $O/episodes31_m.pkl --extra $O/episodes31_l2live_m.pkl --groups artifacts/clf/live/run_groups_live.json --split $O/split_both.json --threads 2 --save-model"
for s in 0 1 2; do
  job e123_R070_s$s "$P scripts/ml/train_clf.py $C --features f15 --active-labels --seed $s --out $O/R070_E1/fold9_seed$s" &
  job e123_R071_s$s "$P scripts/ml/train_clf.py $C --features f15c --seed $s --out $O/R071_E2/fold9_seed$s" &
  job e123_R072_s$s "$P scripts/ml/train_clf.py $C --features f15c --active-labels --seed $s --out $O/R072_E3/fold9_seed$s" &
done
wait
grep -H . $J/e123_*.status
