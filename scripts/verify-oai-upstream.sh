#!/bin/bash
# Rebuild every OAI source tree from its pinned upstream commit plus the local
# patches (in date order) and compare with the tree in src/. MATCH means the
# patches in patches/ are the complete list of local changes; DIFF lists the
# files that changed without a patch. See docs/OAI-UPSTREAM-CHANGES.md.
#
# Usage: scripts/verify-oai-upstream.sh [cache-dir]   (default ~/.cache/oai-upstream)
#        scripts/verify-oai-upstream.sh --into <dir> [cache-dir]
#   --into writes the rebuilt trees to <dir>/{oai-upf,oai-smf,flexric,oai-ran}
#   instead of comparing. A fresh clone uses `--into src` (the trees are not
#   committed). oai-smf and its common-src keep a .git at the pinned commit
#   because `lab.sh build` reads it.
# Network: GitHub/GitLab over HTTPS from the host (shallow fetch by SHA).
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
P=$ROOT/patches
INTO=
if [ "${1:-}" = --into ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --into <dir> [cache-dir]"; exit 2; }
  mkdir -p "$2"; INTO=$(cd "$2" && pwd); shift 2
  for t in oai-upf oai-smf flexric oai-ran; do
    [ ! -e "$INTO/$t" ] || { echo "$INTO/$t exists; refusing to overwrite"; exit 2; }
  done
fi
C=${1:-${XDG_CACHE_HOME:-$HOME/.cache}/oai-upstream}
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir -p "$C"
rc=0

fetch() {  # name url sha -> $C/name at sha
  local d=$C/$1
  if [ "$(git -C "$d" rev-parse HEAD 2>/dev/null)" != "$3" ]; then
    rm -rf "$d"; git init -q "$d" && git -C "$d" remote add origin "$2" &&
      git -C "$d" fetch -q --depth 1 origin "$3" && git -C "$d" checkout -q FETCH_HEAD || { echo "fetch $1 failed"; exit 2; }
  fi
}
tree() {  # name -> fresh copy of the cached upstream tree without .git
  rm -rf "$W/$1"; cp -a "$C/$1" "$W/$1"; find "$W/$1" -name .git -prune -exec rm -rf {} +
}
apply() {  # dir patch [patch(1) options]
  local d=$1 f=$2; shift 2
  (cd "$d" && patch -p1 -s --no-backup-if-mismatch "$@" < "$f") || { echo "  patch failed: ${f#$ROOT/}"; rc=1; }
}
compare() {  # label rebuilt local [extra diff options]
  local label=$1 a=$2 b=$3; shift 3
  if [ -n "$INTO" ]; then
    case $label in oai\ charts) return;; esac   # deploy/k8s/vendor is committed
    mv "$a" "$INTO/${b##*/}" && echo "WROTE  $INTO/${b##*/}"; return
  fi
  local out; out=$(diff -rq -x .git -x build -x ran_build -x '*.previous*' -x compile_commands.json "$@" "$a" "$b" 2>&1 | sed "s#$W/##")
  if [ -z "$out" ]; then echo "MATCH  $label"; else echo "DIFF   $label"; echo "$out" | sed 's/^/  /'; rc=1; fi
}

# --- OAI UPF: oai-cn5g-upf 9e93b63 (+ common-src ef4ddb0, common-build 7b20f7f)
fetch upf https://github.com/openairinterface/oai-cn5g-upf.git 9e93b6383803fd0eea2d18d9953670af17c0de64
fetch upf-common-src https://github.com/openairinterface/oai-cn5g-common-src.git ef4ddb0ee95ad00c4696f549e7486ba202eff825
fetch upf-common-build https://github.com/openairinterface/oai-cn5g-common-build.git 7b20f7ff8a29855fbfa35c0b913e12968db31337
fetch upf-common-ci https://github.com/openairinterface/oai-cn5g-common-ci.git 8471dc86e029641b938818e1c74f7e4f0369dd88
tree upf; tree upf-common-src; tree upf-common-build; tree upf-common-ci
rm -rf "$W/upf/src/common-src" "$W/upf/build/common-build" "$W/upf/ci-scripts/common"
mv "$W/upf-common-src" "$W/upf/src/common-src"; mv "$W/upf-common-build" "$W/upf/build/common-build"
mv "$W/upf-common-ci" "$W/upf/ci-scripts/common"
for x in oai-upf-00b7485-pfcp-urr-reporting oai-upf-xdp-mode oai-upf-cp-initiated-association oai-upf-build-jobs \
         oai-upf-00b7485-dl-qfi-from-access-pdr oai-upf-session-teardown-ue-ip-mapping oai-upf-teardown-best-effort \
         oai-upf-user-id-session-ttl oai-upf-urr-report-semantics; do
  apply "$W/upf" "$P/$x.patch"
done
compare "oai-upf" "$W/upf" "$ROOT/src/oai-upf"

