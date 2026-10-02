#!/usr/bin/env bash
set -e
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/common.sh"
component=${1:?Usage: stop-process.sh gnb|ue|flexric [UE_NUMBER]}
case "$component" in
    gnb) process=nr-softmodem; config="$GNB_CONFIG_DIR/gnb.conf" ;;
    ue) process=nr-uesoftmodem; config="$UE_CONFIG_DIR/ue${2:-}.conf"
        [[ ${2:-} =~ ^[1-9][0-9]*$ ]] || die 'UE number must be positive' ;;
    flexric) process=nearRT-RIC; config="$FLEXRIC_CONFIG_DIR/flexric.conf" ;;
    *) die "Unknown component: $component" ;;
esac
# Match the exact config argument to avoid stopping other testbed instances.
pids=()
while read -r pid; do
    [[ -n $pid ]] || continue
    if sudo python3 - "$pid" "$config" <<'PYCHECK'
import pathlib, sys
try:
    args = pathlib.Path('/proc', sys.argv[1], 'cmdline').read_bytes().split(b'\0')
    sys.exit(0 if sys.argv[2].encode() in args else 1)
except (FileNotFoundError, PermissionError):
    sys.exit(1)
PYCHECK
    then pids+=("$pid"); fi
done < <(pgrep -x "$process" || true)
((${#pids[@]})) || exit 0
sudo kill -TERM "${pids[@]}" 2>/dev/null || true
for ((attempt=0; attempt<10; attempt++)); do
    live=()
    for pid in "${pids[@]}"; do sudo kill -0 "$pid" 2>/dev/null && live+=("$pid"); done
    ((${#live[@]})) || exit 0
    pids=("${live[@]}")
    sleep 1
done
sudo kill -KILL "${pids[@]}" 2>/dev/null || true
