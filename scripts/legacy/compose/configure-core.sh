#!/bin/bash
# Modified 2026-09-15: ported NIST testbed logic to the Codebase layout.
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: configure-core.sh (requires 5gdeploy dependencies; configures host forwarding/NAT)'
    exit 0
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

RESET_ORANTESTBED_SCENARIO=true # Set to false to not modify the 5gdeploy/scenario/orantestbed scenario files before generation
AMF_IP=192.168.62.11            # N2 interface
N2_IP_BIND=192.168.62.1
UPF1_IP=192.168.63.21
UPF4_IP=192.168.63.24
SUBNET_INTERNAL="172.25.160.0/20" # Sets the subnet for internal core network

UE_NUMBERS=($(seq 1 10)) # Subscribers from UE 1 to UE 10

# Exit immediately if a command fails
set -e

source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
SCRIPT_DIR="$SCRIPTS_ROOT"
mkdir -p "$CORE_CONFIG_DIR"
[[ -f "$CORE_OPTIONS" ]] || { echo "Missing $CORE_OPTIONS" >&2; exit 1; }
for command in yq docker node corepack; do
    command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
[[ -x "$DEPLOY_SRC/node_modules/.bin/tsx" ]] || {
    echo "Install 5gdeploy dependencies: cd \"$DEPLOY_SRC\" && corepack pnpm install --frozen-lockfile" >&2
    exit 1
}
docker info >/dev/null
cd "$CORE_CONFIG_DIR"

echo "Parsing options.yaml..."
# Read PLMN and TAC values from the YAML file using yq
PLMN=$(yq eval '.plmn' "$CORE_OPTIONS")
TAC=$(yq eval '.tac' "$CORE_OPTIONS")
EXPOSE_AMF=$(yq eval '.expose_amf_over_hostname' "$CORE_OPTIONS")

if [ "$EXPOSE_AMF" = "true" ]; then
    N3_IP_BIND=$(ip route get 1 | awk '{print $(NF-2); exit}') # Get the IP of the primary network interface
    N2_IP_BIND=$(ip route get 1 | awk '{print $(NF-2); exit}') # Expose N2 over primary network interface
else
    N3_IP_BIND="192.168.63.1" # Internal dockerd network bind for UPF
    N2_IP_BIND="192.168.62.1" # Internal dockerd network bind for AMF
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
echo "MCC (Mobile Country Code): $MCC"
echo "MNC (Mobile Network Code): $MNC"
echo "TAC value: $TAC"

# Ensure that the correct script is used
if [ -f "$CORE_OPTIONS" ]; then
    CORE_TO_USE=$(yq eval '.core_to_use' "$CORE_OPTIONS")
    UPF_TO_USE=$(yq eval '.upf_to_use' "$CORE_OPTIONS")
fi
if [[ "$CORE_TO_USE" == "null" || -z "$CORE_TO_USE" ]]; then
    echo "No core specified in options.yaml, please ensure that \"core_to_use\" is set."
    exit 1
fi
if [[ "$UPF_TO_USE" == "null" || -z "$UPF_TO_USE" ]]; then
    UPF_TO_USE="$CORE_TO_USE" # Default to the same core if not specified
fi

if [[ "$CORE_TO_USE" == "5gdeploy-oai" && "$UPF_TO_USE" == "5gdeploy-oai" ]]; then
    source "$SCRIPTS_ROOT/lib/oai-upf-profile.sh"
    profile_validate
fi
if [ "$CORE_TO_USE" == "open5gs" ]; then
    echo "ERROR: The core Open5GS is in the parent directory. Please run the script from the parent directory."
    exit 1
fi

# Configure the DNN, SST, and SD values
CURRENT_DNN=$(yq eval '.slices[0].dnn' "$CORE_OPTIONS")
SST=$(yq eval '.slices[0].sst' "$CORE_OPTIONS")
SD=$(yq eval '.slices[0].sd' "$CORE_OPTIONS")
if [[ -z "$CURRENT_DNN" || "$CURRENT_DNN" == "null" ]]; then
    echo "DNN is not set in options.yaml, please ensure that \"dnn\" is set."
    exit 1
