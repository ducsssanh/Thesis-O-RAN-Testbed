#!/usr/bin/env bash
# Ordered core recovery for the oai-lab 5GC (see memory testbed-userplane-fragility,
# FAILURE MODE 2). Fixes the SMF<->UPF PFCP-association failure caused by (a) the SMF's
# one-shot NRF UPF-discovery racing ahead of the UPF's NRF registration, and (b) a stale-
# subscription-starved NRF after repeated SMF restarts. The ORDER is the point: a
# simultaneous rollout-restart of all core NFs re-races and does NOT fix it.
#
#   NRF (fresh, clears stale subs) -> UPF (register to fresh NRF) -> wait both REGISTERED
#   -> SMF last (startup discovery finds the registered UPF) -> verify PFCP association
#   -> UEs (re-attach; they do NOT auto-retry a failed PDU request) -> routes -> defense off
#   -> verify 2 tunnels + 2 SUPIs at the xApp.
#
# The watchdog must call THIS for any SMF/core issue, never `rollout restart deploy/oai-smf`
# on its own. Idempotent; safe to re-run. Exit 0 only when the plane is verified healthy.
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
for i in $(seq 1 30); do
  $K -n oai-core logs deploy/oai-nrf --since=120s 2>/dev/null \
    | grep -q "NF type UPF" && { log "UPF registered at NRF"; break; }
  [ "$i" = 30 ] && fail "UPF never registered at NRF"
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
  $K -n oai-core logs deploy/oai-smf -c smf --since=120s 2>/dev/null \
    | grep -q "Added PFCP association with UPF" && { assoc=1; break; }
  sleep 3
done
[ "$assoc" = 1 ] || fail "SMF did not associate with the UPF (no 'Added PFCP association')"
log "PFCP association OK"

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

# 8. defense OFF (recover/restarts re-enable it; v4 capture needs it off)
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
