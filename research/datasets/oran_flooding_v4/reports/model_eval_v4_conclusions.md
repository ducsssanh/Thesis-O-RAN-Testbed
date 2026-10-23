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
