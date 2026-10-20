# v4 Phase 1 — raw capture + causal build + pilot QA (COMPLETE)

Date: 2026-10-20. Implements v4 plan §4 (raw logging, causal offline build, unit
tests) and the §8 pilot. Phase 2 (traffic library) is NOT started — it is the next
gate.

## What was built
**Capture side (xApp, rebuilt `oai-lab-xapp:6dd4c7977f71a530`, live):**
- Raw KPM tap — `features_raw_write()` at the top of `process()` writes one record per
  KPM indication to `<run>_RawKpm.jsonl`: `source_ts` (collect), `arrival_ts` (now),
  supi, amf, rate/thp/prb/cell. Patch `patches/flexric-xapp-rawkpm.patch`.
- URR arrival in ms — the URR export gains `received_unix_ms` (was second-precision
  `received_at` only). Patch `patches/flexric-xapp-urr-arrival-ms.patch`.
- Profiler events already carried `received_unix_ms` (no change).
- Both patches are round-trip verified and registered in `scripts/verify-oai-upstream.sh`.

**Harness:** `collect.py` exports `raw/kpm.jsonl` per run (cut by arrival); `run.py`
creates `raw/`. URR/profiler arrivals come from the existing `core/urr_received.jsonl`
and `core/core_received.jsonl`.

**Offline build:** `scripts/ml/build_dataset_v4.py` reads the harness-native run layout:
- strictly causal as-of join (record used at second t only if `arrival_ts <= t`);
- `*_age_s` recorded; NaN beyond cap (KPM 3 s, URR/profiler 4 s — the A1-EI path lag is
  median ~2 s, p99 ~3.8 s);
- URR rate with the xApp's semantics, verified from data: **URR volumes are per period,
  not cumulative**; rate = volume / Δ(cumulative `duration_seconds`) within one PDU
  session, from causal records only; no cross-session deltas;
- legacy second-precision URR arrivals (pre-patch runs) padded +1 s and flagged
  `meta_urr_arrival_exact=0`;
- labels only from the schedule (`run.json` phases + `traffic/flows.json`):
  MALICIOUS / BENIGN / **IDLE (never merged into BENIGN)**; guard band 3 s;
- features vs `meta_*` strictly separated; v3-compatible feature names.

**Tests:** `scripts/ml/test_build_dataset_v4.py` — 11 checks pass (causality, URR
per-period, Δduration period, session reset, legacy +1 s pad, non-negative, UE join,
age cap, labels + IDLE, guard, separation).

**QA:** `scripts/ml/qa_v4.py` — independent causality audit (re-locates every used
record in the raw files and checks its arrival), C5 comparison against the same run's
xApp join, ages/presence by label, design balance, achieved vs offered.

**Reliability:** `userplane_watchdog.py watch` now recovers only after 3 consecutive
unhealthy ticks (a harness preflight that briefly restarts a UE no longer triggers a
core restart mid-run).

## Pilot (1 run of `ds-mixed`, defense off) — `research/datasets/oran_flooding_v4_pilot/qa_report.md`
- 522 rows: IDLE 258 · BENIGN 144 · MALICIOUS 120.
- **Causality audit: 0 violations** (KPM 522 / URR 520 / profiler 520 rows checked).
  The same run's xApp join used a future URR sample in 0.2% of rows (v3: ~1.3%).
- Presence: KPM 100%, URR 95.2%, profiler 99.6%; BENIGN vs MALICIOUS presence equal
  (97.9 / 97.5% URR) → no missingness leak.
- **achieved_ok 8/8** phase-UE pairs, measured at IP level with URR. Note: the DN counter
  is UDP payload only and under-reads 64-byte floods by the header share (0.63 of
  offered) — achieved-vs-target must be computed in IP bytes.
- **C1 confound present** (P(malicious|ue1)=1.0, ue2=0.0) — expected: this is a v3
  scenario. Fixing it is the job of the Phase 2 traffic library + Phase 3 role-swapping
  campaign design.

## Next gate (plan §8): Phase 2 traffic library
`schedules.py` (CBR/Poisson/MMPP/ON-OFF Pareto/fGn/Hawkes/pulsing, each with a
mean/property test), shared size prior, backends (pacer first; iperf2/hping3 cross-used
for both classes), `mixer.py`, `runner.py` logging achieved per second — all generators
launched from the same sidecar on both UEs. Calibration constraints: per-UE UDP UL
linear to ~8 Mbit/s; payload ≤ 1200 B; a pps ceiling for 64-byte packets must be
measured per backend before fixing the size prior.
