#!/usr/bin/env bash
exec "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../scripts/legacy/compose/run-experiment.sh" "$@"
