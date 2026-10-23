# Trust-weighted cross-domain defence — replay on v4 val runs (stage A)

14 held-out val runs; models trained on train runs only (never on tampered data); integrity rule τ=0.7, m=10 s (chosen on honest train+val: ≤1% of honest phases alarmed). Phase-level metrics over attack / benign phases (icmp control excluded). Brackets = 95% bootstrap CI by run. Defence actions are not replayed into the traffic (v4 was recorded with defence off): times are decision times. v2 = asymmetric integrity rule, added after inspecting v1 on the test runs and checked on the val runs first.

## honest

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.72 [0.607, 0.844] | 0.507 | 14.4 | 0.493 | 23.1 | 0.052 | 0.0 [0.0, 0.0] | None | None |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | None | None |
| cross-domain naive | 0.72 [0.562, 0.878] | 0.627 | 13.9 | 0.587 | 22.7 | 0.052 | 0.013 [0.0, 0.038] | None | None |
| cross-domain trust-weighted | 0.72 [0.562, 0.878] | 0.627 | 13.9 | 0.467 | 22.9 | 0.052 | 0.0 [0.0, 0.0] | None | None |
| cross-domain trust-weighted v2 | 0.72 [0.562, 0.878] | 0.627 | 13.9 | 0.467 | 22.9 | 0.052 | 0.0 [0.0, 0.0] | None | None |

## kpm_hide x0.1

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 | None | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None |
| cross-domain naive | 0.64 [0.516, 0.75] | 0.467 | 13.7 | 0.56 | 22.5 | 0.052 | 0.013 [0.0, 0.038] | 0.0 | None |
| cross-domain trust-weighted | 0.6 [0.461, 0.738] | 0.467 | 14.5 | 0.52 | 22.6 | 0.052 | 0.0 [0.0, 0.0] | 1.0 | 14.1 |
| cross-domain trust-weighted v2 | 1.0 [1.0, 1.0] | 0.907 | 14.6 | 1.0 | 23.6 | 0.052 | 0.0 [0.0, 0.0] | 1.0 | 14.1 |

## kpm_frame x5

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.72 [0.607, 0.844] | 0.533 | 14.0 | 0.493 | 23.1 | 0.987 | 0.948 [0.883, 1.0] | 0.0 | None | 0.948 [0.883, 1.0] |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 [0.0, 0.0] |
| cross-domain naive | 0.733 [0.573, 0.891] | 0.653 | 13.2 | 0.587 | 22.2 | 0.662 | 0.532 [0.377, 0.692] | 0.0 | None | 0.532 [0.377, 0.692] |
| cross-domain trust-weighted | 0.627 [0.522, 0.752] | 0.493 | 13.9 | 0.507 | 22.1 | 0.351 | 0.013 [0.0, 0.038] | 1.0 | 11.5 | 0.013 [0.0, 0.038] |
| cross-domain trust-weighted v2 | 0.627 [0.522, 0.752] | 0.493 | 13.9 | 0.507 | 22.1 | 0.351 | 0.013 [0.0, 0.038] | 1.0 | 11.5 | 0.013 [0.0, 0.038] |

## core_outage

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.72 [0.607, 0.844] | 0.507 | 14.4 | 0.493 | 23.1 | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |
| core-only (5GC) | 0.253 [0.144, 0.371] | 0.213 | 12.6 | 0.227 | 21.1 | 0.026 | 0.0 [0.0, 0.0] | 0.0 | None |
| cross-domain naive | 0.747 [0.642, 0.847] | 0.613 | 15.7 | 0.547 | 23.1 | 0.273 | 0.169 [0.098, 0.248] | 0.0 | None |
| cross-domain trust-weighted | 0.72 [0.614, 0.84] | 0.56 | 13.9 | 0.173 | 22.9 | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |
| cross-domain trust-weighted v2 | 0.72 [0.614, 0.84] | 0.56 | 13.9 | 0.173 | 22.9 | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |

## kpm_hide x0.2

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 | None | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None |
| cross-domain naive | 0.8 [0.696, 0.896] | 0.64 | 14.6 | 0.613 | 22.9 | 0.052 | 0.013 [0.0, 0.038] | 0.0 | None |
| cross-domain trust-weighted | 0.613 [0.467, 0.75] | 0.467 | 13.9 | 0.52 | 22.6 | 0.052 | 0.0 [0.0, 0.0] | 1.0 | 14.5 |
| cross-domain trust-weighted v2 | 1.0 [1.0, 1.0] | 0.907 | 14.6 | 1.0 | 23.6 | 0.052 | 0.0 [0.0, 0.0] | 1.0 | 14.5 |