fi
if [[ -z "$SST" || -z "$SD" || "$SST" == "null" || "$SD" == "null" ]]; then
    echo "SST or SD is not set in options.yaml, please ensure that \"slices[].sst\" and \"slices[].sd\" are set."
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

cd "$SCRIPT_DIR"

UE_CREDENTIAL_GENERATOR_SCRIPT="$SCRIPTS_ROOT/lib/ue-credentials.sh"
if [ ! -f "$UE_CREDENTIAL_GENERATOR_SCRIPT" ]; then
    echo "ERROR: Cannot find $UE_CREDENTIAL_GENERATOR_SCRIPT to generate UE subscriber credentials."
    exit 1
fi

echo "Unregistering all subscribers in 5gdeploy database..."
"$SCRIPTS_ROOT/lib/unregister-subscribers.sh"

# Register the subscribers
for UE_NUMBER in "${UE_NUMBERS[@]}"; do
    echo "Registering UE $UE_NUMBER..."
    # Fetch the UE's OPc, IMEI, IMSI, KEY, and NAMESPACE
    read -r UE_OPC UE_IMEI UE_IMSI UE_KEY UE_NAMESPACE < <("$UE_CREDENTIAL_GENERATOR_SCRIPT" "$UE_NUMBER" "$PLMN")
    "$SCRIPTS_ROOT/lib/register-subscriber.sh" --imsi "$UE_IMSI" --key "$UE_KEY" --opc "$UE_OPC" --apn "$CURRENT_DNN"
done

# Ensure that the core is set correctly
if [ "$CORE_TO_USE" == "5gdeploy-oai" ]; then
    CORE="oai"
elif [ "$CORE_TO_USE" == "5gdeploy-free5gc" ]; then
    CORE="free5gc"
elif [ "$CORE_TO_USE" == "5gdeploy-phoenix" ]; then
    CORE="phoenix"
elif [ "$CORE_TO_USE" == "5gdeploy-open5gs" ]; then
    CORE="open5gs"
else
    # Remove the prefix if it exists
    CORE="${CORE_TO_USE#5gdeploy-}"
    echo
    echo "WARNING: Unknown core: \"$CORE\", 5gdeploy may not support this core."
    echo "Do you want to proceed? (Y/n)"
    read -r CONFIRM
    CONFIRM=$(echo "${CONFIRM:-y}" | tr '[:upper:]' '[:lower:]')
    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "yes" ]]; then
        echo "Exiting."
        exit 1
    fi
fi

# Ensure that the UPF is set correctly
if [ "$UPF_TO_USE" == "5gdeploy-eupf" ]; then
    UPF="eupf"
elif [ "$UPF_TO_USE" == "5gdeploy-oai" ]; then
    UPF="oai"
elif [ "$UPF_TO_USE" == "5gdeploy-oai-vpp" ]; then
    UPF="oai-vpp"
elif [ "$UPF_TO_USE" == "5gdeploy-free5gc" ]; then
    UPF="free5gc"
elif [ "$UPF_TO_USE" == "5gdeploy-phoenix" ]; then
    UPF="phoenix"
elif [ "$UPF_TO_USE" == "5gdeploy-open5gs" ]; then
    UPF="open5gs"
elif [ "$UPF_TO_USE" == "5gdeploy-bess" ]; then
    UPF="bess"
elif [ "$UPF_TO_USE" == "5gdeploy-ndndpdk" ]; then
    UPF="ndndpdk"
else
    # Remove the prefix if it exists
    UPF="${UPF_TO_USE#5gdeploy-}"
    echo
    echo "WARNING: Unknown UPF: \"$UPF\", 5gdeploy may not support this UPF."
    echo "Do you want to proceed? (Y/n)"
    read -r CONFIRM
    CONFIRM=$(echo "${CONFIRM:-y}" | tr '[:upper:]' '[:lower:]')
    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "yes" ]]; then
        echo "Exiting."
        exit 1
    fi
