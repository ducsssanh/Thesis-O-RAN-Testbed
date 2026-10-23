"""Shared v4 evaluation (baselines and LSTM report the SAME metrics; also shipped to Kaggle).

Selection: every function takes a boolean mask `sel` over all windows (e.g. split == test);
main / edge / idle subsets are derived from it. The negative control pair
icmp_flood~icmp_ping (indistinguishable by construction) is EXCLUDED from training, from the
headline and from the per-pair macro, and reported on its own (`neg_control_auc`, expected ~0.5;
> 0.6 = leak warning).
Threshold: chosen on the validation main windows (control excluded) so that the BENIGN
false-positive rate is `fpr_target` (1%), then frozen and applied to test.
Headline (main windows, control excluded): ROC-AUC, PR-AUC, TPR/FPR at the frozen threshold,
per-pair macro AUC (attack pairs, control excluded), mimicry and pulsing AUC, time-to-detect
(TTD, from main+edge windows), benign phases with an alarm, idle false-alarm rate.
"""
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

MAIN, EDGE, IDLE = 0, 1, 2
DUAL_USE = ("pacer", "hping", "iperf")
CONTROL = "icmp_flood~icmp_ping"
MIMICRY = "mimicry_udp~udp_nofeedback"
PULSING = "pulsing_udp~onoff_pareto"


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


def headline_mask(d, sel):
    return sel & (d["kind"] == MAIN) & (d["pair"] != CONTROL)


def train_mask(d, extra=None):
    m = (d["split"] == 0) & (d["kind"] == MAIN) & (d["pair"] != CONTROL)
    return m if extra is None else m & extra


def threshold_at_fpr(p, y, fpr_target=0.01):
    """Smallest threshold whose BENIGN false-positive rate is <= fpr_target."""
    neg = np.sort(p[y == 0])
    if not len(neg):
        return 0.5
    k = int(np.floor((1 - fpr_target) * len(neg)))
    return float(neg[min(k, len(neg) - 1)]) + 1e-9


def val_threshold(p, d, fpr_target=0.01, extra=None):
    vm = headline_mask(d, d["split"] == 1)
    if extra is not None:
        vm &= extra
    return threshold_at_fpr(p[vm], d["y"][vm], fpr_target)


def pair_aucs(p, d, mm):
    out = {}
    for pair in sorted(set(d["pair"][mm])):
        if "~" not in pair:
            continue
        q = mm & (d["pair"] == pair)
        out[pair] = _auc(d["y"][q], p[q])
    return out


def macro(pa):
    v = [a for k, a in pa.items() if k != CONTROL and a is not None]
    return round(float(np.mean(v)), 4) if v else None


