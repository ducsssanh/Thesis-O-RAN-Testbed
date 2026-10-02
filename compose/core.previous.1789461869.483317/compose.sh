#!/bin/bash
set -euo pipefail
# Modified 2026-09-15: resolve the relocated 5gdeploy source via scripts/legacy/compose/env.sh.
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../../scripts/legacy/compose/env.sh"
msg() { echo -ne "\e[35m[5gdeploy] \e[94m"; echo -n "$*"; echo -e "\e[0m"; }
die() { msg "$*"; exit 1; }
with_retry() { while ! "$@"; do sleep 0.2; done }
cd "$(dirname "${BASH_SOURCE[0]}")"
COMPOSE_CTX=$PWD
ACT=${1:-}
[[ -z $ACT ]] || shift
if [[ $ACT == at ]]; then
  case ${1:-} in
    amf|ausf|bridge|cpufreq|dn_internet|dn_vcam|dn_vctl|grafana|nrf|processexporter|prometheus|smf|sql|udm|udr|upf1|upf140|upf141) echo docker;;
    *) die Container not found;;
  esac
elif [[ $ACT == upload ]]; then
  "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/compose/upload.ts" --dir=$COMPOSE_CTX
  "$DEPLOY_SRC/upload.sh" $COMPOSE_CTX 
elif [[ $ACT == create ]]; then
  msg 'Creating scenario containers on PRIMARY'
  docker compose create --remove-orphans amf ausf bridge cpufreq dn_internet dn_vcam dn_vctl grafana nrf processexporter prometheus smf sql udm udr upf1 upf140 upf141
  msg 'Scenario containers have been created, ready for traffic capture'
elif [[ $ACT == up ]]; then
  msg 'Starting the scenario on PRIMARY'
  docker compose up -d --remove-orphans amf ausf bridge cpufreq dn_internet dn_vcam dn_vctl grafana nrf processexporter prometheus smf sql udm udr upf1 upf140 upf141
  msg 'Scenario has started'
elif [[ $ACT == ps ]]; then
  msg 'Checking containers on PRIMARY'
  docker ps -a --format='table {{.Names}}	{{.Image}}	{{.Status}}' --no-trunc
  msg 'If any container is '"'"'Exited'"'"' with non-zero code or '"'"'unhealthy'"'"', please investigate why it failed'
elif [[ $ACT == down ]]; then
  msg 'Stopping the scenario on PRIMARY'
  docker compose down --remove-orphans
  msg 'Scenario has stopped'
elif [[ $ACT == stop ]]; then
  msg 'Stopping scenario containers on PRIMARY'
  docker compose rm -f -s
  msg 'Scenario containers have been deleted'
elif [[ $ACT == web ]]; then
  msg 'Prometheus is at 172.25.166.15:9090'
  msg 'Grafana is at 172.25.166.16:3000 , login with admin/grafana'
  msg Setup SSH port forwarding to access these services in a browser
elif [[ $ACT == phoenix-register ]]; then
  for UECT in $(docker ps --filter='name=^ue' --format='{{.Names}}' | sort -n); do
    msg Invoking Open5GCore UE registration and PDU session establishment in $UECT
    "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/phoenix-rpc/main.ts" --host=$UECT ue-register --dnn='*'
  done
elif [[ $ACT == linkstat ]]; then
  "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/trafficgen/linkstat.ts" --dir=$COMPOSE_CTX "$@"
elif [[ $ACT == list-pdu ]]; then
  "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/trafficgen/list-pdu.ts" --dir=$COMPOSE_CTX "$@"
elif [[ $ACT == nmap ]]; then
  "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/trafficgen/nmap.ts" --dir=$COMPOSE_CTX "$@"
elif [[ $ACT == nfd ]]; then
  "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/trafficgen/nfd.ts" --dir=$COMPOSE_CTX "$@"
elif [[ $ACT == tgcs ]]; then
  "$DEPLOY_SRC/node_modules/.bin/tsx" "$DEPLOY_SRC/trafficgen/tgcs.ts" --dir=$COMPOSE_CTX "$@"
else
  echo 'Usage:
  ./compose.sh up
    Start the scenario.
  ./compose.sh down
    Stop the scenario.
  $(./compose.sh at CT) CMD
    Run Docker command CMD on the host machine of container CT.
  ./compose.sh upload
    Upload Compose context and Docker images to secondary hosts.
  ./compose.sh create
    Create scenario containers to prepare for traffic capture.
  ./compose.sh stop
    Stop and delete the containers, but keep the networks.
  ./compose.sh ps
    View containers on each host machine.
  ./compose.sh web
    View access instructions for web applications.
  ./compose.sh phoenix-register
    Register Open5GCore UEs.
  ./compose.sh linkstat
    Gather netif counters.
  ./compose.sh list-pdu
    List PDU sessions.
  ./compose.sh nmap
    Run nmap ping scans from Data Network to UEs.
  ./compose.sh nfd --dnn=DNN
    Deploy NDN Forwarding Daemon (NFD) between Data Network and UEs.
  ./compose.sh tgcs FLAGS
    Prepare client-server traffic generators.'
  exit 1
fi