# Testbed O-RAN flooding dataset — data quality

Campaigns: 6, OK runs: 18, independent (campaign,run,supi) sessions: 36
Records (per-SUPI-per-second): 6164  (BENIGN 4721 / MALICIOUS 1443)

Ground truth is experimental control only (a UE is MALICIOUS iff it ran an
attack flow in that phase); never derived from volume or PRB.

## Label / family distribution
- BENIGN: 4721
- MALICIOUS/dns_flood: 180
- MALICIOUS/fanout_udp: 300
- MALICIOUS/icmp_flood: 180
- MALICIOUS/syn_flood: 181
- MALICIOUS/udp_flood: 602

## Attack generator validity (achieved activity per family)
A malicious family is kept only if its generator actually produced traffic
(> 10% of rows with profiler pps > 5). This is a validity filter on the
experimental CONTROL, not volume-based labelling of rows.
| family | rows | active rows | kept |
|---|---:|---:|---|
| dns_flood | 180 | 100% | yes |
| fanout_udp | 300 | 100% | yes |
| frag_flood | 180 | 0% | no — EXCLUDED |
| icmp_flood | 180 | 100% | yes |
| syn_flood | 181 | 100% | yes |
| udp_flood | 602 | 100% | yes |

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
| 0-100 | 1513 | 19 |
| 100-300 | 95 | 56 |
| 300-600 | 2504 | 692 |
| 600-1000 | 192 | 544 |
| 1000-2000 | 417 | 132 |
| 2000-inf | 0 | 0 |

## Benign vs malicious LOAD overlap (urr_ul_kbps bands — PFCP/URR / core, dense both classes)
Same overlap holds on the standard 3GPP core-volume counter, confirming the claim is not an artefact of one measurement layer.
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 1445 | 1 |
| 100-300 | 140 | 48 |
| 300-600 | 2503 | 631 |
| 600-1000 | 134 | 592 |
| 1000-2000 | 479 | 171 |
| 2000-inf | 1 | 0 |

## Benign vs malicious PACKET-SIZE overlap (prof_ul_mean_bytes bands)
By design both classes span small and large packets (small-packet benign controls + large-packet flood variants), so mean packet size alone is not a label shortcut.
| band | benign | malicious |
|---|---:|---:|
| 0-100 | 1260 | 181 |
| 100-300 | 360 | 962 |
| 300-800 | 0 | 0 |
| 800-1200 | 10 | 0 |
| 1200-inf | 3087 | 300 |