def report(p, d, sel, thr, _gated=False):
    """All metrics on the windows in `sel` (any kind). p = scores for ALL windows. If the windows carry
    an activity `gate`, r["gated"] repeats the operating-point metrics with score := 0 where the gate is
    closed (window mean UL < 50 kbps): a deployment rule, reported next to, never instead of, the raw ones."""
    y, kind = d["y"], d["kind"]
    hm = headline_mask(d, sel)
    mm_all = sel & (kind == MAIN)
    pred = p >= thr
    pa = pair_aucs(p, d, mm_all)
    r = {"threshold": round(float(thr), 6), "n_main": int(hm.sum()), "pos_main": int(y[hm].sum()),
         "roc_auc": _auc(y[hm], p[hm]), "pr_auc": _ap(y[hm], p[hm]),
         "tpr": _rate(pred[hm & (y == 1)]), "fpr": _rate(pred[hm & (y == 0)]),
         "pair_macro_auc": macro(pa), "mimicry_auc": pa.get(MIMICRY), "pulsing_auc": pa.get(PULSING),
         "neg_control_auc": pa.get(CONTROL), "per_pair_auc": pa}
    r["per_pair_tpr_fpr"] = {pr: {"tpr": _rate(pred[mm_all & (d["pair"] == pr) & (y == 1)]),
                                  "fpr": _rate(pred[mm_all & (d["pair"] == pr) & (y == 0)])}
                             for pr in sorted(set(d["pair"][mm_all]))}
    r["per_victim_mode"] = {v: {"tpr": _rate(pred[hm & (d["victim"] == v) & (y == 1)]),
                                "fpr": _rate(pred[hm & (d["victim"] == v) & (y == 0)])}
                            for v in sorted(set(d["victim"][hm])) if v}
    r["per_dual_use_backend_auc"] = {b: _auc(y[hm & (d["backend"] == b)], p[hm & (d["backend"] == b)]) for b in DUAL_USE}
    r["per_ue_auc"] = {u: _auc(y[hm & (d["ue"] == u)], p[hm & (d["ue"] == u)]) for u in sorted(set(d["ue"][hm]))}
    aa = d["attack_active"]
    r["tpr_by_attack_active"] = {"on": _rate(pred[hm & (y == 1) & (aa == 1)]), "off": _rate(pred[hm & (y == 1) & (aa == 0)])}
    r["idle_fpr"] = _rate(pred[sel & (kind == IDLE)])
    # time-to-detect / benign-phase alarms over main+edge windows ending in the phase (control excluded)
    pe = sel & (kind != IDLE) & (d["pair"] != CONTROL)
    key = np.char.add(np.char.add(d["run"][pe], "|"), np.char.add(np.char.add(d["ue"][pe], "|"), d["phase"][pe]))
    ts, yy, hit = d["t_since"][pe], y[pe], pred[pe]
    ttd, missed, ben_alarm, ben_n = [], 0, 0, 0
    order = np.lexsort((ts, key))
    key, ts, yy, hit = key[order], ts[order], yy[order], hit[order]
    starts = np.r_[0, np.flatnonzero(key[1:] != key[:-1]) + 1, len(key)]
    for a, b in zip(starts[:-1], starts[1:]):
        h = hit[a:b]
        if yy[a] == 1:
            if h.any():
                ttd.append(float(ts[a:b][np.argmax(h)]))
            else:
                missed += 1
        else:
            ben_n += 1
            ben_alarm += int(h.any())
    ttd = np.array(ttd)
    r["ttd"] = {"attack_phases": int(len(ttd) + missed), "detected": int(len(ttd)),
                "median_s": round(float(np.median(ttd)), 1) if len(ttd) else None,
                "p90_s": round(float(np.quantile(ttd, 0.9)), 1) if len(ttd) else None}
    r["benign_phases_alarmed"] = round(ben_alarm / ben_n, 4) if ben_n else None
    if "gate" in d and not _gated:
        g = report(np.where(d["gate"], p, 0.0), d, sel, thr, _gated=True)
        r["gated"] = {k: g[k] for k in ("tpr", "fpr", "idle_fpr", "benign_phases_alarmed", "ttd")}
    return r


def bootstrap_ci(p, d, sel, thr, B=1000, seed=0):
    """95% CI by resampling RUNS (with replacement) of the headline metrics on `sel`."""
    hm = headline_mask(d, sel)
    runs = np.unique(d["run"][hm])
    idx_by_run = {r: np.flatnonzero(hm & (d["run"] == r)) for r in runs}
    pairs_all = sel & (d["kind"] == MAIN)
    pidx_by_run = {r: np.flatnonzero(pairs_all & (d["run"] == r)) for r in runs}
    y, pred = d["y"], p >= thr
    rng = np.random.default_rng(seed)
    acc = {"roc_auc": [], "pr_auc": [], "tpr": [], "pair_macro_auc": []}
    for _ in range(B):
        rs = rng.choice(runs, len(runs), replace=True)
        ix = np.concatenate([idx_by_run[r] for r in rs])
        yy, pp = y[ix], p[ix]
        if yy.min() == yy.max():
            continue
        acc["roc_auc"].append(roc_auc_score(yy, pp))
        acc["pr_auc"].append(average_precision_score(yy, pp))
        acc["tpr"].append(pred[ix][yy == 1].mean())
        jx = np.concatenate([pidx_by_run[r] for r in rs])
        pa = []
        for pr in set(d["pair"][jx]):
            if "~" not in pr or pr == CONTROL:
                continue
            q = jx[d["pair"][jx] == pr]
            if y[q].min() != y[q].max():
                pa.append(roc_auc_score(y[q], p[q]))
        if pa:
            acc["pair_macro_auc"].append(np.mean(pa))
    return {k: [round(float(np.quantile(v, 0.025)), 4), round(float(np.quantile(v, 0.975)), 4)] if v else None
            for k, v in acc.items()}


