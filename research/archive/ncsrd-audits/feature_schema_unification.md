# Feature-Schema Unification & Testbed Scenario-Replay (Phase IV addition)

Date: 2026-10-19. Added after the observation that restricting pretraining to the
NCSRD∩testbed feature intersection is a self-imposed limitation, not a necessity.

## The assumption, corrected
Fine-tuning a checkpoint requires the **input tensor shape** to match (nn.LSTM
input weights are `[4·hidden, n_features]`). It does **not** require pretraining to
use only the shared feature set. Options to let pretrain (NCSRD) and fine-tune
(testbed) differ in features while still transferring weights:

1. **Unified superset schema + missing-mask.** Define the union of features. A
   source lacking a column feeds 0 + a per-feature "present" mask channel. One
   input shape for both datasets; the model learns to ignore masked channels.
2. **Input-layer surgery.** Transfer recurrent weights; replace/extend only the
   input projection to accept new features (partial transfer).
3. **Dual-branch.** Pretrain a shared-feature encoder; at fine-tune concatenate a
   small branch for testbed-only features before the head.
4. **Self-supervised pretraining** (sequence reconstruction/forecasting) that does
   not depend on the exact downstream feature set.

Default choice for this project: **(1) unified superset schema + mask**, because it
keeps a single reproducible input shape across datasets and is the simplest to
version and evaluate. (2) is the fallback if the mask dilutes signal.

## Testbed scenario-replay to enrich the feature space
Goal: build a **testbed-native dataset with the complete schema** (16 shared +
testbed-only) by reproducing NCSRD's scenario design, so NCSRD can pretrain and
the testbed set can fine-tune/validate — including features NCSRD cannot measure.

What replays faithfully:
- Attack *types* (SYN / ICMP / UDP-frag / DNS / GTP-U floods), intensities, and
  durations — reproducible with traffic tools on the isolated testbed.
- Benign traffic profiles (throughput shapes, bursts) — mimicable.
- **All** attributes are then natively collected on the testbed: the 16 shared
  PLUS per-UE packet-mix (eBPF UPF), URR counters, and per-UE/cell PRB **iff** the
  OAI DU exposes it (unverified — see `prb_feature_investigation.md`).

Honest limits (do not over-claim):
- This does **not** back-fill NCSRD rows; it creates a **parallel** dataset.
- Domain differs: NCSRD = Amarisoft, 9 UEs, real radio; testbed = OAI, 2 UEs,
  SKB-mode eBPF, minikube. The replay is *scenario-equivalent*, not *identical*.
- Per-UE PRB may remain unavailable if the DU does not expose it; then testbed-only
  features = packet-mix + URR + cell-PRB proxy only.

## How pretrain↔fine-tune then works
- Pretrain on NCSRD under the **unified schema** (testbed-only columns masked).
- Fine-tune on the testbed set with those columns **present** (mask on→off).
- Keep input shape constant; only the mask changes. Weights transfer cleanly.

## Plan placement
This is inserted as **Phase IV step: Testbed Scenario-Replay Data Generation**
(reproducible config: `research/configs/testbed_enrichment.yaml`). Because a full
capture campaign needs the live cluster and is long-running, this iteration
delivers the **design + config + schema**; the capture itself is driven on the
testbed and its measurements are only reported once actually collected (integrity
rule: never present un-captured testbed features as measured).
