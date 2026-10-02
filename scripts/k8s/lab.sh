#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
case "${1:-}" in
  check|resume|certs|prepare|cutover|rollback|rollout|restart-upf|build-ei|build-xapp|gate-ei|gate-xapp|experiment|new-run)
    exec python3 "$ROOT/scripts/k8s/staged.py" "$@" ;;
  up)
    for arg in "$@"; do
      if [[ "$arg" == nonrt || "$arg" == near-rt || "$arg" == ran || "$arg" == core ]]; then
        exec python3 "$ROOT/scripts/k8s/staged.py" "$@"
      fi
    done ;;
  status)
    exec python3 "$ROOT/scripts/k8s/staged.py" "$@" ;;
esac
exec python3 "$ROOT/scripts/k8s/lab.py" "$@"
