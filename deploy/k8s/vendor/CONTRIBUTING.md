<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Contributing

Thanks for contributing to the OAI Helm charts repository.

This repository contains Helm charts for OAI 5G Core, RAN, RIC, and end-to-end scenarios. 
Contributions should keep charts deployable, documentation aligned with behavior, and changes scoped to the affected charts.

## Repository Layout

- `oai-5g-core/`: Helm charts for OAI 5G Core network functions and parent charts.
- `oai-5g-ran/`: Helm charts for OAI RAN components and FlexRIC.
- `e2e_scenarios/`: End-to-end scenario charts and example compositions.
- `ci-scripts/`: Local and CI validation scripts.

Each chart generally contains:

- `Chart.yaml`: chart metadata and version.
- `values.yaml`: deployment and infrastructure settings.
- `config.yaml`: functional application configuration.
- `templates/`: rendered Kubernetes resources.
- `README.md`: chart-specific usage and configuration notes.

## Development Expectations

- Keep changes focused. If you modify one chart, avoid unrelated edits in other charts.
- Update `README.md` when configuration, behavior, prerequisites, or examples change.
- Update `Chart.yaml` when the chart content changes and a new chart release is intended.
- Preserve the existing separation between `values.yaml` and `config.yaml`:
  - `values.yaml` for deployment, image, and infrastructure parameters.
  - `config.yaml` for network-function runtime configuration.
- Follow the existing templating style and naming conventions already used in the chart you are editing.

## Local Validation

Before submitting a change, run the local syntax check from the repository root:

```bash
./ci-scripts/checkHelmChartSyntax.sh
```

This script renders every chart under `oai-5g-core/`, `oai-5g-ran/`, and `e2e_scenarios/`.

If your change affects deployment behavior on a cluster, also validate it in an environment you control. 
The repository includes longer end-to-end scripts for:

- Minikube: `./ci-scripts/checkHelmChartsMinikube.sh`
- OpenShift: `./ci-scripts/checkHelmChartsOC.sh`

Use the Minikube script for local Kubernetes-based testing when you want to verify that charts install, 
pods become ready, and basic end-to-end traffic works in a local cluster. A typical local workflow is:

```bash
./ci-scripts/checkHelmChartsMinikube.sh
```

`create-cluster.sh` prepares a Minikube environment with the components expected by the charts, 
including Multus-related setup. It is for "Manual testing or easily create a testing environment".
Run this path when changing templates, networking, startup ordering, service exposure, or parent-chart integration.

Use the OpenShift script when your change is specific to OpenShift behavior, security context constraints, 
SCC or RBAC behavior, Multus handling on OpenShift, or when you need to confirm that `kubernetesDistribution=Openshift` still works as expected:

```bash
./ci-scripts/checkHelmChartsOC.sh
```

If you don't have openshift then no issues, please mention in the merge request.

This path requires an accessible OpenShift cluster and a working `oc` and `kubectl` context.

These scripts are integration-oriented rather than fast syntax checks, so contributors should normally run:

1. `./ci-scripts/checkHelmChartSyntax.sh` for every chart change.
2. `./ci-scripts/checkHelmChartsMinikube.sh` for local cluster validation when behavior changes.
3. `./ci-scripts/checkHelmChartsOC.sh` when the change affects OpenShift compatibility or OpenShift-specific logic.

## Documentation

- Keep top-level and chart-level documentation consistent with the implemented behavior.
- Use concrete install or upgrade examples when adding new options.
- If you add, rename, or remove values, document them in the affected chart `README.md`.

## Versioning and Release Notes

- Chart versions are declared in each chart `Chart.yaml`.
- Repository-wide release notes are tracked in `CHANGELOG.md`.
- If your contribution is intended for a release, make sure the relevant version and release notes are updated as part of the same change.

## License and Headers

This repository is MIT licensed. Keep existing SPDX headers intact and use the current conventions:

- CI-scripts and YAML files typically use `SPDX-License-Identifier: MIT`.
- Markdown documentation typically uses `SPDX-License-Identifier: CC-BY-4.0`.
- Network function configuration files use `SPDX-License-Identifier: LicenseRef-CSSL-1.0`

For third party libraries and helm-chart check the [NOTICE](./NOTICE) file.

When adding new files, match the header style already used by similar files in the repository.

## Merge Requests

- Describe the problem the change solves.
- Summarize which charts or scenarios are affected.
- List the validation you ran locally.
- Include any required manual steps, prerequisites, or migration notes.

Small, well-scoped merge requests are easier to review and merge than large mixed changes.
