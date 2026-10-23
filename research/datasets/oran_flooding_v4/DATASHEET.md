# Datasheet — ORAN flooding v4 (full campaign, 88 runs)

Follows "Datasheets for Datasets" (Gebru et al.). Carries forward the Phase-2 pilot datasheet
(`research/datasets/oran_flooding_v4_p2pilot/DATASHEET.md`); everything stated there about the
traffic library, confound controls (C1–C5) and measurement decisions still holds and is not
repeated in full. This file adds the campaign, its incidents and the final QA.

## Motivation
Separate **malicious user-plane flooding** from **legitimate high load** in a 5G O-RAN testbed
from cross-domain telemetry (RAN E2SM-KPM, PFCP URR, eBPF UPF profiler). v3 was confounded
(label separable from UE identity, generator tool, victim response, packet-size grid and a
phase-boundary time leak); v4 is a controlled experiment that neutralises those confounds.
Research-grade: built to make the experiment correct, not as an industrial/standard dataset.

## Composition
- Unit: one row = 1 s × 1 UE. Features `rate_*`, `thp_*`, `prb_*`, `cell_prb_*` (KPM),
  `urr_*` (PFCP URR), `prof_*` (eBPF UPF profiler); `label` ∈ {BENIGN, MALICIOUS, IDLE};
  `meta_*` = experimental control, **never** an input feature.
- IDLE (warm-up, gaps, a UE without a flow) is kept apart, never merged into BENIGN.
- 7 attack↔benign pairs (udp_flood↔udp_bidir, syn↔tcp_shortconn, icmp↔icmp_ping,
  dns↔dns_heavy, fanout↔fanout_benign, pulsing↔onoff_pareto, mimicry↔udp_nofeedback) ×
  load × victim_mode × congestion, plus `benign_benign` offset groups and a both-attack
  extension (runs 84–88).
- Files: `rows.parquet` / `rows.csv` (build output, not committed), `raw/<run_id>/`
  (kpm/urr/prof/achieved/flows of each selected attempt), `manifest/` (design + per-run plan +
  `runs_index.json` with EVERY attempt and its validity), `qa_report.md`, `calibration.md`,
  `reproducibility.txt`, `unit_tests.txt`.

## Collection process
- Manifest `manifest/design.json`: 88 runs / 528 phases, seed 20261020, deterministic.
  Every PREFIX is counterbalanced (UE-mirror pairs packed in one run; dual-use surplus groups
  paired with matching-backend `benign_benign` into backend-neutral units). From run 43 on,
  all phases of a unit share ONE duration (`design.py share-dur`) so balance is exact by rows;
  runs 1–42 (already collected) keep their per-phase durations.
- Both classes come from the same UE keepalive sidecar and egress through interchangeable
  backends (pacer/hping/iperf dual-use; synflood; tcp_shortconn/dns_client hard negatives).
  Detection and mitigation are OFF for the whole campaign.
- Raw telemetry is logged with source and arrival timestamps; rows are built offline by a
  strictly causal as-of join (`arrival_ts ≤ t`, `*_age_s` recorded, age cap → NaN).
- Ground truth = the experiment schedule. `meta_achieved_ratio` (URR, per phase) records the
  realised vs intended load.

### Batches and attempt selection
All camp dirs live in `artifacts/experiments/` (gitignored, backed up). 120 attempts, 88 selected, 24 invalid.

| camp dir | reps | role |
|---|---|---|
| `20261020-213040_v4campaign_batch1`, `…214714_v4campaign_batch1b` | 1–8 | early tries, superseded by batch1c |
| `20261020-232552_v4campaign_batch1c` | 1–8 | valid except rep 7 (iperf FIN stall) |
| `20261021-093244_v4campaign_batch2` | 9 | valid |
| `20261021-102436_v4campaign_batch2b` | 10 | failed in preflight (`error.txt`) |
| `20261021-102738_v4campaign_batch2c` | 10–42 | valid except 37 (host suspend) and 10, 13, 16, 17, 19, 26, 40 (pre-fix iperf) |
| `20261021-194045_…rerun37`, `20261021-194320_…rerun37` | 37 | preflight `defense state HTTP 0` (E2 lost) |
| `20261021-195218_v4campaign_rerun37b` | 37 | valid |
| `20261021-201043_v4campaign_batch3` | 43–76 | valid except 47, 59, 62, 66, 67, 68 (pre-fix iperf) and 76 (UE1 radio-link failure); STOPPED at 76 |
| `20261022-012451_v4campaign_rerun_iperf` | 7, 10, 13, 16, 17, 19, 26, 40, 47 valid; 59 failed | fixed iperf backend; STOPPED at 59 (UE2 released by the core) |
| `20261022-030535_v4campaign_rerun_iperf_b` | 59, 62, 66, 67, 68, 76–88 | fixed iperf backend; final checkpoint over 1..88 PASS |
| `20261022-012016_fixtest_iperf_silent` | — | one-off check of the fixed backend (not a campaign dir, not in the dataset) |

