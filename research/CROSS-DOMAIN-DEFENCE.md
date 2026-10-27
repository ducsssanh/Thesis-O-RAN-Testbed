# Cross-Domain Defence Testbed — System, Threat Model, Telemetry and Data

Status: 2026-10-27. Reference for the testbed and the data. The earlier ML defence (GBDT models, sidecar engine,
evaluation, results) was **removed** on 2026-10-27: the direction changed to deep reinforcement learning, see
`research/DRL-DIRECTION.md`. Removed code and reports remain in git history; removed ML artifacts are backed up in
`~/backups/oran-ml-artifacts-20261027.tar.gz`.

---

## 1. Problem
A UE that floods the uplink can exhaust cell and core resources while staying below simple volume thresholds
(load-matched to legitimate high-load users). The thesis studies detecting and mitigating such UEs from a near-RT RIC
xApp that observes every UE from **two domains** — the RAN (E2SM-KPM from the gNB) and the 5G core (PFCP usage reports
and an eBPF profiler in the UPF) — and acts in both (E2SM-RC slice isolation, UPF blocking), including when one
domain's telemetry is falsified (compromised E2 node) or missing.

## 2. Testbed (5G SA, emulated)

| layer | component | notes |
|---|---|---|
| Host | Ubuntu (RT kernel), 18 cores, minikube profile `oai-lab` | 4 namespaces; each interface on its own Multus network (n2, n3, n4, n6, e2) |
| RAN (`oai-ran`) | OAI monolithic gNB (no CU/DU split) over the **RF simulator**, 2 OAI NR-UEs | band n78 TDD, 3.6192 GHz, 30 kHz SCS, 106 PRB (~40 MHz), TDD period 5 ms (7 DL / 2 UL slots + mixed); PLMN 001/01, TAC 7; E2 agent in the gNB |
| Core (`oai-core`) | OAI 5GC v2.2.0: AMF, NRF, AUSF, UDM, UDR; SMF v2.2.0 + patches (URR, PFCP User ID, session TTL); **eBPF/XDP UPF** (patched: Security API, profiler, URR); DN container | service-based architecture; N2 NGAP, N3 GTP-U, N4 PFCP, N6 |
| Near-RT RIC (`near-rt-ric`) | FlexRIC; **defence xApp** (C) with a classifier **sidecar** container (stub since 2026-10-27); A1-EI adapter | xApp REST API `:8090`; sidecar `:8091` (`/classify`, `/healthz`, `/mode`, `/reset`) |
| Non-RT RIC (`non-rt-ric`) | O-RAN SC Information Coordination Service; URR producer | SMF event exposure → producer → ICS → A1-EI adapter → xApp |

Slices: default SST 1 / SD FFFFFF (DNN `nist-dnn`); quarantine slice SST 1 / SD BADBAD is a **RAN slice** only
(PRB quota via E2SM-RC). Details: `docs/K8S-LAB.md`, `docs/K8S-A1-EI.md`, `docs/OAI-UPSTREAM-CHANGES.md`.

## 3. Telemetry sources (three sources, two domains)

| source | domain | content (per UE, 1 s) | path | delay measurement → xApp |
|---|---|---|---|---|
| E2SM-KPM | RAN | UL/DL rate, throughput, PRB %, cell PRB % | gNB → FlexRIC → xApp (Report Style 4, 1 s) | p50 1 ms, p99 49 ms |
| PFCP URR | core | UL/DL bytes and packets (volume) — **3GPP standard** counters | UPF → SMF (N4 usage report, 1 s) → producer → ICS → A1-EI → xApp | p50 1.5 s, p99 2.8 s |
| UPF eBPF profiler | core | packets / bytes, TCP, TCP-SYN, UDP, ICMP, DNS, fragments, GTP-in-GTP, mean packet size, destination-count estimate — **custom extension** | UPF `/v1/telemetry` → producer (EI type `oai-upf-profile_1.0.0`) → A1-EI → xApp | similar to URR |

The profiler exists because the problem is load-matched: volume (KPM, URR) alone cannot separate a flood from
legitimate traffic of the same rate; the protocol mix and packet shape can.

**Freshness caps** (used when building rows and live): KPM older than **3 s** (three 1 s report periods, two missed
reports tolerated) and URR / profiler older than **4 s** (just above the measured p99 A1-EI path delay of 3.8 s) are
treated as missing, so a stopped stream is never mistaken for a current one.

## 4. Joining KPM and URR into one record per UE per second

