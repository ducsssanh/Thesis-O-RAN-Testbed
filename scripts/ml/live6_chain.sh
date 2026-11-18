#!/usr/bin/env bash
# Advisor step 4 (2026-11-10): benign-only live runs, 84 x 6 phases (~21 UE-hours), same format as the benign-only runs of the live
# test, deployed model unchanged. Waits for the ablation chain (no training during a campaign), checks the model inside the xApp,
# runs the campaign, then the analysis (pre-registered criteria in the logbook). Status: artifacts/clf/jobs/l6_<step>.status.
cd "$(dirname "$0")/../.."
R=$PWD; P=$R/.venv-ml/bin/python; J=artifacts/clf/jobs; M6=research/datasets/oran_flooding_live6/manifest; L6=artifacts/clf/live6; O=artifacts/clf/abl
st() { echo "$2" > $J/l6_$1.status; }
fail() { st $1 "FAILED $2"; exit 1; }

# 0. the ablation chain must have ended cleanly (it trains; nothing may train during the campaign)
st wait running
while kill -0 "$(cat $J/abl_chain.pid)" 2>/dev/null; do sleep 30; done
[ "$(cat $J/abl_eval.status 2>/dev/null)" = ok ] || fail wait "ablation chain did not end ok: $(bash -c "grep -H . $J/abl_*.status" | tr '\n' ' ')"
st wait ok

# 1. pre-flight: design (fixed seed), model inside the running xApp = the deployed export, disk
st preflight running
mkdir -p $M6
[ -s $M6/design.json ] || (cd scripts/k8s/exp/v4traffic && $P design_twin.py --live6 --seed 20261111 --runs 84 --out $R/$M6/design.json) || fail preflight "design"
N=$($P -c "import json; print(len(json.load(open('$M6/design.json'))['runs']))"); [ "$N" = 84 ] || fail preflight "design has $N runs"
IR=$(kubectl --context oai-lab -n near-rt-ric exec deploy/oai-lab-xapp -c xapp -- cat /opt/oai/models/clf_model.json | $P -c "import json,sys; m=json.load(sys.stdin); print(m['name'], m['soft']['rule'], m['soft']['threshold'], m['block']['rule'], m['block']['threshold'])")
EX=$($P -c "import json; m=json.load(open('artifacts/clf/v5/export_v5/clf_model.json')); print(m['name'], m['soft']['rule'], m['soft']['threshold'], m['block']['rule'], m['block']['threshold'])")
[ -n "$IR" ] && [ "$IR" = "$EX" ] || fail preflight "xApp model '$IR' differs from the export '$EX'"
st preflight "ok model $EX; $(df -h / | tail -1 | awk '{print $4}') free"

# 2. campaign
CAMPAIGN_MIN_FREE_GB=3 systemd-inhibit --what=sleep:idle:handle-lid-switch --who=campaign --why="live6 benign campaign" \
  $P scripts/k8s/exp/v4traffic/campaign_twin.py --manifest $M6 --lo 0 --hi 84 > artifacts/clf/campaign_live6.log 2>&1 &
echo $! > artifacts/clf/campaign_live6.pid; st campaign "running since $(date +%H:%M)"
wait "$(cat artifacts/clf/campaign_live6.pid)"; rc=$?
K=$(grep -c '"event": "kept"' $M6/campaign_log.jsonl 2>/dev/null || echo 0)
st campaign "ended $(date +%H:%M) rc=$rc, kept $K/84"
[ "$K" -ge 1 ] || fail campaign "no run kept (rc=$rc)"

# 3. analysis: live decisions (pooled with the live test), then offline replay of every model, KPM as recorded and tampered
st analysis running
RUNS=$($P -c "import json; k={}
for l in open('$M6/campaign_log.jsonl'):
    x=json.loads(l)
    if x['event']=='kept': k[x['id']]=x['run']
print(' '.join(k[i] for i in sorted(k)))")
$P scripts/ml/live_benign_fa.py research/datasets/oran_flooding_live5/manifest $M6 > research/clf/LIVE6_benign_fa.txt 2>&1 || fail analysis "live_benign_fa rc=$?"
mkdir -p $L6
$P scripts/ml/build_dataset_twin.py --out $L6 $RUNS > $L6/build.log 2>&1 || fail analysis "build_dataset_twin rc=$?"
EP_MIMIC=1 EP_MIMIC_POOL=all EP_GATE=run $P scripts/ml/clf_features.py $L6/rows.parquet $L6/episodes31_live6_mall.pkl > $L6/episodes.log 2>&1 || fail analysis "episodes rc=$?"
EP_NOMASK=1 EP_MIMIC=1 EP_MIMIC_POOL=all EP_GATE=run $P scripts/ml/clf_features.py $L6/rows.parquet $L6/episodes31_live6_mall_nomask.pkl >> $L6/episodes.log 2>&1 || fail analysis "episodes nomask rc=$?"
$P scripts/ml/score_models_on.py artifacts/clf/v5/R080_v5 $L6/episodes31_live6_mall.pkl xgb_f15c $L6/V5_live6_mall > $L6/score.log 2>&1 || fail analysis "score deployed"
$P scripts/ml/score_models_on.py $O/R090_core $L6/episodes31_live6_mall.pkl xgb_f15c_core $O/R090_core_live6 >> $L6/score.log 2>&1 || fail analysis "score core"
$P scripts/ml/score_models_on.py $O/R091_nogate $L6/episodes31_live6_mall.pkl xgb_f15c_nogate $O/R091_nogate_live6 >> $L6/score.log 2>&1 || fail analysis "score nogate"
$P scripts/ml/score_models_on.py $O/R092_nogate_nomask $L6/episodes31_live6_mall_nomask.pkl xgb_f15c_nogate $O/R092_nogate_nomask_live6 >> $L6/score.log 2>&1 || fail analysis "score nogate nomask"
$P scripts/ml/abl_benign_fa.py live5=artifacts/clf/live5/episodes31_live5_mall.pkl:live5 live6=$L6/episodes31_live6_mall.pkl:live6 \
  > research/clf/LIVE6_abl_benign_fa.txt 2> $L6/abl_benign_fa.err || fail analysis "abl_benign_fa rc=$?"
st analysis ok
