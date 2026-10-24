# oran_flooding_v5_live — pre-registration (stage B: cross-domain defence live)

Written 2026-10-23, before any pilot or main run. Nothing below is tuned on main-campaign data;
a change after the pilot is listed in "Changes after the pilot" with its reason.

## Question
Do the trust-weighted cross-domain rules + 3 GBDT models (v4, frozen) keep their replay advantage when
they act live in the testbed — under honest telemetry, a compromised E2 node (KPM hidden or framed) and
a core-telemetry outage — and what does acting change (traffic delivered, benign cost)?

## Frozen artifacts
| item | value |
|---|---|
| xApp image | `oai-lab-xapp:31961c9a9a28f3c1` (patches/flexric-xapp-live-sidecar-tamper.patch) |
| sidecar image | `oai-lab-sidecar:5a2ca22005c47270`, version `v4-live-2` |
| engine `defence_engine_v4.py` sha256 | `6bc1c556c80cc44b4f1e5bdcd529e378354c4bf3fbb0cd85d69a0f178ca05515` |
| models spec / integrity rule sha256 | `1fac7d0b…27809c` / `610face2…5d7e6` (artifacts/ml/v4/models, frozen v4) |
| GBDT xd / core / ran sha256 | `4c29a3b4…af20ed` / `09b7482a…8e8` / `cdad0c5d…c2b` |
| urr-ei-producer | `oai-lab-urr-ei-producer:00b9b70c6d9b8a39` (SMF container-restart fix) |
| main manifest | `manifest/design.json` sha256 `69e38a7152227e176e313218a0f80693adb317fa7f429235b221f54fb2878c92` |
| pilot manifest | `manifest/pilot.json` sha256 `fe27c6c783b48c16d797e88b4642b6ae3b697a0adbfa0e792ebd67724d73aaff` (other seed; excluded from results) |

Core, gNB, FlexRIC: the v4 deployment (pods restarted by recover_ran.sh, not redeployed).

## Design (scripts/k8s/exp/v4traffic/design_v5.py)
- 7 scenarios × 6 configurations × 6 reps = 252 runs. Scenarios: honest, kpm_hide ×0.1 / ×0.33,
  kpm_frame ×2 / ×5, core_outage (A1-EI adapter down in phases 0 and 3), icmp_control.
  Configurations: rules-v1 (reference), ran-only, core-only, xd-naive, xd-trust-v1, xd-trust-v2 (main).
- A run: 4 phases × 60 s (2 attack pairs, mirrored roles), 15 s gaps; icmp_control 2 phases. Traffic
  per rep identical across all 42 cells (paired); pairs rotate (udp, syn, dns, pulsing, mimicry, fanout
  twice each), loads 0.4/0.8/1.2 Mbit/s, fresh seeds.
- Defence: xApp classifier external (sidecar mode = config) or rules (rules-v1); L1 expiry 3 s
  (refreshed by every attack label), L3 expiry 120 s, probation 0 for the sidecar modes (the sidecar
  decides L3), UPF block without RRC release, defence levels + tamper reset in every gap, sidecar reset
  at the run start. Tamper at xApp ingest = emulated compromised E2 node (network MITM out of scope).
- Order: rep-major, cells shuffled within a rep (seeded).

## Metrics (scripts/ml/live_eval_v5.py), per scenario × config, 95 % run-bootstrap CI
1. attack phases detected (L1, xApp level ≥ 1) / blocked (L3, level ≥ 3)
2. benign phases wrongly blocked (L3); framed benign (kpm_frame) apart; benign L1 soft isolation apart
3. time phase start → L1, L3, integrity alarm (median, p90)
4. integrity alarms on untampered phases
5. live only: delivered fraction of attacker / benign UL packets at the DN (calibrated to v4 defence-off),
   sidecar latency p50/p99, classifier fallbacks
Plus the offline-replay (v4 test runs) vs live table for the same cells.

## Hypotheses (not targets)
H1 trust-v2 ≥ naive on kpm_hide, kpm_frame and core_outage. H2 ran-only ≈ 0 detection on kpm_hide.
H3 framed benign wrongly blocked ≤ ~2 % under trust-v2. H4 integrity false alarms ≈ 0 on honest phases.
If live differs from replay, the difference is reported, never retuned.

## Validity rules
A run counts only with meta_run_ok = 1 (harness ok, attacker profiler assert, integrity.check_run with the
v5 exemptions: no URR/profiler gap check in core-outage phases, no flow-row check for a UE the defence
acted on). Failed runs are kept and counted; a cell needs ≥ 6 valid reps (failed ones are re-run with
the same manifest entry). Estimated duration: ~6.5 min per run → ~27 h for the main campaign, run in
night batches under systemd-inhibit.

## Known limitations (stated before running)
- Live steps once per KPM report, the replay once per grid second (no difference while KPM is 1 Hz).
- After a core outage the URR path needs ~22 s to recover (adapter restart + A1-EI job): the first
  seconds of the next phase may still have ct = 0.
