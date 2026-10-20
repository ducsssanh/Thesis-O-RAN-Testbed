# Phase L — temporal LSTM baseline (dataset v3)

Window = 8s, label = last step. GroupKFold(5) by (campaign, run, supi); scaler fit on train only. CPU. Metrics = mean±std.

Challenge subset = windows whose last step has thp_ul_kbps in [300,1000) kbps.

| feature set | split | F1 | AUC | recall | precision | bal_acc |
|---|---|---|---|---|---|---|
| full | full-test | 0.992±0.001 | 1.000±0.000 | 0.992±0.003 | 0.992±0.003 | 0.995±0.001 |
| full | challenge | 0.998±0.001 | 1.000±0.000 | 0.999±0.001 | 0.998±0.001 | 0.999±0.001 |
| bytes-only | full-test | 0.975±0.007 | 0.999±0.000 | 0.984±0.004 | 0.965±0.009 | 0.986±0.003 |
| bytes-only | challenge | 0.984±0.004 | 1.000±0.000 | 0.999±0.001 | 0.970±0.007 | 0.991±0.002 |
