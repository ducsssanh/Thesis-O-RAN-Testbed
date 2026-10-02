#!/usr/bin/env bash
set -Eeuo pipefail
case "${1:?component required}" in
  gnb) exec /opt/oai/bin/nr-softmodem -O /config/gnb.conf --rfsim --rfsimulator.[0].serveraddr server --rfsimulator.[0].options chanmod --gNBs.[0].min_rxtxtime 6 ;;
  nr-ue)
    server=$(getent ahostsv4 oai-gnb-rfsim | awk 'NR==1 {print $1}')
    test -n "$server"
    read -r prbs mu band freq < <(python3 -c 'import json; r=json.load(open("/config/lab.json"))["radio"]; print(r["prbs"],r["numerology"],r["band"],r["frequency"])')
    # OAI writes nrL1_UE_stats-<id>.log in the current directory.  The
    # generated configuration is deliberately mounted read-only, so use a
    # writable runtime directory while continuing to read ue.conf from it.
    cd /tmp
    exec /opt/oai/bin/nr-uesoftmodem -O /config/ue.conf --rfsim --rfsimulator.serveraddr "$server" --rfsimulator.options chanmod -r "$prbs" --numerology "$mu" --band "$band" -C "$freq" ;;
  flexric) exec /opt/oai/bin/nearRT-RIC -c /config/flexric.conf -p /opt/oai/sm/ ;;
  xapp)
    printf '[NEAR-RIC]\nNEAR_RIC_IP = %s\n[XAPP]\nDB_NAME = unused\nDB_DIR = /tmp/\n' "$RIC_IP" >/tmp/flexric.conf
    run_id=${RUN_ID:-$(cat /artifacts/current-run)}
    [[ "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]
    mkdir -p "/artifacts/runs/$run_id"
    mkdir -p /urr-state
    export OUTPUT_CSV_PATH="/artifacts/runs/$run_id/KPI_Metrics.csv"
    export URR_DB_PATH=/urr-state/urr.db
    export URR_EXPORT_PATH="/artifacts/runs/$run_id/urr-received.jsonl"
    export KPM_MEAS_LIST_PATH=/source/flexric/build/28_552_kpm_meas.txt
    exec /opt/oai/bin/xapp_kpm_moni_write_to_csv "$OUTPUT_CSV_PATH" "${KPM_PERIOD:-1000}" -c /tmp/flexric.conf -p /opt/oai/sm/ ;;
  *) exit 2 ;;
esac
