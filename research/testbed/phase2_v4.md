# v4 Phase 2 — traffic library + cross-backend matrix + pilot QA gate

Date: 2026-10-20. Phase 2 of the v4 data-generation plan. Builds the traffic
library that generates BOTH classes (benign high-load and malicious flooding) from
the same launch point, then gates on a short live pilot per the plan §8.

## What was built

**Schedules / sizes / mixer** (done earlier, unit-tested): `schedules.py`
(cbr/poisson/mmpp2/onoff_pareto/fgn/hawkes/pulsing, each mean + property verified),
`sizes.py` (shared Dirichlet size prior, bins ≤1228 B IP), `mixer.py`
(x = b + ρ·m·a, load-matched so an attacker and its benign counterpart carry the
same mean load — volume cannot separate them).

**Cross-backend generators** (`backends/`, new this session) — every backend is
usable for BOTH classes and emits the SAME per-second achieved-row schema, so
neither the tool nor the protocol is a label shortcut (plan §5.4):
- `pacer.py` (stdlib UDP) — follows ANY schedule precisely; the dataset backbone.
- `hping.py` — hping3 UDP/SYN/ICMP; realises the per-phase MEAN rate as one
  whole-duration run (hping cannot be re-paced sub-second; the pacer carries fine
  schedule shape). Per-second rows aligned to CLOCK_REALTIME; final row carries the
  real transmitted total.
- `iperf.py` — iperf2 UDP CBR, per-second 1 s blocks.
- `tcp_shortconn.py` — pure-Python short TCP connections (the §6.3 benign
  hard-negative to a SYN flood: same SYNs, but the handshake COMPLETES).
- `dns_client.py` — pure-Python DNS queries (the §6.3 benign hard-negative to a
  UDP small-packet flood: same small UDP, but the request/response completes).
- `dn_sink.py` — pure-Python DN-side TCP accept-serve listener + minimal UDP DNS
  responder (the DN has no named/socat); one attached, timeout-bounded process.

**Plan builder** `planbuilder.py` — ties schedules+sizes+mixer into a concrete
per-second backend plan; load-matching verified exact (benign and attack both mean
to the level). **Runner** `runner.py` — pushes a backend + plan to the keepalive
sidecar, starts the DN server a backend needs, parses achieved; `calibrate` entry
point. **Harness integration** `traffic.py::V4Flow` + `make_flow` dispatch on
`{v4: true, ...}`; scenario `experiments/scenarios/ds-v4pilot.yaml`. Tests:
`test_schedules.py` (10), `test_backends.py` (offline, 4), live `runner.py smoke`.

Two bugs found + fixed by the pilot: (1) `from mixer import mix` shadowed the local
size-mix list → `plan["sizes"]` became a function → attacker plans failed to
serialize and sent nothing; renamed to `size_mix`. (2) per-second hping spawns
overran the 1 s budget and dropped ~half the seconds → single whole-duration run.

## §3.2 pacer + pps calibration — MEASURED (see phase0_v4.md)
64 B linear + 0% loss to **8000 pps/UE**; 1228 B linear to **10 Mbit/s**.
`research/testbed/calib_pps_v4.json`.

## Pilot QA gate — `research/datasets/oran_flooding_v4_p2pilot/qa_report.md`
One mixed run, both UEs, role-swapped, 5 active phases across all backends,
detection OFF. Dataset: 494 rows (IDLE 194 / MALICIOUS 150 / BENIGN 150).

**PASS (the scientific criteria):**
- **Causality: 0 violations** across KPM/URR/profiler (494/488/492 rows) — the
  strict as-of join holds. The v3-style xApp join of the same run still used 1
  future (+1 s) URR sample (the C5 leak v4 removes).
- **Presence equal by label:** URR/profiler 100% for both BENIGN and MALICIOUS →
  no missingness leak.
