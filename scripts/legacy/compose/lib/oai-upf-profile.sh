#!/usr/bin/env bash

# Shared validation and generated-compose patching for the research OAI UPF.
# This file is sourced by generate_configurations.sh and can also be executed
# directly with "validate", "apply", or "metadata".

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then set -Eeuo pipefail; fi

source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../env.sh"
PROFILE_SCRIPT_DIR="$SCRIPTS_ROOT"
PROFILE_OPTIONS="$CORE_OPTIONS"
PROFILE_COMPOSE_DIR="$CORE_COMPOSE_DIR"
PROFILE_SOURCE_DIR="$UPF_SRC"

profile_read() {
    command -v yq >/dev/null 2>&1 || {
        echo "ERROR: yq is required to read $PROFILE_OPTIONS." >&2
        return 1
    }

    OAI_UPF_DATAPATH=$(yq eval '.oai_upf.datapath // "xdp-skb"' "$PROFILE_OPTIONS")
    OAI_UPF_IMAGE=$(yq eval '.oai_upf.image // "oai-upf-research:local"' "$PROFILE_OPTIONS")
    OAI_UPF_BUILD_LOCAL=$(yq eval '.oai_upf | with(select(.build_local_image == null); .build_local_image = true) | .build_local_image' "$PROFILE_OPTIONS")
    OAI_UPF_USAGE_REPORTING=$(yq eval '.oai_upf | with(select(.enable_usage_reporting == null); .enable_usage_reporting = true) | .enable_usage_reporting' "$PROFILE_OPTIONS")
    OAI_UPF_VOLUME_THRESHOLD=$(yq eval '.oai_upf.volume_threshold_bytes // 104857600' "$PROFILE_OPTIONS")
    OAI_UPF_CORE=$(yq eval '.core_to_use // "open5gs"' "$PROFILE_OPTIONS")
    OAI_UPF_IMPLEMENTATION=$(yq eval '.upf_to_use // .core_to_use' "$PROFILE_OPTIONS")
}

profile_validate() {
    profile_read

    [[ "$OAI_UPF_CORE" == "5gdeploy-oai" ]] || {
        echo "ERROR: oai_upf profile requires core_to_use: 5gdeploy-oai." >&2
        return 1
    }
    [[ "$OAI_UPF_IMPLEMENTATION" == "5gdeploy-oai" ]] || {
        echo "ERROR: oai_upf profile requires upf_to_use: 5gdeploy-oai." >&2
        return 1
    }
    case "$OAI_UPF_DATAPATH" in
        simple-switch|xdp-skb) ;;
        *)
            echo "ERROR: oai_upf.datapath must be simple-switch or xdp-skb." >&2
            return 1
            ;;
    esac
    [[ "$OAI_UPF_IMAGE" =~ ^[A-Za-z0-9._/:@-]+$ ]] || {
        echo "ERROR: oai_upf.image contains unsupported characters." >&2
        return 1
    }
    [[ "$OAI_UPF_BUILD_LOCAL" == "true" || "$OAI_UPF_BUILD_LOCAL" == "false" ]] || {
        echo "ERROR: oai_upf.build_local_image must be true or false." >&2
        return 1
    }
    [[ "$OAI_UPF_USAGE_REPORTING" == "true" || "$OAI_UPF_USAGE_REPORTING" == "false" ]] || {
        echo "ERROR: oai_upf.enable_usage_reporting must be true or false." >&2
        return 1
    }
    if [[ "$OAI_UPF_USAGE_REPORTING" == "true" && "$OAI_UPF_DATAPATH" != "xdp-skb" ]]; then
        echo "ERROR: Usage reporting currently requires oai_upf.datapath: xdp-skb." >&2
        echo "Set enable_usage_reporting: false to run the simple-switch fallback." >&2
        return 1
    fi
    [[ "$OAI_UPF_VOLUME_THRESHOLD" =~ ^[1-9][0-9]*$ ]] || {
        echo "ERROR: oai_upf.volume_threshold_bytes must be a positive integer." >&2
        return 1
    }
    if [[ "$OAI_UPF_BUILD_LOCAL" == "true" ]]; then
        [[ -f "$PROFILE_SOURCE_DIR/docker/Dockerfile.upf.ubuntu" ]] || {
            echo "ERROR: OAI UPF submodule is missing. Run: git submodule update --init --recursive" >&2
            return 1
        }
    fi
}

profile_patch_config() {
    local config_file=$1
    [[ -f "$config_file" ]] || return 0

    local bpf_value=false
    [[ "$OAI_UPF_DATAPATH" == "xdp-skb" ]] && bpf_value=true

    if yq eval -e '.upf.support_features | type == "!!map"' "$config_file" >/dev/null 2>&1; then
        BPF_VALUE="$bpf_value" URR_VALUE="$OAI_UPF_USAGE_REPORTING" yq eval -i '
          .upf.support_features.enable_bpf_datapath = (env(BPF_VALUE) == "true") |
          .upf.support_features.enable_urr = (env(URR_VALUE) == "true")
        ' "$config_file"
    fi
    if yq eval -e '.smf.upfs | type == "!!seq"' "$config_file" >/dev/null 2>&1; then
        URR_VALUE="$OAI_UPF_USAGE_REPORTING" yq eval -i '
          .smf.upfs[].config.enable_usage_reporting = (env(URR_VALUE) == "true")
        ' "$config_file"
    fi
}

