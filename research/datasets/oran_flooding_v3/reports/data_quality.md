# Testbed O-RAN flooding dataset — data quality

Campaigns: 12, OK runs: 50, independent (campaign,run,supi) sessions: 100
Records (per-SUPI-per-second): 16812  (BENIGN 12484 / MALICIOUS 4328)

Ground truth is experimental control only (a UE is MALICIOUS iff it ran an
attack flow in that phase); never derived from volume or PRB.

## Label / family distribution
- BENIGN: 12484
- MALICIOUS/dns_flood: 540
- MALICIOUS/fanout_udp: 901
- MALICIOUS/icmp_flood: 542
- MALICIOUS/syn_flood: 541
- MALICIOUS/udp_flood: 1804

## Attack generator validity (achieved activity per family)
A malicious family is kept only if its generator actually produced traffic
(> 10% of rows with profiler pps > 5). This is a validity filter on the
experimental CONTROL, not volume-based labelling of rows.
| family | rows | active rows | kept |
|---|---:|---:|---|
| dns_flood | 540 | 98% | yes |
| fanout_udp | 901 | 99% | yes |
| frag_flood | 180 | 0% | no — EXCLUDED |
| icmp_flood | 542 | 98% | yes |
| syn_flood | 541 | 98% | yes |
| udp_flood | 1804 | 98% | yes |

**Excluded families (generator produced no traffic): frag_flood.** hping3 `-f` fragmented flood emits only a token fragment over the RFsim tunnel, so frag_flood never became a real attack condition; its rows are dropped rather than kept as mislabelled idle traffic. Logged as a limitation; a v3 would generate IP fragmentation with nping/scapy.

## Missingness leak audit (presence rate by class)
A feature present for one class but absent for the other leaks the label via its mask.
Data-driven: any feature with a presence gap > 20 pts is flagged LEAK-RISK and
must be dropped by the modelling step (none expected in v2).
| feature | benign present | malicious present | verdict |
|---|---:|---:|---|
| has_prof | 100% | 100% | ok |
| has_urr | 100% | 100% | ok |

**Leak-risk features: none — all features present for both classes**

## Benign vs malicious LOAD overlap (thp_ul_kbps bands — KPM / RAN, dense both classes)
Overlap is the point: both classes occupy the same volume bands, so volume alone cannot separate them.
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 4065 | 68 |
| 100-300 | 243 | 128 |
| 300-600 | 6463 | 2231 |
| 600-1000 | 584 | 1500 |
| 1000-2000 | 1128 | 401 |
| 2000-inf | 1 | 0 |

## Benign vs malicious LOAD overlap (urr_ul_kbps bands — PFCP/URR / core, dense both classes)
Same overlap holds on the standard 3GPP core-volume counter, confirming the claim is not an artefact of one measurement layer.
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 4040 | 66 |
| 100-300 | 408 | 112 |
| 300-600 | 6318 | 1944 |
| 600-1000 | 397 | 1703 |
| 1000-2000 | 1300 | 503 |
| 2000-inf | 2 | 0 |

## Benign vs malicious PACKET-SIZE overlap (prof_ul_mean_bytes bands)
By design both classes span small and large packets (small-packet benign controls + large-packet flood variants), so mean packet size alone is not a label shortcut.
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 3507 | 607 |
| 100-300 | 1062 | 2838 |
| 300-800 | 0 | 0 |
| 800-1200 | 15 | 0 |
| 1200-inf | 7896 | 883 |
