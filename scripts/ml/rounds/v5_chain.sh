#!/usr/bin/env bash
# Unattended round v5 (2026-11-10): wait for the round-v5 training, export the ensemble, choose the block rule on out-of-fold
# scores, C parity (logit and block decisions), upstream check, build and roll out the xApp, run the blind live v5
# campaign with the futility stop, then the analysis. Every step writes artifacts/clf/jobs/v5chain_<step>.status and the chain
# stops at the first failure ("FAILED ..."), so nothing later runs on a broken step.
cd "$(dirname "$0")/../../.."
P=.venv-ml/bin/python; V=artifacts/clf/v5; J=artifacts/clf/jobs
M=src/xapp; M5=research/datasets/oran_flooding_live5/manifest
st() { echo "$2" > $J/v5chain_$1.status; }
fail() { st $1 "FAILED $2"; exit 1; }
DATA=artifacts/clf/mimic/episodes31_m.pkl,$V/extra_l2_live124_m.pkl

# 0. training
st train running
while kill -0 "$(cat $J/v5_train.pid)" 2>/dev/null; do sleep 30; done
for s in 0 1 2; do
  [ "$(cat $J/v5_train_s$s.status)" = ok ] || fail train "seed $s: $(cat $J/v5_train_s$s.status)"
  [ -s $V/R080_v5/fold9_seed$s/model.json ] && [ -s $V/R080_v5/fold9_seed$s/scores.pkl ] || fail train "seed $s: model or scores missing"
done
st train ok

# 1. export (rate limit among thr/k23/k35 at 2 per UE-hour) and block rule (fixed candidate list, out-of-fold only)
st export running; mkdir -p $V/export_v5
$P scripts/ml/export_clf.py $V/R080_v5 $DATA $V/export_v5/clf_model.json $V/export_v5/parity.csv > $V/export_v5/export.log 2>&1 || fail export "export_clf rc=$?"
$P scripts/ml/select_block_rule.py $V/R080_v5 $DATA $V/export_v5/clf_model.json > $V/export_v5/block_rule.txt 2>&1 || fail export "select_block_rule rc=$?"
RULE=$($P -c "import json; print(json.load(open('$V/export_v5/clf_model.json'))['block']['rule'])")
st export "ok block $RULE, soft $($P -c "import json; print(json.load(open('$V/export_v5/clf_model.json'))['soft']['rule'])")"

# 2. C parity on 40 random episodes: logit |dz| < 1e-3 and identical block decisions
st parity running
$P scripts/ml/clf_parity_seq.py $V/R080_v5 $DATA $V/export_v5/seq.csv 40 > $V/export_v5/seq.log 2>&1 || fail parity "clf_parity_seq rc=$?"
docker run --rm --user "$(id -u):$(id -g)" -v $PWD/$M:/m:ro -v $PWD/tests/xapp:/t:ro -v $PWD/$V/export_v5:/e oai-lab-xapp:46d65c45ded37272 \
  sh -c 'gcc -O2 -I/m /t/test_clf_parity.c /m/clf_xgb.c -ljson-c -lm -o /tmp/p && BLOCK_OUT=/e/seq_block_c.txt /tmp/p /e/clf_model.json /e/seq.csv' \
  > $V/export_v5/parity_c.txt 2>&1 || fail parity "C test rc=$? ($(tail -1 $V/export_v5/parity_c.txt))"
$P scripts/ml/clf_block_expected.py $V/export_v5/clf_model.json $V/export_v5/seq.csv $V/export_v5/seq_block_expected.txt >> $V/export_v5/parity_c.txt 2>&1 || fail parity "expected rc=$?"
[ "$(wc -l < $V/export_v5/seq_block_c.txt)" -eq "$(wc -l < $V/export_v5/seq_block_expected.txt)" ] || fail parity "row counts differ"
ND=$(paste $V/export_v5/seq_block_c.txt $V/export_v5/seq_block_expected.txt | awk '$1!=$2' | wc -l)
[ "$ND" -eq 0 ] || fail parity "block decisions differ in $ND rows"
st parity "ok $(grep '^rows' $V/export_v5/parity_c.txt)"

