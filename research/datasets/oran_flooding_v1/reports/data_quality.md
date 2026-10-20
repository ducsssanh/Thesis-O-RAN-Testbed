# Testbed O-RAN flooding dataset — data quality (v1)

Campaigns: 6, OK runs: 18, independent (campaign,run,supi) sessions: 36
Records (per-SUPI-per-second): 6338  (BENIGN 4718 / MALICIOUS 1620)

Ground truth is experimental control only (a UE is MALICIOUS iff it ran an
attack flow in that phase); never derived from volume or PRB.

## Label / family distribution
- BENIGN: 4718
- MALICIOUS/dns_flood: 180
- MALICIOUS/fanout_udp: 300
- MALICIOUS/frag_flood: 180
- MALICIOUS/icmp_flood: 180
- MALICIOUS/syn_flood: 180
- MALICIOUS/udp_flood: 600

## Missingness leak audit (presence rate by class)
A feature present for one class but absent for the other leaks the label via its mask.
| feature | benign present | malicious present | verdict |
|---|---:|---:|---|
| has_prof | 99% | 100% | ok |
| has_urr | 15% | 0% | ok |
| urr_ul_kbps | 15% | 0% | LEAK (excluded) |
| urr_dl_kbps | 15% | 0% | LEAK (excluded) |
| urr_ul_pps | 15% | 0% | LEAK (excluded) |
| urr_dl_pps | 15% | 0% | LEAK (excluded) |

## Benign vs malicious LOAD overlap (thp_ul_kbps bands — KPM, dense for both classes)
Overlap is the point: both classes occupy the same volume bands, so volume alone cannot separate them. (URR is not used here — it is sparse and confounded; see the leak audit.)
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 1506 | 194 |
| 100-300 | 89 | 15 |
| 300-600 | 2506 | 541 |
| 600-1000 | 166 | 422 |
| 1000-2000 | 451 | 448 |
| 2000-inf | 0 | 0 |

## Benign vs malicious PACKET-SIZE overlap (prof_ul_mean_bytes bands)
By design both classes span small and large packets (small-packet benign controls + large-packet flood variants), so mean packet size alone is not a label shortcut.
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 1271 | 373 |
| 100-300 | 356 | 949 |
| 300-800 | 0 | 0 |
| 800-1200 | 5 | 0 |
| 1200-inf | 3022 | 298 |
