"""The 25 model inputs of one episode scenario, as train_clf.py builds them: cur(raw, "f15") + win_summary(raw, 10)."""
import numpy as np


def cur(raw):
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))[:, None]
    dlul = (raw[:, 7] - raw[:, 6])[:, None]
    return np.hstack([raw[:, [6, 7, 8, 9, 2, 3]], prbk, raw[:, [10, 11]], dlul, raw[:, [30, 26, 27, 28, 29]]])


def win_summary(raw, W=10):
    k, p, r = np.expm1(raw[:, 6]), np.expm1(raw[:, 8]), raw[:, 2] * 100
    T = len(k); out = np.zeros((T, 10), np.float32)
    for t in range(T):
        lo = max(0, t - W + 1); kk, pp, rr = k[lo:t + 1], p[lo:t + 1], r[lo:t + 1]
        m = kk.mean(); busy = kk >= 8
        run = best = 0
        for b in busy:
            run = 0 if b else run + 1; best = max(best, run)
        out[t] = [np.log1p(m), np.log1p(kk.max()), np.log1p(pp.mean()), np.log1p(pp.max()), rr.mean() / 100, rr.max() / 100,
                  busy.mean(), kk.std() / m if m > 0 else 0, kk.max() / m if m > 0 else 0, best / W]
    return out


def x25(raw):
    return np.hstack([cur(raw), win_summary(raw)]).astype(np.float32)


def coupling(raw):
    """train_clf.py coupling() (E2): UL-DL coupling over 10 s and 30 s."""
    ul, dl = np.expm1(raw[:, 6]), np.expm1(raw[:, 7])
    T = len(ul); out = np.zeros((T, 6), np.float32)
    for t in range(T):
        u10, d10 = ul[max(0, t - 9):t + 1], dl[max(0, t - 9):t + 1]
        u30, d30 = ul[max(0, t - 29):t + 1], dl[max(0, t - 29):t + 1]
        su10, su30 = u10.sum(), u30.sum()
        out[t] = [np.log1p(d10.mean()), np.log1p(d10.max()), np.log1p(d10.sum()) - np.log1p(su10), np.log1p(d30.sum()) - np.log1p(su30),
                  u10[d10 < 1].sum() / su10 if su10 > 0 else 0, u30[d30 < 1].sum() / su30 if su30 > 0 else 0]
    return out


def x31(raw):
    return np.hstack([cur(raw).astype(np.float32), win_summary(raw), coupling(raw)]).astype(np.float32)


# Ablations requested by the advisor (2026-11-10), as columns of x31 (= train_clf.py f15c). x31 order: 0-3 core UL/DL kbit/s and pps,
# 4-5 PRB UL/DL, 6 PRB per kbit/s, 7-8 packet size UL/DL, 9 DL/UL, 10 c_t_w, 11 trust, 12 mask, 13 KPM age, 14 profile age,
# 15-24 window (19-20 PRB mean/max), 25-30 UL-DL coupling.
X31_NAMES = ["core_ul_kbps", "core_dl_kbps", "core_ul_pps", "core_dl_pps", "prb_ul", "prb_dl", "prb_ul_per_kbit", "size_ul", "size_dl", "dl_over_ul",
             "c_t_w", "trust_ue", "mask_ue", "kpm_age", "prof_age", "w_ul_kbps_mean", "w_ul_kbps_max", "w_ul_pps_mean", "w_ul_pps_max", "w_prb_mean",
             "w_prb_max", "w_busy", "w_cv", "w_peak", "w_silence", "dl_mean10", "dl_max10", "dlul_10", "dlul_30", "ul_dlidle_10", "ul_dlidle_30"]
SUBSETS = {
    "f15c_core": [i for i in range(31) if i not in (4, 5, 6, 10, 11, 12, 13, 19, 20)],   # core only: no KPM input, no gate input (22)
    "f15c_nogate": [i for i in range(31) if i not in (10, 11, 12)],                      # no c_t_w, trust, mask (28)
}
