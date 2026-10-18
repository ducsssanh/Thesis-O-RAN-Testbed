# ingest-two-sources — 20261018-123100_ingest-two-sources_cl2

Data path check (~7 min): the xApp receives KPM (gNB, E2) and URR (eBPF
UPF, PFCP -> SMF -> producer -> A1-EI -> adapter) for each SUPI, every
second, complete and bound to the right UE, through an idle period, UL and
DL traffic, swapped rates and a UE re-attach. Detection off (no action
shapes the traffic); the xApp still builds the feature vectors. The two
UEs send 4x apart so a swapped SUPI binding shows as a ~4x volume error.
Grade: python3 scripts/k8s/exp/ingest_check.py <campaign dir>

Runs: detection-off 1/1 ok

| metric | detection-off |
|---|---|
| benign_max_level | 0 ± 0 (n=1) |
| benign_delivered_ratio_baseline | 1 ± 0 (n=1) |

Per phase (mean over runs), direction with offered traffic: offered / delivered / at DN (Mbit/s) · KPM / URR (kbit/s) · max level

| variant | phase | ue1 | ue2 |
|---|---|---|---|
| detection-off | idle | UL 0 / – / 0 · 0.011 / 0.015 · L0 | UL 0 / – / 0 · 0.011 / 0.015 · L0 |
| detection-off | ul-4x | UL 3.15 / 3.15 / 3.13 · 3223 / 3301 · L0 | UL 0.75 / 0.75 / 0.748 · 768 / 785 · L0 |
| detection-off | dl-4x | DL 6.29 / 6.29 / 6.25 · 6442 / 6690 · L0 | DL 1.5 / 1.5 / 1.49 · 1534 / 1612 · L0 |
| detection-off | ul-swapped | UL 0.75 / 0.75 / 0.751 · 768 / 788 · L0 | UL 3.15 / 3.14 / 3.15 · 3219 / 3269 · L0 |
| detection-off | reconnect | UL 0.75 / 0.75 / 0.744 · 768 / 783 · L0 | UL 2.1 / 2.1 / 2.08 · 2146 / 2220 · L0 |
