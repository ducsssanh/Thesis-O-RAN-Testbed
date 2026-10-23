# v4 model evaluation — UL-only detector (2026-10-23)

Test = 18 held-out runs (split by run, seed 20261023); threshold frozen on val at benign FPR 1%; operating point = activity gate (10 s mean UL ≥ 50 kbps, fixed); icmp_flood↔icmp_ping = negative control (out of training, headline and macro). LSTM: 2×64, 10 s window, 17 UL features, trained on Colab T4, re-evaluated here with the same `v4_eval.py` as the GBDTs. DL features only in the appendix (designed benign DL feedback is a near-label proxy). Details: `baseline_ul_v4.md`, `leak_phase_v4.md`, `dl_leak_check_v4.md`.

## 1. Headline (test)

| model | ROC-AUC | PR-AUC | TPR@FPR1% | pair macro | mimicry | pulsing | icmp control | FPR | idle FPR | idle FPR ungated | det ≤10 s | det ≤20 s | TTD med s | benign phases alarmed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **LSTM ul** (3 seeds, mean ± std) | 0.838 ± 0.007 | 0.832 ± 0.006 | 0.332 ± 0.006 | 0.840 ± 0.003 | 0.783 ± 0.003 | 0.946 ± 0.012 | 0.511 ± 0.023 | 0.017 ± 0.004 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.101 ± 0.040 | 0.434 ± 0.026 | 11.700 ± 0.294 | 0.194 ± 0.035 |
| **LSTM urr_prof_ul** (3 seeds, mean ± std) | 0.779 ± 0.005 | 0.771 ± 0.004 | 0.209 ± 0.006 | 0.787 ± 0.006 | 0.707 ± 0.021 | 0.902 ± 0.007 | 0.510 ± 0.013 | 0.007 ± 0.002 | 0.000 ± 0.000 | 0.000 ± 0.000 | 0.026 ± 0.029 | 0.270 ± 0.016 | 12.000 ± 0.245 | 0.074 ± 0.030 |
| GBDT rolling cross-domain UL | 0.930 | 0.924 | 0.467 | 0.936 | 0.873 | 0.974 | 0.495 | 0.016 | 0.004 | 0.204 | 0.000 | 0.652 | 13.200 | 0.117 |
| GBDT rolling <=10 s cross-domain UL | 0.900 | 0.896 | 0.394 | 0.907 | 0.848 | 0.947 | 0.488 | 0.011 | 0.001 | 0.001 | 0.022 | 0.596 | 12.600 | 0.107 |
| GBDT rolling URR+prof (UL) | 0.908 | 0.910 | 0.427 | 0.914 | 0.858 | 0.941 | 0.472 | 0.005 | 0.000 | 0.007 | 0.101 | 0.596 | 14.200 | 0.058 |
| GBDT rolling <=10 s URR+prof (UL) | 0.874 | 0.872 | 0.355 | 0.876 | 0.806 | 0.877 | 0.501 | 0.012 | 0.000 | 0.000 | 0.090 | 0.506 | 13.500 | 0.087 |
| GBDT rolling RAN-UL | 0.865 | 0.861 | 0.324 | 0.884 | 0.877 | 0.954 | 0.614 | 0.010 | 0.036 | 0.121 | 0.000 | 0.551 | 13.600 | 0.155 |
| GBDT rolling URR-UL | 0.860 | 0.852 | 0.206 | 0.856 | 0.835 | 0.804 | 0.534 | 0.007 | 0.000 | 0.001 | 0.011 | 0.258 | 19.800 | 0.039 |
| GBDT rolling prof-UL | 0.873 | 0.872 | 0.368 | 0.870 | 0.820 | 0.908 | 0.446 | 0.009 | 0.000 | 0.000 | 0.112 | 0.461 | 14.800 | 0.087 |
| per-second UL (1 s) | 0.790 | 0.789 | 0.288 | 0.770 | 0.678 | 0.722 | 0.513 | 0.017 | 0.000 | 0.000 | 0.427 | 0.528 | 6.400 | 0.233 |
| UL volume (kbps, rolling) | 0.863 | 0.852 | 0.294 | 0.875 | 0.856 | 0.941 | 0.493 | 0.020 | 0.000 | 0.001 | 0.000 | 0.562 | 15.000 | 0.126 |
| nuisance (meta only) | 0.493 | 0.480 | 0.006 | 0.502 | 0.390 | 0.576 | 0.461 | 0.003 | 0.000 | 0.000 | 0.000 | 0.000 | 63.000 | 0.029 |