## kpm_hide x0.33

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 | None | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None |
| cross-domain naive | 0.867 [0.783, 0.945] | 0.68 | 14.6 | 0.68 | 23.5 | 0.052 | 0.013 [0.0, 0.038] | 0.0 | None |
| cross-domain trust-weighted | 0.627 [0.483, 0.768] | 0.493 | 13.9 | 0.52 | 22.8 | 0.052 | 0.0 [0.0, 0.0] | 1.0 | 15.5 |
| cross-domain trust-weighted v2 | 1.0 [1.0, 1.0] | 0.92 | 15.5 | 1.0 | 24.5 | 0.052 | 0.0 [0.0, 0.0] | 1.0 | 15.5 |

## kpm_hide x0.5

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.04 [0.0, 0.088] | 0.027 | 16.4 | 0.013 | 59.3 | 0.052 | 0.0 [0.0, 0.0] | 0.0 | None |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None |
| cross-domain naive | 0.88 [0.792, 0.956] | 0.68 | 14.1 | 0.707 | 22.9 | 0.052 | 0.013 [0.0, 0.038] | 0.0 | None |
| cross-domain trust-weighted | 0.787 [0.644, 0.939] | 0.613 | 14.0 | 0.387 | 22.8 | 0.052 | 0.0 [0.0, 0.0] | 0.68 | 23.1 |
| cross-domain trust-weighted v2 | 0.867 [0.771, 0.969] | 0.627 | 14.6 | 0.453 | 23.0 | 0.052 | 0.0 [0.0, 0.0] | 0.68 | 23.1 |

## kpm_frame x2

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.707 [0.603, 0.825] | 0.493 | 15.2 | 0.493 | 23.8 | 0.636 | 0.494 [0.335, 0.638] | 0.0 | None | 0.494 [0.335, 0.638] |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 [0.0, 0.0] |
| cross-domain naive | 0.707 [0.557, 0.861] | 0.627 | 13.9 | 0.587 | 22.7 | 0.455 | 0.364 [0.222, 0.507] | 0.0 | None | 0.364 [0.222, 0.507] |
| cross-domain trust-weighted | 0.68 [0.554, 0.821] | 0.547 | 14.1 | 0.453 | 23.3 | 0.208 | 0.013 [0.0, 0.038] | 0.636 | 11.5 | 0.013 [0.0, 0.038] |
| cross-domain trust-weighted v2 | 0.68 [0.554, 0.821] | 0.547 | 14.1 | 0.453 | 23.3 | 0.208 | 0.013 [0.0, 0.038] | 0.636 | 11.5 | 0.013 [0.0, 0.038] |

## kpm_frame x3

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.72 [0.607, 0.844] | 0.533 | 14.1 | 0.493 | 23.1 | 0.909 | 0.805 [0.703, 0.909] | 0.0 | None | 0.805 [0.703, 0.909] |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 [0.0, 0.0] |
| cross-domain naive | 0.733 [0.573, 0.891] | 0.653 | 13.3 | 0.587 | 22.3 | 0.558 | 0.455 [0.309, 0.629] | 0.0 | None | 0.455 [0.309, 0.629] |
| cross-domain trust-weighted | 0.627 [0.522, 0.752] | 0.493 | 13.9 | 0.507 | 22.1 | 0.338 | 0.0 [0.0, 0.0] | 1.0 | 11.7 | 0.0 [0.0, 0.0] |
| cross-domain trust-weighted v2 | 0.627 [0.522, 0.752] | 0.493 | 13.9 | 0.507 | 22.1 | 0.338 | 0.0 [0.0, 0.0] | 1.0 | 11.7 | 0.0 [0.0, 0.0] |

## kpm_frame x10

| configuration | attack detected (L1) | detected ≤20 s | t→L1 median s | attack blocked (L3) | t→L3 median s | benign soft-isolated (L1) | benign wrongly blocked (L3) | KPM integrity alarm on tampered | t→integrity s | framed benign blocked (L3) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RAN-only (xApp KPM) | 0.72 [0.607, 0.844] | 0.533 | 13.9 | 0.493 | 23.1 | 0.987 | 0.935 [0.856, 1.0] | 0.0 | None | 0.935 [0.856, 1.0] |
| core-only (5GC) | 0.587 [0.45, 0.729] | 0.453 | 12.8 | 0.52 | 21.6 | 0.039 | 0.0 [0.0, 0.0] | 0.0 | None | 0.0 [0.0, 0.0] |
| cross-domain naive | 0.733 [0.573, 0.891] | 0.653 | 13.2 | 0.587 | 22.1 | 0.766 | 0.714 [0.574, 0.832] | 0.0 | None | 0.714 [0.574, 0.832] |
| cross-domain trust-weighted | 0.627 [0.522, 0.752] | 0.493 | 13.9 | 0.507 | 22.1 | 0.519 | 0.013 [0.0, 0.038] | 1.0 | 11.4 | 0.013 [0.0, 0.038] |
| cross-domain trust-weighted v2 | 0.627 [0.522, 0.752] | 0.493 | 13.3 | 0.507 | 22.1 | 0.519 | 0.013 [0.0, 0.038] | 1.0 | 11.4 | 0.013 [0.0, 0.038] |

