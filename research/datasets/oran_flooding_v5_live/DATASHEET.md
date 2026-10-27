# Datasheet — ORAN flooding v5 live (defence acting in the loop, 224 runs)

Raw run data of a 26 h campaign (2026-10-24 13:19 → 2026-10-25 15:55) in which a (since removed) ML defence acted
live on the traffic. The model, its evaluation and all results were removed on 2026-10-27 (direction changed to
DRL, `research/DRL-DIRECTION.md`; backup of the removed ML artifacts: `~/backups/oran-ml-artifacts-20261027.tar.gz`,
the removed reports remain in git history). What stays is the data and how it was collected.

## Composition
- 224 valid runs + 30 failed attempts (kept on disk, `meta_run_ok = 0`), manifest `manifest/design.json` (252 entries;
  the fair-use-rules configuration was run for reps 1 and 3 only). Pilot: `manifest/pilot.json` (42 runs, other seed).
- Scenarios (phase annotations applied by the harness; traffic labels never change): honest; KPM hide ×0.1 / ×0.33
  (the attacker's KPM UL rate / throughput / PRB scaled at the xApp ingest); KPM frame ×2 / ×5 (the benign UE's KPM
  scaled); core telemetry outage (A1-EI adapter scaled to 0 in phases 0 and 3); ICMP control pair.
- Defence configurations (which detector drove the xApp): fair-use rules, RAN-only, core-only, naive cross-domain,
  trust-weighted v1, trust-weighted v2. Traffic of a repetition is identical across all scenario × configuration
  cells (paired).
- A run: 15 s idle, 4 phases × 60 s with 15 s gaps (ICMP control: 2 phases); in each phase one UE floods UL and the
  other sends load-matched benign traffic; roles mirrored. Families: udp, syn, dns, pulsing, mimicry, fanout;
  loads 0.4 / 0.8 / 1.2 Mbit/s.

## Per-run files (`artifacts/experiments/<camp>_v5live_main_s<N>/runs/<config>/rep-<id>/`)
`run.json` (phases, readiness waits, hooks, `meta_run_ok`, integrity details), `raw/kpm.jsonl` (raw **and** tampered
KPM), `defense/tamper.jsonl` (tamper ground truth), `core/urr_received.jsonl`, `core/core_received.jsonl` (profiler),
`core/upf_audit.jsonl` (UPF policy commands and results), `ran/rc_control.jsonl` (E2SM-RC commands and acks),
`defense/{events,state_timeline,sidecar}.jsonl` (decisions of the removed detector — context only),
`dataplane/dn_per_second.csv` (packets / bytes per UE at the DN), `traffic/*`, `meta/snapshot_{start,end}.json`, `logs/*.log.gz`.

## Collection process and validity
- Unattended supervisor `scripts/k8s/exp/v4traffic/supervise_v5.py` (chunks of 50, automatic RAN / core recovery, QA
  after each chunk with `qa_v5.py`), `systemd-inhibit`.
- Readiness before every traffic phase: KPM < 3 s and URR received < 3 s for both UEs (≤ 30 s, else the run fails).
- `meta_run_ok`: harness ok; attacker visible in the UPF profiler; no KPM / URR / profiler gap > 3 s in any phase or
  gap (URR exempt in outage phases); flow-row coverage ≥ 90 % (exempt for a UE the defence acted on); phase durations
  ±20 %; no host suspend.
- Failed attempts: UE radio-link failure / PDU-session loss, PFCP association loss, xApp restarts, one stuck
  xApp↔FlexRIC E42 association, readiness timeouts — spread 3–7 per configuration.
- QA: no residual UPF policy / xApp level / tamper at any run start.

## Known artefacts in the data
- In 63 of 1536 (run, UE, phase) units (+ 7 ICMP) the UE entered the phase already blocked: the gap reset of the xApp
  level raced with the detector's last "block" answer, which re-set a 120 s block (affected configurations:
  RAN-only, naive, core-only, trust-weighted v1). Any analysis must drop or flag these units.
- The UPF refuses a block that would leave more than half of the UEs blocked (`maxBlockedRatio` 0.5): with 2 UEs the
  second block returns HTTP 403 (visible in `upf_audit.jsonl`).
- Isolation (quarantine slice, 10 % PRB) does not throttle 0.4–1.2 Mbit/s floods in RFsim.

## Limitations
2 UEs, 1 cell, RF simulator; synthetic traffic generators; tamper emulated at the xApp ingest (no E2/SCTP MITM).

## Distribution / maintenance
Raw runs under `artifacts/experiments/` (not in git, never delete). Testbed and data paths:
`research/CROSS-DOMAIN-DEFENCE.md`.
