# Cross-domain uplink-flood defense for O-RAN: testbed and code

Code of the graduation thesis *Cross-Domain Detection and Mitigation of Uplink Flooding in O-RAN With KPM Trust
Verification and an eBPF-Based UPF*. It holds a complete O-RAN and 5G standalone testbed on one machine, the defense
xApp, the telemetry pipeline from the UPF to the xApp, and the tools that generated the dataset, trained the detector
and produced the results.

| Part | What runs | Where the code is |
|---|---|---|
| RAN | OAI gNB and two OAI NR UEs over the RF simulator, E2 agent with E2SM-KPM and E2SM-RC | `patches/oai-ran.patch` |
| Core | OAI 5G core; UPF with an eBPF/XDP datapath, a per-session profiler and a per-SUPI policy (rate limit, block) | `patches/oai-upf.patch`, `src/upf/`, `patches/oai-smf*.patch` |
| Non-RT RIC | O-RAN SC Information Coordination Service; a producer that turns UPF telemetry into A1-EI information | `src/urr-producer/` |
| Near-RT RIC | FlexRIC; A1-EI adapter; the defense xApp (KPM trust gate, embedded XGBoost classifier, policy, RAN and UPF actions) | `src/a1-ei-adapter/`, `src/xapp/`, `patches/flexric*.patch` |
| Experiments | Traffic twinning (replay of real LTE user windows), attack generators, campaign runner, quality checks | `scripts/k8s/exp/`, `research/twinning/` |
| Analysis | Dataset builder, training, export of the model to the xApp, reports and figures | `scripts/ml/` |

Everything runs in a single-node minikube cluster (profile and kubectl context `oai-lab`), in four Helm releases:
`oai-core`, `oai-ran`, `near-rt-ric`, `non-rt-ric`.

## Repository layout

```
src/xapp/            defense xApp, C (copied into FlexRIC's examples/xApp/c/monitor/ at build time)
src/upf/             files added to the OAI UPF: security API, policy store, eBPF policy and profiler maps
src/urr-producer/    A1-EI information producer, Go
src/a1-ei-adapter/   A1-EI consumer that delivers the telemetry to the xApp, Go
patches/             changes to the upstream sources, one patch per tree (patches/README.md)
deploy/k8s/          Helm charts (charts/), lab values (values/minikube.yaml), image definitions (images/),
                     the trained model built into the xApp image (images/models/clf_model.json)
scripts/k8s/         lab lifecycle (lab.sh), recovery scripts, experiment runner (exp/)
scripts/ml/          dataset, training, export, evaluation; rounds/ holds the run scripts of each round
scripts/verify-oai-upstream.sh   rebuilds the upstream source trees and checks them against the patches
experiments/scenarios/           scenario files for scripts/k8s/exp/run.py
research/twinning/   traffic twinning: reduction of the traces, window library, validation, gate evaluation
research/datasets/oran_flooding_twin/   datasheet and campaign manifest of the main dataset
tests/               unit and parity tests
```

Not in the repository: the upstream source trees (rebuilt, step 1), the Madrid LTE traces and the recorded datasets
(`data/`, `research/datasets/*/rows.parquet`), and everything generated at run time (`artifacts/`).

## Requirements

- Ubuntu 24.04 on x86-64, at least 8 CPU cores and 16 GiB of memory for the cluster (the lab was run on 18 cores, 30 GiB),
  25 GiB of free disk for the first build.
- Docker Engine, minikube (v1.38), Helm 3, kubectl, Python 3.12 with PyYAML, `tshark`, `iproute2`, `openssl`, `patch`, `git`.
- Network access to GitHub, GitLab (eurecom.fr) and Docker Hub during the build.

Tool versions used: Docker 29.8, Helm 3.20, Kubernetes v1.33.13 (set in `deploy/k8s/values/minikube.yaml`).

## Install and deploy

All commands run from the repository root. `scripts/k8s/lab.sh` is the single entry point; every `kubectl` and `helm`
call of the tooling uses the context `oai-lab` and leaves the default context alone.

### 1. Rebuild the upstream sources

```bash
scripts/verify-oai-upstream.sh --into src   # fetches the pinned commits, applies patches/, src/xapp and src/upf
scripts/verify-oai-upstream.sh              # must print MATCH for all five trees
```

This writes `src/oai-upf`, `src/oai-smf`, `src/flexric` and `src/oai-ran`. The pinned commits are in the script.

### 2. Build the images

```bash
scripts/k8s/lab.sh check       # values, chart rendering, host preflight (CPU, memory, disk, routes)
scripts/k8s/lab.sh build       # tools, UPF, radio (gNB, UE, FlexRIC), SMF, all compiled from source: the first build is long
```

Image tags and IDs are locked in `artifacts/k8s/state/`. Logs are in `artifacts/k8s/build/`.

### 3. Create the cluster

```bash
scripts/k8s/lab.sh up --stage bootstrap    # starts minikube (profile oai-lab), installs Multus, creates the lab
                                           # Secret from deploy/k8s/values/ue1.conf, runs the network and BPF probes
scripts/k8s/coredns-search-guard.sh        # CoreDNS: answer search-path and PTR lookups of the lab networks locally
```

