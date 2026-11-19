#!/usr/bin/env bash
# Parallel version of after_live.sh (steps 2-6). Every job writes artifacts/clf/jobs/<name>.status = "running" | "ok" | "FAILED rc=N"
# and its own log, so a failure is visible at once (no pgrep watching). Usage: after_live_par.sh
cd "$(dirname "$0")/../../.."
P=.venv-ml/bin/python; M=research/datasets/oran_flooding_live/manifest; L=artifacts/clf/live; J=artifacts/clf/jobs
mkdir -p $J research/clf
D=artifacts/clf/episodes31.pkl,artifacts/clf/episodes31_l2.pkl
job() {  # name, then a shell snippet
  local n=$1; shift
  ( echo running > $J/$n.status; set -e; eval "$@" ) > $J/$n.log 2>&1 && echo ok > $J/$n.status || echo "FAILED rc=$?" > $J/$n.status
}
rep() { $P scripts/ml/report_clf.py "$1" "$2" --data "$3" --test --boot 300 > "$4_soft.txt" 2>&1 && \
        $P scripts/ml/report_clf.py "$1" "$2" --data "$3" --long --rule k2030 --test --boot 300 > "$4_block.txt" 2>&1; }

prep() {
  [ -s $L/episodes31_live_nomask.pkl ] || $P scripts/ml/live_episodes.py $M $L
  [ -s $L/episodes31_nomask.pkl ] || EP_NOMASK=1 $P scripts/ml/clf_features.py research/datasets/oran_flooding_twin/rows.parquet $L/episodes31_nomask.pkl
  [ -s $L/episodes31_l2_nomask.pkl ] || EP_NOMASK=1 $P scripts/ml/clf_features.py research/datasets/oran_flooding_twin_l2/rows.parquet $L/episodes31_l2_nomask.pkl
  $P - <<PY
import pickle
E=pickle.load(open("$L/episodes31_l2_nomask.pkl","rb")); F=pickle.load(open("$L/episodes31_live_nomask.pkl","rb"))
E["episodes"]=E["episodes"]+F["episodes"]; pickle.dump(E,open("$L/episodes31_l2live_nomask.pkl","wb"))
PY
}
job prep prep || true
[ "$(cat $J/prep.status)" = ok ] || { echo "prep failed, see $J/prep.log"; exit 1; }

job r050_live "$P scripts/ml/score_ens.py artifacts/clf/R050_final_m $L/episodes31_live.pkl $L/R050_ens_live && rep 'R050 ensemble offline on live runs' $L/R050_ens_live $D,$L/episodes31_live.pkl research/clf/LIVE_R050_offline" &
for T in clean live; do
  if [ $T = clean ]; then S=artifacts/clf/split_final.json; G=artifacts/clf/run_groups_all.json; DD=$D
  else S=$L/split_live.json; G=$L/run_groups_live.json; DD=$D,$L/episodes31_live.pkl; fi
  job base_$T "$P scripts/ml/baselines.py --data $DD --split $S --groups $G --out $L/base_$T && for b in rate ewma cusum iforest; do rep \"B \$b on $T\" $L/base_$T/B_\$b $DD research/clf/BASE_\${b}_$T; done" &
  if [ $T = clean ]; then X=$L/episodes31_l2_nomask.pkl; DN=$L/episodes31_nomask.pkl,$L/episodes31_l2_nomask.pkl
  else X=$L/episodes31_l2live_nomask.pkl; DN=$L/episodes31_nomask.pkl,$L/episodes31_l2_nomask.pkl,$L/episodes31_live_nomask.pkl; fi
  job b3_$T "for s in 0 1 2; do $P scripts/ml/train_clf.py --model xgb --features fkpm --grid --l3 all --data $L/episodes31_nomask.pkl --extra $X --groups $G --split $S --seed \$s --threads 3 --out $L/B3_kpm_$T/fold9_seed\$s; done && rep 'B3 KPM only on $T' $L/B3_kpm_$T $DN research/clf/BASE_kpm_$T" &
done
for w in 3 5 30; do
  job x2_w$w "for s in 0 1 2; do for f in 0 1 2 3 4; do $P scripts/ml/train_clf.py --model xgb --features f15 --win $w --grid --l3 all --fold \$f --seed \$s --threads 2 --out artifacts/clf/X2_w$w/fold\${f}_seed\$s; done; done && $P scripts/ml/report_clf.py 'X2 window $w s' artifacts/clf/X2_w$w --boot 300 > research/clf/X2_w$w.txt 2>&1" &
done
job x34 "cd research/twinning && ../../$P madrid_history_scope.py > ../../research/clf/X34_madrid_history_scope.txt" &
wait
grep -H . $J/*.status
