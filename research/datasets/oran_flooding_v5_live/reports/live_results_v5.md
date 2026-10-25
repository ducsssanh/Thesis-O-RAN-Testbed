# Cross-domain defence live (v5, stage B) — final results

Main campaign 2026-10-24 13:19 → 2026-10-25 15:55: **224/224 runs valid** (42 cells: 6 reps, rules-v1 2), 30 failed attempts (testbed) re-run. Sidecar latency p50 19.54 / p99 47.7 ms, 34 classifier fallbacks in 224 valid runs. Pilot excluded. Unit = (run, UE, phase); brackets = 95 % bootstrap CI over runs.

**Primary = clean units.** 63 of 1536 phases (4.1 %; 38 runs; 7 icmp phases) started with the UE already at L3: the gap reset of the xApp level raced with the sidecar's last L3 answer, which re-set L3 with a 120 s expiry, so the block carried into the next phase. These units are dropped (their outcome is not their phase's); all-units values in parentheses. Carried phases per config (incl. icmp): rules-v1 0, ran-only 43, core-only 8, xd-naive 16, xd-trust-v1 3, xd-trust-v2 0 (see E).

## 1. Per scenario × configuration (clean units; all units in parentheses for L3)

### honest

| config | phases | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med (s) | t→L3 med (s) | integrity on tampered | integrity false | attack delivered | benign delivered |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| rules-v1 | 16 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 | 0.00 [0.00, 0.00] | – | – | – | – | – | 1.00 | 1.00 |
| ran-only | 36 | 0.94 [0.81, 1.00] | 0.65 [0.47, 0.87] (0.75) | 0.37 | 0.16 [0.00, 0.43] (0.33) | – | 14.7 | 22.5 | – | 0.00 | 0.41 | 1.00 |
| core-only | 47 | 0.75 [0.62, 0.88] | 0.42 [0.21, 0.58] | 0.13 | 0.00 [0.00, 0.00] (0.04) | – | 15.0 | 22.0 | – | 0.00 | 0.99 | 1.00 |
| xd-naive | 48 | 0.79 [0.58, 0.96] | 0.67 [0.54, 0.83] | 0.12 | 0.00 [0.00, 0.00] | – | 13.7 | 22.5 | – | 0.00 | 0.56 | 1.00 |
| xd-trust-v1 | 46 | 0.96 [0.88, 1.00] | 0.46 [0.38, 0.50] | 0.27 | 0.04 [0.00, 0.14] (0.12) | – | 13.4 | 22.4 | – | 0.00 | 0.83 | 1.00 |
| xd-trust-v2 | 48 | 0.92 [0.83, 1.00] | 0.67 [0.46, 0.88] | 0.29 | 0.08 [0.00, 0.17] | – | 16.1 | 31.7 | – | 0.02 | 0.75 | 1.00 |

### kpm_hide_x0.1

| config | phases | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med (s) | t→L3 med (s) | integrity on tampered | integrity false | attack delivered | benign delivered |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| rules-v1 | 16 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 | 0.00 [0.00, 0.00] | – | – | – | – | – | 1.00 | 1.00 |
| ran-only | 43 | 0.05 [0.00, 0.19] | 0.00 [0.00, 0.00] (0.21) | 0.67 | 0.58 [0.42, 0.79] | – | 13.7 | – | 0.00 | 0.00 | 1.00 | 0.62 |
| core-only | 48 | 0.75 [0.58, 0.92] | 0.54 [0.42, 0.67] | 0.12 | 0.00 [0.00, 0.00] | – | 15.2 | 24.4 | 0.00 | 0.00 | 0.85 | 1.00 |
| xd-naive | 48 | 0.83 [0.67, 0.96] | 0.62 [0.42, 0.83] | 0.25 | 0.17 [0.00, 0.42] | – | 14.7 | 22.3 | 0.00 | 0.00 | 0.46 | 1.00 |
| xd-trust-v1 | 48 | 0.79 [0.67, 0.92] | 0.58 [0.42, 0.79] | 0.04 | 0.00 [0.00, 0.00] | – | 15.2 | 23.8 | 1.00 | 0.00 | 0.73 | 1.00 |
| xd-trust-v2 | 48 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.25 | 0.04 [0.00, 0.12] | – | 14.9 | 24.1 | 1.00 | 0.00 | 0.35 | 1.00 |

### kpm_hide_x0.33

