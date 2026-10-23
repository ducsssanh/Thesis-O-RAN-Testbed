# v4 UL-only baselines (test = 18 held-out runs; threshold frozen on val at benign FPR 0.01)

Negative control icmp_flood~icmp_ping is excluded from training, headline and macro; its AUC is reported alone (expected ~0.5). Brackets = 95% bootstrap CI by run.

| model | ROC-AUC | PR-AUC | TPR@FPR1% | FPR | pair macro AUC | mimicry | pulsing | icmp control | idle FPR (gated) | TTD med/p90 s | benign phases alarmed (gated) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nuisance (meta only) | 0.4926 [0.4452–0.5433] | 0.4801 [0.4058–0.5599] | 0.0062 [0.0–0.0172] | 0.0026 | 0.5023 [0.4366–0.5619] | 0.3897 | 0.5762 | 0.4612 | 0.0 (0.0) | 63.0/63.2 | 0.0291 (0.0291) |
| UL volume (kbps, rolling) | 0.8634 [0.82–0.9037] | 0.8524 [0.784–0.9051] | 0.2944 [0.2142–0.382] | 0.0197 | 0.8745 [0.844–0.9095] | 0.8561 | 0.9412 | 0.4927 | 0.0007 (0.0) | 15.0/33.3 | 0.1262 (0.1262) |
| per-second UL (1 s) | 0.7897 [0.7175–0.8558] | 0.7887 [0.7132–0.8548] | 0.2879 [0.1904–0.4032] | 0.0169 | 0.7701 [0.7489–0.8123] | 0.6784 | 0.7215 | 0.5135 | 0.0 (0.0) | 5.5/27.4 | 0.2427 (0.233) |
| GBDT rolling RAN-UL | 0.8654 [0.8102–0.9076] | 0.8612 [0.7934–0.91] | 0.3241 [0.2375–0.4276] | 0.0104 | 0.8836 [0.8635–0.9234] | 0.8769 | 0.9543 | 0.6142 | 0.121 (0.0358) | 11.6/32.5 | 0.2039 (0.1553) |
| GBDT rolling RAN-UL no PRB | 0.8559 [0.8056–0.899] | 0.8529 [0.7866–0.9027] | 0.3141 [0.2285–0.4012] | 0.0152 | 0.8857 [0.8629–0.9205] | 0.8326 | 0.9654 | 0.5609 | 0.1596 (0.0212) | 11.5/25.9 | 0.1748 (0.1553) |
| GBDT rolling URR-UL | 0.86 [0.8041–0.9091] | 0.852 [0.7632–0.9152] | 0.206 [0.1345–0.287] | 0.0075 | 0.8555 [0.7996–0.9093] | 0.8348 | 0.804 | 0.534 | 0.0014 (0.0003) | 19.8/48.7 | 0.0388 (0.0388) |
| GBDT rolling prof-UL | 0.8732 [0.8114–0.9236] | 0.8715 [0.7931–0.9267] | 0.3682 [0.2643–0.4906] | 0.0089 | 0.8701 [0.8184–0.9046] | 0.8199 | 0.9077 | 0.4461 | 0.0 (0.0) | 14.8/38.3 | 0.0874 (0.0874) |
| GBDT rolling URR+prof (UL) | 0.9076 [0.8614–0.9447] | 0.9096 [0.8465–0.9516] | 0.4274 [0.3263–0.5371] | 0.0055 | 0.9144 [0.869–0.9429] | 0.8577 | 0.9405 | 0.4725 | 0.0066 (0.0) | 14.2/24.9 | 0.0583 (0.0583) |
| GBDT rolling cross-domain UL | 0.9298 [0.8944–0.9606] | 0.9238 [0.8661–0.9613] | 0.4674 [0.377–0.5643] | 0.0164 | 0.9362 [0.9168–0.9568] | 0.8728 | 0.9744 | 0.4954 | 0.2038 (0.0035) | 12.6/25.3 | 0.2039 (0.1165) |

## Split-seed repeat (3 run splits, mean ± std)

| model | ROC-AUC | PR-AUC | TPR@FPR1% | pair macro | mimicry | pulsing | icmp control |
|---|---:|---:|---:|---:|---:|---:|---:|
| nuisance (meta only) | 0.492 ± 0.014 | 0.480 ± 0.020 | 0.017 ± 0.011 | 0.489 ± 0.010 | 0.463 ± 0.061 | 0.497 ± 0.057 | 0.528 ± 0.052 |
| UL volume (kbps, rolling) | 0.892 ± 0.020 | 0.887 ± 0.025 | 0.331 ± 0.052 | 0.899 ± 0.018 | 0.866 ± 0.042 | 0.955 ± 0.010 | 0.498 ± 0.004 |
| per-second UL (1 s) | 0.794 ± 0.003 | 0.794 ± 0.009 | 0.263 ± 0.023 | 0.769 ± 0.017 | 0.625 ± 0.076 | 0.805 ± 0.077 | 0.515 ± 0.010 |
| GBDT rolling RAN-UL | 0.905 ± 0.028 | 0.905 ± 0.032 | 0.341 ± 0.012 | 0.911 ± 0.020 | 0.910 ± 0.025 | 0.968 ± 0.011 | 0.568 ± 0.062 |
| GBDT rolling RAN-UL no PRB | 0.891 ± 0.025 | 0.890 ± 0.026 | 0.402 ± 0.062 | 0.909 ± 0.018 | 0.857 ± 0.037 | 0.972 ± 0.007 | 0.507 ± 0.044 |
| GBDT rolling URR-UL | 0.846 ± 0.013 | 0.837 ± 0.021 | 0.279 ± 0.052 | 0.827 ± 0.022 | 0.760 ± 0.085 | 0.773 ± 0.080 | 0.461 ± 0.058 |
| GBDT rolling prof-UL | 0.875 ± 0.006 | 0.871 ± 0.012 | 0.347 ± 0.049 | 0.875 ± 0.016 | 0.762 ± 0.113 | 0.902 ± 0.038 | 0.499 ± 0.056 |
| GBDT rolling URR+prof (UL) | 0.900 ± 0.009 | 0.896 ± 0.017 | 0.388 ± 0.028 | 0.900 ± 0.018 | 0.792 ± 0.096 | 0.905 ± 0.060 | 0.492 ± 0.021 |
| GBDT rolling cross-domain UL | 0.932 ± 0.012 | 0.929 ± 0.014 | 0.496 ± 0.045 | 0.935 ± 0.010 | 0.864 ± 0.061 | 0.967 ± 0.019 | 0.534 ± 0.028 |
| APPENDIX GBDT rolling incl. DL | 0.994 ± 0.000 | 0.993 ± 0.001 | 0.667 ± 0.383 | 0.987 ± 0.005 | 0.926 ± 0.027 | 1.000 ± 0.000 | 0.555 ± 0.007 |

