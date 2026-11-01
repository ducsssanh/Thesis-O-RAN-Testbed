# DRL direction — sequential detection of UL flooding (notes for later study)

Status: 2026-10-27, draft to be verified. Notes from the design discussion about moving the defence towards deep
reinforcement learning (DRL). Nothing here is implemented. Read with `research/CROSS-DOMAIN-DEFENCE.md` (testbed,
threat model, telemetry, data).

Main idea: use DRL for **sequential detection** — at every second, per UE, decide *whether there is already enough
evidence to raise an alarm, or whether to wait one more second* — over two telemetry domains, one fast but
falsifiable (RAN), one trusted but slow and possibly missing (core). Mitigation after an alarm is a fixed mapping onto
the existing actuators. A DRL policy for the escalation itself is kept as a possible extension (§6).

### Decisions of 2026-10-30 (supersede the text below where they conflict)
1. **Core telemetry is assumed always delivered.** No core-outage scenario (threat model: trusted core). Below,
   "core may be missing / outage" rows are dropped; only the delay of core data is modelled.
2. **Primary core source = UPF eBPF profiler, not URR.** The profiler gives, per session and per 1 s window, UL/DL
   bytes and packets of the inner IP PDU (same basis as URR) plus the behaviour counters, counted **before** the
   UPF policy (what the UE offered — matches what the gNB measures, so it is the core side of the KPM ↔ core gate).
   URR (PFCP via SMF) leaves the decision path: it counts only **forwarded** traffic, so it stays as the verifier of
   a UPF action (block → 0, ratelimit → ≤ cap), as the standard 3GPP reference and as the latency baseline. Below,
   "URR" in observation / consistency / teacher text reads "core volume (profiler)".
3. **Measured core delay** (time a record reaches the xApp after the KPM of the same second; 5 min idle, 2 UEs,
   testbed 2026-10-30). The "1.5 s p50 / 2.8 s p99" below was an underestimate:

   | | before (v4, 88 runs) | before (testbed) | after removing polling |
   |---|---|---|---|
   | URR | p50 2.04 / p99 3.65 s | p50 2.00 / p99 3.30 s | p50 **0.58** / p99 **0.78** s |
   | profiler | p50 1.90 / p99 3.41 s | p50 2.46 / p99 3.70 s | p50 **0.23** / p99 **0.24** s |

   The delay was polling in the exposure path (producer delivered every 2 s, adapter slept 1 s when idle, the
   producer pulled the UPF ring on a free-running 1 s ticker), not the network or the core. Fix: deliver on enqueue,
   pull just after the UPF window tick (`src/urr-producer`, `src/a1-ei-adapter`); the A1-EI path is unchanged.
   Open: URR now arrives every 2 s per UE although the SMF sets a 1 s period (v4: 1 s in ~85 % of gaps).
4. **Consequence for DRL.** With core data 0.23 s behind KPM (inside the same KPM period), "wait for core" costs
   less than one step in the honest case, so the "when to decide" gain shrinks. The DRL value has to be shown on
   (a) evasive attacks where only behaviour separates (profiler) and (b) KPM hide / frame, against a strong
   "always use core" baseline. The KPM ↔ core gate stays a fixed physical check, not learned.
5. **Actuation path.** The xApp calling the UPF Security API directly is non-standard; the target is 3GPP policy
   control (xApp as AF → NEF → PCF → SMF → N4 QER/FAR → eBPF UPF enforces). Feasibility in OAI (PCF/NEF, dynamic
   PCC, QER gate) still to be checked. The UPF reflex stays, configured by the operator, not by the xApp.

---

## 1. Research problem — what the thesis has to solve

### 1.1 Context
- 5G connects very many UEs (phones, IoT, CPE). A compromised UE — or many of them, a botnet — can **flood the
  uplink**: it consumes radio resources (PRBs) of the cell, user-plane capacity of the UPF and the services in the
  data network, degrading service for the legitimate users around it.
- The uplink is the natural place to stop such a UE: as close to the source as possible, **before** the traffic
  leaves the mobile network (N6), and per UE (per SUPI), not per IP flow.
- O-RAN makes this possible in a new way: a **near-RT RIC xApp** can see per-UE RAN measurements (E2SM-KPM) within
  ~1 s and control the RAN (E2SM-RC); with exposure of core data (here via A1-EI) the same xApp can also see what the
  core sees for that UE and command the UPF. One component can therefore observe and act in **two domains**.