95% bootstrap CI by run — LSTM ul seed 0: ROC [0.7743, 0.8835], PR [0.7574, 0.8842], TPR [0.2307, 0.437], macro [0.8119, 0.8768], icmp [0.4875, 0.523]; GBDT 30 s: ROC [0.8944, 0.9606], TPR [0.377, 0.5643]; GBDT ≤10 s: ROC [0.8525, 0.9376], TPR [0.3029, 0.5028].

## 2. Validation → test gap

| model | val ROC-AUC | test ROC-AUC | gap |
|---|---:|---:|---:|
| LSTM ul seed 0 | 0.907 | 0.833 | -0.074 |
| LSTM ul 3-seed score mean | 0.919 | 0.852 | -0.067 |
| GBDT rolling <=10 s cross-domain UL | 0.928 | 0.900 | -0.029 |
| GBDT rolling cross-domain UL | 0.952 | 0.930 | -0.022 |

## 3. Paired bootstrap by run (A − B, 95% CI)

| A − B | ΔROC-AUC | ΔPR-AUC | ΔTPR@FPR1% | Δpair macro |
|---|---:|---:|---:|---:|
| LSTM ul s0 − GBDT rolling <=10 s cross-domain UL | -0.067 [-0.093, -0.041] | -0.068 [-0.091, -0.043] | -0.069 [-0.116, -0.017] | -0.066 [-0.087, -0.013] |
| LSTM ul s0 − GBDT rolling cross-domain UL | -0.097 [-0.131, -0.069] | -0.096 [-0.122, -0.069] | -0.143 [-0.219, -0.060] | -0.095 [-0.120, -0.067] |
| LSTM ul 3-seed mean − GBDT rolling <=10 s cross-domain UL | -0.048 [-0.070, -0.028] | -0.050 [-0.072, -0.027] | -0.065 [-0.112, -0.012] | -0.055 [-0.073, -0.007] |
| GBDT rolling cross-domain UL - GBDT rolling URR+prof (UL) | +0.022 [+0.005, +0.045] | +0.014 [-0.002, +0.036] | +0.040 [+0.002, +0.076] | +0.022 [+0.008, +0.052] |
| GBDT rolling cross-domain UL - GBDT rolling RAN-UL | +0.064 [+0.036, +0.094] | +0.063 [+0.037, +0.088] | +0.143 [+0.058, +0.223] | +0.053 [+0.021, +0.070] |
| GBDT rolling cross-domain UL - GBDT rolling URR-UL | +0.070 [+0.042, +0.102] | +0.072 [+0.041, +0.107] | +0.261 [+0.195, +0.320] | +0.081 [+0.041, +0.125] |
| GBDT rolling cross-domain UL - GBDT rolling prof-UL | +0.057 [+0.028, +0.092] | +0.052 [+0.023, +0.088] | +0.099 [+0.037, +0.159] | +0.066 [+0.040, +0.110] |
| GBDT rolling cross-domain UL - GBDT rolling <=10 s cross-domain UL | +0.030 [+0.014, +0.052] | +0.028 [+0.009, +0.050] | +0.073 [+0.019, +0.119] | +0.029 [+0.012, +0.069] |

## 4. Does the LSTM use time order? (time steps permuted inside every test window)

LSTM ul: ROC-AUC 0.838 ± 0.007 → shuffled 0.829 ± 0.005 (Δ -0.010). The LSTM is nearly order-blind: it behaves as a bag of 10 seconds.

## 5. Split-seed repeat (3 run splits, mean ± std)

