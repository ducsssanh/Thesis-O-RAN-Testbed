# Datasheet: O-RAN flooding, twinned traffic (2026-11-04)

Follows "Datasheets for Datasets". Research grade. Not published; `research/datasets/oran_flooding_twin_package.tar.gz` is a local package.

## Motivation
Paired RAN and core telemetry per UE per second, for detecting user-plane floods in a 5G O-RAN testbed when KPM can be tampered. Benign traffic replays real 75 s windows of Madrid LTE users; floods are anchored to real packet shapes and to real active-second rates.

## Composition
- 72 runs, 64 800 rows (UE x second), 432 attack episodes, 144 per evasion level, 25 806 attack seconds. KPM present in all rows, profiler in all but 0.01 %.
- `rows.parquet`: KPM, profiler, `c_t`, `c_t_w`, trust and mask with node and per-UE scope, data ages, labels. `windows.csv`: bytes planned and reached per twin window. `raw/`: the files the builder reads.
- **A row of second t holds the traffic of [t-1, t)**: KPM and the profile report at the end of their second.
- Labels and meta, never inputs: `role`, `attack_active`, `attack_bytes`, `attack_bytes_core`, `onset_t`, `t_window`, `evasion`, `vector`, `anchor_bps`, `band`, `window_index`, `attacker_ue`, `client_role`, `run_id`, `phase`, `seed`.
- Twin bands drawn at P1-P4 .25 .25 .20 .30 (real Madrid about .50 .40 .09 .01): re-weight false alarms.
- Only build cells are replayed: I-2650, I-1815, II-816, II-1835.

## Collection
OAI 5G SA with RF simulator, FlexRIC xApp, eBPF UPF profiler, 2 UEs, egress blocked, detection off. Manifest `manifest/design.json`, seed 20261104, fixed before the runs. Each phase: both UEs replay a twin window; one also runs the attack from a random onset in the 15 s pre-roll. L1 hping3 default packets; L2 UDP in the rhythm, TTI times and sizes of another real window; L3 real TCP and DNS clients against a responsive sink, with the same client as a benign hard negative on the other UE.

## QA
Per-run QA `scripts/k8s/exp/v4traffic/qa_twin.py`, log `manifest/campaign_log.jsonl`. 72 kept, 14 failed attempts repeated with the same seeds. Builder tests `scripts/ml/test_build_dataset_twin.py`; offline gate equals the live xApp on 99.9 % of c_t values and 99.8 % of masks. Validation and limits: `research/TRAFFIC-TWINNING-PLAN.md` 6.5 to 6.8 and 9.

## Limits a user must know
- Benign traffic is LTE demand replayed open loop on a testbed cell; it does not react to the network as TCP or ABR would.
- The twin's held-out check ran before the sidecar CPU limit was raised; it cannot be repeated.
- The tamper injection leaves a cue at equal UL rate (benign x0.8 AUC .67, x5 .99): read KPM-only ablations with care.
- No ramp, no react, 3 of 6 L1 vectors, DNS not on port 53, attack rates at 3 fixed levels.
- Bursts of one second can lose bytes at the testbed: use `attack_bytes_core` and `windows.csv`.
- Node trust masks the honest UE of the node; per-UE trust is computed offline and was not run live.
- 2 UEs only: dilution of pooled trust with more UEs is derived, not measured.
