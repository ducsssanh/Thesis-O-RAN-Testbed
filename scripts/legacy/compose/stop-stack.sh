#!/usr/bin/env bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: stop-stack.sh [UE_NUMBER=1]'
    exit 0
fi
set -e
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
UE_NUMBER=${1:-1}
status=0
"$SCRIPTS_ROOT/stop-ue.sh" "$UE_NUMBER" || status=1
"$SCRIPTS_ROOT/stop-gnb.sh" || status=1
"$SCRIPTS_ROOT/stop-flexric.sh" || status=1
"$SCRIPTS_ROOT/stop-core.sh" || status=1
exit "$status"
