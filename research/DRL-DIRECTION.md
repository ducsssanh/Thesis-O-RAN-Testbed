# DRL direction — notes for later study

Status: 2026-10-27. Notes from the design discussion about moving the defence towards deep reinforcement learning
(DRL). Nothing here is implemented. Read with `research/CROSS-DOMAIN-DEFENCE.md` (testbed, threat model, telemetry).

---

## 1. Where DRL fits — and where it does not

- **Detection** (is this UE flooding?) is a labelled classification problem; supervised learning is the better tool
  (labels exist in the testbed; DRL would learn the same mapping from a sparse reward, less sample-efficiently).
- **Decision / control over time** (when to isolate, how long to hold, when to block, when to release) is a
  sequential decision problem — the natural place for DRL. In the earlier design this layer was hand-written rules
  (3-of-5 alarms, 10 s hold before blocking, both domains must agree, fixed expiries).

```
earlier design:  telemetry → detector(s) + KPM↔URR integrity/trust → [hand-written escalation rules] → actions
DRL direction:   telemetry → detector(s) + KPM↔URR integrity/trust → [DRL agent]                    → actions
```

## 2. A DRL formulation of the decision layer

| element | proposal |
|---|---|
| **State** (per UE, per second) | detector scores per domain (RAN, core, cross-domain); KPM/URR log-ratio and integrity flag; KPM trust, core trust; current action level and how long it has been held; cell load; a few seconds of history |
| **Actions** | no-op · isolate (RAN quarantine slice) · rate-limit (UPF) · block (UPF) · release |
| **Reward** | − attack bytes delivered to the DN − λ·benign throughput lost − μ·wrong block (large) − small cost per action change |
| **Algorithm** | DQN or PPO, discrete actions, small MLP policy |
| **Safety layer** | action masking (e.g. no block without core evidence), the UPF block-ratio guard, fallback to rules if the agent is unavailable |

**Training environment** — the live testbed is far too slow for DRL (~9 runs/hour vs 10⁵–10⁶ episodes needed):
- trace-driven replay of recorded telemetry (the generated datasets), KPM tamper injected by scaling, core outage by
  dropping URR/profiler;
- an actuation model: block → the UE's UL at the UPF / DN and its URR go to 0; isolation → little effect on low-rate
  floods in RFsim (as measured);
- domain randomisation over traffic families, loads, tamper factors, outage timing.

**Deployment** — the policy (a few-KB MLP) runs where the decision is taken (a model sidecar next to the xApp);
xApp actuators (E2SM-RC, UPF Security API) stay unchanged; keep a rule-based fallback.

**Evaluation** — compare against the rule-based policy first in replay (cheap), then in a small pre-registered live
campaign (e.g. 3 configurations × 7 scenarios × 6 repetitions ≈ 15 h).

**Effort estimate** — environment 3–5 days, training + reward tuning ~1 week, integration 2–3 days, live 1–2 days.

## 3. Risks of DRL here
- **Sim-to-real gap**: replay cannot reproduce every consequence of an action on the traffic.
- **Reward hacking / sensitivity**: low wrong-block penalty → blocks everything; high → never blocks; results depend on λ, μ.
- **Explainability**: rules can be justified step by step; a learned policy is harder to defend in a thesis.
- **May not win**: the rule policy already blocked every hidden attacker and almost never a framed UE; the room for
  improvement is in framing and core-outage cases.
- **Adversarial**: a learned policy can be probed and gamed; a physics-based integrity rule is harder to game.

## 4. Misconception to avoid: "DRL reacts to the environment, so dataset realism matters less"
DRL does **not** remove the dataset-realism problem; it moves it into the training environment.
1. A policy trained in a testbed / simulator is a fixed function after training; on real traffic it meets the same
   **sim-to-real gap** as a supervised model (RL is often *less* robust to distribution shift).
2. Adapting **online** in a real network needs a **reward**, i.e. knowing whether a decision was right — ground truth
   is not available online (proxies such as complaints or resource exhaustion are late and noisy).
