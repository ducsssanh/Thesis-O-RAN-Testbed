# Dataset scripts

Setup: `python3 -m venv .venv-ml && .venv-ml/bin/pip install -r scripts/ml/requirements.txt`; run with
`.venv-ml/bin/python -I` (raw data is untrusted input). The ML training / evaluation scripts were removed on
2026-10-27 (direction changed to DRL, `research/DRL-DIRECTION.md`; they remain in git history).

| script | role |
|---|---|
| `build_dataset_v4.py` (+ `test_build_dataset_v4.py`) | causal as-of build of the v4 rows (1 s × 1 UE) from raw runs |
| `qa_v4.py` | dataset QA (balance, causality, nuisance baseline, stop-gates) |
| `package_v4.py` | packaging: selected attempts, raw copy, runs index |
| `build_oran_dataset.py` | builder of the older datasets v1–v3 |
