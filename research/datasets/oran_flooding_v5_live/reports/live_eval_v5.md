# Cross-domain defence live (v5, stage B) — results

Runs: 254 (224 with meta_run_ok=1). Sidecar latency {'p50': 19.54, 'p99': 47.7} ms. xApp classifier fallbacks: 34. Unit = (run, UE, attack phase), icmp control apart; brackets = 95% bootstrap CI by run. Levels = enforced by the xApp; delivered = DN UL packets / sent, calibrated to the v4 defence-off median (1 = untouched).

## honest

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 | 0.0 [0.0, 0.0] | – | – | – | – | – | – | 1.002 | 1.0 |
| ran-only | 6 | 0.958 [0.875, 1.0] | 0.75 [0.583, 0.917] | 0.5 | 0.333 [0.083, 0.667] | – | 13.3 | 22.0 | – | – | 0.0 | 0.427 | 0.992 |
| core-only | 6 | 0.75 [0.625, 0.875] | 0.417 [0.208, 0.583] | 0.167 | 0.042 [0.0, 0.125] | – | 15.0 | 22.0 | – | – | 0.0 | 0.995 | 0.999 |
| xd-naive | 6 | 0.792 [0.583, 0.958] | 0.667 [0.542, 0.833] | 0.125 | 0.0 [0.0, 0.0] | – | 13.7 | 22.5 | – | – | 0.0 | 0.563 | 1.0 |
| xd-trust-v1 | 6 | 0.958 [0.875, 1.0] | 0.458 [0.375, 0.5] | 0.333 | 0.125 [0.042, 0.208] | – | 13.4 | 22.4 | – | – | 0.0 | 0.83 | 1.0 |
| xd-trust-v2 | 6 | 0.917 [0.833, 1.0] | 0.667 [0.458, 0.875] | 0.292 | 0.083 [0.0, 0.167] | – | 16.1 | 31.7 | – | – | 0.021 | 0.746 | 0.998 |

## kpm_hide_x0.1

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 | 0.0 [0.0, 0.0] | – | – | – | – | – | – | 0.999 | 1.0 |
| ran-only | 6 | 0.25 [0.042, 0.5] | 0.208 [0.042, 0.376] | 0.667 | 0.583 [0.417, 0.792] | – | 0.7 | 0.7 | 0.0 | – | 0.0 | 0.998 | 0.617 |
| core-only | 6 | 0.75 [0.583, 0.917] | 0.542 [0.417, 0.667] | 0.125 | 0.0 [0.0, 0.0] | – | 15.2 | 24.4 | 0.0 | – | 0.0 | 0.851 | 1.0 |
| xd-naive | 6 | 0.833 [0.667, 0.958] | 0.625 [0.417, 0.833] | 0.25 | 0.167 [0.0, 0.417] | – | 14.7 | 22.3 | 0.0 | – | 0.0 | 0.458 | 1.0 |
| xd-trust-v1 | 6 | 0.792 [0.667, 0.917] | 0.583 [0.417, 0.792] | 0.042 | 0.0 [0.0, 0.0] | – | 15.2 | 23.8 | 1.0 | 13.8 | 0.0 | 0.726 | 1.0 |
| xd-trust-v2 | 6 | 1.0 [1.0, 1.0] | 1.0 [1.0, 1.0] | 0.25 | 0.042 [0.0, 0.125] | – | 14.9 | 24.1 | 1.0 | 13.9 | 0.0 | 0.355 | 1.0 |

## kpm_hide_x0.33

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 | 0.0 [0.0, 0.0] | – | – | – | – | – | – | 0.999 | 1.0 |
| ran-only | 6 | 0.5 [0.167, 0.833] | 0.417 [0.125, 0.708] | 0.667 | 0.5 [0.292, 0.75] | – | 12.4 | 27.1 | 0.0 | – | 0.0 | 0.988 | 0.668 |
| core-only | 6 | 0.833 [0.75, 0.917] | 0.75 [0.625, 0.875] | 0.167 | 0.042 [0.0, 0.125] | – | 15.5 | 25.0 | 0.0 | – | 0.0 | 0.478 | 1.0 |
| xd-naive | 6 | 0.917 [0.833, 1.0] | 0.875 [0.708, 1.0] | 0.208 | 0.208 [0.0, 0.542] | – | 13.0 | 22.0 | 0.0 | – | 0.0 | 0.349 | 1.0 |
| xd-trust-v1 | 6 | 0.875 [0.792, 0.958] | 0.625 [0.458, 0.792] | 0.167 | 0.0 [0.0, 0.0] | – | 13.4 | 23.9 | 1.0 | 17.3 | 0.0 | 0.832 | 1.0 |
| xd-trust-v2 | 6 | 1.0 [1.0, 1.0] | 1.0 [1.0, 1.0] | 0.292 | 0.125 [0.0, 0.292] | – | 13.6 | 23.3 | 1.0 | 18.0 | 0.0 | 0.355 | 1.0 |

