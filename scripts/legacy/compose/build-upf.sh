#!/usr/bin/env bash
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    echo 'Usage: build-upf.sh (reads configs/core/options.yaml)'
    exit 0
fi

set -Eeuo pipefail

source "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/env.sh"
SOURCE_DIR="$UPF_SRC"
source "$SCRIPTS_ROOT/lib/oai-upf-profile.sh"
profile_validate

[[ "$OAI_UPF_BUILD_LOCAL" == "true" ]] || {
    echo "oai_upf.build_local_image is false; nothing to build."
    exit 0
}
command -v docker >/dev/null 2>&1 || {
    echo "ERROR: docker is required to build the research OAI UPF image." >&2
    exit 1
}
docker info >/dev/null 2>&1 || {
    echo "ERROR: Docker daemon is not accessible." >&2
    exit 1
}

echo "Initializing OAI UPF build dependencies..."
if [[ -e "$SOURCE_DIR/.git" ]]; then
    git -C "$SOURCE_DIR" submodule update --init --recursive
fi

SOURCE_COMMIT="snapshot"
if [[ -e "$SOURCE_DIR/.git" ]]; then
    SOURCE_COMMIT=$(git -C "$SOURCE_DIR" rev-parse HEAD)
fi
echo "Building $OAI_UPF_IMAGE from OAI UPF commit $SOURCE_COMMIT..."
docker build \
    --file "$SOURCE_DIR/docker/Dockerfile.upf.ubuntu" \
    --target oai-upf \
    --build-arg "GIT_COMMIT=$SOURCE_COMMIT" \
    --tag "$OAI_UPF_IMAGE" \
    "$SOURCE_DIR"

docker image inspect "$OAI_UPF_IMAGE" --format \
    'Built {{.RepoTags}} digest={{.Id}} created={{.Created}}'
