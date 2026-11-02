"""Validation of the benign twin against Madrid (TRAFFIC-TWINNING-PLAN §6, rev 4 §0a), one band at a time.

Both sides are sets of 75 s windows, with known limits (decided 2026-11-01): the twin side comes from the gNB MAC counters
of a replayed window, the real side from benign_windows.npz (4 build cells only). So no session is re-cut on the twin,
and ON runs and OFF gaps are truncated by the window alike on both sides. Active second: bytes > 0 on the real side,
bytes > --active-bytes on the twin side (the RLC status PDUs caused by DL put a few bytes on the UL data bearer).

Statistics, per band: KS on the active-second UL and DL rate (normalised by the window's mean active rate), the per-second
DL/UL byte ratio, ON-run length, OFF-gap length, the 60 s window mean, the 60 s busy share; d_ACF (lags 1-10, windows
spanning >= 15 s); |difference| of the Spearman between ON-run length and its mean rate; for P4 also Anderson-Darling
and |difference| of q99 of the normalised UL rate. Window mean and busy share use the last 60 s (phase), the rest all 75 s.

Bar (§6.3): null = n windows drawn with replacement from cell A (a window is the cluster) against all of cell B of the same
group (I or II), both directions; per replicate each statistic becomes its percentile in its own null distribution and
T = the largest one; tau* = q95 of T. The twin passes if every statistic's percentile <= tau*.

Usage: validate_twin.py <band> <out.json> <run dir or campaign dir>... [--active-bytes 30] [--replicates 1000] [--windows f.npz]"""
import argparse, json, pathlib, sys
import numpy as np
from scipy import stats as st

LEN, PRE = 75, 15
PAIRS = [(0, 1), (1, 0), (2, 3), (3, 2)]   # cell order of benign_profiles.json: I-2650, I-1815 / II-816, II-1835
KS = ("ul_rate", "dl_rate", "ratio", "on_run", "off_gap", "win_mean", "busy")
AD_MAX = 20_000


def window_samples(u, d, au, ad):
    """All per-window quantities of one window (u, d: 75 bytes per second)."""
    ua, da = u > au, d > ad
    out = {"win_mean": np.array([8 * u[PRE:].mean()]), "busy": np.array([(ua | da)[PRE:].mean()])}
    out["ul_rate"] = u[ua] / u[ua].mean() if ua.any() else np.empty(0)
    out["dl_rate"] = d[da] / d[da].mean() if da.any() else np.empty(0)
    both = ua & da
    out["ratio"] = d[both] / u[both]
    idx = np.flatnonzero(ua)
    acf = None
    if idx.size == 0:
        out.update(on_run=np.empty(0), off_gap=np.empty(0), sp=np.empty((0, 2)))
    else:
        cut = np.flatnonzero(np.diff(idx) > 1)
        first, last = np.r_[idx[0], idx[cut + 1]], np.r_[idx[cut], idx[-1]]
        on = last - first + 1
        out["on_run"] = on.astype(float)
        out["off_gap"] = (first[1:] - last[:-1] - 1).astype(float)
        norm = u / u[ua].mean()
        out["sp"] = np.c_[on, [norm[a:b + 1].mean() for a, b in zip(first, last)]]
        if idx[-1] - idx[0] + 1 >= 15:
            x = norm[idx[0]:idx[-1] + 1] - norm[idx[0]:idx[-1] + 1].mean()
            den = float((x * x).sum())
            if den > 0:
                acf = np.r_[den, [(x[:-k] * x[k:]).sum() for k in range(1, 11)]]
    out["acf"] = acf
    return out


class Pool:
    """Samples of a set of windows, ready for repeated resampling."""

    def __init__(self, ul, dl, au, ad):
        self.w = [window_samples(u.astype(float), d.astype(float), au, ad) for u, d in zip(ul, dl)]

    def __len__(self):
        return len(self.w)

    def take(self, idx=None):
        w = self.w if idx is None else [self.w[i] for i in idx]
        s = {k: np.sort(np.concatenate([x[k] for x in w])) for k in KS}
        s["sp"] = np.concatenate([x["sp"] for x in w])
        a = [x["acf"] for x in w if x["acf"] is not None]
        s["acf"] = (np.sum(a, axis=0)[1:] / np.sum(a, axis=0)[0]) if a else None
        return s


