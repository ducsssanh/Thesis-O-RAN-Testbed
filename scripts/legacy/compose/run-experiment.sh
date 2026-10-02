#!/usr/bin/env bash

set -Eeuo pipefail
shopt -s nullglob

source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
BASE="$CODEBASE_ROOT"

UE_NUMBER=1
KPM_PERIOD_MS=1000
BASELINE_SECONDS=30
BETWEEN_SECONDS=30
POST_SECONDS=10
DL_RATE=10M
DL_DURATION=120
UL_RATE=10M
UL_DURATION=120
RUN_DL=true
RUN_UL=true
RESTART=false
KEEP_RUNNING=false
DRY_RUN=false
CAPTURE_INTERFACE=auto
EXPERIMENT_TIMEZONE=${EXPERIMENT_TIMEZONE:-Asia/Ho_Chi_Minh}
RUN_ID=""

usage() {
  cat <<'EOF'
Usage: run-experiment.sh [options]

Runs the selected 5G Core, FlexRIC, OAI gNB/UE, KPM xApp, PFCP capture, and traffic from
one terminal. All artifacts are stored below artifacts/experiments/<run-id>/.

Options:
  --ue N                 UE number (default: 1)
  --period-ms N          KPM reporting period (default: 1000)
  --baseline SEC         Idle baseline before traffic (default: 30)
  --between SEC          Idle gap between DL and UL (default: 30)
  --post-wait SEC        Wait after traffic (default: 10)
  --dl-rate RATE         Downlink iperf2 rate (default: 10M)
  --dl-duration SEC      Downlink duration (default: 120)
  --ul-rate RATE         Uplink iperf2 rate (default: 10M)
  --ul-duration SEC      Uplink duration (default: 120)
  --no-dl                Skip downlink traffic
  --no-ul                Skip uplink traffic
  --capture-interface IF PFCP capture interface (default: auto; resolves Docker N4 bridge for OAI)
  --run-id ID            Override generated UTC run ID
  --restart              Stop an existing minimal OAI stack before starting
  --keep-running         Leave core, FlexRIC, gNB, and UE running at the end
  --smoke                Use 1M for 10 seconds with short idle periods
  --dry-run              Validate options and print the resolved plan only
  -h, --help             Show this help
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

is_uint() {
  [[ ${1:-} =~ ^[0-9]+$ ]]
}

is_rate() {
  [[ ${1:-} =~ ^[0-9]+[kKmMgG]$ ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ue) UE_NUMBER=${2:?Missing value for --ue}; shift 2 ;;
    --period-ms) KPM_PERIOD_MS=${2:?Missing value for --period-ms}; shift 2 ;;
    --baseline) BASELINE_SECONDS=${2:?Missing value for --baseline}; shift 2 ;;
    --between) BETWEEN_SECONDS=${2:?Missing value for --between}; shift 2 ;;
    --post-wait) POST_SECONDS=${2:?Missing value for --post-wait}; shift 2 ;;
    --dl-rate) DL_RATE=${2:?Missing value for --dl-rate}; shift 2 ;;
    --dl-duration) DL_DURATION=${2:?Missing value for --dl-duration}; shift 2 ;;
    --ul-rate) UL_RATE=${2:?Missing value for --ul-rate}; shift 2 ;;
    --ul-duration) UL_DURATION=${2:?Missing value for --ul-duration}; shift 2 ;;
    --no-dl) RUN_DL=false; shift ;;
    --no-ul) RUN_UL=false; shift ;;
    --capture-interface) CAPTURE_INTERFACE=${2:?Missing value for --capture-interface}; shift 2 ;;
    --run-id) RUN_ID=${2:?Missing value for --run-id}; shift 2 ;;
    --restart) RESTART=true; shift ;;
    --keep-running) KEEP_RUNNING=true; shift ;;
    --smoke)
      BASELINE_SECONDS=5
      BETWEEN_SECONDS=5
      POST_SECONDS=5
      DL_RATE=1M
      DL_DURATION=10
      UL_RATE=1M
      UL_DURATION=10
      shift
      ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

is_uint "$UE_NUMBER" && ((UE_NUMBER >= 1)) || die "--ue must be at least 1"
is_uint "$KPM_PERIOD_MS" && ((KPM_PERIOD_MS >= 1)) || die "--period-ms must be positive"
for value in "$BASELINE_SECONDS" "$BETWEEN_SECONDS" "$POST_SECONDS" "$DL_DURATION" "$UL_DURATION"; do
  is_uint "$value" || die "Durations must be non-negative integers"
done
is_rate "$DL_RATE" || die "Invalid --dl-rate: $DL_RATE"
is_rate "$UL_RATE" || die "Invalid --ul-rate: $UL_RATE"
[[ "$RUN_DL" == false ]] || ((DL_DURATION >= 1)) || die "--dl-duration must be positive when DL is enabled"
[[ "$RUN_UL" == false ]] || ((UL_DURATION >= 1)) || die "--ul-duration must be positive when UL is enabled"
[[ -d "$CODEBASE_ROOT" ]] || die "Missing Codebase root: $CODEBASE_ROOT"

