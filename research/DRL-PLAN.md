# DRL plan (step 8)

The design is "DRL design for the defence xApp (A to Z)". It stays the single source: this plan adds no item, only the order of work and what the twin campaign changes. The DRL is a component with a modest claim, not a contribution of the thesis. First results: `research/drl/out_r0_report.txt` (2026-11-05: 5 folds, 1 seed, 3 C_FA, no history feature, no confidence interval yet). Code: `scripts/drl/`.

## Input
`research/datasets/oran_flooding_twin/rows.parquet` (`scripts/ml/build_dataset_twin.py`), 72 runs. A row of second t holds the traffic of [t-1, t), and `t_window`, `onset_t`, `attack_*` are labels, never inputs. Tampering is injected on replay by `scripts/ml/tamper_replay.py`, then `gate()` is called again.

## Order of work
1. **Environment**: per episode, 10 s of the 30 features of design 3.2, reward of 3.4, the episode rule of 3.1. Test: same run and seed give the same episode; alarm ends it; no label in the observation.
2. **Baselines first**, design 3.2 and 7: xApp rules, classifier + threshold with temperature scaling, CUSUM on prior-corrected log-odds, always-use-core, oracle. If the classifier + threshold already reaches the oracle, report that.
3. **One small training** of Double DQN on a part of the folds, to check that it learns and how many episodes it needs (design 5.4, 5.5). This decides whether 72 runs are enough, which is not yet known. More runs come from the same manifest with a new seed.
4. **Full training**: GroupKFold by run, 5 folds, L1 + L2 for training, L3 only in test, 3 seeds, about 225 trainings on CPU. Never during a testbed run.
5. **Ablations A-D and evaluation**, design 6 and 7, false alarms re-weighted to the Madrid band frequencies.
6. **Deployment**, design 5.6: ONNX in the sidecar behind `/classify`, 200 ms fallback to the rules; live check on a few runs, separate from the evaluation.

## Questions the campaign leaves for this plan
- **Trust scope: decided, per UE** (user, 2026-11-04). The xApp runs it live; the environment reads `kpm_trust_ue` and `kpm_masked_ue`, not the node columns.
- **Tamper cue.** See `research/twinning/out_tamper_cue.txt`. If a KPM-only classifier separates tampered seconds, ablations B and C must be read with that limit.
- **Training mode.** Offline on replay; online inference only. The attacker does not react to an alarm in these data, which limits the claim.
- **Correction to make.** `research/DRL-DIRECTION.md:133`, the "waiting for core 1.5-2.8 s" argument: on the campaign data the profile reaches the xApp within about 0.1 s (q99 of `prof_age_s`).

## First run (r0), what it showed
- At about 1.9 false alarms per benign UE-hour, DQN with C_FA 50 against the calibrated classifier: L1 detected 135 and 143 of 144, L2 123 and 116, L3 125 and 143. The DQN is faster on L2 (median 2.2 s against 5.7 s, 16.8 % against 31.4 % of attack bytes first) and worse on L1 and L3. One seed, so not yet a finding.
- The same TCP or DNS client as a benign hard negative raises an alarm in 120-142 of 144 episodes, in both methods: L3 phases are out of training, and benign traffic in training is all UDP. This is the main weakness.
- Tamper scenarios are easier than honest ones, partly by construction: hiding is only applied to attackers and framing only to benign UEs, so the sign of c_t tells the label. To fix before reading any tamper result.
- Choice made for this run: from the onset to the end of the episode an alarm is a true alarm, including in the silent seconds of L2.

## Second round (r2), 2026-11-05: full-replay training, tamper on every UE from a start independent of the label
Five folds, 3 seeds, test folds only (`research/drl/out_r2*_cost.txt`, `out_r2*_report.txt`); configuration chosen on inner splits of 2 folds (`out_tuning_inner.txt`). Policy = a small DQN stopping on a calibrated classifier's logits, the best learned option found. Against the classifier at the operating point picked on the inner split, return difference (policy - classifier, 95 % CI over runs, without L3 phases): C_FA 10 -0.03 [-0.17, +0.13]; C_FA 50 -0.52 [-0.93, -0.13]; C_FA 200 -1.38 [-3.33, +0.45]. With usage history -0.16, -0.53, -2.87 [-4.26, -1.61]. The DRL does not beat the classifier. The usage history improves both methods (classifier at C_FA 50: -4.46 to -4.21; honest L2 -7.31 to -6.59), no CI computed. Without protocol features the classifier moves from -4.46 to -4.59, and the benign L3 client is still alarmed in 425-432 of 432 episodes, so protocol was not the only cause: it sends a steady stream of small packets, which training never saw as benign. xApp rules: no detection at these rates, in line with their 2 Mbit/s limit. Test folds of this round have been read: any further tuning needs inner splits and a new test, stated when reported.

