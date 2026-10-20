# Verification Report — apples-to-apples, resid_dl shortcut test, independence

Date: 2026-10-19. Run in response to the reviewer's (correct) demand to verify
before accepting. `scripts/ml/feature_ablation.py` + `train_lstm.py` on the SAME
leakage-free split `artifacts/ml/ncsrd-v2-dns`. **Two earlier claims are
retracted here.** Raw rows: `research/experiments/results_ablation.csv`.

## 1. Apples-to-apples (one split: v2-dns, leakage-free, same val set)

| model / features | AP | note |
|---|---|---|
| Original LSTM — **leaky v1 split** | 0.121 | the old headline |
| Original LSTM — **leakage-free v2 split** | **0.876** | *same model*, only split changed |
| "Improved" LSTM (experiments.py, multi-seed) | 0.733 ± 0.050 | no real improvement; higher variance |
| RandomForest, all 16 | 0.956 (0.967 ± 0.011) | |
| LogReg, all 16 | 0.972 | DNS-specific (fails other attacks) |
| **RF, volume_only (5 rate feats)** | **0.998** | best; volume dominates |
| RF, drop resid_dl (15) | 0.991 | *higher* without resid_dl |
| RF, drop both residuals (14) | 0.992 | *higher* without residuals |
| RF, no_volume (11) | 0.860 | weaker without volume |
| RF, share_only | 0.368 | |
| LogReg, share_only | 0.027 ≈ prevalence | share carries ~no detection |
| RF, ran_ul_only (raw uplink magnitude) | 0.155 | magnitude alone is useless |

### Attribution of the "0.12 → 0.97" jump (the reviewer's key question)
- **0.121 → 0.876 is the SPLIT fix alone** (identical original LSTM). The bulk of
  the apparent gain was never a modelling improvement — it was removing the
  leaky/ distribution-shifted v1 split.
- **0.876 → ~0.96 is the model change** (LSTM → RandomForest). Modest.
- So: most of the headline came from correcting the evaluation, not from a better
  model. Stated honestly now.

## 2. RETRACTION — resid_dl is NOT the mechanism; detection is volume-driven
Earlier I claimed (from RandomForest *impurity* importance, 0.30–0.42) that the
detector "keys on the RAN↔core residual, behaviour not bandwidth." **The ablation
refutes this:**
- Dropping `resid_dl` *raises* RF AP (0.956 → 0.991); dropping both residuals
  raises it again (0.992). The residual is redundant/slightly harmful, not
  load-bearing.
- **volume_only = 0.998** — the five rate features alone are the best detector.
- Impurity importance is biased toward continuous/high-variance features and
  misled me; the ablation is the authoritative test.

**Corrected statement:** on NCSRD the detector is **volume-driven**. It is *not*
raw single-UE uplink magnitude (ran_ul alone = 0.155), but a multi-dimensional
volume/load pattern across RAN+core+cell rates. The "behaviour-not-bandwidth"
claim is withdrawn.

## 3. resid_dl shortcut question — resolved (it is not a shortcut)
Because resid_dl is not load-bearing (dropping it does not hurt; on v2-ue AP
0.843→0.819, on v2-gtpu the models are unstable either way), it cannot be the
feature the model "cheats" on. The shortcut risk is moot — but so is the claimed
benefit. If residuals are to matter, that must be shown on testbed telemetry, not
asserted from NCSRD.

## 4. RETRACTION/weakening — the high-load-benign "0 FPR" is on ~2 sessions
The high-load-benign windows come from only **2 distinct segments** out of 9 total
val segments (v2-dns); v2-gtpu likewise 2; v2-ue 8 of 28. So "0 FPR on ~18k–36k
windows" is really **0 FPR on ~2 benign UE-sessions** — exactly the correlated-
session caveat the reviewer raised. **The high-load-benign result is not
trustworthy as stated** and is downgraded to anecdotal. A real test needs many
independent legitimate-high-load sessions → testbed capture.

## 5. What still stands
- The **leakage audit and fix** are solid (0 shared segments; the 0.12 was a split
  artifact).
- **Detection generalises across attack families** (SYN/ICMP/UDP-frag/DNS) and
  across one held-out UE — but the *reason* is volume pattern, not a verified
  behavioural/consistency signal.
- **GTP-U is not detected** by any model (AP ≤0.35) — two-layer design still
  justified.
- **LSTM does not earn its complexity** (0.73–0.88 vs RF 0.96–0.998, far slower).
- `p×share` harms a good detector.

## 6. Honest bottom line
The project has a correct, leakage-free evaluation and a working volume-based
detector that generalises across IP-flood families. It has **not** shown that it
distinguishes malicious flooding from *legitimate high-load* traffic: the one test
that aimed at that rests on ~2 benign sessions, and the detector leans on volume.
**Proving malicious ≠ high-load requires the testbed capture** (many independent
deliberate heavy-uploader sessions at attacker-matched load). Until then, AP 0.97
is a within-NCSRD number, not evidence for the thesis's central claim.