## kpm_frame_x2

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.5 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | – | – | – | – | – | 1.0 | 0.997 |
| ran-only | 6 | 0.917 [0.833, 1.0] | 0.583 [0.292, 0.875] | 0.75 | 0.667 [0.375, 0.917] | 0.667 [0.375, 0.917] | 13.4 | 0.6 | 0.0 | – | 0.0 | 0.943 | 0.816 |
| core-only | 6 | 0.75 [0.625, 0.875] | 0.5 [0.375, 0.583] | 0.083 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 16.1 | 23.4 | 0.0 | – | 0.0 | 0.864 | 1.0 |
| xd-naive | 6 | 0.875 [0.708, 1.0] | 0.708 [0.458, 0.917] | 0.542 | 0.5 [0.167, 0.833] | 0.5 [0.167, 0.833] | 12.8 | 22.2 | 0.0 | – | 0.0 | 0.715 | 0.812 |
| xd-trust-v1 | 6 | 0.792 [0.624, 0.958] | 0.292 [0.083, 0.5] | 0.375 | 0.083 [0.0, 0.25] | 0.083 [0.0, 0.25] | 15.6 | 25.6 | 0.75 | 10.8 | 0.042 | 0.994 | 1.0 |
| xd-trust-v2 | 6 | 0.708 [0.583, 0.833] | 0.292 [0.25, 0.375] | 0.458 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 15.8 | 31.1 | 0.75 | 10.9 | 0.0 | 0.998 | 1.0 |

## kpm_frame_x5

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.75 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | – | – | – | – | – | 1.0 | 0.999 |
| ran-only | 6 | 0.708 [0.5, 0.917] | 0.333 [0.125, 0.542] | 0.917 | 0.667 [0.417, 0.917] | 0.667 [0.417, 0.917] | 38.7 | 48.4 | 0.0 | – | 0.0 | 0.999 | 0.358 |
| core-only | 6 | 0.875 [0.792, 0.958] | 0.667 [0.542, 0.833] | 0.167 | 0.042 [0.0, 0.125] | 0.042 [0.0, 0.125] | 16.1 | 25.1 | 0.0 | – | 0.0 | 0.616 | 1.0 |
| xd-naive | 6 | 0.792 [0.542, 1.0] | 0.792 [0.542, 1.0] | 0.75 | 0.583 [0.333, 0.833] | 0.583 [0.333, 0.833] | 13.2 | 30.0 | 0.0 | – | 0.0 | 0.651 | 0.336 |
| xd-trust-v1 | 6 | 0.625 [0.542, 0.708] | 0.5 [0.333, 0.667] | 0.542 | 0.083 [0.0, 0.25] | 0.083 [0.0, 0.25] | 13.8 | 23.5 | 1.0 | 10.7 | 0.0 | 0.856 | 0.999 |
| xd-trust-v2 | 6 | 0.75 [0.625, 0.875] | 0.417 [0.333, 0.5] | 0.542 | 0.042 [0.0, 0.125] | 0.042 [0.0, 0.125] | 14.6 | 22.0 | 1.0 | 10.5 | 0.0 | 0.994 | 1.0 |

## core_outage

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 | 0.0 [0.0, 0.0] | – | – | – | – | – | – | 1.001 | 0.997 |
| ran-only | 6 | 0.75 [0.5, 0.958] | 0.625 [0.375, 0.875] | 0.25 | 0.083 [0.0, 0.167] | – | 14.4 | 22.5 | – | – | 0.0 | 0.754 | 1.0 |
| core-only | 6 | 0.417 [0.333, 0.5] | 0.25 [0.125, 0.375] | 0.125 | 0.042 [0.0, 0.125] | – | 15.1 | 23.1 | – | – | 0.0 | 0.999 | 1.0 |
| xd-naive | 6 | 0.667 [0.583, 0.75] | 0.542 [0.417, 0.667] | 0.208 | 0.125 [0.042, 0.208] | – | 14.1 | 22.8 | – | – | 0.0 | 0.934 | 1.0 |
| xd-trust-v1 | 6 | 0.833 [0.667, 0.958] | 0.25 [0.125, 0.375] | 0.125 | 0.0 [0.0, 0.0] | – | 13.6 | 31.5 | – | – | 0.0 | 0.996 | 0.999 |
| xd-trust-v2 | 6 | 0.833 [0.667, 0.958] | 0.333 [0.208, 0.458] | 0.292 | 0.0 [0.0, 0.0] | – | 13.6 | 23.8 | – | – | 0.0 | 0.979 | 0.998 |

