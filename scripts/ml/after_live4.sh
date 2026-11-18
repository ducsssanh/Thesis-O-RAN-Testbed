#!/usr/bin/env bash
# Analysis of the live v2 campaign (mimic). Status per job in artifacts/clf/jobs/l4_*.status.
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; M=research/datasets/oran_flooding_live4/manifest; L=artifacts/clf/live4; O=artifacts/clf/mimic; J=artifacts/clf/jobs
mkdir -p $L $J
job() { local n=$1; shift; ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status; }
RUNS=$($P -c "import json; k={}
for l in open('$M/campaign_log.jsonl'):
    x=json.loads(l)
    if x['event']=='kept': k[x['id']]=x['run']
print(' '.join(k[i] for i in sorted(k)))")
job l4_report "$P scripts/ml/live_report.py $M research/clf/LIVE4_detection.txt --json research/clf/LIVE4_detection.json" &
job l4_parity "CLF_MODEL=$O/export_e3/clf_model.json $P scripts/ml/live_parity.py $O/R072_E3 $RUNS > research/clf/LIVE4_parity.txt" &
# rebuild the live runs offline (honest scenario = the live traffic incl. its live tamper), masked and unmasked
job l4_rows "$P scripts/ml/build_dataset_twin.py --out $L $RUNS && EP_GATE=run $P scripts/ml/clf_features.py $L/rows.parquet $L/episodes31_live4.pkl && EP_NOMASK=1 EP_GATE=run $P scripts/ml/clf_features.py $L/rows.parquet $L/episodes31_live4_nomask.pkl"
wait
grep -q FAILED $J/l4_*.status && { grep -H . $J/l4_*.status; exit 1; }
# offline scores on the live v2 runs: R060 (cross-domain), B3m (KPM only), baselines B1/B2/B4, using the models already trained
$P - <<PY
import json
f = json.load(open("artifacts/clf/split_final.json"))
ids = ["/".join(__import__("pathlib").Path(r).parts[-4:]) for r in "$RUNS".split()]
json.dump({"train": f["train"], "test": ids}, open("$L/split_live4.json", "w"))
g = json.load(open("artifacts/clf/live/run_groups_live.json")); g.update({r: "live4:" + r for r in ids}); json.dump(g, open("$L/run_groups_live4.json", "w"))
PY
[ -d $O/B3m_saved ] || echo "missing B3m_saved" 
job l4_score "$P scripts/ml/score_models_on.py $O/R072_E3 $L/episodes31_live4.pkl xgb_f15c $L/E3_live4 && $P scripts/ml/score_models_on.py $O/B3m_saved $L/episodes31_live4_nomask.pkl xgb_fkpm $L/B3m_live4" &
job l4_base "$P scripts/ml/baselines.py --data artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl,$L/episodes31_live4.pkl --split $L/split_live4.json --groups $L/run_groups_live4.json --out $L/base" &
wait
grep -q FAILED $J/l4_*.status && { grep -H . $J/l4_*.status; exit 1; }
DM=$O/episodes31_m.pkl,$O/episodes31_l2_m.pkl,$L/episodes31_live4.pkl
DN=$O/episodes31_m_nomask.pkl,$O/episodes31_l2_m_nomask.pkl,$L/episodes31_live4_nomask.pkl
DB=artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl,$L/episodes31_live4.pkl
job l4_eval "$P scripts/ml/live_by_case.py $DM $M/design.json E3=$L/E3_live4 > research/clf/LIVE4_by_case.txt && $P scripts/ml/live_by_case.py $DN $M/design.json B3m_kpm=$L/B3m_live4 | tail -n +2 >> research/clf/LIVE4_by_case.txt && $P scripts/ml/live_by_case.py $DB $M/design.json B1rate=$L/base/B_rate B2ewma=$L/base/B_ewma B2cusum=$L/base/B_cusum B4iforest=$L/base/B_iforest | tail -n +2 >> research/clf/LIVE4_by_case.txt"
grep -H . $J/l4_*.status
# step 3d: block rules on the live v3 scores (paired with live v2) + step 2 metrics
job l4_rules "$P scripts/ml/eval_block_rules.py --data $O/episodes31_m.pkl,$O/episodes31_l2_m.pkl,$L/episodes31_live4.pkl live4=$L/E3_live4:flood-live-ly > research/clf/BLOCK_rules_live4.txt"
grep -H . $J/l4_*.status
