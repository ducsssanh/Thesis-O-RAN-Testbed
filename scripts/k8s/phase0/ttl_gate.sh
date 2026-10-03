#!/bin/bash
# A.8 session TTL gate (docs/TWO-LAYER-DEFENSE-DESIGN.md 4.1).
# Usage: ttl_gate.sh <out-dir> lost|idle|smf
#   lost: scale gNB and UE to 0 (the gNB dies for good: no NG Setup from a
#         replacement gNB). The AMF drops the UE without Release SM Context,
#         so only T2 cleans up: UPIR after up_inactivity_s, release after
#         another deactivated_release_s. Restore with `lab.sh up --stage ran`.
#   idle: UE stays attached with its keep-alive off (helm ueKeepaliveS=0).
#         Phase 1 sends traffic right after the UPIR: the session must survive
#         past the deadline. Phase 2 stays silent: the session is released.
#         The keep-alive is restored at the end.
#   smf : restart the SMF only. The UPF must delete the sessions of the old
#         association when the new one arrives with another Recovery Time Stamp.
# PASS when every per-session BPF map is empty of the SEIDs present at start
# and the expected UPF/SMF log lines are there.
set -u
D=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$D/../../.." && pwd)
OUT=${1:?out-dir}; MODE=${2:?lost|idle|smf}
K="kubectl --context oai-lab"
mkdir -p "$OUT"
cfg() { python3 -c "import yaml,sys; c=yaml.safe_load(open('$ROOT/deploy/k8s/values/minikube.yaml'))['global']['lab']['defense']['sessionTtl']; print(c['$1'])"; }
UPIT=$(cfg upInactivityS); T1=$(cfg deactivatedReleaseS)
MAPS="rules_match_pdr session_by_ue_i pdrs_per_sessio urr_config_map urr_volume_coun session_rules_e"

map_seids() {  # SEIDs per map: "name:seid,seid name:..."
  local show; show=$("$D/bpftool.sh" map show)
  for m in $MAPS; do
    local id; id=$(grep "name $m" <<<"$show" | head -1 | cut -d: -f1)
    [ -z "$id" ] && { echo -n "$m:? "; continue; }
    local dump; dump=$("$D/bpftool.sh" -j map dump id "$id")
    # Maps keyed by SEID have a u64 key; others carry "seid" in key or value
    local s; s=$(grep -o '"seid":[0-9]*' <<<"$dump" | cut -d: -f2 | sort -nu | paste -sd, -)
    [ -z "$s" ] && s=$(python3 -c '
import json,sys
d=json.load(sys.stdin); out=set()
for e in d:
    k=e.get("key")
    if isinstance(k,int): out.add(k)
    elif isinstance(k,list) and len(k)==8: out.add(int.from_bytes(bytes(int(x,16) for x in k),"little"))
print(",".join(map(str,sorted(out))))' <<<"$dump" 2>/dev/null)
    echo -n "$m:${s:-} "
  done
}
logs() { $K -n oai-core logs deploy/oai-$1 -c $1 --since-time="$since" 2>/dev/null | grep -av '^ {'; }
wait_log() {  # component regex timeout-s (wall clock)
  local end=$(( $(date +%s) + $3 ))
  while [ "$(date +%s)" -lt $end ]; do logs "$1" | grep -aqE "$2" && return 0; sleep 2; done; return 1
}
verdict() { echo "$1" | tee -a "$OUT/result.txt"; [ "$1" = PASS ]; exit $?; }

since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
start=$(map_seids); echo "start $start (up_inactivity_s=$UPIT deactivated_release_s=$T1)" | tee "$OUT/result.txt"
ok=1
case $MODE in
lost)
  $K -n oai-ran scale deployment/oai-nr-ue deployment/oai-gnb --replicas=0 >/dev/null
  $K -n oai-ran delete pod -l 'oai-lab/component in (gnb,nr-ue)' --grace-period=0 --force >/dev/null 2>&1
  t0=$(date +%s)
  wait_log upf 'User Plane Inactivity Report' $((UPIT + 30)) || ok=0
  echo "UPIR after $(( $(date +%s) - t0 )) s (ok=$ok)" | tee -a "$OUT/result.txt"
  wait_log smf 'Session TTL T[12]: .*network-requested release' $((T1 + 40)) || ok=0
  echo "release after $(( $(date +%s) - t0 )) s (ok=$ok)" | tee -a "$OUT/result.txt"
  sleep 5 ;;