## icmp_control

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 2 | – | – | – | – | – | – | – | – | – | – | – | – |
| ran-only | 6 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| core-only | 6 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| xd-naive | 6 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| xd-trust-v1 | 6 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| xd-trust-v2 | 6 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |

## Offline replay (v4 test runs) vs live

| scenario | config | metric | offline | live |
|---|---|---|---:|---:|
| core_outage | core-only | attack_L1 | 0.36 | 0.417 |
| core_outage | core-only | attack_L3 | 0.247 | 0.25 |
| core_outage | core-only | benign_L3 | 0.01 | 0.042 |
| core_outage | core-only | integrity_tampered | 0.0 | None |
| core_outage | core-only | t_L1_median | 20.0 | 15.1 |
| core_outage | core-only | t_L3_median | 25.0 | 23.1 |
| core_outage | ran-only | attack_L1 | 0.607 | 0.75 |
| core_outage | ran-only | attack_L3 | 0.416 | 0.625 |
| core_outage | ran-only | benign_L3 | 0.01 | 0.083 |
| core_outage | ran-only | integrity_tampered | 0.0 | None |
| core_outage | ran-only | t_L1_median | 16.0 | 14.4 |
| core_outage | ran-only | t_L3_median | 26.3 | 22.5 |
| core_outage | rules-v1 | attack_L1 | None | 0.0 |
| core_outage | rules-v1 | attack_L3 | None | 0.0 |
| core_outage | rules-v1 | benign_L3 | None | 0.0 |
| core_outage | xd-naive | attack_L1 | 0.787 | 0.667 |
| core_outage | xd-naive | attack_L3 | 0.517 | 0.542 |
| core_outage | xd-naive | benign_L3 | 0.204 | 0.125 |
| core_outage | xd-naive | integrity_tampered | 0.0 | None |
| core_outage | xd-naive | t_L1_median | 15.6 | 14.1 |
| core_outage | xd-naive | t_L3_median | 24.2 | 22.8 |
| core_outage | xd-trust-v1 | attack_L1 | 0.652 | 0.833 |
| core_outage | xd-trust-v1 | attack_L3 | 0.18 | 0.25 |
| core_outage | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| core_outage | xd-trust-v1 | integrity_tampered | 0.0 | None |
| core_outage | xd-trust-v1 | t_L1_median | 15.6 | 13.6 |
| core_outage | xd-trust-v1 | t_L3_median | 27.3 | 31.5 |
| core_outage | xd-trust-v2 | attack_L1 | 0.652 | 0.833 |
| core_outage | xd-trust-v2 | attack_L3 | 0.18 | 0.333 |
| core_outage | xd-trust-v2 | benign_L3 | 0.01 | 0.0 |
| core_outage | xd-trust-v2 | integrity_tampered | 0.0 | None |
| core_outage | xd-trust-v2 | t_L1_median | 15.6 | 13.6 |
| core_outage | xd-trust-v2 | t_L3_median | 27.3 | 23.8 |
| honest | core-only | attack_L1 | 0.663 | 0.75 |
| honest | core-only | attack_L3 | 0.483 | 0.417 |
| honest | core-only | benign_L3 | 0.01 | 0.042 |
| honest | core-only | t_L1_median | 17.5 | 15.0 |
| honest | core-only | t_L3_median | 24.3 | 22.0 |
| honest | ran-only | attack_L1 | 0.607 | 0.958 |
| honest | ran-only | attack_L3 | 0.416 | 0.75 |
| honest | ran-only | benign_L3 | 0.01 | 0.333 |
| honest | ran-only | t_L1_median | 16.0 | 13.3 |
| honest | ran-only | t_L3_median | 26.3 | 22.0 |
| honest | rules-v1 | attack_L1 | None | 0.0 |
| honest | rules-v1 | attack_L3 | None | 0.0 |
| honest | rules-v1 | benign_L3 | None | 0.0 |
| honest | xd-naive | attack_L1 | 0.697 | 0.792 |
| honest | xd-naive | attack_L3 | 0.506 | 0.667 |
| honest | xd-naive | benign_L3 | 0.019 | 0.0 |
| honest | xd-naive | t_L1_median | 15.2 | 13.7 |
| honest | xd-naive | t_L3_median | 23.7 | 22.5 |
| honest | xd-trust-v1 | attack_L1 | 0.697 | 0.958 |
| honest | xd-trust-v1 | attack_L3 | 0.337 | 0.458 |
| honest | xd-trust-v1 | benign_L3 | 0.01 | 0.125 |
| honest | xd-trust-v1 | t_L1_median | 15.2 | 13.4 |
| honest | xd-trust-v1 | t_L3_median | 24.4 | 22.4 |
| honest | xd-trust-v2 | attack_L1 | 0.697 | 0.917 |
| honest | xd-trust-v2 | attack_L3 | 0.337 | 0.667 |
| honest | xd-trust-v2 | benign_L3 | 0.01 | 0.083 |
| honest | xd-trust-v2 | t_L1_median | 15.2 | 16.1 |
| honest | xd-trust-v2 | t_L3_median | 24.4 | 31.7 |
| kpm_frame_x2 | core-only | attack_L1 | 0.663 | 0.75 |
| kpm_frame_x2 | core-only | attack_L3 | 0.483 | 0.5 |
| kpm_frame_x2 | core-only | benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | core-only | framed_benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x2 | core-only | t_L1_median | 17.5 | 16.1 |
| kpm_frame_x2 | core-only | t_L3_median | 24.3 | 23.4 |
| kpm_frame_x2 | ran-only | attack_L1 | 0.618 | 0.917 |
| kpm_frame_x2 | ran-only | attack_L3 | 0.404 | 0.583 |
| kpm_frame_x2 | ran-only | benign_L3 | 0.66 | 0.667 |
| kpm_frame_x2 | ran-only | framed_benign_L3 | 0.66 | 0.667 |
| kpm_frame_x2 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x2 | ran-only | t_L1_median | 15.6 | 13.4 |
| kpm_frame_x2 | ran-only | t_L3_median | 25.9 | 0.6 |
| kpm_frame_x2 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_frame_x2 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_frame_x2 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_frame_x2 | rules-v1 | framed_benign_L3 | None | 0.0 |
| kpm_frame_x2 | xd-naive | attack_L1 | 0.708 | 0.875 |
| kpm_frame_x2 | xd-naive | attack_L3 | 0.506 | 0.708 |
| kpm_frame_x2 | xd-naive | benign_L3 | 0.437 | 0.5 |
| kpm_frame_x2 | xd-naive | framed_benign_L3 | 0.437 | 0.5 |
| kpm_frame_x2 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x2 | xd-naive | t_L1_median | 14.6 | 12.8 |
| kpm_frame_x2 | xd-naive | t_L3_median | 22.9 | 22.2 |
| kpm_frame_x2 | xd-trust-v1 | attack_L1 | 0.685 | 0.792 |
| kpm_frame_x2 | xd-trust-v1 | attack_L3 | 0.404 | 0.292 |
| kpm_frame_x2 | xd-trust-v1 | benign_L3 | 0.01 | 0.083 |
| kpm_frame_x2 | xd-trust-v1 | framed_benign_L3 | 0.01 | 0.083 |
| kpm_frame_x2 | xd-trust-v1 | integrity_tampered | 0.728 | 0.75 |
| kpm_frame_x2 | xd-trust-v1 | t_L1_median | 15.6 | 15.6 |
| kpm_frame_x2 | xd-trust-v1 | t_L3_median | 24.9 | 25.6 |
| kpm_frame_x2 | xd-trust-v1 | t_integrity_median | 11.3 | 10.8 |
| kpm_frame_x2 | xd-trust-v2 | attack_L1 | 0.685 | 0.708 |
| kpm_frame_x2 | xd-trust-v2 | attack_L3 | 0.404 | 0.292 |
| kpm_frame_x2 | xd-trust-v2 | benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | xd-trust-v2 | framed_benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | xd-trust-v2 | integrity_tampered | 0.728 | 0.75 |
| kpm_frame_x2 | xd-trust-v2 | t_L1_median | 15.6 | 15.8 |
| kpm_frame_x2 | xd-trust-v2 | t_L3_median | 24.9 | 31.1 |
| kpm_frame_x2 | xd-trust-v2 | t_integrity_median | 11.3 | 10.9 |
| kpm_frame_x5 | core-only | attack_L1 | 0.663 | 0.875 |
| kpm_frame_x5 | core-only | attack_L3 | 0.483 | 0.667 |
| kpm_frame_x5 | core-only | benign_L3 | 0.01 | 0.042 |
| kpm_frame_x5 | core-only | framed_benign_L3 | 0.01 | 0.042 |
| kpm_frame_x5 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x5 | core-only | t_L1_median | 17.5 | 16.1 |
| kpm_frame_x5 | core-only | t_L3_median | 24.3 | 25.1 |
| kpm_frame_x5 | ran-only | attack_L1 | 0.618 | 0.708 |
| kpm_frame_x5 | ran-only | attack_L3 | 0.416 | 0.333 |
| kpm_frame_x5 | ran-only | benign_L3 | 0.932 | 0.667 |
| kpm_frame_x5 | ran-only | framed_benign_L3 | 0.932 | 0.667 |
| kpm_frame_x5 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x5 | ran-only | t_L1_median | 13.8 | 38.7 |
| kpm_frame_x5 | ran-only | t_L3_median | 25.3 | 48.4 |
| kpm_frame_x5 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_frame_x5 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_frame_x5 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_frame_x5 | rules-v1 | framed_benign_L3 | None | 0.0 |
| kpm_frame_x5 | xd-naive | attack_L1 | 0.719 | 0.792 |
| kpm_frame_x5 | xd-naive | attack_L3 | 0.517 | 0.792 |
| kpm_frame_x5 | xd-naive | benign_L3 | 0.757 | 0.583 |
| kpm_frame_x5 | xd-naive | framed_benign_L3 | 0.757 | 0.583 |
| kpm_frame_x5 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x5 | xd-naive | t_L1_median | 13.9 | 13.2 |
| kpm_frame_x5 | xd-naive | t_L3_median | 22.7 | 30.0 |
| kpm_frame_x5 | xd-trust-v1 | attack_L1 | 0.663 | 0.625 |
| kpm_frame_x5 | xd-trust-v1 | attack_L3 | 0.449 | 0.5 |
| kpm_frame_x5 | xd-trust-v1 | benign_L3 | 0.019 | 0.083 |
| kpm_frame_x5 | xd-trust-v1 | framed_benign_L3 | 0.019 | 0.083 |
| kpm_frame_x5 | xd-trust-v1 | integrity_tampered | 1.0 | 1.0 |
| kpm_frame_x5 | xd-trust-v1 | t_L1_median | 15.6 | 13.8 |
| kpm_frame_x5 | xd-trust-v1 | t_L3_median | 24.3 | 23.5 |
| kpm_frame_x5 | xd-trust-v1 | t_integrity_median | 11.3 | 10.7 |
| kpm_frame_x5 | xd-trust-v2 | attack_L1 | 0.663 | 0.75 |
| kpm_frame_x5 | xd-trust-v2 | attack_L3 | 0.449 | 0.417 |
| kpm_frame_x5 | xd-trust-v2 | benign_L3 | 0.019 | 0.042 |
| kpm_frame_x5 | xd-trust-v2 | framed_benign_L3 | 0.019 | 0.042 |
| kpm_frame_x5 | xd-trust-v2 | integrity_tampered | 1.0 | 1.0 |
| kpm_frame_x5 | xd-trust-v2 | t_L1_median | 15.6 | 14.6 |
| kpm_frame_x5 | xd-trust-v2 | t_L3_median | 24.3 | 22.0 |
| kpm_frame_x5 | xd-trust-v2 | t_integrity_median | 11.3 | 10.5 |
| kpm_hide_x0.1 | core-only | attack_L1 | 0.663 | 0.75 |
| kpm_hide_x0.1 | core-only | attack_L3 | 0.483 | 0.542 |
| kpm_hide_x0.1 | core-only | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.1 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.1 | core-only | t_L1_median | 17.5 | 15.2 |
| kpm_hide_x0.1 | core-only | t_L3_median | 24.3 | 24.4 |
| kpm_hide_x0.1 | ran-only | attack_L1 | 0.0 | 0.25 |
| kpm_hide_x0.1 | ran-only | attack_L3 | 0.0 | 0.208 |
| kpm_hide_x0.1 | ran-only | benign_L3 | 0.019 | 0.583 |
| kpm_hide_x0.1 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.1 | ran-only | t_L1_median | None | 0.7 |
| kpm_hide_x0.1 | ran-only | t_L3_median | None | 0.7 |
| kpm_hide_x0.1 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_hide_x0.1 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_hide_x0.1 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_hide_x0.1 | xd-naive | attack_L1 | 0.798 | 0.833 |
| kpm_hide_x0.1 | xd-naive | attack_L3 | 0.64 | 0.625 |
| kpm_hide_x0.1 | xd-naive | benign_L3 | 0.019 | 0.167 |
| kpm_hide_x0.1 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.1 | xd-naive | t_L1_median | 16.0 | 14.7 |
| kpm_hide_x0.1 | xd-naive | t_L3_median | 24.4 | 22.3 |
| kpm_hide_x0.1 | xd-trust-v1 | attack_L1 | 0.674 | 0.792 |
| kpm_hide_x0.1 | xd-trust-v1 | attack_L3 | 0.461 | 0.583 |
| kpm_hide_x0.1 | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.1 | xd-trust-v1 | integrity_tampered | 1.0 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v1 | t_L1_median | 17.6 | 15.2 |
| kpm_hide_x0.1 | xd-trust-v1 | t_L3_median | 24.3 | 23.8 |
| kpm_hide_x0.1 | xd-trust-v1 | t_integrity_median | 13.6 | 13.8 |
| kpm_hide_x0.1 | xd-trust-v2 | attack_L1 | 1.0 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v2 | attack_L3 | 0.989 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v2 | benign_L3 | 0.019 | 0.042 |
| kpm_hide_x0.1 | xd-trust-v2 | integrity_tampered | 1.0 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v2 | t_L1_median | 15.1 | 14.9 |
| kpm_hide_x0.1 | xd-trust-v2 | t_L3_median | 24.1 | 24.1 |
| kpm_hide_x0.1 | xd-trust-v2 | t_integrity_median | 13.6 | 13.9 |
| kpm_hide_x0.33 | core-only | attack_L1 | 0.663 | 0.833 |
| kpm_hide_x0.33 | core-only | attack_L3 | 0.483 | 0.75 |
| kpm_hide_x0.33 | core-only | benign_L3 | 0.01 | 0.042 |
| kpm_hide_x0.33 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.33 | core-only | t_L1_median | 17.5 | 15.5 |
| kpm_hide_x0.33 | core-only | t_L3_median | 24.3 | 25.0 |
| kpm_hide_x0.33 | ran-only | attack_L1 | 0.0 | 0.5 |
| kpm_hide_x0.33 | ran-only | attack_L3 | 0.0 | 0.417 |
| kpm_hide_x0.33 | ran-only | benign_L3 | 0.019 | 0.5 |
| kpm_hide_x0.33 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.33 | ran-only | t_L1_median | None | 12.4 |
| kpm_hide_x0.33 | ran-only | t_L3_median | None | 27.1 |
| kpm_hide_x0.33 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_hide_x0.33 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_hide_x0.33 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_hide_x0.33 | xd-naive | attack_L1 | 0.921 | 0.917 |
| kpm_hide_x0.33 | xd-naive | attack_L3 | 0.753 | 0.875 |
| kpm_hide_x0.33 | xd-naive | benign_L3 | 0.019 | 0.208 |
| kpm_hide_x0.33 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.33 | xd-naive | t_L1_median | 15.6 | 13.0 |
| kpm_hide_x0.33 | xd-naive | t_L3_median | 24.1 | 22.0 |
| kpm_hide_x0.33 | xd-trust-v1 | attack_L1 | 0.742 | 0.875 |
| kpm_hide_x0.33 | xd-trust-v1 | attack_L3 | 0.461 | 0.625 |
| kpm_hide_x0.33 | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.33 | xd-trust-v1 | integrity_tampered | 0.989 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v1 | t_L1_median | 15.3 | 13.4 |
| kpm_hide_x0.33 | xd-trust-v1 | t_L3_median | 24.3 | 23.9 |
| kpm_hide_x0.33 | xd-trust-v1 | t_integrity_median | 16.3 | 17.3 |
| kpm_hide_x0.33 | xd-trust-v2 | attack_L1 | 1.0 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v2 | attack_L3 | 0.966 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v2 | benign_L3 | 0.019 | 0.125 |
| kpm_hide_x0.33 | xd-trust-v2 | integrity_tampered | 0.989 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v2 | t_L1_median | 15.6 | 13.6 |
| kpm_hide_x0.33 | xd-trust-v2 | t_L3_median | 24.4 | 23.3 |
| kpm_hide_x0.33 | xd-trust-v2 | t_integrity_median | 16.3 | 18.0 |
