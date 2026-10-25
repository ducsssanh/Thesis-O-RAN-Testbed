# v5 live — extra analyses (main campaign, 224 valid runs)

Unit = (run, UE, phase). Brackets: 95 % bootstrap CI over runs. Levels = enforced by the xApp (L1 = quarantine slice / UPF monitor, L3 = UPF block).

## A. icmp control pair (icmp_flood vs icmp_ping, honest telemetry)

| config | runs | flood L1 | flood L3 | ping L1 | ping L3 |
|---|---:|---|---|---|---|
| rules-v1 | 2 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| ran-only | 6 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| core-only | 6 | 1.00 [1.00, 1.00] | 0.75 [0.42, 1.00] | 0.92 [0.75, 1.00] | 0.83 [0.67, 1.00] |
| xd-naive | 6 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.92 [0.75, 1.00] |
| xd-trust-v1 | 6 | 1.00 [1.00, 1.00] | 0.58 [0.33, 0.83] | 1.00 [1.00, 1.00] | 0.58 [0.25, 0.92] |
| xd-trust-v2 | 6 | 1.00 [1.00, 1.00] | 0.58 [0.25, 0.92] | 1.00 [1.00, 1.00] | 0.50 [0.17, 0.83] |

## B. core_outage: L1 vs L3, outage phases vs core-present phases (attacker / benign)

Outage phases = 0 and 3 (A1-EI adapter scaled to 0: no URR, no profiler). Trust-weighted v1/v2 need core evidence for L3 by design (L3 = L1 held ≥ 10 s AND core in 3 of 5 s), so L3 ≈ 0 in outage phases is the design, not a miss; L1 there comes from the RAN fallback (ct = 0 → z_ran).

| config | outage: attack L1 | outage: attack L3 | outage: benign L3 | core present: attack L1 | core present: attack L3 | core present: benign L3 |
|---|---|---|---|---|---|---|
| rules-v1 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| ran-only | 0.75 [0.58, 0.92] | 0.58 [0.17, 0.92] | 0.08 [0.00, 0.25] | 0.75 [0.42, 1.00] | 0.67 [0.33, 0.92] | 0.08 [0.00, 0.25] |
| core-only | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.83 [0.67, 1.00] | 0.50 [0.25, 0.75] | 0.08 [0.00, 0.25] |
| xd-naive | 0.42 [0.25, 0.50] | 0.42 [0.25, 0.50] | 0.25 [0.08, 0.42] | 0.92 [0.75, 1.00] | 0.67 [0.50, 0.83] | 0.00 [0.00, 0.00] |
| xd-trust-v1 | 0.75 [0.58, 0.92] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.92 [0.75, 1.00] | 0.50 [0.25, 0.75] | 0.00 [0.00, 0.00] |
| xd-trust-v2 | 0.75 [0.58, 0.92] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.92 [0.75, 1.00] | 0.67 [0.42, 0.92] | 0.00 [0.00, 0.00] |

## C. kpm_hide: time to block and attacker bytes at the DN

t→L3 = phase start → UPF block (median / p90 over blocked phases). Bytes = attacker UL IP payload at the DN in the phase window; 'after/before' compares the mean rate after the block with the rate before it.

| scenario | config | attack phases | blocked | t→L3 med / p90 (s) | rate before block (kbit/s, med) | rate after block (kbit/s, med) | after/before | share of phase bytes after block |
|---|---|---:|---|---|---:|---:|---:|---:|
| kpm_hide_x0.1 | rules-v1 | 8 | 0.00 [0.00, 0.00] | – | – | – | – | – |
| kpm_hide_x0.1 | ran-only | 24 | 0.21 [0.04, 0.38] | 0.7 / 0.9 | 0 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | core-only | 24 | 0.54 [0.42, 0.67] | 24.4 / 50.3 | 410 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | xd-naive | 24 | 0.62 [0.42, 0.83] | 22.3 / 39.1 | 923 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | xd-trust-v1 | 24 | 0.58 [0.42, 0.79] | 23.8 / 45.2 | 458 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | xd-trust-v2 | 24 | 1.00 [1.00, 1.00] | 24.1 / 30.8 | 526 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | rules-v1 | 8 | 0.00 [0.00, 0.00] | – | – | – | – | – |
| kpm_hide_x0.33 | ran-only | 24 | 0.42 [0.12, 0.71] | 27.1 / 54.5 | 712 | 340 | 0.384 | 0.125 |
| kpm_hide_x0.33 | core-only | 24 | 0.75 [0.62, 0.88] | 25.0 / 45.1 | 406 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | xd-naive | 24 | 0.88 [0.71, 1.00] | 22.0 / 29.8 | 541 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | xd-trust-v1 | 24 | 0.62 [0.46, 0.79] | 23.9 / 56.1 | 416 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | xd-trust-v2 | 24 | 1.00 [1.00, 1.00] | 23.3 / 28.8 | 499 | 0 | 0.000 | 0.000 |

