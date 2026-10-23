# Leak check through the previous phase (v4)

## 1. Run structure

- Phases whose previous pNN phase in the same run is their UE-mirror (same pair, attacker swapped): **212 / 440 = 48.2%**.
- Previous-phase label of the same UE as a predictor of the current label (main windows, control excluded, n = 34538): **AUC 0.178** (agreement 0.181; 0.5 = no information).

## 2. Rolling history crossing the phase start (main windows)

| history | share of main windows whose history starts before the phase start |
|---|---:|
| 5 s | 0.000 |
| 10 s | 0.000 |
| 30 s | 0.386 |

Main windows end ≥ 12 s into a phase (3 s guard + 10 s window), so the 5/10 s statistics never cross; only the 30 s statistics do.

## 3. GBDT rolling: normal history vs history cut at the phase start

Same split, val threshold (benign FPR 1%), gate and v4_eval. A drop when the history is cut = the model used pre-phase seconds. (A deployed xApp does not know phase boundaries; the cut is a diagnostic.)

| model | ROC-AUC | PR-AUC | TPR@FPR1% (ungated) | FPR | pair macro AUC | mimicry | pulsing | icmp control | idle FPR (ungated) | attack phases detected ≤10 s / ≤20 s | TTD median s | benign phases alarmed (ungated) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GBDT rolling cross-domain UL — normal | 0.9298 | 0.9238 | 0.4674 (0.4674) | 0.0164 | 0.9362 | 0.8728 | 0.9744 | 0.4954 | 0.0035 (0.2038) | 0.0 / 0.6517 | 13.2 | 0.1165 (0.2039) |
| GBDT rolling cross-domain UL — cut at phase start | 0.9373 | 0.9287 | 0.4993 (0.4993) | 0.0188 | 0.9372 | 0.8712 | 0.9741 | 0.5461 | 0.0 (0.0066) | 0.0787 / 0.6404 | 12.5 | 0.1262 (0.1942) |
| GBDT rolling <=10 s cross-domain UL — normal | 0.8996 | 0.8961 | 0.3939 (0.3939) | 0.0111 | 0.9068 | 0.8477 | 0.9467 | 0.4882 | 0.0007 (0.0014) | 0.0225 / 0.5955 | 12.6 | 0.1068 (0.1068) |
| GBDT rolling <=10 s cross-domain UL — cut at phase start | 0.894 | 0.8901 | 0.3687 (0.3687) | 0.0123 | 0.9065 | 0.8483 | 0.9546 | 0.4932 | 0.0 (0.0) | 0.0112 / 0.573 | 12.9 | 0.1359 (0.1942) |
| GBDT rolling URR+prof (UL) — normal | 0.9076 | 0.9096 | 0.4274 (0.4274) | 0.0055 | 0.9144 | 0.8577 | 0.9405 | 0.4725 | 0.0 (0.0066) | 0.1011 / 0.5955 | 14.2 | 0.0583 (0.0583) |
| GBDT rolling URR+prof (UL) — cut at phase start | 0.9086 | 0.9069 | 0.3585 (0.3585) | 0.0019 | 0.9 | 0.8382 | 0.9226 | 0.5169 | 0.0 (0.0021) | 0.2022 / 0.4607 | 13.2 | 0.0485 (0.0583) |
| GBDT rolling RAN-UL — normal | 0.8654 | 0.8612 | 0.3241 (0.3241) | 0.0104 | 0.8836 | 0.8769 | 0.9543 | 0.6142 | 0.0358 (0.121) | 0.0 / 0.5506 | 13.6 | 0.1553 (0.2039) |
| GBDT rolling RAN-UL — cut at phase start | 0.8969 | 0.888 | 0.3396 (0.3396) | 0.0125 | 0.8983 | 0.8451 | 0.9682 | 0.6695 | 0.0007 (0.0017) | 0.0 / 0.5843 | 12.4 | 0.1165 (0.1262) |
| GBDT rolling URR-UL — normal | 0.86 | 0.852 | 0.206 (0.206) | 0.0075 | 0.8555 | 0.8348 | 0.804 | 0.534 | 0.0003 (0.0014) | 0.0112 / 0.2584 | 19.8 | 0.0388 (0.0388) |
| GBDT rolling URR-UL — cut at phase start | 0.8661 | 0.8594 | 0.1982 (0.1982) | 0.0039 | 0.8498 | 0.7942 | 0.7875 | 0.5167 | 0.0 (0.0) | 0.0562 / 0.2584 | 14.1 | 0.0291 (0.0291) |
| GBDT rolling prof-UL — normal | 0.8732 | 0.8715 | 0.3682 (0.3682) | 0.0089 | 0.8701 | 0.8199 | 0.9077 | 0.4461 | 0.0 (0.0) | 0.1124 / 0.4607 | 14.8 | 0.0874 (0.0874) |
| GBDT rolling prof-UL — cut at phase start | 0.8784 | 0.8754 | 0.3396 (0.3396) | 0.006 | 0.8684 | 0.822 | 0.9196 | 0.5216 | 0.0 (0.0042) | 0.1461 / 0.3933 | 13.6 | 0.0583 (0.0583) |
| UL volume (kbps, rolling) — normal | 0.8634 | 0.8524 | 0.2944 (0.2944) | 0.0197 | 0.8745 | 0.8561 | 0.9412 | 0.4927 | 0.0 (0.0007) | 0.0 / 0.5618 | 15.0 | 0.1262 (0.1262) |
| UL volume (kbps, rolling) — cut at phase start | 0.899 | 0.8862 | 0.3033 (0.3033) | 0.0164 | 0.8933 | 0.8723 | 0.9268 | 0.5134 | 0.0 (0.0) | 0.0 / 0.4944 | 14.3 | 0.0971 (0.0971) |
