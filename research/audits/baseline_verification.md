# Baseline Verification (Phase I)

Date: 2026-10-19. All numbers recomputed from saved artifacts with
`research/audits/scripts/verify_baseline.py` and `share_ablation.py`
(`.venv-ml/bin/python -I`). Nothing here is from memory — every figure is
reproduced from `val_scores.npz` / `windows.npz`.

## Artifacts verified
- `artifacts/ml/ncsrd/` — **leave-one-attack-out**, DNS held out (`--val-attack 4`).
- `artifacts/ml/ncsrd-timesplit/` — **time split** (`--val-attack 0`, last 20% by time).

## Answers to the 7 required verification questions

1. **PR-AUC = Average Precision**, not trapezoidal. `train_lstm.py` uses
   `sklearn.metrics.average_precision_score`. Confirmed numerically: DNS split
   AP = 0.1211 vs trapezoidal = 0.1205 (they differ, AP is what is reported).
2. **Which split / threshold produced each metric:**
   - PR-AUC / ROC-AUC are threshold-free, computed on the **DNS-held-out val set**.
   - Recall 0.54 / FPR 0.135 are at **threshold 0.5** on that same set.
   - The "0.62 PR-AUC" quoted earlier is the **time-split** set, a different split.
3. **FPR level: window-level**, not UE-level. Computed over all 133,887 benign
   validation *windows*. No UE-level or per-hour alert rate exists yet (gap).
4. **Ranking precision** = `rank_precision_at_positives`: take the top-k windows
   by `rank = p_attack × ue_cell_ul_share`, report the fraction that are positive.
5. **k = number of positives** in the val set (k = 1399 for the DNS split). So it
   is Precision@k with k = #positives, **window-level**, not UE-level.
6. **Prevalence confirmed:** DNS split 1399/135286 = **1.034%** (95.7:1), *not*
   the 1.67% of the full dataset (that is before the split). Time split: 3.55%.
7. **Leakage: yes, material** — see `data_leakage_report.md`. Headline numbers are
   inflated by UE-identity sharing and overlapping windows.

## Reproduced metric table

| | DNS held-out | time-split |
|---|---|---|
| n / positives | 135286 / 1399 | 138081 / 4896 |
| prevalence | 1.03% | 3.55% |
| AP (PR-AUC) | **0.1211** | **0.6223** |
| ROC-AUC | 0.8908 | 0.8847 |
| recall @0.5 | 0.5397 | 0.1430 |
| FPR @0.5 (window) | 0.1350 | 0.0001 |
| precision @0.5 | **0.0401** (TP 755 / FP 18070) | 0.9736 (TP 700 / FP 19) |

The FP≈18k / TP≈755 / precision≈3.9% figure in the brief is **confirmed exactly**.

## The decisive finding: the "0.97 ranking" is not the detector working

Ablation (`share_ablation.py`, using the **true** saved `share_val`, not a
reconstruction):

| ranking by | DNS held-out AP | DNS P@pos | time-split AP | time-split P@pos |
|---|---|---|---|---|
| `p_attack` alone | 0.1211 | 0.1708 | **0.6223** | **0.5715** |
| `share` alone | 0.0110 | 0.0000 | 0.0277 | 0.0000 |
| `rank = p×share` | 0.9345 | **0.9721** | 0.4413 | 0.4263 |

Three facts that change the story:

1. **Attackers do NOT have higher UL share.** True mean share: DNS attackers
   0.27 vs benign 0.33; time-split attackers 0.08 (median 0.004) vs benign 0.34.
   Share **alone is useless** (AP ≈ prevalence, P@pos = 0). The earlier verbal
   claim "attackers flood → high share → share lifts them to the top" is **wrong**
   on this data and is retracted.
2. On unseen DNS the detector is **blind**: its 100 most-confident windows are
   **all benign** (P@100[p] = 0.0). The 0.97 comes only from the *product*
   `p×share` — an interaction between two individually weak signals, not from the
   detector recognising the attack.
3. The product is **inconsistent**: it helps when the detector is blind (DNS) but
   **hurts** when the detector actually works (time-split: rank AP 0.44 < p AP
   0.62; P@pos 0.43 < 0.57). A prioritiser that is better exactly when the
   detector is worse is a dataset artifact, not a principled design.

**Conclusion.** Reported detection quality on unseen attacks is poor (AP 0.12).
The headline 0.97 is a ranking artifact and must never be reported as detection
accuracy. Detection and prioritisation must be separated and evaluated
independently (drives the Phase III redesign).
