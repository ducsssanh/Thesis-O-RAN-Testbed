# Cross-domain defence: trust-weighted rules + GBDT (v4, replay stage)

## Rule set (`scripts/ml/fusion_v4.py`)
Per UE and second, in the xApp's decision layer:
1. **Three models** (GBDT on causal rolling UL features): cross-domain (KPM+URR+profiler), core
   (URR+profiler), RAN (KPM). Each score is divided by its own val threshold (benign FPR 1%): z ≥ 1 = alarm.
2. **KPM↔URR integrity rule:** |log(Σ KPM UL / Σ URR UL) over 10 s − bias| > τ for m consecutive
   seconds while the UE is active ⇒ integrity alarm (E2 node flagged at once) and `kpm_trust` = 0 for
   60 s, then back to 1 over 30 s. τ = 0.7 (a factor of 2), m = 10 s, chosen before testing on the
   honest train+val runs (≤ 1% of honest phases alarmed; measured 0.12%).
3. **core_trust** = 0 while URR is stale (age > 4 s or missing).
4. **Fusion:** z = kt·ct·z_xd + (1−kt)·ct·z_core + kt·(1−ct)·z_ran — the domain that can be trusted
   decides; with both trusted the cross-domain model decides.
5. **Asymmetric integrity (v2):** KPM < URR (the RAN under-reports what the core measured — someone hides
   this UE) counts as core evidence against the UE while it persists; KPM > URR (the RAN over-reports —
   someone frames this UE) only flags the E2 node, the UE is judged by the core.
6. **Fair-use rules** (classifier v1): KPM UL > 2 Mbit/s with cell PRB UL ≥ 80% (3 of 4) = RAN
   evidence (ignored while kpm_trust < 0.5); URR UL > 2 Mbit/s (3 of 4) = core evidence.
7. **Escalation:** L1 soft isolation (RAN slice / UPF monitor, reversible) when the fused alarm holds
   3 of 5 s (activity gate UL ≥ 50 kbps); **L3 block** (UPF block + RRC release) after L1 has held 10 s
   **and both layers agree** — or core evidence alone when kpm_trust < 0.5.

Baselines: RAN-only (xApp with KPM only: RAN model + KPM rule), core-only (5GC defence: core model + URR
rule), cross-domain naive (one cross-domain model, no trust, no integrity rule).

## Scenarios (built from the 18 held-out test runs; models never saw tampered data)
- **honest** — v4 as recorded (load-matched low-rate floods vs legitimate load).
- **kpm_hide ×f** — E2 MITM deflates the attacker's KPM (rate, throughput, PRB) by f during attacks.
- **kpm_frame ×f** — E2 MITM inflates a benign UE's KPM by f (an innocent UE is framed).
- **core_outage** — URR/profiler missing for half of the phases (A1-EI path down).

## Procedure and honesty notes
- Rules and τ/m fixed before any test run. v1 (symmetric integrity) was run on test first; v2 (asymmetric
  rule) was designed after seeing v1's test results, developed on the val runs (a 60 s hold of the
  under-report flag was tried and dropped on val because it spilled into the next phase — v4 swaps UE
  roles), then frozen and run once on test. Both versions are reported.
- Replay: v4 was recorded with the defence off, so actions do not change the traffic; times are decision
  times from the phase start, including the 10 s window fill. Live confirmation (stage B: sidecar +
  E2 MITM proxy in the testbed) is still to be done.

