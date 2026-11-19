#!/usr/bin/env bash
# Round v5 (2026-11-10): E3 configuration (f15c, active labels, L3 in train, mimic scenario, run-level gate) trained on the twin
# data + live 1, live v2, live v4 (attack runs; live v4 benign-only runs kept out as the mimic donor pool of live v5).
# Groups: runs sharing a Madrid window are one group (live v2 and live v4 replay the same windows). Status: artifacts/clf/jobs/v5_*.status
cd "$(dirname "$0")/../../.."
P=.venv-ml/bin/python; O=artifacts/clf/v5; J=artifacts/clf/jobs
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
C="--model xgb --grid --l3 all --data artifacts/clf/mimic/episodes31_m.pkl --extra $O/extra_l2_live124_m.pkl --groups $O/run_groups_v5.json --split $O/split_v5.json --threads 5 --save-model --features f15c --active-labels"
for s in 0 1 2; do
  job v5_train_s$s "$P scripts/ml/train_clf.py $C --seed $s --out $O/R080_v5/fold9_seed$s" &
done
wait
grep -H . $J/v5_train_s*.status
grep -q FAILED $J/v5_train_s*.status && exit 1 || exit 0