### 1.2 The problem
**How can a near-RT RIC xApp detect a UE that floods the uplink as early as possible — without raising alarms on
legitimate users — when the attack is hard to separate by volume and the telemetry it relies on may be falsified or
missing?**

It is hard because of four facts that hold together:
1. **Load-matched attacks.** A flood at a rate comparable to legitimate heavy users (video upload, sync, IoT bursts)
   stays below any volume / fair-use threshold. Volume alone (RAN KPM, core URR) cannot separate attacker from heavy
   benign user; behaviour (protocol mix, SYN share, packet size, number of destinations) can — but only the core
   (UPF) sees it.
2. **The RAN telemetry is not trustworthy.** The xApp's fastest data (KPM) comes from the E2 node. O-RAN opens the
   RAN to multi-vendor software and open interfaces; a compromised or faulty E2 node can report false per-UE
   measurements — **hide** an attacker (nothing is done) or **frame** a legitimate UE (it is blocked). A RAN-only
   defence trusts exactly the data an attacker in the RAN controls.
3. **The trustworthy telemetry is slow and can disappear.** Core data (URR, UPF profiler) is out of the E2 node's
   reach, but arrives 1.5–2.8 s later through the exposure path and can be lost (core / exposure outage). A
   core-only defence is slower and blind during an outage.
4. **When to decide is itself the decision.** Every second of waiting lets attack traffic through; deciding on the
   first suspicious sample lets a lying gNB steer the defence. The right waiting time depends on which sources are
   present, whether they agree and how long the suspicion has lasted — it differs per situation.

### 1.3 Gap
Commonly a defence of this kind (to be confirmed against the literature review):
- uses **one domain** — RAN KPIs at the RIC, or flow / packet data in the core — not both for the same UE;
- assumes the telemetry is **correct and complete** (no falsified E2 data, no outage);
- treats detection as **per-sample classification** (one verdict per window) and adds fixed rules for when to act
  ("N alarms in M seconds", "both domains must agree"), which fix one speed–safety trade-off for every situation;
- is evaluated **offline** (accuracy on a dataset), not by detection delay vs false alarms, and not in a **closed
  loop** that acts on the network.

### 1.4 Contributions (what the thesis does)
1. **Cross-domain xApp and testbed** — joins, per UE and per second, RAN telemetry (KPM) and core telemetry (URR +
   UPF eBPF profiler) by SUPI, and acts in both domains (RAN slice isolation, UPF rate-limit / block) on a real 5G SA
   software stack (OAI RAN + 5GC + FlexRIC). *Built.*
2. **Cross-domain dataset with controlled confounds and telemetry attacks** — load-matched attack ↔ benign pairs,
   KPM hiding / framing and core outage with ground truth (v4, v5). *Built.*
3. **Sequential detection with DRL** *(candidate contribution, §2–§4)* — a learned stopping policy that decides per
   UE per second "alarm now / wait", using the physical KPM ↔ URR invariant to recognise falsified RAN telemetry;
   evaluated by detection delay vs false-alarm rate against classifier + fixed rules and against classical
   sequential tests (CUSUM). *To be done.*
4. **Closed-loop evaluation** — alarm → UPF block on the live testbed: attack bytes reaching the DN, time to
   mitigation, legitimate UEs wrongly blocked, under honest telemetry, hidden attacker, framed UE and core outage.
   *Harness built.*

### 1.5 Research questions
1. Does joining RAN and core telemetry detect load-matched UL floods that a single domain misses?
2. Can falsified RAN telemetry (hiding, framing) be recognised and neutralised using the core as reference?
3. At the same false-alarm rate, does a DRL sequential detector raise the alarm **earlier** than classifier + fixed
   rules and than CUSUM — in particular, is it fast when both domains agree and not fooled when KPM is framed?
4. Does the advantage hold for attack families and loads unseen in training, and when core telemetry is lost?

### 1.6 Boundaries
Emulated radio (RFsim), one cell, few UEs, synthetic traffic generators, tampering emulated at the xApp ingest; the
core is trusted. The thesis shows the approach on a realistic software stack, not operator-scale performance.

---

## 2. Sequential detection — the idea

### 2.1 Per-sample classification vs sequential detection
- **Per-sample classification**: every second, look at the data and answer *attack* or *benign*. Each second is an
  independent question; there is no option "not sure yet".
