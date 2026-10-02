#!/usr/bin/env bash

set -Eeuo pipefail

CONTEXT="${OAI_K8S_CONTEXT:-oai-lab}"
NAMESPACE="${OAI_K8S_NAMESPACE:-oai-lab}"
TIMEOUT="${OAI_K8S_ROLLOUT_TIMEOUT:-180s}"
DRY_RUN=false

CORE_DEPLOYMENTS=(
  oai-nrf
  oai-udr
  oai-udm
  oai-ausf
  oai-amf
  oai-smf
  oai-lab-dn
  oai-upf
)

usage() {
  cat <<'EOF'
Usage: start-deployments.sh [options] [COMPONENT ...]

Scale selected Kubernetes Deployments to one replica and wait for each rollout.
With no COMPONENT, start the complete OAI core in dependency order.

Components may be written as aliases or Deployment names:
  nrf udr udm ausf amf smf dn upf
  oai-nrf ... oai-lab-dn oai-upf

Options:
  --context NAME     Kubernetes context (default: oai-lab)
  --namespace NAME   Kubernetes namespace (default: oai-lab)
  --timeout VALUE    Rollout timeout per Deployment (default: 180s)
  --dry-run          Print the operations without changing the cluster
  -h, --help         Show this help

This script does not start minikube, run Helm, load images, bootstrap networks,
or rerun the subscriber Job.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

deployment_name() {
  case "$1" in
    nrf|oai-nrf) printf '%s\n' oai-nrf ;;
    udr|oai-udr) printf '%s\n' oai-udr ;;
    udm|oai-udm) printf '%s\n' oai-udm ;;
    ausf|oai-ausf) printf '%s\n' oai-ausf ;;
    amf|oai-amf) printf '%s\n' oai-amf ;;
    smf|oai-smf) printf '%s\n' oai-smf ;;
    dn|oai-lab-dn) printf '%s\n' oai-lab-dn ;;
    upf|oai-upf) printf '%s\n' oai-upf ;;
    *) die "Unknown component '$1'. Run --help for the supported names." ;;
  esac
}

components=()
while (($#)); do
  case "$1" in
    --context)
      (($# >= 2)) || die '--context requires a value'
      CONTEXT="$2"
      shift 2
      ;;
    --namespace)
      (($# >= 2)) || die '--namespace requires a value'
      NAMESPACE="$2"
      shift 2
      ;;
    --timeout)
      (($# >= 2)) || die '--timeout requires a value'
      TIMEOUT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($#)); do components+=("$1"); shift; done
      ;;
    -*) die "Unknown option '$1'" ;;
    *)
      components+=("$1")
      shift
      ;;
  esac
done

deployments=()
if ((${#components[@]} == 0)); then
  deployments=("${CORE_DEPLOYMENTS[@]}")
else
  for component in "${components[@]}"; do
    deployments+=("$(deployment_name "$component")")
  done
fi

command -v kubectl >/dev/null 2>&1 || die 'kubectl is required'
kubectl config get-contexts "$CONTEXT" >/dev/null 2>&1 || \
  die "Kubernetes context '$CONTEXT' does not exist"

# Validate every target before scaling the first one, so a typo or stale
# Deployment name cannot leave a partially started core.
for deployment in "${deployments[@]}"; do
  kubectl --context="$CONTEXT" --namespace="$NAMESPACE" \
    get deployment "$deployment" >/dev/null 2>&1 || \
    die "Deployment '$deployment' was not found in namespace '$NAMESPACE'"
done

for deployment in "${deployments[@]}"; do
  printf '==> Starting deployment/%s (%s/%s)\n' \
    "$deployment" "$CONTEXT" "$NAMESPACE"
  if [[ "$DRY_RUN" == true ]]; then
    printf 'kubectl --context=%q --namespace=%q scale deployment/%q --replicas=1\n' \
      "$CONTEXT" "$NAMESPACE" "$deployment"
    printf 'kubectl --context=%q --namespace=%q rollout status deployment/%q --timeout=%q\n' \
      "$CONTEXT" "$NAMESPACE" "$deployment" "$TIMEOUT"
    continue
  fi

  kubectl --context="$CONTEXT" --namespace="$NAMESPACE" \
    scale "deployment/$deployment" --replicas=1
  kubectl --context="$CONTEXT" --namespace="$NAMESPACE" \
    rollout status "deployment/$deployment" --timeout="$TIMEOUT"
done

if [[ "$DRY_RUN" == false ]]; then
  kubectl --context="$CONTEXT" --namespace="$NAMESPACE" \
    get deployment "${deployments[@]}"
fi