**Identity** — KPM identifies a UE by its AMF UE NGAP ID, URR by its PFCP session (SEID); the common key is the **SUPI**:
1. gNB reports KPM per UE with the AMF UE NGAP ID.
2. UPF counts per SEID; the SMF maps SEID → PDU session → SUPI and attaches the SUPI to each usage report.
3. The producer joins the SUPI with the AMF's UE table (IMSI ↔ AMF UE NGAP ID, read from the AMF log every ~20 s)
   and adds `ran_identity.amf_ue_ngap_id`, plus `session_epoch` to separate reused SEIDs.
4. The A1-EI adapter de-duplicates (`seid:session_epoch:ur_seqn`) and delivers to the xApp.
5. The xApp learns AMF UE NGAP ID → SUPI from URR and tags every KPM record with the SUPI (records without a mapping
   yet — up to ~20 s after attach — are dropped and counted).
6. The profiler carries the SUPI from the source: the SMF sends it to the UPF in the PFCP **User ID IE**
   (TS 29.244 §8.2.101 — standard IE; sending it is a testbed patch of the OAI SMF).

**Time** — causal as-of join on a 1 s grid: at second *t*, the newest record of each source that had **arrived** by
*t*, with `age = t − measurement time`, NaN beyond the freshness cap. URR rate = volume ÷ Δ(cumulative duration)
between consecutive reports of the same session (never across sessions).

**Checks** — byte counts agree across domains up to protocol overhead (KPM ≈ URR − 16.3 B × packets for UL);
preflight before each run requires both SEIDs in URR, both SUPIs known by the xApp, fresh KPM and URR.

Limits: the AMF-log mapping is non-standard, assumes one AMF and lags ~20 s after attach; a real deployment would
use NWDAF / Namf event exposure or a RAN-provided mapping. Detail: `docs/KPM-URR-DATA-PATH.md`, `docs/KPM-URR-ALIGNMENT.md`.

## 5. Threat model

| threat | emulation |
|---|---|
| UE uplink flooding, load-matched | one UE floods UL while the other sends benign traffic at the same load (0.4 / 0.8 / 1.2 Mbit/s, below the 2 Mbit/s fair-use threshold); families UDP, TCP SYN, DNS, pulsing, mimicry, fan-out |
| compromised E2 node — KPM hiding | the xApp's KPM ingest scales the attacker's UL rate / throughput / PRB by 0.1 or 0.33 (ground truth logged) |
| compromised E2 node — KPM framing | the benign UE's UL KPM × 2 or × 5 |
| core telemetry outage | A1-EI adapter scaled to 0 (no URR, no profiler) |
| negative control | ICMP flood vs ICMP ping at the same rate |

Out of scope: network MITM on E2/SCTP, real attack tools / botnets, more than 2 UEs or 1 cell.

**Physical invariant available to any defence**: the same UE's UL bytes are counted by the gNB (KPM) and by the UPF
(URR); a sustained disagreement beyond protocol overhead means one counter is lying — the basis for detecting a
compromised E2 node (a KPM↔URR integrity check; candidate DRL state feature, `DRL-DIRECTION.md`).

## 6. Defence actuation infrastructure (kept, model-independent)

| level | action | where |
|---|---|---|
| isolate | E2SM-RC `prb_quota` (quarantine slice ≤ 10 % PRB) + `slice_handover`; UE keeps its PDU session; UPF "monitor" | gNB via FlexRIC; ack ~0.4 ms |
| rate-limit | UPF Security API `PUT /v1/ues/<supi>` `{action: ratelimit}` | UPF |
| block | UPF Security API `PUT /v1/ues/<supi>` `{action: block, ttl_s}` — policy in a per-SUPI BPF map (SQLite-persisted), checked inline in the XDP session lookup; UL dropped before N6 | UPF; decision → policy accepted p50 26 ms |

- The xApp (C, FlexRIC SDK) is the single decision point: KPM ingest (+ tamper hook for experiments), URR / profile
  receiver (`:8443`), feature window per UE, classifier (built-in fair-use rules, or `external` = the sidecar on
  `127.0.0.1:8091` with a 200 ms timeout and fallback to the rules), escalation policy with expiries, actuators,
  verification and a 10 s resync with the UPF.
- UPF safety guards: `maxBlockedRatio` 0.5 (2nd of 2 UEs → HTTP 403), command rate limit, TTL bounds; fixed rules
  (drop spoofed source, GTP-in-GTP, unknown UL).
