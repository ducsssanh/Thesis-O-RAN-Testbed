# Experiments

Definitions of the experiments live here (`scenarios/*.yaml`, committed); the
runner is `scripts/k8s/exp/`; results go to `artifacts/experiments/` (one
directory per campaign, never edited by hand).

```bash
scripts/k8s/lab.sh exp list                                   # scenarios
scripts/k8s/lab.sh exp run smoke                              # ~2 min pipeline check
scripts/k8s/lab.sh exp run e3-reconnect --reps 5 --tag final  # a campaign
scripts/k8s/lab.sh exp run e3-reconnect --variants two-layer --reps 1
scripts/k8s/lab.sh exp report artifacts/experiments/<campaign>   # recompute numbers from stored files
scripts/k8s/lab.sh exp restore                                # defense back to deploy/k8s/values/minikube.yaml
```

Prerequisite: the four namespaces up, the UEs of the scenario attached and
known to the xApp (`GET /v1/defense/state` lists their SUPI with an AMF UE ID),
xApp with the run-time endpoints of C36 (`/v1/defense/{enabled,core,mode,timing,policy,reset}`),
UPF with C35, ≥ 5 GiB free disk. The runner re-attaches a UE whose PDU session
is gone (e.g. released by T2 after a long block) and restarts the xApp after it.

## Results layout

```
artifacts/experiments/<YYYYmmdd-HHMMSS>_<scenario>[_<tag>]/
  campaign.json            scenario as run, variants, reps, image locks, defense config restored at the end
  runs.csv                 one row per run: headline numbers + per-phase/UE numbers
  summary.csv              per variant: n, mean, sd, min, max of every number
  summary.md               headline table (mean ± sd) and per-phase table
  runs/<variant>/rep-NN/
    run.json               status, preflight facts, defense config, phases with timestamps, UE IP history
    phases.csv             phase, start/end (Unix s), flags, action (e.g. UE restart and how long it took)
    metrics.json           all numbers of this run (computed only from the files below)
    error.txt              traceback of a failed run
    meta/                  snapshot_start.json, snapshot_end.json (defense state, UPF /v1/ues, /v1/stats,
                           /v1/sessions, /v1/info), link_stats.json (N3/N6 counters)
    traffic/               flows.json, <phase>_<ue>_<dir>.csv (iperf2 receiver, one row per second + final)
    dataplane/             dn_per_second.csv (packets and UDP payload bytes per UE address and direction at the DN's N6)
    ran/                   kpm.csv (per-UE KPM rows, with SUPI), kpm_cells.csv, rc_control.jsonl (E2SM-RC requests/acks)
    core/                  urr_received.jsonl (URR as the xApp got it), producer_normalized.jsonl, producer_smf_raw.jsonl
                           (SMF notifications), adapter_delivery.jsonl, upf_audit.jsonl (UPF Security API audit),
                           pfcp.pcap (N4), pfcp_messages.csv, pfcp_usage_reports.csv
    defense/               events.jsonl (evidence / level / action / verified), features.jsonl (classifier input
                           = dataset), state_timeline.jsonl (defense state every 1 s), db_rows.json
    logs/                  xapp, flexric, gnb, upf, smf, amf, <ue> .log.gz (since the run start, with timestamps)
```

These are the records of the old `lab.sh experiment` run (KPM CSVs, URR at
every hop, PFCP capture and its CSVs, iperf CSVs, data-plane counters,
metadata) plus the defense records, cut by the run's time window from the
continuous files in the pods — no `new-run` (which needs the UEs stopped)
between runs.

## Scenario file