For each manifest run the dataset uses the **newest valid attempt by `t_start`**
(`package_v4.attempts`, `campaign.newest_valid_dirs`). Invalid attempts are never deleted: they
stay on disk with `meta_run_ok=0` (+ `meta_run_ok_prev` when invalidated after the fact) and
their reason, and are all listed in `manifest/runs_index.json`.

### Per-run validity (`meta_run_ok`)
A run is valid only if: preflight passed (PFCP association, both tunnels, xApp knows both
SUPIs, fresh URR for both SEIDs, defense off); `prof_assert` (attacker `prof_ul_pps` peak ≥ 20
in every attack phase, matched by SUPI); and `integrity.check_run`:
1. every phase lasted within ±20% of plan;
2. no KPM/URR/profiler gap > 3 s inside any phase (per SUPI, edges included);
3. no host suspend (`PM: suspend entry/exit`) overlapping the run;
4. **(added 2026-10-22)** every generator flow logged ≥ 90% of the planned phase seconds with
   a known sent volume (`traffic/<phase>_<ue>_<dir>.csv`).

## Incidents and how they were handled
1. **Host suspend → E2 loss (2026-10-21 15:48–16:08, rep 37).** The laptop suspended mid-run
   (gsd-power idle action; `systemd-inhibit` alone does not stop it); FlexRIC lost the E2 SCTP
   association and the xApp kept resending E2 Setup. rep 37 is invalid (phase +3625%, KPM gap
   1380 s); two rerun attempts failed preflight (`defense state HTTP 0`) until `recover_ran.sh`.
   Sleep/suspend targets were then masked, logind/GNOME idle actions disabled, and the suspend
   guard (integrity check 3) was added.
2. **iperf silent-victim FIN stall (pre-fix backend).** Each 1 s block was a separate
   `iperf -u -t 1`; with a silent victim (DROP on the DN) the iperf2 client waited for the server's
   final UDP stats and hung until the 3 s timeout, so only the MALICIOUS flow pulsed ~1 s ON / 2 s
   OFF, and the backend logged the TARGET as sent on timeout (fake achieved). Load symmetry did not
   catch it because it pools all backends. Found at checkpoint 64 (silent MAL achieved 0.56–0.68 vs
   BEN ≈ 1). Affected runs: 7, 16, 17, 47, 59, 62, 66, 67, 68 (+ early attempt batch1b/4); run 78 was
   not yet collected and ran with the fixed backend.
3. **iperf per-block drift (pre-fix backend).** Fixed `-t 1` blocks took 1.03–1.19 s (process
   start + FIN exchange), so long iperf phases logged only 80–93% of their seconds, in BOTH classes.
   The new row-coverage guard (≥ 90%) caught runs 10, 13, 19, 26 and 40 as well; they were
   invalidated and rerun rather than relaxing the guard. The iperf phases of the other selected
   runs passed the guard (≥ 90%) and keep the pre-fix behaviour (see limitations).
   **Fix (both classes):** `--no-udp-fin`; each block runs `-t` = time to the next 1 s boundary
   minus the measured process overhead (one row per wall second, `-b` unchanged); a timed-out /
   unparsable block or a skipped second logs `sent_* = None`, never the target. Verified on rep 59's
   iperf/silent phases: 30–31 of 31 rows, achieved MAL silent 0.984 / 0.945, BEN 0.964 / 0.954.
   Retroactive invalidation keeps every attempt (`meta_run_ok=0`, `meta_run_ok_prev=1`, reason in
   `integrity.reasons`, `integrity.flow_rows_guard`).