## Transfers (GBDT rolling cross-domain UL)

| protocol | n | ROC-AUC | PR-AUC | TPR | FPR | pair macro | mimicry | pulsing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| leave-UE-out ue1->ue2 | 3926 | 0.9113 | 0.8957 | 0.4228 | 0.0256 | 0.888 | 0.8662 | 0.8823 |
| leave-UE-out ue2->ue1 | 3926 | 0.8703 | 0.8423 | 0.3698 | 0.0598 | 0.9136 | 0.868 | 0.9245 |
| leave-generator-out pacer | 3464 | 0.6731 | 0.7381 | 0.6388 | 0.4299 | 0.6273 | 0.4559 | 0.637 |
| leave-generator-out hping | 2483 | 0.6379 | 0.659 | 0.1056 | 0.0189 | 0.6516 | None | None |
| leave-generator-out iperf | 574 | 0.7932 | 0.8315 | 0.1986 | 0.0035 | 0.7932 | None | None |
| victim silent->responsive | 3970 | 0.7979 | 0.8149 | 0.501 | 0.084 | 0.8158 | 0.8291 | 0.9542 |
| victim responsive->silent | 3882 | 0.9409 | 0.9336 | 0.3671 | 0.0009 | 0.8805 | 0.841 | 0.6828 |

## Per-pair AUC (test)

| set | dns_flood~dns_heavy | fanout_udp~fanout_benign | icmp_flood~icmp_ping | mimicry_udp~udp_nofeedback | pulsing_udp~onoff_pareto | syn_flood~tcp_shortconn | udp_flood~udp_bidir |
|---|---:|---:|---:|---:|---:|---:|---:|
| nuisance (meta only) | 0.4232 | 0.588 | 0.4612 | 0.3897 | 0.5762 | 0.5045 | 0.5319 |
| UL volume (kbps, rolling) | 0.9755 | 0.7191 | 0.4927 | 0.8561 | 0.9412 | 0.9957 | 0.7596 |
| per-second UL (1 s) | 1.0 | 0.643 | 0.5135 | 0.6784 | 0.7215 | 1.0 | 0.5774 |
| GBDT rolling RAN-UL | 0.9753 | 0.7247 | 0.6142 | 0.8769 | 0.9543 | 0.9979 | 0.7724 |
| GBDT rolling RAN-UL no PRB | 0.9428 | 0.8052 | 0.5609 | 0.8326 | 0.9654 | 0.9942 | 0.7741 |
| GBDT rolling URR-UL | 0.9922 | 0.7474 | 0.534 | 0.8348 | 0.804 | 0.9993 | 0.7555 |
| GBDT rolling prof-UL | 0.9998 | 0.7725 | 0.4461 | 0.8199 | 0.9077 | 1.0 | 0.7205 |
| GBDT rolling URR+prof (UL) | 0.9996 | 0.8635 | 0.4725 | 0.8577 | 0.9405 | 1.0 | 0.8253 |
| GBDT rolling cross-domain UL | 1.0 | 0.9036 | 0.4954 | 0.8728 | 0.9744 | 1.0 | 0.8667 |
| APPENDIX GBDT rolling incl. DL | 1.0 | 0.999 | 0.5645 | 0.8888 | 1.0 | 1.0 | 0.9944 |

## GBDT rolling cross-domain UL breakdowns (test)
- victim_mode: {np.str_('responsive'): {'tpr': 0.4085, 'fpr': 0.03}, np.str_('silent'): {'tpr': 0.532, 'fpr': 0.0033}}
- dual-use backend AUC: {'pacer': 0.9352, 'hping': 0.8536, 'iperf': 0.9081}
- UE AUC: {np.str_('ue1'): 0.9314, np.str_('ue2'): 0.9277}
- TPR by attack_active: {'on': 0.4751, 'off': 0.3592}
- TTD: {'attack_phases': 89, 'detected': 75, 'median_s': 12.6, 'p90_s': 25.3}

## Appendix — with DL (caveat: designed benign DL feedback is a near-label proxy)

| model | ROC-AUC | PR-AUC | TPR@FPR1% | FPR | pair macro AUC | mimicry | pulsing | icmp control | idle FPR (gated) | TTD med/p90 s | benign phases alarmed (gated) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| APPENDIX GBDT rolling incl. DL | 0.9947 [0.9877–0.9995] | 0.9938 [0.9863–0.9995] | 0.9378 [0.8941–0.9754] | 0.0296 | 0.9804 [0.9596–0.9989] | 0.8888 | 1.0 | 0.5645 | 0.3606 (0.0615) | 0.8/12.0 | 0.4951 (0.0583) |
