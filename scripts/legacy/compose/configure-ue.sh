#!/bin/bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: configure-ue.sh [UE_NUMBER ...] (default: 3 2 1)'
    exit 0
fi
# Modified 2026-09-15: ported NIST testbed logic to the Codebase layout.
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
source "$SCRIPTS_ROOT/lib/common.sh"
require_yq
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

# Exit immediately if a command fails
set -e

RADIO_TYPE="${RADIO_TYPE:-SIMU}" # Set to "SIMU", "ZMQ", or "USRP"


SCRIPT_DIR="$SCRIPTS_ROOT"
cd "$CODEBASE_ROOT"

CLEAR_CONFIGS=false

# Support input argument for the UE number(s), for example:
# "$SCRIPTS_ROOT/configure-ue.sh" --> configures UE 1, 2, and 3
# "$SCRIPTS_ROOT/configure-ue.sh" 2 --> configures UE 2
# "$SCRIPTS_ROOT/configure-ue.sh" 4 5 6 --> configures UE 4, 5, and 6
UE_NUMBERS=("$@")
if [ ${#UE_NUMBERS[@]} -eq 0 ]; then
    UE_NUMBERS=(3 2 1)
    CLEAR_CONFIGS=true
fi
# Check if the input is a number
for i in "${UE_NUMBERS[@]}"; do
    if ! [[ "$i" =~ ^[0-9]+$ ]]; then
        echo "ERROR: UE number must be a number."
        exit 1
    fi
    if [ "$i" -lt 1 ]; then
        echo "ERROR: UE number must be greater than or equal to 1."
        exit 1
    fi
    echo "UE $i will be configured."
done

# Ensure the correct YAML editor is installed
require_yq

# Function to update or add configuration properties in .conf files, considering sections and uncommenting if needed
update_conf() {
    echo "update_conf($1, $2, $3)"
    local FILE_PATH="$1"
    local PROPERTY="$2"
    local VALUE="$3"

    # Check if the property exists in the file, and update or append it accordingly
    if grep -q "^\s*$PROPERTY\s*=" "$FILE_PATH"; then
        # Update existing property's value
        sed -i "s|^\(\s*$PROPERTY\s*=\).*|\1 $VALUE;|" "$FILE_PATH"
    else
        # Append new property-value pair if it does not exist
        echo "$PROPERTY = $VALUE;" >>"$FILE_PATH"
    fi
}

# Function to comment out a line in a file
comment_out() {
    local FILE_PATH="$1"
    local STRING="$2"
    sed -i "s|^\(\s*\)$STRING|#\1$STRING|" "$FILE_PATH"
}

# Read the PLMN value from the 5G Core, and apply it to the beginning of the UE's IMSI
YAML_PATH="$CORE_OPTIONS"
if [ ! -f "$YAML_PATH" ]; then
    echo "Configuration not found in $YAML_PATH, please generate the configuration with configure-core.sh first."
    exit 1
fi
# Read PLMN and TAC values from the YAML file using sed
PLMN=$(sed -n 's/^plmn: \([0-9]*\)/\1/p' "$YAML_PATH" | tr -d '[:space:]')
TAC=$(sed -n 's/^tac: \([0-9]*\)/\1/p' "$YAML_PATH" | tr -d '[:space:]')
# Check if PLMN and TAC values are found, if not, exit with an error message
if [ -z "$PLMN" ]; then
    echo "PLMN not configured in $YAML_PATH, please generate the configuration with configure-core.sh first."
    exit 1
fi
if [ -z "$TAC" ]; then
    echo "TAC not configured in $YAML_PATH, please generate the configuration with configure-core.sh first."
    exit 1
fi

# Parse Mobile Country Code (MCC) and Mobile Network Code (MNC) from PLMN
MCC="${PLMN:0:3}"
if [ ${#PLMN} -eq 5 ]; then
    MNC="${PLMN:3:2}"
elif [ ${#PLMN} -eq 6 ]; then
    MNC="${PLMN:3:3}"
fi
MNC_LENGTH=${#MNC}

echo "PLMN value: $PLMN"
echo "TAC value: $TAC"
echo "MCC value: $MCC"
echo "MNC value: $MNC"
echo "MNC_LENGTH value: $MNC_LENGTH"

# Configure the DNN, SST, and SD values
CURRENT_DNN=$(yq eval '.slices[0].dnn' "$YAML_PATH")
SST=$(yq eval '.slices[0].sst' "$YAML_PATH")
SD=$(yq eval '.slices[0].sd' "$YAML_PATH")
if [[ -z "$CURRENT_DNN" || "$CURRENT_DNN" == "null" ]]; then
    echo "DNN is not set in "$YAML_PATH", please ensure that \"dnn\" is set."
    exit 1
fi
if [[ -z "$SST" || -z "$SD" || "$SST" == "null" || "$SD" == "null" ]]; then
    echo "SST or SD is not set in "$YAML_PATH", please ensure that \"slices[].sst\" and \"slices[].sd\" are set."
    exit 1
fi

# SST/SD are configured in options.yaml as hex without 0x prefix.
SST_HEX="${SST#0x}"
SST_HEX="${SST_HEX#0X}"
SST_HEX="${SST_HEX^^}"
SD_HEX="${SD#0x}"
SD_HEX="${SD_HEX#0X}"
SD_HEX="${SD_HEX^^}"

if [[ ! "$SST_HEX" =~ ^[0-9A-F]{1,2}$ ]]; then
    echo "Invalid slices[0].sst '$SST'. Use hexadecimal (00-FF), no 0x prefix."
    exit 1
fi
if [[ ! "$SD_HEX" =~ ^[0-9A-F]{1,6}$ ]]; then
    echo "Invalid slices[0].sd '$SD'. Use hexadecimal (up to 6 hex digits), no 0x prefix."
    exit 1
fi

SST_DEC=$((16#$SST_HEX))
SD_HEX=$(printf "%06X" "$((16#$SD_HEX))")

OGSTUN_IPV4=$(yq eval '.ogstun_ipv4' "$YAML_PATH")
OGSTUN_IPV6=$(yq eval '.ogstun_ipv6' "$YAML_PATH")
if [[ "$OGSTUN_IPV4" == "null" || -z "$OGSTUN_IPV4" ]]; then
    echo "Missing parameter in "$YAML_PATH": ogstun_ipv4"
    exit 1
fi
if [[ "$OGSTUN_IPV6" == "null" || -z "$OGSTUN_IPV6" ]]; then
    echo "Missing parameter in "$YAML_PATH": ogstun_ipv6"
    exit 1
fi

echo "Saving configuration file example..."
mkdir -p "$UE_CONFIG_DIR"
mkdir -p "$UE_LOG_DIR"
echo "$RADIO_TYPE" >"$UE_CONFIG_DIR/radio_type.txt"

if [ "$RADIO_TYPE" = "SIMU" ] || [ "$RADIO_TYPE" = "ZMQ" ]; then
    echo "Using the channelmod_rfsimu.conf file for the SIMU/ZMQ channel model."
    if [ ! -e "$UE_CONFIG_DIR/channelmod_rfsimu.conf" ]; then
        cp "$RAN_SRC/targets/PROJECTS/GENERIC-NR-5GC/CONF/channelmod_rfsimu.conf" "$UE_CONFIG_DIR/channelmod_rfsimu.conf"
    fi
else
    echo "Using the channelmod_rfsimu_LEO_satellite.conf channel model."
    # Use the default channelmod_rfsimu_LEO_satellite.conf file
    if [ ! -e "$UE_CONFIG_DIR/channelmod_rfsimu.conf" ]; then
        cp "$RAN_SRC/targets/PROJECTS/GENERIC-NR-5GC/CONF/channelmod_rfsimu_LEO_satellite.conf" "$UE_CONFIG_DIR/channelmod_rfsimu.conf"
    fi
fi

UE_CREDENTIAL_GENERATOR_SCRIPT="$SCRIPTS_ROOT/lib/ue-credentials.sh"
if [ ! -f "$UE_CREDENTIAL_GENERATOR_SCRIPT" ]; then
    echo "ERROR: Cannot find $UE_CREDENTIAL_GENERATOR_SCRIPT to generate UE subscriber credentials."
    exit 1
fi

for UE_NUMBER in "${UE_NUMBERS[@]}"; do
    cp "$RAN_SRC"/targets/PROJECTS/GENERIC-NR-5GC/CONF/ue.conf "$UE_CONFIG_DIR/ue$UE_NUMBER.conf"

    # Fetch the UE's OPc, IMEI, IMSI, KEY, and NAMESPACE
    read -r UE_OPC UE_IMEI UE_IMSI UE_KEY UE_NAMESPACE < <("$UE_CREDENTIAL_GENERATOR_SCRIPT" "$UE_NUMBER" "$PLMN")

    # Unique identifier for the UE within the mobile network. Used by the network to identify the UE during authentication. It ensures that the UE is correctly identified by the network.
    update_conf "$UE_CONFIG_DIR/ue$UE_NUMBER.conf" "imsi" "\"$UE_IMSI\""

    # Cryptographic key shared between the UE and the network, used for encryption during the authentication process.
    update_conf "$UE_CONFIG_DIR/ue$UE_NUMBER.conf" "key" "\"$UE_KEY\""

    # Operator key for the Milenage Authentication and Key Agreement algorithm used for encryption during the authentication process.
    update_conf "$UE_CONFIG_DIR/ue$UE_NUMBER.conf" "opc" "\"$UE_OPC\""

    # Configure the PDU sessions (DNN, SST, SD)
    update_conf "$UE_CONFIG_DIR/ue$UE_NUMBER.conf" "pdu_sessions" "({ dnn = \"$CURRENT_DNN\"; nssai_sst = $SST_DEC; nssai_sd = 0x$SD_HEX; })"

    "$SCRIPTS_ROOT/lib/add-channel-model.sh" ue "rfsimu_channel_ue$UE_NUMBER"

    # Finally, ensure that it is referencing the channelmod_rfsimu.conf file
    sed -i "s|channelmod_rfsimu_LEO_satellite.conf|channelmod_rfsimu.conf|" "$UE_CONFIG_DIR/ue$UE_NUMBER.conf"
    if ! grep -q "@include \"channelmod_rfsimu.conf\"" "$UE_CONFIG_DIR/ue$UE_NUMBER.conf"; then
        echo "" >>"$UE_CONFIG_DIR/ue$UE_NUMBER.conf"
        echo "@include \"channelmod_rfsimu.conf\"" >>"$UE_CONFIG_DIR/ue$UE_NUMBER.conf"
    fi

    UE_IPV4=""
    if [ "$UE_NUMBER" -gt 3 ]; then
        "$SCRIPTS_ROOT/lib/register-subscriber.sh" --imsi "$UE_IMSI" --key "$UE_KEY" --opc "$UE_OPC" --apn "$CURRENT_DNN"
        echo "Subscriber saved. Re-run configure-core.sh before starting the core to include new UEs."
    fi

    echo
    echo "Successfully configured UE ${UE_NUMBER}."
    echo "    OPc:  $UE_OPC"
    echo "    IMEI: $UE_IMEI"
    echo "    IMSI: $UE_IMSI"
    echo "    KEY:  $UE_KEY"
    echo "    PLMN: $PLMN"
    echo "    DNN:  $CURRENT_DNN"
    echo "    SST:  $SST_HEX (hex)"
    echo "    SD:   $SD_HEX (hex)"
    if [ -n "$UE_IPV4" ]; then
        echo "    IPv4: $UE_IPV4"
    fi
    echo

    echo "The configuration file is located in the $UE_CONFIG_DIR/ directory."
done

# Create the get_rfsim_server_address.txt file with the current hostname IP
HOSTNAME_IP=$(hostname -I | awk '{print $1}')
mkdir -p "$UE_CONFIG_DIR"
echo "$HOSTNAME_IP" >"$UE_CONFIG_DIR/get_rfsim_server_address.txt"
