# v4 QA report — `/home/ducsssanh/6G/O-RAN/DATN/Codebase/research/datasets/oran_flooding_v4`

Rows: 87294 · BENIGN 32779 · MALICIOUS 29333 · IDLE 25182

## 1. Causality audit (independent of the builder)

| stream | rows checked | violations (arrival_ts > t) |
|---|---:|---:|
| kpm | 87294 | **0** |
| urr | 86937 | **0** |
| prof | 87196 | **0** |

For comparison, the v3-style xApp join (`defense/features.jsonl`) of the same run: 87470 rows, **241 (0.3%) used a future (+1 s) URR sample and 0 (0.0%) a future profiler sample** — the C5 leak the v4 build removes.

## 2. Data age (s) at the row's second

| stream | median | p90 | max | present % |
|---|---:|---:|---:|---:|
| kpm | 0.83 | 1.00 | 1.03 | 100.0 |
| urr | 2.16 | 3.19 | 5.55 | 97.8 |
| prof | 1.84 | 2.83 | 4.51 | 99.9 |

Presence by label (URR / profiler):

| label | URR % | prof % |
|---|---:|---:|
| BENIGN | 99.4 | 100.0 |
| IDLE | 93.7 | 99.6 |
| MALICIOUS | 99.7 | 100.0 |

## 3. Design balance (excl. IDLE)

```
label    BENIGN  MALICIOUS
meta_ue                   
ue1       16044      15012
ue2       16735      14321
```

P(malicious | UE): ue1 0.48, ue2 0.46

Balanced on UE.

P(malicious | backend): dns_client 0.00, hping 0.53, iperf 0.50, pacer 0.54, synflood 1.00, tcp_shortconn 0.00  — dual-use in band (benign-only backends excluded)

P(malicious | victim mode): responsive 0.48, silent 0.47  — dual-use in band

P(malicious | load level): 0.2 0.50, 0.4 0.47, 0.6 0.50, 0.8 0.45, 1.2 0.48  (load distribution should match across classes)

P(malicious | congestion): 0.0 0.47, 1.0 0.49  (load distribution should match across classes)

χ² independence of label vs each nuisance (phase-UE units; dual-use backends only; p > 0.05 ⇒ no evidence of dependence):

| nuisance | χ² | dof | n | p |
|---|---:|---:|---:|---:|
| ue | 0.00 | 1 | 1056 | 1.000 |
| backend | 0.52 | 2 | 864 | 0.771 |
| victim_mode | 0.01 | 1 | 1056 | 0.932 |
| load_level | 1.08 | 4 | 1056 | 0.897 |
| congestion | 0.10 | 1 | 1056 | 0.757 |

## 4. Achieved vs target (URR ground truth, ±10%, per native unit)

Per-phase achieved/target ratio (mean rate over the phase), by backend × class:

| backend | class | phases | median ratio | p10 | p90 | achieved_ok |
|---|---|---:|---:|---:|---:|---:|
| dns_client | BENIGN | 78 | 0.989 | 0.959 | 1.012 | 1.00 |
| hping | BENIGN | 156 | 0.991 | 0.882 | 1.023 | 0.88 |
| hping | MALICIOUS | 176 | 0.973 | 0.873 | 1.030 | 0.85 |
| iperf | BENIGN | 36 | 1.014 | 0.982 | 1.039 | 0.97 |
| iperf | MALICIOUS | 36 | 1.015 | 0.980 | 1.051 | 1.00 |
| pacer | BENIGN | 210 | 1.022 | 0.961 | 1.089 | 0.88 |
| pacer | MALICIOUS | 250 | 1.024 | 0.978 | 1.072 | 0.94 |
| synflood | MALICIOUS | 36 | 1.010 | 0.922 | 1.056 | 0.94 |

By attack family / benign class (`backend/model`):

| family | class | phases | median ratio | achieved_ok |
|---|---|---:|---:|---:|
| benign_benign | BENIGN | 120 | 1.004 | 0.96 |
| dns_heavy | BENIGN | 78 | 0.989 | 1.00 |
| fanout_benign | BENIGN | 42 | 1.017 | 1.00 |
| hping/cbr | MALICIOUS | 78 | 0.959 | 0.77 |
| hping/hawkes | MALICIOUS | 42 | 0.932 | 0.81 |
| hping/mmpp2 | MALICIOUS | 56 | 1.007 | 1.00 |
| icmp_ping | BENIGN | 42 | 0.911 | 0.57 |
| iperf/cbr | MALICIOUS | 36 | 1.015 | 1.00 |
| onoff_pareto | BENIGN | 42 | 1.028 | 0.86 |
| pacer/cbr | MALICIOUS | 104 | 1.025 | 0.99 |
| pacer/fgn | MALICIOUS | 62 | 1.026 | 0.95 |
| pacer/onoff_pareto | MALICIOUS | 42 | 1.016 | 0.95 |
| pacer/pulsing | MALICIOUS | 42 | 1.025 | 0.81 |
| synflood/hawkes | MALICIOUS | 36 | 1.010 | 0.94 |
| udp_bidir | BENIGN | 114 | 1.014 | 0.98 |
| udp_nofeedback | BENIGN | 42 | 1.069 | 0.69 |

