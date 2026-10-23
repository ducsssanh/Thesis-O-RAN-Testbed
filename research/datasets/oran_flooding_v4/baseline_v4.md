# v4 baselines (test split, 18 runs; threshold frozen on val at benign FPR 0.01)

| model | ROC-AUC | PR-AUC | TPR@FPR1%val | FPR test | idle FPR | TTD med/p90 s | benign phases alarmed |
|---|---:|---:|---:|---:|---:|---:|---:|
| nuisance (meta only) | 0.4863 | 0.4723 | 0.0147 | 0.0122 | 0.0 | 57.9/71.4 | 0.0522 |
| UL mean kbps only | 0.7588 | 0.7229 | 0.0397 | 0.0011 | 0.0 | 15.6/63.7 | 0.0435 |
| UL kbps (mean/std/min/max/last) | 0.8181 | 0.806 | 0.1717 | 0.0027 | 0.0 | 14.4/50.8 | 0.0609 |
| DL kbps only | 0.9625 | 0.9556 | 0.5485 | 0.0137 | 0.0 | 11.4/27.6 | 0.1478 |
| volume only (kbps) | 0.9716 | 0.9675 | 0.6858 | 0.0171 | 0.0 | 11.3/15.6 | 0.0957 |
| all minus DL | 0.8675 | 0.8634 | 0.3013 | 0.008 | 0.0 | 13.6/32.0 | 0.087 |
| RAN (KPM) | 0.9714 | 0.9674 | 0.7157 | 0.0192 | 0.0 | 10.3/13.9 | 0.1478 |
| URR | 0.9659 | 0.9621 | 0.6228 | 0.0097 | 0.0 | 11.3/28.5 | 0.0783 |
| profiler (eBPF UPF) | 0.978 | 0.9765 | 0.7529 | 0.0116 | 0.0 | 9.6/14.1 | 0.2783 |
| RAN + URR | 0.974 | 0.9702 | 0.7005 | 0.0099 | 0.0362 | 10.3/16.0 | 0.087 |
| all (HGB) | 0.9807 | 0.9793 | 0.7522 | 0.0065 | 0.0028 | 11.1/13.8 | 0.0783 |
| all (logistic) | 0.9742 | 0.9708 | 0.7169 | 0.0186 | 0.2083 | 3.8/12.8 | 0.5478 |

## Per pair (all-HGB, test): AUC / TPR / FPR

| pair | AUC | TPR | FPR | n |
|---|---:|---:|---:|---:|
| benign_benign | None | None | 0.0 | 914 |
| both_attack | None | 0.8587 | None | 460 |
| dns_flood~dns_heavy | 1.0 | 1.0 | 0.0 | 1310 |
| fanout_udp~fanout_benign | 1.0 | 1.0 | 0.0 | 562 |
| icmp_flood~icmp_ping | 0.4811 | 0.0017 | 0.0172 | 1164 |
| mimicry_udp~udp_nofeedback | 0.8799 | 0.4307 | 0.0495 | 808 |
| pulsing_udp~onoff_pareto | 1.0 | 0.6948 | 0.0 | 616 |
| syn_flood~tcp_shortconn | 1.0 | 0.99 | 0.0 | 798 |
| udp_flood~udp_bidir | 0.9988 | 0.927 | 0.0008 | 2384 |

## Per pair AUC by feature set (test)

| set | benign_benign | both_attack | dns_flood~dns_heavy | fanout_udp~fanout_benign | icmp_flood~icmp_ping | mimicry_udp~udp_nofeedback | pulsing_udp~onoff_pareto | syn_flood~tcp_shortconn | udp_flood~udp_bidir |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nuisance (meta only) | None | None | 0.4136 | 0.583 | 0.4796 | 0.3908 | 0.5811 | 0.5042 | 0.5227 |
| UL mean kbps only | None | None | 0.9925 | 0.6578 | 0.4906 | 0.762 | 0.582 | 0.9795 | 0.685 |
| UL kbps (mean/std/min/max/last) | None | None | 0.9827 | 0.7412 | 0.5373 | 0.8148 | 0.982 | 0.9995 | 0.7069 |
| DL kbps only | None | None | 1.0 | 0.9712 | 0.467 | 0.7845 | 1.0 | 1.0 | 0.9807 |
| volume only (kbps) | None | None | 1.0 | 0.9749 | 0.4813 | 0.8578 | 1.0 | 1.0 | 0.9845 |
| all minus DL | None | None | 1.0 | 0.8636 | 0.5016 | 0.8489 | 0.9601 | 1.0 | 0.7706 |
| RAN (KPM) | None | None | 1.0 | 0.9789 | 0.4867 | 0.9031 | 1.0 | 1.0 | 0.9827 |
| URR | None | None | 1.0 | 0.9406 | 0.4869 | 0.7839 | 1.0 | 0.9999 | 0.9914 |
| profiler (eBPF UPF) | None | None | 1.0 | 1.0 | 0.4645 | 0.7781 | 1.0 | 1.0 | 0.9998 |
| RAN + URR | None | None | 1.0 | 0.9896 | 0.4781 | 0.8855 | 1.0 | 1.0 | 0.9865 |
| all (HGB) | None | None | 1.0 | 1.0 | 0.4811 | 0.8799 | 1.0 | 1.0 | 0.9988 |
| all (logistic) | None | None | 1.0 | 0.9495 | 0.5626 | 0.8452 | 1.0 | 1.0 | 0.9982 |

## all-HGB breakdowns (test)
- victim_mode: {np.str_('responsive'): {'tpr': 0.6087, 'fpr': 0.0088}, np.str_('silent'): {'tpr': 0.9347, 'fpr': 0.004}}
- dual-use backend AUC: {'pacer': 0.9874, 'hping': 0.9471, 'iperf': 1.0}
- UE AUC: {np.str_('ue1'): 0.979, np.str_('ue2'): 0.9825}
- TPR by attack_active: {'on': 0.7559, 'off': 0.6898}
- TTD: {'attack_phases': 101, 'detected': 88, 'median': 11.1, 'p90': 13.8}