fi

cd "$SCRIPT_DIR"

# Generate into a temporary Compose context, then publish the complete configuration.
mkdir -p "$(dirname "$CORE_COMPOSE_DIR")"
CORE_STAGE=$(mktemp -d "${CORE_COMPOSE_DIR}.stage.XXXXXX")
trap 'rm -rf -- "$CORE_STAGE"' EXIT

# Network configuration
sudo sysctl net.ipv4.conf.all.forwarding=1

# Ensure FORWARD policy is ACCEPT
if ! sudo iptables -L FORWARD | grep -q "Chain FORWARD (policy ACCEPT)"; then
    echo "Setting iptables FORWARD policy to ACCEPT..."
    sudo iptables -P FORWARD ACCEPT
fi

# Give the core components internet access
if ! sudo iptables -t nat -C POSTROUTING -s "$SUBNET_INTERNAL" ! -d "$SUBNET_INTERNAL" -j MASQUERADE 2>/dev/null; then
    sudo iptables -t nat -A POSTROUTING -s "$SUBNET_INTERNAL" ! -d "$SUBNET_INTERNAL" -j MASQUERADE
fi
# Remove with sudo iptables -t nat -D POSTROUTING -s "$SUBNET_INTERNAL" ! -d "$SUBNET_INTERNAL" -j MASQUERADE

# Enable SCTP kernel module
sudo modprobe sctp

# Update the configuration file so that the gNodeB can find the AMF
mkdir -p "$CORE_CONFIG_DIR"
AMF_ADDRESSES_OUTPUT="$CORE_CONFIG_DIR/get_amf_address.txt"
echo "$AMF_IP" >"$AMF_ADDRESSES_OUTPUT"
echo "$N3_IP_BIND" >>"$AMF_ADDRESSES_OUTPUT"
echo "$N2_IP_BIND" >>"$AMF_ADDRESSES_OUTPUT"

### Start of pre-generation patching ###
cd "$DEPLOY_SRC/scenario"

if [ "$RESET_ORANTESTBED_SCENARIO" = true ]; then
    echo "Resetting \"orantestbed\" scenario in \"$DEPLOY_SRC/scenario\"..."
    if [ -d "orantestbed" ]; then
        echo "Removing existing orantestbed directory..."
        sudo rm -rf "orantestbed"
    fi
    cp -r 20230817 orantestbed
fi

SST_PADDED=$(printf "%02x" "$SST_DEC") # For example, 0x01 -> 01

if [ "$RESET_ORANTESTBED_SCENARIO" = true ]; then
    echo "Revising scenario files..."
    sed -i "s/01000000/$SST_PADDED$SD_HEX/g" orantestbed/scenario.ts
    sed -i "s/20230817/orantestbed/g" orantestbed/sonic-dl.ts
    sed -i "s/20230817/orantestbed/g" orantestbed/sonic-ul.ts
fi

TAC_PADDED=$(printf "%06x" "$TAC") # For example, 7 -> 000007
# Edit the common scenario template
sed -i "s/plmn: \"[^\"]*\"/plmn: \"$MCC-$MNC\"/g" common/phones-vehicles.ts
sed -i "s/tac: \"[^\"]*\"/tac: \"$TAC_PADDED\"/g" common/phones-vehicles.ts

cd "$DEPLOY_SRC"

# Set the subnet in compose/ipalloc.ts
if [ -f "compose/ipalloc.ts" ]; then
    echo "Setting core subnet in compose/ipalloc.ts..."
    sed -E -i 's|(dfltSpace[[:space:]]*=[[:space:]]*")[^"]*(")|\1'"$SUBNET_INTERNAL"'\2|' compose/ipalloc.ts
fi