```yaml
name: e3-reconnect
description: |
  ...
ues: {ue1: attacker, ue2: benign}        # roles: attacker | benign (ue1..ue4 = oai-nr-ue..oai-nr-ue4)
reps: 5
payload_bytes: 1200                      # UDP payload (GTP-U + IP + UDP stay below MTU 1500)
drain: {quiet_kbps: 300, timeout_s: 420} # wait until every UE's KPM rate is quiet before a run
defense_common:                          # applied before every run, then the variant's settings
  classes: {ue1: default, ue2: default}  # fair-use class per UE (persists in the xApp DB)
  timing: {expiryS: [20, 30, 240, 240], probationS: 120, fusionS: 10}
variants:                                # each one is a defense configuration
  - name: two-layer
    defense: {enabled: true, core: true, mode: slice}   # enabled, core (UPF layer), mode slice|ue, classifier rules|external
phases:                                  # run in order; flows per UE: ul / dl offered rate (iperf2 UDP)
  - {name: baseline, duration: 20, baseline: true, flows: {ue1: {ul: 1M}, ue2: {ul: 1M}}}
  - name: attack
    duration: 180
    attack: true                         # times are measured from the start of this phase
    flows: {ue1: {ul: 10M}, ue2: {ul: 1M}}
    stop_when: {ue: ue1, level_gte: 3, hold_s: 15}   # end the phase early
  - name: reconnect
    reconnect: true
    action: {restart_ue: ue1, restart_xapp: true}   # before the phase's flows start
    duration: 60
    flows: {ue1: {ul: 10M}, ue2: {ul: 1M}}
report: [attacker_t_level1_s, ...]       # rows of the headline table (default: all headline numbers)
```

Before every run the defense state of the scenario's UEs is reset (level 0,
no UPF policy). At the end of a campaign the defense configuration found at
its start is restored.

## Numbers (metrics.json)

Per phase and UE (`phases.<phase>.<ue>`):

| key | meaning |
|---|---|
| `offered_{ul,dl}_mbps` | sum of the offered rates of the UE's flows in the phase |
| `delivered_{ul,dl}_mbps` | bytes received by the iperf2 receiver in the phase / phase duration |
| `loss_{ul,dl}_pct` | lost / sent datagrams of the receiver's 1 s rows |
| `dn_{ul,dl}_mbps` | UDP payload bytes of the UE's address at the DN's N6 / duration (what actually left / reached the network) |
| `kpm_{ul,dl}_kbps`, `kpm_prb_{ul,dl}_pct` | mean of the UE's KPM rows (PDCP SDU volume per 1 s period; PRB share) |
| `urr_{ul,dl}_kbps` | mean URR rate of the SUPI (volume / measurement period; period = difference of the cumulative Duration of OAI) |
| `max_level` | highest defense level in the 1 s state timeline |

Per UE over the run (`ues.<ue>`): `evidence`, `max_level`, `t_first_evidence_s`,
`t_level1_s` … `t_level4_s`, `t_ran_limit_s` (first acknowledged RAN limit),
`t_upf_block_s` (first acknowledged UPF block) — seconds from the start of the
`attack` phase —, `rrc_releases`, `ran_actions`, `upf_actions`, `verified`,
`unverified`, `upf_drop_{ul,dl}_{pkts,bytes}` (UPF security drops during the run).

Headline (`headline`): `attacker_*` (the timings above, `delivered_ratio_attack` =
delivered / offered in the attack phase, `dn_ul_mbps_attack`,
`dn_ul_mbps_after_reconnect`, `dn_ul_mbytes_after_reconnect`, `upf_drop_ul_mbytes`)
and `benign_*` (`delivered_ratio_baseline`, `delivered_ratio_attack`,
`loss_pct_attack`, `max_level`, `evidence`; with several benign UEs: worst
ratio, highest level, total evidence).

## Scenarios

| file | what | runs |
|---|---|---|
| `smoke.yaml` | pipeline check, benign only | 1 × 1, ~2 min |
| `e1-ran-layer.yaml` | RAN layer alone vs flood: no defense / slice / per-UE quota | 3 × 5, ~1 h |
| `e2-benign-fpr.yaml` | false positives on benign profiles; dataset for the AI phase | 1 × 3, ~25 min |
| `e3-reconnect.yaml` | reconnecting attacker: no defense / RAN only / both layers | 3 × 5, ~1.5 h |

E4 (UPF overhead with 0/1k/10k policies) needs a policy seeder and small-packet
pps tests; not in this runner yet.
