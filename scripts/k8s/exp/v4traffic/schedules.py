"""Rate-schedule models for the v4 traffic library (v4 plan §5.2).

Every model returns a per-second target series of IP-level bytes/s with a
prescribed mean r̄ (the load level), so benign and attack traffic of one design
cell can be load-matched exactly. Intra-second packet timing is left to the
backend ("process": "even" spreads packets evenly, "poisson" uses exponential
gaps). All randomness comes from a numpy Generator, so a schedule is fully
reproducible from (model, params, seed).

Models (mean constraint in brackets):
  cbr           r_t = r̄                                              [exact]
  poisson       packet counts ~ Poisson(λ), λ = r̄ / E[size]          [E = r̄]
  mmpp2         2-state Markov-modulated Poisson; λ_lo, λ_hi set so
                (q10·λ_lo + q01·λ_hi)/(q01+q10) = r̄/E[size]            [E = r̄]
  onoff_pareto  K sources, ON/OFF durations Pareto(α∈(1.2,1.8), t_m);
                peak p = r̄(E[ON]+E[OFF])/(K·E[ON]); realised series
                rescaled to mean r̄ (heavy tails make the sample mean of a
                short run drift; load matching needs the realised mean)   [exact]
  fgn           r_t = r̄·max(0, 1 + c·G_t), G = fGn(H) by Davies-Harte;
                rescaled to mean r̄                                     [exact]
  hawkes        self-exciting connection arrivals (μ, α, β, α/β<1), Ogata
                thinning; mean event rate μ/(1-α/β); each event carries
                `bytes_per_event` → mean bytes/s = r̄                    [E = r̄]
  pulsing       square wave period T, on-length L, amplitude R = r̄·T/L,
                random phase offset; mean R·L/T = r̄                    [exact]
"""
import pathlib

import numpy as np

MODELS = ("cbr", "poisson", "mmpp2", "onoff_pareto", "fgn", "hawkes", "pulsing")


def _result(model, rate, process, params, events=None):
    out = {"model": model, "bytes_s": np.asarray(rate, dtype=float), "process": process, "params": params}
    if events is not None:
        out["events_s"] = np.asarray(events, dtype=float)
    return out


def cbr(rbar, T, rng=None):
    return _result("cbr", np.full(T, float(rbar)), "even", {"rbar": rbar})


def poisson(rbar, T, rng, mean_size):
    lam = rbar / mean_size
    counts = rng.poisson(lam, size=T)
    return _result("poisson", counts * mean_size, "poisson", {"rbar": rbar, "lambda_pps": lam})


def mmpp2(rbar, T, rng, mean_size, ratio=6.0, q01=0.05, q10=0.15):
    """q01: lo->hi rate (1/s), q10: hi->lo rate (1/s); λ_hi = ratio·λ_lo."""
    pi_hi = q01 / (q01 + q10)
    pi_lo = 1.0 - pi_hi
    lam_mean = rbar / mean_size
    lam_lo = lam_mean / (pi_lo + ratio * pi_hi)
    lam_hi = ratio * lam_lo
    p01, p10 = 1 - np.exp(-q01), 1 - np.exp(-q10)   # per-second switch probabilities
    state = int(rng.random() < pi_hi)               # start in the stationary distribution
    counts = np.empty(T)
    for t in range(T):
        counts[t] = rng.poisson(lam_hi if state else lam_lo)
        state = (1 - state) if rng.random() < (p10 if state else p01) else state
    return _result("mmpp2", counts * mean_size, "poisson",
                   {"rbar": rbar, "lambda_lo": lam_lo, "lambda_hi": lam_hi, "q01": q01, "q10": q10})


def pareto_mean(alpha, t_m):
    return alpha * t_m / (alpha - 1)


def onoff_pareto(rbar, T, rng, K=4, a_on=1.5, a_off=1.5, t_on=1.0, t_off=2.0):
    for a in (a_on, a_off):
        if not 1.2 <= a <= 1.8:
            raise ValueError("alpha must be in [1.2, 1.8]")
    e_on, e_off = pareto_mean(a_on, t_on), pareto_mean(a_off, t_off)
    p = rbar * (e_on + e_off) / (K * e_on)
    rate = np.zeros(T)
    on_time = 0.0
    for _ in range(K):
        t = -rng.random() * (e_on + e_off)          # random phase so sources are not aligned
        on = rng.random() < e_on / (e_on + e_off)
        while t < T:
            d = (t_on if on else t_off) * (1 - rng.random()) ** (-1 / (a_on if on else a_off))
            if on:                                   # add p over [t, t+d) with fractional seconds
                a, b = max(t, 0.0), min(t + d, T)
                on_time += max(b - a, 0.0)
                i = int(np.floor(a))
                while a < b:
                    j = min(b, i + 1)
                    rate[i] += p * (j - a)
                    a, i = j, i + 1
            t += d
            on = not on
    on_frac = float((rate > 0).mean())
    if rate.mean() > 0:
        rate *= rbar / rate.mean()
    return _result("onoff_pareto", rate, "even",
                   {"rbar": rbar, "K": K, "a_on": a_on, "a_off": a_off, "t_on": t_on, "t_off": t_off,
                    "peak_theoretical": p, "expected_on_fraction_per_source": e_on / (e_on + e_off),
                    "realised_nonzero_fraction": on_frac, "realised_on_fraction_per_source": on_time / (K * T)})


