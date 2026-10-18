# e3-reconnect — 20261006-005453_e3-reconnect_check

E3 - attacker that reconnects. UE1 floods until it reaches level 3 (or the
phase ends), then re-attaches (new PDU session, new UE ID) and floods again.
Compares no defense, RAN layer only and both layers. Shortened ladder
(20/30/240/240 s, probation 120 s) so that level 3 is reachable in one run;
report the timing with the results.

Runs: two-layer 1/1 ok

| metric | two-layer |
|---|---|
| attacker_t_level1_s | 4.18 ± 0 (n=1) |
| attacker_t_level3_s | 244 ± 0 (n=1) |
| attacker_t_upf_block_s | 244 ± 0 (n=1) |
| attacker_max_level | 3 ± 0 (n=1) |
| attacker_delivered_ratio_attack | 0.138 ± 0 (n=1) |
| attacker_dn_ul_mbps_attack | 1.44 ± 0 (n=1) |
| attacker_dn_ul_mbps_after_reconnect | 0.33 ± 0 (n=1) |
| attacker_dn_ul_mbytes_after_reconnect | 2.48 ± 0 (n=1) |
| attacker_upf_drop_ul_mbytes | 0 ± 0 (n=1) |
| benign_delivered_ratio_attack | 0.999 ± 0 (n=1) |
| benign_loss_pct_attack | 0.01 ± 0 (n=1) |
| benign_max_level | 0 ± 0 (n=1) |

Per phase (mean over runs), direction with offered traffic: offered / delivered / at DN (Mbit/s) · KPM / URR (kbit/s) · max level

| variant | phase | ue1 | ue2 |
|---|---|---|---|
| two-layer | baseline | UL 1.05 / 1.05 / 1.04 · 1074 / 1099 · L0 | UL 1.05 / 1.05 / 1.04 · 1071 / 1082 · L0 |
| two-layer | attack | UL 10.5 / 1.45 / 1.44 · 1470 / 1457 · L2 | UL 1.05 / 1.05 / 1.05 · 1074 / 1103 · L0 |
| two-layer | reconnect | UL 10.5 / 0.332 / 0.33 · 3992 / 290 · L3 | UL 1.05 / 1.05 / 1.05 · 1074 / 1105 · L0 |
| two-layer | cooldown | UL 0 / – / 0 · – / 0 · L3 | UL 1.05 / 1.05 / 1.04 · 1072 / 1079 · L0 |
