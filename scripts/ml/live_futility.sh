#!/usr/bin/env bash
# Futility stop of a live campaign (agreed 2026-11-09): at the checkpoints of 10 and 20 kept runs, if the upper bound of the
# 95 % CI of BLOCK detection over all attack episodes (L1-L3 pooled, L2 included) is below 90 %, or that of rate-limit
# detection is, stop the campaign right after that kept run (never during a recovery). L2 alone is reported, not used to stop.
cd "$(dirname "$0")/../.."
M=$1; PIDF=$2; P=.venv-ml/bin/python; L=$M/campaign_log.jsonl; OUT=${FUT_OUT:-research/clf/LIVE3_futility.log}
PID=$(cat $PIDF); done_cp=""
while kill -0 $PID 2>/dev/null; do
  n=$(grep -c '"event": "kept"' $L 2>/dev/null || echo 0)
  for cp in 10 20; do
    if [ "$n" -ge $cp ] && ! echo "$done_cp" | grep -qw $cp; then
      done_cp="$done_cp $cp"
      $P scripts/ml/live_report.py $M /tmp/futility_$$.txt --json /tmp/futility_$$.json --boot 500 > /dev/null 2>&1
      verdict=$($P - <<PY
import json
r = json.load(open("/tmp/futility_$$.json"))
b, s = r["block"]["all"], r["soft"]["all"]
l2b = [v for k, v in r["block"].items() if k.startswith("L2")]
l2 = sum(v["det"] * v["n"] for v in l2b) / max(sum(v["n"] for v in l2b), 1)
stop = b["det_ci"][1] < 90 or s["det_ci"][1] < 90
print("%s block %.1f%% [%.1f, %.1f] (n %d) | rate %.1f%% [%.1f, %.1f] | L2 block %.1f%% | FA block %.2f rate %.2f" % (
    "STOP" if stop else "CONTINUE", b["det"], *b["det_ci"], b["n"], s["det"], *s["det_ci"], l2, b["fa"], s["fa"]))
PY
)
      echo "$(date +%H:%M) checkpoint $cp kept: $verdict" >> $OUT
      if echo "$verdict" | grep -q '^STOP'; then
        pkill -f "^.venv-ml/bin/python scripts/k8s/exp/v4traffic/campaign_twin.py --manifest $M"; pkill -f "scripts/k8s/exp/run.py run"
        echo "$(date +%H:%M) campaign stopped by the futility rule" >> $OUT; exit 0
      fi
    fi
  done
  sleep 30
done
echo "$(date +%H:%M) campaign ended, checkpoints passed:$done_cp" >> $OUT