Phase-level achieved_ok: 892/978 = **0.91** (target ≥ 0.90). Cell-level (backend×class×load, n≥3, median within ±10%): **1.00** over 28 cells. 78 conn-rate phase-UEs (tcp_shortconn) are checked by connection completion, not URR.

## 5. Load overlap between classes (volume cannot separate them)

Overlap coefficient (Σ min of the two normalised histograms; 1 = identical, 0 = disjoint):

| stratum | n ben | n mal | RAN UL thp | URR UL pps | pkt mean B | URR DL |
|---|---:|---:|---:|---:|---:|---:|
| all | 32779 | 29333 | 0.97 | 0.89 | 0.73 | 0.81 |
| 0.2 Mbit/s | 2771 | 2771 | 0.76 | 0.66 | 0.17 | 0.44 |
| 0.4 Mbit/s | 10891 | 9649 | 0.91 | 0.81 | 0.69 | 0.75 |
| 0.6 Mbit/s | 2701 | 2701 | 0.31 | 0.30 | 0.07 | 0.20 |
| 0.8 Mbit/s | 9860 | 8086 | 0.89 | 0.90 | 0.92 | 0.71 |
| 1.2 Mbit/s | 6556 | 6126 | 0.90 | 0.95 | 0.89 | 0.73 |

Coarsened exact matching on UL bytes/UL pps/DL bytes (5 bins each): **90% of MALICIOUS** and **93% of BENIGN** rows fall in a cell containing BOTH classes (common support). Cell-distribution L1 imbalance 1.28 → 1.22 after restricting to common support. High common support ⇒ a volume-matched control exists for the thesis.

## 6. Packet-size overlap per attack ↔ counterpart pair

Each attack phase pairs the attacker with its load-matched benign counterpart in the same cell. Overlap of `prof_ul_mean_bytes` (mean packet size) between the two — a shared size prior should keep UDP pairs high; protocol-fixed pairs (SYN vs short-conn) differ by design (a *valid* distinguishing signal, not a confound).

| meta_pair | mixed phases | median overlap | p10 | p90 |
|---|---:|---:|---:|---:|
| dns_flood~dns_heavy | 78 | 0.04 | 0.00 | 0.10 |
| fanout_udp~fanout_benign | 42 | 0.87 | 0.76 | 0.95 |
| icmp_flood~icmp_ping | 42 | 1.00 | 1.00 | 1.00 |
| mimicry_udp~udp_nofeedback | 42 | 0.84 | 0.74 | 0.93 |
| pulsing_udp~onoff_pareto | 42 | 0.84 | 0.71 | 0.94 |
| syn_flood~tcp_shortconn | 78 | 0.06 | 0.03 | 0.11 |
| udp_flood~udp_bidir | 114 | 0.96 | 0.77 | 1.00 |

## 7. Adversarial validation (nuisance fingerprinting; chance AUC = 0.5)

Grouped by `meta_run_id`. AUC predicting each nuisance *within* a class, per telemetry domain:

| class | nuisance | #vals | RAN | URR | prof |
|---|---|---:|---:|---:|---:|
| BENIGN | ue | 2 | 0.55 | 0.53 | 0.49 |
| BENIGN | backend | 5 | 0.91 | 0.92 | 0.97 |
| BENIGN | victim_mode | 2 | 0.51 | 0.44 | 0.46 |
| MALICIOUS | ue | 2 | 0.51 | 0.50 | 0.48 |
| MALICIOUS | backend | 4 | 0.91 | 0.89 | 0.91 |
| MALICIOUS | victim_mode | 2 | 0.96 | 0.94 | 0.95 |

High AUC ⇒ the domain fingerprints that nuisance *within a class*. This is a finding to report, not a leak by itself: a nuisance only becomes a shortcut if it is also correlated with the label (§3 χ² / §8). `ue | RAN` high would mean RFsim fingerprints the UE. `victim_mode | MALICIOUS` is expected to be high: the responsive victim's ICMP/RST replies are DL the attacker receives (C2 is solved by making victim_mode ⟂ label, not by removing the reply). `backend` within a class reflects real per-tool traffic shape.

## 8. Nuisance-only baseline (predict label from meta_ only; target AUC ≈ 0.5)

