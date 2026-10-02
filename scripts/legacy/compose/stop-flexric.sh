#!/usr/bin/env bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: stop-flexric.sh'
    exit 0
fi
set -e
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
exec "$SCRIPTS_ROOT/lib/stop-process.sh" flexric
