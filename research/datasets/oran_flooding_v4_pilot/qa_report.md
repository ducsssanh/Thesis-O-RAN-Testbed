# v4 QA report — `research/datasets/oran_flooding_v4_pilot`

Rows: 522 · IDLE 258 · BENIGN 144 · MALICIOUS 120

## 1. Causality audit (independent of the builder)

| stream | rows checked | violations (arrival_ts > t) |
|---|---:|---:|
| kpm | 522 | **0** |
| urr | 520 | **0** |
| prof | 520 | **0** |

For comparison, the v3-style xApp join (`defense/features.jsonl`) of the same run: 524 rows, **1 (0.2%) used a future (+1 s) URR sample and 0 (0.0%) a future profiler sample** — the C5 leak the v4 build removes.

## 2. Data age (s) at the row's second

| stream | median | p90 | max | present % |
|---|---:|---:|---:|---:|
| kpm | 0.86 | 0.86 | 0.86 | 100.0 |
| urr | 2.25 | 3.24 | 4.09 | 95.2 |
| prof | 1.65 | 2.65 | 3.65 | 99.6 |

Presence by label (URR / profiler):

| label | URR % | prof % |
|---|---:|---:|
| BENIGN | 97.9 | 100.0 |
| IDLE | 92.6 | 99.2 |
| MALICIOUS | 97.5 | 100.0 |

## 3. Design balance (excl. IDLE)

```
label    BENIGN  MALICIOUS
meta_ue                   
ue1           0        120
ue2         144          0
```

P(malicious | UE): ue1 1.00, ue2 0.00

**C1 confound present** — ['ue1', 'ue2'] outside [0.45, 0.55]: label ≈ UE identity. Expected for a v3 scenario; v4 role-swapping campaign design (Phase 3) must fix it.

## 4. Achieved vs offered (DN, ±10%)

| phase | ue | offered Mbit/s | URR (IP) Mbit/s | DN payload Mbit/s | URR/offered | achieved_ok |
|---|---|---:|---:|---:|---:|---|
| mix-sm | ue1 | 1.0 | 1.049 | 0.6284 | 1.049 | yes |
| mix-sm | ue2 | 1.0 | 1.057 | 0.996 | 1.057 | yes |
| gap1 | ue2 | 0.3 | 0.328 | 0.2963 | 1.093 | yes |
| mix-lg | ue1 | 1.0 | 1.016 | 0.9567 | 1.016 | yes |
| mix-lg | ue2 | 1.0 | 1.047 | 0.9867 | 1.047 | yes |
| gap2 | ue2 | 0.3 | 0.321 | 0.2887 | 1.071 | yes |
| mix-fanout | ue1 | 1.0 | 1.031 | 0.6187 | 1.031 | yes |
| mix-fanout | ue2 | 1.0 | 1.049 | 0.9963 | 1.049 | yes |

achieved_ok: 8/8 phase-UE pairs (target ≥ 90%).