| model | roc_auc | pr_auc | tpr | pair_macro_auc | mimicry_auc | pulsing_auc | neg_control_auc |
|---|---:|---:|---:|---:|---:|---:|---:|
| LSTM ul | 0.855 ± 0.018 | 0.854 ± 0.022 | 0.337 ± 0.036 | 0.848 ± 0.005 | 0.813 ± 0.068 | 0.979 ± 0.018 | 0.505 ± 0.004 |
| GBDT rolling cross-domain UL | 0.932 ± 0.012 | 0.929 ± 0.014 | 0.496 ± 0.045 | 0.935 ± 0.010 | 0.864 ± 0.061 | 0.967 ± 0.019 | 0.534 ± 0.028 |
| GBDT rolling <=10 s cross-domain UL | 0.901 ± 0.003 | 0.898 ± 0.008 | 0.408 ± 0.048 | 0.907 ± 0.009 | 0.844 ± 0.070 | 0.956 ± 0.014 | 0.510 ± 0.017 |

## 6. Transfers (UL, gated)

clean-a / clean-b: leave-generator-out restricted to the generator cells (family × schedule × load) made by ≥2 dual-use tools (a: train and test inside them; b: train on everything except tool b, test on b's clean cells). Those cells hold only dns_flood on the attack side and udp_bidir / benign_benign on the benign side, so their AUC mixes pairs: read TPR / FPR.

| protocol | LSTM ROC | GBDT ROC | LSTM TPR | GBDT TPR | LSTM FPR | GBDT FPR |
|---|---:|---:|---:|---:|---:|---:|
| leave-UE-out ue1->ue2 | 0.753 | 0.911 | 0.149 | 0.423 | 0.001 | 0.026 |
| leave-UE-out ue2->ue1 | 0.785 | 0.870 | 0.138 | 0.370 | 0.004 | 0.060 |
| leave-generator-out pacer | 0.510 | 0.673 | 0.433 | 0.639 | 0.402 | 0.430 |
| leave-generator-out hping | 0.635 | 0.638 | 0.189 | 0.106 | 0.000 | 0.019 |
| leave-generator-out iperf | 0.587 | 0.793 | 0.004 | 0.199 | 0.000 | 0.004 |
| victim silent->responsive | 0.718 | 0.798 | 0.196 | 0.501 | 0.034 | 0.084 |
| victim responsive->silent | 0.912 | 0.941 | 0.334 | 0.367 | 0.000 | 0.001 |
| clean leave-generator-out pacer | 0.942 | 0.949 | 0.969 | 0.948 | 0.089 | 0.218 |
| clean leave-generator-out hping | 0.995 | 0.985 | 0.837 | 0.057 | 0.005 | 0.000 |
| clean leave-generator-out iperf | – | – | – | – | 0.206 | 0.000 |
| clean-b leave-generator-out pacer | 0.885 | 0.942 | 0.740 | 0.993 | 0.111 | 0.474 |
| clean-b leave-generator-out hping | 0.850 | 0.654 | 0.324 | 0.128 | 0.000 | 0.019 |
| clean-b leave-generator-out iperf | – | – | – | – | 0.000 | 0.004 |

## 7. Per-pair AUC (test)

| model | dns_flood~dns_heavy | fanout_udp~fanout_benign | icmp_flood~icmp_ping | mimicry_udp~udp_nofeedback | pulsing_udp~onoff_pareto | syn_flood~tcp_shortconn | udp_flood~udp_bidir |
|---|---:|---:|---:|---:|---:|---:|---:|
| LSTM ul (3 seeds) | 1.000 | 0.651 | 0.511 | 0.783 | 0.946 | 0.999 | 0.662 |
| GBDT rolling cross-domain UL | 1.000 | 0.904 | 0.495 | 0.873 | 0.974 | 1.000 | 0.867 |
| GBDT rolling <=10 s cross-domain UL | 1.000 | 0.862 | 0.488 | 0.848 | 0.947 | 1.000 | 0.784 |
| GBDT rolling URR+prof (UL) | 1.000 | 0.864 | 0.472 | 0.858 | 0.941 | 1.000 | 0.825 |

## 8. Appendix — with DL (not a result: designed DL feedback ≈ label)

LSTM all features: ROC 0.996, TPR 0.937, macro 0.974. GBDT rolling incl. DL: ROC 0.995, TPR 0.938.

## 9. Leak checks (summary)

- Indirect DL through RAN UL ratios: overall AUC 0.525 / 0.503 (`dl_leak_check_v4.md`).
- Previous phase: previous-phase label AUC 0.178 (inverted), but cutting the rolling history at the phase start does not lower any GBDT (`leak_phase_v4.md`).
- Negative control (icmp): ~0.5 for every model using URR/prof; RAN-UL GBDT 0.614 [0.512–0.719] (CI contains 0.5).

## 10. Conclusions

1. **Best detector: GBDT on rolling UL features from all three domains** — ROC-AUC 0.930 [0.894–0.961], PR-AUC
   0.924, TPR@FPR1% 0.467 [0.377–0.564], pair macro 0.936, gated idle FPR 0.004; stable over 3 run splits
   (0.932 ± 0.012). With the LSTM's 10 s history the same GBDT reaches 0.900 [0.853–0.938].
2. **The LSTM (2×64, 10 s, UL) is significantly worse than the GBDT with the same history**: ΔROC −0.067
   [−0.093, −0.041], ΔTPR −0.069 [−0.116, −0.017] (3-seed score mean: −0.048 [−0.070, −0.028]). It loses
   more from validation to test (−0.074 vs −0.029): it fits run-specific patterns that do not transfer to new
   runs. It is nearly order-blind (shuffling the 10 time steps costs 0.010 AUC) and fails on the CBR UDP pairs
   (udp_flood↔udp_bidir 0.66, fanout 0.65 vs 0.78–0.90 for GBDT); it matches GBDT on the protocol pairs and on
   pulsing. On this dataset the sequence model brings no benefit over explicit rolling statistics.
3. **Cross-domain fusion helps** (the two-layer premise): the cross-domain GBDT beats every single domain and the
   core-only URR+prof combination — paired CIs exclude 0 for ROC, TPR and macro (vs URR+prof: ΔROC +0.022
   [+0.005, +0.045]; vs RAN-UL +0.064, vs URR-UL +0.070, vs profiler-UL +0.057).
4. **History matters**: 30 s rolling > 10 s rolling (+0.030 [+0.014, +0.052]) > single second (0.790).
5. **The operating point is modest**: at benign FPR 1% only ~47% of attack windows are flagged; 65% of attack
   phases are detected within 20 s, none within 10 s (the 10 s window must fill with in-phase data), median TTD
   13 s; 12% of benign phases raise at least one alarm. Usable as a level-1 (reversible) trigger inside the
   escalation policy, not as a sole block decision.
6. **Generalisation**: transfers across UEs (0.87–0.91) and from responsive to silent victims (0.94); weaker
   from silent to responsive (0.80); poor to an unseen generator (0.64–0.79). In the clean test, where family,
   schedule and load are held and only the tool changes, the GBDT's operating point still breaks (pacer unseen:
   benign FPR 0.22–0.47; hping unseen: attack TPR 0.06–0.13), so tool identity, not only the schedule, drives
   part of the decision. Caveat: the clean cells contain only dns_flood on the attack side. The LSTM is better on
   the unseen-hping clean test (TPR 0.84 / 0.32) but worse on most other transfers.
