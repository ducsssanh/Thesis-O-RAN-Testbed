# Final Research Report — Resource-Aware User-Plane Flooding Detection in 5G O-RAN

Date: 2026-10-19. Consolidates the Phase I–VII work on the NCSRD-DS-5GDDoS
dataset. Every number is reproduced from committed artifacts/scripts (see
`reproducibility/`). Testbed-dependent items are marked and **not fabricated**.

---
## A. Original system assessment
The existing pipeline (`scripts/ml/prep_ncsrd.py` + `train_lstm.py`) trains a
6×16 LSTM → `p_attack`, and ranks by `rank = p_attack × ue_cell_ul_share`.
Reproduced headline (DNS leave-one-attack-out): AP 0.121, ROC 0.891, FPR@0.5
0.135, **ranking precision 0.97**.

Main failure modes found:
1. **The 0.97 is a ranking artifact, not detection.** `p` alone AP 0.12 (top-100
   windows all benign); `share` alone useless; only the product reaches 0.97, and
   it *reverses* to worse-than-`p` on splits where the detector works. Never report
   it as detection accuracy.
2. **Severe leakage** inflated/contaminated the split: 9 UEs all on both sides; 73%
   of val windows overlapped a same-UE train window (stride-1 windows straddling a
   per-row time cut); ~5 attack episodes inflated to 11k positive windows.
3. **AP 0.12 was itself a split artifact** (overlap leak + a distribution-shifted
   time-tail benign set the model false-triggered on).

## B. Dataset improvements
- **Leakage-free split** (`prep_ncsrd_v2.py`): segment-atomic group split —
  whole UE segments go to one side, so no window crosses the boundary
  (`segments_on_both_sides = 0`). Modes: leave-one-attack-out, leave-one-UE-out.
- **Labels** kept rebuilt from the schedule (not the leaky `attack`/`malicious`
  columns); scaler fit on train only.
- **Dataset versioning**: v1 (original), v2 (leakage-free), v3 (Feature Set B);
  raw data never overwritten; artifacts and metas versioned.
- Integrity findings in `audits/data_leakage_report.md`.

## C. PRB investigation
- `ue_cell_ul_share` = **UE uplink throughput / cell uplink throughput** in a 5 s
  bucket — **traffic share, NOT PRB** (traced to code).
- **No per-UE PRB in NCSRD**, not derivable. Only a **cell-level** utilisation
  proxy (`cell_*_ul_use_*`) in the uncollected `enb_counters` file.
- **Feature Set B** (join those cell-use features, `prep_ncsrd_v3.py`): DNS best AP
  0.956→0.973, GTP-U 0.299→0.346; the added features **do not enter the top-8
  importances**. Cell-PRB context is marginal; **not adopted**. Per-UE PRB is a
  testbed-instrumentation item (unverified the OAI DU exposes it).

## D. Model architecture
Baselines on leakage-free splits (per-window `[mean|last|std]` aggregates for
tabular):
- **RandomForest / HistGB ≥ LSTM ≥ LogReg** overall. LogReg wins DNS but fails
  SYN/ICMP/UDP-frag (non-linear).
- **LSTM does not earn its complexity:** multi-seed AP 0.733 ± 0.050 vs
  RandomForest 0.967 ± 0.011; LSTM 10–40× slower; longer windows give it no gain.
- **Recommended detector: RandomForest** on a 6-step window of behavioural
  features. LSTM retained only as a baseline.

## E. Experimental results (leakage-free)
Leave-one-attack-out, best model per attack:

| held-out | best AP | ROC | model |
|---|---|---|---|
| SYN | 0.999 | 1.000 | HistGB |
| ICMP | 0.943 | 1.000 | HistGB |
| UDP-frag | 1.000 | 1.000 | RandomForest |
| DNS | 0.972 | 0.999 | LogReg (RF 0.967±0.01) |
| **GTP-U** | **0.299** | 0.81 | — (ML fails) |

Leave-one-UE-out (unseen device): AP 0.84–0.87 — generalises across devices.