## D. Sensitivity: without the flagged runs [40, 91, 99, 110, 173, 212] (classifier fallback inside a phase)

Largest absolute change of any cell metric: **0.222**.

| scenario | config | runs | all runs → without flagged |
|---|---|---|---|
| core_outage | core-only | 6 → 5 | attack_L1 0.417 → 0.450, attack_L3 0.250 → 0.300, benign_L3 0.042 → 0.000, attack_delivered_frac 0.999 → 0.998 |
| honest | ran-only | 6 → 5 | attack_L1 0.958 → 0.950, attack_L3 0.750 → 0.700, benign_L3 0.333 → 0.200, attack_delivered_frac 0.427 → 0.401 |
| honest | xd-trust-v1 | 6 → 4 | attack_L1 0.958 → 0.938, attack_L3 0.458 → 0.500, benign_L3 0.125 → 0.125, attack_delivered_frac 0.830 → 0.635 |
| honest | xd-trust-v2 | 6 → 4 | attack_L1 0.917 → 0.875, attack_L3 0.667 → 0.625, benign_L3 0.083 → 0.062, attack_delivered_frac 0.746 → 0.968 |

## E. Failed attempts per cell (testbed failures, all re-run; valid runs 6 per cell, rules-v1 2)

| scenario | rules-v1 | ran-only | core-only | xd-naive | xd-trust-v1 | xd-trust-v2 |
|---|---:|---:|---:|---:|---:|---:|
| honest | 1/3 | 3/9 | 0/6 | 1/7 | 1/7 | 0/6 |
| kpm_hide_x0.1 | 1/3 | 0/6 | 0/6 | 1/7 | 1/7 | 1/7 |
| kpm_hide_x0.33 | 0/2 | 0/6 | 1/7 | 1/7 | 1/7 | 1/7 |
| kpm_frame_x2 | 0/2 | 1/7 | 2/8 | 1/7 | 1/7 | 1/7 |
| kpm_frame_x5 | 0/2 | 2/8 | 0/6 | 1/7 | 0/6 | 1/7 |
| core_outage | 1/3 | 0/6 | 0/6 | 1/7 | 0/6 | 0/6 |
| icmp_control | 0/2 | 1/7 | 0/6 | 1/7 | 1/7 | 1/7 |
| **all** | 3 | 7 | 3 | 7 | 5 | 5 |

(failed / attempts)

## F. Pre-registered hypotheses (read off the cells; not targets)

- **H1** trust-v2 ≥ naive on kpm_hide, kpm_frame, core_outage — attack L3 (higher better) / benign L3 (lower better):
  - kpm_hide_x0.1 attack_L3: trust-v2 1.000 vs naive 0.625
  - kpm_hide_x0.1 benign_L3: trust-v2 0.042 vs naive 0.167
  - kpm_hide_x0.33 attack_L3: trust-v2 1.000 vs naive 0.875
  - kpm_hide_x0.33 benign_L3: trust-v2 0.125 vs naive 0.208
  - kpm_frame_x2 attack_L3: trust-v2 0.292 vs naive 0.708
  - kpm_frame_x2 benign_L3: trust-v2 0.000 vs naive 0.500
  - kpm_frame_x5 attack_L3: trust-v2 0.417 vs naive 0.792
  - kpm_frame_x5 benign_L3: trust-v2 0.042 vs naive 0.583
  - core_outage attack_L3: trust-v2 0.333 vs naive 0.542
  - core_outage benign_L3: trust-v2 0.000 vs naive 0.125
- **H2** ran-only ≈ 0 detection on kpm_hide: attack L1 x0.1 0.250, x0.33 0.500
- **H3** framed benign wrongly blocked ≤ ~2 % under trust-v2: x2 0.000, x5 0.042
- **H4** integrity false alarms ≈ 0 on untampered phases (trust-v2): core_outage 0.0, honest 0.021, icmp_control 0.0, kpm_frame_x2 0.0, kpm_frame_x5 0.0, kpm_hide_x0.1 0.0, kpm_hide_x0.33 0.0

