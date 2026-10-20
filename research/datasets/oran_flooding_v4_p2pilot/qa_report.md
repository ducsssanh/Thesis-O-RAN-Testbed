# v4 QA report — `research/datasets/oran_flooding_v4_p2pilot`

Rows: 518 · IDLE 218 · MALICIOUS 150 · BENIGN 150

## 1. Causality audit (independent of the builder)

| stream | rows checked | violations (arrival_ts > t) |
|---|---:|---:|
| kpm | 518 | **0** |
| urr | 516 | **0** |
| prof | 516 | **0** |

For comparison, the v3-style xApp join (`defense/features.jsonl`) of the same run: 520 rows, **3 (0.6%) used a future (+1 s) URR sample and 0 (0.0%) a future profiler sample** — the C5 leak the v4 build removes.

## 2. Data age (s) at the row's second

| stream | median | p90 | max | present % |
|---|---:|---:|---:|---:|
| kpm | 0.01 | 0.01 | 1.01 | 100.0 |
| urr | 2.28 | 3.31 | 4.67 | 95.9 |
| prof | 2.41 | 2.41 | 3.41 | 99.6 |

Presence by label (URR / profiler):

| label | URR % | prof % |
|---|---:|---:|
| BENIGN | 95.3 | 100.0 |
| IDLE | 94.5 | 99.1 |
| MALICIOUS | 98.7 | 100.0 |

## 3. Design balance (excl. IDLE)

```
label    BENIGN  MALICIOUS
meta_ue                   
ue1          60         90
ue2          90         60
```

P(malicious | UE): ue1 0.60, ue2 0.40

**UE-balance not yet met** — ['ue1', 'ue2'] outside [0.45, 0.55]: label still tracks UE. Full per-phase role-swap balance is the Phase-3 campaign-design job.

P(malicious | backend): dns_client 0.00, hping 0.67, iperf 0.50, pacer 0.67, tcp_shortconn 0.00  — **dual-use outside [0.4, 0.6]: ['hping', 'pacer']** (benign-only backends excluded)

P(malicious | victim mode): responsive 0.50, silent 0.50  — dual-use in band

P(malicious | load level): 0.2 0.33, 0.4 1.00, 0.8 0.50  (load distribution should match across classes)

## 4. Achieved vs target (URR ground truth, ±10%, per native unit)

| phase | ue | backend | unit | achieved_ok |
|---|---|---|---|---|
| p-dns | ue1 | pacer | bytes | yes |
| p-dns | ue2 | dns_client | pps | yes |
| p-fgn | ue1 | pacer | bytes | yes |
| p-fgn | ue2 | pacer | bytes | **no** |
| p-hping | ue1 | hping | bytes | **no** |
| p-hping | ue2 | hping | bytes | yes |
| p-iperf | ue1 | iperf | bytes | **no** |
| p-iperf | ue2 | iperf | bytes | yes |
| p-syn | ue2 | hping | pps | **no** |

achieved_ok: 5/9 phase-UE pairs (target ≥ 90%). conn-rate backends (tcp_shortconn) are checked by connection completion, not URR.

## 5. Load overlap between classes (volume cannot separate them)

Overlap coefficient (Σ min of the two normalised histograms; 1 = identical, 0 = disjoint):

| stratum | n ben | n mal | RAN UL thp | URR UL pps | pkt mean B | URR DL |
|---|---:|---:|---:|---:|---:|---:|
| all | 150 | 150 | 0.70 | 0.49 | 0.37 | 0.57 |
| 0.2 Mbit/s | 60 | 30 | 0.10 | 0.35 | 0.22 | 0.27 |
| 0.4 Mbit/s | 0 | 30 | — | — | — | — |
| 0.8 Mbit/s | 90 | 90 | 0.74 | 0.41 | 0.13 | 0.08 |

Coarsened exact matching on UL bytes/UL pps/DL bytes (5 bins each): **39% of MALICIOUS** and **30% of BENIGN** rows fall in a cell containing BOTH classes (common support). Cell-distribution L1 imbalance 1.47 → 0.46 after restricting to common support. High common support ⇒ a volume-matched control exists for the thesis.

## 6. Packet-size overlap per attack ↔ counterpart pair

Each attack phase pairs the attacker with its load-matched benign counterpart in the same cell. Overlap of `prof_ul_mean_bytes` (mean packet size) between the two — a shared size prior should keep UDP pairs high; protocol-fixed pairs (SYN vs short-conn) differ by design (a *valid* distinguishing signal, not a confound).

| phase | attacker (backend/family) | counterpart (backend/class) | size overlap |
|---|---|---|---:|
| p-dns | pacer/pacer/pulsing | dns_client/poisson | 0.13 |
| p-fgn | pacer/pacer/fgn | pacer/fgn | 0.13 |
| p-hping | hping/hping/mmpp2 | hping/cbr | 0.13 |
| p-iperf | iperf/iperf/onoff_pareto | iperf/cbr | 0.13 |
| p-syn | hping/hping/hawkes | tcp_shortconn/hawkes | 0.27 |

## 7. Adversarial validation (nuisance fingerprinting; chance AUC = 0.5)

Grouped by `meta_phase` (1 run → phase groups; campaign will group by run_id). AUC predicting each nuisance *within* a class, per telemetry domain:

| class | nuisance | #vals | RAN | URR | prof |
|---|---|---:|---:|---:|---:|
| BENIGN | ue | 2 | 0.72 | 0.73 | 0.65 |
| BENIGN | backend | 5 | — | — | — |
| BENIGN | victim_mode | 2 | 0.72 | 0.73 | 0.65 |
| MALICIOUS | ue | 2 | 0.98 | 0.99 | 0.98 |
| MALICIOUS | backend | 3 | nan | nan | nan |
| MALICIOUS | victim_mode | 2 | 0.98 | 0.99 | 0.98 |

High AUC ⇒ the domain fingerprints that nuisance. In this 1-run pilot each backend occupies a single phase, so `backend` ≈ phase and its AUC is inflated by that confound; the campaign (many phases per backend, grouped by run_id) is what makes this diagnostic meaningful. `ue | RAN` high would mean RFsim fingerprints the UE.

## 8. Nuisance-only baseline (predict label from meta_ only; target AUC ≈ 0.5)

- innocent nuisances (ue + timing + load + victim_mode): **AUC 0.62**
- + backend: **AUC 0.62** (benign-only hard-negative backends legitimately carry label signal — expected > 0.5)

The innocent-nuisance AUC is the headline confound metric; the Phase-3 campaign balance targets drive it to ≈0.5 (the pilot's residual comes from the 0.60/0.40 UE imbalance).