The bootstrap stage uses the baseline chart `deploy/k8s/chart` in the namespace `oai-lab`. It only prepares the
cluster; the network functions run in the four releases of the next step.

### 4. Bring up the four releases

```bash
scripts/k8s/lab.sh certs                   # private CA and TLS Secrets of the telemetry path
scripts/k8s/lab.sh build-ei                # producer and adapter images
scripts/k8s/lab.sh build-xapp              # xApp image (FlexRIC + src/xapp + the model)
scripts/k8s/lab.sh cutover                 # installs the four releases at zero replicas, stops the baseline pods
scripts/k8s/lab.sh up --stage core         # database, subscribers, NRF ... SMF, UPF; checks NRF, PFCP and XDP
scripts/k8s/lab.sh up --stage nonrt        # Information Coordination Service, producer
scripts/k8s/lab.sh up --stage near-rt      # FlexRIC, adapter
scripts/k8s/lab.sh up --stage ran          # gNB, first UE, xApp; checks E2, the PDU session and KPM

XAPP=$(python3 -c 'import json;print(json.load(open("artifacts/k8s/state/xapp-image.json"))["image"])')
ADAPTER=$(python3 -c 'import json;print(json.load(open("artifacts/k8s/state/ei-images.json"))["adapter"]["image"])')
scripts/k8s/lab.sh rollout xapp "$XAPP"          # the built xApp image
scripts/k8s/lab.sh rollout adapter "$ADAPTER"    # enables the push of telemetry to the xApp
```

Second UE (the experiments use two):

```bash
helm --kube-context oai-lab -n oai-ran upgrade oai-ran deploy/k8s/charts/ran --reuse-values \
  --set oai-nr-ue2.enabled=true --set global.lab.extraUeReplicas=1
scripts/k8s/recover_ran.sh --keep-flexric   # the xApp learns both SUPIs
```

### 5. Check

```bash
scripts/k8s/lab.sh status
scripts/k8s/lab.sh exp run smoke      # about 2 minutes: benign traffic on both UEs, every record type exported
```

The smoke run must report a delivered ratio of 1, level 0 for both UEs and matching KPM and core rates. Its files
are in `artifacts/experiments/<time>_smoke/`.

## Operating the testbed

| Task | Command |
|---|---|
| Stop the cluster, keep everything | `minikube stop -p oai-lab` |
| Start it again | `minikube start -p oai-lab --keep-context`, then the two recovery scripts below |
| Core out of order (no PFCP association, UE without a tunnel, SMF restarted) | `scripts/k8s/recover_core_ordered.sh` |
| xApp or gNB lost its E2 association, xApp does not list both SUPIs | `scripts/k8s/recover_ran.sh` |
| New xApp after editing `src/xapp/` | `scripts/k8s/lab.sh build-xapp`, then `scripts/k8s/lab.sh rollout xapp <image>` |
| New UPF image | stop the UEs, then `scripts/k8s/lab.sh rollout upf <image>` |
| Inspect the UPF's BPF maps from the host | `scripts/k8s/bpftool.sh map list` |

After a node restart the pods come up before Multus has attached their secondary interfaces, and the OAI SMF needs
the UPF registered before it starts. Run `recover_core_ordered.sh`, then `recover_ran.sh`; the core script ends with
"xApp does not know both SUPIs" until the second one has run. `minikube image load` leaves a tarball of every image
in the node and in `~/.minikube/cache/images`; remove them when disk runs low.

After the xApp restarts it needs up to a minute to learn the UE identities (the AMF prints its UE table every 20 s);
the runner refuses to start a run until `GET /v1/defense/state` lists both SUPIs.

The xApp is configured by the block `global.lab.defense.xapp` of `deploy/k8s/values/minikube.yaml`. The idle
testbed runs the fair-use rule; a campaign run selects the embedded model and its actions over the xApp's REST API
(`/v1/defense/*` on port 8090 inside the pod) and restores the defaults at the end.

## Running experiments

One run: `scripts/k8s/exp/run.py run <scenario.yaml>` (same as `lab.sh exp run`). It applies the defense
configuration of the scenario, starts the traffic of each phase, and exports KPM, core telemetry, xApp decisions,
RAN control messages and per-second traffic counters to `artifacts/experiments/`.

A campaign is a manifest of runs fixed before it starts:

```bash
cd scripts/k8s/exp/v4traffic
python design_twin.py --e2e --seed <seed> --rel-ratio 0.7 --rtt-budget 0.5 --out <dir>/manifest/design.json   # held-out end-to-end design; other designs: --l2, --live5, --live6
cd -
systemd-inhibit --what=sleep:idle:handle-lid-switch \
  .venv-ml/bin/python scripts/k8s/exp/v4traffic/campaign_twin.py --manifest <dir>/manifest --lo 0 --hi 24
```

`campaign_twin.py` runs each entry, checks it (`qa_twin.py`), recovers the testbed and repeats a failed run with the
same seeds, and logs to `<dir>/manifest/campaign_log.jsonl`. Do not build images or train models while a campaign
runs: the RF simulator is sensitive to CPU load.