4. **UE1 radio-link failure (2026-10-22 00:52, rep 76).** gNB `UL Failure on PUSCH after 10 DTX`
   → out-of-sync → `UEContextReleaseRequest` cause `radio-connection-with-ue-lost`; UE1's PDU
   session vanished from the UPF → KPM/URR/prof gaps → run invalid, batch 3 stopped. RAN-only;
   recovered with `recover_ran.sh` (core untouched). Evidence in `batch3/diag_run76/`.
5. **UE2 released by the core (2026-10-22 02:50, rerun of rep 59).** Network-initiated release
   (AMF→SMF `REL_DUE_TO_REACTIVATION`, NGAP cause NAS `deregister`) with a healthy radio. The
   trigger inside AMF/SMF is unknown: their logs were lost when the user-plane watchdog — a process
   still running OLD code — did a simultaneous core rollout-restart, which re-raced the SMF↔UPF PFCP
   association (no tunnels). Recovered with `recover_core_ordered.sh`; the watchdog was relaunched
   on the current (ordered-recovery) code. Evidence in `rerun_iperf/diag_run59/`.

## Weighting: rows vs phases
Two balance views are reported and they differ on purpose:
- **row-weighted** (what a per-second classifier sees; the campaign stop-gate uses it);
- **phase-weighted** (each (phase, UE) counts once; QA §3/§11 use it).
Runs 1–42 have unequal per-phase durations inside a unit, so their row-weighted P(mal|ue)
drifts from the phase-weighted one; runs 43–88 share durations per unit and do not.
Balance is gated RELATIVE to the base rate (benign_benign pulls the MALICIOUS base rate to
≈0.44), not to an absolute 0.5.

## Final QA
88/88 manifest runs selected; 87 294 rows (62 112 BENIGN/MALICIOUS, 25 182 IDLE), 1 056
(phase, UE) units. URR present 0.978, profiler 0.999. Full report: `qa_report.md`.

| metric | row-weighted | phase-weighted |
|---|---|---|
| base rate P(mal) | 0.472 | 0.472 |
| P(mal\|ue1) / P(mal\|ue2) | 0.483 / 0.461 | 0.472 / 0.472 |
| dual-use base | 0.532 | 0.535 |
| P(mal\|hping) / iperf / pacer | 0.526 / 0.500 / 0.540 | 0.530 / 0.500 / 0.543 |

| final stop-gate @88 (full prefix) | value | gate |
|---|---|---|
| \|P(mal\|ue) − base\| max | 0.011 | ≤ 0.05 |
| \|P(mal\|backend) − base_du\| max | 0.032 | ≤ 0.05 |
| cell-achieved pass rate | 1.0 (28 cells) | ≥ 0.85 |
| load symmetry max | 0.015 | ≤ 0.05 |
| nuisance-only AUC (innocent) | 0.487 | ≤ 0.6 |
| size overlap udp / fanout / mimicry / pulsing / icmp | 0.96 / 0.87 / 0.84 / 0.84 / 1.00 | ≥ 0.6 (size-matched) |

dns (0.04) and syn (0.06) differ by protocol design and are not size-matched pairs.

iperf achieved (median per-phase ratio, n = 6 per cell) after the fix, split by victim mode:
responsive BEN 1.027 / 1.011 / 0.987, MAL 1.032 / 1.017 / 0.992; silent BEN 1.038 / 1.008 / 1.011,
MAL 1.026 / 1.007 / 1.009 (loads 0.4 / 0.8 / 1.2 Mbit/s).

Acceptance (plan §7.3), all PASS: P(mal|UE) ∈ [0.45, 0.55]; P(mal|dual-use backend) ∈ [0.4, 0.6];
≥ 90% phases achieved_ok (0.912; cell-level 1.0); 0 causality violations; unit tests; nuisance AUC
≤ 0.6; each §6.3 cell ≥ 3 valid phases per UE; reproducible from manifest + seed; every selected run
passes the integrity guards (incl. the row-coverage guard).

## Adversarial validation and nuisance baseline
- Nuisance-only baseline uses only "innocent" features (identity/tool/victim-response proxies);
  AUC ≤ 0.6 is a stop-gate.
