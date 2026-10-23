# PILOT (excluded from results) — cross-domain defence live (v5), 1 rep per cell

Runs: 47 (42 with meta_run_ok=1). Sidecar latency {'p50': 18.82, 'p99': 39.34} ms. xApp classifier fallbacks: 0. Unit = (run, UE, attack phase), icmp control apart; brackets = 95% bootstrap CI by run. Levels = enforced by the xApp; delivered = DN UL packets / sent, calibrated to the v4 defence-off median (1 = untouched).

## honest

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | 0.0 | 0.0 | 0.0 | 0.0 | – | – | – | – | – | – | 1.003 | 0.991 |
| ran-only | 1 | 1.0 | 0.5 | 0.0 | 0.0 | – | 15.0 | 22.3 | – | – | 0.0 | 0.685 | 0.992 |
| core-only | 1 | 0.75 | 0.75 | 0.0 | 0.0 | – | 13.8 | 22.8 | – | – | 0.0 | 0.642 | 0.989 |
| xd-naive | 1 | 1.0 | 1.0 | 0.0 | 0.0 | – | 13.8 | 28.8 | – | – | 0.0 | 0.474 | 0.999 |
| xd-trust-v1 | 1 | 1.0 | 0.5 | 0.0 | 0.0 | – | 13.7 | 35.9 | – | – | 0.0 | 0.596 | 1.0 |
| xd-trust-v2 | 1 | 1.0 | 0.5 | 0.0 | 0.0 | – | 14.3 | 21.8 | – | – | 0.0 | 0.673 | 0.994 |

## kpm_hide_x0.1

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | 0.0 | 0.0 | 0.0 | 0.0 | – | – | – | – | – | – | 1.005 | 0.999 |
| ran-only | 1 | 0.0 | 0.0 | 0.5 | 0.5 | – | – | – | 0.0 | – | 0.0 | 1.0 | 0.724 |
| core-only | 1 | 0.75 | 0.5 | 0.0 | 0.0 | – | 15.2 | 22.5 | 0.0 | – | 0.0 | 0.691 | 0.993 |
| xd-naive | 1 | 0.75 | 0.5 | 0.0 | 0.0 | – | 11.7 | 20.6 | 0.0 | – | 0.0 | 0.663 | 0.994 |
| xd-trust-v1 | 1 | 1.0 | 0.75 | 0.25 | 0.0 | – | 20.7 | 21.9 | 1.0 | 15.3 | 0.0 | 0.573 | 0.988 |
| xd-trust-v2 | 1 | 1.0 | 1.0 | 0.25 | 0.0 | – | 13.7 | 22.7 | 1.0 | 14.1 | 0.0 | 0.345 | 0.996 |

## kpm_hide_x0.33

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | 0.0 | 0.0 | 0.0 | 0.0 | – | – | – | – | – | – | 1.002 | 0.998 |
| ran-only | 1 | 0.0 | 0.0 | 0.5 | 0.5 | – | – | – | 0.0 | – | 0.0 | 1.002 | 0.826 |
| core-only | 1 | 1.0 | 0.5 | 0.0 | 0.0 | – | 28.4 | 21.7 | 0.0 | – | 0.0 | 0.682 | 1.0 |
| xd-naive | 1 | 0.75 | 0.5 | 0.0 | 0.0 | – | 12.8 | 21.7 | 0.0 | – | 0.0 | 0.67 | 0.992 |
| xd-trust-v1 | 1 | 1.0 | 0.75 | 0.0 | 0.0 | – | 24.0 | 22.5 | 1.0 | 18.0 | 0.0 | 0.658 | 0.999 |
| xd-trust-v2 | 1 | 1.0 | 1.0 | 0.0 | 0.0 | – | 15.7 | 24.7 | 1.0 | 16.1 | 0.0 | 0.383 | 0.992 |

