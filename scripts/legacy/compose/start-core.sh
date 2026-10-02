#!/bin/bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: start-core.sh'
    exit 0
fi
# Modified 2026-09-15: ported NIST testbed logic to the Codebase layout.
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
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

set -e
SCRIPT_DIR="$SCRIPTS_ROOT"
cd "$CODEBASE_ROOT"

if [ ! -f "$CORE_COMPOSE_DIR/compose.sh" ]; then
    echo "ERROR: Cannot find compose.sh in compose/orantestbed/. Please run the configure-core.sh script first."
    exit 1
fi

# Fetch the core and UPF to use from options.yaml
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

cd "$CORE_COMPOSE_DIR"

# Verify that the selected core and UPF match the currently deployed ones
if [ -f "core_upf_used.txt" ]; then
    CURRENT_CORE=$(sed -n '1p' core_upf_used.txt)
    CURRENT_UPF=$(sed -n '2p' core_upf_used.txt)
    if [[ "$CURRENT_CORE" != "$CORE_TO_USE" || "$CURRENT_UPF" != "$UPF_TO_USE" ]]; then
        echo
        echo "ERROR: The selected core ($CORE_TO_USE) or UPF ($UPF_TO_USE) does not match the currently deployed core ($CURRENT_CORE) or UPF ($CURRENT_UPF)."
        echo "Please run the configure-core.sh script to update the configuration before deploying."
        echo
        exit 1
    fi
fi

docker info >/dev/null


echo "Starting the 5G Core Deployment Helper (5gdeploy) Core..."
if docker ps -aq -f name=^/amf$ | grep -q .; then
    echo "ERROR: Docker container name 'amf' is already in use. Stop or remove the existing container before starting the 5G Core."
    exit 1
fi
if [ -f "$CORE_CONFIG_DIR/get_amf_address.txt" ]; then
    AMF_IP=$(sed -n '1p' "$CORE_CONFIG_DIR/get_amf_address.txt")
    if [ -n "$AMF_IP" ]; then
        for CONTAINER_ID in $(docker ps -q); do
            if docker inspect --format '{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}' "$CONTAINER_ID" 2>/dev/null | grep -Fxq "$AMF_IP"; then
                echo "ERROR: Docker IP address $AMF_IP is already in use. Stop the conflicting container before starting the 5G Core."
                exit 1
            fi
        done
    fi
fi
./compose.sh up

cd "$SCRIPT_DIR"