- innocent nuisances (ue + timing + load + victim_mode + congestion): **AUC 0.49**
- + backend: **AUC 0.74** (benign-only hard-negative backends legitimately carry label signal — expected > 0.5)

The innocent-nuisance AUC is the headline confound metric (§7.3 target ≤ 0.6).

## 9. Per meta_pair (section-6.3 cell)

| meta_pair | rows | MAL/BEN | achieved_ok | per-cell size overlap |
|---|---:|---:|---:|---:|
| benign_benign | 6838 | 0/6838 | 0.96 | — |
| both_attack | 3392 | 3392/0 | 0.97 | — |
| dns_flood~dns_heavy | 8750 | 4375/4375 | 0.99 | 0.04 |
| fanout_udp~fanout_benign | 4930 | 2465/2465 | 1.00 | 0.87 |
| icmp_flood~icmp_ping | 5284 | 2642/2642 | 0.57 | 1.00 |
| mimicry_udp~udp_nofeedback | 5072 | 2536/2536 | 0.82 | 0.84 |
| pulsing_udp~onoff_pareto | 4790 | 2395/2395 | 0.83 | 0.84 |
| syn_flood~tcp_shortconn | 9280 | 4640/4640 | 0.87 | 0.06 |
| udp_flood~udp_bidir | 13776 | 6888/6888 | 0.99 | 0.96 |

## 10. Design-cell coverage (valid phases per section-6.3 pair × UE)

Valid = `meta_run_ok=1` and not achieved-failed. Target ≥ 3 per cell for BOTH the attack and its counterpart on EACH UE.

| meta_pair | ue | MALICIOUS | BENIGN |
|---|---|---:|---:|
| dns_flood~dns_heavy | ue1 | 39 | 39 |
| dns_flood~dns_heavy | ue2 | 38 | 39 |
| fanout_udp~fanout_benign | ue1 | 21 | 21 |
| fanout_udp~fanout_benign | ue2 | 21 | 21 |
| icmp_flood~icmp_ping | ue1 | 12 | 12 |
| icmp_flood~icmp_ping | ue2 | 12 | 12 |
| mimicry_udp~udp_nofeedback | ue1 | 21 | 16 |
| mimicry_udp~udp_nofeedback | ue2 | 19 | 13 |
| pulsing_udp~onoff_pareto | ue1 | 20 | 18 |
| pulsing_udp~onoff_pareto | ue2 | 14 | 18 |
| syn_flood~tcp_shortconn | ue1 | 33 | 39 |
| syn_flood~tcp_shortconn | ue2 | 35 | 39 |
| udp_flood~udp_bidir | ue1 | 57 | 56 |
| udp_flood~udp_bidir | ue2 | 56 | 56 |

Cells below 3: **none**

## 10b. Run integrity (phase duration ±20%, stream gap ≤ 3 s, no host suspend)

