#!/bin/bash
# A.3 orphan-session check: kill the UE pod abruptly N times, then verify the
# UPF datapath only holds the live session.
# Usage: orphan_cycle.sh <out-dir> [cycles=3] [mode=ue|gnb]
#   ue : force-delete the UE pod only (gNB alive -> AMF releases via N2)
#   gnb: force-delete gNB and UE together (SCTP shutdown -> AMF drops the UE
#        without Release SM Context; only the SMF collision path cleans up)
# PASS when rules_match_pdr has exactly one SEID and the UPF logged an
# N4_SESSION_DELETION_REQUEST for every SEID that was replaced.
set -u
D=$(cd "$(dirname "$0")" && pwd)
OUT=${1:?out-dir}; N=${2:-3}; MODE=${3:-ue}
K="kubectl --context oai-lab"
mkdir -p "$OUT"

seids() {  # sorted unique SEIDs in rules_match_pdr
  local id; id=$("$D/bpftool.sh" map show | grep 'name rules_match_pdr' | cut -d: -f1)
  "$D/bpftool.sh" -j map dump id "$id" | grep -o '"seid":[0-9]*' | cut -d: -f2 | sort -nu | tr '\n' ' '
}
wait_session() {  # until UPF holds a SEID not in $1 (new session up); prints it
  for _ in $(seq "${2:-90}"); do
    for x in $(seids); do grep -qw "$x" <<<"$1" || { echo "$x"; return 0; }; done
    sleep 2
  done; return 1
}

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "start $(seids)" | tee "$OUT/cycles.txt"
seen=" $(seids) "
for i in $(seq "$N"); do
  ue=$($K -n oai-ran get pod -l oai-lab/component=nr-ue -o name | head -1)
  before=$(seids)
  if [ "$MODE" = gnb ]; then
    gnb=$($K -n oai-ran get pod -l oai-lab/component=gnb -o name | head -1)
    $K -n oai-ran delete "$gnb" "$ue" --grace-period=0 --force >/dev/null 2>&1
  else
    $K -n oai-ran delete "$ue" --grace-period=0 --force >/dev/null 2>&1
  fi
  new=$(wait_session "$seen" 150) || { echo "cycle $i: no new session" | tee -a "$OUT/cycles.txt"; break; }
  seen="$seen $new "
  sleep 5
  echo "cycle $i: killed $ue; before=[$before] new=$new after=[$(seids)]" | tee -a "$OUT/cycles.txt"
done

$K -n oai-core logs deploy/oai-upf -c upf --since-time="$since" | grep -av '^ {' \
  | grep -aE 'N4_SESSION_(ESTABLISHMENT|DELETION)_REQUEST|Delete Session' > "$OUT/upf-n4.log"
$K -n oai-core logs deploy/oai-smf -c smf --since-time="$since" | grep -aE 'already existed|Release stale PDU' > "$OUT/smf-stale.log"
id=$("$D/bpftool.sh" map show | grep 'name rules_match_pdr' | cut -d: -f1)
"$D/bpftool.sh" -j map dump id "$id" > "$OUT/after-rules_match_pdr.json"
python3 "$D/mapview.py" "$OUT/after-rules_match_pdr.json" > "$OUT/after-keys.json"

final=$(seids); count=$(wc -w <<<"$final"); missing=""
for x in $seen; do  # every replaced SEID must have been deleted in the UPF
  [ "$x" = "$(tr -d ' ' <<<"$final")" ] && continue
  grep -q "DELETION_REQUEST seid $(printf '0x%x' "$x") " "$OUT/upf-n4.log" || missing="$missing $x"
done
echo "mode=$MODE final=[$final] replaced=[$seen] missing-deletion=[$missing]" | tee -a "$OUT/cycles.txt"
if [ "$count" -eq 1 ] && [ -z "$missing" ]; then echo PASS | tee -a "$OUT/cycles.txt"; else echo FAIL | tee -a "$OUT/cycles.txt"; exit 1; fi