- The sidecar is the **plug-in point for a DRL policy**; it currently runs `scripts/k8s/classifier/stub_classifier.py`
  (answers benign; `/mode`, `/reset`, `/healthz` acknowledged).
- One KPM report → E2SM-RC ack measured at p50 39 ms / p99 100 ms with the previous detector in the loop (near-RT
  bound 10 ms – 1 s); the loop period equals the 1 s KPM period.

## 7. Data generation

### 7.1 Dataset v4 (defence off) — `research/datasets/oran_flooding_v4/` (DATASHEET.md)
- **Controlled experiment**: a seeded, pre-generated manifest (`manifest/design.json`, `scripts/k8s/exp/v4traffic/design.py`,
  seed 20261020) fixes for every phase which UE attacks, the attack↔benign pair, traffic generator, load, victim
  behaviour, congestion and duration; the harness only executes it; labels come from the plan.
- **7 attack ↔ benign pairs** (same family, same load): UDP flood ↔ bidirectional UDP, SYN ↔ short TCP connections,
  DNS flood ↔ heavy DNS, fan-out ↔ benign fan-out, pulsing ↔ on/off Pareto, mimicry ↔ UDP without feedback,
  ICMP flood ↔ ping (control).
- **Criteria**: load-matched; label independent of UE identity (P(mal | UE) 0.483 / 0.461), of the generator tool
  (0.50–0.54), packet sizes matched (overlap 0.84–1.00); metadata-only model AUC 0.487; causal as-of join; per-run
  validity (phase durations, no telemetry gap > 3 s, attacker visible, ≥ 90 % flow rows); invalid runs re-run.
- **Result**: 88 runs (120 attempts), 528 phases, **87,294 rows** (62,112 labelled + 25,182 idle), malicious share
  47.2 %, 31 raw features (KPM 8, URR 4, profiler 19), URR present 97.8 %, profiler 99.9 %.
- Build: `scripts/ml/build_dataset_v4.py` (+ `test_build_dataset_v4.py`), QA `qa_v4.py`, packaging `package_v4.py`.

### 7.2 Live campaign data v5 (defence in the loop) — `research/datasets/oran_flooding_v5_live/` (DATASHEET.md)
224 valid runs with the previous detector acting (7 scenarios incl. KPM hide / frame and core outage, 6 defence
configurations, paired traffic); raw KPM (raw + tampered), URR, profiler, UPF audit, RC control, DN counters.
Known artefacts (block carried over across a gap in 63 units; UPF block-ratio guard) are listed in its datasheet.

### 7.3 Older datasets
v1–v3 (`research/datasets/oran_flooding_v{1,2,3}`) — superseded by v4 (confounds); raw data kept.
Public NCSRD-DS-5GDDoS in `data/` (git-ignored).

## 8. Campaign tooling
- Harness `scripts/k8s/exp/run.py` (phases, gaps, hooks: defence reset, KPM tamper, core outage; readiness check;
  log collection), campaign driver `scripts/k8s/exp/v4traffic/campaign.py`, validity `integrity.py`.
- Unattended supervisor `supervise_v5.py` (re-run until valid, `recover_ran.sh` → `recover_core_ordered.sh` →
  `recover_ran.sh`, QA every N runs via `qa_v5.py`), live view `watch_v5.py`.
- Testbed failure modes seen: UE radio-link failure under host load (RFsim timing) → PDU session not re-activated →
  SMF session-TTL release; PFCP association loss; xApp↔FlexRIC E42 association stuck. Recovery is automatic.

## 9. Reproduction and file map
| what | where |
|---|---|
| DRL direction (study notes) | `research/DRL-DIRECTION.md` |
| datasets | `research/datasets/oran_flooding_v4/`, `.../oran_flooding_v5_live/` |
| raw runs (not in git, never delete) | `artifacts/experiments/` |
| testbed operation, recovery | `docs/K8S-LAB.md`, `docs/K8S-A1-EI.md`, `scripts/k8s/phase0/recover_ran.sh`, `recover_core_ordered.sh` |
| changes to OAI / FlexRIC | `docs/OAI-UPSTREAM-CHANGES.md`, `patches/` |
| session state | `docs/SESSION-HANDOFF.md` |

**Glossary**: KPM — E2SM-KPM measurements; URR — PFCP usage reporting rule; E2SM-RC — RAN control service model;
A1-EI — enrichment information from the Non-RT RIC; SUPI — subscriber identity joining both domains; SEID — PFCP
session ID; phase — 60 s traffic interval with fixed roles.
