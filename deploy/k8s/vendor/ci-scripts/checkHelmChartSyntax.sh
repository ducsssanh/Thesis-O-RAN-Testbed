#!/bin/bash
# SPDX-License-Identifier: MIT

set -euo pipefail

if ! command -v helm >/dev/null 2>&1; then
  echo "helm is not installed, install it from --> https://helm.sh/docs/intro/install/"
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_root="$(mktemp -d)"
work_repo="$work_root/charts"

cleanup() {
  rm -rf "$work_root"
}
trap cleanup EXIT

mkdir -p "$work_repo"
tar --exclude=.git -cf - -C "$repo_root" . | tar -xf - -C "$work_repo"

mapfile -t charts < <(find "$work_repo/oai-5g-core" "$work_repo/oai-5g-ran" "$work_repo/e2e_scenarios" -name Chart.yaml -print | sort | xargs -n1 dirname)

if [[ "${#charts[@]}" -eq 0 ]]; then
  echo "No charts found"
  exit 1
fi

for chart in "${charts[@]}"; do
  relative_chart="${chart#"$work_repo"/}"
  echo "Checking ${relative_chart}"
  helm dependency build "$chart" >/dev/null
  helm template syntax-check "$chart" >/dev/null
done

echo "Helm chart syntax verification passed for ${#charts[@]} charts."