## Key results (test, phase level; brackets = 95% bootstrap CI by run)
| scenario | RAN-only | core-only | cross-domain naive | **trust-weighted v2** |
|---|---|---|---|---|
| honest — attacks detected (L1) | 0.607 | 0.663 | 0.697 | **0.697** [0.600–0.805] |
| honest — benign wrongly blocked (L3) | 0.010 | 0.010 | 0.019 | **0.010** [0–0.032] |
| kpm_hide ×0.1 — attacks detected / blocked | 0.000 / 0.000 | 0.663 / 0.483 | 0.798 / 0.640 | **1.000 / 0.989** |
| kpm_hide ×0.33 — detected / blocked | 0.000 / 0.000 | 0.663 / 0.483 | 0.921 / 0.753 | **1.000 / 0.966** |
| kpm_hide ×0.5 — detected / blocked | 0.056 / 0.011 | 0.663 / 0.483 | 0.899 / 0.798 | 0.921 / 0.371 |
| kpm_frame ×2 — framed benign wrongly blocked | 0.660 | 0.010 | 0.437 | **0.010** [0–0.032] |
| kpm_frame ×5 — framed benign wrongly blocked | 0.932 | 0.010 | 0.757 | **0.019** [0–0.063] |
| core_outage — attacks detected (L1) | 0.607 | 0.360 | 0.787 | **0.652** |
| core_outage — benign wrongly blocked (L3) | 0.010 | 0.010 | 0.204 | **0.010** |
| KPM integrity alarm on tampered phases | – | – | – | 1.000 (×0.1, ×5), 0.989 (×0.33), 0.728 (×2), 0.483 (×0.5); 0 false on honest phases; median 11–16 s |

## Conclusions
1. **Hidden flood (KPM deflated):** the RAN-only xApp is blind (0%); the integrity rule exposes the
   mismatch and the trust-weighted engine detects 100% and blocks 97–99% (×0.1–×0.33) — better than the
   core alone (66% / 48%) and the naive model (80–92% / 64–75%). Below a factor-2 tamper (×0.5) the integrity
   rule catches half the cases: the detection limit of a 10 s volume check.
2. **Framed UE (KPM inflated):** RAN-only wrongly blocks 66–93% of the framed benign phases and the naive
   cross-domain model 44–76%; the trust-weighted engine blocks 1–2% — the core vetoes the RAN.
3. **Core telemetry outage:** core-only drops to 36% detection; the naive model, fed missing core inputs,
   wrongly blocks 20% of benign phases; the trust-weighted engine falls back to the RAN (65% detection,
   1% wrongful blocks) and caps blocking, as designed (blocking needs a trusted core).
4. **Cost:** with honest telemetry the both-layer block rule blocks fewer attacks (0.337 vs 0.506 naive):
   detection (L1) is the same, blocking is more conservative. L1 soft isolation of framed benign UEs still
   happens (27–57%) before the integrity alarm fires (~11 s) — reversible, but reported.

---

# Trust-weighted cross-domain defence — replay on v4 test runs (stage A)

18 held-out test runs; models trained on train runs only (never on tampered data); integrity rule τ=0.7, m=10 s (chosen on honest train+val: ≤1% of honest phases alarmed). Phase-level metrics over attack / benign phases (icmp control excluded). Brackets = 95% bootstrap CI by run. Defence actions are not replayed into the traffic (v4 was recorded with defence off): times are decision times. v2 = asymmetric integrity rule, added after inspecting v1 on the test runs and checked on the val runs first.

## honest

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.607 [0.481, 0.742] | 0.427 | 16.0 | 0.416 | 26.3 | 0.049 | 0.01 [0.0, 0.032] | None | None |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | None | None |
| cross-domain naive | 0.697 [0.6, 0.805] | 0.573 | 15.2 | 0.506 | 23.7 | 0.058 | 0.019 [0.0, 0.05] | None | None |
| cross-domain trust-weighted | 0.697 [0.6, 0.805] | 0.573 | 15.2 | 0.337 | 24.4 | 0.058 | 0.01 [0.0, 0.032] | None | None |
| cross-domain trust-weighted v2 | 0.697 [0.6, 0.805] | 0.573 | 15.2 | 0.337 | 24.4 | 0.058 | 0.01 [0.0, 0.032] | None | None |

## kpm_hide x0.1

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 | None | 0.049 | 0.019 [0.0, 0.05] | 0.0 | None |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None |
| cross-domain naive | 0.798 [0.658, 0.919] | 0.517 | 16.0 | 0.64 | 24.4 | 0.058 | 0.019 [0.0, 0.05] | 0.0 | None |
| cross-domain trust-weighted | 0.674 [0.577, 0.787] | 0.416 | 17.6 | 0.461 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 1.0 | 13.6 |
| cross-domain trust-weighted v2 | 1.0 [1.0, 1.0] | 0.888 | 15.1 | 0.989 | 24.1 | 0.049 | 0.019 [0.0, 0.05] | 1.0 | 13.6 |