## kpm_frame_x2

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | – | – | – | – | – | 1.003 | 0.995 |
| ran-only | 1 | 1.0 | 0.5 | 0.5 | 0.25 | 0.25 | 24.7 | 27.8 | 0.0 | – | 0.0 | 1.001 | 0.975 |
| core-only | 1 | 1.0 | 0.5 | 0.0 | 0.0 | 0.0 | 15.1 | 20.5 | 0.0 | – | 0.0 | 0.665 | 1.0 |
| xd-naive | 1 | 0.5 | 0.5 | 0.0 | 0.0 | 0.0 | 12.8 | 21.8 | 0.0 | – | 0.0 | 0.672 | 0.988 |
| xd-trust-v1 | 1 | 1.0 | 0.25 | 0.0 | 0.0 | 0.0 | 13.9 | 21.8 | 0.75 | 10.9 | 0.0 | 1.005 | 0.993 |
| xd-trust-v2 | 1 | 0.75 | 0.25 | 0.0 | 0.0 | 0.0 | 13.6 | 22.6 | 0.5 | 11.1 | 0.0 | 1.006 | 1.0 |

## kpm_frame_x5

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | 0.0 | 0.0 | 0.5 | 0.0 | 0.0 | – | – | – | – | – | 1.001 | 0.988 |
| ran-only | 1 | 0.0 | 0.0 | 0.5 | 0.0 | 0.0 | – | – | 0.0 | – | 0.0 | 1.004 | 0.994 |
| core-only | 1 | 0.75 | 0.75 | 0.0 | 0.0 | 0.0 | 12.4 | 21.4 | 0.0 | – | 0.0 | 0.596 | 0.997 |
| xd-naive | 1 | 0.75 | 0.75 | 0.5 | 0.25 | 0.25 | 14.8 | 23.8 | 0.0 | – | 0.0 | 0.688 | 0.975 |
| xd-trust-v1 | 1 | 0.5 | 0.5 | 0.0 | 0.0 | 0.0 | 11.8 | 20.8 | 1.0 | 10.8 | 0.0 | 0.668 | 0.996 |
| xd-trust-v2 | 1 | 0.75 | 0.5 | 0.25 | 0.0 | 0.0 | 12.9 | 20.7 | 1.0 | 15.4 | 0.0 | 0.675 | 0.998 |

## core_outage

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | 0.0 | 0.0 | 0.0 | 0.0 | – | – | – | – | – | – | 1.005 | 0.999 |
| ran-only | 1 | 0.75 | 0.75 | 0.25 | 0.0 | – | 13.1 | 22.1 | – | – | 0.0 | 0.516 | 0.992 |
| core-only | 1 | 0.25 | 0.25 | 0.25 | 0.0 | – | 14.7 | 23.7 | – | – | 0.0 | 1.0 | 0.991 |
| xd-naive | 1 | 0.75 | 0.75 | 0.25 | 0.25 | – | 13.0 | 22.0 | – | – | 0.0 | 0.592 | 0.988 |
| xd-trust-v1 | 1 | 1.0 | 0.25 | 0.25 | 0.0 | – | 14.6 | 22.3 | – | – | 0.0 | 1.002 | 0.99 |
| xd-trust-v2 | 1 | 1.0 | 0.5 | 0.0 | 0.0 | – | 19.9 | 35.6 | – | – | 0.0 | 0.921 | 1.0 |

## icmp_control

| config | runs | attack L1 | attack L3 | benign L1 | benign L3 | framed benign L3 | t→L1 med | t→L3 med | integrity on tampered | t→integrity | integrity false (untampered) | attack delivered | benign delivered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules-v1 | 1 | – | – | – | – | – | – | – | – | – | – | – | – |
| ran-only | 1 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| core-only | 1 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| xd-naive | 1 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| xd-trust-v1 | 1 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |
| xd-trust-v2 | 1 | – | – | – | – | – | – | – | – | – | 0.0 | – | – |

## Offline replay (v4 test runs) vs live