- **Sequential detection**: evidence accumulates over time; every second the detector chooses **continue** (not
  enough evidence, observe one more second) or **alarm** (stop, hand over to mitigation). *When* to stop is part of
  the decision.

In continuous monitoring a UE is never "finished" as benign — "benign" simply means *continue*; the attack can start
at any time (an unknown change point). Two forces pull against each other:
- alarm early → little attack traffic gets through, but more false alarms;
- alarm late → more certain, but every second of waiting lets attack traffic through.

Goal: **minimum detection delay subject to a bound on the false-alarm rate.**

### 2.2 Examples on the testbed (UE1 starts a SYN flood at t = 0, 0.8 Mbit/s, same load as benign UE2)
**Honest telemetry**

| t | observed | right decision |
|---|---|---|
| 0 | KPM: UE1 UL rises to 0.8 Mbit/s; no core data yet (1.5–2.8 s delay) | heavy benign users do this too → continue |
| 1 | KPM still high; core still pending | continue |
| 2 | URR arrives, bytes agree with KPM; profiler: ~90 % SYN, many destinations | trusted evidence, clear → **alarm** |

**KPM hiding** (gNB reports UE1 at 0.08 Mbit/s)

| t | observed | right decision |
|---|---|---|
| 0–1 | KPM low, looks normal | a KPM-only detector concludes benign (wrong); a good one keeps watching for core data |
| 2 | URR 0.8 Mbit/s vs KPM 0.08: ×10 mismatch, violates the physical invariant; profiler shows SYN | KPM is falsified → **alarm** |

**KPM framing** (gNB reports benign UE2 × 5)

| t | observed | right decision |
|---|---|---|
| 0 | KPM: UE2 at 4 Mbit/s, above even the fair-use threshold | a fixed rule blocks immediately (wrong) → continue |
| 2 | URR: UE2 at 0.8 Mbit/s, normal behaviour | KPM is false → **no alarm on UE2** |

**Core outage** — URR / profiler never arrive. Waiting for them forever lets the attack through; the detector has to
alarm on KPM alone but more cautiously (more consecutive anomalous seconds).

In all four cases the hard question is not "attack or benign" but **"is it time to trust the evidence yet?"** — and
the answer depends on which sources are present, whether they agree, and how long the anomaly has lasted.

### 2.3 Why a classifier + fixed rules falls short
A classifier at t = 0 in the framing case sees "UE2 = 4 Mbit/s" and answers *attack*; it has no notion of "wait 2 s,
better evidence is coming". The usual patch is a rule outside the classifier ("3 alarms in 5 s", "both domains must
agree") — exactly the earlier design of this thesis. Such a rule fixes **one** waiting time for every situation:
long → slow in the honest case (both domains agree and could alarm at once); short → fooled by framing. One fixed
waiting time cannot be optimal in both.

### 2.4 Theory
Sequential hypothesis testing and **quickest change detection** are classical:
- **SPRT** (Wald, 1945): accumulate the log-likelihood ratio; above the upper threshold → H1, below the lower → H0,
  in between → continue.
