#!/bin/bash
# A.7 calibration sweep: one full experiment per benign traffic profile
# (rate, UDP payload), with the CPU time of the URR path components sampled
# before and after each experiment (A.6 load).
# Usage: calib_sweep.sh <list-file> "rate:len" ["rate:len" ...]
#   Appends one experiment directory per line to <list-file>.
#   Duration per direction: LAB_EXPERIMENT_DURATION (default 60 s).
set -u
D=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$D/../../.." && pwd)
LIST=${1:?list-file}; shift
K="kubectl --context oai-lab"
export LAB_EXPERIMENT_DURATION=${LAB_EXPERIMENT_DURATION:-60}
COMPONENTS="oai-core/oai-smf/smf oai-core/oai-upf/upf non-rt-ric/urr-ei-producer/producer near-rt-ric/a1-ei-adapter/adapter near-rt-ric/oai-lab-xapp/xapp"

cpu() {  # JSON {component: usage_usec}
  local out="{"
  for c in $COMPONENTS; do
    IFS=/ read -r ns dep ctr <<<"$c"
    local u; u=$($K -n "$ns" exec "deploy/$dep" -c "$ctr" -- cat /sys/fs/cgroup/cpu.stat 2>/dev/null | awk '/^usage_usec/ {print $2}')
    out="$out\"$dep\": ${u:-null}, "
  done
  echo "${out%, }, \"t\": $(date +%s.%N)}"
}

for p in "$@"; do
  rate=${p%%:*}; len=${p##*:}
  echo "== profile rate=$rate payload=$len"
  $K -n oai-ran scale deployment/oai-nr-ue --replicas=0 >/dev/null
  $K -n oai-ran wait --for=delete pod -l oai-lab/component=nr-ue --timeout=120s >/dev/null 2>&1
  "$ROOT/scripts/k8s/lab.sh" new-run | tail -1
  "$ROOT/scripts/k8s/lab.sh" up --stage ran | grep -v '^ {' | tail -1
  before=$(cpu)
  LAB_EXPERIMENT_RATE=$rate LAB_EXPERIMENT_LENGTH=$len "$ROOT/scripts/k8s/lab.sh" experiment 2>&1 \
    | grep -v '^ {' | grep -vE 'running: [0-9]+ s' | tail -2
  after=$(cpu)
  run=$(tr -d '[:space:]' < "$ROOT/artifacts/k8s/state/current-staged-run")
  dir="$ROOT/artifacts/experiments/$run"
  printf '{"before": %s, "after": %s}\n' "$before" "$after" > "$dir/cpu.json"
  echo "$dir" >> "$LIST"
done
