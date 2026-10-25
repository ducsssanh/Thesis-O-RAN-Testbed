# Cross-Domain Defence Against UE Flooding in O-RAN / 5G SA — System, Experiments and Results

Status: 2026-10-25. Single reference document for the thesis and the paper: what the testbed is, how the defence
works, how it was evaluated offline (v4) and live (v5), what the results are, how far they can be trusted, and
how to reproduce them. Detailed sources are linked in each section; §14 maps every name used here to the code.

---

## 1. Summary

A UE that floods the uplink can exhaust cell and core resources while staying below simple volume thresholds.
The defence in this work is a **near-RT RIC xApp** that observes every UE from **two independent domains** — the
**RAN** (E2SM-KPM reports from the gNB) and the **5G core** (PFCP URR usage reports and an eBPF profiler in the
UPF) — and acts in both: **soft isolation** in the RAN (E2SM-RC slice handover to a quarantine slice) and
**blocking** in the core (UPF Security API).

The contribution is not the classifier alone but **how the two domains are combined when one of them cannot be
trusted**:
- a **KPM↔URR integrity check** detects an E2 node that falsifies KPM (hiding an attacker or framing a benign UE);
- **trust weights** for the KPM and the core telemetry decide which model drives the decision;
- an **asymmetric rule** treats hidden traffic as evidence against the UE but framed traffic only as evidence
  against the E2 node;
- **blocking requires agreement of both domains** (or the core alone when KPM is untrusted).

