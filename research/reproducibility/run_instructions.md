# Reproducibility — Phase I audit

Environment: `.venv-ml` (numpy 2.5.4, scikit-learn 1.9.1, torch 2.14.1+cpu,
pandas). Untrusted dataset under `data/` — always run with `-I`.

## Reproduce the verified baseline numbers
```bash
cd /home/ducsssanh/6G/O-RAN/DATN/Codebase
.venv-ml/bin/python -I research/audits/scripts/verify_baseline.py   # metric table + thresholds
.venv-ml/bin/python -I research/audits/scripts/leakage.py           # UE/window leakage
.venv-ml/bin/python -I research/audits/scripts/share_ablation.py    # detection vs ranking ablation
```
These read the committed-small artifacts' `val_scores.npz` / `windows.npz` under
`artifacts/ml/{ncsrd,ncsrd-timesplit}/` (the `windows.npz` files are git-ignored;
regenerate with the prep command below if missing).

## Regenerate the processed datasets
```bash
# DNS held-out (leave-one-attack-out)
.venv-ml/bin/python -I scripts/ml/prep_ncsrd.py \
    --merged data/NCSRD_5GDDOS_V3/amari_ue_data_merged_with_attack_number.csv \
    --out artifacts/ml/ncsrd --val-attack 4
# time split
.venv-ml/bin/python -I scripts/ml/prep_ncsrd.py \
    --merged data/NCSRD_5GDDOS_V3/amari_ue_data_merged_with_attack_number.csv \
    --out artifacts/ml/ncsrd-timesplit --val-attack 0
```

## Retrain the baseline LSTM
```bash
.venv-ml/bin/python -I scripts/ml/train_lstm.py \
    --data artifacts/ml/ncsrd/windows.npz --out artifacts/ml/ncsrd
```

## Known limitations of this split (do not over-claim)
See `research/audits/data_leakage_report.md`. The current splits leak via shared
UEs and overlapping windows; treat the numbers as an optimistic baseline, not a
generalisation result. The next iteration replaces the split with a group/
gap-guarded one before any new modelling claims.
