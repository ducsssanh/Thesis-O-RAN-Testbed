# Baseline Comparison — leakage-free split (Phase III/V first pass)

Date: 2026-10-19. Source: `scripts/ml/experiments.py` on
`artifacts/ml/ncsrd-v2-dns/windows.npz` (segment-atomic, leave-one-attack-out,
DNS held out, `segments_on_both_sides=0`). Raw rows in
`research/experiments/results.csv`. Single seed (0); multi-seed pending.

## Results — DNS held out, leakage-free

| model | AP | ROC-AUC | recall@0.5 | FPR@0.5 | prec@0.5 | P@pos[p] | P@pos[p×share] | train s |
|---|---|---|---|---|---|---|---|---|
| **LogReg** | **0.972** | 0.999 | 0.953 | 0.0009 | — | **0.947** | 0.499 | fast |
| RandomForest | 0.956 | 0.999 | 0.746 | 0.0001 | — | 0.850 | 0.499 | fast |
| HistGB | 0.883 | 0.997 | 0.851 | 0.0048 | — | 0.689 | 0.482 | fast |
| LSTM | 0.815 | 0.993 | 0.652 | 0.0021 | — | 0.685 | 0.794 | ~CPU-mins |

(val: 182,735 windows, 2,797 positives, prevalence 1.53%.)

## Three findings that change the thesis story

### 1. The "AP 0.12 on unseen DNS" was largely a split artifact, not detection failure
On the leakage-free segment-atomic split, unseen-DNS detection AP is **0.82–0.97**,
not 0.12. Two things differed between v1 and v2: v1 had **overlapping-window
leakage** AND used a **time-tail benign** val set (a distribution-shifted benign
population the model false-triggered on, FPR 0.135). v2 removes the overlap leak
and draws benign from the DNS episode. The honest conclusion: **behavioural
features generalise across attack types** — a model that never saw DNS still
detects it — because all floods share a generic signature (elevated rate +
residual + retx) in the feature space. v1's numbers are deprecated; do not cite
them as generalisation.

### 2. A LINEAR model beats the LSTM — the LSTM does not (yet) earn its complexity
LogReg on simple per-window aggregates `[mean | last | std]` of the 16 features
reaches **AP 0.972**, above the LSTM's 0.815, at a fraction of the cost. So the
discriminative signal is largely in **window statistics, not temporal dynamics**.
Implications: (a) report LogReg/RF/HistGB as mandatory baselines; (b) the LSTM
must justify itself on something the aggregates miss (short bursts, onset
latency, sequence order) or it should not be the headline model; (c) this is
exactly the "don't assume deep learning is superior" check your prompt required.

### 3. `p × share` HURTS ranking once the detector works — separate detection from prioritisation
For every model here, `P@pos[p×share] < P@pos[p]` (LogReg 0.50 vs 0.95). The
share multiplier only helped on the broken leaky-v1 detector; with a working
detector it **degrades** ranking. This confirms the audit's conclusion: share is
not a detection signal and must not be baked into the detector. Prioritisation
should be a separate, independently-evaluated stage (Phase III Stage B/C).

## Caveat resolved — leave-one-UE-out holds up
Holding attacker `8642840401612300` out **entirely** (its benign *and* attack
windows all in val; `artifacts/ml/ncsrd-v2-ue`):

| model | AP | ROC-AUC | recall@0.5 | FPR@0.5 | P@pos[p] | P@pos[p×share] |
|---|---|---|---|---|---|---|
| LSTM | 0.874 | 0.953 | 0.849 | 0.0023 | 0.850 | 0.850 |
| LogReg | 0.861 | 0.960 | 0.848 | 0.0021 | 0.852 | 0.852 |
| RandomForest | 0.843 | 0.931 | **0.000** | 0.0000 | 0.852 | 0.852 |
| HistGB | 0.842 | 0.937 | **0.007** | 0.0000 | 0.828 | 0.846 |

AP stays **0.84–0.87** with the UE fully unseen, so §1 is genuine cross-UE +
cross-signature generalisation, not UE-baseline memorisation. The residual
UE-identity concern is substantially cleared (one held-out UE; a full
leave-each-UE-out loop is a later refinement).

