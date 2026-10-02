#!/bin/bash
#
# NIST-developed software is provided by NIST as a public service. You may use,
# copy, and distribute copies of the software in any medium, provided that you
# keep intact this entire notice. You may improve, modify, and create derivative
# works of the software or any portion of the software, and you may copy and
# distribute such modifications or works. Modified works should carry a notice
# stating that you changed the software and should note the date and nature of
# any such change. Please explicitly acknowledge the National Institute of
# Standards and Technology as the source of the software.
#
# NIST-developed software is expressly provided "AS IS." NIST MAKES NO WARRANTY
# OF ANY KIND, EXPRESS, IMPLIED, IN FACT, OR ARISING BY OPERATION OF LAW,
# INCLUDING, WITHOUT LIMITATION, THE IMPLIED WARRANTY OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND DATA ACCURACY. NIST
# NEITHER REPRESENTS NOR WARRANTS THAT THE OPERATION OF THE SOFTWARE WILL BE
# UNINTERRUPTED OR ERROR-FREE, OR THAT ANY DEFECTS WILL BE CORRECTED. NIST DOES
# NOT WARRANT OR MAKE ANY REPRESENTATIONS REGARDING THE USE OF THE SOFTWARE OR
# THE RESULTS THEREOF, INCLUDING BUT NOT LIMITED TO THE CORRECTNESS, ACCURACY,
# RELIABILITY, OR USEFULNESS OF THE SOFTWARE.
#
# You are solely responsible for determining the appropriateness of using and
# distributing the software and you assume all risks associated with its use,
# including but not limited to the risks and costs of program errors, compliance
# with applicable laws, damage to or loss of data, programs or equipment, and
# the unavailability or interruption of operation. This software is not intended
# to be used in any situation where a failure could cause risk of injury or
# damage to property. The software developed by NIST employees is not subject to
# copyright protection within the United States.


# Modified 2026-09-15: ported NIST testbed logic to the Codebase layout.
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
set -e
source "$SCRIPTS_ROOT/lib/common.sh"
if [[ ${1:-} == --help ]]; then
    echo 'Usage: build-ran.sh [--install-deps]'
    echo 'Builds UE then gNB in src/oai-ran. Environment: RADIO_TYPE=SIMU, CLEAN_INSTALL=false, DEBUG_SYMBOLS=false, NRSCOPE_GUI=false, TELNET_SERVER=true, APPLY_PATCHES=true'
    exit 0
fi
[[ $# == 0 || ( $# == 1 && $1 == --install-deps ) ]] || die 'Usage: build-ran.sh [--install-deps]'
RADIO_TYPE=${RADIO_TYPE:-SIMU}
case "$RADIO_TYPE" in SIMU|ZMQ|USRP) ;; *) die 'RADIO_TYPE must be SIMU, ZMQ or USRP' ;; esac
require_commands gcc g++ cmake ninja
require_file "$RAN_SRC/cmake_targets/build_oai"
require_file "$RAN_SRC/openair2/E2AP/flexric/src/agent/e2_agent_api.c"
printf 'RAN source: %s\nEmbedded FlexRIC: %s\n' \
    "$(realpath -- "$RAN_SRC")" "$(realpath -- "$RAN_SRC/openair2/E2AP/flexric")"
if [[ $(realpath -- "$RAN_SRC") != "$(realpath -m -- "$CODEBASE_ROOT/src/oai-ran")" ]]; then
    echo 'WARNING: RAN_SRC overrides the Codebase source directory. Check this path before building.' >&2
fi
if [[ $RADIO_TYPE == ZMQ ]]; then
    require_commands pkg-config
    pkg-config --exists libzmq libczmq || die 'Install libzmq and libczmq before building ZMQ.'
fi
if [[ ${APPLY_PATCHES:-true} == true ]]; then
    "$SCRIPTS_ROOT/lib/apply-patches.sh" ran
    "$SCRIPTS_ROOT/lib/apply-patches.sh" flexric-agent "$RAN_SRC/openair2/E2AP/flexric"
fi
current_port=$(sed -nE 's/.*e2ap_server_port *= *([0-9]+);/\1/p' "$RAN_SRC/openair2/E2AP/flexric/src/agent/e2_agent_api.c")
[[ $current_port == 36421 ]] || die "Expected the existing E2 port 36421, found: $current_port"
cd "$RAN_SRC"
source oaienv
cd "$RAN_SRC/cmake_targets"
[[ ${1:-} != --install-deps ]] || ./build_oai -I
flags=(-w "$RADIO_TYPE")
[[ ${DEBUG_SYMBOLS:-false} != true ]] || flags+=(-g)
# Clean only once: gNB and UE now share a single build directory.
clean=()
[[ ${CLEAN_INSTALL:-false} != true ]] || clean=(-C)
./build_oai --ninja --nrUE "${flags[@]}" "${clean[@]}"
gnb_flags=(--cmake-opt -DE2AP_VERSION=E2AP_V3 --cmake-opt -DKPM_VERSION=KPM_V3_00)
[[ ${TELNET_SERVER:-true} != true ]] || gnb_flags+=(--build-lib telnetsrv)
[[ ${NRSCOPE_GUI:-false} != true ]] || gnb_flags+=(--build-lib imscope)
./build_oai --ninja --gNB --build-e2 "${gnb_flags[@]}" "${flags[@]}"
