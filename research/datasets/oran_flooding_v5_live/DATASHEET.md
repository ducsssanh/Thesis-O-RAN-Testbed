# Datasheet — ORAN flooding v5 live (cross-domain defence ON, main campaign, 224 runs)

Stage B of the thesis: the v4 cross-domain defence (3 frozen GBDT models + KPM↔URR integrity rule + trust-weighted
fusion) acting live in the OAI testbed, under honest telemetry, a compromised E2 node (KPM hidden / framed) and a
core-telemetry outage. Pre-registration with every frozen hash and every deviation: `PREREGISTRATION.md`.
Results: `reports/live_results_v5.md` (primary, clean units), `reports/live_eval_v5.md` (as pre-registered, all units).

## Motivation
v4 measured detection offline on runs collected with the defence OFF. v5 answers what the replay cannot: whether the
defence keeps its advantage when its actions feed back into the traffic, under real-time constraints (sidecar latency,
telemetry delay and loss), and what acting changes (traffic delivered at the DN, benign cost).

## Composition
- 224 valid runs = 7 scenarios × 5 model configurations × 6 reps + 7 scenarios × fair-use rules × 2 reps
  (manifest `manifest/design.json`, 252 entries; rules-v1 reps 1 and 3 selected by the supervisor).
- Scenarios: honest; KPM hide ×0.1 / ×0.33 (attacker's KPM UL rate/throughput/PRB scaled at the xApp ingest);
  KPM frame ×2 / ×5 (benign UE's KPM scaled); core outage (A1-EI adapter scaled to 0 in phases 0 and 3);
  icmp control (icmp_flood vs icmp_ping, 2 phases).
- Configurations: fair-use rules (xApp v1), RAN-only, core-only, naive cross-domain, trust-weighted v1, trust-weighted
  v2 (proposed). Same sidecar, mode flag; traffic per rep identical across the 42 cells (paired).
- A run: 15 s idle, 4 phases × 60 s with 15 s gaps (icmp: 2 phases); in each phase one UE floods UL, the other sends
  load-matched benign traffic; roles mirrored. Families: udp, syn, dns, pulsing, mimicry, fanout (2 reps each);
  loads 0.4 / 0.8 / 1.2 Mbit/s (below the 2 Mbit/s fair-use threshold by design).
- Unit of analysis: (run, UE, phase): 1536 attack-pair units + 128 icmp units.

## Per-run files (`artifacts/experiments/<camp>_v5live_main_s<N>/runs/<config>/rep-<id>/`)
`run.json` (phases, readiness waits, hooks, meta_run_ok, integrity, attempt_id), `defense/sidecar.jsonl` (every engine
step: row, z-scores, trust, integrity, decisions of all 5 configs, latency), `defense/events.jsonl` +
`state_timeline.jsonl` (xApp evidence / level / actions), `defense/tamper.jsonl` (tamper ground truth),
`raw/kpm.jsonl` (raw and tampered KPM), `core/urr_received.jsonl`, `core/upf_audit.jsonl`, `ran/rc_control.jsonl`,
`dataplane/dn_per_second.csv`, `traffic/*`, `meta/snapshot_{start,end}.json`, `logs/*.log.gz`.

## Collection process
- 2026-10-24 13:19 → 2026-10-25 15:55, unattended `scripts/k8s/exp/v4traffic/supervise_v5.py` (chunks of 50, QA
  after each, automatic recover_ran.sh / recover_core_ordered.sh, systemd-inhibit).
- Readiness before every traffic phase: KPM < 3 s and URR received < 3 s for both UEs (≤ 30 s wait, else the run fails).
- Defence state reset (xApp level, tamper) at idle and every gap; sidecar state reset at the run start only.
- Validity (`meta_run_ok`): harness ok, attacker profiler assert, `integrity.check_run` (phase durations, no KPM/URR/
  profiler gap > 3 s incl. gaps, flow-row coverage ≥ 90 %, no host suspend; v5 exemptions: URR/profiler gaps in
  outage phases, flow rows of a UE the defence acted on).
- 254 attempts, 30 failed (testbed: UE radio-link failure / PDU-session loss, PFCP association loss, xApp↔FlexRIC E42
  stuck, readiness timeouts), all re-run; failures spread 3–7 per configuration. Failed attempts kept on disk.
- QA (`qa_v5.py`): 0 residual UPF policy / xApp level / tamper at any run start; 0 sidecar steps on stale KPM;
  34 classifier fallbacks in 124,758 calls (0.03 %); 6 runs flagged for a fallback inside a phase (40, 91, 99, 110,
  173, 212; sensitivity ≤ 0.10 on any rate).

## Known artefacts and how they are handled
- **L3 carry-over** (harness/xApp interaction): the gap reset raced with the sidecar's last L3 answer, so 63 of 1536
  phases (4.1 %, 38 runs; + 7 icmp phases) started with the UE already blocked — ran-only 43, naive 16, core-only 8,
  trust-v1 3, trust-v2 0. Primary analysis drops these units (`scripts/ml/carryover_v5.py`); all-units values shown.
- **L3 decision ≠ enforcement**: the UPF refuses a block beyond maxBlockedRatio 0.5 (2 UEs → the 2nd block, HTTP 403).
  Attacker L3 enforced 95–96 % (core-only, trust-v1, trust-v2), 75 % naive, 62 % RAN-only; delivered fraction at
  the DN is the measured effect.
- Missing KPM enters the engine as 0 kbit/s (defence_engine_v4.py:117); live the sidecar steps only on new KPM, so
  this never occurred (KPM age max 0.09 s over all steps).

## Headline results (clean units, 95 % run-bootstrap CI) — details `reports/live_results_v5.md`
- KPM hide: trust-weighted v2 blocks 100 % [1.00, 1.00] of attack phases at ×0.1 and ×0.33 (naive 62 / 87 %, core-only
  54 / 74 %, RAN-only 0 / 33 %); integrity alarm on 100 % of tampered phases; time to block median ~24 s; attacker UL at
  the DN ~500 kbit/s before the block → 0 after.
- KPM frame: framed benign UE blocked 0 % (×2) / 4 % (×5) under trust-v2, vs 46 / 44 % naive and 64 / 62 % RAN-only;
  cost: attack phases blocked 29 / 42 % vs naive 67 / 79 %.
- Core outage: in outage phases trust-v2 isolates 75 % of attack phases via the RAN fallback and blocks none (L3 needs
  core evidence by design); with core telemetry present 92 % isolated, 67 % blocked, 0 benign blocked.
- Honest: trust-v2 isolates 92 %, blocks 67 %, benign wrongly blocked 8 % [0, 17 %].
- Fair-use rules detect nothing (load-matched floods < 2 Mbit/s). icmp control: flood and ping not separable
  (every model config isolates ping 90–100 %); trust-v2 blocks ping 50 % vs naive 92 %.
- Control loop (one KPM report → E2SM-RC ack): p50 39 ms, p99 100 ms, max 168 ms; → UPF policy p50 41 ms; URR reaches
  the xApp 1.5–2.8 s after measurement (A1-EI path).

## Known limitations
6 reps per cell (wide CIs); 2 UEs, 1 cell, RFsim; traffic generators, not real attackers; tamper emulated at the xApp
ingest (no E2/SCTP MITM); core telemetry 1.5–2.8 s stale; the UPF block-ratio guard limits L3 with 2 UEs; the L3
carry-over corrected in the analysis, not by re-running.

## Distribution / maintenance
Raw runs under `artifacts/experiments/` (not in git, never delete); reports, scripts and manifests in git.
Reproduce: `live_eval_v5.py --manifest manifest/design.json <main camps>` → `carryover_v5.py` → `loop_latency_v5.py`
→ `live_extra_v5.py` → `figures_v5.py --eval reports --run <run dir>`.
