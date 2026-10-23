"""Shared v4 evaluation (baselines and LSTM report the SAME metrics; also shipped to Kaggle).

Threshold: chosen on the VALIDATION main windows so that the BENIGN false-positive rate is
`fpr_target` (default 1%), then frozen and applied to test. Headline = test main windows.
Breakdowns: per meta_pair, victim_mode, dual-use backend, UE, attack_active; idle false
alarms; time-to-detect (TTD) per attack phase from main+edge windows (seconds since the phase
start of the first window whose score crosses the threshold) and the share of benign phases
that raise any alarm.
"""
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

MAIN, EDGE, IDLE = 0, 1, 2
DUAL_USE = ("pacer", "hping", "iperf")


def _auc(y, p):
    if len(y) == 0 or y.min() == y.max():
        return None
    return round(float(roc_auc_score(y, p)), 4)


def _ap(y, p):
    if len(y) == 0 or y.min() == y.max():
        return None
    return round(float(average_precision_score(y, p)), 4)


def _rate(mask):
    return round(float(mask.mean()), 4) if mask.size else None


def threshold_at_fpr(p, y, fpr_target=0.01):
    """Smallest threshold whose BENIGN false-positive rate is <= fpr_target."""
    neg = np.sort(p[y == 0])
    if not len(neg):
        return 0.5
    k = int(np.floor((1 - fpr_target) * len(neg)))
    return float(neg[min(k, len(neg) - 1)]) + 1e-9


def report(p, d, split, thr):
    """Metrics for one split. p = scores for ALL windows; d = the windows_v4.npz arrays."""
    s = d["split"] == split
    y, kind = d["y"], d["kind"]
    mm = s & (kind == MAIN)
    pred = p >= thr
    r = {"threshold": round(float(thr), 6), "n_main": int(mm.sum()), "pos_main": int(y[mm].sum())}
    r["main"] = {"roc_auc": _auc(y[mm], p[mm]), "pr_auc": _ap(y[mm], p[mm]),
                 "tpr": _rate(pred[mm & (y == 1)]), "fpr": _rate(pred[mm & (y == 0)])}
    pr = {}
    for pair in sorted(set(d["pair"][mm])):
        q = mm & (d["pair"] == pair)
        pr[pair] = {"auc": _auc(y[q], p[q]), "tpr": _rate(pred[q & (y == 1)]),
                    "fpr": _rate(pred[q & (y == 0)]), "n": int(q.sum())}
    r["per_pair"] = pr
    r["per_victim_mode"] = {v: {"tpr": _rate(pred[mm & (d["victim"] == v) & (y == 1)]),
                                "fpr": _rate(pred[mm & (d["victim"] == v) & (y == 0)])}
                            for v in sorted(set(d["victim"][mm])) if v}
    r["per_dual_use_backend_auc"] = {b: _auc(y[mm & (d["backend"] == b)], p[mm & (d["backend"] == b)])
                                     for b in DUAL_USE}
    r["per_ue_auc"] = {u: _auc(y[mm & (d["ue"] == u)], p[mm & (d["ue"] == u)]) for u in sorted(set(d["ue"][mm]))}
    aa = d["attack_active"]
    r["tpr_by_attack_active"] = {"on": _rate(pred[mm & (y == 1) & (aa == 1)]),
                                 "off": _rate(pred[mm & (y == 1) & (aa == 0)])}
    ii = s & (kind == IDLE)
    r["idle_fpr"] = _rate(pred[ii])
    # time-to-detect / phase false alarms over main+edge windows (all windows ending in the phase)
    pe = s & (kind != IDLE)
    key = np.char.add(np.char.add(d["run"][pe].astype(str), "|"), np.char.add(np.char.add(d["ue"][pe].astype(str), "|"),
                                                                              d["phase"][pe].astype(str)))
    ts, yy, hit = d["t_since"][pe], y[pe], pred[pe]
    ttd, missed, ben_alarm, ben_n = [], 0, 0, 0
    for k in np.unique(key):
        q = key == k
        o = np.argsort(ts[q])
        h, t = hit[q][o], ts[q][o]
        if yy[q][0] == 1:
            if h.any():
                ttd.append(float(t[np.argmax(h)]))
            else:
                missed += 1
        else:
            ben_n += 1
            ben_alarm += int(h.any())
    ttd = np.array(ttd)
    r["time_to_detect_s"] = {"attack_phases": int(len(ttd) + missed), "detected": int(len(ttd)),
                             "median": round(float(np.median(ttd)), 1) if len(ttd) else None,
                             "p90": round(float(np.quantile(ttd, 0.9)), 1) if len(ttd) else None}
    r["benign_phases_with_alarm"] = round(ben_alarm / ben_n, 4) if ben_n else None
    return r


def md_table(name_to_report):
    """Compact markdown table of the headline numbers per model/feature set."""
    L = ["| model | ROC-AUC | PR-AUC | TPR@FPR1%val | FPR test | idle FPR | TTD med/p90 s | benign phases alarmed |",
         "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for n, r in name_to_report.items():
        m, t = r["main"], r["time_to_detect_s"]
        L.append("| %s | %s | %s | %s | %s | %s | %s/%s | %s |" % (n, m["roc_auc"], m["pr_auc"], m["tpr"], m["fpr"],
                 r["idle_fpr"], t["median"], t["p90"], r["benign_phases_with_alarm"]))
    return "\n".join(L)
