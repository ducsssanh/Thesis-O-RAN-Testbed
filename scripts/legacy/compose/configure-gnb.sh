#!/bin/bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: configure-gnb.sh (after configure-core.sh)'
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

SPLIT_DU_IDS=$(seq 1 3)
RADIO_TYPE="${RADIO_TYPE:-SIMU}" # Set to "SIMU", "ZMQ", or "USRP"
MAKE_GNB_E2_NODE="${MAKE_GNB_E2_NODE:-true}"
MAKE_CU_E2_NODE="${MAKE_CU_E2_NODE:-false}"
MAKE_DU_E2_NODE="${MAKE_DU_E2_NODE:-true}"

# FLEXRIC_LIBRARY_DIR="/usr/local/lib/flexric/" # Default


SCRIPT_DIR="$SCRIPTS_ROOT"
cd "$CODEBASE_ROOT"

if [[ "$FLEXRIC_LIBRARY_DIR" != /* ]]; then
    FULL_SM_DIR="$(realpath "$SCRIPT_DIR/$FLEXRIC_LIBRARY_DIR" 2>/dev/null || echo "$SCRIPT_DIR/$FLEXRIC_LIBRARY_DIR")"
else
    FULL_SM_DIR="$FLEXRIC_LIBRARY_DIR"
fi
if [[ "$FULL_SM_DIR" != */ ]]; then
    FULL_SM_DIR="${FULL_SM_DIR}/"
fi

# There are two types of RSRP/SINR measurements: SSB and CSI
# Valid values for CSI_REPORT_TYPE: "ssb_rsrp", "ssb_sinr", "cri_rsrp", or "null" (to omit CSI_report_type and set do_CSIRS=1)
# If using MIMO, then CSI_REPORT_TYPE must not be an SSB-based measurement (https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/RUNMODEM.md#5g-gnb-mimo-configuration)
CSI_REPORT_TYPE="ssb_rsrp"

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

# Define the path to the 5G Core YAML file
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
DNN=($(yq eval '.slices[].dnn' "$YAML_PATH"))
SST=($(yq eval '.slices[].sst' "$YAML_PATH"))
SD=($(yq eval '.slices[].sd' "$YAML_PATH"))
if [[ -z "${DNN[0]}" || "${DNN[0]}" == "null" ]]; then
    echo "DNN is not set in $YAML_PATH, please ensure that \"dnn\" is set."
    exit 1
fi
if [[ -z "${SST[0]}" || "${SST[0]}" == "null" ]]; then
    echo "SST is not set in $YAML_PATH, please ensure that \"slices[].sst\" is set."
    exit 1
fi