def ks_sorted(a, b):
    """Two-sample KS distance of sorted arrays, in O(len(a) log len(b)), for a much smaller than b."""
    if a.size == 0 or b.size == 0:
        return np.nan
    hi = np.abs(np.searchsorted(a, a, "right") / a.size - np.searchsorted(b, a, "right") / b.size).max()
    lo = np.abs(np.searchsorted(a, a, "left") / a.size - np.searchsorted(b, a, "left") / b.size).max()
    return float(max(hi, lo))


def spearman(x):
    if len(x) < 3 or np.ptp(x[:, 0]) == 0 or np.ptp(x[:, 1]) == 0:
        return np.nan
    return float(st.spearmanr(x[:, 0], x[:, 1]).statistic)


def compare(a, b, heavy, b_sp, b_ad):
    out = {k: ks_sorted(a[k], b[k]) for k in KS}
    out["d_acf"] = float(((a["acf"] - b["acf"]) ** 2).sum()) if a["acf"] is not None and b["acf"] is not None else np.nan
    out["spearman"] = abs(spearman(a["sp"]) - b_sp)
    if heavy:
        out["q99"] = abs(np.quantile(a["ul_rate"], .99) - np.quantile(b["ul_rate"], .99)) if a["ul_rate"].size else np.nan
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out["ad"] = float(st.anderson_ksamp([a["ul_rate"], b_ad], method=None).statistic) if a["ul_rate"].size > 1 else np.nan
    return out


def reference(p):
    b = p.take()
    u = b["ul_rate"]
    ad = u if u.size <= AD_MAX else u[np.linspace(0, u.size - 1, AD_MAX).astype(int)]
    return b, spearman(b["sp"]), ad


def null_bar(cells, n, heavy, replicates, seed=0):
    """Per statistic the null values, T per replicate, tau*; also tau* per pair."""
    rng = np.random.default_rng(seed)
    refs = {k: reference(c) for k, c in cells.items()}
    per = replicates // len(PAIRS)
    rows, tag = [], []
    for ia, ib in PAIRS:
        b, sp, ad = refs[ib]
        for _ in range(per):
            rows.append(compare(cells[ia].take(rng.integers(len(cells[ia]), size=n)), b, heavy, sp, ad))
            tag.append((ia, ib))
    names = list(rows[0])
    V = np.array([[r[k] for k in names] for r in rows])
    P = np.zeros_like(V)
    for j in range(V.shape[1]):
        col = V[:, j]
        ok = np.sort(col[~np.isnan(col)])
        P[:, j] = np.where(np.isnan(col), 0.0, np.searchsorted(ok, col, "right") / max(ok.size, 1))
    T = P.max(axis=1)
    tag = np.array(tag)
    by_pair = {"%d-%d" % p: float(np.quantile(T[(tag == p).all(axis=1)], .95)) for p in PAIRS}
    return names, V, float(np.quantile(T, .95)), by_pair


def validate(band, twin_u, twin_d, real_u, real_d, real_cell, active_bytes=30, replicates=1000):
    heavy = band == "P4"
    tw = Pool(twin_u, twin_d, active_bytes, active_bytes).take()
    all_real = Pool(real_u, real_d, 0, 0)
    cells = {c: Pool(real_u[real_cell == c], real_d[real_cell == c], 0, 0) for c in {x for p in PAIRS for x in p}}
    names, V, tau, by_pair = null_bar(cells, len(twin_u), heavy, replicates)
    b, sp, ad = reference(all_real)
    s = compare(tw, b, heavy, sp, ad)
    tests = {}
    for j, k in enumerate(names):
        col = np.sort(V[:, j][~np.isnan(V[:, j])])
        tests[k] = {"stat": None if np.isnan(s[k]) else round(float(s[k]), 5),
                    "percentile": None if np.isnan(s[k]) or not col.size else round(float(np.searchsorted(col, s[k], "right") / col.size), 4),
                    "null_q50": round(float(np.median(col)), 5) if col.size else None,
                    "null_q95": round(float(np.quantile(col, .95)), 5) if col.size else None}
        if k in KS and tw[k].size and b[k].size:
            r = st.ks_2samp(tw[k], b[k])
            tests[k].update(n_twin=int(tw[k].size), location=float(r.statistic_location), sign=int(r.statistic_sign))
    pct = [t["percentile"] for t in tests.values() if t["percentile"] is not None]
    no_data = [k for k, t in tests.items() if t["percentile"] is None]
    return {"band": band, "n_windows": len(twin_u), "tau_star": round(tau, 4), "tau_per_pair": {k: round(v, 4) for k, v in by_pair.items()},
            "pass": bool(pct) and max(pct) <= tau and not no_data, "worst": max(tests, key=lambda k: tests[k]["percentile"] or 0),
            "no_data": no_data, "active_bytes": active_bytes, "replicates": replicates, "tests": tests}