profile_patch_compose() {
    local compose_file=$1
    [[ -f "$compose_file" ]] || return 0

    OAI_UPF_IMAGE_VALUE="$OAI_UPF_IMAGE" yq eval -i '
      (.services[] | select((.image // "") | test("(?i)oai.*upf|upf.*oai"))).image = strenv(OAI_UPF_IMAGE_VALUE)
    ' "$compose_file"
}

profile_validate_compose_capabilities() {
    local compose_file=$1
    [[ "$OAI_UPF_DATAPATH" == "xdp-skb" ]] || return 0
    if ! yq eval -e '[.services[] | select((.image // "") | test("(?i)oai.*upf|upf.*oai"))] | length > 0' "$compose_file" >/dev/null; then
        echo "ERROR: No OAI UPF service in generated Compose." >&2
        return 1
    fi
    # The generator must grant these when --oai-upf-bpf=true is passed.
    local capability
    for capability in NET_ADMIN BPF SYS_ADMIN SYS_RESOURCE; do
        if ! CAPABILITY="$capability" yq eval -e '
          [.services[] | select((.image // "") | test("(?i)oai.*upf|upf.*oai")) |
            ((.cap_add // []) | contains([strenv(CAPABILITY)]))] |
          all
        ' "$compose_file" >/dev/null; then
            echo "ERROR: Generated OAI UPF Compose lacks $capability; check --oai-upf-bpf=true." >&2
            return 1
        fi
    done
}

profile_apply() {
    profile_validate
    [[ -d "$PROFILE_COMPOSE_DIR" ]] || {
        echo "ERROR: Generated compose directory not found: $PROFILE_COMPOSE_DIR" >&2
        return 1
    }
    if [[ "$OAI_UPF_BUILD_LOCAL" == "true" ]] && ! docker image inspect "$OAI_UPF_IMAGE" >/dev/null 2>&1; then
        echo "ERROR: Local image $OAI_UPF_IMAGE is not built." >&2
        echo "Run $SCRIPTS_ROOT/build-upf.sh before generating configurations." >&2
        return 1
    fi

    local file
    for file in "$PROFILE_COMPOSE_DIR"/cp-cfg/*.yaml "$PROFILE_COMPOSE_DIR"/up-cfg/*.yaml; do
        [[ -e "$file" ]] || continue
        profile_patch_config "$file"
    done
    profile_patch_compose "$PROFILE_COMPOSE_DIR/compose.yml"
    profile_validate_compose_capabilities "$PROFILE_COMPOSE_DIR/compose.yml"

    {
        printf 'core=%s\n' "$OAI_UPF_CORE"
        printf 'upf=%s\n' "$OAI_UPF_IMPLEMENTATION"
        printf 'datapath=%s\n' "$OAI_UPF_DATAPATH"
        printf 'image=%s\n' "$OAI_UPF_IMAGE"
        printf 'usage_reporting=%s\n' "$OAI_UPF_USAGE_REPORTING"
        printf 'volume_threshold_bytes=%s\n' "$OAI_UPF_VOLUME_THRESHOLD"
        if [[ -d "$PROFILE_SOURCE_DIR/.git" || -f "$PROFILE_SOURCE_DIR/.git" ]]; then
            printf 'source_commit=%s\n' "$(git -C "$PROFILE_SOURCE_DIR" rev-parse HEAD)"
        fi
    } >"$PROFILE_COMPOSE_DIR/oai_upf_profile.env"

    echo "Applied OAI UPF profile: datapath=$OAI_UPF_DATAPATH image=$OAI_UPF_IMAGE URR=$OAI_UPF_USAGE_REPORTING"
}

profile_metadata() {
    profile_validate
    printf 'OAI_UPF_DATAPATH=%q\n' "$OAI_UPF_DATAPATH"
    printf 'OAI_UPF_IMAGE=%q\n' "$OAI_UPF_IMAGE"
    printf 'OAI_UPF_USAGE_REPORTING=%q\n' "$OAI_UPF_USAGE_REPORTING"
    printf 'OAI_UPF_VOLUME_THRESHOLD_BYTES=%q\n' "$OAI_UPF_VOLUME_THRESHOLD"
    if [[ -d "$PROFILE_SOURCE_DIR/.git" || -f "$PROFILE_SOURCE_DIR/.git" ]]; then
        printf 'OAI_UPF_SOURCE_COMMIT=%q\n' "$(git -C "$PROFILE_SOURCE_DIR" rev-parse HEAD)"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-validate}" in
        validate) profile_validate ;;
        apply) profile_apply ;;
        metadata) profile_metadata ;;
        *) echo "Usage: $0 [validate|apply|metadata]" >&2; exit 2 ;;
    esac
fi
