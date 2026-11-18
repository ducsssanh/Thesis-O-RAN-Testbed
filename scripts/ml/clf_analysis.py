#!/usr/bin/env python3
"""Feature analysis before training (Kế hoạch huấn luyện classifier, step 1): per-feature AUC of attack seconds against
benign seconds, on all seconds and on active seconds at a heavy-user rate (UL at least 50 kbit/s), by evasion level;
correlation between the 15 chosen features. Honest scenario, L3 phases left out except where named. No model, no split.
Usage: clf_analysis.py <episodes31.pkl> <out.txt>"""
import pickle, sys
import numpy as np
from sklearn.metrics import roc_auc_score
sys.argv += [] ; D = pickle.load(open(sys.argv[1], "rb")); E = D["episodes"]
N = D["names"]
PROTO = list(range(12, 19)) + list(range(20, 25))


def f15(raw):
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))
    return np.c_[raw[:, [6, 7, 8, 9, 2, 3]], prbk, raw[:, [10, 11]], raw[:, 7] - raw[:, 6], raw[:, [30, 26, 27, 28, 29]]]


NAMES15 = ["core_ul_kbps", "core_dl_kbps", "core_ul_pps", "core_dl_pps", "prb_ul", "prb_dl", "prb_ul_per_kbit", "size_ul", "size_dl",
           "dl_over_ul", "c_t_w", "trust_ue", "mask_ue", "kpm_age", "prof_age"]
out = open(sys.argv[2], "w")
say = lambda *x: (print(*x), print(*x, file=out))
rows = []
for e in E:
    raw = e["scen"]["honest"]; x = np.c_[f15(raw), raw[:, [0, 1, 4, 5] + PROTO + [19]]]
    for t in range(len(raw)):
        rows.append((x[t], int(e["run_lab"][t]), e["evasion"] if e["attack"] else "", e["other_evasion"], e["client"], e["band"]))
X = np.array([r[0] for r in rows]); y = np.array([r[1] for r in rows]); ev = np.array([r[2] for r in rows]); oth = np.array([r[3] for r in rows])
cl = np.array([r[4] for r in rows])
names = NAMES15 + ["kpm_rate_ul", "kpm_rate_dl", "cell_prb_ul", "cell_prb_dl"] + [N[i] for i in PROTO] + ["dst_ul"]
active = np.expm1(X[:, 0]) >= 50
base = oth != "L3"


def auc(m, j):
    yy = y[m]
    if yy.min() == yy.max():
        return np.nan
    a = roc_auc_score(yy, X[m, j]); return max(a, 1 - a)


say("seconds", len(y), "attack seconds", int(y.sum()), "active at >= 50 kbit/s", int(active.sum()))
say("AUC of one feature, attack against benign seconds (direction-free, 0.5 = no separation). Benign = benign UEs and attack UEs before onset.")
say("%-22s %6s %6s | active >= 50 kbit/s: %6s %6s %6s | L3 phase vs benign client %6s" % ("feature", "all", "", "L1", "L2", "all", "active"))
for j, n in enumerate(names):
    m_all = base
    m_act = base & active
    m1 = m_act & ((ev == "L1") | (y == 0)); m2 = m_act & ((ev == "L2") | (y == 0))
    m3 = (oth == "L3") & active & ((ev == "L3") | cl)
    tag = "  (in f15)" if j < 15 else ""
    say("%-22s %6.3f %6s | %26.3f %6.3f %6.3f | %6.3f%s" % (n, auc(m_all, j), "", auc(m1, j), auc(m2, j), auc(m_act, j), auc(m3, j), tag))
C = np.corrcoef(X[base][:, :15].T)
say("\nPairs among the 15 features with |correlation| >= 0.8:")
for i in range(15):
    for j in range(i + 1, 15):
        if abs(C[i, j]) >= .8:
            say("  %-18s %-18s %.2f" % (NAMES15[i], NAMES15[j], C[i, j]))
