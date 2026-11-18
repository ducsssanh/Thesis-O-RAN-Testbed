#!/usr/bin/env bash
# Train on episodes with the mimic scenario + run-level gate: R060 cross-domain (as R050: xgb f15, L3 in training, 3 seeds) and
# B3m KPM-only (fkpm, unmasked KPM), same split (train = final training runs; test = clean test + live runs). Then per-scenario
# evaluation on the clean test and on the live runs. Status per job in artifacts/clf/jobs/mtrain_*.status.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; O=artifacts/clf/mimic; J=artifacts/clf/jobs
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
$P - <<'PY'
import json, pickle
f = json.load(open("artifacts/clf/split_final.json")); l = json.load(open("artifacts/clf/live/split_live.json"))
json.dump({"train": f["train"], "test": f["test"] + l["test"]}, open("artifacts/clf/mimic/split_both.json", "w"))
for v in ("m", "m_nomask"):
    A = pickle.load(open("artifacts/clf/mimic/episodes31_l2_%s.pkl" % v, "rb")); B = pickle.load(open("artifacts/clf/mimic/episodes31_live_%s.pkl" % v, "rb"))
    A["episodes"] += B["episodes"]; pickle.dump(A, open("artifacts/clf/mimic/episodes31_l2live_%s.pkl" % v, "wb"))
PY
S=$O/split_both.json; G=artifacts/clf/live/run_groups_live.json
for s in 0 1 2; do
  job mtrain_r060_s$s "$P scripts/ml/train_clf.py --model xgb --features f15 --grid --l3 all --data $O/episodes31_m.pkl --extra $O/episodes31_l2live_m.pkl --groups $G --split $S --seed $s --threads 3 --save-model --out $O/R060/fold9_seed$s" &
  job mtrain_b3m_s$s "$P scripts/ml/train_clf.py --model xgb --features fkpm --grid --l3 all --data $O/episodes31_m_nomask.pkl --extra $O/episodes31_l2live_m_nomask.pkl --groups $G --split $S --seed $s --threads 3 --out $O/B3m/fold9_seed$s" &
done
wait
grep -q FAILED $J/mtrain_*.status && { grep -H . $J/mtrain_*.status; exit 1; }
DM=$O/episodes31_m.pkl,$O/episodes31_l2_m.pkl,$O/episodes31_live_m.pkl
DN=$O/episodes31_m_nomask.pkl,$O/episodes31_l2_m_nomask.pkl,$O/episodes31_live_m_nomask.pkl
for T in l2c live; do
  job meval_r060_$T "$P scripts/ml/eval_by_scen.py --data $DM --runs $T R060_crossdomain=$O/R060 > research/clf/MIMIC_eval_R060_$T.txt" &
  job meval_b3m_$T "$P scripts/ml/eval_by_scen.py --data $DN --runs $T B3m_kpm_only=$O/B3m > research/clf/MIMIC_eval_B3m_$T.txt" &
done
wait
grep -H . $J/mtrain_*.status $J/meval_*.status
