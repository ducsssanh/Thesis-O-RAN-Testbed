# Ablation Study (Phase VII §10.6)

Date: 2026-10-19. Separates the contribution of the behavioural detector, the
traffic-share signal, and cell-PRB context. All on leakage-free segment-atomic
splits. Detection = AP of the score; prioritisation = P@pos (top-k precision,
k=#positives).

## Detection: behavioural detector vs share vs PRB

| variant | detector | share | PRB-ctx | DNS AP | GTP-U AP | note |
|---|---|---|---|---|---|---|
| A behavioural only | yes | (in feats) | no | 0.88–0.97 | 0.27–0.30 | the detector |
| B share alone | no | yes | no | **0.011** | ~0.01 | useless as detection |
| C PRB alone | no | no | yes | — | — | not evaluated alone (coarse, cell-level) |
| E detector + PRB (Set B) | yes | yes | yes | 0.97 (RF) | 0.35 | +0.02/+0.05, PRB not in top-8 importances |

- **Share carries almost no detection signal** (AP 0.011 ≈ prevalence). It must not
  be treated as evidence of attack.
- **PRB context adds little** and is not adopted.
- `ue_cell_ul_share` is currently also one of the 16 detector inputs, but its
  RandomForest importance is only ~0.07 (vs residual 0.30–0.42), so removing it
  from the detector would change detection marginally — the detector does not lean
  on share. (The clean "detector with share removed from inputs" variant is a
  minor follow-up.)

## Prioritisation: does multiplying by share help?

| ranking score | DNS P@pos | time-split P@pos | UDP-frag P@pos | verdict |
|---|---|---|---|---|
| p (good detector) | 0.95 (LogReg) | 0.57 | 0.999 (RF) | strong |
| p × share | 0.50 | 0.43 | 0.001 | **hurts a good detector** |
| p × share (weak detector, leaky v1) | 0.97 | — | — | only helps when p is bad |

**Conclusion.** `p × share` is a crutch for a broken detector. With a working
detector it is redundant (DNS) or destructive (UDP-frag). Prioritisation must be a
separate, *gated* stage (`detector_prioritiser_design.md`), not a product baked
into the score.

## Takeaways for the paper
1. The detector earns its result from **behavioural consistency (RAN↔core
   residual)**, not volume or share — the resource-aware property.
2. Neither share nor cell-PRB context materially improves detection.
3. The headline `p×share` ranking from the original pipeline is an artifact; drop
   it from detection and gate it in prioritisation.
