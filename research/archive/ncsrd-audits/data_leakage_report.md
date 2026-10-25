# Data Leakage & Dataset-Integrity Report (Phase I)

Date: 2026-10-19. Evidence from `research/archive/ncsrd-audits/scripts/leakage.py` on
`artifacts/ml/ncsrd/windows.npz`, plus inspection of `scripts/ml/prep_ncsrd.py`
and the raw CSVs under `data/NCSRD_5GDDOS_V3/`.

## Findings, ranked by severity

### 1. UE-identity leakage — SEVERE
The whole dataset has **only 9 distinct UEs** (`imeisv`), and **all 9 appear in
both train and val**. The model can memorise each UE's baseline rather than learn
transferable behaviour. The benign class is the *same devices* on both sides of
every split. This inflates benign-vs-benign discrimination and hence ROC-AUC
(0.89) and FPR.

*Fix:* group-based splitting. For benign, hold out whole UEs (leave-one-UE-out)
in addition to leave-one-attack-out. Report both.

### 2. Overlapping-window leakage across the benign boundary — SEVERE
Windows are built with **stride 1** (adjacent windows share 5 of 6 rows). The
benign split is by a time quantile, which does not stop adjacent overlapping
windows from straddling the cut. Measured: **98,556 / 135,286 (73%)** of
validation windows have a same-UE training window within 26 s (≤ one window
span). Train and val benign windows are effectively contiguous slices of the same
device timelines.

*Fix:* split by independent **segment/run**, not by per-row time; or insert a
guard gap of ≥ W steps between train and val on each timeline; build windows
**after** assigning segments to partitions.

### 3. Tiny effective sample size — SEVERE (Concern D)
Positive *windows* (11,456) massively overstate independence:
- Attacks 1–4 (SYN/ICMP/UDP-frag/DNS): **2 attacker devices** each.
- Attack 5 (GTP-U): 5 devices.
- **5 attack types total**, a handful of attack episodes, expanded to thousands
  of windows purely by stride-1 overlap.

So the real quantity is ~5 attack scenarios × a few devices, not 11k samples. Any
"generalisation" claim must be framed against this. Report effective counts
(distinct episodes), not window counts.

### 4. Label-source leakage — AVOIDED (good), worth stating
The raw CSV ships `attack`, `malicious`, `attack_number` (cols 56–58). `attack`
is on for every UE during an attack window; `malicious` is a static per-device
flag. Using them directly would leak the label onto idle attacker devices and
co-present benign UEs. `prep_ncsrd.py` correctly **rebuilds labels** from the
schedule (`attack_number` × the device set that actually attacked). Keep this;
never feed `attack`/`malicious` as features.

### 5. Scaler fit — CORRECT
z-score mean/std are fit on the **train split only** (`prep_ncsrd.py` lines
~187–191) and applied to val. No scaler leakage.

### 6. Residual feature construction — LOW risk, one caveat
`resid_ul/dl = (ran − core)/(core+1)` mixes RAN rate and differenced bearer-byte
counters. Counter resets are clamped to 0 and segment breaks zeroed — fine. The
`+1` denominator is in kbit/s units, so residual scale is traffic-dependent;
acceptable but document it.

### 7. Not yet checked (open items)
- NaN/inf and constant/near-constant feature audit across the full matrix.
- Pairwise feature correlation / redundancy.
- Distribution shift train vs val per feature.
- Transition-boundary mislabelling (first/last window of each attack episode).

These are queued for the next iteration (`dataset_statistics.json` to be produced).

## Bottom line
The two headline splits both leak through shared UEs and overlapping windows, and
rest on very few independent attack episodes. Results are usable as a *starting
baseline* but **not** as evidence of generalisation. The redesign must introduce
group-based, gap-guarded splits and report effective episode counts.