idle)
  helm --kube-context oai-lab -n oai-ran upgrade oai-ran "$ROOT/deploy/k8s/charts/ran" --reuse-values \
    --set global.lab.defense.ueKeepaliveS=0 --wait --timeout 5m >/dev/null
  echo "keep-alive off; waiting for the UE session" | tee -a "$OUT/result.txt"
  sleep 30; since=$(date -u +%Y-%m-%dT%H:%M:%SZ); start=$(map_seids)
  echo "session $start" | tee -a "$OUT/result.txt"
  ue_ip=$($K -n oai-ran exec deploy/oai-nr-ue -c nr-ue -- ip -4 -o addr show oaitun_ue1 | awk '{print $4}' | cut -d/ -f1)
  dn=$(python3 -c "import yaml; print(yaml.safe_load(open('$ROOT/deploy/k8s/values/minikube.yaml'))['global']['lab']['networks']['n6']['addresses']['dn'])")
  # Phase 1: traffic after the UPIR keeps the session
  wait_log upf 'User Plane Inactivity Report' $((UPIT + 30)) || ok=0
  echo "phase1 UPIR (ok=$ok); sending traffic" | tee -a "$OUT/result.txt"
  $K -n oai-ran exec deploy/oai-nr-ue -c nr-ue -- iperf -c "$dn" -B "$ue_ip" -u -b 100k -t 5 >/dev/null 2>&1
  sleep $((T1 + 20))
  logs smf | grep -aq 'Session TTL .*network-requested release' && ok=0
  echo "phase1 survived past the deadline (ok=$ok)" | tee -a "$OUT/result.txt"
  # Phase 2: silence until release (the timer re-arms after the traffic)
  t0=$(date +%s)
  wait_log smf 'Session TTL T2: .*network-requested release' $((UPIT + T1 + 60)) || ok=0
  echo "phase2 release after $(( $(date +%s) - t0 )) s (ok=$ok)" | tee -a "$OUT/result.txt"
  sleep 5 ;;
smf)
  $K -n oai-core delete pod -l oai-lab/component=smf --wait=false >/dev/null
  wait_log upf 'new Recovery Time Stamp' 180 || ok=0
  echo "UPF saw the SMF restart (ok=$ok)" | tee -a "$OUT/result.txt"
  sleep 5 ;;
*) echo "mode must be lost, idle or smf"; exit 2 ;;
esac

logs upf | grep -aE 'User Plane Inactivity|Recovery Time Stamp|N4_SESSION_DELETION|RemoveSession|Delete datapath|PFCP session established' > "$OUT/upf.log"
logs smf | grep -aE 'Session TTL|User Plane Inactivity|Release stale PDU|N4 Session Deletion' > "$OUT/smf.log"
end=$(map_seids); echo "end $end" | tee -a "$OUT/result.txt"
# Every SEID present at start must be gone from every map
for x in $(grep -o '[0-9]\+' <<<"$(sed 's/[a-z_]*://g' <<<"$start")" | sort -u); do
  for entry in $end; do grep -qE "(:|,)$x(,|$)" <<<"$entry" && { echo "leak: SEID $x in ${entry%%:*}" | tee -a "$OUT/result.txt"; ok=0; }; done
done
if [ "$MODE" = idle ]; then
  helm --kube-context oai-lab -n oai-ran upgrade oai-ran "$ROOT/deploy/k8s/charts/ran" --reuse-values \
    --set global.lab.defense.ueKeepaliveS=20 --wait --timeout 5m >/dev/null && echo "keep-alive restored" | tee -a "$OUT/result.txt"
fi
[ $ok = 1 ] && verdict PASS || verdict FAIL