| config | phases | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med (s) | t→L3 med (s) | integrity on tampered | integrity false | attack delivered | benign delivered |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| rules-v1 | 16 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 | 0.00 [0.00, 0.00] | – | – | – | – | – | 1.00 | 1.00 |
| ran-only | 41 | 0.43 [0.17, 0.78] | 0.33 [0.12, 0.61] (0.42) | 0.60 | 0.40 [0.27, 0.62] (0.50) | – | 16.2 | 41.6 | 0.00 | 0.00 | 1.00 | 0.97 |
| core-only | 46 | 0.83 [0.73, 0.92] | 0.74 [0.62, 0.87] (0.75) | 0.13 | 0.00 [0.00, 0.00] (0.04) | – | 15.5 | 25.2 | 0.00 | 0.00 | 0.48 | 1.00 |
| xd-naive | 45 | 0.91 [0.83, 1.00] | 0.87 [0.71, 1.00] (0.88) | 0.14 | 0.14 [0.00, 0.39] (0.21) | – | 13.0 | 22.1 | 0.00 | 0.00 | 0.35 | 1.00 |
| xd-trust-v1 | 48 | 0.88 [0.79, 0.96] | 0.62 [0.46, 0.79] | 0.17 | 0.00 [0.00, 0.00] | – | 13.4 | 23.9 | 1.00 | 0.00 | 0.83 | 1.00 |
| xd-trust-v2 | 48 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.29 | 0.12 [0.00, 0.29] | – | 13.6 | 23.3 | 1.00 | 0.00 | 0.35 | 1.00 |

### kpm_frame_x2

| config | phases | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med (s) | t→L3 med (s) | integrity on tampered | integrity false | attack delivered | benign delivered |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| rules-v1 | 16 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.50 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | – | – | – | – | 1.00 | 1.00 |
| ran-only | 37 | 0.87 [0.71, 1.00] | 0.33 [0.11, 0.70] (0.58) | 0.73 | 0.64 [0.33, 0.90] (0.67) | 0.64 [0.33, 0.90] (0.67) | 17.5 | 36.1 | 0.00 | 0.00 | 1.00 | 0.85 |
| core-only | 48 | 0.75 [0.62, 0.88] | 0.50 [0.38, 0.58] | 0.08 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 16.1 | 23.4 | 0.00 | 0.00 | 0.86 | 1.00 |
| xd-naive | 43 | 0.86 [0.67, 1.00] | 0.67 [0.43, 0.91] (0.71) | 0.50 | 0.46 [0.17, 0.80] (0.50) | 0.46 [0.17, 0.80] (0.50) | 13.0 | 26.0 | 0.00 | 0.00 | 0.77 | 0.99 |
| xd-trust-v1 | 48 | 0.79 [0.62, 0.96] | 0.29 [0.08, 0.50] | 0.38 | 0.08 [0.00, 0.25] | 0.08 [0.00, 0.25] | 15.6 | 25.6 | 0.75 | 0.04 | 0.99 | 1.00 |
| xd-trust-v2 | 48 | 0.71 [0.58, 0.83] | 0.29 [0.25, 0.38] | 0.46 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 15.8 | 31.1 | 0.75 | 0.00 | 1.00 | 1.00 |

### kpm_frame_x5

| config | phases | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med (s) | t→L3 med (s) | integrity on tampered | integrity false | attack delivered | benign delivered |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| rules-v1 | 16 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.75 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | – | – | – | – | 1.00 | 1.00 |
| ran-only | 43 | 0.68 [0.50, 0.90] | 0.27 [0.09, 0.46] (0.33) | 0.91 | 0.62 [0.39, 0.90] (0.67) | 0.62 [0.39, 0.90] (0.67) | 43.7 | 55.2 | 0.00 | 0.00 | 1.00 | 0.50 |
| core-only | 48 | 0.88 [0.79, 0.96] | 0.67 [0.54, 0.83] | 0.17 | 0.04 [0.00, 0.12] | 0.04 [0.00, 0.12] | 16.1 | 25.1 | 0.00 | 0.00 | 0.62 | 1.00 |
| xd-naive | 42 | 0.79 [0.54, 1.00] | 0.79 [0.54, 1.00] | 0.67 | 0.44 [0.24, 0.67] (0.58) | 0.44 [0.24, 0.67] (0.58) | 13.2 | 30.0 | 0.00 | 0.00 | 0.65 | 0.99 |
| xd-trust-v1 | 47 | 0.61 [0.50, 0.71] | 0.48 [0.32, 0.65] (0.50) | 0.54 | 0.08 [0.00, 0.25] | 0.08 [0.00, 0.25] | 14.5 | 24.2 | 1.00 | 0.00 | 0.97 | 1.00 |
| xd-trust-v2 | 48 | 0.75 [0.62, 0.88] | 0.42 [0.33, 0.50] | 0.54 | 0.04 [0.00, 0.12] | 0.04 [0.00, 0.12] | 14.6 | 22.0 | 1.00 | 0.00 | 0.99 | 1.00 |

