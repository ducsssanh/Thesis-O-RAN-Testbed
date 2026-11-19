#!/usr/bin/env python3
"""Gate replay and KPM tamper injection on built rows. Shared by the DRL environment and the baselines.

gate(df, scope): the xApp gate of features.c over a frame of rows: c_t per second, c_t_w over 3 s, trust EWMA, mask with hysteresis. scope "node" pools the UEs of the gNB as the
live xApp does; scope "ue" keeps one trust per UE.
tamper(df, ...): hiding or framing multiplies UL rate, UL throughput, UL PRB of the UE and its share of the cell UL PRB by one factor; values stay on the grid of honest KPM
(rate in 8 B steps per second, PRB in whole percent), so the injection leaves no cue of its own. on_only limits it to attack seconds. swap exchanges all KPM fields of two UEs."""
import numpy as np, pandas as pd

BETA, EPS, LO, HI, ALPHA, TRUST_MIN, HYST, WINDOW = 57.0, 1000.0, -0.2, 0.2, 0.1, 0.85, 0.05, 3
KPM_ALL = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps", "prb_ul_pct", "prb_dl_pct"]
RATE_STEP = 0.008


def gate(df, scope="node"):
    """df: one gNB, columns t_unix, supi, rate_ul_kbps, prof_ul_bytes, prof_ul_pkts, prof_window_s. Returns a frame on the index of df: c_t, c_t_w, kpm_trust, kpm_masked."""
    d = df.sort_values(["t_unix", "supi"], kind="stable")
    kpm = d["rate_ul_kbps"].to_numpy(float) * 125.0
    core = np.maximum(d["prof_ul_bytes"].to_numpy(float) - BETA * d["prof_ul_pkts"].to_numpy(float), 0.0) / d["prof_window_s"].to_numpy(float)
    has = ~(np.isnan(kpm) | np.isnan(core))
    n = len(d)
    ct, cw, tr, mk = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, bool)
    hist, trust, masked = {}, {}, {}
    for i, (t, s) in enumerate(zip(d["t_unix"].to_numpy(), d["supi"].to_numpy())):
        key = "node" if scope == "node" else s
        trust.setdefault(key, 1.0); masked.setdefault(key, False)
        if has[i]:
            ct[i] = np.log((kpm[i] + EPS) / (core[i] + EPS))
            h = hist.setdefault(s, {})
            h[t] = (kpm[i], core[i])
            w = [h[t - k] for k in range(WINDOW) if t - k in h]
            sk, sc, e = sum(x[0] for x in w), sum(x[1] for x in w), EPS * len(w)
            cw[i] = np.log((sk + e) / (sc + e))
            if not ((kpm[i] <= 0 and core[i] <= 0) or (sk < e and sc < e)):
                trust[key] += ALPHA * (float(LO <= cw[i] <= HI) - trust[key])
                masked[key] = trust[key] < TRUST_MIN + HYST if masked[key] else trust[key] < TRUST_MIN
        tr[i], mk[i] = trust[key], masked[key]
    out = pd.DataFrame({"c_t": ct, "c_t_w": cw, "kpm_trust": tr, "kpm_masked": mk}, index=d.index)
    return out.reindex(df.index)


def tamper(df, supi, t0, t1, factor=None, on_only=False, swap_with=None, donor=None):
    """A copy of df with the KPM of `supi` tampered on seconds t0 <= t < t1; the cell PRB follows. Gate columns are not updated: call gate() on the result.
    donor (2026-11-09, "mimic"): rows of a benign UE recorded on the testbed; its KPM replaces the UE's KPM second by second (the k-th tampered
    second gets the k-th donor second): a MITM replaying a real benign KPM trace, so the reported KPM is benign KPM by construction."""
    d = df.copy()
    me = (d["supi"] == supi) & (d["t_unix"] >= t0) & (d["t_unix"] < t1)
    if on_only:
        me &= d["attack_active"] == 1
    if donor is not None:
        idx = d.index[me][:len(donor)]
        src = donor.iloc[:len(idx)]
        for c, cell in (("prb_ul_pct", "cell_prb_ul_pct"), ("prb_dl_pct", "cell_prb_dl_pct")):
            delta = src[c].to_numpy() - d.loc[idx, c].to_numpy()
            d.loc[idx, cell] = np.clip(np.nan_to_num(d.loc[idx, cell].to_numpy() + delta), 0.0, 100.0)
        for c in KPM_ALL:
            d.loc[idx, c] = src[c].to_numpy()
        return d
    if swap_with is not None:
        a = d[me].set_index("t_unix")
        o = (d["supi"] == swap_with) & d["t_unix"].isin(a.index)
        b = d[o].set_index("t_unix")
        both = a.index.intersection(b.index)
        for c in KPM_ALL:
            d.loc[me & d["t_unix"].isin(both), c] = b.loc[d.loc[me & d["t_unix"].isin(both), "t_unix"], c].to_numpy()
            d.loc[o & d["t_unix"].isin(both), c] = a.loc[d.loc[o & d["t_unix"].isin(both), "t_unix"], c].to_numpy()
        return d
    for c in ("rate_ul_kbps", "thp_ul_kbps"):
        d.loc[me, c] = np.round(d.loc[me, c] * factor / RATE_STEP) * RATE_STEP
    new = np.minimum(np.round(d.loc[me, "prb_ul_pct"] * factor), 100.0)
    delta = new - d.loc[me, "prb_ul_pct"]
    d.loc[me, "prb_ul_pct"] = new
    d.loc[me, "cell_prb_ul_pct"] = np.clip(d.loc[me, "cell_prb_ul_pct"] + delta, 0.0, 100.0)
    return d