- Adversarial validation (pilot, 9 runs): `victim_mode | MALICIOUS` AUC 0.74–0.86 — expected,
  victim response is a per-phase environment property (C2) and a silent victim legitimately has
  no DL; within-class `backend` AUC 0.69–0.95 — tools are distinguishable from each other, which
  is harmless because each dual-use tool is balanced across classes (C4).
- Final campaign (grouped by run, AUC within a class): `ue` 0.48–0.55 (no UE fingerprint);
  BENIGN `victim_mode` 0.44–0.51; MALICIOUS `victim_mode` 0.94–0.96 (expected: a silent victim
  sends no DL to the attacker); `backend` 0.89–0.97 in both classes (tools distinguishable, but
  balanced across classes). Nuisance-only baseline: innocent AUC 0.49; + backend 0.74 (benign-only
  hard-negative backends carry label signal by design).

## IDLE rows and their noise floor
IDLE = a UE second without a generator flow: the 15 s warm-up (`idle`), the gaps between phases
(`gapNN`) and the drain seconds between a phase's end and the next gap's start (empty
`meta_phase`). IDLE is never a training target and never in the headline evaluation (see
training protocol); it is kept to measure false alarms on an idle UE.
Noise floor (all 25 182 IDLE rows): every feature has median 0 (PRB 2% UE / 4% cell). The tail is
NOT idle traffic but the end of the previous phase: in the drain seconds 36% of rows still carry
> 50 kbps UL (generator stop + the as-of join's 3–4 s URR/profiler lag), in the first 2 s of a gap
28%, after 2 s 0%, and the warm-up 0%.

| feature (IDLE, all rows) | median | p95 | p99 |
|---|---:|---:|---:|
| `rate_ul_kbps` | 0 | 375 | 1096 |
| `prb_ul_pct` / `cell_prb_ul_pct` | 2 / 4 | 28 / 53 | 40 / 70 |
| `urr_ul_kbps` / `urr_dl_kbps` | 0 / 0 | 823 / 173 | 1282 / 871 |
| `prof_ul_kbps` / `prof_dl_kbps` | 0 / 0 | 867 / 76 | 1323 / 466 |
| `prof_ul_pps` | 0 | 318 | 1097 |

## Training protocol (2026-10-23)
- `scripts/ml/prep_v4_windows.py`: windows of 10 s per (run, UE), label = last second.
  `main` = all 10 s in one pNN phase, one label, no guard second (guard = first/last 3 s) →
  train set and headline evaluation; `edge` (crosses a phase start / touches guard) → evaluation of
  time-to-detect only; `idle` (all 10 s IDLE) → idle false-alarm rate only.
- Split by run (seed 20261023): 56 train / 14 val / 18 test runs; every meta_pair shows all its
  labels in every split. Threshold frozen on val at benign FPR 1%, applied to test.
- Shared metrics `scripts/ml/v4_eval.py` (baselines `baseline_v4.py`, LSTM `train_lstm_v4.py`,
  Kaggle package `artifacts/ml/kaggle-v4/`).

## Baseline findings (test, 18 runs) — read before interpreting any model
- **Designed downlink is a near-label proxy.** DL-kbps-only HGB reaches ROC-AUC 0.963 (all
  features 0.981; all minus DL 0.868; UL kbps stats 0.818; UL mean only 0.759; meta-only 0.486).
  Cause: every benign UDP flow receives the designed DN→UE feedback (1–10% of UL) and TCP/DNS
  benign get real replies, while an attacker's DL is 0 (silent) or tiny (responsive: ICMP/RST,
  median 4.7 kbps vs 86–94 kbps benign). The C2 control made DL independent of `victim_mode`, not
  of the label. Per pair without DL: udp_flood↔udp_bidir 0.98 → 0.77, fanout 1.0 → 0.86.
  Consequence: report every model with and without DL features (`--features no_dl`); the no-DL
  number is the robustness headline. UL/DL asymmetry is a real flood indicator, but its size here is
  a design artefact, so it must not carry the result.
- **icmp_flood ↔ icmp_ping is indistinguishable by construction** (AUC 0.46–0.56 for every feature
  set): same rate, same 84 B echo, the responsive DN answers both. Label = intent only. Report it
  separately, exclude it from "per-pair minimum" claims.
