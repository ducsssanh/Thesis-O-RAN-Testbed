#!/bin/bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: configure-flexric.sh'
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

# FLEXRIC_LIBRARY_DIR="/usr/local/lib/flexric/" # Default


SCRIPT_DIR="$SCRIPTS_ROOT"
cd "$CODEBASE_ROOT"

# Function to update or add configuration properties in .conf files, considering sections and uncommenting if needed
update_conf() {
    echo "update_conf($1, $2, $3, $4)"
    local FILE_PATH="$1"
    local SECTION="$2"
    local PROPERTY="$3"
    local VALUE="$4"

    # Ensure the section exists; if not, add it at the end
    if ! grep -q "^\[$SECTION\]" "$FILE_PATH"; then
        echo -e "\n[$SECTION]" >>"$FILE_PATH"
    fi
    # Remove any existing entries of the property in the section (including commented ones)
    sed -i "/^\[$SECTION\]/,/^\s*\[/{/^[# ]*\s*$PROPERTY\s*=.*/d}" "$FILE_PATH"
    # Append the new property=value after the section header
    sed -i "/^\[$SECTION\]/a $PROPERTY = $VALUE" "$FILE_PATH"
}

echo "Saving configuration file example..."

if [ ! -d "$FLEXRIC_SRC" ]; then
    echo "FlexRIC cannot be configured because it is not installed. Skipping."
    exit 0
fi

mkdir -p "$FLEXRIC_CONFIG_DIR"

# Only remove the $FLEXRIC_LOG_DIR if not running
RUNNING_STATUS=$("$SCRIPTS_ROOT/lib/flexric-status.sh")
if [[ $RUNNING_STATUS != *": RUNNING"* ]]; then
    mkdir -p "$FLEXRIC_LOG_DIR"
fi

PREFIX_DIR="${FLEXRIC_LIBRARY_DIR%/lib/flexric*}"
if [[ "$PREFIX_DIR" != /* ]]; then
    PREFIX_DIR="$SCRIPT_DIR/$PREFIX_DIR"
fi

if [ -f "$PREFIX_DIR/etc/flexric/flexric.conf" ]; then
    cp "$PREFIX_DIR/etc/flexric/flexric.conf" "$FLEXRIC_CONFIG_DIR/flexric.conf"
elif [ -f /usr/local/etc/flexric/flexric.conf ]; then
    cp /usr/local/etc/flexric/flexric.conf "$FLEXRIC_CONFIG_DIR/flexric.conf"
else
    cp "$FLEXRIC_SRC/flexric.conf" "$FLEXRIC_CONFIG_DIR/flexric.conf"
fi

update_conf "$FLEXRIC_CONFIG_DIR/flexric.conf" "XAPP" "DB_NAME" "xapp_db1"

echo "Successfully configured the FlexRIC. The configuration file is located in the $FLEXRIC_CONFIG_DIR/ directory."