## kpm_frame x5

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.618 [0.487, 0.763] | 0.483 | 13.8 | 0.416 | 25.3 | 1.0 | 0.932 [0.86, 0.981] | 0.0 | None | 0.932 [0.86, 0.981] |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None | 0.01 [0.0, 0.032] |
| cross-domain naive | 0.719 [0.62, 0.824] | 0.607 | 13.9 | 0.517 | 22.7 | 0.874 | 0.757 [0.66, 0.845] | 0.0 | None | 0.757 [0.66, 0.845] |
| cross-domain trust-weighted | 0.663 [0.567, 0.781] | 0.472 | 15.6 | 0.449 | 24.3 | 0.573 | 0.019 [0.0, 0.063] | 1.0 | 11.3 | 0.019 [0.0, 0.063] |
| cross-domain trust-weighted v2 | 0.663 [0.567, 0.781] | 0.472 | 15.6 | 0.449 | 24.3 | 0.573 | 0.019 [0.0, 0.063] | 1.0 | 11.3 | 0.019 [0.0, 0.063] |

## core_outage

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.607 [0.481, 0.742] | 0.427 | 16.0 | 0.416 | 26.3 | 0.049 | 0.01 [0.0, 0.032] | 0.0 | None |
| core-only (5GC) | 0.36 [0.247, 0.465] | 0.191 | 20.0 | 0.247 | 25.0 | 0.019 | 0.01 [0.0, 0.032] | 0.0 | None |
| cross-domain naive | 0.787 [0.725, 0.857] | 0.607 | 15.6 | 0.517 | 24.2 | 0.291 | 0.204 [0.113, 0.313] | 0.0 | None |
| cross-domain trust-weighted | 0.652 [0.537, 0.778] | 0.506 | 15.6 | 0.18 | 27.3 | 0.058 | 0.01 [0.0, 0.032] | 0.0 | None |
| cross-domain trust-weighted v2 | 0.652 [0.537, 0.778] | 0.506 | 15.6 | 0.18 | 27.3 | 0.058 | 0.01 [0.0, 0.032] | 0.0 | None |

## kpm_hide x0.2

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 | None | 0.049 | 0.019 [0.0, 0.05] | 0.0 | None |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None |
| cross-domain naive | 0.843 [0.714, 0.947] | 0.64 | 15.7 | 0.697 | 24.3 | 0.058 | 0.019 [0.0, 0.05] | 0.0 | None |
| cross-domain trust-weighted | 0.674 [0.585, 0.779] | 0.449 | 16.5 | 0.472 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 1.0 | 14.0 |
| cross-domain trust-weighted v2 | 1.0 [1.0, 1.0] | 0.888 | 15.2 | 1.0 | 24.2 | 0.049 | 0.019 [0.0, 0.05] | 1.0 | 14.0 |

## kpm_hide x0.33

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 | None | 0.049 | 0.019 [0.0, 0.05] | 0.0 | None |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None |
| cross-domain naive | 0.921 [0.878, 0.963] | 0.652 | 15.6 | 0.753 | 24.1 | 0.058 | 0.019 [0.0, 0.05] | 0.0 | None |
| cross-domain trust-weighted | 0.742 [0.649, 0.837] | 0.539 | 15.3 | 0.461 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.989 | 16.3 |
| cross-domain trust-weighted v2 | 1.0 [1.0, 1.0] | 0.854 | 15.6 | 0.966 | 24.4 | 0.049 | 0.019 [0.0, 0.05] | 0.989 | 16.3 |

