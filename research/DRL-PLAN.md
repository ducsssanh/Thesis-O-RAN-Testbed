# DRL plan (step 8)

The design is "DRL design for the defence xApp (A to Z)". It stays the single source: this plan adds no item, only the order of work and what the twin campaign changes. The DRL is a component with a modest claim, not a contribution of the thesis. Nothing here has been run.

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
- **Trust scope.** The design's gate input is the trust of the gNB. Pooled trust masks the honest UE too and dilutes with many UEs (TRAFFIC-TWINNING-PLAN 9); on replay, per-UE trust keeps the honest UE masked at 0.4 % against about 97 %. The dataset has both (`kpm_trust`, `kpm_trust_ue`). Decide before step 1; changing it means a patch of the xApp for step 6.
- **Tamper cue.** See `research/twinning/out_tamper_cue.txt`. If a KPM-only classifier separates tampered seconds, ablations B and C must be read with that limit.
- **Training mode.** Offline on replay; online inference only. The attacker does not react to an alarm in these data, which limits the claim.
- **Correction to make.** `research/DRL-DIRECTION.md:133`, the "waiting for core 1.5-2.8 s" argument: on the campaign data the profile reaches the xApp within about 0.1 s (q99 of `prof_age_s`).