### New finding — tree models are mis-calibrated; 0.5 is the wrong threshold
RandomForest/HistGB show recall ≈ 0 at threshold 0.5 despite AP ≈ 0.84 — their
positive scores sit below 0.5. **Threshold must be selected per model** (e.g. on a
validation PR curve), and probabilities calibrated, before any operating-point
claim. Never report recall/FPR at a fixed 0.5 across models. (Prompt §2.2, §10.1.)

## Cross-attack generalisation sweep (all 5 attacks, leave-one-out)
Segment-atomic, tabular (LSTM ≈ best tabular on the two splits tried). **Best AP
per held-out attack**, over {LogReg, RandomForest, HistGB}:

| held-out attack | best model | best AP | ROC | LogReg AP | RF AP | HistGB AP |
|---|---|---|---|---|---|---|
| SYN | HistGB | **0.999** | 1.000 | 0.111 | 0.998 | 0.999 |
| ICMP | HistGB | **0.943** | 1.000 | 0.197 | 0.833 | 0.943 |
| UDP-frag | RandomForest | **1.000** | 1.000 | 0.355 | 1.000 | 0.961 |
| DNS | LogReg | **0.972** | 0.999 | 0.972 | 0.956 | 0.883 |
| **GTP-U** | LogReg | **0.299** | 0.81 | 0.299 | 0.129 | 0.269 |

Mean best-AP over the 4 IP-layer floods = **0.978**; including GTP-U = 0.843.

### Finding A — four flood families generalise; GTP-U does not
A detector trained on the other attacks detects unseen SYN/ICMP/UDP-frag/DNS at
AP 0.94–1.00, but **GTP-U collapses to ≤0.30** (ROC 0.67–0.81). GTP-U is a
tunnel-layer / malformed-encapsulation attack whose signature is not in the
volume + residual + radio features, so it does not transfer from IP-layer floods.
**This directly justifies the two-layer design**: the ML layer covers flooding
families; **GTP-in-GTP / spoofed-TEID / malformed GTP-U are caught by the eBPF
UPF fixed rules, not the model.** Frame GTP-U as a fixed-rule responsibility, not
an ML failure.

### Finding B — no single model wins; tree ensembles are the strongest baseline
The earlier "LogReg beats LSTM" was **DNS-specific**. LogReg *fails* on
SYN/ICMP/UDP-frag (AP 0.11–0.36) — those need non-linear boundaries — while
**RandomForest/HistGB are strong across all four floods**. Corrected ranking:
tree ensembles ≥ LSTM ≥ linear, and the LSTM still has not shown a win that
justifies its cost. Report per-attack, not a single headline number.

### Finding C — `p×share` is a crutch for weak detectors only
Where a model is weak it is rescued by the share multiplier (SYN LogReg: P@pos
0.001 → rank 0.986); where it is strong the multiplier is redundant or
destructive (UDP-frag RF: P@pos 0.999 → rank 0.001). Confirms: share belongs in a
separate prioritiser, never in detection.

### Finding D — calibration again
Recall at 0.5 swings between 0.0 and 1.0 across models/attacks at similar AP.
Thresholds must be chosen per model on a PR curve; 0.5 is meaningless here.

## Robustness (multi-seed + window sweep, `results_robustness.csv`)
- **Multi-seed (v2-DNS, w6):** LSTM AP **0.733 ± 0.050** (0.68/0.71/0.80, high
  variance, 155–720 s/run); RandomForest **0.967 ± 0.011** (stable, ~17 s); LogReg
  deterministic 0.972. The LSTM is both weaker and less stable.
- **Window length [6,12,24]:** LSTM no gain (0.73→0.70→0.75) at up to 4× cost;
  RandomForest marginal (0.956→0.958→0.980); HistGB flat. Window 6 is adequate for
  a near-RT detector.
- **Verdict:** the LSTM does not earn its complexity. **RandomForest on
  [mean|last|std] aggregates of a 6-step window is the recommended detector.**

## Open items (next iterations)
- Multi-seed variance (≥5 seeds) for the top configs.
- Leave-one-attack-out for all 5 attacks (not just DNS) → mean ± sd.
- Feature correlation/redundancy + permutation importance (why does LogReg win?).
- Window-length sweep [6,12,24] and a proper detector/prioritiser two-stage model.
- Cell-PRB Feature Set B ablation.