### core_outage

| config | phases | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med (s) | t→L3 med (s) | integrity on tampered | integrity false | attack delivered | benign delivered |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| rules-v1 | 16 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 | 0.00 [0.00, 0.00] | – | – | – | – | – | 1.00 | 1.00 |
| ran-only | 45 | 0.74 [0.50, 0.96] | 0.61 [0.38, 0.86] (0.62) | 0.18 | 0.00 [0.00, 0.00] (0.08) | – | 14.9 | 23.2 | – | 0.00 | 0.85 | 1.00 |
| core-only | 48 | 0.42 [0.33, 0.50] | 0.25 [0.12, 0.38] | 0.12 | 0.04 [0.00, 0.12] | – | 15.1 | 23.1 | – | 0.00 | 1.00 | 1.00 |
| xd-naive | 48 | 0.67 [0.58, 0.75] | 0.54 [0.42, 0.67] | 0.21 | 0.12 [0.04, 0.21] | – | 14.1 | 22.8 | – | 0.00 | 0.93 | 1.00 |
| xd-trust-v1 | 48 | 0.83 [0.67, 0.96] | 0.25 [0.12, 0.38] | 0.12 | 0.00 [0.00, 0.00] | – | 13.6 | 31.5 | – | 0.00 | 1.00 | 1.00 |
| xd-trust-v2 | 48 | 0.83 [0.67, 0.96] | 0.33 [0.21, 0.46] | 0.29 | 0.00 [0.00, 0.00] | – | 13.6 | 23.8 | – | 0.00 | 0.98 | 1.00 |

## A. icmp control pair (icmp_flood vs icmp_ping, honest telemetry; clean units)

| config | runs | flood L1 | flood L3 | ping L1 | ping L3 (all) |
|---|---:|---|---|---|---|
| rules-v1 | 2 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] (0.00) |
| ran-only | 6 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] (1.00) |
| core-only | 6 | 1.00 [1.00, 1.00] | 0.67 [0.25, 1.00] | 0.90 [0.73, 1.00] | 0.80 [0.50, 1.00] (0.83) |
| xd-naive | 6 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.92 [0.75, 1.00] (0.92) |
| xd-trust-v1 | 6 | 1.00 [1.00, 1.00] | 0.58 [0.33, 0.83] | 1.00 [1.00, 1.00] | 0.58 [0.25, 0.92] (0.58) |
| xd-trust-v2 | 6 | 1.00 [1.00, 1.00] | 0.58 [0.25, 0.92] | 1.00 [1.00, 1.00] | 0.50 [0.17, 0.83] (0.50) |

## B. core_outage: L1 vs L3, outage phases vs core-present phases

Outage phases = 0 and 3 (A1-EI adapter scaled to 0: no URR, no profiler; the UPF Security API stays up). **By design** the trust-weighted L3 needs core evidence (L1 held ≥ 10 s AND core alarm in 3 of 5 s), so trust-v1/v2 cannot block in an outage phase: their L3 = 0 there is the two-layer rule, not a miss. Their L1 in outage phases comes from the RAN fallback (ct = 0 → z_ran).

| config | outage: attack L1 | outage: attack L3 | outage: benign L3 | core present: attack L1 | core present: attack L3 | core present: benign L3 |
|---|---|---|---|---|---|---|
| rules-v1 | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] |
| ran-only | 0.73 [0.55, 0.92] | 0.55 [0.17, 0.91] | 0.00 [0.00, 0.00] | 0.75 [0.42, 1.00] | 0.67 [0.33, 0.92] | 0.00 [0.00, 0.00] |
| core-only | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.83 [0.67, 1.00] | 0.50 [0.25, 0.75] | 0.08 [0.00, 0.25] |
| xd-naive | 0.42 [0.25, 0.50] | 0.42 [0.25, 0.50] | 0.25 [0.08, 0.42] | 0.92 [0.75, 1.00] | 0.67 [0.50, 0.83] | 0.00 [0.00, 0.00] |
| xd-trust-v1 | 0.75 [0.58, 0.92] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.92 [0.75, 1.00] | 0.50 [0.25, 0.75] | 0.00 [0.00, 0.00] |
| xd-trust-v2 | 0.75 [0.58, 0.92] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.92 [0.75, 1.00] | 0.67 [0.42, 0.92] | 0.00 [0.00, 0.00] |

## C. kpm_hide: time to block and attacker bytes at the DN (clean units)

