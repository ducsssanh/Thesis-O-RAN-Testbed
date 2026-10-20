# Two-Stage Detection → Prioritisation → Mitigation (Phase III)

Date: 2026-10-19. Motivated by the audit finding that `p × share` is a crutch for
weak detectors and *harms* ranking once the detector works (see
`baseline_comparison.md` Findings C). Detection and prioritisation are separated
and evaluated independently, as the prompt requires.

## Stage A — Behavioural detector  →  p_malicious
- Input: the per-window behavioural features (volume, RAN↔core residual, radio
  quality). **Resource-share is NOT an input to detection.**
- Model: strongest leakage-free baseline. Current evidence: **tree ensemble
  (HistGB/RandomForest)** ≥ LSTM ≥ linear across attacks; LSTM not yet justified.
- Output: `p_malicious` ∈ [0,1], **calibrated** (isotonic/Platt on a train-only
  calibration slice) so the threshold has a stable meaning.
- Evaluated by: AP, ROC-AUC, recall/FPR at a **train-selected** threshold,
  leave-one-attack-out and leave-one-UE-out. NOT by any ranking metric.

## Stage B — Resource-impact score  →  impact_score
- Input: `ue_cell_ul_share` (traffic share) and, where available, cell-PRB
  utilisation context (Feature Set B) / per-UE PRB (testbed only).
- `impact_score` measures *potential resource impact*, NOT intent. A benign heavy
  uploader can have high impact and MUST still be allowed.
- Evaluated separately: does it rank by actual resource pressure? (sanity, not
  detection.)

## Stage C — Risk-aware prioritisation (gated)
Only UEs the detector already finds suspicious are ranked by impact:
```
if p_malicious < t_detect:          risk = 0          # ALLOW, never ranked on load alone
else:                               risk = impact_score
```
This replaces `risk = p_malicious × share`, which let load dominate and inverted
on a good detector. Compare on held-out data: gated-risk vs `p×share` vs `p`
alone vs share alone (ablation table), using Precision@k / Recall@k at k = the
mitigation capacity (number of UEs that can be rate-limited at once).

## Stage D — Mitigation policy (conservative)
```
p_malicious < t_detect                  -> ALLOW
t_detect <= p_malicious < t_high        -> MONITOR            (no disruptive action)
p_malicious >= t_high AND sustained_N   -> RATE_LIMIT         (reversible, TTL)
                                           escalate to BLOCK only on repeat
```
- `sustained_N`: require malicious across N consecutive windows (temporal
  stability) before any disruptive action — cuts false alerts from single-window
  blips.
- Disruptive action is **never** taken on resource consumption alone.
- Maps to the live system: RATE_LIMIT = the eBPF UPF uplink-quota reflex (TTL,
  reversible); BLOCK = the stronger rule; GTP-U malformation is handled by the UPF
  **fixed rules**, not Stage A (the ML does not detect GTP-U — see
  `baseline_comparison.md` Finding A).

## Why this is the defensible contribution
- Detection quality is reported honestly (per-attack, leakage-free), not hidden
  behind a volume-boosted ranking number.
- The prioritiser is gated so legitimate high-load UEs are never mitigated on load
  alone — the core "malicious ≠ high-load" guarantee, tested by the high-load-
  benign challenge (`high_load_benign_analysis.md`).
- Two layers are justified by evidence: ML for flooding families, fixed UPF rules
  for GTP-U / spoofing.
