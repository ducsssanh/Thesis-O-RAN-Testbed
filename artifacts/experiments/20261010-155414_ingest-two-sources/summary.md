# ingest-two-sources — 20261010-155414_ingest-two-sources

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
| detection-off | idle | UL 0 / – / 0 · 0.011 / 0.029 · L0 | UL 0 / – / 0 · 0.011 / 0.029 · L0 |
| detection-off | ul-4x | UL 3.15 / 3.14 / 3.14 · 3254 / 3319 · L0 | UL 0.75 / 0.75 / 0.749 · 770 / 793 · L0 |
| detection-off | dl-4x | DL 6.29 / 6.28 / 6.28 · 6442 / 6634 · L0 | DL 1.5 / 1.49 / 1.5 · 1533 / 1585 · L0 |
| detection-off | ul-swapped | UL 0.75 / 0.75 / 0.75 · 768 / 801 · L0 | UL 3.15 / 3.14 / 3.14 · 3219 / 3322 · L0 |
| detection-off | reconnect | UL 0.75 / 0.75 / 0.748 · 769 / 793 · L0 | UL 2.1 / 2.1 / 2.1 · 2146 / 2207 · L0 |