def run_dirs(paths):
    out = []
    for p in map(pathlib.Path, paths):
        out += [p] if (p / "traffic/flows.json").exists() else sorted(q.parent.parent for q in p.glob("runs/*/*/traffic/flows.json"))
    return out


def twin_windows(run, band):
    """MAC bytes per second of every replayed window of a run. A second is the stats second ending at start + i + 1 (grid: gnb).
    A window with a missing stats sample or a new RNTI inside it is dropped and counted."""
    mac, dropped, U, D, src = {}, 0, [], [], []
    with open(run / "ran/mac_stats.csv") as fh:
        next(fh)
        for line in fh:
            f = line.strip().split(",")
            mac.setdefault(f[2], []).append((float(f[0]), f[1], int(f[4]), int(f[5])))
    for fl in json.loads((run / "traffic/flows.json").read_text()):
        if fl.get("model") != "real_window" or fl["v4_meta"].get("band") != band:
            continue
        rows = mac.get(fl["ue"], [])
        t = np.array([r[0] for r in rows])
        s0, u, d, good = fl["replay_start_at"], np.zeros(LEN), np.zeros(LEN), bool(rows)
        for i in range(LEN if good else 0):
            k = int(np.argmin(np.abs(t - (s0 + i + 1))))
            if abs(t[k] - (s0 + i + 1)) > 0.5 or k == 0 or rows[k][1] != rows[k - 1][1] or t[k] - t[k - 1] > 1.5:
                good = False
                break
            u[i], d[i] = rows[k][2] - rows[k - 1][2], rows[k][3] - rows[k - 1][3]
        if good:
            U.append(u); D.append(d); src.append([str(run), fl["phase"], fl["ue"]])
        else:
            dropped += 1
    return U, D, src, dropped


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("band"); ap.add_argument("out"); ap.add_argument("runs", nargs="+")
    ap.add_argument("--active-bytes", type=float, default=30); ap.add_argument("--replicates", type=int, default=1000)
    ap.add_argument("--windows", default=str(pathlib.Path(__file__).parent / "benign_windows.npz"))
    a = ap.parse_args()
    U, D, src, dropped = [], [], [], 0
    for r in run_dirs(a.runs):
        u, d, s, n = twin_windows(r, a.band)
        U += u; D += d; src += s; dropped += n
    if not U:
        sys.exit("no window of band %s in %s" % (a.band, a.runs))
    z = np.load(a.windows)
    res = validate(a.band, np.array(U), np.array(D), z["ul_" + a.band], z["dl_" + a.band], z["src_" + a.band][:, 0], a.active_bytes, a.replicates)
    res.update(dropped_windows=dropped, runs=a.runs, windows=a.windows)
    pathlib.Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    print("%s n=%d dropped=%d tau*=%.3f pass=%s worst=%s no_data=%s" % (a.band, res["n_windows"], dropped, res["tau_star"], res["pass"], res["worst"], res["no_data"]))
    print("tau per pair", res["tau_per_pair"])
    for k, t in res["tests"].items():
        print("  %-9s stat %-9s pct %-7s null q50/q95 %s/%s  n %s loc %s sign %s" % (k, t["stat"], t["percentile"], t["null_q50"], t["null_q95"], t.get("n_twin", ""), t.get("location", ""), t.get("sign", "")))


if __name__ == "__main__":
    main()