# SST/SD are configured in options.yaml as hex without 0x prefix.
for i in "${!SST[@]}"; do
    CURRENT_DNN="${DNN[$i]}"
    CURRENT_SST="${SST[$i]}"
    CURRENT_SD="${SD[$i]}"

    CURRENT_SST="${CURRENT_SST#0x}"
    CURRENT_SST="${CURRENT_SST#0X}"
    CURRENT_SST="${CURRENT_SST^^}"

    if [[ ! "$CURRENT_SST" =~ ^[0-9A-F]{1,2}$ ]]; then
        echo "Invalid slices[$i].sst '${SST[$i]}'. Use hexadecimal (00-FF), no 0x prefix."
        exit 1
    fi
    SST[$i]="$((16#$CURRENT_SST))"

    if [[ "$CURRENT_SD" != "null" ]]; then
        CURRENT_SD="${CURRENT_SD#0x}"
        CURRENT_SD="${CURRENT_SD#0X}"
        CURRENT_SD="${CURRENT_SD^^}"
        if [[ ! "$CURRENT_SD" =~ ^[0-9A-F]{1,6}$ ]]; then
            echo "Invalid slices[$i].sd '${SD[$i]}'. Use hexadecimal (up to 6 hex digits), no 0x prefix."
            exit 1
        fi
        SD[$i]="$(printf "%06X" "$((16#$CURRENT_SD))")"
    fi
done

SNSSAI_LIST="("
declare -A OMIT_SD
declare -A OMIT_SD_ADDED

# Check for omitting SD if null or FFFFFF (case insensitive)
for i in "${!SST[@]}"; do
    CURRENT_DNN="${DNN[$i]}"
    CURRENT_SST="${SST[$i]}"
    CURRENT_SD="${SD[$i]}"
    if [[ "$CURRENT_SD" == "null" || "${CURRENT_SD^^}" == "FFFFFF" ]]; then
        OMIT_SD["$CURRENT_SST"]=1
    fi
done

FIRST_ENTRY=1
for i in "${!SST[@]}"; do
    CURRENT_DNN="${DNN[$i]}"
    CURRENT_SST="${SST[$i]}"
    CURRENT_SD="${SD[$i]}"

    # If SST has SD wildcard, only add SST to the list
    if [[ -n "${OMIT_SD[$CURRENT_SST]}" ]]; then
        if [[ -z "${OMIT_SD_ADDED[$CURRENT_SST]}" ]]; then # Uniqueness
            if [ "$FIRST_ENTRY" -eq 0 ]; then SNSSAI_LIST+=", "; fi
            SNSSAI_LIST+="{ sst = $CURRENT_SST; }"
            OMIT_SD_ADDED["$CURRENT_SST"]=1
            FIRST_ENTRY=0
        fi
    else
        # Entry with SST and SD
        if [ "$FIRST_ENTRY" -eq 0 ]; then SNSSAI_LIST+=", "; fi
        SNSSAI_LIST+="{ sst = $CURRENT_SST; sd = 0x$CURRENT_SD; }"
        FIRST_ENTRY=0
    fi
done
SNSSAI_LIST+=")"

# Ensure the correct YAML editor is installed
require_yq

echo "Saving configuration file example..."
mkdir -p "$GNB_CONFIG_DIR"
echo "$RADIO_TYPE" >"$GNB_CONFIG_DIR/radio_type.txt"

# Only remove the $GNB_LOG_DIR if not running
RUNNING_STATUS=$("$SCRIPTS_ROOT/lib/gnb-status.sh")
if [[ $RUNNING_STATUS != *": RUNNING"* ]]; then
    mkdir -p "$GNB_LOG_DIR"
fi

cp "$RAN_SRC"/targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpb210.conf "$GNB_CONFIG_DIR/gnb.conf"
cp "$RAN_SRC"/targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb-cu.sa.f1.conf "$GNB_CONFIG_DIR/split_cu.conf"
for i in $SPLIT_DU_IDS; do
    cp "$GNB_CONFIG_DIR/gnb.conf" "$GNB_CONFIG_DIR/split_du${i}.conf"
done

echo "Fetching AMF addresses..."
AMF_ADDRESSES=$(cat "$CORE_CONFIG_DIR/get_amf_address.txt")

prompt_for_addresses() {
    echo "Please enter the AMF address and the AMF binding address manually." >&2
    echo "You can find this information in the $CORE_CONFIG_DIR/get_amf_address.txt file in the first two lines, respectively." >&2
    read -p "Enter AMF Address: " AMF_ADDR
    read -p "Enter AMF Binding Address: " N3_ADDR_BIND
    N2_ADDR_BIND=$N3_ADDR_BIND
}

# Check if AMF_ADDRESSES has at least two non-empty lines
if [[ -n "$AMF_ADDRESSES" ]]; then
    # Read AMF_ADDRESSES into an array, splitting on newlines
    ADDRESSES=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue # skip blank lines
        ADDRESSES+=("$line")
    done <<<"$AMF_ADDRESSES"
    if [[ ${#ADDRESSES[@]} -ge 3 ]] && [[ -n ${ADDRESSES[0]} ]] && [[ -n ${ADDRESSES[1]} ]] && [[ -n ${ADDRESSES[2]} ]]; then
        AMF_ADDR="${ADDRESSES[0]}"
        N3_ADDR_BIND="${ADDRESSES[1]}"
        N2_ADDR_BIND="${ADDRESSES[2]}"
    elif [[ ${#ADDRESSES[@]} -ge 2 ]] && [[ -n ${ADDRESSES[0]} ]] && [[ -n ${ADDRESSES[1]} ]]; then
        AMF_ADDR="${ADDRESSES[0]}"
        N3_ADDR_BIND="${ADDRESSES[1]}"
        N2_ADDR_BIND="${ADDRESSES[1]}"
    else
        echo
        echo "AMF address script did not return valid data."
        prompt_for_addresses
    fi
else
    echo
    echo "Open5GS was not configured."
    prompt_for_addresses
fi

echo "AMF Address: $AMF_ADDR"
echo "AMF Binding Address: $N3_ADDR_BIND"
echo "NGAP Binding Address: $N2_ADDR_BIND/24"

SPLIT_DUS=()
for i in $SPLIT_DU_IDS; do
    SPLIT_DUS+=("split_du${i}.conf")
done

for CONF_FILE in gnb.conf split_cu.conf "${SPLIT_DUS[@]}"; do
    echo "Configuring $CONF_FILE..."
    # Update configuration values for RF front-end device
    update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "amf_ip_address" "({ ipv4 = \"$AMF_ADDR\"; })"
    update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "GNB_IPV4_ADDRESS_FOR_NG_AMF" "\"$N2_ADDR_BIND/24\""
    update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "GNB_IPV4_ADDRESS_FOR_NGU" "\"$N3_ADDR_BIND/24\""
    update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "tracking_area_code" "$TAC"
    update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "sm_dir" "\"$FULL_SM_DIR\""

    # Configure the Single Network Slice Selection Assistance Information (S-NSSAI)
    update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "plmn_list" "({ mcc = $MCC; mnc = $MNC; mnc_length = $MNC_LENGTH; snssaiList = $SNSSAI_LIST })"

    if [ "$CSI_REPORT_TYPE" = "ssb_rsrp" ] || [ "$CSI_REPORT_TYPE" = "ssb_sinr" ] || [ "$CSI_REPORT_TYPE" = "cri_rsrp" ]; then
        if [ "$CSI_REPORT_TYPE" = "cri_rsrp" ]; then
            update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "do_CSIRS" "1"
        else
            update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "do_CSIRS" "0"
        fi

        # 38.331's reportQuantity and reportQuantity-r16 CHOICE enforces only either ssb-Index-RSRP or ssb-Index-SINR-r16, not both
        if grep -q "^\s*CSI_report_type\s*=" "$GNB_CONFIG_DIR/$CONF_FILE"; then
            sed -i "s|^\(\s*CSI_report_type\s*=\).*|\1 \"$CSI_REPORT_TYPE\"; # ssb_rsrp, ssb_sinr, or cri_rsrp|" "$GNB_CONFIG_DIR/$CONF_FILE"
        else
            sed -i "/do_CSIRS\s*=/a \    CSI_report_type                                           = \"$CSI_REPORT_TYPE\"; # ssb_rsrp, ssb_sinr, or cri_rsrp" "$GNB_CONFIG_DIR/$CONF_FILE"
        fi
    else
        update_conf "$GNB_CONFIG_DIR/$CONF_FILE" "do_CSIRS" "1"
        sed -i '/^\s*CSI_report_type\s*=/d' "$GNB_CONFIG_DIR/$CONF_FILE"
    fi

    if [ "$RADIO_TYPE" = "SIMU" ] || [ "$RADIO_TYPE" = "ZMQ" ]; then
        if ! grep -q "@include \"channelmod_rfsimu.conf\"" "$GNB_CONFIG_DIR/$CONF_FILE"; then
            echo "" >>"$GNB_CONFIG_DIR/$CONF_FILE"
            echo "@include \"channelmod_rfsimu.conf\"" >>"$GNB_CONFIG_DIR/$CONF_FILE"
        fi
        if [ ! -e "$GNB_CONFIG_DIR/channelmod_rfsimu.conf" ]; then
            cp "$RAN_SRC"/targets/PROJECTS/GENERIC-NR-5GC/CONF/channelmod_rfsimu.conf "$GNB_CONFIG_DIR/channelmod_rfsimu.conf"
        fi
    fi

    if [[ "$CONF_FILE" == "gnb.conf" ]] && [ "$MAKE_GNB_E2_NODE" = "false" ]; then
        sed -i '/^e2_agent *= *{/,/^};/ s/^/#/' "$GNB_CONFIG_DIR/$CONF_FILE"
    elif [[ "$CONF_FILE" == "split_cu.conf" ]] && [ "$MAKE_CU_E2_NODE" = "false" ]; then
        sed -i '/^e2_agent *= *{/,/^};/ s/^/#/' "$GNB_CONFIG_DIR/$CONF_FILE"
    elif [[ "$CONF_FILE" == *"du"* ]] && [ "$MAKE_DU_E2_NODE" = "false" ]; then
        sed -i '/^e2_agent *= *{/,/^};/ s/^/#/' "$GNB_CONFIG_DIR/$CONF_FILE"
    fi
done

echo
echo "Generating configuration for CU..."
# Set the local_n_address in the CU configuration file
sed -i 's|^\([[:space:]]*\)local_n_address\s*=.*|\1local_n_address     = "127.0.0.100";|' "$GNB_CONFIG_DIR/split_cu.conf"
echo "    Configured CU."

for DU_CONF in "${SPLIT_DUS[@]}"; do
    DU_NUMBER=$(echo "$DU_CONF" | grep -oP 'split_du\K[0-9]+')
    "$SCRIPTS_ROOT/lib/configure-du.sh" "$DU_NUMBER"
done


echo
echo "Successfully configured the gNodeB and split CU/DUs. The configuration files are located in the $GNB_CONFIG_DIR/ directory."
