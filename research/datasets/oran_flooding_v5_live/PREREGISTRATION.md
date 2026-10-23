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