Three gradient-boosted tree models (GBDT: RAN-only, core-only, cross-domain), trained on a controlled 88-run
testbed dataset (v4), score each UE once per second. Offline, the cross-domain GBDT beats every single domain
(ROC-AUC 0.930) and an LSTM (−0.067 ROC-AUC). **Live** (v5, 224 valid runs, defence acting on the traffic):
- **KPM hiding** (compromised E2 node scales the attacker's KPM to 10 % / 33 %): the proposed defence blocks
  **100 %** of attack phases (naive fusion 62 / 87 %, RAN-only 0 / 33 %); attacker traffic at the data network
  drops from ~500 kbit/s to 0 after the block.
- **KPM framing** (benign UE's KPM ×2 / ×5): the framed UE is wrongly blocked in **0 % / 4 %** of phases
  (naive 46 / 44 %, RAN-only 64 / 62 %) — at the cost of blocking fewer attacks (29 / 42 % vs naive 67 / 79 %).
- **Core telemetry outage**: detection continues through the RAN fallback (75 % of attack phases isolated, none
  blocked by design, no benign UE blocked).
- **Control loop**: one KPM report → E2SM-RC acknowledgement in 39 ms (p50) / 100 ms (p99), inside the near-RT
  10 ms – 1 s bound.

The results are credible as research-prototype evidence for these claims (pre-registered design, validity gating,
paired traffic, documented deviations), with limits stated in §11.

---

## 2. Testbed

| layer | component | notes |
|---|---|---|
| Host | Ubuntu (RT kernel), 18 cores, minikube profile `oai-lab` | 4 namespaces, each 3GPP / O-RAN interface on its own Multus network (n2, n3, n4, n6, e2) |
| RAN (`oai-ran`) | OAI gNB (RF simulator), 2 OAI NR-UEs | KPM via E2SM-KPM, slicing control via E2SM-RC |
| Core (`oai-core`) | OAI AMF, SMF (v2.2.0 + fixes), NRF, AUSF, UDM, UDR; **eBPF/XDP UPF**; DN | UPF: per-SUPI policy maps, URR counters, profiler (packet/byte/protocol counts per UE per second), **Security API** `:8095` (monitor / rate-limit / block, TTL, SQLite persistence, `maxBlockedRatio` 0.5 guard) |
| Near-RT RIC (`near-rt-ric`) | FlexRIC; **defence xApp** (C) + **model sidecar** (Python) in one pod; A1-EI adapter | xApp REST API `:8090` (state, timing, classifier, tamper, reset); sidecar `:8091` (`/classify`, `/healthz`, `/state`, `/mode`, `/reset`) |
| Non-RT RIC (`non-rt-ric`) | O-RAN SC Information Coordination Service; URR producer | SMF event exposure → producer → ICS → A1-EI adapter → xApp |

**Telemetry paths and measured timing** (main campaign, all pods on one node clock):

| path | period | delay measurement → xApp |
|---|---|---|
| gNB → FlexRIC → xApp: E2SM-KPM (UL/DL rate, throughput, PRB of the UE and the cell) | 1 s | p50 1 ms, p99 49 ms |
| UPF → SMF (PFCP usage report) → producer → A1-EI → xApp: URR (volume, packets) + profiler | 1 s (spacing up to 2 s) | p50 1.5 s, p99 2.8 s |

Sources: `docs/SYSTEM-OVERVIEW.md` (node-level description, 05/10 state), `docs/KPM-URR-DATA-PATH.md`,
`docs/KPM-URR-ALIGNMENT.md`, `docs/CLOSED-LOOP-FRAMEWORK.md`, `docs/OAI-UPSTREAM-CHANGES.md` (every change to OAI).

---

## 3. Threat model

| threat | how it is emulated | defence goal |
|---|---|---|
| **UE uplink flooding**, load-matched | per phase one UE floods UL while the other sends benign traffic at the same load (0.4 / 0.8 / 1.2 Mbit/s, below the 2 Mbit/s fair-use threshold); 6 attack families: UDP, TCP SYN, DNS, pulsing, mimicry (on/off Pareto imitating benign UDP), fan-out (many destinations) | detect and stop the flooding UE, not the benign one |
| **Compromised E2 node — KPM hiding** | the xApp's KPM ingest multiplies the attacker's UL rate / throughput / PRB by 0.1 or 0.33 (ground truth logged) | still catch the attacker |
| **Compromised E2 node — KPM framing** | the benign UE's UL KPM × 2 or × 5 (PRB capped at 100 %) | do not punish the framed UE |
| **Core telemetry outage** | A1-EI adapter scaled to 0 in phases 0 and 3 (no URR, no profiler) | keep detecting from the RAN, do not act blindly |
| **Negative control** | ICMP flood vs ICMP ping at the same rate | expose what the features cannot separate |

Out of scope: a network MITM on the E2/SCTP link (the tamper is applied at the xApp ingest, equivalent to a
compromised E2 node), real attack tools / botnets, more than 2 UEs or 1 cell.

---

## 4. Defence design

### 4.1 Per-UE decision step (once per KPM report, in the sidecar; shared code with the offline replay)
1. **Telemetry row** (dataset semantics of the v4 builder): newest KPM (missing if older than 3 s), latest URR and
   profiler record (missing if older than 4 s), their ages.
2. **Features**: each raw value at 1 s plus rolling mean / std / slope / max over 5, 10 and 30 s (221 features for
   the cross-domain model, 169 core, 52 RAN UL).
3. **Scores**: three frozen GBDT models give `p`; normalised `z = p / threshold` (thresholds 0.9641 RAN, 0.9676 core,
   0.9732 cross-domain), so `z ≥ 1` is that model's alarm. Activity gate: UL ≥ 50 kbit/s.
4. **KPM↔URR integrity check**: `r = log(ΣKPM_UL / ΣURR_UL)` over 10 s minus a calibrated bias (−0.048). If
   `|r| > log 2` (the two domains disagree by more than 2×) for 10 consecutive seconds with fresh URR → **integrity
   alarm** (the E2 node is flagged). Not evaluated while the UPF is already blocking or rate-limiting the UE.
5. **Trust**: KPM trust `kt` = 0 for 60 s after an integrity alarm, then ramps back to 1 over 30 s; core trust
   `ct` = 0 when URR / profiler data is older than 4 s, else 1.
6. **Trust-weighted fusion**: `z_fused = kt·ct·z_xd + (1−kt)·ct·z_core + kt·(1−ct)·z_ran` — both domains trusted →
   cross-domain model; KPM untrusted → core model; core missing → RAN model.
7. **Asymmetric rule**: KPM *below* URR (hiding) → the violation itself counts as evidence against the UE;
   KPM *above* URR (framing) → only the E2 node is flagged, the UE is judged on core evidence.
8. **Fair-use evidence** kept per domain (UL > 2000 kbit/s while cell PRB ≥ 80 %, 3 of 4 samples).

### 4.2 Escalation and actuation (xApp, C)
| level | condition | action | reversal |
|---|---|---|---|
| **Isolate** (L1) | fused alarm in 3 of the last 5 s | E2SM-RC slice handover to a quarantine slice (10 % PRB) + UPF "monitor" | expires 3 s after the alarm stops |
| **Block** (L3) | isolated ≥ 10 s **and** core alarm in 3 of 5 s (or the core alone while `kt` < 0.5) | UPF Security API `PUT /v1/ues/<supi>` block, TTL 120 s, no RRC release | expiry / admin reset |
| Fallback | sidecar error or timeout (200 ms) | xApp's rule classifier decides that step | per step |

The UPF refuses a block that would leave more than half of the known UEs blocked (`maxBlockedRatio` 0.5): with
2 UEs the second block is rejected (HTTP 403).

### 4.3 Compared configurations (same sidecar, mode flag; same traffic)
| name in this document | code name | decision |
|---|---|---|
| Fair-use rules | `rules-v1` | xApp rule classifier only (2 Mbit/s fair use under congestion); no ML |
| RAN-only | `ran-only` | RAN GBDT on KPM |
| Core-only | `core-only` | core GBDT on URR + profiler |
| Naive cross-domain | `xd-naive` | cross-domain GBDT, both domains always trusted, no integrity check |
| Trust-weighted v1 | `xd-trust-v1` | integrity check + trust weights, no asymmetric hiding/framing rule |
| **Trust-weighted (proposed)** | `xd-trust-v2` | full design §4.1–4.2 |

Sources: `scripts/ml/defence_engine_v4.py` (engine), `scripts/k8s/classifier/sidecar_v4.py` (sidecar),
`patches/flexric-xapp-*.patch` (xApp), `docs/TWO-LAYER-DEFENSE-DESIGN.md` (early design log). The ML foundations
(features, gradient boosting, thresholds, model choice, why a C xApp + Python sidecar) are in
`research/ML-FOUNDATIONS.md`.

### 4.4 Design rationale — why the pipeline is built this way

**(a) Two domains, because each one alone has a blind spot.**
| domain | sees | cannot see / weakness |
|---|---|---|
| RAN (KPM) | radio resources per UE, 1 s, ~1 ms delay; the UE identity in the cell | only what the E2 node reports — a compromised E2 node can falsify it; no protocol detail |
| core (URR + profiler) | bytes, packets and protocol mix that actually crossed the UPF | 1.5–2.8 s delay; disappears when the core telemetry path fails; no radio context |
Offline, the cross-domain model beats every single domain (§5). More importantly, two independent views of the same
traffic make a **consistency check** possible — the basis of everything below.

**(b) The KPM↔URR integrity check uses a physical invariant.** The UL bytes a UE sends are counted twice: by the
gNB (KPM) and by the UPF (URR). Up to protocol overhead and report timing they must agree, whatever the traffic is,
so a sustained disagreement means one of the counters lies — and only the E2 node is in the threat model.
- *Log ratio* $r=\log(\sum \text{KPM}/\sum \text{URR})$: scale-free (the same at 0.4 and 1.2 Mbit/s) and symmetric
  (×2 and ×0.5 are equally far from 0), so hiding and framing are measured on one axis.
- *Bias* −0.048: the systematic offset between the two counters on honest data, removed before thresholding.
- *10 s sums*: the two reports are not aligned (URR every 1–2 s, delayed); summing over 10 s cancels the jitter.
- *τ = 0.7 ≈ log 2, m = 10 consecutive seconds*: chosen on honest train + validation runs from a grid
  (τ ∈ {0.7 … 1.6}, m ∈ {3, 5, 10}) as the most sensitive setting with ≤ 1 % of honest phases alarmed:
  | τ | m = 3 | m = 5 | m = 10 |
  |---|---|---|---|
  | 0.7 (2×) | 33.7 % | 7.5 % | **0.12 %** |
  | 1.1 (3×) | 17.0 % | 0.95 % | 0 % |
  | 1.6 (5×) | 6.1 % | 0.24 % | 0 % |
  The most sensitive ratio (2×) needs persistence (10 s); a shorter persistence would need a coarser ratio and miss
  ×0.33 hiding. Live: 1 false alarm in 48 honest phases, 0 elsewhere.
- *Not evaluated while the UPF blocks or rate-limits the UE*: then the core drops what the RAN still carries and the
  invariant no longer holds by construction.

**(c) Trust weights select the model that is valid for the available evidence.**
$z_{\text{fused}} = kt\,ct\,z_{xd} + (1-kt)\,ct\,z_{core} + kt\,(1-ct)\,z_{ran}$ reduces to the cross-domain, the
core or the RAN model when both / only the core / only the RAN can be trusted. Each of the three models was trained
on exactly those inputs, so no model ever scores inputs it should not trust, and no extra model per trust state is
needed. *KPM trust* drops at once and is held 60 s, then ramps over 30 s: an attacker cannot regain trust by
behaving for a few seconds, and trust does not flip back and forth at the alarm boundary. *Core trust* is a direct
observation (data age > 4 s), so it switches immediately, without hysteresis.

**(d) Hiding and framing are treated asymmetrically, because they mean different things.** KPM *below* URR is
under-reporting that only benefits the UE being hidden — the discrepancy itself is evidence against that UE, so it
feeds the UE's alarm and the core-only block path. KPM *above* URR is over-reporting that harms the UE being framed —
the E2 node is flagged, and the UE is judged on core evidence alone, so a lying E2 node cannot get a victim blocked.
*Disclosure:* this rule (trust-weighted v2) was added after inspecting the v1 rule on the offline test runs (checked
on the validation runs first; a 60 s hold of the hiding flag was tried and dropped because it spilled into the next
phase on validation). The live campaign is fresh data (new seeds, actions in the loop) and confirms it, but the
offline replay numbers of v2 are not a clean held-out estimate.

**(e) Two escalation levels, because the costs differ.**
- *Isolate* is cheap and reversible: an E2SM-RC slice handover keeps the PDU session and moves the UE to a quarantine
  slice (10 % PRB); it expires 3 s after the alarm stops, so it holds exactly while the alarm holds (the same
  semantics as the offline replay). It needs only 3 alarms in 5 s (offline: one third of the false alarms of a
  1-of-1 rule, §4.3 of ML-FOUNDATIONS).
- *Block* stops the traffic at the UPF — where it is measured and before it reaches the data network — and is costly
  if wrong. It requires the isolation to have held ≥ 10 s **and** independent core evidence (3 of 5 s): two
  independent views agreeing is the strongest guard against a false block. The exception "core alone while KPM is
  untrusted" exists because otherwise a hiding attacker (whose RAN evidence is suppressed) could never be blocked.
- No RRC release on block (UPF block only): the UE stays attached, its traffic remains measurable at the DN, and the
  re-attach path of the testbed is avoided.
- Consequence by design: without core telemetry the system isolates but never blocks (§8.3), and when KPM is
  distrusted it needs stronger core evidence, so it blocks fewer attacks than naive fusion (§8.2) — the price of not
  punishing framed or unverifiable UEs.

**(f) Supporting choices.**
- *Activity gate (10 s mean UL ≥ 50 kbit/s)*: idle UEs produce noise-driven scores and cannot be flooding.
- *Fair-use rules kept as evidence*: they catch high-volume floods the models never saw (outside the training load
  range) and are the fallback when the sidecar is unavailable.
- *One engine for replay and live*: the same Python module computes features and decisions offline and in the
  sidecar, so a live/replay difference is a property of the live system (feedback, delays), not of the code.
- *Step only on a new KPM report*: stale KPM never enters the integrity rule (a stall pauses it instead).
- *Sidecar state carried across gaps, reset per run*: rolling history and trust behave as in the replay; the cost
  was the gap-reset race of §10.1 — a lesson: a reset must clear every component that can re-assert a decision.

---

## 5. Offline stage (v4 dataset, defence off)

- **Dataset**: 88 runs, 1 row = 1 s × 1 UE, labels BENIGN / MALICIOUS / IDLE, 7 attack↔benign pairs controlled for
  the confounds found in v3 (UE identity, generator tool, victim response, packet-size grid, phase-boundary leak).
  `research/datasets/oran_flooding_v4/DATASHEET.md`.
- **Models** (`reports/model_eval_v4.md`): cross-domain GBDT on 30 s rolling UL features ROC-AUC 0.930
  [0.894–0.961], PR-AUC 0.924, TPR at 1 % FPR 0.467; LSTM (2×64, 10 s) worse by −0.067 ROC-AUC; cross-domain beats
  every single domain (vs URR+profiler +0.022, vs RAN UL +0.064); 30 s history > 10 s > 1 s. Weak transfer to an
  unseen generator (0.64–0.79) — a stated limitation.
- **Replay** (`reports/fusion_eval_v4.md`): the same engine run on recorded test runs with simulated tamper —
  the basis of the live hypotheses.

---

## 6. Live experiment design (v5)

- **Pre-registered** before any run (`research/datasets/oran_flooding_v5_live/PREREGISTRATION.md`): frozen image
  tags and sha256 of the sidecar, engine, models, thresholds and manifest; metrics; hypotheses H1–H4; validity rules.
  Nothing was tuned on main-campaign data; every later change is listed there.
- **Design**: 7 scenarios (honest, KPM hide ×0.1 / ×0.33, KPM frame ×2 / ×5, core outage, ICMP control) ×
  6 configurations × 6 repetitions (fair-use rules: 2 repetitions, reference only) = **224 runs**.
- **A run**: setup + 15 s idle, 4 phases × 60 s with 15 s gaps (ICMP control: 2 phases); roles mirrored (UE1 attacks,
  then UE2); the families rotate so each appears in 2 of 6 repetitions; **traffic of a repetition is identical in all
  42 cells** (paired comparison). Defence level and tamper reset at idle and every gap; sidecar state reset at the
  run start.
- **Readiness**: a phase starts only when the xApp holds KPM < 3 s old and URR received < 3 s ago for both UEs
  (≤ 30 s wait, else the run fails).
- **Validity** (`meta_run_ok`): harness ok; attacker visible in the UPF profiler; no KPM / URR / profiler gap > 3 s in
  any phase or gap (except URR in outage phases); flow-row coverage ≥ 90 % (except a UE the defence acted on);
  phase durations within ±20 %; no host suspend. Failed runs are kept and re-run with the same manifest entry.
- **Metrics** per scenario × configuration, unit = (run, UE, phase), 95 % bootstrap CI over runs: attack phases
  isolated / blocked; benign phases wrongly blocked (framed UE apart); time to isolate / block / integrity alarm;
  integrity alarms on untampered phases; attacker and benign packets delivered at the DN (calibrated to the v4
  defence-off median); sidecar latency; fallbacks.
- **Unattended execution**: supervisor (`scripts/k8s/exp/v4traffic/supervise_v5.py`) re-runs entries until valid
  (max 3 attempts), recovers the testbed automatically, and runs QA (`qa_v5.py`) after every 50 runs.

---

## 7. Campaign execution

- 2026-10-24 13:19 → 2026-10-25 15:55; **224/224 valid**, 254 attempts, **30 failed** (all testbed): UE radio-link
  failure followed by a PDU session that is not re-activated (released by the SMF session TTL after 120 s), PFCP
  association loss, xApp container restarts, one xApp↔FlexRIC E42 association stuck (needed a second RAN recovery),
  readiness timeouts. Failures are spread over configurations (3–7 each), so re-running until valid does not favour
  one configuration. Incidents came every 30–90 min under host load 12–16 / 18 cores.
- **QA over the campaign**: no residual UPF policy, xApp level or tamper at any run start; no sidecar step on stale
  KPM; 34 classifier fallbacks in 124,758 calls (0.03 %); 6 runs flagged for a fallback inside a phase (40, 91, 99,
  110, 173, 212) — in the checked cases the sidecar's own answer at those steps was "benign", so no decision changed.
- **Tooling changes during the campaign** (no defence or validity change; PREREGISTRATION "tooling fix 1–5"):
  readiness check; fair-use rules reduced to 2 repetitions; QA stop rules relaxed to serious errors only (residual
  state, stale KPM, sidecar p99 > 200 ms, < 50 % valid, failed recovery); a second recovery pass.

---

## 8. Results (live, clean units)

**Primary analysis = clean units**: 63 of 1536 phases (4.1 %) started with the UE already blocked from the previous
phase (§10.1) and are dropped; the proposed configuration has none. Full tables with all units beside the clean
values: `research/datasets/oran_flooding_v5_live/reports/live_results_v5.md`.

### 8.1 KPM hiding (attacker's KPM scaled at the compromised E2 node)
| configuration | attack isolated | attack blocked ×0.1 / ×0.33 | benign wrongly blocked | integrity alarm on tampered phases |
|---|---|---|---|---|
| Fair-use rules | 0 | 0 / 0 | 0 | – |
| RAN-only | 0.05 / 0.43 | **0 / 0.33** | 0.58 / 0.40 | 0 |
| Core-only | 0.75 / 0.83 | 0.54 / 0.74 | 0 / 0 | 0 |
| Naive cross-domain | 0.83 / 0.91 | 0.62 / 0.87 | 0.17 / 0.14 | 0 |
| Trust-weighted v1 | 0.79 / 0.88 | 0.58 / 0.62 | 0 / 0 | 1.00 |
| **Proposed** | **1.00 / 1.00** | **1.00 [1.00, 1.00] / 1.00** | 0.04 / 0.12 | **1.00** |

Time to block (proposed): median 24 s, p90 29–31 s (minimum by design ~13 s: 3 of 5 s to isolate + 10 s held).
Attacker UL at the DN: median ~500 kbit/s before the block → **0** after it (every blocking configuration).
RAN-only is blind to hiding and instead blocks the benign UE, which now looks heavier.

### 8.2 KPM framing (benign UE's KPM inflated)
| configuration | framed UE wrongly blocked ×2 / ×5 | attack blocked ×2 / ×5 | integrity alarm ×2 / ×5 |
|---|---|---|---|
| RAN-only | 0.64 / 0.62 | 0.33 / 0.27 | 0 |
| Core-only | 0 / 0.04 | 0.50 / 0.67 | 0 |
| Naive cross-domain | 0.46 / 0.44 | 0.67 / 0.79 | 0 |
| Trust-weighted v1 | 0.08 / 0.08 | 0.29 / 0.48 | 0.75 / 1.00 |
| **Proposed** | **0 / 0.04** | 0.29 / 0.42 | 0.75 / 1.00 |

Trade-off: once KPM is distrusted the decision rests on core evidence alone and the block needs stronger evidence,
so fewer attack phases are blocked than with naive fusion, which blocks more of everything (including the framed UE).

### 8.3 Core telemetry outage (outage phases vs phases with core data)
| configuration | outage: attack isolated | outage: attack blocked | outage: benign blocked | core present: isolated / blocked / benign blocked |
|---|---|---|---|---|
| RAN-only | 0.73 | 0.55 | 0 | 0.75 / 0.67 / 0 |
| Core-only | 0 | 0 | 0 | 0.83 / 0.50 / 0.08 |
| Naive cross-domain | 0.42 | 0.42 | **0.25** | 0.92 / 0.67 / 0 |
| Trust-weighted v1 | 0.75 | 0 | 0 | 0.92 / 0.50 / 0 |
| **Proposed** | **0.75** | **0 (by design)** | **0** | 0.92 / 0.67 / 0 |

Blocking requires core evidence by design, so the trust-weighted configurations only isolate during an outage —
the RAN fallback keeps detection alive without acting on unverifiable evidence.

### 8.4 Honest telemetry
Proposed: isolated 0.92, blocked 0.67 [0.46, 0.88], benign wrongly blocked 0.08 [0, 0.17]. RAN-only blocks 0.65 but
wrongly blocks 0.16; core-only blocks 0.42; naive 0.67 with 0 benign blocked. Fair-use rules detect nothing in any
scenario (the floods are load-matched below its threshold).

### 8.5 ICMP negative control
Every ML configuration isolates the ICMP flood (1.00) **and** the benign ping (0.90–1.00): the features cannot
separate them. Benign ping blocked: proposed 0.50, trust-weighted v1 0.58, core-only 0.80, naive 0.92, RAN-only 1.00
— the two-domain block rule limits the damage but does not solve the separability problem.

### 8.6 Control-loop latency (one KPM report → action)
| segment | p50 | p99 | max |
|---|---|---|---|
| E2 indication (gNB measured → xApp) | 1.1 ms | 48.5 ms | 968 ms |
| xApp processing incl. sidecar (KPM arrival → RC sent) | 21.7 ms | 56.6 ms | 106 ms |
| sidecar `/classify` | 19.5 ms | 47.9 ms | 633 ms |
| E2SM-RC sent → gNB ack | 0.4 ms | 1.3 ms | 3.2 ms |
| **RAN loop: KPM measured → RC ack** | **39.0 ms** | **100.2 ms** | **168 ms** |
| decision → UPF policy accepted | 26.0 ms | 64.0 ms | 1022 ms |
| **core loop: KPM measured → UPF policy** | **41.4 ms** | ≈1 s (timer-driven TTL refreshes) | 1554 ms |
| URR measured → xApp (A1-EI path) | 1.5 s | 2.8 s | 4.5 s |

One iteration meets the near-RT bound with margin; the loop period equals the 1 s KPM period (the models use 1 s
features). Decisions using core evidence act on telemetry 1.5–2.8 s old.

### 8.7 Offline replay vs live (selected rows)
| scenario / configuration | measure | replay | live |
|---|---|---|---|
| KPM hide ×0.1 / proposed | attack blocked | 0.99 | 1.00 |
| KPM frame ×5 / proposed | framed UE blocked | 0.02 | 0.04 |
| KPM frame ×5 / naive | framed UE blocked | 0.76 | 0.44 |
| core outage / proposed | attack blocked | 0.18 | 0.33 |
| honest / proposed | attack blocked / benign blocked | 0.34 / 0.01 | 0.67 / 0.08 |

The tamper results transfer from replay to live almost exactly; live blocks more under honest telemetry (actions
change the traffic and the benign/attack contrast) at a higher benign cost. Full table: live_results_v5 §J.

### 8.8 Hypotheses (pre-registered, not targets)
- **H1** proposed ≥ naive on hiding, framing, outage: **holds** for blocking attackers under hiding and for protecting
  benign UEs everywhere; **does not hold** for attack blocking under framing (0.29–0.42 vs 0.67–0.79) and outage
  (0.33 vs 0.54).
- **H2** RAN-only ≈ 0 under hiding: holds at ×0.1 (isolated 0.05, blocked 0); not at ×0.33 (0.43 / 0.33).
- **H3** framed benign wrongly blocked ≤ ~2 % (proposed): 0 % at ×2, 4.2 % (1 of 24) at ×5.
- **H4** integrity false alarms ≈ 0 on untampered phases: 1 of 48 honest phases (2.1 %), 0 elsewhere.

---

## 9. Answers to specific questions

- **Does the xApp meet the O-RAN near-RT control-loop bound (10 ms – 1 s) per request?** Yes: the defence has two
  closed loops sharing one decision per KPM report — the RAN loop (E2SM-RC) at 39 ms p50 / 168 ms max and the core
  loop (UPF API) at 41 ms p50. Housekeeping timers (expiry, TTL refresh, core sync 10 s) are not per-request loops.
- **Is missing KPM treated differently from falsified KPM?** In the engine a missing KPM value enters the integrity
  rule as 0 kbit/s (`defence_engine_v4.py:117`), which would look like hiding. Live this never happens: the sidecar
  steps only on a new KPM report (`sidecar_v4.py:170-171`), so a KPM stall pauses the rule; measured KPM age at every
  step ≤ 0.09 s. Missing URR is never a violation. The replay grid does not have this protection (limitation).
- **Why does blocking stop at 0 in the outage phases?** Two-domain agreement is required to block; without core data
  it cannot be met, so the system isolates only.

---

## 10. Deviations and known artefacts

### 10.1 Block carried over across the gap (analysis correction)
At every gap the harness resets the xApp level; ~0.1 s later the sidecar (not reset at gaps, by design) still answers
"block" for the last step of the phase just ended, the xApp sets the block again with a fresh 120 s expiry, and the
UE enters the next phase blocked. 63 of 1536 phases (38 runs) + 7 ICMP phases: RAN-only 43, naive 16, core-only 8,
trust-weighted v1 3, **proposed 0**. These units are dropped from the primary analysis; uncorrected values are
reported beside them. The correction lowers the baselines (e.g. RAN-only blocked under hiding ×0.1: 0.21 → 0). A fix
for future campaigns: reset again after the sidecar's first post-phase answer, or reset the sidecar's block hold at
the gap (`scripts/ml/carryover_v5.py`).

### 10.2 "Blocked" is the xApp's decision; the UPF may refuse it
With 2 UEs the UPF `maxBlockedRatio` guard rejects the second block. Attacker blocks were enforced in 95–96 % of
phases for core-only, trust-weighted v1 and the proposed configuration, 75 % naive, 62 % RAN-only; wrong blocks of
benign UEs were enforced in 30–67 %. The delivered fraction at the DN is the measured effect.

### 10.3 Other
Pilot runs (42 cells, other seed) are excluded from every result (the evaluation refuses another manifest).
Sensitivity without the 6 flagged runs: detection/block rates change by ≤ 0.10.

---

## 11. Credibility

**Credible for**: the hiding result (100 % blocked, CI [1.00, 1.00], replay = live), the framing protection
(0–4 % vs 44–64 %), the outage fallback behaviour, the integrity check's false-alarm rate, and the loop latency.

**Why**: pre-registered and frozen design with hashes; no tuning on main data; paired traffic across configurations;
validity gating and QA on every run; failures re-run and spread evenly; sensitivity checks; every deviation
documented with its cause.

**Caveats that must accompany the numbers**:
1. 6 repetitions per cell → CIs of ±15–30 points; only large differences are established.
2. 2 UEs, 1 cell, RF simulator; traffic generators, not real attackers; tamper at the xApp ingest, not on the wire.
3. The carry-over artefact was corrected in the analysis, not by re-running.
4. Blocking is limited by the UPF guard with 2 UEs.
5. Unfavourable results: fewer attacks blocked than naive fusion under framing and outage; flood vs ping not separable.
6. Core telemetry is 1.5–2.8 s stale.
7. Offline: weak transfer to unseen traffic generators (ROC-AUC 0.64–0.79).

**Bottom line**: on a live OAI testbed, cross-domain fusion with a KPM↔URR integrity check and trust weighting keeps
detection working when an E2 node is compromised — it blocks every hidden attacker and almost never blocks a framed
UE — within a ~40 ms control loop, at the cost of lower recall than naive fusion when one domain is distrusted.
Research-prototype evidence, not production readiness.

---

## 12. Limitations and future work
More UEs and cells (the block guard and per-cell PRB effects change with scale); real E2/SCTP MITM; real attack
tools; faster core telemetry (direct UPF→xApp path); a feature set that separates protocol-identical floods (packet
timing, destination entropy); fix the gap-reset race and re-run the affected configurations; train models on
sub-second KPM to shorten the loop period.

---

## 13. Figures and tables

Data figures (matplotlib, 95 % CI): `research/datasets/oran_flooding_v5_live/reports/figures/`; structure diagrams
(Mermaid): `.../figures/mermaid/` (plan in its `README.md`).

| | conference paper (12 pages) | thesis |
|---|---|---|
| Fig. | 1 architecture (`P1_architecture.mmd`); 2 decision step (`P2_decision_pipeline.mmd`); 3 configuration comparison (`fig_a_live_configs.pdf`); 4 one-run timeline (`fig_c_timeline.pdf`); 5 tamper sensitivity replay vs live (`fig_b_tamper_sensitivity.pdf`, optional) | all of the paper + testbed deployment, telemetry/actuation sequence, escalation and trust state machines, run timeline, supervisor/QA flow, carry-over sequence (`T1`–`T7`) |
| Table | I threat model + configurations; II headline numbers (§8.1–8.4); III loop latency (§8.6) | all of the paper + ICMP control, outage isolate vs block, hiding time-to-block and DN bytes, decided vs enforced blocks, replay vs live, sensitivity, failures and carry-over per cell, offline model comparison (v4) |
| Text only (paper) | ICMP control, enforced vs decided, carry-over deviation, failures | – |

---

## 14. Reproduction and file map

**Analysis pipeline** (`.venv-ml/bin/python -I`):
1. `scripts/ml/live_eval_v5.py --manifest research/datasets/oran_flooding_v5_live/manifest/design.json artifacts/experiments/*_v5live_main_s*`
2. `scripts/ml/carryover_v5.py` → 3. `scripts/ml/loop_latency_v5.py` → 4. `scripts/ml/live_extra_v5.py`
5. `scripts/ml/figures_v5.py --eval research/datasets/oran_flooding_v5_live/reports --run artifacts/experiments/20261024-164959_v5live_main_s1/runs/xd-trust-v2/rep-41`

**Campaign**: `scripts/k8s/exp/v4traffic/supervise_v5.py --manifest .../design.json --tag main --config-reps rules-v1=1,3 --chunk 50 --max-recoveries 30`
(harness `scripts/k8s/exp/run.py`, `campaign.py`, `integrity.py`, `qa_v5.py`, live view `watch_v5.py`).

| what | where |
|---|---|
| ML foundations: features, gradient boosting math, thresholds, model choice, xApp + sidecar architecture | `research/ML-FOUNDATIONS.md` |
| pre-registration, frozen hashes, all deviations | `research/datasets/oran_flooding_v5_live/PREREGISTRATION.md` |
| v5 datasheet / handoff | `research/datasets/oran_flooding_v5_live/{DATASHEET,HANDOFF}.md` |
| live results (primary) / as pre-registered | `.../reports/live_results_v5.md` / `.../reports/live_eval_v5.md` |
| v4 dataset, models, offline evaluation | `research/datasets/oran_flooding_v4/` (`DATASHEET.md`, `reports/model_eval_v4.md`, `reports/fusion_eval_v4.md`), `artifacts/ml/v4/models/` |
| raw runs (not in git, never delete) | `artifacts/experiments/*_v5live_main_s*/` |
| testbed operation, recovery | `docs/K8S-LAB.md`, `docs/K8S-A1-EI.md`, `scripts/k8s/phase0/recover_ran.sh`, `recover_core_ordered.sh` |
| changes to OAI / FlexRIC | `docs/OAI-UPSTREAM-CHANGES.md`, `patches/` |

**Glossary**: KPM — E2SM-KPM key performance measurements from the gNB; URR — PFCP usage reporting rule (volume and
packet counters from the UPF via the SMF); E2SM-RC — RAN control service model (slice handover, PRB quota); A1-EI —
enrichment-information path from the Non-RT RIC; SUPI — subscriber identity used to join both domains; phase — 60 s
traffic interval with fixed roles; isolate / block — the two escalation levels (L1 / L3 in code); clean units —
phases that did not start already blocked.