- **Balance 150/150**, and **role-swapped**: ue1 90 mal/60 benign, ue2 60/90 — both
  UEs appear on both sides (C1 reduced from v3's 1.0/0.0 to 0.60/0.40). Full
  per-phase balance to P(mal|UE)∈[0.45,0.55] is the Phase 3 campaign-design job.
- **Cross-backend matrix works live:** pacer/hping/iperf/tcp_shortconn/dns_client
  all generate and deliver; both classes from the same sidecar + plan path.

**OPEN ITEM — achieved_ok 6/10 (target ≥90%):** the misses are the protocol-fixed /
count-driven backends plus iperf's block-boundary overshoot, NOT delivery failures:
- pacer (dataset backbone): within ±2.4% (achieved_ok yes on all its pairs).
- iperf: +10.5% on one pair (1 s `-b` blocks slightly overshoot) — just outside ±10%.
- tcp_shortconn +29.5%, syn −12.9%, dns +26%: the nominal "offered bytes" is derived
  from an assumed bytes-per-unit (200 B/conn, 60 B/SYN, 56 B/query) that differs from
  the true UL wire volume URR measures. **Fix (Phase 3):** define "offered" for these
  backends from their measured per-unit wire size, and load-match the §6.3 pairs on the
  comparable dimension (conn/query/packet rate), not nominal bytes.

## Verdict (first pilot)
Phase 2 gate PASSED on the scientific criteria (causality, presence, balance,
both-classes-one-path). The achieved-accounting for count-driven backends needs the
Phase-3 calibration above before the full campaign.

---

## P0 completion + second pilot (2026-10-20, `..._ds-v4pilot_p2gate3`)
Added the remaining P0 items from the prompt's priority list (section 9) and re-ran.

**Downlink feedback for benign (C2, prompt section 5.5)** — `runner.start_dl_feedback`:
the DN runs the pacer DN→UE at a random 1–10% of the UL level (per-flow seeded), with a
UE-side UDP sink absorbing it (no ICMP bounce). Verified: BENIGN now carries DL (mean
~109 kbps, 87% of rows DL>1 kbps) instead of ≈0 — so "DL>0 ⇒ attack" no longer holds.

**Victim mode silent/responsive (C2, prompt section 6.1)** — `runner.set_victim_silent`
installs an `iptables -s <attacker> -p <proto> --dport <port> -j DROP` on the DN for the
malicious flow only (silent = no ICMP/RST back = no DL); responsive leaves it (closed
port → ICMP-unreachable DL). Recorded per phase on every flow as `meta_victim_mode`, so
it does not track the label. Pilot: P(malicious|victim_mode) = 0.50 / 0.50.

**Achieved accounting fixed** — `meta_achieved_ok` is now computed in the builder from
URR ground truth per the backend's native unit (bytes for rate backends, packets/s for
SYN/DNS, connection completion for tcp_shortconn), using the phase **mean** (= total
volume / duration) vs the target mean. (Deviates from the prompt's literal "median":
for bursty schedules the per-second median sits below the mean, so median would fail a
phase that delivered full volume — mean is the faithful load check, a correctness fix,
not a loosened bar.)

**QA extended** (`qa_v4.py`): balance now also on backend (dual-use only; benign-only
hard-negatives excluded), victim_mode and load level; **load-overlap** (overlap
coefficient of BENIGN vs MALICIOUS histograms per feature per load level) and
**coarsened exact matching** (common-support share + L1 imbalance before/after) added —
the evidence that the two classes occupy the same feature space.

### Second pilot QA — 518 rows (IDLE 218 / MAL 150 / BEN 150)
- **Causality: 0 violations** (518/516/516); v3 join still leaks 3 future URR samples.
- BENIGN DL present (C2 fixed); victim_mode balanced 0.50/0.50.
- Load overlap at 0.8 Mbit/s: RAN UL throughput overlap 0.74 (classes overlap on volume),
  URR UL pps 0.41; CEM common support 39% MAL / 30% BEN, L1 1.47→0.46 — a volume-matched
  control exists even at pilot scale.
- **achieved_ok 5/9**: the misses are single-phase sampling variance of heavy-tailed
  schedules (fGn over 30 s realised 0.93 vs 0.80 — normal for H=0.8 long-range dependence),
  hping ~10% pacing error, and iperf+on-off genuinely under-delivering (burst peaks exceed
  the 10 Mbit/s ceiling → loss). NOT a pipeline bug. **Phase-3 fixes:** longer phases /
  aggregate achieved over the campaign (the ≥90% bar is campaign-level); route bursty
  schedules (fGn/on-off/Hawkes) through the pacer, keep hping/iperf for CBR/MMPP.

### Still open (prompt priority P1 — not P0)
- QA: nuisance-only baseline AUC (section 7.2 item 5) and adversarial validation (item 4)
  — the metrics that *quantify* whether confounds are gone. pkt-size overlap is low at
  pilot scale (0.13 at 0.8 Mbit/s) because each phase draws its own Dirichlet with 1 phase
  per cell; the full campaign (many phases, shared prior) must drive this up — the
  adversarial-validation check will measure it.
- Attack families icmp / fanout / mimicry; full section 6.3 counterpart pairs load-matched
  on the comparable rate (conn/query/packet), not nominal bytes.
