<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Helm Repository for OAI Network Functions 

This repository provides Helm charts for deploying OpenAirInterface (OAI) 5G components, including Core Network Functions, RAN Network Functions, the RIC platform, and xApps.

These charts simplify deployment, configuration, and lifecycle management of OAI network functions in Kubernetes or OpenShift environments.

[Tutorial for deploying helm-charts](https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed/-/blob/master/docs/DEPLOY_SA5G_HC.md?ref_type=heads)

To verify chart rendering syntax locally, run `./ci-scripts/checkHelmChartSyntax.sh`.

## Core Network Functions (OAI 5G Core)
- [OAI-AMF](./oai-5g-core/oai-amf/README.md)
- [OAI-SMF](./oai-5g-core/oai-smf/README.md)
- [OAI-UPF](./oai-5g-core/oai-upf/README.md)
- [OAI-NRF](./oai-5g-core/oai-nrf/README.md)
- [OAI-AUSF](./oai-5g-core/oai-ausf/README.md)
- [OAI-UDR](./oai-5g-core/oai-udr/README.md)
- [OAI-UDM](./oai-5g-core/oai-udm/README.md)
- [OAI-LMF](./oai-5g-core/oai-lmf/README.md)
- [OAI-PCF](./oai-5g-core/oai-pcf/README.md)
- [OAI-NSSF](./oai-5g-core/oai-nssf/README.md)

## RAN Network Functions
- [OAI-CU](./oai-5g-ran/oai-cu/README.md)
- [OAI-CU-CP](./oai-5g-ran/oai-cu-cp/README.md)
- [OAI-CU-UP](./oai-5g-ran/oai-cu-up/README.md)
- [OAI-DU](./oai-5g-ran/oai-du/README.md)
- [OAI-gNB](./oai-5g-ran/oai-gnb/README.md)
- [OAI-NR-UE](./oai-5g-ran/oai-nr-ue/README.md)
- [OAI-gNB-FHI72](./oai-5g-ran/oai-gnb-fhi-72/README.md)
- [OAI-DU-FHI72](./oai-5g-ran/oai-du-fhi72-72/README.md)

## RIC
- [OAI-FLEXRIC](./oai-5g-ran/oai-flexric/README.md)

## Tested Environment

- Kubernetes v1.31+
- Openshift: 4.17+
- Helm: v3.14+

## Future release

- vrtsim as radio for gNB and nr-ue
- raytracer helm-charts
- xApp helm-charts

# License

The charts and ci-scripts are license under [MIT License](./LICENSE), network function helm charts are in [CSSL v1.0](./LICENSES/prefered/CSSL-v1.0.txt) and documentation is license under
[CC-BY-4.0](./LICENSES/preferred/CC-BY-4.0.txt).

For third party libraries and helm-chart check the [NOTICE](./NOTICE) file.

# Contribute

Please check [CONTRIBUTING.md](./CONTRIBUTING.md)
