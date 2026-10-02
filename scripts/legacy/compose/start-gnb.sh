#!/bin/bash
# Modified 2026-09-15: ported NIST testbed logic to the Codebase layout.
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
source "$SCRIPTS_ROOT/lib/common.sh"
if [[ ${1:-} == --help ]]; then
    echo 'Usage: start-gnb.sh [--background] '
    exit 0
fi
if [[ ${1:-} == --background ]]; then
    shift
    exec "$SCRIPTS_ROOT/lib/start-background.sh" gnb "$@"
fi
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

DISABLE_NRSCOPE_IF_INSTALLED=${DISABLE_NRSCOPE_IF_INSTALLED:-false}


set -e
[[ -x "$RAN_BUILD_DIR/nr-softmodem" ]] || die "Missing binary: $RAN_BUILD_DIR/nr-softmodem; build the component first."
require_file "$GNB_CONFIG_DIR/gnb.conf"
SCRIPT_DIR="$SCRIPTS_ROOT"

ADDITIONAL_FLAGS=""
if [ -f "$RAN_SRC/cmake_targets/ran_build/build/libtelnetsrv.so" ]; then
    echo "Found telnet server library. Enabling telnet server..."
    TELNET_ADDRESS=127.0.0.1
    TELNET_PORT=9099
    ADDITIONAL_FLAGS="$ADDITIONAL_FLAGS --telnetsrv"
    ADDITIONAL_FLAGS="$ADDITIONAL_FLAGS --telnetsrv.shrmod ci,o1"
    ADDITIONAL_FLAGS="$ADDITIONAL_FLAGS --telnetsrv.listenaddr $TELNET_ADDRESS"
    ADDITIONAL_FLAGS="$ADDITIONAL_FLAGS --telnetsrv.listenport $TELNET_PORT"
    ADDITIONAL_FLAGS="$ADDITIONAL_FLAGS --telnetsrv.listenstdin 1"
fi
IMSCOPE=false
if [ "$DISABLE_NRSCOPE_IF_INSTALLED" = false ] && [ -f "$RAN_SRC/cmake_targets/ran_build/build/libimscope.so" ]; then
    echo "Enabling ImScope..."
    ADDITIONAL_FLAGS="$ADDITIONAL_FLAGS --imscope -d --log_config.global_log_options utc_time"
    IMSCOPE=true
fi

cd "$CODEBASE_ROOT"

# Write the hostname IP to the get_rfsim_server_address.txt file
HOSTNAME_IP=$(hostname -I | awk '{print $1}')
mkdir -p "$GNB_CONFIG_DIR"
echo "$HOSTNAME_IP" >"$GNB_CONFIG_DIR/get_rfsim_server_address.txt"
# The local UE launcher reads its own endpoint file. Keep it in sync when
# starting components manually, as well as through the experiment runner.
mkdir -p "$UE_CONFIG_DIR"
if [[ ! "$GNB_CONFIG_DIR/get_rfsim_server_address.txt" -ef "$UE_CONFIG_DIR/get_rfsim_server_address.txt" ]]; then
    cp "$GNB_CONFIG_DIR/get_rfsim_server_address.txt" "$UE_CONFIG_DIR/get_rfsim_server_address.txt"
fi

mkdir -p "$GNB_LOG_DIR"
if [ -f "$GNB_LOG_DIR/gnb_stdout.txt" ]; then
    sudo chown "${SUDO_USER:-$USER}" "$GNB_LOG_DIR/gnb_stdout.txt"
fi
>"$GNB_LOG_DIR/gnb_stdout.txt"

cd "$RAN_SRC/cmake_targets/ran_build/build"

# Code from (https://github.com/OPENAIRINTERFACE/openairinterface5g/blob/develop/radio/rfsimulator/README.md#5g-case):
# sudo ./nr-softmodem -O "$GNB_CONFIG_DIR/gnb.conf" $RADIO_ARGS --gNBs.[0].min_rxtxtime 6 $ADDITIONAL_FLAGS

RADIO_TYPE=$(cat "$GNB_CONFIG_DIR/radio_type.txt" 2>/dev/null || echo "RFSIM")
if [ "$RADIO_TYPE" = "ZMQ" ]; then
    ZMQ_TX_PORT=4556
    ZMQ_RX_PORT=4557
    UE_NUMBER=1
    UE_NS_IP=$(python3 "$SCRIPTS_ROOT/lib/fetch-nth-ip.py" "10.201.0.0/16" $(((UE_NUMBER * 4) + 1)))
    RADIO_ARGS="--device.name oai_zmqdevif --zmq.[0].tx_channels tcp://0.0.0.0:$ZMQ_TX_PORT --zmq.[0].rx_channels tcp://$UE_NS_IP:$ZMQ_RX_PORT"
elif [ "$RADIO_TYPE" = "USRP" ]; then
    RADIO_ARGS=""
else
    RADIO_ARGS="--rfsim --rfsimulator.[0].serveraddr server --rfsimulator.[0].options chanmod"
fi

if [ "$IMSCOPE" = true ]; then # ImScope GUI cannot be run with sudo
    script -q -f -c "./nr-softmodem -O \"$GNB_CONFIG_DIR/gnb.conf\" $RADIO_ARGS --gNBs.[0].min_rxtxtime 6 $ADDITIONAL_FLAGS" "$GNB_LOG_DIR/gnb_stdout.txt"
else
    sudo script -q -f -c "./nr-softmodem -O \"$GNB_CONFIG_DIR/gnb.conf\" $RADIO_ARGS --gNBs.[0].min_rxtxtime 6 $ADDITIONAL_FLAGS" "$GNB_LOG_DIR/gnb_stdout.txt"
fi