- **CUSUM** (Page, 1954): detects a change of distribution (attack onset) with minimum delay for a given false-alarm
  rate (optimal in Lorden's minimax sense).
- Standard criterion: minimise the (worst-case or average) **detection delay** subject to a lower bound on the
  **mean time to false alarm**.

These are optimal when the probability model of the data is known and the data come from one regularly sampled
source. Here none of that holds: two sources with different delays, one possibly falsified on purpose, one possibly
missing, no known traffic distribution. Hence learning the stopping rule from data: formulated as a (partially
observable) MDP, sequential detection is an **optimal stopping** problem, which DRL can solve. (Literature to look up
for related work: DRL for quickest change detection / optimal stopping; RL-based early classification of time series.)

---

## 3. Formulation

### 3.1 Setting
- One cell, *N* UEs (2 in the testbed), the xApp as the single decision point, step Δt = **1 s** (KPM period); the
  near-RT bound (10 ms – 1 s) and the sidecar timeout (200 ms) bound the decision time.
- Adversaries (`CROSS-DOMAIN-DEFENCE.md` §5):

| adversary | capability | cannot |
|---|---|---|
| flooding UE | UL flood (UDP, TCP SYN, DNS, pulsing, mimicry, fan-out) at 0.4 / 0.8 / 1.2 Mbit/s, load-matched to benign heavy users, starts / stops at will | change what the UPF counts and profiles for its packets |
| compromised E2 node | falsify KPM: hide the attacker (× 0.1 / × 0.33) or frame a benign UE (× 2 / × 5) | touch URR / profiler (produced in UPF / SMF) |

Assumption: UPF, SMF and the A1-EI path are trusted → one **fast, falsifiable** domain and one **slow, trusted,
possibly missing** domain.

### 3.2 Observation (per UE *u*, step *t*)
| group | content | delay / reliability |
|---|---|---|
| RAN (E2SM-KPM) | UL/DL rate, throughput, PRB %, cell PRB % | ~1 ms; may be falsified |
| core volume (UPF profiler) | UL/DL bytes, packets → rates (counted before the UPF policy) | 0.23 s p50, 0.24 s p99 after the 2026-10-30 fix; trusted |
| core behaviour (UPF profiler) | TCP / SYN / UDP / ICMP / DNS counts, fragments, mean packet size, destination-count estimate | same record as core volume |
| freshness | age of each source; stale beyond 3 s (KPM) / 2 s (profiler) | — |
| cross-domain consistency | log(KPM UL bytes / (profiler UL bytes − β·profiler UL packets)), both of the **same measurement second** (profiler `time_unix`, not arrival); β ≈ 57 B/packet, benign 1–99 % band −0.18…+0.16 (v4) — the physical invariant | only when both are fresh |
| history | the above for the last *k* seconds (k ≈ 5–10), or a recurrent policy (GRU/LSTM) | — |

Hidden: whether *u* attacks, when it started, whether its KPM is falsified, whether core is down → a POMDP; in
practice an MDP over a short observation history.

Design choice to make: (a) features directly (the agent learns detection and stopping together), or (b) per-domain
anomaly / detector scores as input (smaller state, but a supervised detector has to be rebuilt).

### 3.3 Actions
- Base: **{continue, alarm}** per UE per second.
- Optional richer variant: **{continue, suspect, alarm}** — *suspect* maps to a cheap reversible action (isolation /
  UPF monitor), *alarm* to a block; gives the agent a middle step at low cost.
- Safety outside the policy: no alarm on a UE whose block the UPF guard would refuse (`maxBlockedRatio` 0.5); fallback
  to the rule detector if the policy is unavailable.

### 3.4 Reward (per UE)
| situation | reward |
|---|---|
| continue, UE benign | 0 |
| continue, UE attacking | − c per second (or − α × attack bytes that second) — the cost of delay |
| alarm, UE attacking | + R (or 0; the episode for this UE ends, delay already paid) |
| alarm, UE benign | − C_FA (large) — false alarm |

The ratio C_FA / c is the speed–safety knob. Equivalent constrained form: minimise expected delay subject to
false-alarm rate ≤ ε (Lagrangian, e.g. PPO-Lagrangian; sweeping ε gives the delay–false-alarm curve). Labels (who
attacks, onset time, which KPM is tampered) come from the manifest and the tamper log — available for training and
evaluation, not online (§8).

### 3.5 Episodes and environment
- Episode: one UE through one phase plus the idle / gap before it (a run = 15 s idle, 4 phases × 60 s, 15 s gaps;
  one UE attacks per phase, roles mirrored), so each episode has either one attack onset or none; it ends at the
  first alarm or at the end of the phase. Onset times are randomised by cropping the pre-phase segment.
- **Key advantage over a mitigation policy**: the action *continue* does not change the traffic or the telemetry,
  and *alarm* ends the episode. The environment is therefore an **exact replay** of recorded traces — no actuation
  model, no sim-to-real gap from actions. It is also suitable for **offline RL** (every trajectory can be replayed
  with every stopping time).
- Telemetry attacks injected on replay: KPM hide / frame by scaling (factors and onset randomised), core outage by
  dropping URR / profiler (timing randomised); domain randomisation over families, loads, onset times.
- Algorithms: DQN (discrete, 2–3 actions) or PPO, small MLP or GRU; a few-KB policy.

### 3.6 Data
| data | use |
|---|---|
| v4 (`oran_flooding_v4`, defence off): 88 runs, 87,294 UE-seconds, 7 attack ↔ benign pairs, controlled confounds | main training / test traces — defence off, so the traffic is not disturbed by any action; split by run and by family |
| v5 live (`oran_flooding_v5_live`): 224 runs, real KPM hide / frame and core outage | real tamper / outage timing to validate the injection; traces up to the first action of the old defence; closed-loop reference |

### 3.7 Mitigation after an alarm
Fixed mapping onto existing actuators: alarm → UPF block via the Security API (+ optional RAN isolation); release
after a fixed TTL; the UPF guard stays. Mitigation is not learned in the base version.

---

## 4. Evaluation

### 4.1 Metrics
- **Detection delay**: seconds from attack onset to alarm, and attack bytes delivered before the alarm.
- **False-alarm rate**: alarms on benign UEs per benign UE-hour (or per benign phase).
- **Miss rate**: attack phases with no alarm.
- Reported **per scenario** (honest, KPM hide, KPM frame, core outage) and as a **delay vs false-alarm curve**
  (sweep ε or the threshold of each method) — the standard comparison in quickest detection; compare delays at equal
  false-alarm rate.

### 4.2 Baselines
1. Supervised classifier per second (same features) + fixed rules ("N of M seconds", "both domains agree").
2. CUSUM per source (KPM, URR, profiler) and on the KPM ↔ URR consistency, with a fixed fusion rule.
3. Fixed "always wait for core" detector (safe, slow; blind during outage).
4. The xApp's built-in fair-use rules + escalation (`src/flexric/examples/xApp/c/monitor/policy_rules.h`,
   `defense.c`).
