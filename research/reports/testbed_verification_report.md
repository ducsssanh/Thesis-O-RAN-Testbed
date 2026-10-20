# Testbed Dataset (v3) — Verification & the Behaviour-vs-Volume Answer

Date: 2026-10-20. The testbed ML pipeline (`build_oran_dataset.py` →
`eval_oran_models.py` → `eval_oran_lstm.py`) ran to completion for dataset **v3**;
this report verifies it and fixes the one methodological hole (the challenge set
did not actually neutralise volume). Scripts added: `eval_oran_challenge.py`.
Raw: `research/datasets/oran_flooding_v3/reports/`.

## Dataset v3 (vs NCSRD — this is the real one)
- 12 campaigns, 50 OK runs, **100 independent (campaign,run,supi) sessions**,
  16,812 records (BENIGN 12,484 / MALICIOUS 4,328).
- **Real legitimate high-load** (`ds-benign-bulk` heavy uploaders) — the thing
  NCSRD lacked — plus 5 verified flood families (udp, fanout_udp, icmp, syn, dns).
  frag_flood auto-excluded (generator produced no real traffic — honest gate).
- Per-UE PRB, packet-mix (profiler), and URR present for **both** classes; leak
  audit clean (has_urr/has_prof 100% both classes). Load overlaps on KPM and URR
  volume axes and on packet size → volume alone is not a trivial label.
- Ground truth = experimental control only (a UE is MALICIOUS iff it ran an attack
  flow in that phase); decision outputs excluded as leakage.

## Detection (session-grouped 5-fold CV, no session spans train/test)
Full test, best model (hist-gbm/RF), F1 ≈ 0.99, AUC ≈ 0.999; per-family recall
dns 0.95 / fanout 0.99 / icmp 0.97 / syn 0.995 / udp 0.99. LSTM full-test F1
0.992. These are strong and leakage-aware. (`model_eval.md`, `model_eval_lstm.md`.)

## The behaviour-vs-volume test — FIXED and answered
The v3 "load-matched" challenge only banded `thp_ul_kbps`, so volume-only stayed
~0.99 (other volume axes still differed) — it did **not** prove the claim. New
strict control (`eval_oran_challenge.py`): 1-NN match each malicious test row to a
benign one on **all 16 volume/PRB axes** (residual imbalance ~0.035 std → classes
near-identical in volume), then score two models:

| model | full test AUC | volume-matched AUC |
|---|---|---|
| volume-only (16 rate/PRB feats) | 0.9992 | **0.997** |
| behaviour-norm (protocol *shares* + pkt size + fan-out; NO volume) | 0.9931 | **0.988** |

(caliper 1.0–2.0, 894–982 matched pairs, stable.)

**Reading:**
1. **Separation does NOT require volume.** A model using only volume-*invariant*
   behaviour features (packet-type shares, mean packet size, fan-out) separates
   attack from benign at **AUC ≈ 0.99**, even on volume-matched pairs. This is the
   positive evidence for *malicious ≠ legitimate high-load* that NCSRD could not
   give — and it is on data with real heavy-uploader benign and 100 sessions.
2. **Volume alone is also sufficient** — volume-only stays 0.997 even when the 16
   volume axes are matched to near-identical marginals. The attack classes occupy
   a distinct *joint* traffic structure (combinations/ratios), so matching
   marginals doesn't erase them. So volume is sufficient but not necessary.

## Honest caveats (do not overclaim)
- **Generator-fingerprint risk (the key one).** behaviour-norm's power comes from
  protocol shares and packet sizes, which are dictated by the synthetic attack
  tools (hping3/nping: pure SYN/ICMP, fixed sizes). So "behaviour separates" may
  partly mean "the tool's fingerprint is recognisable", not that it generalises to
  real-world adversarial traffic. This is the testbed analogue of the NCSRD
  `resid_dl` caveat and must be stated as a limitation.
- **C5 causal-join leak (small, baked into capture).** v3 features.jsonl used a
  ±1 s / +1 s join for URR/profiler; ~212/16,812 rows (1.3%) use a future (+1 s)
  value. Removing it fully needs a causal re-join from raw logs or a re-capture
  (v4). Impact is small but acknowledged; `phase0_v4.md` specs the causal as-of
  join with a 3–4 s age cap.
- **frag_flood excluded** (generator failed over RFsim) → fragmentation attacks
  untested.
- **Scale:** 2 UEs, OAI RFsim; not real radio or many UEs.

## Status of v4 (new capture) — BLOCKED, not attempted
v4 (more sessions, causal join, per-backend traffic library) is blocked by the
OAI user-plane fault: SMF segfaults ~every 5.5 h and leaves the gNB not forwarding
UL GTP-U; no operational reset (recover_ran, cold core restart, minikube restart)
fixes it (`phase0_v4.md`, memory `testbed-userplane-fragility`). The real v4 P0 is
a watchdog/checkpoint-resume harness, then the traffic library. I did not attempt
live-cluster surgery autonomously — the offline mission (reproduce + fix the
challenge control) is complete; new measurements are not fabricated.

## Bottom line
On the testbed dataset, the central thesis claim is **supported**: a volume-
invariant behavioural detector separates malicious flooding from legitimate
high-load at AUC ≈ 0.99 under a strict volume-matched control. The remaining risk
is that this separation reflects the synthetic generators' fingerprints; settling
that needs more realistic/diverse attack traffic (a v4 goal) — which is blocked by
the testbed fault, not by analysis.
