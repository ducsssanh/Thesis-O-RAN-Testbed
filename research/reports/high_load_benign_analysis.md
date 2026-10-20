# High-Load-Benign Challenge & Feature Importance (Phase VII, core result)

> **⚠️ CORRECTED 2026-10-19 — see `verification_report.md`.** Two claims below are
> RETRACTED by the feature ablation: (1) the high-load-benign windows come from only
> **~2 distinct benign sessions**, so "0 FPR on ~18k–36k windows" is anecdotal, not
> strong evidence; (2) the detector is **volume-driven**, NOT keyed on the RAN↔core
> residual — dropping `resid_dl` *raises* RF AP, and the RF *impurity importance*
> used below is biased and misled the analysis. Read the ablation table in
> `verification_report.md` as authoritative; the sections below are kept for the
> record with this caveat.

Date: 2026-10-19. `scripts/ml/analysis.py` (HistGB detector, threshold fixed at
**1% train-benign FPR**, chosen on train only; RandomForest impurity importances
aggregated to base features). JSON in `research/experiments/analysis_*.json`.

This is the decisive test of the ultimate goal: **does the detector separate
malicious behaviour from legitimate HIGH-LOAD traffic, or does it just flag heavy
UEs?** "High-load benign" = the heaviest 10% of benign windows by uplink;
"load-matched" = attackers vs benign within the top-20% uplink band.

## Result — the detector does NOT conflate load with attack

| split | AP | recall(attackers) | FPR all-benign | **FPR high-load-benign** | mean score: attacker / high-load-benign / normal-benign |
|---|---|---|---|---|---|
| DNS held out | 0.88 | 0.91 | 0.009 | **0.000** | 0.78 / 0.0004 / 0.007 |
| UE held out | 0.84 | 0.80 | 0.002 | 0.017 | 0.03 / 0.0001 / 0.000 |
| GTP-U held out | 0.27 | 0.40 | 0.014 | **0.000** | 0.12 / 0.0004 / 0.001 |

Load-matched (top-20% uplink band), DNS: **recall(attackers) = 1.00, FPR(benign)
= 0.00** over 36,523 heavy-benign windows and 24 heavy-attacker windows — every
heavy attacker caught, **zero** heavy benign flagged.

**Interpretation.** On the DNS split the heaviest legitimate uplinkers get a mean
score of 0.0004 while attackers get 0.78 — three orders of magnitude apart. The
model is **not** using "is this UE heavy?" as its rule. The UE-held-out case is
weaker (FPR high-load-benign 0.017) but still low. On GTP-U the model misses the
attack (recall 0.40) yet still does not false-trigger on heavy benign — it fails
by *missing*, not by *confusing load with attack*.

**Caveat (honesty).** NCSRD contains almost no *sustained legitimate high-load*
benign (no deliberate heavy-uploader sessions). "High-load benign" here is the top
decile of ordinary benign, which is modest. The strong claim — robustness against a
*deliberate* heavy uploader at attacker-matched volume — still requires the
testbed scenario-replay set (`b_heavy_ul`, `configs/testbed_enrichment.yaml`).
This result is necessary evidence, not yet sufficient.

## Why it works — feature importance (the mechanism)
Aggregated RandomForest importances, consistent across all splits:

| rank | feature | importance (DNS / UE / GTP-U) |
|---|---|---|
| 1 | **resid_dl** (RAN↔core residual) | 0.34 / 0.30 / 0.42 |
| 2 | core_ul_kbps | 0.16 / 0.16 / 0.10 |
| 3 | resid_ul (RAN↔core residual) | 0.09 / — / 0.04 |
| — | ran_ul_kbps (raw uplink volume) | 0.065 / 0.047 / 0.078 |
| — | ue_cell_ul_share (traffic share) | 0.07 / — / 0.05 |

The dominant signal is the **RAN↔core consistency residual**, not raw volume. Raw
uplink rate and traffic share are minor. This is exactly the resource-aware,
behaviour-not-bandwidth property the goal requires, and it explains the clean
high-load-benign result: a heavy *legitimate* UE has consistent RAN and core
accounting (small residual); an attacker does not.

**Shortcut caveat.** `resid_dl` dominating even for uplink floods is worth
scrutiny — it could be a genuine consistency signal *or* an NCSRD logging
artifact. Must be re-validated on testbed data before being claimed as the
mechanism; flagged for the testbed phase.

## Feature Set B (cell-level PRB context) — marginal, honest negative
Adding `cell_ul_use/dl_use/ul_sched_users/ue_active` from enb_counters (v3, 20
features):

| split | best AP, Feature A (16) | best AP, Feature B (20) | verdict |
|---|---|---|---|
| DNS | 0.956 (RF) | 0.973 (RF) | +0.017, marginal |
| GTP-U | 0.299 | 0.346 | +0.047, still failing |

The added cell-use features **do not enter the top-8 importances**. Conclusion:
**cell-level PRB context adds little** — it is too coarse. Per-UE PRB (unavailable
in NCSRD) might help, but the cell aggregate does not. This is a documented
negative result, not a reason to add the features.
