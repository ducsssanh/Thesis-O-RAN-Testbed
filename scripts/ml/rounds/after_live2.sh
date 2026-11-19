#!/usr/bin/env bash
# Analysis of the live v2 campaign (mimic). Status per job in artifacts/clf/jobs/l2_*.status.
cd "$(dirname "$0")/../../.."
P=.venv-ml/bin/python; M=research/datasets/oran_flooding_live2/manifest; L=artifacts/clf/live2; O=artifacts/clf/mimic; J=artifacts/clf/jobs
mkdir -p $L $J
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
RUNS=$($P -c "import json; k={}
for l in open('$M/campaign_log.jsonl'):
    x=json.loads(l)
    if x['event']=='kept': k[x['id']]=x['run']
print(' '.join(k[i] for i in sorted(k)))")
job l2_report "$P scripts/ml/live_report.py $M research/clf/LIVE2_detection.txt --json research/clf/LIVE2_detection.json" &
job l2_parity "CLF_MODEL=$O/export/clf_model.json $P scripts/ml/live_parity.py $O/R060 $RUNS > research/clf/LIVE2_parity.txt" &
# rebuild the live runs offline (honest scenario = the live traffic incl. its live tamper), masked and unmasked
job l2_rows "$P scripts/ml/build_dataset_twin.py --out $L $RUNS && EP_GATE=run $P scripts/ml/clf_features.py $L/rows.parquet $L/episodes31_live2.pkl && EP_NOMASK=1 EP_GATE=run $P scripts/ml/clf_features.py $L/rows.parquet $L/episodes31_live2_nomask.pkl"
wait
grep -q FAILED $J/l2_*.status && { grep -H . $J/l2_*.status; exit 1; }
# offline scores on the live v2 runs: R060 (cross-domain), B3m (KPM only), baselines B1/B2/B4, using the models already trained
$P - <<PY
import json
f = json.load(open("artifacts/clf/split_final.json"))
ids = ["/".join(__import__("pathlib").Path(r).parts[-4:]) for r in "$RUNS".split()]
json.dump({"train": f["train"], "test": ids}, open("$L/split_live2.json", "w"))
g = json.load(open("artifacts/clf/live/run_groups_live.json")); g.update({r: "live2:" + r for r in ids}); json.dump(g, open("$L/run_groups_live2.json", "w"))
PY
job l2_b3save "for s in 0 1 2; do $P scripts/ml/train_clf.py --model xgb --features fkpm --grid --l3 all --data $O/episodes31_m_nomask.pkl --extra $O/episodes31_l2live_m_nomask.pkl --groups artifacts/clf/live/run_groups_live.json --split $O/split_both.json --seed \$s --threads 4 --save-model --out $O/B3m_saved/fold9_seed\$s; done"
job l2_score "$P scripts/ml/score_models_on.py $O/R060 $L/episodes31_live2.pkl xgb_f15 $L/R060_live2 && $P scripts/ml/score_models_on.py $O/B3m_saved $L/episodes31_live2_nomask.pkl xgb_fkpm $L/B3m_live2" &
job l2_base "$P scripts/ml/baselines.py --data artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl,$L/episodes31_live2.pkl --split $L/split_live2.json --groups $L/run_groups_live2.json --out $L/base" &
wait
grep -q FAILED $J/l2_*.status && { grep -H . $J/l2_*.status; exit 1; }
DM=$O/episodes31_m.pkl,$O/episodes31_l2_m.pkl,$L/episodes31_live2.pkl
DN=$O/episodes31_m_nomask.pkl,$O/episodes31_l2_m_nomask.pkl,$L/episodes31_live2_nomask.pkl
DB=artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl,$L/episodes31_live2.pkl
job l2_eval "$P scripts/ml/live_by_case.py $DM $M/design.json R060=$L/R060_live2 > research/clf/LIVE2_by_case.txt && $P scripts/ml/live_by_case.py $DN $M/design.json B3m_kpm=$L/B3m_live2 | tail -n +2 >> research/clf/LIVE2_by_case.txt && $P scripts/ml/live_by_case.py $DB $M/design.json B1rate=$L/base/B_rate B2ewma=$L/base/B_ewma B2cusum=$L/base/B_cusum B4iforest=$L/base/B_iforest | tail -n +2 >> research/clf/LIVE2_by_case.txt"
grep -H . $J/l2_*.status
