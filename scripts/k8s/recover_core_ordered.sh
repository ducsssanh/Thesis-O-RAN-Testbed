#!/usr/bin/env bash
# Ordered core recovery of the lab's 5G core. Fixes a failed SMF-UPF PFCP association, caused by (a) the SMF's one-shot
# UPF discovery at the NRF running before the UPF has registered, and (b) an NRF that keeps notification subscriptions
# of dead SMF pods after repeated SMF restarts. The order is the point: restarting every core NF at once races again.
#
#   NRF (fresh, clears stale subscriptions) -> UPF and AMF (register at the fresh NRF) -> wait for the UPF registration
#   -> SMF last (its discovery finds the UPF) -> verify the PFCP association -> wait for the gNB at the new AMF
#   -> UEs (they do not retry a failed PDU session request) -> routes -> detection off
#   -> verify 2 tunnels and 2 SUPIs at the xApp (needs a working xApp: run recover_ran.sh if this last step fails).
#
# Use this for any SMF or core problem, never a lone `rollout restart deploy/oai-smf`. Idempotent; exit 0 only when
# the user plane is verified.
set -uo pipefail
CTX=oai-lab
K="kubectl --context $CTX"
log(){ echo "[recover-core $(date +%H:%M:%S)] $*"; }
fail(){ log "FAIL: $*"; exit 1; }

wait_ready(){ # ns deploy timeout
  $K -n "$1" rollout status "deploy/$2" --timeout="${3:-150s}" >/dev/null 2>&1 \
    || fail "$2 not ready"; }

# 1. NRF fresh -> clears stale notification subscriptions to dead SMF pod IPs
log "restart NRF (clear stale subscriptions)"
$K -n oai-core rollout restart deploy/oai-nrf >/dev/null 2>&1
wait_ready oai-core oai-nrf 150s

# 2. UPF + AMF re-register to the fresh NRF (restart UPF so its registration is fresh and
#    lands AFTER the NRF is up; AMF re-registers on its own timer but restart is cheap)
log "restart UPF + AMF (register to fresh NRF)"
$K -n oai-core rollout restart deploy/oai-upf deploy/oai-amf >/dev/null 2>&1
wait_ready oai-core oai-upf 150s
wait_ready oai-core oai-amf 150s

# 3. wait until the NRF has the UPF REGISTERED (so the SMF's discovery will find it)
log "wait for UPF registered at NRF"
# a restarted UPF takes ~100 s to (re-)register (seen 2026-10-24): wait up to 180 s
for i in $(seq 1 60); do
  # read the log first: `logs | grep -q` under pipefail fails on SIGPIPE when grep exits early
  l=$($K -n oai-core logs deploy/oai-nrf --since=240s 2>/dev/null)
  grep -q "NF type UPF" <<<"$l" && { log "UPF registered at NRF"; break; }
  [ "$i" = 60 ] && fail "UPF never registered at NRF"
  sleep 3
done

# 4. SMF LAST -> its startup NRF discovery finds the registered UPF and associates
log "restart SMF (discovers UPF, associates)"
$K -n oai-core rollout restart deploy/oai-smf >/dev/null 2>&1
wait_ready oai-core oai-smf 150s

# 5. verify the PFCP N4 association actually formed
log "verify PFCP association"
assoc=0
for i in $(seq 1 30); do
  l=$($K -n oai-core logs deploy/oai-smf -c smf --since=120s 2>/dev/null)
  grep -q "Added PFCP association with UPF" <<<"$l" && { assoc=1; break; }
  sleep 3
done
[ "$assoc" = 1 ] || fail "SMF did not associate with the UPF (no 'Added PFCP association')"
log "PFCP association OK"

# 5b. the gNB re-dials the restarted AMF on its own (~40-60 s); a UE restarted before the NG
#     Setup sends its Registration Request to "no AMF" and never retries (seen 2026-11-14)
log "wait for the gNB NG Setup at the new AMF"
for i in $(seq 1 60); do
  l=$($K -n oai-core logs deploy/oai-amf 2>/dev/null)
  grep -q "has been attached to AMF" <<<"$l" && { log "gNB attached to AMF"; break; }
  [ "$i" = 60 ] && fail "gNB never attached to the new AMF"
  sleep 3
done

# 6. UEs re-attach (they do not auto-retry a PDU request that failed before association)
log "restart UEs"
$K -n oai-ran rollout restart deploy/oai-nr-ue deploy/oai-nr-ue2 >/dev/null 2>&1
wait_ready oai-ran oai-nr-ue 150s
wait_ready oai-ran oai-nr-ue2 150s

# 7. wait for both tunnels, then re-add the UE->DN route (lost on every UE restart)
log "wait for UE tunnels"
for ue in oai-nr-ue oai-nr-ue2; do
  for i in $(seq 1 40); do
    $K -n oai-ran exec deploy/$ue -c nr-ue -- ip -br addr show oaitun_ue1 >/dev/null 2>&1 \
      && break
    [ "$i" = 40 ] && fail "$ue has no oaitun_ue1 (PDU session did not establish)"
    sleep 3
  done
  $K -n oai-ran exec deploy/$ue -c nr-ue -- ip route replace 172.30.26.0/24 dev oaitun_ue1 >/dev/null 2>&1
done
log "tunnels up + routes added"

# 8. detection off (a restarted xApp starts with it on; every run sets its own defense configuration)
$K -n near-rt-ric exec deploy/oai-lab-xapp -c xapp -- python3 -c \
  'import urllib.request,json;urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8090/v1/defense/enabled",data=json.dumps({"enabled":False}).encode(),headers={"Content-Type":"application/json"},method="POST"))' \
  >/dev/null 2>&1 && log "defense off"

# 9. verify the xApp knows BOTH SUPIs (per-UE KPM/SUPI mapping)
log "verify xApp knows 2 SUPIs"
for i in $(seq 1 20); do
  n=$($K -n near-rt-ric exec deploy/oai-lab-xapp -c xapp -- python3 -c \
    'import urllib.request,json;print(len([u for u in json.loads(urllib.request.urlopen("http://127.0.0.1:8090/v1/defense/state",timeout=5).read())["ues"] if u.get("amf_ue_ngap_id") is not None]))' 2>/dev/null)
  [ "${n:-0}" -ge 2 ] && { log "xApp knows $n SUPIs -> HEALTHY"; exit 0; }
  sleep 3
done
fail "xApp does not know both SUPIs"