- L1 (quarantine slice, 10 % PRB) does not throttle 0.4–1.2 Mbit/s floods in RFsim: delivered stays ~1.
- rules-v1 (2 Mbit/s fair-use) cannot see these load-matched floods by construction.

## Changes after the pilot (2026-10-24; pilot = 42/42 cells valid after 47 attempts, reports/pilot/)
No change to the engine, models, thresholds, configurations, timing, scenarios or metrics.
Tooling only:
- `supervise_v5.py`: unattended driver (re-runs a manifest entry until valid, max 3 attempts; on a failed
  preflight saves logs, recover_ran.sh, then recover_core_ordered.sh).
- `recover_core_ordered.sh`: wait up to 180 s (was 90 s) for the UPF to register at the NRF — a restarted
  UPF needs ~100 s; the short wait gave a false FAIL that left the SMF unassociated.
- The v4 `userplane_watchdog.py` (auto-recovery, started 2026-10-22) was stopped: it restarted the core
  during a pilot run (run 28 failed). Only the supervisor recovers during v5 campaigns.
Pilot failure causes (all testbed, kept with meta_run_ok=0 and re-run): KPM indications stall ~15 s right at
the gap-reset RC slice handover (2/46: runs 4, 19 — xApp watchdog restart); UE radio-link failure (2/46:
runs 9, 33); external watchdog (1). Expected ~9 % re-runs in the main campaign.

## Main campaign freeze (2026-10-24, before main run 1)
Approved after the pilot with three tooling changes. Engine, models, thresholds, configurations,
timing, scenarios, metrics and validity rules are unchanged.

Frozen artifacts, checked against the running pod before run 1 (sidecar `/healthz`, deployment images):
| item | value (sha256) |
|---|---|
| xApp / sidecar / producer / adapter images | `oai-lab-xapp:31961c9a9a28f3c1`, `oai-lab-sidecar:5a2ca22005c47270`, `oai-lab-urr-ei-producer:00b9b70c6d9b8a39`, `oai-lab-a1-ei-adapter:6be3ddf2ba9f499a` |
| sidecar `v4-live-2`: `sidecar_v4.py` / `defence_engine_v4.py` | `b98c0980950704d50f2f981a2ea6713daf367b3493b7c4494e537b5f8da565fa` / `6bc1c556c80cc44b4f1e5bdcd529e378354c4bf3fbb0cd85d69a0f178ca05515` |
| spec / integrity rule | `1fac7d0bd183b5e622d29367672922eec13ac71ad77a0939a4c4d3618a27809c` / `610face2148689a039ae4c1c4be1c450042de43775e6b8db8d2b8d7a04a5d7e6` (tau 0.7, m 10, bias −0.0476) |
| GBDT xd / core / ran | `4c29a3b48838c2ad7b53d4a85d2546cabc59334bd3331fa66af85319b9af20ed` / `09b7482ac1a647e282e5c202442678b1671a6358713b2758dd70943abf2b88e8` / `cdad0c5d5da74c9cc9620703a2f9db94e43a891fc972af8494e72c9357058c2b` |
| main manifest `design.json` | `69e38a7152227e176e313218a0f80693adb317fa7f429235b221f54fb2878c92` (unchanged; the subset below is selected by the supervisor) |
| tooling (sha256 prefix) | run.py `d5a7b1d6be717525`, campaign.py `5626e3d4f69ce021`, supervise_v5.py `7a581e1f0a09eadf`, qa_v5.py `60ed2376fde71c2e`, integrity.py `34c21b8a2f07c3c1`, live_eval_v5.py `272297c38f981176` |

Changes (tooling only):
1. **Readiness before each traffic phase** (`run.py readiness()`, config `campaign.READINESS`): a phase (and its
   tamper / core-outage hook) starts only when the xApp holds, for both UEs, a KPM report < 3 s old and a URR report
   received < 3 s ago. Wait ≤ 30 s, else the run fails (`meta_run_ok=0`, error `readiness: …` with the ages).
   The wait lies between the gap's end and the phase's start, so phase and gap durations are unaffected. Each phase
   records `readiness.wait_s` and the ages. A KPM stall inside a gap still fails the run under the unchanged
   integrity rule (stream gap > 3 s in any planned phase, gaps included) — the pilot's 2 KPM-stall failures were of
   that kind, so the re-run rate is not expected to drop much.
2. **rules-v1 = 2 reps per scenario** (reference only; it cannot see these floods by construction): manifest reps
   1 and 3 (loads 0.4 and 1.2 Mbit/s, pairs udp/syn and mimicry/fanout), `supervise_v5.py --config-reps rules-v1=1,3`.
   Main campaign = 7 × 5 × 6 + 7 × 2 = **224 runs**. Pilot wall time per run (start to start): 384 s for 4-phase runs,
   217 s for icmp_control → 192 × 384 s + 32 × 217 s ≈ 22.4 h, + ~11 % re-runs (pilot 5/47) and recoveries ≈ **25–26 h**.
