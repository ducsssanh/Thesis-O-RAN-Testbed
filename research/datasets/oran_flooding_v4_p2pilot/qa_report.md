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