5. Oracle bound: the earliest second at which the attack is detectable with the ground truth (lower bound on delay).

### 4.3 Expected result if DRL helps
- **faster in the honest case** (no unnecessary waiting when both domains agree);
- **not fooled in the framing case** (waits for core when KPM is anomalous but URR has not confirmed);
- **graceful under core outage** (falls back to cautious KPM-only alarms).
A single fixed waiting time cannot achieve the first two together; that is the claim to test.

### 4.4 Steps
1. Replay environment on v4 + injection; unit tests against the manifest labels.
2. Baselines 1–3 on the same splits; delay–false-alarm curves.
3. DRL agent; same curves; generalisation (leave-one-family-out, unseen loads, unseen tamper factors).
4. Deploy the policy in the sidecar (`127.0.0.1:8091`, already the plug-in point); small pre-registered live
   campaign (alarm → block) on the testbed.
Effort (rough): environment 3–5 days, baselines 2–3 days, DRL 1–2 weeks, integration + live 3–5 days.

---

## 5. Risks and objections
- **"Why not a classifier?"** — answered only if the gain is in the **delay at equal false-alarm rate**, especially
  across scenarios; if the curves coincide, DRL brings nothing. Show the curves.
- **Reward sensitivity**: low C_FA → alarms on everything; high → never alarms; report the full curve, not one point.
- **Explainability**: inspect the learned stopping behaviour (e.g. waiting time vs KPM/URR agreement and source
  availability) to show it learned a sensible rule.
- **Generalisation**: synthetic traffic only — the realism problem remains (§7, §9).
- **Adversarial**: a UE can adapt to the stopping rule (slow ramp-up, mimicry); a gNB can tamper below the
  consistency threshold. Test ramp-up and small persistent tamper factors.

---

## 6. Extension: DRL for the escalation / mitigation policy
After the sequential detector, a second learned layer could choose the defence level over time (when to isolate,
rate-limit, block, release) instead of the fixed mapping of §3.7.

| element | proposal |
|---|---|
| state | detector output / alarm state, KPM ↔ URR consistency, current level and time held, number of UEs blocked |
| actions | target level 0 normal · 1 isolate (RAN quarantine slice + UPF monitor) · 2 rate-limit (UPF) · 3 block (UPF) |
| reward | − attack bytes to DN − β × benign bytes lost − C × wrong block − c × level change |
| safety | UPF guard, TTL bounds, rule fallback |

Harder than detection: actions change the traffic and remove their own evidence (a blocked UE sends nothing), so the
environment needs an **actuation model** calibrated on v5 (block → DN UL ≈ 0 within ~26 ms of policy acceptance; URR
≈ 0 while blocked; isolation ≈ no throttling at 0.4–1.2 Mbit/s in RFsim) — a sim-to-real gap the detection task does
not have. Baseline: the xApp's 4-level escalation (block only with KPM and URR evidence within 10 s; level expiries
60 / 180 / 600 s, probation 180 s).

