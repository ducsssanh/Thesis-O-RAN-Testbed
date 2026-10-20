# ML preprocessing

Turns the public NCSRD-DS-5GDDoS dataset (in `data/`, git-ignored) into
per-UE time-series windows for the LSTM described in
`docs/AI-DEFENSE-MODEL-DESIGN.md`.

## Setup

```
python3 -m venv .venv-ml
.venv-ml/bin/pip install -r scripts/ml/requirements.txt
```

`.venv-ml/` is git-ignored. Run the dataset scripts with `-I` (the dataset is
untrusted input): `.venv-ml/bin/python -I scripts/ml/prep_ncsrd.py ...`.

## NCSRD preprocessing

```
.venv-ml/bin/python -I scripts/ml/prep_ncsrd.py \
    --merged data/NCSRD_5GDDOS_V3/amari_ue_data_merged_with_attack_number.csv \
    --out artifacts/ml/ncsrd --window 6 --val-attack 4
```

Writes `artifacts/ml/ncsrd/windows.npz` (git-ignored, ~28 MB; regenerate) and
`meta.json`. Key points, all verified on the current data:

- **Labels are rebuilt from the attack schedule**, not the dataset's `attack`
  / `malicious` columns, which mark idle malicious devices and benign UEs as
  positive. A window is positive only when its device actually attacked in that
  attack (`ATTACKERS` in the script). Verified: benign 0 positives; SYN / ICMP /
  UDP-frag / DNS positive only for 10.20.10.2 and .4; GTP-U positive for all
  five malicious devices.
- **Two volume sources per UE**, like the testbed's KPM and URR: `ran_*_kbps`
  (from `ul/dl_bitrate`) and `core_*_kbps` (bearer byte counters differenced
  over the ~5 s period). `resid_ul/dl` is their relative difference — the
  NCSRD analogue of the KPM↔URR residual.
- **16 features** (`FEATURES` in the script): the two rates per direction, the
  cell uplink rate, the two residuals, the UE's cell uplink share, and radio
  metrics (MCS, retx, err, CQI, PUSCH SNR). Rates are `log1p`'d; the scaler is
  fit on the training split only.
- **Windows**: 6 steps (~30 s), stride 1, never crossing a session gap (> 15 s).
- **Split**: leave-one-attack-out — `--val-attack k` holds out one attack for
  validation, plus a time-tail slice of benign windows. Run once per attack
  (1..5) for a full leave-one-attack-out evaluation.
- **Rank**: the LSTM predicts `p_attack`; the rank is
  `p_attack × ue_cell_ul_share`, saved per window (`share_*`), formed at
  inference, not a training target.
- **No per-UE packet-mix features** exist in NCSRD; they are added only when
  fine-tuning on testbed data.

Current run: 684,798 windows, 16 features, 1.67 % positive; held out DNS →
549,512 train / 135,286 val.

## Training the LSTM

```
.venv-ml/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-ml/bin/python -I scripts/ml/train_lstm.py --data artifacts/ml/ncsrd/windows.npz --out artifacts/ml/ncsrd
```

Small LSTM (1–2 layers, 64 units) over the 6-step window, one head `p_attack`.
Positive class weight = #neg/#pos handles the 1.7 % imbalance; metrics are
PR-AUC (average precision) and per-attack recall, not accuracy. Pure CPU, a few
minutes. Writes `model.pt` (weights + scaler) and `metrics.json`. The rank
(`p_attack × observed cell uplink share`) is computed and reported, not
learned; the volume-forecast head of the design is deferred (needs a forecast
target in preprocessing).

### Results so far (18/10, NCSRD)

- **Leave-one-attack-out** (hold out DNS, `--val-attack 4`): ROC-AUC 0.89,
  PR-AUC 0.12, benign false-positive rate 14 % at threshold 0.5, DNS recall
  0.54; **rank precision-at-positives 0.97** (the rank puts attackers on top
  because they take a large share of the cell). The low PR-AUC is honest: the
  model is judged on an attack type it never saw in training — the hard,
  convincing test.
- **Time split** (`--val-attack 0`, attacks seen in training): PR-AUC 0.62,
  benign false-positive rate 0.02 %. Shows the model learns well in
  distribution. (GTP-U recall 0 here because it is the last attack
  chronologically, so an 80 % time cut leaves none of it in training —
  a split artifact, not a model fault.)

For a full leave-one-attack-out evaluation, re-run prep + train for each
`--val-attack` in 1..5 and average. These numbers are a pretraining baseline on
public data; the thesis result is on testbed data after fine-tuning.
