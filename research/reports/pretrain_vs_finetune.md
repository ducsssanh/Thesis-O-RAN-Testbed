# Pretrain vs Fine-Tune (Phase VI)

Date: 2026-10-19. The project's pretrain→fine-tune is **NCSRD (public) → testbed
(own)**. Full P1–P4 comparison needs the *target* training set = testbed capture,
which is not yet collected. This file states the design, what the P-experiments
will measure, and the transfer evidence available **now** as a proxy.

## Design (runs once the testbed set exists)
- **P1 From scratch:** random init, train on testbed train only.
- **P2 Frozen encoder:** load NCSRD-pretrained LSTM, freeze, train a new head.
- **P3 Full fine-tune:** load NCSRD weights, fine-tune all with a small LR.
- **P4 Improved pretraining:** only if P1–P3 show the pretrain distribution is the
  bottleneck.
Compare held-out testbed AP, convergence, data efficiency, seed variance,
overfitting, inference cost. Check for **negative transfer** explicitly.

Schema handling: unified superset + missing-mask (see
`audits/feature_schema_unification.md`) so NCSRD (16 shared) and testbed (shared +
packet-mix/URR/PRB) share one input shape; pretrain masks testbed-only columns,
fine-tune turns the mask off. Input shape constant → weights transfer.

## Proxy evidence available now — cross-distribution transfer within NCSRD
We cannot fine-tune on the testbed yet, but the **leave-one-attack-out** study is
itself a transfer test: train on 4 attack families, evaluate on a 5th unseen one.

| transfer target (unseen) | best AP | transfers? |
|---|---|---|
| SYN | 0.999 | yes |
| ICMP | 0.943 | yes |
| UDP-frag | 1.000 | yes |
| DNS | 0.972 | yes |
| GTP-U | 0.299 | **no** |

And **leave-one-UE-out** (unseen device) holds AP 0.84–0.87. So behavioural
features transfer across attack families and devices — evidence that an
NCSRD-pretrained encoder should give the testbed a useful starting point for the
IP-flood families, but **not** for GTP-U (a fixed-rule responsibility).

## Expectation for NCSRD→testbed
- Positive transfer likely for SYN/ICMP/UDP-frag/DNS detection.
- GTP-U will not transfer; do not rely on fine-tune to fix it.
- Domain gap (Amarisoft→OAI, 9→2 UEs, radio) means P3 (full fine-tune) is the
  most likely winner over P1; P2 (frozen) tests how reusable the encoder is.
- Report honestly if negative transfer appears (e.g. NCSRD radio stats misleading
  on OAI) — then prefer P1 or a unified-schema joint train.

## Status
Design + proxy complete. P1–P4 **blocked on the testbed capture campaign**
(`configs/testbed_enrichment.yaml`); results will not be invented.
