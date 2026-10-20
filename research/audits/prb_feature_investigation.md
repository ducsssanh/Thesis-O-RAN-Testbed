# PRB vs ue_cell_ul_share Investigation (Phase II/V)

Date: 2026-10-19. Evidence from raw CSV headers under `data/NCSRD_5GDDOS_V3/`
and `scripts/ml/prep_ncsrd.py`.

## 1. What `ue_cell_ul_share` actually is (traced, not inferred)
From `prep_ncsrd.py:120-126` (`cell_share`):

```
bucket           = _time floored to 5 s
cell_ul_kbps     = sum over (cell_id, bucket) of ran_ul_kbps   # = ul_bitrate/1000
ue_cell_ul_share = ran_ul_kbps / max(cell_ul_kbps, 1e-6)
```

- **It is a TRAFFIC-THROUGHPUT share, not a PRB share.** Numerator and
  denominator are both `ul_bitrate` (RAN-reported UE uplink bit-rate), never a
  radio-resource measurement.
- Level: **UE / cell**. Denominator: sum of UE UL bit-rates in the same cell and
  5 s bucket. Zero-traffic guard: `max(., 1e-6)`.
- It does **not** measure PRB allocation, scheduling, or spectral occupancy. A UE
  on poor radio can consume many PRBs for little throughput and still show a small
  `ue_cell_ul_share`, and vice-versa.

## 2. Is real PRB data available? NO per-UE; cell-level proxy exists uncollected

Searched every NCSRD CSV header for `prb|rru|resource`:
- `amari_ue_data_*` (the per-UE file we train on): **no PRB column**. Radio
  columns present but unused include `ul_path_loss, ul_phr, ul_rank, ul_n_layer,
  dl_tx, ul_tx, epre, ri, turbo_decoder_*`.
- `enb_counters_data_*` (per-cell, separate file, **not currently joined**) has
  Amarisoft resource-utilisation proxies **per cell**:
  `cell_X_ul_use_avg/max/min`, `cell_X_dl_use_avg/max/min` (fraction of
  radio resource in use ≈ PRB utilisation), plus `cell_X_ul_sched_users_*`,
  `cell_X_drb_count_*`, `cell_X_ue_active_count_*`, `cell_X_ul_gbr_use_*`.
- `mme_counters.csv`: only NGAP/PDU-session message counters, no PRB.

So there is **no true per-UE PRB** anywhere in NCSRD, and **no per-UE PRB can be
derived** from it. There is a **cell-level** utilisation proxy, in a different
file at a different sampling cadence, which we do not yet ingest.

## 3. Classification of each requested PRB feature

| Requested | Status in NCSRD | Note |
|---|---|---|
| UL/DL total cell PRB utilisation | **2 — supported, not collected** | `cell_X_ul_use_*`/`dl_use_*` in `enb_counters`, needs time-join |
| `RRU.PrbTotUl/Dl`, `PrbUsedUl`, `PrbAvailUl` | 5 — unavailable | Amarisoft names differ; closest proxy = `*_use_*` |
| Per-UE UL PRB allocation / share | **5 — unavailable** | no per-UE PRB in dataset, not derivable |
| Cell sched users / active UEs / DRB count | 2 — supported, not collected | congestion context, per cell |
| Scheduling / radio condition per UE | 3 — derivable | `ul_mcs, cqi, pusch_snr, ul_path_loss, ul_phr` (some already used) |

## 4. Testbed side (OAI / FlexRIC) — honest feasibility note
This is a dataset audit; the testbed claim needs its own check, but to set
expectations for the paper:
- **Do not assume** an xApp reads per-UE PRB over standardised E2SM-KPM just
  because the measurement is standardised — the DU must actually expose it.
- UPF/URR telemetry gives **no** RAN PRB (different plane). Keep RAN-PRB and
  core-volume features clearly separated by source in the paper.
- Per-UE PRB from OAI needs explicit DU instrumentation; treat as "requires RAN
  instrumentation" until verified on the live gNB.

## 5. What this means for feature engineering (Phase V plan)
- **Feature Set A** = current 16 (traffic + residual + radio quality). Baseline.
- **Feature Set B** = A + **cell-level** PRB-utilisation context
  (`cell_ul_use`, `ul_sched_users`, `ue_active_count`) time-joined from
  `enb_counters`. This is the *only* genuine PRB-ish signal we can add from NCSRD,
  and it is **context, not per-UE** — must be labelled as such.
- **Feature Set C** (per-UE PRB) is **not possible on NCSRD**; defer to testbed.
- **Feature Set D** (temporal PRB deltas) only meaningful once B is joined.

**Rule honoured:** no synthetic PRB values will be fabricated or presented as
measured radio-resource consumption. Set C stays empty until real per-UE PRB is
measured on the testbed.

## 6. Feature Set B evaluated — marginal, negative (added 2026-10-19)
Built `scripts/ml/prep_ncsrd_v3.py` (v2 + cell-use from enb_counters, merge_asof
by time per cell; cell_id==2 → 0) and evaluated:

| held-out | best AP, Set A (16) | best AP, Set B (20) |
|---|---|---|
| DNS | 0.956 | 0.973 (+0.017) |
| GTP-U | 0.299 | 0.346 (+0.047) |

The added `cell_ul_use/dl_use/ul_sched_users/ue_active` features **do not enter the
top-8 RandomForest importances**. Cell-level PRB context is too coarse to help
per-UE detection; it is **not** adopted as a default. Per-UE PRB (testbed only)
remains the open question. See `reports/high_load_benign_analysis.md`.
