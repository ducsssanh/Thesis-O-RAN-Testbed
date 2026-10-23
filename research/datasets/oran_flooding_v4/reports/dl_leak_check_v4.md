# Indirect-DL leak check through RAN UL (v4)

Rows: active, non-guard, URR UL > 10 kbps (n = 54857). AUC = univariate ROC-AUC of the ratio for MALICIOUS vs BENIGN; 0.5 = no signal, flag if |AUC − 0.5| > 0.1.

## Overall

| ratio | median BEN | median MAL | AUC | AUC excl. icmp control |
|---|---:|---:|---:|---:|
| `prb_per_kbps` | 0.04908 | 0.05309 | 0.525 | 0.525 |
| `thp_per_urr` | 0.9484 | 0.9415 | 0.501 | 0.503 |

## `prb_per_kbps` by load × victim_mode

| load | victim | n | median BEN | median MAL | AUC |
|---:|---|---:|---:|---:|---:|
| 0.2 | responsive | 2409 | 0.09085 | 0.1061 | 0.64 |
| 0.2 | silent | 2318 | 0.09323 | 0.1062 | 0.635 |
| 0.4 | responsive | 9589 | 0.06324 | 0.0648 | 0.52 |
| 0.4 | silent | 8613 | 0.06375 | 0.06528 | 0.52 |
| 0.6 | responsive | 2352 | 0.06991 | 0.05115 | 0.408 |
| 0.6 | silent | 2402 | 0.05109 | 0.04967 | 0.451 |
| 0.8 | responsive | 9704 | 0.03947 | 0.0401 | 0.533 |
| 0.8 | silent | 6229 | 0.03869 | 0.03955 | 0.53 |
| 1.2 | responsive | 5697 | 0.02841 | 0.02851 | 0.516 |
| 1.2 | silent | 5544 | 0.02897 | 0.02899 | 0.519 |

## `thp_per_urr` by load × victim_mode

| load | victim | n | median BEN | median MAL | AUC |
|---:|---|---:|---:|---:|---:|
| 0.2 | responsive | 2409 | 0.8664 | 0.9147 | 0.592 |
| 0.2 | silent | 2318 | 0.8779 | 0.9257 | 0.6 |
| 0.4 | responsive | 9589 | 0.9336 | 0.9309 | 0.512 |
| 0.4 | silent | 8613 | 0.9435 | 0.9402 | 0.505 |
| 0.6 | responsive | 2352 | 0.9042 | 0.9223 | 0.538 |
| 0.6 | silent | 2402 | 0.8975 | 0.9285 | 0.565 |
| 0.8 | responsive | 9704 | 0.9646 | 0.945 | 0.476 |
| 0.8 | silent | 6229 | 0.9682 | 0.9503 | 0.473 |
| 1.2 | responsive | 5697 | 0.9718 | 0.9563 | 0.475 |
| 1.2 | silent | 5544 | 0.9678 | 0.9553 | 0.478 |

## AUC per meta_pair

| pair | `prb_per_kbps` | `thp_per_urr` |
|---|---:|---:|
| dns_flood~dns_heavy | 0.577 | 0.734 |
| fanout_udp~fanout_benign | 0.485 | 0.464 |
| icmp_flood~icmp_ping | 0.498 | 0.497 |
| mimicry_udp~udp_nofeedback | 0.566 | 0.532 |
| pulsing_udp~onoff_pareto | 0.622 | 0.507 |
| syn_flood~tcp_shortconn | 0.407 | 0.531 |
| udp_flood~udp_bidir | 0.487 | 0.458 |

**Trigger (|AUC − 0.5| > 0.1 overall, excl. control): NO** — RAN UL features kept as is