HEAD = ("roc_auc", "pr_auc", "tpr", "fpr", "pair_macro_auc", "mimicry_auc", "pulsing_auc", "neg_control_auc", "idle_fpr")


def md_table(name_to_report, ci=None):
    """Headline table; `ci` = {name: bootstrap_ci(...)} adds [lo, hi] under ROC/PR/TPR/macro."""
    L = ["| model | ROC-AUC | PR-AUC | TPR@FPR1% | FPR | pair macro AUC | mimicry | pulsing | icmp control | idle FPR (gated) | TTD med/p90 s | benign phases alarmed (gated) |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for n, r in name_to_report.items():
        c = (ci or {}).get(n) or {}
        f = lambda k: ("%s [%s–%s]" % (r[k], *c[k])) if c.get(k) else str(r[k])
        g = r.get("gated") or {}
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s (%s) | %s/%s | %s (%s) |" % (
            n, f("roc_auc"), f("pr_auc"), f("tpr"), r["fpr"], f("pair_macro_auc"), r["mimicry_auc"], r["pulsing_auc"],
            r["neg_control_auc"], r["idle_fpr"], g.get("idle_fpr"), r["ttd"]["median_s"], r["ttd"]["p90_s"],
            r["benign_phases_alarmed"], g.get("benign_phases_alarmed")))
    return "\n".join(L)


def split_from_windows(d, seed, n_test=18, n_val=14, tries=1000):
    """Alternative run split (0 train / 1 val / 2 test per window) for the split-seed repeat:
    every meta_pair shows all its labels (main windows) in every split."""
    mm = d["kind"] == MAIN
    runs = np.unique(d["run"])
    full = {pr: set(d["y"][mm & (d["pair"] == pr)].tolist()) for pr in np.unique(d["pair"][mm]) if pr}
    by_run = {r: {} for r in runs}
    for r, pr, yy in zip(d["run"][mm], d["pair"][mm], d["y"][mm]):
        by_run[r].setdefault(pr, set()).add(int(yy))
    rng = np.random.default_rng(seed)
    for _ in range(tries):
        p = rng.permutation(runs)
        parts = (p[:n_test], p[n_test:n_test + n_val], p[n_test + n_val:])
        ok = all(set().union(*[by_run[r].get(pr, set()) for r in part]) == lab
                 for part in parts for pr, lab in full.items())
        if ok:
            s = np.zeros(len(d["run"]), np.int8)
            s[np.isin(d["run"], parts[1])] = 1
            s[np.isin(d["run"], parts[0])] = 2
            return s
    raise RuntimeError("no split covers every pair")


def transfer_protocols(d):
    """(name, train/threshold filter, test filter) for the robustness transfers."""
    P = [("leave-UE-out ue1->ue2", d["ue"] == "ue1", d["ue"] == "ue2"),
         ("leave-UE-out ue2->ue1", d["ue"] == "ue2", d["ue"] == "ue1")]
    for b in DUAL_USE:
        P.append(("leave-generator-out %s" % b, d["backend"] != b, d["backend"] == b))
    P += [("victim silent->responsive", d["victim"] == "silent", d["victim"] == "responsive"),
          ("victim responsive->silent", d["victim"] == "responsive", d["victim"] == "silent")]
    return P


def short(r):
    return {k: r[k] for k in ("n_main", "roc_auc", "pr_auc", "tpr", "fpr", "pair_macro_auc", "mimicry_auc",
                              "pulsing_auc", "neg_control_auc")}
