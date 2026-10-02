set -euo pipefail
msg() { echo -ne "\e[35m[5gdeploy] \e[94m"; echo -n "$*"; echo -e "\e[0m"; }
die() { msg "$*"; exit 1; }
with_retry() { while ! "$@"; do sleep 0.2; done }
CLEANUPS='set -euo pipefail'
cleanup() { msg Performing cleanup; ash -c "$CLEANUPS"; trap - EXIT SIGTERM; }
trap cleanup EXIT SIGTERM

msg Setting healthy state
touch /run/5gdeploy-bridge-is-healthy
msg Idling
tail -f &
wait $!