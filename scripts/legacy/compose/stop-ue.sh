#!/usr/bin/env bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: stop-ue.sh [UE_NUMBER=1]'
    exit 0
fi
set -e
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
UE_NUMBER=${1:-1}
[[ $UE_NUMBER =~ ^[1-9][0-9]*$ ]] || { echo 'Usage: stop-ue.sh [UE_NUMBER]' >&2; exit 2; }
"$SCRIPTS_ROOT/lib/stop-process.sh" ue "$UE_NUMBER"
exec "$SCRIPTS_ROOT/stop-ue-network.sh" "$UE_NUMBER"
