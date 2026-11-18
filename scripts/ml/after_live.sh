#!/usr/bin/env bash
# Plan steps 3, 3b, 3c after the live detection campaign (no testbed use; run only when no campaign is running).
# Outputs: research/clf/LIVE_*.txt, research/clf/BASE_*.txt, research/clf/X2_*.txt; working data in artifacts/clf/live/.
set -eu
cd "$(dirname "$0")/../.."
P=.venv-ml/bin/python; M=research/datasets/oran_flooding_live/manifest; L=artifacts/clf/live; mkdir -p $L research/clf
RUNS=$($P -c "import json; k={}
for l in open('$M/campaign_log.jsonl'):
    x=json.loads(l)
    if x['event']=='kept': k[x['id']]=x['run']
print(' '.join(k[i] for i in sorted(k)))")
# 1. live report (whole xApp) and live/offline parity
[ -s research/clf/LIVE_detection.txt ] || $P scripts/ml/live_report.py $M research/clf/LIVE_detection.txt --json research/clf/LIVE_detection.json
[ -s research/clf/LIVE_parity.txt ] || $P scripts/ml/live_parity.py artifacts/clf/R050_final_m $RUNS > research/clf/LIVE_parity.txt 2>&1
# 2. live runs as dataset episodes; offline R050 ensemble on them
[ -s $L/episodes31_live_nomask.pkl ] || $P scripts/ml/live_episodes.py $M $L
D=artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl
$P scripts/ml/score_ens.py artifacts/clf/R050_final_m $L/episodes31_live.pkl $L/R050_ens_live
$P scripts/ml/report_clf.py "R050 ensemble offline on live runs, soft" $L/R050_ens_live --data $D,$L/episodes31_live.pkl --test --boot 300 > research/clf/LIVE_R050_offline_soft.txt 2>&1
$P scripts/ml/report_clf.py "R050 ensemble offline on live runs, block" $L/R050_ens_live --data $D,$L/episodes31_live.pkl --long --rule k2030 --test --boot 300 > research/clf/LIVE_R050_offline_block.txt 2>&1
# 3. baselines B1, B2, B4 on the clean test and on the live runs
for T in clean live; do
  if [ $T = clean ]; then S=artifacts/clf/split_final.json; G=artifacts/clf/run_groups_all.json; DD=$D
  else S=$L/split_live.json; G=$L/run_groups_live.json; DD=$D,$L/episodes31_live.pkl; fi
  $P scripts/ml/baselines.py --data $DD --split $S --groups $G --out $L/base_$T
  for b in rate ewma cusum iforest; do
    $P scripts/ml/report_clf.py "B $b on $T, soft" $L/base_$T/B_$b --data $DD --test --boot 300 > research/clf/BASE_${b}_${T}_soft.txt 2>&1
    $P scripts/ml/report_clf.py "B $b on $T, block" $L/base_$T/B_$b --data $DD --long --rule k2030 --test --boot 300 > research/clf/BASE_${b}_${T}_block.txt 2>&1
  done
done
# 4. B3 KPM-only model (unmasked KPM), 3 seeds, clean test and live
EP_NOMASK=1 $P scripts/ml/clf_features.py research/datasets/oran_flooding_twin/rows.parquet $L/episodes31_nomask.pkl
EP_NOMASK=1 $P scripts/ml/clf_features.py research/datasets/oran_flooding_twin_l2/rows.parquet $L/episodes31_l2_nomask.pkl
for T in clean live; do
  if [ $T = clean ]; then S=artifacts/clf/split_final.json; G=artifacts/clf/run_groups_all.json; X=$L/episodes31_l2_nomask.pkl
  else S=$L/split_live.json; G=$L/run_groups_live.json; X=$L/episodes31_l2_nomask.pkl; fi
  for s in 0 1 2; do
    if [ $T = clean ]; then
      $P scripts/ml/train_clf.py --model xgb --features fkpm --grid --l3 all --data $L/episodes31_nomask.pkl --extra $X --groups $G --split $S --seed $s --threads 6 --out $L/B3_kpm_$T/fold9_seed$s
    else  # live episodes appended as a third source through a merged pickle
      $P - <<PY
import pickle
E=pickle.load(open("$L/episodes31_l2_nomask.pkl","rb")); F=pickle.load(open("$L/episodes31_live_nomask.pkl","rb"))
E["episodes"]=E["episodes"]+F["episodes"]; pickle.dump(E,open("$L/episodes31_l2live_nomask.pkl","wb"))
PY
      $P scripts/ml/train_clf.py --model xgb --features fkpm --grid --l3 all --data $L/episodes31_nomask.pkl --extra $L/episodes31_l2live_nomask.pkl --groups $G --split $S --seed $s --threads 6 --out $L/B3_kpm_$T/fold9_seed$s
    fi
  done
  DD=$L/episodes31_nomask.pkl,$L/episodes31_l2_nomask.pkl; [ $T = live ] && DD=$DD,$L/episodes31_live_nomask.pkl
  $P scripts/ml/report_clf.py "B3 KPM only on $T, soft" $L/B3_kpm_$T --data $DD --test --boot 300 > research/clf/BASE_kpm_${T}_soft.txt 2>&1
  $P scripts/ml/report_clf.py "B3 KPM only on $T, block" $L/B3_kpm_$T --data $DD --long --rule k2030 --test --boot 300 > research/clf/BASE_kpm_${T}_block.txt 2>&1
done
# 5. X2 window sweep (out-of-fold, 5 folds x 3 seeds, as R013 with L3 in training)
for w in 3 5 30; do
  for s in 0 1 2; do for f in 0 1 2 3 4; do
    $P scripts/ml/train_clf.py --model xgb --features f15 --win $w --grid --l3 all --fold $f --seed $s --threads 6 --out artifacts/clf/X2_w$w/fold${f}_seed$s
  done; done
  $P scripts/ml/report_clf.py "X2 window $w s" artifacts/clf/X2_w$w --boot 300 > research/clf/X2_w${w}.txt 2>&1
done
# 6. X3, X4: Madrid traces (session length, persistence by lag and band)
(cd research/twinning && ../../$P madrid_history_scope.py) > research/clf/X34_madrid_history_scope.txt 2>&1
echo after_live done