## kpm_hide x0.5

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.056 [0.0, 0.117] | 0.011 | 36.3 | 0.011 | 44.2 | 0.049 | 0.019 [0.0, 0.05] | 0.0 | None |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None |
| cross-domain naive | 0.899 [0.808, 0.971] | 0.753 | 14.8 | 0.798 | 23.7 | 0.058 | 0.019 [0.0, 0.05] | 0.0 | None |
| cross-domain trust-weighted | 0.899 [0.825, 0.963] | 0.685 | 15.3 | 0.27 | 24.5 | 0.049 | 0.01 [0.0, 0.032] | 0.483 | 29.8 |
| cross-domain trust-weighted v2 | 0.921 [0.859, 0.977] | 0.697 | 15.3 | 0.371 | 30.2 | 0.049 | 0.01 [0.0, 0.032] | 0.483 | 29.8 |

## kpm_frame x2

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.618 [0.487, 0.763] | 0.427 | 15.6 | 0.404 | 25.9 | 0.777 | 0.66 [0.563, 0.748] | 0.0 | None | 0.66 [0.563, 0.748] |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None | 0.01 [0.0, 0.032] |
| cross-domain naive | 0.708 [0.608, 0.816] | 0.584 | 14.6 | 0.506 | 22.9 | 0.563 | 0.437 [0.323, 0.541] | 0.0 | None | 0.437 [0.323, 0.541] |
| cross-domain trust-weighted | 0.685 [0.589, 0.8] | 0.506 | 15.6 | 0.404 | 24.9 | 0.272 | 0.01 [0.0, 0.032] | 0.728 | 11.3 | 0.01 [0.0, 0.032] |
| cross-domain trust-weighted v2 | 0.685 [0.589, 0.8] | 0.506 | 15.6 | 0.404 | 24.9 | 0.272 | 0.01 [0.0, 0.032] | 0.728 | 11.3 | 0.01 [0.0, 0.032] |

## kpm_frame x3

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.618 [0.487, 0.763] | 0.472 | 14.1 | 0.416 | 25.3 | 0.971 | 0.893 [0.83, 0.95] | 0.0 | None | 0.893 [0.83, 0.95] |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None | 0.01 [0.0, 0.032] |
| cross-domain naive | 0.719 [0.62, 0.824] | 0.607 | 13.9 | 0.517 | 22.7 | 0.699 | 0.612 [0.528, 0.68] | 0.0 | None | 0.612 [0.528, 0.68] |
| cross-domain trust-weighted | 0.663 [0.567, 0.781] | 0.472 | 15.6 | 0.449 | 24.3 | 0.398 | 0.019 [0.0, 0.063] | 0.99 | 11.5 | 0.019 [0.0, 0.063] |
| cross-domain trust-weighted v2 | 0.663 [0.567, 0.781] | 0.472 | 15.6 | 0.449 | 24.3 | 0.398 | 0.019 [0.0, 0.063] | 0.99 | 11.5 | 0.019 [0.0, 0.063] |

## kpm_frame x10

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.618 [0.487, 0.763] | 0.483 | 13.8 | 0.416 | 25.3 | 1.0 | 0.981 [0.953, 1.0] | 0.0 | None | 0.981 [0.953, 1.0] |
| core-only (5GC) | 0.663 [0.565, 0.775] | 0.427 | 17.5 | 0.483 | 24.3 | 0.039 | 0.01 [0.0, 0.032] | 0.0 | None | 0.01 [0.0, 0.032] |
| cross-domain naive | 0.719 [0.62, 0.824] | 0.607 | 13.9 | 0.517 | 22.7 | 0.922 | 0.883 [0.816, 0.946] | 0.0 | None | 0.883 [0.816, 0.946] |
| cross-domain trust-weighted | 0.663 [0.567, 0.781] | 0.472 | 15.6 | 0.449 | 24.3 | 0.68 | 0.019 [0.0, 0.063] | 1.0 | 11.2 | 0.019 [0.0, 0.063] |
| cross-domain trust-weighted v2 | 0.663 [0.567, 0.781] | 0.483 | 15.6 | 0.449 | 24.3 | 0.68 | 0.019 [0.0, 0.063] | 1.0 | 11.2 | 0.019 [0.0, 0.063] |

