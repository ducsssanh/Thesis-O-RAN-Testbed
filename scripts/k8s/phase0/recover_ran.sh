#!/bin/bash
# Restart the RAN chain after FlexRIC or the gNB restarted (FlexRIC keeps a
# dead E2 association and the xApp asserts on its subscription): FlexRIC ->
# gNB -> every running UE -> (UE IPs + one AMF UE table period) -> xApp.
# Usage: recover_ran.sh [--keep-flexric]
set -eu
K="kubectl --context oai-lab"
if [ "${1:-}" != --keep-flexric ]; then
  $K -n near-rt-ric rollout restart deploy/oai-flexric >/dev/null
  $K -n near-rt-ric rollout status deploy/oai-flexric --timeout=120s >/dev/null
fi
$K -n oai-ran rollout restart deploy/oai-gnb >/dev/null
$K -n oai-ran rollout status deploy/oai-gnb --timeout=180s >/dev/null
sleep 10
UES=$($K -n oai-ran get deploy -o jsonpath='{range .items[?(@.spec.replicas>0)]}{.metadata.name}{"\n"}{end}' | grep '^oai-nr-ue')
for d in $UES; do $K -n oai-ran rollout restart deploy/$d >/dev/null; done
for d in $UES; do $K -n oai-ran rollout status deploy/$d --timeout=180s >/dev/null; done
for d in $UES; do
  for i in $(seq 1 40); do
    $K -n oai-ran exec deploy/$d -c nr-ue -- ip -4 -o addr show oaitun_ue1 2>/dev/null | grep -q inet && break
    sleep 3
  done
done
sleep 25   # AMF prints its UE table every ~20 s (SUPI mapping)
$K -n near-rt-ric rollout restart deploy/oai-lab-xapp >/dev/null
$K -n near-rt-ric rollout status deploy/oai-lab-xapp --timeout=120s >/dev/null
for i in $(seq 1 30); do
  $K -n near-rt-ric logs deploy/oai-lab-xapp 2>/dev/null | grep -qE "RAN control on|Assertion" && break
  sleep 3
done
$K -n near-rt-ric logs deploy/oai-lab-xapp | grep -E "RAN control on|Assertion|\[defense\]" || true