7. **Leak checks pass**: indirect DL through RAN UL ratios 0.525 / 0.503; the previous-phase label is not
   exploited (cutting history at the phase start does not lower any GBDT); negative control ≈ 0.5 for every
   model using URR/prof (RAN-UL GBDT 0.614, CI [0.512–0.719] contains 0.5 — watch).
8. With DL the problem is trivial (ROC 0.995 for both models) because the testbed's benign DL is designed; this is
   reported only as an appendix.

**Open decision (author):** the thesis plan names an LSTM as classifier v2. On v4 the rolling-feature GBDT is
better, more robust across runs and cheaper to serve. Options: (a) adopt the GBDT as classifier v2 and report the
LSTM as a measured negative result; (b) keep the LSTM and try to close the gap (longer history, rolling-feature
inputs, regularisation, hyper-parameter search on validation runs only — never on test).

## Mini-simulations (added with stage B, offline, test runs, models frozen)

Each GBDT alone, activity-gated alarm z ≥ 1, phase level (icmp control excluded); brackets = 95% bootstrap CI by run (`scripts/ml/mini_sim_v4.py`).

### k-of-n alarm rule (honest telemetry)

| model | rule | attack phases detected | median t (s) | benign phases with an alarm |
|---|---|---:|---:|---:|
| xd | 1 of 1 | 0.798 [0.723, 0.868] | 13.2 | 0.117 [0.058, 0.189] |
| xd | 2 of 3 | 0.764 [0.685, 0.847] | 14.3 | 0.087 [0.03, 0.161] |
| xd | 3 of 5 | 0.697 [0.6, 0.805] | 15.2 | 0.039 [0.009, 0.084] |
| xd | 4 of 5 | 0.663 [0.571, 0.769] | 16.3 | 0.039 [0.009, 0.084] |
| xd | 5 of 5 | 0.64 [0.547, 0.75] | 17.3 | 0.029 [0.009, 0.062] |
| core | 1 of 1 | 0.742 [0.651, 0.839] | 14.2 | 0.058 [0.01, 0.119] |
| core | 2 of 3 | 0.719 [0.62, 0.825] | 16.3 | 0.029 [0.0, 0.081] |
| core | 3 of 5 | 0.652 [0.558, 0.758] | 17.5 | 0.019 [0.0, 0.05] |
| core | 4 of 5 | 0.629 [0.532, 0.741] | 18.1 | 0.019 [0.0, 0.05] |
| core | 5 of 5 | 0.562 [0.461, 0.674] | 18.0 | 0.01 [0.0, 0.032] |
| ran | 1 of 1 | 0.708 [0.607, 0.813] | 13.6 | 0.155 [0.096, 0.206] |
| ran | 2 of 3 | 0.652 [0.539, 0.775] | 15.0 | 0.087 [0.041, 0.131] |
| ran | 3 of 5 | 0.607 [0.481, 0.742] | 16.0 | 0.049 [0.01, 0.086] |
| ran | 4 of 5 | 0.517 [0.402, 0.652] | 16.5 | 0.019 [0.0, 0.05] |
| ran | 5 of 5 | 0.461 [0.347, 0.588] | 19.2 | 0.019 [0.0, 0.05] |

