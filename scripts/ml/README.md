# ML and analysis scripts

Setup: `python3 -m venv .venv-ml && .venv-ml/bin/pip install -r scripts/ml/requirements.txt`; run with
`.venv-ml/bin/python -I` (datasets are untrusted input). Overview of the whole pipeline:
`research/CROSS-DOMAIN-DEFENCE.md` §14.

## Current pipeline
| stage | scripts |
|---|---|
| v4 dataset (testbed, defence off) | `build_dataset_v4.py` (+ `test_build_dataset_v4.py`), `qa_v4.py`, `package_v4.py`, `baseline_v4.py` |
| v4 features, training, evaluation | `prep_v4_windows.py`, `v4_eval.py`, `train_lstm_v4.py`, `report_model_eval_v4.py`, `mini_sim_v4.py`, `dl_leak_check_v4.py`, `leak_phase_v4.py` |
| defence engine (shared offline / live) | `defence_engine_v4.py`; offline replay `fusion_v4.py`; sidecar parity `sidecar_parity_v4.py` |
| v5 live evaluation | `live_eval_v5.py` → `carryover_v5.py` → `loop_latency_v5.py` → `live_extra_v5.py` → `figures_v5.py` |

## Legacy (NCSRD / dataset v1–v3; reports in `research/archive/`)
`prep_ncsrd.py`, `prep_ncsrd_v2.py`, `prep_ncsrd_v3.py`, `train_lstm.py`, `experiments.py`, `feature_ablation.py`,
`analysis.py`, `build_oran_dataset.py`, `eval_oran_models.py`, `eval_oran_lstm.py`, `eval_oran_challenge.py`.
