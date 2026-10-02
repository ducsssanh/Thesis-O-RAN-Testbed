#!/bin/bash
# Modified 2026-09-15: ported NIST testbed logic to the Codebase layout.
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../env.sh"
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

# Ensure that the correct script is used
if [ -f "$CORE_OPTIONS" ]; then
    CORE_TO_USE=$(yq eval '.core_to_use' "$CORE_OPTIONS")
fi
if [[ "$CORE_TO_USE" == "null" || -z "$CORE_TO_USE" ]]; then
    CORE_TO_USE="open5gs" # Default
fi
if [[ "$CORE_TO_USE" == "open5gs" ]]; then
    echo "Native Open5GS is not part of this 5gdeploy port." >&2
    exit 1
fi

docker info >/dev/null


AMF_LOG=$(docker logs amf 2>&1)

if "$SCRIPTS_ROOT/lib/core-status.sh" 2>/dev/null | grep -q "NOT_RUNNING"; then
    echo false
    exit 0
fi

if [ -z "$AMF_LOG" ]; then
    echo false
    exit 0
fi

if [[ "$CORE_TO_USE" == "5gdeploy-open5gs" ]]; then
    if echo "$AMF_LOG" | grep -q "NF registered"; then
        # Wait for all subscribers to be created
        NUM_SUBS=$(($(wc -l <"$CORE_CONFIG_DIR/sims.tsv") - 1))
        if [ "$(docker logs mongo 2>&1 | grep -c "Creating subscriber")" -ge "$NUM_SUBS" ]; then
            echo true
            exit 0
        fi
    fi
    echo false
    exit 0
elif [[ "$CORE_TO_USE" == "5gdeploy-oai" ]]; then
    if echo "$AMF_LOG" | grep -q "AMF has successfully registered to NRF"; then
        if [ "$(docker logs sql 2>&1 | grep -c "MariaDB init process done")" -gt 0 ] &&
            docker logs udr 2>&1 | grep -q "Sending NF Registration request"; then
            echo true
            exit 0
        fi
    fi
elif [[ "$CORE_TO_USE" == "5gdeploy-free5gc" ]]; then
    if echo "$AMF_LOG" | grep -q "Start SBI server"; then
        # Wait for all subscribers to be created
        NUM_SUBS=$(($(wc -l <"$CORE_CONFIG_DIR/sims.tsv") - 1))
        if [ "$(docker logs webui 2>&1 | grep -c "Post One Subscriber Data")" -ge "$NUM_SUBS" ]; then
            echo true
            exit 0
        fi
    fi
elif [[ "$CORE_TO_USE" == "5gdeploy-phoenix" ]]; then
    if echo "$AMF_LOG" | grep -q "Successfully parsed command line"; then # TODO: Improve this check
        echo true
        exit 0
    fi
fi

echo false
exit 1