# Set the subnet in virt/main.ts
if [ -f "virt/main.ts" ]; then
    echo "Setting core subnet in virt/main.ts..."
    sed -E -i 's|(ipAllocOptions[[:space:]]*\(")[^"]*("\))|\1'"$SUBNET_INTERNAL"'\2|' virt/main.ts
fi

### End of pre-generation patching ###

cd "$DEPLOY_SRC/scenario"

echo "Using CP: $CORE"
echo "Using UP: $UPF"

# For a multi-host deployment, see the 5gdeploy documentation: https://github.com/usnistgov/5gdeploy/blob/main/docs/multi-host.md
BPF_ARGS=()
if [[ "$UPF_TO_USE" == "5gdeploy-oai" ]]; then
    BPF_ARGS=(--oai-upf-bpf=false)
    [[ "${OAI_UPF_DATAPATH:-}" != xdp-skb ]] || BPF_ARGS=(--oai-upf-bpf=true)
fi
"$SCRIPTS_ROOT/lib/generate-core-scenario.sh" "$CORE_STAGE" orantestbed \
    +gnbs=1 +phones=0 +vehicles=0 \
    --cp=$CORE --up=$UPF --ran=none "${BPF_ARGS[@]}" \
    --ip-fixed=amf,n2,$AMF_IP \
    --ip-fixed=upf1,n3,$UPF1_IP \
    --ip-fixed=upf4,n3,$UPF4_IP
# --bridge="n2 | vx | $IP_ADDRESS,$AMF_IP" \
# --bridge="n3 | vx | $IP_ADDRESS,$UPF1_IP" \

cd "$CORE_CONFIG_DIR"

### Start of post-generation patching ###

cd "$CORE_STAGE"

# Save the core and UPF used to a text file for reference
echo "$CORE_TO_USE" >core_upf_used.txt
echo "$UPF_TO_USE" >>core_upf_used.txt

# Revise configuration file netdef.json
if [ -f "netdef.json" ]; then
    echo "Setting subscribers field in netdef.json..."
    sed -i "s/\"internet\"/\"$CURRENT_DNN\"/g" netdef.json
    sed -i "s/'internet'/'$CURRENT_DNN'/g" netdef.json
fi