| run | ok | max dur dev | max stream gap s | reasons |
|---|---|---:|---:|---|
| rep-01 | ok | 0.001 | 2.27 |  |
| rep-02 | ok | 0.001 | 2.31 |  |
| rep-03 | ok | 0.003 | 2.29 |  |
| rep-04 | ok | 0.004 | 2.48 |  |
| rep-05 | ok | 0.003 | 2.11 |  |
| rep-06 | ok | 0.004 | 2.27 |  |
| rep-07 | ok | 0.001 | 2.05 |  |
| rep-08 | ok | 0.001 | 2.43 |  |
| rep-09 | ok | 0.002 | 2.05 |  |
| rep-10 | ok | 0.001 | 2.25 |  |
| rep-11 | ok | 0.001 | 2.47 |  |
| rep-12 | ok | 0.005 | 2.26 |  |
| rep-13 | ok | 0.001 | 2.12 |  |
| rep-14 | ok | 0.001 | 2.2 |  |
| rep-15 | ok | 0.001 | 2.38 |  |
| rep-16 | ok | 0.001 | 2.15 |  |
| rep-17 | ok | 0.001 | 2.28 |  |
| rep-18 | ok | 0.001 | 2.04 |  |
| rep-19 | ok | 0.001 | 2.29 |  |
| rep-20 | ok | 0.001 | 2.43 |  |
| rep-21 | ok | 0.001 | 2.32 |  |
| rep-22 | ok | 0.001 | 2.43 |  |
| rep-23 | ok | 0.001 | 2.25 |  |
| rep-24 | ok | 0.005 | 2.26 |  |
| rep-25 | ok | 0.001 | 2.4 |  |
| rep-26 | ok | 0.001 | 2.02 |  |
| rep-27 | ok | 0.005 | 2.4 |  |
| rep-28 | ok | 0.003 | 2.25 |  |
| rep-29 | ok | 0.005 | 2.48 |  |
| rep-30 | ok | 0.001 | 2.26 |  |
| rep-31 | ok | 0.001 | 2.26 |  |
| rep-32 | ok | 0.001 | 2.36 |  |
| rep-33 | ok | 0.001 | 2.25 |  |
| rep-34 | ok | 0.001 | 2.73 |  |
| rep-35 | ok | 0.002 | 2.25 |  |
| rep-36 | ok | 0.001 | 2.23 |  |
| rep-37 | ok | 0.001 | 2.21 |  |
| rep-38 | ok | 0.006 | 2.48 |  |
| rep-39 | ok | 0.007 | 2.47 |  |
| rep-40 | ok | 0.001 | 2.26 |  |
| rep-41 | ok | 0.001 | 2.51 |  |
| rep-42 | ok | 0.004 | 2.24 |  |
| rep-43 | ok | 0.001 | 2.36 |  |
| rep-44 | ok | 0.003 | 2.02 |  |
| rep-45 | ok | 0.001 | 2.31 |  |
| rep-46 | ok | 0.006 | 2.26 |  |
| rep-47 | ok | 0.001 | 2.25 |  |
| rep-48 | ok | 0.001 | 2.03 |  |
| rep-49 | ok | 0.007 | 2.37 |  |
| rep-50 | ok | 0.001 | 2.27 |  |
| rep-51 | ok | 0.001 | 2.34 |  |
| rep-52 | ok | 0.001 | 2.25 |  |
| rep-53 | ok | 0.006 | 2.06 |  |
| rep-54 | ok | 0.003 | 2.4 |  |
| rep-55 | ok | 0.001 | 2.36 |  |
| rep-56 | ok | 0.001 | 2.25 |  |
| rep-57 | ok | 0.001 | 2.29 |  |
| rep-58 | ok | 0.001 | 2.25 |  |
| rep-59 | ok | 0.001 | 2.43 |  |
| rep-60 | ok | 0.001 | 2.45 |  |
| rep-61 | ok | 0.001 | 2.25 |  |
| rep-62 | ok | 0.003 | 2.2 |  |
| rep-63 | ok | 0.001 | 2.19 |  |
| rep-64 | ok | 0.002 | 2.45 |  |
| rep-65 | ok | 0.001 | 2.23 |  |
| rep-66 | ok | 0.001 | 2.27 |  |
| rep-67 | ok | 0.004 | 2.15 |  |
| rep-68 | ok | 0.001 | 2.26 |  |
| rep-69 | ok | 0.001 | 2.27 |  |
| rep-70 | ok | 0.003 | 2.28 |  |
| rep-71 | ok | 0.001 | 2.33 |  |
| rep-72 | ok | 0.003 | 2.25 |  |
| rep-73 | ok | 0.004 | 2.24 |  |
| rep-74 | ok | 0.003 | 2.26 |  |
| rep-75 | ok | 0.001 | 2.06 |  |
| rep-76 | ok | 0.001 | 2.43 |  |
| rep-77 | ok | 0.001 | 2.49 |  |
| rep-78 | ok | 0.001 | 2.26 |  |
| rep-79 | ok | 0.001 | 2.05 |  |
| rep-80 | ok | 0.004 | 2.37 |  |
| rep-81 | ok | 0.001 | 2.38 |  |
| rep-82 | ok | 0.001 | 2.14 |  |
| rep-83 | ok | 0.001 | 2.23 |  |
| rep-84 | ok | 0.004 | 2.08 |  |
| rep-85 | ok | 0.001 | 2.25 |  |
| rep-86 | ok | 0.004 | 2.15 |  |
| rep-87 | ok | 0.003 | 2.25 |  |
| rep-88 | ok | 0.003 | 2.27 |  |

## 11. Acceptance (plan §7.3)

| criterion | result | value |
|---|---|---|
| P(malicious | UE) ∈ [0.45, 0.55] (excl. IDLE) | PASS | ue1 0.483, ue2 0.461 |
| P(malicious | dual-use backend) ∈ [0.4, 0.6] | PASS | hping 0.526, iperf 0.500, pacer 0.540 |
| ≥ 90% phases achieved_ok | PASS | phase 0.912; cell-level 1.0 |
| 0 causality violations | PASS | 0 violations |
| all unit tests pass | PASS | unit_tests.txt |
| nuisance-only baseline AUC ≤ 0.6 | PASS | AUC 0.487 |
| each section-6.3 cell ≥ 3 valid phases per UE | PASS | 0 cells short |
| re-run from manifest + seed reproduces target schedule | PASS | check_reproducible.py |
| every selected run passes integrity guards | PASS | 0 bad runs |
