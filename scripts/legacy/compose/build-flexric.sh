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
    echo 'Usage: build-flexric.sh [--install-deps]'
    echo 'Environment: BUILD_JOBS, CLEAN_INSTALL=false, DEBUG_SYMBOLS=false, APPLY_PATCHES=true'
    exit 0
fi
[[ $# == 0 || ( $# == 1 && $1 == --install-deps ) ]] || die 'Usage: build-flexric.sh [--install-deps]'
BUILD_JOBS=${BUILD_JOBS:-$(nproc)}
[[ $BUILD_JOBS =~ ^[1-9][0-9]*$ ]] || die 'BUILD_JOBS must be positive'
require_file "$FLEXRIC_SRC/CMakeLists.txt"
if [[ ${1:-} == --install-deps ]]; then
    sudo apt-get install -y build-essential automake bison flex libsctp-dev python3 cmake-curses-gui libpcre2-dev python3-dev swig
fi
require_commands gcc g++ cmake make swig
[[ ${APPLY_PATCHES:-true} == false ]] || "$SCRIPTS_ROOT/lib/apply-patches.sh" flexric
current_port=$(sed -nE 's/.*e2ap_server_port *= *([0-9]+);/\1/p' "$FLEXRIC_SRC/src/agent/e2_agent_api.c")
[[ $current_port == 36421 ]] || die "Expected the existing E2 port 36421, found: $current_port"
if [[ ${CLEAN_INSTALL:-false} == true ]]; then rm -rf -- "$FLEXRIC_SRC/build"; fi
build_type=Release
[[ ${DEBUG_SYMBOLS:-false} != true ]] || build_type=Debug
export CFLAGS="-Wno-error=incompatible-pointer-types"
export CXXFLAGS="-Wno-error=incompatible-pointer-types"
CC=gcc CXX=g++ cmake -S "$FLEXRIC_SRC" -B "$FLEXRIC_SRC/build" \
    -DCMAKE_INSTALL_PREFIX="$FLEXRIC_PREFIX" -DXAPP_DB=NONE_XAPP \
    -DE2AP_VERSION=E2AP_V3 -DKPM_VERSION=KPM_V3_00 -DCMAKE_BUILD_TYPE="$build_type"
make -C "$FLEXRIC_SRC/build" -j"$BUILD_JOBS"
make -C "$FLEXRIC_SRC/build" install
"$SCRIPTS_ROOT/configure-flexric.sh"
