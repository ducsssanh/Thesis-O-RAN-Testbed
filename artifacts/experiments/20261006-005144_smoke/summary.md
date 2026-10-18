# smoke — 20261006-005144_smoke

Pipeline check (~2 min): benign traffic only, both layers on. Every record
type must be exported and the metrics computed; no evidence expected.

Runs: two-layer 1/1 ok

| metric | two-layer |
|---|---|
| benign_delivered_ratio_baseline | 1.05 ± 0 (n=1) |
| benign_max_level | 0 ± 0 (n=1) |
| benign_evidence | 0 ± 0 (n=1) |

Per phase (mean over runs), direction with offered traffic: offered / delivered / at DN (Mbit/s) · KPM / URR (kbit/s) · max level

| variant | phase | ue1 | ue2 |
|---|---|---|---|
| two-layer | baseline | UL 1 / 1.05 / 1.04 · 1073 / 1121 · L0 | UL 1 / 1.05 / 1.04 · 1073 / 1086 · L0 |
| two-layer | dl | DL 2 / 2.1 / 2.05 · 2148 / 2249 · L0 | DL 2 / 2.09 / 2.05 · 2147 / 2247 · L0 |
