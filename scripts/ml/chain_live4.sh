#!/usr/bin/env bash
# Unattended chain (2026-11-09): wait for the E3 image build, roll it out, free disk, run the live v4 campaign with the futility
# stop (block over L1-L3 >= 90 %), then the analysis. Every step writes artifacts/clf/jobs/chain4_<step>.status.
cd "$(dirname "$0")/../.."
J=artifacts/clf/jobs; P=.venv-ml/bin/python; M=research/datasets/oran_flooding_live4/manifest
st() { echo "$2" > $J/chain4_$1.status; }
while [ "$(cat $J/e3_build.status)" = running ]; do sleep 20; done
[ "$(cat $J/e3_build.status)" = ok ] || { st build FAILED; exit 1; }
IMG=$(tail -1 artifacts/clf/build_xapp.log | awk '{print $2}'); st build "ok $IMG"
timeout 900 $P scripts/k8s/staged.py rollout xapp $IMG > artifacts/clf/rollout_e3.log 2>&1 && st rollout ok || { st rollout FAILED; exit 1; }
minikube -p oai-lab ssh -- 'sudo rm -f /var/lib/minikube/images/*' >/dev/null 2>&1; rm -rf ~/.minikube/cache/images/*
docker rmi oai-lab-xapp:376673cf835b30d4 >/dev/null 2>&1; docker buildx prune -a -f >/dev/null 2>&1
st disk "$(df -h / | tail -1 | awk '{print $4}') free"
sleep 30
CAMPAIGN_MIN_FREE_GB=3 systemd-inhibit --what=sleep:idle:handle-lid-switch --who=campaign --why="live4 campaign" $P scripts/k8s/exp/v4traffic/campaign_twin.py --manifest $M --lo 0 --hi 30 > artifacts/clf/campaign_live4.log 2>&1 &
echo $! > artifacts/clf/campaign_live4.pid; st campaign "running $(date +%H:%M)"
FUT_OUT=research/clf/LIVE4_futility.log bash scripts/ml/live_futility.sh $M artifacts/clf/campaign_live4.pid &
wait $(cat artifacts/clf/campaign_live4.pid)
st campaign "ended $(date +%H:%M)"
bash scripts/ml/after_live4.sh > artifacts/clf/after_live4.log 2>&1 && st analysis ok || st analysis FAILED