# Revise configuration files in the cp-cfg directory
for CPFILE in cp-cfg/*; do
    if [ -f "$CPFILE" ]; then
        sed -i "s/\"internet\"/\"$CURRENT_DNN\"/g" "$CPFILE"
        sed -i "s/'internet'/'$CURRENT_DNN'/g" "$CPFILE"
    fi
done

# Revise configuration files up-cfg/upf1.yaml, up-cfg/upf140.yaml, and up-cfg/upf141.yaml
for FILE in up-cfg/upf1.yaml up-cfg/upf140.yaml up-cfg/upf141.yaml; do
    if [ -f "$FILE" ]; then
        # Patch all "sd" fields to the correct SD value, but only for top-level or first element arrays
        SD="$SD_HEX" yq '
            with(select(has("sd")); .sd = env(SD)) |
            (
                (.. | select(kind == "seq" and length > 0) | .[0]
                    | select(kind == "map" and has("sd")) | .sd
                ) |= env(SD)
            )
        ' "$FILE" >tmp.yaml && mv tmp.yaml "$FILE"

        sed -i "s/\"internet\"/\"$CURRENT_DNN\"/g" "$FILE"
        sed -i "s/'internet'/'$CURRENT_DNN'/g" "$FILE"
    fi
done

# Revise compose.yml
if [ -f "compose.yml" ]; then
    # Replace "dnn":["internet"] with dnn:["$CURRENT_DNN"]
    sed -i -E 's/"dnn"[[:space:]]*:[[:space:]]*\[[[:space:]]*"internet"[[:space:]]*\]/"dnn":["'"$CURRENT_DNN"'"]/g' compose.yml
    # Replace "dnn":"internet" with "dnn":"$CURRENT_DNN"
    sed -i -E 's/"dnn"[[:space:]]*:[[:space:]]*"internet"/"dnn":"'"$CURRENT_DNN"'"/g' compose.yml
    # Replace ${SST_PADDED}${SD_HEX}_internet with ${SST_PADDED}${SD_HEX}_${CURRENT_DNN}
    sed -i -E "s/${SST_PADDED}${SD_HEX}_internet/${SST_PADDED}${SD_HEX}_${CURRENT_DNN}/g" compose.yml
    # Replace ${SST_PADDED}${SD_HEX}:internet with ${SST_PADDED}${SD_HEX}:${CURRENT_DNN}
    sed -i -E "s/${SST_PADDED}${SD_HEX}:internet/${SST_PADDED}${SD_HEX}:${CURRENT_DNN}/g" compose.yml
fi

# Revise cp-sql/oai_db.sql
if [ -f "cp-sql/oai_db.sql" ]; then
    # Ensure that the database is dropped before creating it
    sed -i '1i DROP DATABASE IF EXISTS oai_db;' cp-sql/oai_db.sql
    # Fix primary key for SessionManagementSubscriptionData to allow multiple SDs per UE
    sed -i '/ALTER TABLE `SessionManagementSubscriptionData`/,/ADD PRIMARY KEY/ s/ADD PRIMARY KEY (`ueid`,`servingPlmnid`)/ADD PRIMARY KEY (`ueid`,`servingPlmnid`,`singleNssai`(64))/' cp-sql/oai_db.sql
fi

# Revise cp-sql/smf.sql
if [ -f "cp-sql/smf.sql" ]; then
    # Replace "'internet'" with "'$CURRENT_DNN'"
    sed -i "s/'internet'/'$CURRENT_DNN'/g" cp-sql/smf.sql
fi

# Revise cp-sql/udm.sql
if [ -f "cp-sql/udm.sql" ]; then
    # Replace "'internet'" with "'$CURRENT_DNN'"
    sed -i "s/'internet'/'$CURRENT_DNN'/g" cp-sql/udm.sql
fi

if [ -f "cp-db/open5gs.sh" ]; then
    # Replace " internet " with " $CURRENT_DNN "
    sed -i "s/ internet / $CURRENT_DNN /g" cp-db/open5gs.sh
fi

### End of post-generation patching ###

if [[ "$CORE_TO_USE" == "5gdeploy-oai" && "$UPF_TO_USE" == "5gdeploy-oai" ]]; then
    PROFILE_COMPOSE_DIR="$CORE_STAGE"
    profile_apply
fi

# Replace the generated context only after generation and patching succeeded.
mkdir -p "$(dirname "$CORE_COMPOSE_DIR")"
if [[ -e "$CORE_COMPOSE_DIR" ]]; then
    CORE_BACKUP="${CORE_COMPOSE_DIR}.previous.$(date +%s).$$"
    mv -- "$CORE_COMPOSE_DIR" "$CORE_BACKUP"
    echo "Previous Compose context: $CORE_BACKUP"
fi
mv -- "$CORE_STAGE" "$CORE_COMPOSE_DIR"
trap - EXIT
ln -sfn "$DEPLOY_SRC/sims.tsv" "$CORE_CONFIG_DIR/sims.tsv"
ln -sfn "$CORE_COMPOSE_DIR/netdef.json" "$CORE_CONFIG_DIR/netdef.json"
ln -sfn "$CORE_COMPOSE_DIR/cp-cfg/config.yaml" "$CORE_CONFIG_DIR/cp-cfg-config.yaml"
for upf in upf1 upf140 upf141; do
    ln -sfn "$CORE_COMPOSE_DIR/up-cfg/$upf.yaml" "$CORE_CONFIG_DIR/up-cfg-$upf.yaml"
done
echo "Core configuration: $CORE_CONFIG_DIR; Compose context: $CORE_COMPOSE_DIR"