t→L3 = phase start → UPF block (median / p90 over blocked phases; ≥ ~13 s by design: L1 needs 3 of 5 s, L3 needs L1 held 10 s). Rates = attacker UL IP payload at the DN, phase window + 2 s.

| scenario | config | attack phases | blocked | t→L3 med / p90 (s) | before block (kbit/s, med) | after block (kbit/s, med) | after/before | share of phase bytes after block |
|---|---|---:|---|---|---:|---:|---:|---:|
| kpm_hide_x0.1 | rules-v1 | 8 | 0.00 [0.00, 0.00] | – | – | – | – | – |
| kpm_hide_x0.1 | ran-only | 19 | 0.00 [0.00, 0.00] | – | – | – | – | – |
| kpm_hide_x0.1 | core-only | 24 | 0.54 [0.42, 0.67] | 24.4 / 50.3 | 410 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | xd-naive | 24 | 0.62 [0.42, 0.83] | 22.3 / 39.1 | 923 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | xd-trust-v1 | 24 | 0.58 [0.42, 0.79] | 23.8 / 45.2 | 458 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.1 | xd-trust-v2 | 24 | 1.00 [1.00, 1.00] | 24.1 / 30.8 | 526 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | rules-v1 | 8 | 0.00 [0.00, 0.00] | – | – | – | – | – |
| kpm_hide_x0.33 | ran-only | 21 | 0.33 [0.12, 0.61] | 41.6 / 56.3 | 893 | 210 | 0.291 | 0.125 |
| kpm_hide_x0.33 | core-only | 23 | 0.74 [0.62, 0.87] | 25.2 / 45.5 | 427 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | xd-naive | 23 | 0.87 [0.71, 1.00] | 22.1 / 30.0 | 570 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | xd-trust-v1 | 24 | 0.62 [0.46, 0.79] | 23.9 / 56.1 | 416 | 0 | 0.000 | 0.000 |
| kpm_hide_x0.33 | xd-trust-v2 | 24 | 1.00 [1.00, 1.00] | 23.3 / 28.8 | 499 | 0 | 0.000 | 0.000 |

## D. Sensitivity: without the flagged runs [40, 91, 99, 110, 173, 212] (classifier fallback inside a phase)

Largest change of a detection/block rate: **0.099**; of the median delivered fraction (few phases, volatile): 0.222. In every flagged run the sidecar's own answer at the fallback steps was benign / level 0 (checked for 91, 99, 173).

| scenario | config | runs | all → without flagged |
|---|---|---|---|
| core_outage | core-only | 6 → 5 | attack_L1 0.417 → 0.450, attack_L3 0.250 → 0.300, benign_L3 0.042 → 0.000, attack_delivered_frac 0.999 → 0.998 |
| honest | ran-only | 6 → 5 | attack_L1 0.941 → 0.933, attack_L3 0.647 → 0.600, benign_L3 0.158 → 0.059, attack_delivered_frac 0.410 → 0.410 |
| honest | xd-trust-v1 | 6 → 4 | attack_L1 0.958 → 0.938, attack_L3 0.458 → 0.500, benign_L3 0.045 → 0.000, attack_delivered_frac 0.830 → 0.635 |
| honest | xd-trust-v2 | 6 → 4 | attack_L1 0.917 → 0.875, attack_L3 0.667 → 0.625, benign_L3 0.083 → 0.062, attack_delivered_frac 0.746 → 0.968 |

## E. Carried-over L3 per cell (phases dropped from the primary analysis: attacker / benign)

| scenario | rules-v1 | ran-only | core-only | xd-naive | xd-trust-v1 | xd-trust-v2 |
|---|---:|---:|---:|---:|---:|---:|
| honest | 0 / 0 | 7 / 5 | 0 / 1 | 0 / 0 | 0 / 2 | 0 / 0 |
| kpm_hide_x0.1 | 0 / 0 | 5 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| kpm_hide_x0.33 | 0 / 0 | 3 / 4 | 1 / 1 | 1 / 2 | 0 / 0 | 0 / 0 |
| kpm_frame_x2 | 0 / 0 | 9 / 2 | 0 / 0 | 3 / 2 | 0 / 0 | 0 / 0 |
| kpm_frame_x5 | 0 / 0 | 2 / 3 | 0 / 0 | 0 / 6 | 1 / 0 | 0 / 0 |
| core_outage | 0 / 0 | 1 / 2 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| icmp_control | 0 / 0 | 0 / 0 | 3 / 2 | 2 / 0 | 0 / 0 | 0 / 0 |

