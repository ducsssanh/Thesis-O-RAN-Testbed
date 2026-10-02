#!/usr/bin/env bash
# Internal helper: called after elevation, before detaching from the terminal.
set -e
log_file=${1:?Missing launcher log}
shift
setsid stdbuf -oL -eL "$@" </dev/null >"$log_file" 2>&1 &
printf '%s\n' "$!"
