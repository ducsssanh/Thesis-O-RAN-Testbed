#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR=$(dirname "$(realpath "$0")")
PROFILE="$SCRIPT_DIR/../scripts/legacy/compose/lib/oai-upf-profile.sh"

source "$PROFILE"
profile_validate

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

CONFIG="$TMP_DIR/config.yaml"
COMPOSE="$TMP_DIR/compose.yml"

cat >"$CONFIG" <<'YAML'
smf:
  upfs:
    - host: upf1
      config:
        enable_usage_reporting: false
upf:
  support_features:
    enable_bpf_datapath: false
    enable_urr: false
YAML

cat >"$COMPOSE" <<'YAML'
services:
  amf:
    image: example/amf:stable
  upf1:
    image: example/oai-upf:stable
YAML

profile_patch_config "$CONFIG"
profile_patch_compose "$COMPOSE"

[[ $(yq eval '.upf.support_features.enable_bpf_datapath' "$CONFIG") == "true" ]]
[[ $(yq eval '.upf.support_features.enable_urr' "$CONFIG") == "true" ]]
[[ $(yq eval '.smf.upfs[0].config.enable_usage_reporting' "$CONFIG") == "true" ]]
[[ $(yq eval '.services.upf1.image' "$COMPOSE") == "$OAI_UPF_IMAGE" ]]
[[ $(yq eval '.services.amf.image' "$COMPOSE") == "example/amf:stable" ]]

echo "OAI UPF profile tests passed."

# Negative: enabling BPF in YAML without generated capabilities must fail.
if profile_validate_compose_capabilities "$COMPOSE" 2>/dev/null; then
    echo "Expected missing BPF capabilities to fail" >&2
    exit 1
fi
yq eval -i '.services.upf1.cap_add = ["NET_ADMIN", "BPF", "SYS_ADMIN", "SYS_RESOURCE"]' "$COMPOSE"
profile_validate_compose_capabilities "$COMPOSE"
echo "Compose BPF capability gates passed."