CORE_BACKEND=$(yq eval '.core_to_use // "open5gs"' "$CORE_OPTIONS")
[[ "$CORE_BACKEND" == 5gdeploy-* ]] || die "This port supports 5gdeploy backends; set core_to_use in $CORE_OPTIONS accordingly."
UPF_BACKEND=$(yq eval '.upf_to_use // .core_to_use' "$CORE_OPTIONS")
OAI_UPF_DATAPATH=$(yq eval '.oai_upf.datapath // "not-applicable"' "$CORE_OPTIONS")
URR_REQUIRED=$(yq eval '.oai_upf.enable_usage_reporting // false' "$CORE_OPTIONS")
URR_THRESHOLD_BYTES=$(yq eval '.oai_upf.volume_threshold_bytes // 104857600' "$CORE_OPTIONS")

if [[ -z "$RUN_ID" ]]; then
  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)_ue${UE_NUMBER}"
fi
[[ "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "--run-id contains unsupported characters"

RUN_DIR="$EXPERIMENT_ROOT/$RUN_ID"
KPM_DIR="$RUN_DIR/kpm"
CAPTURE_DIR="$RUN_DIR/capture"
TRAFFIC_DIR="$RUN_DIR/traffic"
AUTOMATION_DIR="$RUN_DIR/automation"
METADATA_DIR="$RUN_DIR/metadata"
RUN_MARKER="$METADATA_DIR/run_started.marker"

if [[ "$DRY_RUN" == true ]]; then
  cat <<EOF
BASE=$BASE
RUN_DIR=$RUN_DIR
UE=$UE_NUMBER
KPM_PERIOD_MS=$KPM_PERIOD_MS
DL=$RUN_DL rate=$DL_RATE duration=$DL_DURATION
UL=$RUN_UL rate=$UL_RATE duration=$UL_DURATION
BASELINE=$BASELINE_SECONDS BETWEEN=$BETWEEN_SECONDS POST=$POST_SECONDS
RESTART=$RESTART KEEP_RUNNING=$KEEP_RUNNING CAPTURE_INTERFACE=$CAPTURE_INTERFACE
CORE_BACKEND=$CORE_BACKEND UPF_BACKEND=$UPF_BACKEND OAI_UPF_DATAPATH=$OAI_UPF_DATAPATH
EXPERIMENT_TIMEZONE=$EXPERIMENT_TIMEZONE
EOF
  exit 0
fi

[[ ! -e "$RUN_DIR" ]] || die "Run directory already exists: $RUN_DIR"
mkdir -p "$RUN_DIR"/{automation,capture,core,flexric,gnb,kpm,metadata,traffic,ue}
touch "$RUN_MARKER"
ln -sfn "$RUN_ID" "$EXPERIMENT_ROOT/latest"

exec > >(tee -a "$AUTOMATION_DIR/experiment.log") 2>&1

XAPP_PID=""
XAPP_PGID=""
DUMPCAP_PID=""
SUDO_REFRESH_PID=""
STACK_STARTED=false
MONGOD_WAS_ACTIVE=false
EXPERIMENT_STATUS=failed
CLEANUP_STARTED=false

report_error() {
  local rc=$?
  local line=${BASH_LINENO[0]:-$LINENO}
  local command=${BASH_COMMAND:-unknown}
  printf '\nERROR: command failed with exit code %s at line %s: %s\n' \
    "$rc" "$line" "$command" >&2
}

stage() {
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  printf '%s\n' "[$timestamp] $*" >"$METADATA_DIR/current_stage.txt"
  printf '\n[%s] %s\n' "$timestamp" "$*"
}

utc_ms() {
  date -u +%s%3N
}

command_required() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

run_logged() {
  local output_file=$1
  local status=0
  shift
  # A launcher may spawn a detached child that keeps its stdout descriptor.
  # Logging to a regular file avoids waiting forever for a tee pipe to close.
  "$@" >"$output_file" 2>&1 || status=$?
  cat "$output_file"
  return "$status"
}

stack_is_running() {
  if [[ "$CORE_BACKEND" != "open5gs" ]] && command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' | rg -q '^(amf|smf|upf|upf1)$'; then
      return 0
    fi
  fi
  local process
  for process in open5gs-amfd open5gs-smfd open5gs-upfd nearRT-RIC nr-softmodem nr-uesoftmodem; do
    if pgrep -x "$process" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

wait_for_container() {
  local pattern=$1
  local timeout_seconds=$2
  local elapsed=0
  while ! docker ps --format '{{.Names}}' | rg -q "$pattern"; do
    ((elapsed >= timeout_seconds)) && die "Timed out waiting for container matching $pattern"
    sleep 1
    ((elapsed += 1))
  done
}

wait_for_core_ready() {
  local timeout_seconds=$1
  local elapsed=0
  while true; do
    if [[ $("$SCRIPTS_ROOT/lib/core-ready.sh" 2>/dev/null || true) == "true" ]]; then
      return 0
    fi
    ((elapsed >= timeout_seconds)) && die "Timed out waiting for $CORE_BACKEND readiness"
    sleep 2
    ((elapsed += 2))
    ((elapsed % 10 == 0)) && printf '  waiting for %s readiness (%ss/%ss)\n' "$CORE_BACKEND" "$elapsed" "$timeout_seconds"
  done
}

wait_for_oai_pfcp_association() {
  local timeout_seconds=$1
  local elapsed=0
  while true; do
    if docker logs smf 2>&1 | rg -qi 'PFCP.*associ|associ.*UPF|N4.*associ'; then
      return 0
    fi
    ((elapsed >= timeout_seconds)) && die "Timed out waiting for OAI SMF-UPF PFCP association"
    sleep 2
    ((elapsed += 2))
  done
}

wait_for_process() {
  local process=$1
  local timeout_seconds=$2
  local elapsed=0
  while ! pgrep -x "$process" >/dev/null 2>&1; do
    ((elapsed >= timeout_seconds)) && die "Timed out waiting for process $process"
    sleep 1
    ((elapsed += 1))
    ((elapsed % 10 == 0)) && printf '  waiting for %s (%ss/%ss)\n' "$process" "$elapsed" "$timeout_seconds"
  done
}

wait_for_log() {
  local label=$1
  local file=$2
  local pattern=$3
  local timeout_seconds=$4
  local elapsed=0
  local search_status
  while true; do
    search_status=1
    if [[ -f "$file" ]]; then
      search_status=0
      rg -q "$pattern" "$file" || search_status=$?
      [[ "$search_status" -eq 0 ]] && return 0
      [[ "$search_status" -eq 1 ]] || die "Failed to search $file while waiting for $label"
    fi
    ((elapsed >= timeout_seconds)) && die "Timed out waiting for $label; inspect $file"
    sleep 1
    ((elapsed += 1))
    ((elapsed % 10 == 0)) && printf '  waiting for %s (%ss/%ss)\n' "$label" "$elapsed" "$timeout_seconds"
  done
}

wait_for_pdu_session() {
  local ue_log=$1
  local amf_log=$2
  local timeout_seconds=$3
  local elapsed=0
  while true; do
    if [[ -f "$ue_log" ]] && rg -q 'PDU Session Establishment Accept' "$ue_log"; then
      return 0
    fi
    if [[ -f "$ue_log" ]] && rg -q 'PDU Session Establishment Reject' "$ue_log"; then
      rg 'PDU Session Establishment Reject' "$ue_log" | tail -n 1 >&2
      die "The UE received a PDU session rejection; inspect $ue_log"
    fi
    if [[ -f "$amf_log" ]] && rg -q 'create_sm_context failed' "$amf_log"; then
      rg 'create_sm_context failed' "$amf_log" | tail -n 1 >&2
      die "AMF failed to create the SM context; inspect $amf_log and $ue_log"
    fi
    ((elapsed >= timeout_seconds)) && die "Timed out waiting for PDU session; inspect $ue_log"
    sleep 1
    ((elapsed += 1))
    ((elapsed % 10 == 0)) && printf '  waiting for PDU session (%ss/%ss)\n' "$elapsed" "$timeout_seconds"
  done
}

sleep_progress() {
  local label=$1
  local seconds=$2
  local elapsed=0
  ((seconds == 0)) && return 0
  while ((elapsed < seconds)); do
    local step=5
    ((seconds - elapsed < step)) && step=$((seconds - elapsed))
    sleep "$step"
    ((elapsed += step))
    printf '  %s: %ss/%ss\r' "$label" "$elapsed" "$seconds"
  done
  printf '\n'
}

record_idle_phase() {
  local name=$1
  local duration=$2
  local start_ms end_ms
  start_ms=$(utc_ms)
  sleep_progress "$name" "$duration"
  end_ms=$(utc_ms)
  printf '%s,idle,0,%s,%s,%s,ok\n' "$name" "$duration" "$start_ms" "$end_ms" >>"$METADATA_DIR/phases.csv"
}

record_traffic_phase() {
  local name=$1
  local direction=$2
  local rate=$3
  local duration=$4
  local output_file=$5
  shift 5
  local start_ms end_ms status=ok
  start_ms=$(utc_ms)
  if ! run_logged "$output_file" "$@"; then
    status=failed
  fi
  end_ms=$(utc_ms)
  printf '%s,%s,%s,%s,%s,%s,%s\n' "$name" "$direction" "$rate" "$duration" "$start_ms" "$end_ms" "$status" \
    >>"$METADATA_DIR/phases.csv"
  [[ "$status" == ok ]] || die "$name traffic failed; inspect $output_file"
}

record_status() {
  local output_file=$1
  {
    printf 'timestamp=%s\n' "$(date --iso-8601=seconds)"
    printf 'hostname=%s\n' "$(hostname)"
    printf '\n[core]\n'
    "$SCRIPTS_ROOT/lib/core-status.sh" minimal-5g 2>&1 || true
    if [[ "$CORE_BACKEND" != "open5gs" ]] && command -v docker >/dev/null 2>&1; then
      printf '\n[core_containers]\n'
      docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1 || true
    fi
    printf '\n[gnb]\n'
    "$SCRIPTS_ROOT/lib/gnb-status.sh" 2>&1 || true
    printf '\n[ue]\n'
    "$SCRIPTS_ROOT/lib/ue-status.sh" 2>&1 || true
    printf '\n[flexric]\n'
    "$SCRIPTS_ROOT/lib/flexric-status.sh" 2>&1 || true
    printf '\n[network_namespaces]\n'
    ip netns list 2>&1 || true
    printf '\n[disk]\n'
    df -h "$BASE" 2>&1 || true
  } >"$output_file"
}

resolve_pfcp_capture_interface() {
  [[ "$CAPTURE_INTERFACE" == "auto" ]] || return 0
  if [[ "$CORE_BACKEND" == "open5gs" ]]; then
    CAPTURE_INTERFACE=lo
    return 0
  fi

  local smf_networks upf_container network network_id bridge
  upf_container=$(docker ps --format '{{.Names}}' | rg '^(upf|upf1)$' | head -n 1 || true)
  [[ -n "$upf_container" ]] || die "Cannot resolve OAI UPF container for PFCP capture"
  smf_networks=$(docker inspect smf --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}')
  for network in $smf_networks; do
    if docker inspect "$upf_container" --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' | grep -qw "$network"; then
      network_id=$(docker network inspect "$network" --format '{{.Id}}')
      bridge=$(docker network inspect "$network" --format '{{index .Options "com.docker.network.bridge.name"}}')
      [[ -n "$bridge" && "$bridge" != "<no value>" ]] || bridge="br-${network_id:0:12}"
      if ip link show "$bridge" >/dev/null 2>&1; then
        CAPTURE_INTERFACE=$bridge
        return 0
      fi
    fi
  done
  echo "WARNING: Could not resolve the Docker N4 bridge; capturing PFCP on all interfaces." >&2
  CAPTURE_INTERFACE=any
}

start_capture() {
  resolve_pfcp_capture_interface
  stage "Starting PFCP capture on $CAPTURE_INTERFACE"
  : >"$CAPTURE_DIR/dumpcap.log"
  # The shell opens the pcap file as the current user. dumpcap writes to its
  # inherited stdout, so its privilege drop cannot cause a directory error.
  sudo -n dumpcap -q -i "$CAPTURE_INTERFACE" -f 'udp port 8805' -w - \
    >"$CAPTURE_DIR/pfcp.pcapng" 2>"$CAPTURE_DIR/dumpcap.log" &
  DUMPCAP_PID=$!
  printf '%s\n' "$DUMPCAP_PID" >"$CAPTURE_DIR/dumpcap.pid"
  sleep 2
  if ! sudo -n kill -0 "$DUMPCAP_PID" 2>/dev/null; then
    wait "$DUMPCAP_PID" 2>/dev/null || true
    sed -n '1,80p' "$CAPTURE_DIR/dumpcap.log" >&2
    die "dumpcap did not start"
  fi
}

stop_xapp() {
  [[ -n "$XAPP_PID" ]] || return 0
  if kill -0 "$XAPP_PID" 2>/dev/null; then
    stage "Stopping KPM xApp"
    if [[ -n "$XAPP_PGID" ]]; then
      kill -INT -- "-$XAPP_PGID" 2>/dev/null || true
    else
      kill -INT "$XAPP_PID" 2>/dev/null || true
    fi
    for _ in {1..20}; do
      kill -0 "$XAPP_PID" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$XAPP_PID" 2>/dev/null; then
      if [[ -n "$XAPP_PGID" ]]; then
        kill -TERM -- "-$XAPP_PGID" 2>/dev/null || true
      else
        kill -TERM "$XAPP_PID" 2>/dev/null || true
      fi
      for _ in {1..10}; do
        kill -0 "$XAPP_PID" 2>/dev/null || break
        sleep 0.5
      done
    fi
    if kill -0 "$XAPP_PID" 2>/dev/null; then
      if [[ -n "$XAPP_PGID" ]]; then
        kill -KILL -- "-$XAPP_PGID" 2>/dev/null || true
      else
        kill -KILL "$XAPP_PID" 2>/dev/null || true
      fi
    fi
  fi
  wait "$XAPP_PID" 2>/dev/null || true
  XAPP_PID=""
  XAPP_PGID=""
}

stop_capture() {
  [[ -n "$DUMPCAP_PID" ]] || return 0
  stage "Stopping PFCP capture"
  sudo -n kill -INT "$DUMPCAP_PID" 2>/dev/null || true
  wait "$DUMPCAP_PID" 2>/dev/null || true
  DUMPCAP_PID=""
}

epoch_to_iso8601() {
  local epoch=${1:-}
  [[ -n "$epoch" ]] || return 0
  LC_ALL=C TZ="$EXPERIMENT_TIMEZONE" date -d "@$epoch" '+%Y-%m-%dT%H:%M:%S.%3N%:z'
}

absolute_time_to_iso8601() {
  local timestamp=${1:-}
  [[ -n "$timestamp" ]] || return 0
  LC_ALL=C TZ="$EXPERIMENT_TIMEZONE" date -d "$timestamp" '+%Y-%m-%dT%H:%M:%S.%3N%:z'
}

decode_capture() {
  [[ -s "$CAPTURE_DIR/pfcp.pcapng" ]] || return 0
  capinfos "$CAPTURE_DIR/pfcp.pcapng" >"$CAPTURE_DIR/capinfos.txt" 2>&1 || true

  {
    printf '%s\n' 'frame_time_iso,frame_time_epoch_seconds,ip_src,ip_dst,pfcp_message_type,pfcp_seid'
    while IFS='|' read -r epoch ip_src ip_dst message_type seid; do
      [[ -n "$epoch" ]] || continue
      printf '%s,%s,%s,%s,%s,%s\n' \
        "$(epoch_to_iso8601 "$epoch")" "$epoch" "$ip_src" "$ip_dst" "$message_type" "$seid"
    done < <(
      tshark -r "$CAPTURE_DIR/pfcp.pcapng" -Y pfcp \
        -T fields -E 'separator=|' -E occurrence=f \
        -e frame.time_epoch -e ip.src -e ip.dst -e pfcp.msg_type -e pfcp.seid \
        2>"$CAPTURE_DIR/tshark_messages.log" || true
    )
  } >"$CAPTURE_DIR/pfcp_messages.csv"

  {
    printf '%s\n' 'frame_time_iso,frame_time_epoch_seconds,pfcp_message_type,pfcp_seid,urr_id,measurement_method_volume,trigger_volume_threshold,volume_threshold_bytes'
    while IFS='|' read -r epoch message_type seid urr_id measurement_volume trigger_threshold threshold_bytes; do
      [[ -n "$epoch" ]] || continue
      printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$(epoch_to_iso8601 "$epoch")" "$epoch" "$message_type" "$seid" "$urr_id" \
        "$measurement_volume" "$trigger_threshold" "$threshold_bytes"
    done < <(
      tshark -r "$CAPTURE_DIR/pfcp.pcapng" \
        -Y 'pfcp.urr_id && pfcp.volume_threshold.tovol' \
        -T fields -E 'separator=|' -E occurrence=f \
        -e frame.time_epoch -e pfcp.msg_type -e pfcp.seid -e pfcp.urr_id \
        -e pfcp.measurement_method_flags.volume -e pfcp.reporting_triggers_flags.volth \
        -e pfcp.volume_threshold.tovol \
        2>"$CAPTURE_DIR/tshark_urr_config.log" || true
    )
  } >"$CAPTURE_DIR/pfcp_urr_config.csv"

  {
    printf '%s\n' 'frame_time_iso,frame_time_epoch_seconds,first_packet_time_iso,last_packet_time_iso,ip_src,ip_dst,pfcp_message_type,pfcp_seid,urr_id,total_volume_bytes,uplink_volume_bytes,downlink_volume_bytes,trigger_volume_threshold,trigger_periodic,trigger_termination'
    while IFS='|' read -r epoch first_packet last_packet ip_src ip_dst message_type seid urr_id \
        total_bytes uplink_bytes downlink_bytes trigger_threshold trigger_periodic trigger_termination; do
      [[ -n "$epoch" ]] || continue
      printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$(epoch_to_iso8601 "$epoch")" "$epoch" \
        "$(absolute_time_to_iso8601 "$first_packet")" "$(absolute_time_to_iso8601 "$last_packet")" \
        "$ip_src" "$ip_dst" "$message_type" "$seid" "$urr_id" \
        "$total_bytes" "$uplink_bytes" "$downlink_bytes" \
        "$trigger_threshold" "$trigger_periodic" "$trigger_termination"
    done < <(
      tshark -r "$CAPTURE_DIR/pfcp.pcapng" -Y 'pfcp.volume_measurement.tovol' \
        -T fields -E 'separator=|' -E occurrence=f \
        -e frame.time_epoch -e pfcp.time_of_first_packet -e pfcp.time_of_last_packet \
        -e ip.src -e ip.dst -e pfcp.msg_type -e pfcp.seid -e pfcp.urr_id \
        -e pfcp.volume_measurement.tovol -e pfcp.volume_measurement.ulvol \
        -e pfcp.volume_measurement.dlvol -e pfcp.usage_report_trigger_flags.volth \
        -e pfcp.usage_report_trigger_flags.perio -e pfcp.usage_report_trigger.term \
        2>"$CAPTURE_DIR/tshark_urr.log" || true
    )
  } >"$CAPTURE_DIR/pfcp_urr.csv"
}

validate_urr_capture() {
  [[ "$URR_REQUIRED" == "true" ]] || return 0
  [[ -s "$CAPTURE_DIR/pfcp_urr_config.csv" ]] || {
    echo "ERROR: PFCP URR configuration CSV is missing." >&2
    return 1
  }
  [[ -s "$CAPTURE_DIR/pfcp_urr.csv" ]] || {
    echo "ERROR: PFCP Usage Report CSV is missing." >&2
    return 1
  }

  awk -F, -v threshold="$URR_THRESHOLD_BYTES" '
    NR > 1 && $7 == "True" && $8 == threshold { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$CAPTURE_DIR/pfcp_urr_config.csv" || {
    echo "ERROR: No Create URR with VOLTH=$URR_THRESHOLD_BYTES bytes was captured." >&2
    return 1
  }
  awk -F, -v threshold="$URR_THRESHOLD_BYTES" '
    NR > 1 && $13 == "True" && ($10 + 0) >= threshold && ($10 + 0) == ($11 + 0) + ($12 + 0) { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$CAPTURE_DIR/pfcp_urr.csv" || {
    echo "ERROR: No valid volume-threshold Usage Report was captured." >&2
    return 1
  }
}

collect_artifacts() {
  stage "Collecting component logs"
  collect_recent_logs "$CORE_LOG_DIR" "$RUN_DIR/core"
  if [[ "$CORE_BACKEND" != "open5gs" ]] && command -v docker >/dev/null 2>&1; then
    local container
    for container in $(docker ps -a --format '{{.Names}}' | rg '^(amf|smf|upf|upf1|nrf|ausf|udm|udr|nssf|pcf|sql|mysql)$' || true); do
      docker logs --timestamps "$container" >"$RUN_DIR/core/${container}.log" 2>&1 || true
      docker inspect "$container" >"$RUN_DIR/core/${container}.inspect.json" 2>/dev/null || true
    done
    cp "$CORE_COMPOSE_DIR/oai_upf_profile.env" "$METADATA_DIR/" 2>/dev/null || true
    cp "$CORE_COMPOSE_DIR/compose.yml" "$METADATA_DIR/core-compose.yml" 2>/dev/null || true
  fi
  collect_recent_logs "$GNB_LOG_DIR" "$RUN_DIR/gnb"
  collect_recent_logs "$UE_LOG_DIR" "$RUN_DIR/ue"
  collect_recent_logs "$FLEXRIC_LOG_DIR" "$RUN_DIR/flexric" \
    --exclude='KPI_Metrics*.csv' --exclude='.~lock.*'

  cp "$CORE_OPTIONS" "$METADATA_DIR/core_options.yaml" 2>/dev/null || true
  cp "$GNB_CONFIG_DIR/gnb.conf" "$METADATA_DIR/gnb.conf" 2>/dev/null || true
  cp "$UE_CONFIG_DIR/ue${UE_NUMBER}.conf" "$METADATA_DIR/ue${UE_NUMBER}.conf" 2>/dev/null || true
  cp "$FLEXRIC_CONFIG_DIR/flexric.conf" "$METADATA_DIR/flexric.conf" 2>/dev/null || true
}

collect_recent_logs() {
  local source_dir=$1
  local destination_dir=$2
  shift 2
  [[ -d "$source_dir" ]] || return 0
  find "$source_dir" -type f -newer "$RUN_MARKER" -printf '%P\0' \
    | rsync -a --from0 --files-from=- "$@" "$source_dir/" "$destination_dir/" \
        2>/dev/null || true
}

abort_cleanup() {
  trap - EXIT INT TERM
  set +e
  printf '\nCleanup interrupted; forcing the experiment runner to exit.\n' >&2
  if [[ -n "$XAPP_PGID" ]]; then
    kill -KILL -- "-$XAPP_PGID" 2>/dev/null || true
  elif [[ -n "$XAPP_PID" ]]; then
    kill -KILL "$XAPP_PID" 2>/dev/null || true
  fi
  if [[ -n "$DUMPCAP_PID" ]]; then
    sudo -n kill -KILL "$DUMPCAP_PID" 2>/dev/null || true
  fi
  printf 'status=interrupted\nexit_code=130\nfinished_at=%s\n' \
    "$(date --iso-8601=seconds)" >"$METADATA_DIR/result.env"
  exit 130
}

cleanup() {
  local rc=$?
  [[ "$CLEANUP_STARTED" == false ]] || exit "$rc"
  CLEANUP_STARTED=true
  trap - EXIT
  trap abort_cleanup INT TERM
  set +e
  printf 'Cleanup in progress; press Ctrl+C again to force the runner to exit.\n'

  stop_xapp

  # Preserve PFCP packets and Docker logs before compose down removes the OAI
  # containers. This also makes URR validation part of the experiment result.
  stop_capture
  decode_capture
  if [[ "$EXPERIMENT_STATUS" == "complete" ]] && ! validate_urr_capture; then
    EXPERIMENT_STATUS=failed
    rc=1
  fi
  collect_artifacts

  if [[ "$STACK_STARTED" == true && "$KEEP_RUNNING" == false ]]; then
    stage "Stopping the minimal OAI stack"
    timeout --foreground 180 "$SCRIPTS_ROOT/stop-stack.sh" "$UE_NUMBER" >"$AUTOMATION_DIR/stop_stack.log" 2>&1 || true
    sleep 2
  fi

  record_status "$METADATA_DIR/status_after.txt"

  if [[ "$CORE_BACKEND" == "open5gs" && "$STACK_STARTED" == true && "$KEEP_RUNNING" == false && "$MONGOD_WAS_ACTIVE" == false ]]; then
    sudo -n systemctl stop mongod >/dev/null 2>&1 || true
  fi
  if [[ -n "$SUDO_REFRESH_PID" ]]; then
    kill "$SUDO_REFRESH_PID" 2>/dev/null || true
    wait "$SUDO_REFRESH_PID" 2>/dev/null || true
  fi

  printf 'status=%s\nexit_code=%s\nfinished_at=%s\n' \
    "$EXPERIMENT_STATUS" "$rc" "$(date --iso-8601=seconds)" >"$METADATA_DIR/result.env"
  ln -sfn "$RUN_ID" "$EXPERIMENT_ROOT/latest"

  stage "Artifacts saved to $RUN_DIR"
  exit "$rc"
}

trap cleanup EXIT
trap 'EXPERIMENT_STATUS=interrupted; exit 130' INT TERM
trap report_error ERR

for command in capinfos date dumpcap ip iperf pgrep ps realpath rg rsync setsid sudo systemctl tee timeout tshark yq; do
  command_required "$command"
done
if [[ "$CORE_BACKEND" != "open5gs" ]]; then
  command_required docker
fi
for script in \
  "$SCRIPTS_ROOT/start-core.sh" \
  "$SCRIPTS_ROOT/start-gnb.sh" \
  "$SCRIPTS_ROOT/start-ue.sh" \
  "$SCRIPTS_ROOT/traffic-dl.sh" \
  "$SCRIPTS_ROOT/traffic-ul.sh" \
  "$SCRIPTS_ROOT/start-flexric.sh" \
  "$SCRIPTS_ROOT/start-xapp.sh"; do
  [[ -x "$script" ]] || die "Required executable not found: $script"
done

printf 'phase,direction,offered_rate,duration_seconds,start_unix_ms,end_unix_ms,status\n' >"$METADATA_DIR/phases.csv"
{
  printf 'RUN_ID=%q\n' "$RUN_ID"
  printf 'BASE=%q\n' "$BASE"
  printf 'UE_NUMBER=%q\n' "$UE_NUMBER"
  printf 'KPM_PERIOD_MS=%q\n' "$KPM_PERIOD_MS"
  printf 'EXPERIMENT_TIMEZONE=%q\n' "$EXPERIMENT_TIMEZONE"
  printf 'CORE_BACKEND=%q\nUPF_BACKEND=%q\n' "$CORE_BACKEND" "$UPF_BACKEND"
  printf 'OAI_UPF_DATAPATH=%q\n' "$OAI_UPF_DATAPATH"
  printf 'URR_REQUIRED=%q\nURR_THRESHOLD_BYTES=%q\n' "$URR_REQUIRED" "$URR_THRESHOLD_BYTES"
  printf 'DL_RATE=%q\nDL_DURATION=%q\n' "$DL_RATE" "$DL_DURATION"
  printf 'UL_RATE=%q\nUL_DURATION=%q\n' "$UL_RATE" "$UL_DURATION"
  printf 'STARTED_AT=%q\n' "$(date --iso-8601=seconds)"
} >"$METADATA_DIR/run.env"
printf 'status=running\npid=%s\nstarted_at=%s\n' \
  "$$" "$(date --iso-8601=seconds)" >"$METADATA_DIR/result.env"

stage "Experiment $RUN_ID"
printf 'Artifacts: %s\n' "$RUN_DIR"

sudo -v
(while sleep 45; do sudo -n true || exit; done) </dev/null >/dev/null 2>&1 &
SUDO_REFRESH_PID=$!

if stack_is_running; then
  if [[ "$RESTART" == true ]]; then
    stage "Stopping the existing minimal OAI stack"
    timeout --foreground 180 "$SCRIPTS_ROOT/stop-stack.sh" "$UE_NUMBER" >"$AUTOMATION_DIR/restart_stack.log" 2>&1 || true
  else
    die "A minimal OAI component is already running. Stop it first or pass --restart"
  fi
fi

sudo -n systemctl start chrony
if [[ "$CORE_BACKEND" == "open5gs" ]]; then
  systemctl is-active --quiet mongod && MONGOD_WAS_ACTIVE=true
  stage "Starting chrony and MongoDB"
  sudo -n systemctl start mongod
else
  stage "Starting chrony; OAI database is managed by Docker"
fi

STACK_STARTED=true
stage "Starting $CORE_BACKEND"
if [[ "$CORE_BACKEND" == "open5gs" ]]; then
  run_logged "$AUTOMATION_DIR/start_core.log" "$SCRIPTS_ROOT/start-core.sh" minimal-5g
  wait_for_process open5gs-amfd 60
  wait_for_process open5gs-smfd 60
  wait_for_process open5gs-upfd 60
  wait_for_process open5gs-udrd 60
  wait_for_process open5gs-bsfd 60
  stage "Waiting for Open5GS readiness"
  wait_for_log "BSF registration with NRF" "$CORE_LOG_DIR/bsf.log" 'NF registered \[Heartbeat:' 90
  wait_for_log "SMF registration with NRF" "$CORE_LOG_DIR/smf.log" 'NF registered \[Heartbeat:' 90
  wait_for_log "AMF registration with NRF" "$CORE_LOG_DIR/amf.log" 'NF registered \[Heartbeat:' 90
  wait_for_log "SMF-UPF PFCP association" "$CORE_LOG_DIR/smf.log" 'PFCP associated' 90
  wait_for_log "AMF discovery of SMF" "$CORE_LOG_DIR/amf.log" '\[SMF\] NFInstance associated' 90
else
  run_logged "$AUTOMATION_DIR/start_core.log" "$SCRIPTS_ROOT/start-core.sh"
  wait_for_container '^amf$' 120
  wait_for_container '^smf$' 120
  wait_for_container '^(upf|upf1)$' 120
  stage "Waiting for OAI Core readiness"
  wait_for_core_ready 180
  wait_for_oai_pfcp_association 120
fi

stage "Starting FlexRIC"
run_logged "$AUTOMATION_DIR/start_flexric.log" timeout 90 "$SCRIPTS_ROOT/start-flexric.sh" --background
wait_for_process nearRT-RIC 30

stage "Starting OAI gNB"
run_logged "$AUTOMATION_DIR/start_gnb.log" timeout 90 "$SCRIPTS_ROOT/start-gnb.sh" --background
wait_for_process nr-softmodem 30
wait_for_log "E2 Setup" "$FLEXRIC_LOG_DIR/flexric_stdout.txt" 'E2 SETUP-REQUEST' 90

if [[ ! "$GNB_CONFIG_DIR/get_rfsim_server_address.txt" -ef "$UE_CONFIG_DIR/get_rfsim_server_address.txt" ]]; then
  cp "$GNB_CONFIG_DIR/get_rfsim_server_address.txt" "$UE_CONFIG_DIR/get_rfsim_server_address.txt"
fi
start_capture

stage "Starting OAI UE $UE_NUMBER"
run_logged "$AUTOMATION_DIR/start_ue.log" timeout 120 "$SCRIPTS_ROOT/start-ue.sh" --background "$UE_NUMBER"
wait_for_process nr-uesoftmodem 30
wait_for_log "UE RRC connection" "$UE_LOG_DIR/ue${UE_NUMBER}_stdout.txt" 'NR_RRC_CONNECTED' 120

stage "Starting KPM CSV xApp"
setsid env TZ="$EXPERIMENT_TIMEZONE" OUTPUT_CSV_PATH="$KPM_DIR/KPI_Metrics.csv" \
  "$SCRIPTS_ROOT/start-xapp.sh" "$KPM_PERIOD_MS" \
  >"$RUN_DIR/flexric/xapp_stdout.log" 2>&1 &
XAPP_PID=$!

for _ in {1..20}; do
  kill -0 "$XAPP_PID" 2>/dev/null || break
  pgid_candidate=$(ps -o pgid= -p "$XAPP_PID" 2>/dev/null || true)
  pgid_candidate=${pgid_candidate//[[:space:]]/}
  if [[ "$pgid_candidate" == "$XAPP_PID" ]]; then
    XAPP_PGID=$pgid_candidate
    break
  fi
  XAPP_PGID=""
  sleep 0.1
done
kill -0 "$XAPP_PID" 2>/dev/null || die "KPM xApp exited; inspect $RUN_DIR/flexric/xapp_stdout.log"
[[ "$XAPP_PGID" == "$XAPP_PID" ]] || die "KPM xApp process group was not established"

elapsed=0
while [[ ! -f "$KPM_DIR/KPI_Metrics.csv" ]] || (( $(wc -l <"$KPM_DIR/KPI_Metrics.csv") < 2 )); do
  kill -0 "$XAPP_PID" 2>/dev/null || die "KPM xApp exited; inspect $RUN_DIR/flexric/xapp_stdout.log"
  ((elapsed >= 30)) && die "Timed out waiting for KPM samples"
  sleep 1
  ((elapsed += 1))
done

stage "Waiting for UE PDU session"
wait_for_pdu_session \
  "$UE_LOG_DIR/ue${UE_NUMBER}_stdout.txt" \
  "$CORE_LOG_DIR/amf.log" \
  120

PDU_IP=$(rg 'PDU Session Establishment Accept' "$UE_LOG_DIR/ue${UE_NUMBER}_stdout.txt" \
  | tail -n 1 | sed -E 's/.*UE IPv4:[[:space:]]*([^[:space:]\r]+).*/\1/')
printf 'PDU_IP=%q\n' "$PDU_IP" >>"$METADATA_DIR/run.env"

record_status "$METADATA_DIR/status_during.txt"

stage "Collecting idle baseline"
record_idle_phase baseline "$BASELINE_SECONDS"

if [[ "$RUN_DL" == true ]]; then
  stage "Generating downlink traffic: $DL_RATE for ${DL_DURATION}s"
  record_traffic_phase downlink_1 dl "$DL_RATE" "$DL_DURATION" "$TRAFFIC_DIR/downlink_client.log" \
    "$SCRIPTS_ROOT/traffic-dl.sh" "$UE_NUMBER" "$DL_RATE" "$DL_DURATION"
fi

if [[ "$RUN_DL" == true && "$RUN_UL" == true ]]; then
  stage "Collecting idle gap"
  record_idle_phase between_dl_ul "$BETWEEN_SECONDS"
fi

if [[ "$RUN_UL" == true ]]; then
  stage "Generating uplink traffic: $UL_RATE for ${UL_DURATION}s"
  record_traffic_phase uplink_1 ul "$UL_RATE" "$UL_DURATION" "$TRAFFIC_DIR/uplink_client.log" \
    "$SCRIPTS_ROOT/traffic-ul.sh" "$UE_NUMBER" "$UL_RATE" "$UL_DURATION"
fi

stage "Waiting for final KPM and PFCP reports"
record_idle_phase post_traffic "$POST_SECONDS"

EXPERIMENT_STATUS=complete
stage "Experiment completed"