The benign traffic replays 75 s windows of real users from the Madrid LTE traces. The window library
(`research/twinning/benign_windows*.npz`) is not in the repository; build it from the traces with
`research/twinning/madrid_reduce.py`, `madrid_windows.py` and `madrid_tti_windows.py`. Attacks are laid over the
replay at three levels: L1 (hping3 at a matched rate), L2 (UDP sender that follows another real window), L3 (real TCP
and DNS clients).

## Dataset, training and evaluation

```bash
python3 -m venv .venv-ml && .venv-ml/bin/pip install -r scripts/ml/requirements.txt
```

| Step | Script |
|---|---|
| Rows of a campaign (one UE, one second: KPM, profiler, gate, labels) | `scripts/ml/build_dataset_twin.py --out <dir> <run dirs>` |
| Episodes and KPM tamper scenarios (hide, frame, swap, mimic) | `scripts/ml/clf_features.py` (uses `episodes.py`, `tamper_replay.py`) |
| Training (XGBoost, LightGBM, MLP, GRU; grouped split by real user) | `scripts/ml/train_clf.py` |
| Model file for the xApp and the alarm rules, chosen on out-of-fold scores | `scripts/ml/export_clf.py`, `select_block_rule.py` |
| C against Python: logits and block decisions | `scripts/ml/clf_parity_seq.py`, `clf_block_expected.py`, `tests/xapp/test_clf_parity.c` |
| Live test report, parity of live and offline decisions | `scripts/ml/live_report.py`, `live_parity.py`, `live_by_case.py`, `live_benign_fa.py` |
| Ablations (core only, without the gate, KPM only) and baselines | `scripts/ml/ablation_eval.py`, `abl_*.py`, `baselines.py` |
| False-alarm curves | `scripts/ml/far_curves.py`, `far_cross_vs_ran.py` |
| End-to-end mitigation report, escalation calibration | `scripts/ml/e2e_report.py`, `e2e_thesis_extra.py`, `esc_calib.py` |
| Figures of the thesis | `scripts/ml/thesis_figs.py`, `far_curves_fig.py`, `e2e_timeseries.py` |

`scripts/ml/rounds/` holds the shell scripts that ran these steps round by round, in the order of the thesis:
model family (`run_clf.sh`, `clf_all_reports.sh`), L2 campaign and clean test (`clf_round4.sh`), live tests 1 to 4
(`after_live*.sh`, `mimic_*.sh`, `e123_*.sh`, `chain_live4.sh`), the deployed model and the blind live test
(`v5_inputs.sh`, `v5_train.sh`, `v5_chain.sh`, `after_live5.sh`), the benign-only extension (`live6_chain.sh`),
ablations and comparison (`ablation_chain.sh`, `cmp_chain.sh`). They record how each number was produced and expect
the raw runs under `artifacts/experiments/`.

Names used in scripts and data:

| Name | Meaning |
|---|---|
| `oran_flooding_twin` | main campaign, 72 runs, attacks L1 to L3 |
| `oran_flooding_twin_l2` | L2 campaign, 36 runs: 24 for training, 12 as a clean test |
| `oran_flooding_live`, `live2`, `live3`, `live4` | live tests during development |
| `oran_flooding_live5` | blind live test on users never replayed before |
| `oran_flooding_live6` | benign-only runs that extend the false-alarm measurement |
| `oran_flooding_e2e`, `e2e_calib*` | end-to-end development campaign and calibration runs |
| `oran_flooding_e2e2` | held-out end-to-end campaign |
| `R080_v5` | the deployed model (three XGBoost seeds, 31 inputs), exported as `clf_model.json` |

## Tests

```bash
python3 -m unittest discover -s tests/k8s                                     # lab tooling
python3 -m unittest tests.test_k8s_staged tests.test_k8s_staged_helpers tests.test_k8s_real_urr_gate
(cd src/urr-producer && go test ./...) && (cd src/a1-ei-adapter && go test ./...)
.venv-ml/bin/python scripts/k8s/exp/v4traffic/test_backends.py                # traffic generators
.venv-ml/bin/python scripts/k8s/exp/v4traffic/test_schedules.py
.venv-ml/bin/python scripts/ml/test_build_dataset_twin.py
.venv-ml/bin/python research/twinning/test_validate_twin.py
cc -I src/xapp tests/xapp/test_policy_rules.c -o /tmp/t && /tmp/t             # escalation table
tests/k8s/test_urr_receiver.sh <xApp image>                                   # telemetry receiver of the xApp
```

`tests/xapp/test_clf_parity.c` and `tests/xapp/test_esc_rule.c` compare the C code of the xApp with the Python
reference on exported sequences; their headers give the build line and the inputs.

## Limits

- One cell, two UEs, RF simulator: radio conditions and botnet scale are not reproduced.
- The path from the UPF to the xApp uses A1-EI with information types defined for this testbed; pushing per-session
  UPF telemetry every second is an extension, not a standard O-RAN flow.
- The UPF policy is set by the xApp through the UPF's own HTTP API, not through NEF, PCF and SMF.
- The lab uses test SIM credentials and plain HTTP inside the cluster.