# --- OAI SMF: oai-cn5g-smf d189066 (v2.2.0 line; common-src b5042f5)
fetch smf https://github.com/openairinterface/oai-cn5g-smf.git d18906656ca85b823cc68877e3c545353150c018
fetch smf-common-src https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-common-src.git b5042f5f52cbb0dd61e9a1421b34a9fc030c685f
fetch smf-common-build https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-common-build.git bd36b5c7ee802984c6948e61b8815afbbc63d42e
fetch smf-common-ci https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-common-ci.git 3407df4f295246ab12718488745d7923c4023f43
tree smf; tree smf-common-src; tree smf-common-build; tree smf-common-ci
rm -rf "$W/smf/src/oai-cn5g-common-src" "$W/smf/build/common-build" "$W/smf/ci-scripts/common"
mv "$W/smf-common-src" "$W/smf/src/oai-cn5g-common-src"; mv "$W/smf-common-build" "$W/smf/build/common-build"
mv "$W/smf-common-ci" "$W/smf/ci-scripts/common"
apply "$W/smf/src/oai-cn5g-common-src" "$P/oai-smf-v2.2.0-pfcp-up-features-extension.patch"
apply "$W/smf" "$P/oai-smf-v2.2.0-stale-session-release.patch"
apply "$W/smf/src/oai-cn5g-common-src" "$P/oai-smf-v2.2.0-common-src-user-id-length.patch"
apply "$W/smf" "$P/oai-smf-v2.2.0-user-id-urr-config-ttl.patch"
apply "$W/smf" "$P/oai-smf-v2.2.0-reassociation-up-features.patch"
if [ -n "$INTO" ]; then
  cp -a "$C/smf/.git" "$W/smf/.git"
  cp -a "$C/smf-common-src/.git" "$W/smf/src/oai-cn5g-common-src/.git"
fi
compare "oai-smf" "$W/smf" "$ROOT/src/oai-smf"

# --- FlexRIC ef6d722 (xApp, nearRT-RIC)
fetch flexric https://gitlab.eurecom.fr/mosaic5g/flexric.git ef6d722f22191eea74089966983da1f5ec1fedd4
tree flexric; F=$W/flexric
apply "$F" "$P/flexric-working-tree.patch"
cp "$P"/flexric/examples/xApp/c/metrics_factory.[ch] "$F/examples/xApp/c/"
cp "$P"/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_influxdb.c "$P"/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c "$F/examples/xApp/c/monitor/"
apply "$F" "$P/flexric-k8s-runtime.patch"
apply "$F" "$P/flexric-xapp-urr-receiver.patch" -l --fuzz=3   # generated with different blank lines
apply "$F" "$P/flexric-xapp-epoch-kpm-watchdog.patch"
apply "$F" "$P/flexric-whitespace-exact.patch"   # blank-line/indent drift left by the fuzzed patch above
apply "$F" "$P/flexric-epoll-eintr.patch"
compare "flexric" "$F" "$ROOT/src/flexric"

# --- OAI RAN 26efcc4 (gNB, nrUE); embedded FlexRIC submodule ef6d722
fetch ran https://gitlab.eurecom.fr/oai/openairinterface5g.git 26efcc498931b8f6979c39f9f44400f3c965fdc4
tree ran; R=$W/ran
(cd "$R" && git apply --exclude=openair2/E2AP/flexric "$P/oai-ran-working-tree.patch") || { echo "  patch failed: oai-ran-working-tree"; rc=1; }
rm -rf "$R/openair2/E2AP/flexric"; tree flexric; mv "$W/flexric" "$R/openair2/E2AP/flexric"; E=$R/openair2/E2AP/flexric
apply "$E" "$P/flexric-working-tree.patch"
cp "$P"/flexric/examples/xApp/c/metrics_factory.[ch] "$E/examples/xApp/c/"
cp "$P"/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_influxdb.c "$E/examples/xApp/c/monitor/"
apply "$E" "$P/flexric-epoll-eintr.patch"
# The embedded copy keeps the NIST 20/08 xapp_kpm_moni_write_to_csv.c (its CMakeLists references it)
cp "$P"/flexric-embedded-ran/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c "$E/examples/xApp/c/monitor/"
compare "oai-ran (+embedded flexric)" "$R" "$ROOT/src/oai-ran"

# --- OAI Helm charts 7925f93 (deploy/k8s/vendor)
fetch charts https://gitlab.eurecom.fr/oai/orchestration/charts.git 7925f939ea36a3c4c1df5525f3718ce8470f6b3f
tree charts
(cd "$W/charts" && git apply "$P/oai-charts-7925f93-lab.patch") || { echo "  patch failed: oai-charts"; rc=1; }
compare "oai charts" "$W/charts" "$ROOT/deploy/k8s/vendor" -x multus.yaml -x PROVENANCE.json

exit $rc