**High-load-benign challenge (the core test) — DOWNGRADED, see
`verification_report.md`:** the heaviest benign windows score ~0.0004 vs attackers
~0.78, but those windows come from only **~2 distinct benign sessions**, so the
"0 FPR" is anecdotal, not evidence. The malicious-≠-high-load claim is **not**
established on NCSRD; it needs the testbed capture.

**Mechanism — CORRECTED:** the detector is **volume-driven** (volume_only RF AP
0.998; dropping residuals *raises* AP). The earlier "keys on RAN↔core residual,
behaviour not bandwidth" claim is **retracted** — it came from biased RF impurity
importance; the ablation refutes it. It is not raw single-UE uplink magnitude
(ran_ul alone AP 0.155) but a multi-dimensional volume/load pattern.

**Ranking:** `p×share` hurts a working detector; use a gated prioritiser
(`detector_prioritiser_design.md`).

## F. Best model (current recommendation)
- **Architecture:** RandomForest (200 trees, balanced) on `[mean|last|std]` of a
  6-step (~31 s) window of the 16 behavioural features.
- **Preprocessing:** `prep_ncsrd_v2.py`, segment-atomic, log1p on rate cols,
  z-score fit on train.
- **Operating point:** threshold selected on train at 1% benign FPR (not 0.5);
  calibrate probabilities before deployment.
- **Prioritisation:** gated — rank suspicious UEs by impact; never mitigate on load
  alone.
- **Two layers:** ML for SYN/ICMP/UDP-frag/DNS; **eBPF UPF fixed rules for GTP-U /
  spoofing** (ML provably does not detect GTP-u, AP 0.30).
- **Inference cost:** RandomForest ~ms; fits the near-RT xApp budget.
- **Limitations:** see G.

## G. Research-contribution assessment
Defensible contributions:
1. A **leakage-free evaluation** of ML flooding detection on NCSRD, correcting a
   ranking-artifact headline and showing most of the "0.12→0.97" gain was the
   split fix, not the model — methodological value.
2. Detection **generalises across IP-flood families and an unseen UE**, driven by a
   multi-dimensional **volume/load pattern** (verified by ablation).
3. An **evidence-based two-layer justification**: ML covers IP-flood families;
   fixed UPF rules own GTP-U, which ML cannot detect (AP ≤0.35).
4. A gated detector→prioritiser→mitigation design (share removed from detection).

NOT yet a contribution (needs testbed): the **malicious ≠ high-load** claim. The
one test aimed at it rests on ~2 benign sessions and the detector leans on volume;
see `verification_report.md`.

NOT claimed: that the LSTM is a contribution (it underperforms); that cell-PRB
helps (it doesn't); that the system is validated against *deliberate* legitimate
high-load (NCSRD lacks it).

**Open / blocked on testbed (designs + configs delivered, no fabricated data):**
- High-load-benign robustness vs a deliberate heavy uploader at matched volume
  (`configs/testbed_enrichment.yaml`, scenario `b_heavy_ul`).
- NCSRD→testbed pretrain/fine-tune P1–P4 (`pretrain_vs_finetune.md`).
- Re-validate that `resid_dl` is a genuine consistency signal, not an NCSRD
  logging shortcut.
- Per-UE PRB feature (requires OAI DU instrumentation).
- Multi-seed/threshold/calibration for the final tree detector across all attacks.

## Deliverables map
`audits/{dataset_audit,baseline_verification,data_leakage_report,
prb_feature_investigation,feature_schema_unification}.md`,
`audits/feature_inventory.csv`, `audits/scripts/*`;
`reports/{baseline_comparison,high_load_benign_analysis,ablation_study,
detector_prioritiser_design,pretrain_vs_finetune,final_research_report}.md`;
`configs/testbed_enrichment.yaml`; `experiments/results*.csv`,
`experiments/analysis_*.json`; `reproducibility/{run_instructions,environment}.md`;
scripts `prep_ncsrd_v2.py`, `prep_ncsrd_v3.py`, `experiments.py`, `analysis.py`.
