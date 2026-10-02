#!/usr/bin/env bash
set -e
source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/common.sh"
kind=${1:?Usage: apply-patches.sh ran|flexric|flexric-agent [source-dir]}
case "$kind" in
    ran) tree=${2:-$RAN_SRC} ;;
    flexric) tree=${2:-$FLEXRIC_SRC} ;;
    flexric-agent) tree=${2:-$RAN_SRC/openair2/E2AP/flexric} ;;
    *) die "Unknown patch family: $kind" ;;
esac
require_commands git
require_file "$tree/CMakeLists.txt"
# OAI links agent/lib/sm/util directly, not FlexRIC's standalone xApp targets.
# The xApp CSV implementations may legitimately differ between these trees.
if [[ "$kind" == flexric-agent ]]; then
    require_file "$tree/src/util/conf_file.h"
    sed -i 's/#define FR_CONF_FILE_LEN 128/#define FR_CONF_FILE_LEN 1024/g' "$tree/src/util/conf_file.h"
    echo "Prepared embedded FlexRIC E2 agent: $tree (xApp sources preserved)"
    exit 0
fi
patches=("$PATCH_ROOT/$kind")
[[ -d ${patches[0]} ]] || die "Missing patch directory: ${patches[0]}"
while IFS= read -r -d '' patch_file; do
    if git -C "$tree" apply --reverse --check --ignore-whitespace "$patch_file" >/dev/null 2>&1; then
        echo "Already applied: $patch_file"
    elif git -C "$tree" apply --check --ignore-whitespace "$patch_file"; then
        git -C "$tree" apply --ignore-whitespace "$patch_file"
    else
        die "Patch conflicts with current source: $patch_file"
    fi
done < <(find "${patches[@]}" -name '*.patch' -type f ! -path '*/correcting_e2_node_id/src/*' ! -path '*/correcting_e2_node_id/examples/*' -print0 | sort -z)
if [[ "$kind" == flexric ]]; then
    for file in metrics_factory.h metrics_factory.c monitor/xapp_kpm_moni_write_to_csv.c monitor/xapp_kpm_moni_write_to_influxdb.c; do
        source_file="$PATCH_ROOT/flexric/examples/xApp/c/$file"
        require_file "$source_file"
        destination="$tree/examples/xApp/c/$file"
        if [[ -e "$destination" ]]; then
            cmp -s "$source_file" "$destination" || die "Local changes in $destination; reconcile with $source_file before patching."
        else
            cp "$source_file" "$destination"
        fi
    done
    sed -i 's/#define FR_CONF_FILE_LEN 128/#define FR_CONF_FILE_LEN 1024/g' "$tree/src/util/conf_file.h"
fi
