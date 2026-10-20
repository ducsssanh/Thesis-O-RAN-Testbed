# Dataset & Pipeline Audit (Phase I overview)

Date: 2026-10-19. Scope: audit the existing ML pipeline (dataset → features →
split → LSTM → metrics → ranking) and reproduce the reported baseline. This file
is the index; see the companions for detail.

## Companion deliverables
- `baseline_verification.md` — all metrics recomputed; answers the 7 verification
  questions; the detection-vs-ranking ablation.
- `data_leakage_report.md` — UE-identity + overlapping-window leakage, effective
  sample size, label-source handling.
- `prb_feature_investigation.md` — what `ue_cell_ul_share` really is; PRB
  availability in NCSRD and the testbed.
- `feature_inventory.csv` — the 16 features traced to source code and raw columns.
- `scripts/` — `verify_baseline.py`, `leakage.py`, `share_ablation.py` (run with
  `.venv-ml/bin/python -I`, reproducible from committed artifacts).

## Pipeline dependency map (as-built)
```
data/NCSRD_5GDDOS_V3/amari_ue_data_merged_with_attack_number.csv  (231 MB, per-UE, ~5.14s)
        │   (+ summary_report.xlsx attack schedule, encoded in prep ATTACKERS dict)
        ▼
scripts/ml/prep_ncsrd.py
   load → relabel(schedule) → per_step(RAN & core rates, residual, segments)
        → cell_share → windows(W=6, stride 1, log1p rates) → split → zscore(train)
        ▼
artifacts/ml/{ncsrd (DNS held-out), ncsrd-timesplit}/windows.npz  (git-ignored)
        ▼
scripts/ml/train_lstm.py
   WindowLSTM: nn.LSTM(16,64,1) → Linear(64,1) → sigmoid = p_attack
   loss BCEWithLogitsLoss(pos_weight=neg/pos) ; Adam 1e-3 ; early stop on val AP
   rank = p_attack × ue_cell_ul_share (NOT learned)
        ▼
   model.pt, metrics.json, val_scores.npz
```

Unused raw signals available for later feature work: `ul_path_loss, ul_phr,
ul_rank, ul_n_layer, dl_tx, ul_tx, epre, ri, turbo_decoder_*` (per-UE) and the
whole `enb_counters_data_*` cell-level file (incl. `cell_*_ul_use_*` PRB proxy).

## Top findings (evidence-backed)
1. **Reported baseline reproduces exactly.** DNS held-out: AP 0.121, ROC 0.891,
   recall 0.54 / FPR 0.135 / precision 0.040 @0.5 (TP 755, FP 18070). Prevalence
   1.03%. PR-AUC = Average Precision (confirmed).
2. **The 0.97 "ranking precision" is a product artifact, not detection.** `p`
   alone AP 0.12 (its top-100 windows are all benign); `share` alone useless;
   only `p×share` reaches 0.97 — and it *reverses* to worse-than-`p` on the
   time-split. Detection does not generalise to unseen attacks.
3. **Attackers do not have high UL share** (DNS 0.27 vs benign 0.33; time-split
   0.08 vs 0.34). Any "high load ⇒ attacker" assumption is unsupported here.
4. **Severe leakage:** 9 UEs total, all in both splits; 73% of val windows sit
   within 26 s of a same-UE train window; ~5 attack episodes inflated to 11k
   positive windows by stride-1 overlap.
5. **Good practices to keep:** labels rebuilt from schedule (not leaky `attack`
   column); scaler fit on train only.
6. **PRB:** `ue_cell_ul_share` is traffic share, not PRB. No per-UE PRB in NCSRD;
   only a cell-level utilisation proxy, uncollected, in a separate file.

## Integrity-check status
Done: metric reproduction, AP-vs-trapezoidal, prevalence, FPR level, ranking-k
definition, UE-identity leakage, overlapping-window leakage, label-source,
scaler, PRB tracing. Open (next iteration): NaN/inf & constant-feature scan,
pairwise correlation/redundancy, per-feature train/val distribution shift,
transition-boundary label check → to be emitted as `dataset_statistics.json`.

## Prioritised next iterations (evidence-driven)
P1. **Fix the split** (segment-atomic group split + leave-one-attack-out /
    leave-one-UE-out) and **re-measure the baseline**. DONE (prep_ncsrd_v2.py):
    `segments_on_both_sides = 0`, the 73% overlap leak is eliminated.
P2. **Separate detector from prioritiser** (Phase III Stage A/B/C); evaluate
    detection and ranking independently; stop multiplying by share inside
    detection. IN PROGRESS: experiments.py reports P@k for `p` and `p*share`
    separately per model.
P3. **Tabular baselines** (LogReg, RandomForest, HistGB on window-aggregated
    features) — decides whether the LSTM earns its complexity. IN PROGRESS
    (experiments.py, results.csv).
P4. **Schema unification + testbed scenario-replay** (NEW, requested 2026-10-19):
    pretraining need NOT be restricted to shared features. Adopt a unified
    superset schema with a missing-mask, and generate a testbed-native dataset
    that reproduces NCSRD scenarios to collect the testbed-only features
    (packet-mix, URR, cell/per-UE PRB). Design + reproducible config delivered:
    `feature_schema_unification.md`, `research/configs/testbed_enrichment.yaml`.
    Capture itself runs on the live cluster (long-running) — not fabricated here.
P5. **Add cell-level PRB context** (Feature Set B) from enb_counters and ablate.
P6. **High-load-benign challenge set** — the core scientific test; produced by the
    P4 replay (`b_heavy_ul` held entirely in TEST), since NCSRD lacks legitimate
    high-load benign.
