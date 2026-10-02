#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
FED_TAG=${1:-}
FED_TAG=${FED_TAG:-v2.2.0}
NWDAF_TAG=${2:-6a1408c9be6f5cf0ddb6c1f1b527a04e36205471}

TMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TMP_ROOT"' EXIT

download_compose_dir() {
  local name=$1
  local repository=$2
  local ref=$3
  local archive_url=$4
  local output_dir=$5
  local archive_file="$TMP_ROOT/${name}.tar.gz"
  local checkout_dir="$TMP_ROOT/${name}"

  mkdir -p "$output_dir"
  if curl -fLS --retry 2 --retry-delay 5 --retry-all-errors \
      -o "$archive_file" "$archive_url"; then
    tar -C "$output_dir" -xzv --strip-components=2 -f "$archive_file"
    return
  fi

  echo "Archive download for $name failed; falling back to Git fetch." >&2
  mkdir -p "$checkout_dir"
  git -C "$checkout_dir" init --quiet
  git -C "$checkout_dir" remote add origin "$repository"
  git -C "$checkout_dir" fetch --quiet --depth=1 origin "$ref"
  git -C "$checkout_dir" checkout --quiet --detach FETCH_HEAD
  cp -a "$checkout_dir/docker-compose/." "$output_dir/"
}

download_compose_dir \
  fed \
  "https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed.git" \
  "$FED_TAG" \
  "https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed/-/archive/${FED_TAG}/oai-cn5g-fed-${FED_TAG}.tar.gz?path=docker-compose" \
  fed

download_compose_dir \
  nwdaf \
  "https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-nwdaf.git" \
  "$NWDAF_TAG" \
  "https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-nwdaf/-/archive/${NWDAF_TAG}/oai-cn5g-nwdaf-${NWDAF_TAG}.tar.gz?path=docker-compose" \
  nwdaf