- Protocol pairs (dns, syn) are separable by protocol counters and by unmatched pps (dns benign
  ~900 pps vs flood ~75 pps; syn 330 vs 780 pps) — valid signal, but not a load-matched test.
- Genuinely hard pair: mimicry_udp ↔ udp_nofeedback (all HGB 0.88, without DL 0.85).

## Detector scope: UL-only (decision 2026-10-23)
- The main detector and every headline number use the 17 UL features only; all DL columns
  (`rate_dl`, `thp_dl`, `prb_dl`, `cell_prb_dl`, `urr_dl_*`, `prof_dl_*` incl. the DL protocol counters)
  are removed from training and evaluation. No derived feature uses DL.
- Why: the threat model is a UL flood originating at the UE; in this testbed the DL is a designed
  artefact (benign feedback 1–10% of UL, attack DL 0 / tiny), a near-label proxy (DL-only AUC 0.963).
  Results with DL are kept in an appendix with that caveat. Future work: a DL-aware detector needs
  realistic DL (real closed-loop applications), not designed feedback.
- Indirect-DL check through RAN UL (`reports/dl_leak_check_v4.md`): `prb_ul_pct/urr_ul_kbps` and
  `thp_ul_kbps/urr_ul_kbps` have overall AUC 0.525 / 0.503; strata above 0.6 (load 0.2, dns, pulsing)
  are identical for silent and responsive victims and absent in udp_flood↔udp_bidir (0.49 / 0.46), so
  they reflect packet size / burstiness, not DL feedback. The URR+prof-only and RAN-UL-without-PRB
  ablations are reported anyway.
- **Negative control:** icmp_flood↔icmp_ping is excluded from training, from the headline and from the
  per-pair macro; its AUC is reported alone for every model (expected ~0.5, > 0.6 = leak warning).
- Idle false alarms: rolling-feature GBDT flags every cold-start warm-up window (30 s of silence is
  outside the training distribution); an activity gate (classify only when the 10 s mean UL ≥ 50 kbps)
  removes them at no TPR cost. Reported as a secondary "gated" operating point, never instead of the
  raw one.

## Known limitations
- RFsim/GTP caps: UL linear region ≈ 10 Mbit/s per UE, payload ≤ 1200 B, TCP ≈ 330 kbps.
- Two iperf backend versions coexist (pre-fix for the iperf phases of the runs that passed the
  row guard, post-fix for the reruns and runs 76–88); both are used for both classes within a
  run, so the version is a run-level nuisance, not a label proxy. The pre-fix blocks ran with a
  ~5–15% inter-block gap, the post-fix ones are aligned to the 1 s grid.
- Row-weighted P(mal|ue) of runs 1–42 cannot be corrected after the fact (see weighting).
- Stream gaps up to ~2.7 s and attacker `prof_ul_pps` peaks down to ~24 pps sit close to their
  thresholds (3 s, 20 pps); thresholds were kept, not relaxed.
- Traffic is synthetic and statistically modelled (CBR, Poisson, MMPP-2, on-off Pareto, fGn,
  Hawkes, pulsing; real TCP handshakes and DNS answers for the hard negatives), not real user or
  application behaviour; load levels are discrete (0.2–1.2 Mbit/s per UE) and there is no
  low-rate background usage. Results show separability without the v3 shortcuts, not
  generalisation to real users.
- **pcap replay was rejected** as a realism test: replay is open-loop, so TCP never completes a
  handshake against the testbed's DN and benign replays look like SYN floods — any FPR measured that
  way is an artefact. A realism set, if needed later, must be closed-loop real applications
  (e.g. nginx + HLS/ffmpeg video, curl with Pareto think-time, SIPp/RTP), evaluation-only.
- Single-node minikube testbed; RFsim radio. A UE radio-link failure (run 76) and a host suspend
  (run 37) were observed; both invalidated the affected attempt.

## Distribution / maintenance
Internal research dataset; not for external release. Regenerable from `manifest/` + seed and
the raw run directories under `artifacts/experiments/` (backed up as tar.zst + SHA256SUMS in
`/home/ducsssanh/DATN-backup/<date>/`).