---

## 7. Misconception to avoid: "DRL reacts to the environment, so dataset realism matters less"
DRL does **not** remove the dataset-realism problem; it moves it into the training environment.
1. A policy trained in a testbed / simulator is a fixed function after training; on real traffic it meets the same
   **sim-to-real gap** as a supervised model (RL is often *less* robust to distribution shift).
2. Adapting **online** in a real network needs a **reward**, i.e. knowing whether a decision was right — ground truth
   is not available online (proxies such as complaints or resource exhaustion are late and noisy).
3. Online learning means **exploring on real users** (deliberately blocking / allowing to learn) — unacceptable to an
   operator.
4. The threat model already assumes falsified telemetry: an attacker who controls part of the state / reward can
   **poison** an online learner.
5. Whether the state is raw telemetry or detector output, the agent still has to recognise attacks — the realism of
   the training traffic still bounds what it learns.
6. Claiming "DRL generalises better" requires the **same realism test** (real or unseen traffic) anyway.

**What actually reduces dependence on realistic data**:
| approach | idea |
|---|---|
| physics-based invariants | the KPM ↔ URR consistency is not learned — it holds in any network |
| domain randomisation | train over wide ranges of traffic, load, tamper parameters |
| anomaly detection on each network's own baseline | learn "normal" on the target network; no realistic attack data needed |
| small labelled fine-tuning on the target network | start from the testbed model, adapt with a little real data |

**Sound way to use DRL here**: for the *when-to-decide* part (sequential detection, possibly escalation), trained
with domain randomisation and a safety layer; test generalisation directly (unseen generators, real applications —
§9) and compare with the baselines on the same test; claim only what that test shows.

## 8. Online learning protected against falsified KPM: core data as the trusted reference
**Feasible** and consistent with the two-domain architecture. Core telemetry (URR, UPF profiler) is outside the
compromised E2 node's reach, so it can serve as:
1. **A gate on what is learned** — update only on samples where KPM agrees with URR; freeze learning while a
   consistency alarm is active, so falsified KPM never enters the training stream.
2. **A teacher for the RAN side (teacher–student, cross-domain self-supervision)**:
   - teacher = core-based detection + attack-effect signals measurable at the UPF (unanswered SYNs, UL without
     matching DL, many new destinations, drops) — slow (1.5–2.8 s) but not falsifiable by the gNB;
   - student = the fast RAN-side detector (KPM in ~1 ms), updated online with the teacher's labels;
   - benefit: the fast side adapts to the real network without manual labels and keeps working when core data is
     lost.

**What it does not solve**:
- a **malicious UE** still controls its own traffic and can shape it to mislead the teacher (mimicry) — core data
  protects against a lying gNB, not against the UE;
- **slow-poisoning tamper** below the consistency threshold (e.g. a constant × 1.5) passes the gate and drifts the
  model;
- the **teacher is still trained on testbed data** — the realism problem shrinks but does not vanish;
- a compromised UPF / core would remove the trusted reference (outside the threat model).

**Safeguards if implemented**: update only when KPM and URR agree and the teacher is confident; monitor the long-term
KPM / URR bias to catch small persistent tampering; bound the update rate; keep a fixed validation set and roll back
on degradation; never let the online-learned side block on its own.

**How to test it (offline replay)**: frozen core teacher, RAN student updated online; inject strong, weak-persistent
and drifting tamper; compare a gated vs an ungated student — measure poisoning and post-adaptation accuracy.

## 9. Dataset realism — what to do regardless of the model family
1. Quantify realism of the benign traffic: packet-size and inter-arrival distributions, burstiness (Hurst exponent)
   vs public 5G / mobile traces.
2. Run **real benign applications closed-loop** from the UEs (e.g. nginx + HLS/ffmpeg video, curl with Pareto
   think-time, SIPp/RTP) and run a small evaluation-only campaign with frozen policies — the most direct answer to
   "is it realistic?". **Not pcap replay**: replay is open-loop, TCP never completes a handshake against the DN and
   replayed benign traffic looks like a SYN flood (rejected for this reason in the v4 datasheet).
3. Real attack tooling (hping3 exists; botnet samples in an isolated setup).
4. External validation on public datasets (single-domain only — they lack paired KPM / URR).
5. More UEs and background-load variety; real radio (SDR) remains out of scope.