3. **Pilot excluded** from every main analysis: `live_eval_v5.py` refuses a campaign whose `campaign.json` manifest
   is not `--manifest` (the pilot ran `pilot.json`), and refuses two valid attempts of one manifest run.
Automatic QA after every 50 runs (`qa_v5.py`, supervisor `--chunk 50`, reports in `artifacts/experiments/qa_v5_main/`):
run_ok and failure reasons, readiness waits / timeouts, classifier fallbacks, residual UPF policy / xApp level /
tamper at each run start, sidecar steps on stale KPM. The supervisor STOPS (human needed) on a residual state, a
fallback or a stale-KPM step in a valid run, fewer than 75 % valid attempts in a chunk, or a failed recovery.

Missing KPM vs deviating KPM in the integrity rule (checked before run 1):
- The engine itself does not separate them: `defence_engine_v4.py:117` turns a missing KPM UL rate (NaN) into
  0 kbps, and only URR freshness gates the rule (`:119` fresh, `:135` violation needs the 10 s window fully URR-fresh).
  A row with missing KPM and active URR would therefore count as "KPM < URR" (hiding).
- Live, such a row is never formed: the sidecar steps only on a new KPM report (`sidecar_v4.py:170-171`, a repeated
  seq returns the cached answer without a step), so a KPM stall pauses the rule instead of feeding it zeros; a step
  whose KPM is older than 3 s would carry NaN (`sidecar_v4.py:85-88`). Pilot: 29,859 sidecar steps, KPM age max
  0.09 s, 0 steps with missing KPM. `qa_v5.py` asserts this stays 0 for every valid main run (stop otherwise).
- Missing URR (core outage) is never a violation (`:119`, `:135`).
- Not changed (frozen defence). Limitation for the thesis: in the offline replay grid (1 row per second) a second
  without KPM enters the rule as 0 kbps; the live system only avoids this through its KPM-driven stepping.

### Main campaign, tooling fix 1 (2026-10-24 14:55, after main attempt 16; no defence/validity change)
Main runs 13 and 14 (rules-v1) failed on the readiness check: ue1 had a radio-link failure (gNB "UL failure timer
expiry", then RRCReject) — KPM age 52 s / 110 s. campaign.py stopped after 2 failures in a row, as designed, but the
QA valid-rate rule then stopped the supervisor on a 4-attempt chunk instead of letting the recovery run. Fixes:
the QA valid-rate stop needs ≥ 10 attempts in the chunk (`qa_v5.MIN_N`); the supervisor preflight also requires the
readiness condition (fresh KPM + URR for both UEs), so a dead UE triggers recover_ran.sh. Images verified unchanged
(the xApp pod restart at 14:31 was the harness's `rollout restart` after it re-attached ue2).

### Main campaign, tooling fix 2 (2026-10-24 17:00, after main attempt 30; no defence/validity change)
QA stopped the supervisor on "classifier fallback in a valid run": runs 27 and 29 had 4 fallbacks each, all from one
burst of sidecar latency 370–550 ms (> the xApp's 200 ms timeout; host load ~11, swap in use). Both bursts lie in
gaps (run 27: gap00, 5 s after p00 ended; run 29: gap03, 37 s after p03 ended): no traffic, the xApp's rules said
benign, no action; the sidecar still stepped (state = engine). No phase metric uses gap time. The QA stop is narrowed
to a fallback inside a live_eval phase window ([t_start, t_end + 2 s], located by sidecar steps > 150 ms ± 1 s) or a
fallback with no slow step at all; gap/idle fallbacks are counted and reported (metric group 5). QA report files
are now named per supervisor start (`<start>_batchNN.md`) so a restart cannot overwrite one.

### Main campaign, tooling fix 3 (2026-10-24 18:50, after main attempt 56; user decision; no defence/validity change)
Run 40 (honest / xd-trust-v1) had 1 fallback inside p03_syn: the xApp's 200 ms timeout expired before the request
reached the sidecar (no slow sidecar step; the sidecar missed one step of ue2), so the xApp's rules decided that one
second. A valid run with a fallback in a traffic phase (or an unexplained one) is now FLAGGED instead of stopping the
campaign: it keeps meta_run_ok, and the final report repeats every metric without the flagged runs (sensitivity
analysis). QA still stops when a flagged run has > 3 fallbacks or flagged runs exceed 10 % of a chunk (≥ 10 attempts)
— a systematic latency problem. Flagged so far: run 40. The supervisor's QA now covers only the campaigns of its
own start (a restart reuses batch numbers). Runs 48–49 failed because ue1 lost its tunnel IP (testbed, re-run).