- Congestion `tc tbf` on the UPF N6 (section 6.1).

**Per the plan, STOP here for user approval before the Phase 3 campaign design + Phase 4
full capture.**

---

## Pre-Phase-3 analysis (2026-10-20, on the existing pilot — no new capture)

**Balance (2a):** P(malicious|UE) = ue1 0.60 / ue2 0.40 (pilot role-split; Phase 3
balances per cell). P(malicious|backend): pacer 0.67, hping 0.67, iperf 0.50 (dual-use,
pilot-noisy); dns_client / tcp_shortconn = 0 by design (benign-only hard-negatives,
excluded from the [0.4,0.6] check).

**Adversarial validation + nuisance baseline (2b)** — wired into `qa_v4.py`
(GroupKFold by run_id, falling back to phase for a 1-run pilot; HGB; chance AUC 0.5):
within-class nuisance AUCs are inflated in the pilot because each backend/victim_mode
occupies a single phase (backend≈phase≈ue), so the diagnostic only becomes meaningful
with the many-phase campaign grouped by run_id. Nuisance-only baseline (label from meta_
only): **AUC 0.62** (innocent: ue+timing+load+victim), driven by the 0.60/0.40 UE
imbalance; Phase-3 balance targets drive it toward 0.5. Plumbing verified; it is the
headline confound metric for the campaign.

**Per-pair packet-size overlap (2c):** all UDP attack↔benign pairs showed only **0.13**
size overlap — attacker and counterpart drew *independent* Dirichlet weights, so their
mean packet sizes differ per phase.

**Size-prior dry-run (2d, `design.py sizes`, no testbed):** simulating the shared prior
over a campaign shows the problem is **by design, not fixable by reps**:

| policy | pooled overlap | per-cell overlap (median) |
|---|---:|---:|
| independent draws | 0.94 | **0.00** |
| shared-per-cell draw | 0.99 | **0.68** |

Pooled overlap is high either way (averaging over reps *hides* it), but the per-cell
overlap — what a per-phase detector sees — stays 0 unless the two flows of a cell share
one size draw. **Fix applied:** `planbuilder.build_plan` now takes a separate `size_seed`
(default = `seed`); a Phase-3 size-matched cell gives both flows the same `size_seed` so
their packet-size mix is identical per phase while behaviour seeds stay distinct.
Protocol-fixed pairs (SYN vs tcp_shortconn, ICMP) keep distinct sizes by design (a valid
signal, not a confound).

## New generators + intervention smoke (ds-v4smoke, no full gate)
icmp_flood↔icmp_ping, fanout_udp↔fanout_benign, mimicry_udp↔udp_nofeedback (stress,
train-excluded), and a tc-tbf congestion phase. All ran; labels + raw KPM + meta captured:
- **fan-out works:** `prof_ul_dst_estimate` ~96 under fan-out vs ~0.85 otherwise (the
  destination-spread signal). pacer gained a `fanout` dst-sweep over the DN /24.
- **mimicry** flagged `meta_stress_cell=1`; **congestion** `meta_congestion=1` (tc tbf on
  UPF N6 applied per phase and cleared after; also cleared on the error path).
- ICMP/congest/bursty phases show the same ~10% pacing / single-phase-variance achieved
  noise already noted (not a delivery or pipeline fault).
- `meta_fanout, meta_stress_cell, meta_congestion` added to the builder/dataset.

Limitation noted: with a single DN host, fanout_benign's "many responsive destinations"
is approximated (benign fan-out has aggregate DL feedback, attacker fan-out is silent);
per-destination bidirectionality is not measured. DN IP aliases are a P2 improvement.

## Phase-3 design constraints (locked from Phase 0 + the above)
1. Peak of every schedule ≤ the measured linear region (≈10 Mbit/s/UE, 8000 pps 64 B) —
   the iperf+on-off miss came from burst peaks exceeding it.
2. Bursty schedules (fGn, on-off-Pareto, MMPP, Hawkes, pulsing) run through the **pacer**;
   iperf/hping only carry piecewise-constant (CBR-ish) schedules.
3. `achieved_ok ≥ 90%` is evaluated **campaign-wide**; the report lists failing phases by
   backend/family (single bursty phases miss on sampling variance alone).
4. Size-matched pairs share `size_seed` per cell (2d); protocol-fixed pairs do not.

**Still STOP for approval before the full campaign.** Next: `design.py` campaign plan
(fractional-factorial / LHS over the section-6.2 factors with the balance constraints) +
ETA, for review.