# 3. xApp sources (src/xapp) into the rebuilt FlexRIC tree, then the upstream check (every MATCH, no DIFF, no patch failure)
st patch running
cp src/xapp/*.[ch] src/flexric/examples/xApp/c/monitor/
timeout 1800 bash scripts/verify-oai-upstream.sh > $V/verify.log 2>&1
NM=$(grep -c "^MATCH" $V/verify.log); ND=$(grep -c -E "^DIFF|patch failed" $V/verify.log)
[ "$NM" -ge 5 ] && [ "$ND" -eq 0 ] || fail patch "MATCH $NM, DIFF/failed $ND (see $V/verify.log)"
st patch "ok MATCH $NM"

# 4. build the xApp image with the new model and check the model inside the image
st build running
cp $V/export_v5/clf_model.json deploy/k8s/images/models/clf_model.json
timeout 5400 $P scripts/k8s/staged.py build-xapp > artifacts/clf/build_xapp_v5.log 2>&1 || fail build "build rc=$?"
IMG=$(grep -o "Built oai-lab-xapp:[0-9a-f]*" artifacts/clf/build_xapp_v5.log | tail -1 | awk '{print $2}')
[ -n "$IMG" ] || fail build "no image tag in the build log"
IR=$(docker run --rm --entrypoint cat $IMG /opt/oai/models/clf_model.json | $P -c "import json,sys; m=json.load(sys.stdin); print(m['block']['rule'], len(m['features']))")
[ "$IR" = "$RULE 31" ] || fail build "model in image: '$IR', expected '$RULE 31'"
st build "ok $IMG"

# 5. roll out, then free disk (image tarballs in the minikube node and host cache, build cache)
st rollout running
timeout 900 $P scripts/k8s/staged.py rollout xapp $IMG > artifacts/clf/rollout_v5.log 2>&1 || fail rollout "rollout rc=$?"
sleep 20
kubectl --context oai-lab -n near-rt-ric get pods --no-headers | grep -q "oai-lab-xapp.*Running" || fail rollout "xApp pod not running"
CUR=$(kubectl --context oai-lab -n near-rt-ric get deploy -o jsonpath='{range .items[*]}{.spec.template.spec.containers[*].image}{"\n"}{end}' | grep -o "oai-lab-xapp:[0-9a-f]*" | head -1)
[ "$CUR" = "$IMG" ] || fail rollout "deployed image '$CUR', expected '$IMG'"
minikube -p oai-lab ssh -- 'sudo rm -f /var/lib/minikube/images/*' >/dev/null 2>&1; rm -rf ~/.minikube/cache/images/*
docker buildx prune -a -f >/dev/null 2>&1
st rollout "ok $IMG, $(df -h / | tail -1 | awk '{print $4}') free"

# 6. blind live v5 campaign with the futility stop (block or rate limit: upper 95 % CI bound < 90 % at 10 / 20 kept runs)
sleep 30
CAMPAIGN_MIN_FREE_GB=3 systemd-inhibit --what=sleep:idle:handle-lid-switch --who=campaign --why="live5 campaign" $P scripts/k8s/exp/v4traffic/campaign_twin.py --manifest $M5 --lo 0 --hi 30 > artifacts/clf/campaign_live5.log 2>&1 &
echo $! > artifacts/clf/campaign_live5.pid; st campaign "running $(date +%H:%M)"
FUT_OUT=research/clf/LIVE5_futility.log bash scripts/ml/rounds/live_futility.sh $M5 artifacts/clf/campaign_live5.pid &
wait "$(cat artifacts/clf/campaign_live5.pid)"
K=$(grep -c '"event": "kept"' $M5/campaign_log.jsonl)
st campaign "ended $(date +%H:%M), kept $K"

# 7. analysis
st analysis running
bash scripts/ml/rounds/after_live5.sh > artifacts/clf/after_live5.log 2>&1
grep -q FAILED $J/l5_*.status && fail analysis "$(grep -H FAILED $J/l5_*.status | tr '\n' ' ')"
[ -s research/clf/LIVE5_detection.txt ] || fail analysis "no LIVE5_detection.txt"
st analysis ok