### KPM tamper per model (3 of 5)

hide ×f: attacker's KPM UL deflated (detection on the tampered attack phases); frame ×f: a benign UE's KPM UL inflated (alarm on the framed benign phases).

| scenario | model | attack detected | benign (framed) alarm |
|---|---|---:|---:|
| honest | xd | 0.697 [0.6, 0.805] | 0.039 [0.009, 0.084] |
| honest | core | 0.652 [0.558, 0.758] | 0.019 [0.0, 0.05] |
| honest | ran | 0.607 [0.481, 0.742] | 0.049 [0.01, 0.086] |
| kpm_hide x0.1 | xd | 0.798 [0.658, 0.919] | 0.039 [0.009, 0.084] |
| kpm_hide x0.1 | core | 0.652 [0.558, 0.758] | 0.019 [0.0, 0.05] |
| kpm_hide x0.1 | ran | 0.0 [0.0, 0.0] | 0.049 [0.01, 0.086] |
| kpm_hide x0.33 | xd | 0.921 [0.878, 0.963] | 0.039 [0.009, 0.084] |
| kpm_hide x0.33 | core | 0.652 [0.558, 0.758] | 0.019 [0.0, 0.05] |
| kpm_hide x0.33 | ran | 0.0 [0.0, 0.0] | 0.049 [0.01, 0.086] |
| kpm_hide x0.5 | xd | 0.899 [0.808, 0.971] | 0.039 [0.009, 0.084] |
| kpm_hide x0.5 | core | 0.652 [0.558, 0.758] | 0.019 [0.0, 0.05] |
| kpm_hide x0.5 | ran | 0.056 [0.0, 0.117] | 0.049 [0.01, 0.086] |
| kpm_frame x2 | xd | 0.708 [0.608, 0.816] | 0.476 [0.381, 0.57] |
| kpm_frame x2 | core | 0.652 [0.558, 0.758] | 0.019 [0.0, 0.05] |
| kpm_frame x2 | ran | 0.618 [0.487, 0.763] | 0.767 [0.663, 0.855] |
| kpm_frame x5 | xd | 0.719 [0.62, 0.824] | 0.66 [0.574, 0.747] |
| kpm_frame x5 | core | 0.652 [0.558, 0.758] | 0.019 [0.0, 0.05] |
| kpm_frame x5 | ran | 0.618 [0.487, 0.763] | 1.0 [1.0, 1.0] |