| scenario | config | metric | offline | live |
|---|---|---|---:|---:|
| core_outage | core-only | attack_L1 | 0.36 | 0.25 |
| core_outage | core-only | attack_L3 | 0.247 | 0.25 |
| core_outage | core-only | benign_L3 | 0.01 | 0.0 |
| core_outage | core-only | integrity_tampered | 0.0 | None |
| core_outage | core-only | t_L1_median | 20.0 | 14.7 |
| core_outage | core-only | t_L3_median | 25.0 | 23.7 |
| core_outage | ran-only | attack_L1 | 0.607 | 0.75 |
| core_outage | ran-only | attack_L3 | 0.416 | 0.75 |
| core_outage | ran-only | benign_L3 | 0.01 | 0.0 |
| core_outage | ran-only | integrity_tampered | 0.0 | None |
| core_outage | ran-only | t_L1_median | 16.0 | 13.1 |
| core_outage | ran-only | t_L3_median | 26.3 | 22.1 |
| core_outage | rules-v1 | attack_L1 | None | 0.0 |
| core_outage | rules-v1 | attack_L3 | None | 0.0 |
| core_outage | rules-v1 | benign_L3 | None | 0.0 |
| core_outage | xd-naive | attack_L1 | 0.787 | 0.75 |
| core_outage | xd-naive | attack_L3 | 0.517 | 0.75 |
| core_outage | xd-naive | benign_L3 | 0.204 | 0.25 |
| core_outage | xd-naive | integrity_tampered | 0.0 | None |
| core_outage | xd-naive | t_L1_median | 15.6 | 13.0 |
| core_outage | xd-naive | t_L3_median | 24.2 | 22.0 |
| core_outage | xd-trust-v1 | attack_L1 | 0.652 | 1.0 |
| core_outage | xd-trust-v1 | attack_L3 | 0.18 | 0.25 |
| core_outage | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| core_outage | xd-trust-v1 | integrity_tampered | 0.0 | None |
| core_outage | xd-trust-v1 | t_L1_median | 15.6 | 14.6 |
| core_outage | xd-trust-v1 | t_L3_median | 27.3 | 22.3 |
| core_outage | xd-trust-v2 | attack_L1 | 0.652 | 1.0 |
| core_outage | xd-trust-v2 | attack_L3 | 0.18 | 0.5 |
| core_outage | xd-trust-v2 | benign_L3 | 0.01 | 0.0 |
| core_outage | xd-trust-v2 | integrity_tampered | 0.0 | None |
| core_outage | xd-trust-v2 | t_L1_median | 15.6 | 19.9 |
| core_outage | xd-trust-v2 | t_L3_median | 27.3 | 35.6 |
| honest | core-only | attack_L1 | 0.663 | 0.75 |
| honest | core-only | attack_L3 | 0.483 | 0.75 |
| honest | core-only | benign_L3 | 0.01 | 0.0 |
| honest | core-only | t_L1_median | 17.5 | 13.8 |
| honest | core-only | t_L3_median | 24.3 | 22.8 |
| honest | ran-only | attack_L1 | 0.607 | 1.0 |
| honest | ran-only | attack_L3 | 0.416 | 0.5 |
| honest | ran-only | benign_L3 | 0.01 | 0.0 |
| honest | ran-only | t_L1_median | 16.0 | 15.0 |
| honest | ran-only | t_L3_median | 26.3 | 22.3 |
| honest | rules-v1 | attack_L1 | None | 0.0 |
| honest | rules-v1 | attack_L3 | None | 0.0 |
| honest | rules-v1 | benign_L3 | None | 0.0 |
| honest | xd-naive | attack_L1 | 0.697 | 1.0 |
| honest | xd-naive | attack_L3 | 0.506 | 1.0 |
| honest | xd-naive | benign_L3 | 0.019 | 0.0 |
| honest | xd-naive | t_L1_median | 15.2 | 13.8 |
| honest | xd-naive | t_L3_median | 23.7 | 28.8 |
| honest | xd-trust-v1 | attack_L1 | 0.697 | 1.0 |
| honest | xd-trust-v1 | attack_L3 | 0.337 | 0.5 |
| honest | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| honest | xd-trust-v1 | t_L1_median | 15.2 | 13.7 |
| honest | xd-trust-v1 | t_L3_median | 24.4 | 35.9 |
| honest | xd-trust-v2 | attack_L1 | 0.697 | 1.0 |
| honest | xd-trust-v2 | attack_L3 | 0.337 | 0.5 |
| honest | xd-trust-v2 | benign_L3 | 0.01 | 0.0 |
| honest | xd-trust-v2 | t_L1_median | 15.2 | 14.3 |
| honest | xd-trust-v2 | t_L3_median | 24.4 | 21.8 |
| kpm_frame_x2 | core-only | attack_L1 | 0.663 | 1.0 |
| kpm_frame_x2 | core-only | attack_L3 | 0.483 | 0.5 |
| kpm_frame_x2 | core-only | benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | core-only | framed_benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x2 | core-only | t_L1_median | 17.5 | 15.1 |
| kpm_frame_x2 | core-only | t_L3_median | 24.3 | 20.5 |
| kpm_frame_x2 | ran-only | attack_L1 | 0.618 | 1.0 |
| kpm_frame_x2 | ran-only | attack_L3 | 0.404 | 0.5 |
| kpm_frame_x2 | ran-only | benign_L3 | 0.66 | 0.25 |
| kpm_frame_x2 | ran-only | framed_benign_L3 | 0.66 | 0.25 |
| kpm_frame_x2 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x2 | ran-only | t_L1_median | 15.6 | 24.7 |
| kpm_frame_x2 | ran-only | t_L3_median | 25.9 | 27.8 |
| kpm_frame_x2 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_frame_x2 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_frame_x2 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_frame_x2 | rules-v1 | framed_benign_L3 | None | 0.0 |
| kpm_frame_x2 | xd-naive | attack_L1 | 0.708 | 0.5 |
| kpm_frame_x2 | xd-naive | attack_L3 | 0.506 | 0.5 |
| kpm_frame_x2 | xd-naive | benign_L3 | 0.437 | 0.0 |
| kpm_frame_x2 | xd-naive | framed_benign_L3 | 0.437 | 0.0 |
| kpm_frame_x2 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x2 | xd-naive | t_L1_median | 14.6 | 12.8 |
| kpm_frame_x2 | xd-naive | t_L3_median | 22.9 | 21.8 |
| kpm_frame_x2 | xd-trust-v1 | attack_L1 | 0.685 | 1.0 |
| kpm_frame_x2 | xd-trust-v1 | attack_L3 | 0.404 | 0.25 |
| kpm_frame_x2 | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | xd-trust-v1 | framed_benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | xd-trust-v1 | integrity_tampered | 0.728 | 0.75 |
| kpm_frame_x2 | xd-trust-v1 | t_L1_median | 15.6 | 13.9 |
| kpm_frame_x2 | xd-trust-v1 | t_L3_median | 24.9 | 21.8 |
| kpm_frame_x2 | xd-trust-v1 | t_integrity_median | 11.3 | 10.9 |
| kpm_frame_x2 | xd-trust-v2 | attack_L1 | 0.685 | 0.75 |
| kpm_frame_x2 | xd-trust-v2 | attack_L3 | 0.404 | 0.25 |
| kpm_frame_x2 | xd-trust-v2 | benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | xd-trust-v2 | framed_benign_L3 | 0.01 | 0.0 |
| kpm_frame_x2 | xd-trust-v2 | integrity_tampered | 0.728 | 0.5 |
| kpm_frame_x2 | xd-trust-v2 | t_L1_median | 15.6 | 13.6 |
| kpm_frame_x2 | xd-trust-v2 | t_L3_median | 24.9 | 22.6 |
| kpm_frame_x2 | xd-trust-v2 | t_integrity_median | 11.3 | 11.1 |
| kpm_frame_x5 | core-only | attack_L1 | 0.663 | 0.75 |
| kpm_frame_x5 | core-only | attack_L3 | 0.483 | 0.75 |
| kpm_frame_x5 | core-only | benign_L3 | 0.01 | 0.0 |
| kpm_frame_x5 | core-only | framed_benign_L3 | 0.01 | 0.0 |
| kpm_frame_x5 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x5 | core-only | t_L1_median | 17.5 | 12.4 |
| kpm_frame_x5 | core-only | t_L3_median | 24.3 | 21.4 |
| kpm_frame_x5 | ran-only | attack_L1 | 0.618 | 0.0 |
| kpm_frame_x5 | ran-only | attack_L3 | 0.416 | 0.0 |
| kpm_frame_x5 | ran-only | benign_L3 | 0.932 | 0.0 |
| kpm_frame_x5 | ran-only | framed_benign_L3 | 0.932 | 0.0 |
| kpm_frame_x5 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x5 | ran-only | t_L1_median | 13.8 | None |
| kpm_frame_x5 | ran-only | t_L3_median | 25.3 | None |
| kpm_frame_x5 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_frame_x5 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_frame_x5 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_frame_x5 | rules-v1 | framed_benign_L3 | None | 0.0 |
| kpm_frame_x5 | xd-naive | attack_L1 | 0.719 | 0.75 |
| kpm_frame_x5 | xd-naive | attack_L3 | 0.517 | 0.75 |
| kpm_frame_x5 | xd-naive | benign_L3 | 0.757 | 0.25 |
| kpm_frame_x5 | xd-naive | framed_benign_L3 | 0.757 | 0.25 |
| kpm_frame_x5 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_frame_x5 | xd-naive | t_L1_median | 13.9 | 14.8 |
| kpm_frame_x5 | xd-naive | t_L3_median | 22.7 | 23.8 |
| kpm_frame_x5 | xd-trust-v1 | attack_L1 | 0.663 | 0.5 |
| kpm_frame_x5 | xd-trust-v1 | attack_L3 | 0.449 | 0.5 |
| kpm_frame_x5 | xd-trust-v1 | benign_L3 | 0.019 | 0.0 |
| kpm_frame_x5 | xd-trust-v1 | framed_benign_L3 | 0.019 | 0.0 |
| kpm_frame_x5 | xd-trust-v1 | integrity_tampered | 1.0 | 1.0 |
| kpm_frame_x5 | xd-trust-v1 | t_L1_median | 15.6 | 11.8 |
| kpm_frame_x5 | xd-trust-v1 | t_L3_median | 24.3 | 20.8 |
| kpm_frame_x5 | xd-trust-v1 | t_integrity_median | 11.3 | 10.8 |
| kpm_frame_x5 | xd-trust-v2 | attack_L1 | 0.663 | 0.75 |
| kpm_frame_x5 | xd-trust-v2 | attack_L3 | 0.449 | 0.5 |
| kpm_frame_x5 | xd-trust-v2 | benign_L3 | 0.019 | 0.0 |
| kpm_frame_x5 | xd-trust-v2 | framed_benign_L3 | 0.019 | 0.0 |
| kpm_frame_x5 | xd-trust-v2 | integrity_tampered | 1.0 | 1.0 |
| kpm_frame_x5 | xd-trust-v2 | t_L1_median | 15.6 | 12.9 |
| kpm_frame_x5 | xd-trust-v2 | t_L3_median | 24.3 | 20.7 |
| kpm_frame_x5 | xd-trust-v2 | t_integrity_median | 11.3 | 15.4 |
| kpm_hide_x0.1 | core-only | attack_L1 | 0.663 | 0.75 |
| kpm_hide_x0.1 | core-only | attack_L3 | 0.483 | 0.5 |
| kpm_hide_x0.1 | core-only | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.1 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.1 | core-only | t_L1_median | 17.5 | 15.2 |
| kpm_hide_x0.1 | core-only | t_L3_median | 24.3 | 22.5 |
| kpm_hide_x0.1 | ran-only | attack_L1 | 0.0 | 0.0 |
| kpm_hide_x0.1 | ran-only | attack_L3 | 0.0 | 0.0 |
| kpm_hide_x0.1 | ran-only | benign_L3 | 0.019 | 0.5 |
| kpm_hide_x0.1 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.1 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_hide_x0.1 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_hide_x0.1 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_hide_x0.1 | xd-naive | attack_L1 | 0.798 | 0.75 |
| kpm_hide_x0.1 | xd-naive | attack_L3 | 0.64 | 0.5 |
| kpm_hide_x0.1 | xd-naive | benign_L3 | 0.019 | 0.0 |
| kpm_hide_x0.1 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.1 | xd-naive | t_L1_median | 16.0 | 11.7 |
| kpm_hide_x0.1 | xd-naive | t_L3_median | 24.4 | 20.6 |
| kpm_hide_x0.1 | xd-trust-v1 | attack_L1 | 0.674 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v1 | attack_L3 | 0.461 | 0.75 |
| kpm_hide_x0.1 | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.1 | xd-trust-v1 | integrity_tampered | 1.0 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v1 | t_L1_median | 17.6 | 20.7 |
| kpm_hide_x0.1 | xd-trust-v1 | t_L3_median | 24.3 | 21.9 |
| kpm_hide_x0.1 | xd-trust-v1 | t_integrity_median | 13.6 | 15.3 |
| kpm_hide_x0.1 | xd-trust-v2 | attack_L1 | 1.0 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v2 | attack_L3 | 0.989 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v2 | benign_L3 | 0.019 | 0.0 |
| kpm_hide_x0.1 | xd-trust-v2 | integrity_tampered | 1.0 | 1.0 |
| kpm_hide_x0.1 | xd-trust-v2 | t_L1_median | 15.1 | 13.7 |
| kpm_hide_x0.1 | xd-trust-v2 | t_L3_median | 24.1 | 22.7 |
| kpm_hide_x0.1 | xd-trust-v2 | t_integrity_median | 13.6 | 14.1 |
| kpm_hide_x0.33 | core-only | attack_L1 | 0.663 | 1.0 |
| kpm_hide_x0.33 | core-only | attack_L3 | 0.483 | 0.5 |
| kpm_hide_x0.33 | core-only | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.33 | core-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.33 | core-only | t_L1_median | 17.5 | 28.4 |
| kpm_hide_x0.33 | core-only | t_L3_median | 24.3 | 21.7 |
| kpm_hide_x0.33 | ran-only | attack_L1 | 0.0 | 0.0 |
| kpm_hide_x0.33 | ran-only | attack_L3 | 0.0 | 0.0 |
| kpm_hide_x0.33 | ran-only | benign_L3 | 0.019 | 0.5 |
| kpm_hide_x0.33 | ran-only | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.33 | rules-v1 | attack_L1 | None | 0.0 |
| kpm_hide_x0.33 | rules-v1 | attack_L3 | None | 0.0 |
| kpm_hide_x0.33 | rules-v1 | benign_L3 | None | 0.0 |
| kpm_hide_x0.33 | xd-naive | attack_L1 | 0.921 | 0.75 |
| kpm_hide_x0.33 | xd-naive | attack_L3 | 0.753 | 0.5 |
| kpm_hide_x0.33 | xd-naive | benign_L3 | 0.019 | 0.0 |
| kpm_hide_x0.33 | xd-naive | integrity_tampered | 0.0 | 0.0 |
| kpm_hide_x0.33 | xd-naive | t_L1_median | 15.6 | 12.8 |
| kpm_hide_x0.33 | xd-naive | t_L3_median | 24.1 | 21.7 |
| kpm_hide_x0.33 | xd-trust-v1 | attack_L1 | 0.742 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v1 | attack_L3 | 0.461 | 0.75 |
| kpm_hide_x0.33 | xd-trust-v1 | benign_L3 | 0.01 | 0.0 |
| kpm_hide_x0.33 | xd-trust-v1 | integrity_tampered | 0.989 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v1 | t_L1_median | 15.3 | 24.0 |
| kpm_hide_x0.33 | xd-trust-v1 | t_L3_median | 24.3 | 22.5 |
| kpm_hide_x0.33 | xd-trust-v1 | t_integrity_median | 16.3 | 18.0 |
| kpm_hide_x0.33 | xd-trust-v2 | attack_L1 | 1.0 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v2 | attack_L3 | 0.966 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v2 | benign_L3 | 0.019 | 0.0 |
| kpm_hide_x0.33 | xd-trust-v2 | integrity_tampered | 0.989 | 1.0 |
| kpm_hide_x0.33 | xd-trust-v2 | t_L1_median | 15.6 | 15.7 |
| kpm_hide_x0.33 | xd-trust-v2 | t_L3_median | 24.4 | 24.7 |
| kpm_hide_x0.33 | xd-trust-v2 | t_integrity_median | 16.3 | 16.1 |