def fgn_series(T, H, rng):
    """Fractional Gaussian noise (unit variance) by Davies-Harte circulant embedding."""
    n = 1 << int(np.ceil(np.log2(2 * T)))
    k = np.arange(n + 1)
    gamma = 0.5 * (np.abs(k + 1) ** (2 * H) - 2 * np.abs(k) ** (2 * H) + np.abs(k - 1) ** (2 * H))
    row = np.concatenate([gamma, gamma[-2:0:-1]])   # length 2n
    lam = np.fft.fft(row).real
    if np.any(lam < -1e-8):
        raise RuntimeError("circulant embedding not non-negative definite")
    lam = np.clip(lam, 0, None)
    m = row.size
    z = rng.standard_normal(m) + 1j * rng.standard_normal(m)
    w = np.fft.fft(np.sqrt(lam / m) * z)
    return w.real[:T]


def fgn(rbar, T, rng, H=0.8, c=0.5):
    if not 0.7 <= H <= 0.9:
        raise ValueError("H must be in [0.7, 0.9]")
    g = fgn_series(T, H, rng)
    rate = rbar * np.maximum(0.0, 1.0 + c * g)
    rate *= rbar / rate.mean()
    return _result("fgn", rate, "even", {"rbar": rbar, "H": H, "c": c})


def hawkes(rbar, T, rng, bytes_per_event=20000.0, alpha=0.6, beta=1.2):
    """Ogata thinning; exponential kernel α·e^{-β s}. Branching ratio α/β < 1."""
    if alpha / beta >= 1:
        raise ValueError("alpha/beta must be < 1")
    mean_events = rbar / bytes_per_event
    mu = mean_events * (1 - alpha / beta)
    t, excite, events = 0.0, 0.0, []
    while True:
        lam_bar = mu + excite                        # intensity is non-increasing between events
        w = rng.exponential(1 / lam_bar)
        excite *= np.exp(-beta * w)
        t += w
        if t >= T:
            break
        if rng.random() * lam_bar <= mu + excite:     # accept
            events.append(t)
            excite += alpha
    ev = np.histogram(events, bins=np.arange(T + 1))[0].astype(float)
    return _result("hawkes", ev * bytes_per_event, "events",
                   {"rbar": rbar, "mu": mu, "alpha": alpha, "beta": beta, "bytes_per_event": bytes_per_event,
                    "expected_event_rate": mean_events}, events=ev)


def pulsing(rbar, T, rng, period=10, on=2):
    if not 0 < on < period:
        raise ValueError("0 < on < period")
    R = rbar * period / on
    off = int(rng.integers(period))
    rate = np.array([R if ((t + off) % period) < on else 0.0 for t in range(T)])
    return _result("pulsing", rate, "even", {"rbar": rbar, "period": period, "on": on, "amplitude": R, "offset": off})


# ---- benign twin: replay of a real window -----------------------
WINDOWS_NPZ = pathlib.Path(__file__).resolve().parents[4] / "research/twinning/benign_windows.npz"
WINDOW_LEN = 75                                      # 15 s pre-roll + 60 s phase
_windows = {}


def real_window(band, rng, path=WINDOWS_NPZ):
    """One real user's window of the band: UL and DL bytes per second of the SAME window, never
    rescaled, zeros outside the session. src = (cell index, rnti, start second)."""
    if path not in _windows:
        _windows[path] = np.load(path)
    d = _windows[path]
    i = int(rng.integers(d["ul_" + band].shape[0]))
    return {"ul": d["ul_" + band][i].astype(float), "dl": d["dl_" + band][i].astype(float),
            "src": [int(x) for x in d["src_" + band][i]], "index": i}


WINDOWS_TTI_NPZ = WINDOWS_NPZ.replace("benign_windows.npz", "benign_windows_tti.npz") if isinstance(WINDOWS_NPZ, str) else WINDOWS_NPZ.with_name("benign_windows_tti.npz")
_tti = {}


def window_tti(band, index, direction, path=WINDOWS_TTI_NPZ):
    """TTIs of one window: ms from the window start and bytes, sorted by time."""
    if path not in _tti:
        z = np.load(path)
        _tti[path] = {k: z[k] for k in z.files}
    d, n = _tti[path], "%s_%s_" % (direction, band)
    a, b = d[n + "off"][index], d[n + "off"][index + 1]
    return d[n + "ms"][a:b], d[n + "b"][a:b]


def make(model, rbar, T, rng, mean_size, **kw):
    if model == "cbr":
        return cbr(rbar, T)
    if model == "poisson":
        return poisson(rbar, T, rng, mean_size)
    if model == "mmpp2":
        return mmpp2(rbar, T, rng, mean_size, **kw)
    if model == "onoff_pareto":
        return onoff_pareto(rbar, T, rng, **kw)
    if model == "fgn":
        return fgn(rbar, T, rng, **kw)
    if model == "hawkes":
        return hawkes(rbar, T, rng, **kw)
    if model == "pulsing":
        return pulsing(rbar, T, rng, **kw)
    raise ValueError(model)


def hurst_aggvar(x, scales=(1, 2, 4, 8, 16, 32, 64)):
    """Aggregated-variance estimate of H (Var(X^(m)) ~ m^(2H-2))."""
    v = []
    for m in scales:
        n = len(x) // m
        v.append(np.var(x[: n * m].reshape(n, m).mean(1)))
    slope = np.polyfit(np.log(scales), np.log(v), 1)[0]
    return 1 + slope / 2
