#!/usr/bin/env bash
set -e
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/common.sh"
component=${1:?Usage: start-background.sh gnb|ue|flexric [args]}
shift
case "$component" in
    gnb) process=nr-softmodem; log_dir=$GNB_LOG_DIR; name=gnb ;;
    ue) process=nr-uesoftmodem; log_dir=$UE_LOG_DIR; name=ue${1:-1} ;;
    flexric) process=nearRT-RIC; log_dir=$FLEXRIC_LOG_DIR; name=flexric ;;
    *) die "Unknown component: $component" ;;
esac
require_commands setsid stdbuf pgrep
if [[ $component == ue ]]; then
    [[ ${1:-1} =~ ^[1-9][0-9]*$ ]] || die 'UE number must be positive'
    if "$SCRIPTS_ROOT/lib/ue-status.sh" | grep -qw "$name"; then echo "$name already running"; exit 0; fi
elif pgrep -x "$process" >/dev/null; then
    echo "$component already running"
    exit 0
fi
mkdir -p "$log_dir"
launcher_log="$log_dir/${name}_launcher.log"
if [[ $component == flexric ]]; then launcher_log="$log_dir/flexric_stdout.txt"; fi
kill_command=(kill)
if [[ $component == flexric ]]; then
    setsid stdbuf -oL -eL "$SCRIPTS_ROOT/start-$component.sh" "$@" \
        </dev/null >"$launcher_log" 2>&1 &
    pid=$!
else
    # Authenticate and elevate while still attached to the caller's terminal.
    # A sudo timestamp associated with that terminal cannot be relied on after setsid.
    sudo -v
    launch_env=()
    for variable in CODEBASE_ROOT RAN_SRC FLEXRIC_SRC UPF_SRC DEPLOY_SRC CONFIG_ROOT \
        ARTIFACT_ROOT PATCH_ROOT CORE_OPTIONS CORE_COMPOSE_DIR LOG_ROOT FLEXRIC_PREFIX EXPERIMENT_ROOT; do
        launch_env+=("$variable=${!variable}")
    done
    pid=$(sudo -n -- env "${launch_env[@]}" DISABLE_NRSCOPE_IF_INSTALLED=true \
        bash "$SCRIPTS_ROOT/lib/launch-detached.sh" \
        "$launcher_log" "$SCRIPTS_ROOT/start-$component.sh" "$@")
    [[ $pid =~ ^[0-9]+$ ]] || die "Invalid launcher PID: $pid"
    kill_command=(sudo -n kill)
fi
for ((attempt=0; attempt<120; attempt++)); do
    "${kill_command[@]}" -0 "$pid" 2>/dev/null || { cat "$launcher_log" >&2; die "$component launcher exited"; }
    if [[ $component == ue ]]; then
        if "$SCRIPTS_ROOT/lib/ue-status.sh" | grep -qw "$name"; then echo "$name started"; exit 0; fi
    elif pgrep -x "$process" >/dev/null; then
        echo "$component started"
        exit 0
    fi
    sleep 0.5
done
"${kill_command[@]}" -TERM -- "-$pid" 2>/dev/null || true
die "Timed out starting $component; inspect $launcher_log"