## F. Failed attempts per cell (failed / attempts; testbed failures, all re-run)

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

Failures are spread over configurations (3–7 each); no configuration is over-represented, so re-running until valid does not select for one.

## G. Control-loop latency, one iteration (one KPM report → action), detection-triggered actions

| segment | n | p50 (ms) | p99 (ms) | max (ms) |
|---|---:|---:|---:|---:|
| gNB KPM measured → xApp (E2 indication) | 159191 | 1.1 | 48.5 | 968.1 |
| xApp: features + sidecar + policy → RC sent | 1440 | 21.7 | 56.6 | 106.4 |
| sidecar /classify (server) | 149259 | 19.5 | 47.9 | 633.3 |
| E2SM-RC sent → gNB ack | 1440 | 0.4 | 1.3 | 3.2 |
| **RAN loop: gNB KPM → RC ack** | 1440 | 39.0 | 100.2 | 167.9 |
| decision → UPF policy accepted | 3750 | 26.0 | 64.0 | 1022.0 |
| **core loop: gNB KPM → UPF policy** | 3750 | 41.4 | 1004.5 | 1554.3 |
| KPM report period | 158743 | 1000.0 | 1020.1 | 1947.5 |
| URR measured (SMF) → xApp (A1-EI path) | 97985 | 1525.8 | 2836.8 | 4493.7 |
| URR report spacing | 97601 | 1027.1 | 2217.6 | 3157.1 |

One iteration meets the near-RT bound (10 ms–1 s) with margin; the loop period is the 1 s KPM report period (the models use 1 s features). The core telemetry reaches the xApp 1.5–2.8 s after measurement (SMF periodic report + A1-EI path): decisions using core evidence act on telemetry older than one loop. The core-loop p99 ≈ 1 s comes from timer-driven TTL refreshes, not from KPM-triggered decisions (decision → UPF p99 64 ms).

## I. L3 decided (xApp level 3) vs enforced at the UPF (clean units, all scenarios)

The UPF Security API refuses a block that would put more than half of the known UEs in block (maxBlockedRatio 0.5: with 2 UEs, the second block → HTTP 403). The tables above count the xApp's L3 decision; the delivered fraction measures what reached the DN.

| config | attacker L3 phases | enforced | refused (403) | benign L3 phases | enforced | refused (403) |
|---|---:|---:|---:|---:|---:|---:|
| rules-v1 | 0 | – | – | 0 | – | – |
| ran-only | 55 | 0.62 | 0.38 | 64 | 0.64 | 0.36 |
| core-only | 80 | 0.95 | 0.05 | 10 | 0.30 | 0.70 |
| xd-naive | 107 | 0.75 | 0.25 | 39 | 0.51 | 0.49 |
| xd-trust-v1 | 71 | 0.96 | 0.04 | 12 | 0.67 | 0.33 |
| xd-trust-v2 | 96 | 0.95 | 0.05 | 13 | 0.46 | 0.54 |

## H. Pre-registered hypotheses (clean units; read off the cells, not targets)

- **H1** trust-v2 ≥ naive on kpm_hide, kpm_frame, core_outage — attack L3 (higher better) / benign L3 (lower better):
  - kpm_hide_x0.1 attack_L3: trust-v2 1.000 vs naive 0.625
  - kpm_hide_x0.1 benign_L3: trust-v2 0.042 vs naive 0.167
  - kpm_hide_x0.33 attack_L3: trust-v2 1.000 vs naive 0.870
  - kpm_hide_x0.33 benign_L3: trust-v2 0.125 vs naive 0.136
  - kpm_frame_x2 attack_L3: trust-v2 0.292 vs naive 0.667
  - kpm_frame_x2 benign_L3: trust-v2 0.000 vs naive 0.455
  - kpm_frame_x5 attack_L3: trust-v2 0.417 vs naive 0.792
  - kpm_frame_x5 benign_L3: trust-v2 0.042 vs naive 0.444
  - core_outage attack_L3: trust-v2 0.333 vs naive 0.542
  - core_outage benign_L3: trust-v2 0.000 vs naive 0.125
- **H2** ran-only ≈ 0 detection on kpm_hide: L1 x0.1 0.053, x0.33 0.429; L3 x0.1 0.000, x0.33 0.333
- **H3** framed benign wrongly blocked ≤ ~2 % under trust-v2: x2 0.000, x5 0.042
- **H4** integrity false alarms ≈ 0 on untampered phases (trust-v2): honest 0.021, kpm_hide_x0.1 0.0, kpm_hide_x0.33 0.0, kpm_frame_x2 0.0, kpm_frame_x5 0.0, core_outage 0.0