3. Online learning means **exploring on real users** (deliberately blocking / allowing to learn) — unacceptable to an
   operator.
4. The threat model already assumes falsified telemetry: an attacker who controls part of the state / reward can
   **poison** an online learner.
5. If the state is raw telemetry, the agent must still learn to recognise attacks (same realism problem, harder
   signal); if the state is detector output, the detector's realism problem remains.
6. Claiming "DRL generalises better" requires the **same realism test** (real or unseen traffic) anyway.

**What actually reduces dependence on realistic data**:
| approach | idea |
|---|---|
| physics-based invariants | the KPM↔URR consistency check is not learned — it holds in any network |
| domain randomisation | train over wide ranges of traffic, load, tamper parameters (works for supervised and DRL) |
| anomaly detection on each network's own baseline | learn "normal" on the target network; no realistic attack data needed |
| small labelled fine-tuning on the target network | start from the testbed model, adapt with a little real data |

**Sound way to use DRL**: DRL for the decision layer only, trained with domain randomisation and a safety layer;
test generalisation directly (train on synthetic traffic, test on **replayed real traces** or unseen generators) and
compare with the rule policy on the same test; claim only what that test shows.

## 5. Online learning protected against falsified KPM: core data as the trusted reference
**Feasible** and consistent with the two-domain architecture. Core telemetry (URR, UPF profiler) is outside the
compromised E2 node's reach, so it can serve as:
1. **A gate on what is learned** — update only on samples where KPM agrees with URR (KPM trust = 1); freeze learning
   while an integrity alarm is active, so falsified KPM never enters the training stream.
2. **A teacher for the RAN model (teacher–student, cross-domain self-supervision)**:
   - teacher = core detector + attack-effect signals measurable at the UPF (unanswered SYNs, UL without matching DL,
     many new destinations, drops) — slow (1.5–2.8 s telemetry delay) but not falsifiable by the gNB;
   - student = RAN detector (KPM arrives in ~1 ms), updated online with the teacher's labels;
   - benefit: the fast RAN model adapts to the real network without manual labels, and keeps working when core data
     is lost.

**What it does not solve**:
- a **malicious UE** still controls its own traffic and can shape it to mislead the teacher (mimicry) — core data
  protects against a lying gNB, not against the UE;
- **slow-poisoning tamper** below the integrity threshold (e.g. a constant ×1.5) passes the gate and drifts the model;
- the **teacher is still trained on testbed data** — the realism problem shrinks but does not vanish;
- a compromised UPF/core would remove the trusted reference (outside the current threat model).

**Safeguards if implemented**: update only when KPM trust = 1 and the teacher is confident (score far from its
threshold); monitor the long-term KPM/URR bias to catch small persistent tampering; bound the update rate; keep a
fixed validation set and roll back on degradation; never let the online-learned model block on its own (keep the
two-domain rule).

**How to test it (offline replay)**: frozen core teacher, RAN student updated online; inject strong, weak-persistent
and drifting tamper; compare a gated vs an ungated student — measure poisoning and post-adaptation accuracy.

## 6. Dataset realism — what to do regardless of the model family
1. Quantify realism of the benign traffic: packet-size and inter-arrival distributions, burstiness (Hurst exponent)
   vs public 5G / mobile traces.
2. Run **real benign applications closed-loop** from the UEs (e.g. nginx + HLS/ffmpeg video, curl with Pareto
   think-time, SIPp/RTP) and run a small evaluation-only campaign with frozen models — the most direct answer to
   "is it realistic?". **Not pcap replay**: replay is open-loop, TCP never completes a handshake against the DN and
   replayed benign traffic looks like a SYN flood (rejected for this reason in the v4 datasheet).
3. Real attack tooling (hping3 exists; botnet samples in an isolated setup).
4. External validation on public datasets (single-domain only — they lack paired KPM/URR).
5. More UEs and background-load variety; real radio (SDR) remains out of scope.
