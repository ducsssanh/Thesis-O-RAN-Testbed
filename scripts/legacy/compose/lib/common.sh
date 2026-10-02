#!/usr/bin/env bash
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../env.sh"
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
require_commands() {
    local cmd
    for cmd in "$@"; do command -v "$cmd" >/dev/null || die "Missing command: $cmd"; done
}
require_file() { [[ -f "$1" ]] || die "Missing file: $1"; }
require_yq() {
    require_commands yq
    yq --version | grep -q 'mikefarah/yq.*version v4' || die 'Mike Farah yq v4 is required.'
}
