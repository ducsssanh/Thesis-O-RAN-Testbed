"""Tests of validate_twin.py on synthetic windows: KS helper agrees with scipy, statistics of a known window, a twin drawn from the
real distribution passes and a distorted twin fails.  Usage: .venv-ml/bin/python -I research/twinning/test_validate_twin.py"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np
from scipy import stats as st
import validate_twin as V

rng = np.random.default_rng(3)
a, b = np.sort(rng.integers(0, 40, 300).astype(float)), np.sort(rng.lognormal(2, 1, 50_000).round())
assert abs(V.ks_sorted(a, b) - st.ks_2samp(a, b).statistic) < 1e-9
a, b = np.sort(rng.normal(0, 1, 200)), np.sort(rng.normal(.2, 1, 20_000))
assert abs(V.ks_sorted(a, b) - st.ks_2samp(a, b).statistic) < 1e-9

u, d = np.zeros(75), np.zeros(75)
u[[20, 21, 22, 30]] = [100, 100, 100, 500]; d[[22, 40]] = [1000, 3000]
s = V.window_samples(u, d, 0, 0)
assert sorted(s["on_run"]) == [1, 3] and list(s["off_gap"]) == [7]
assert np.allclose(s["ul_rate"].mean(), 1) and np.allclose(s["ratio"], [10])
assert abs(s["busy"][0] - 5 / 60) < 1e-12 and abs(s["win_mean"][0] - 8 * 800 / 60) < 1e-9
s = V.window_samples(u, d, 200, 0)      # the threshold hides the small seconds
assert list(s["on_run"]) == [1] and s["ul_rate"].size == 1


def fake(n, duty, cell):
    active = rng.random((n, 75)) < duty[:, None]
    ul = active * rng.lognormal(6, 1.2, (n, 75)).round()
    dl = (rng.random((n, 75)) < duty[:, None]) * rng.lognormal(7, 1.2, (n, 75)).round()
    return ul, dl, np.full(n, cell)


parts = [fake(1500, rng.beta(1.2, 3, 1500), c) for c in range(4)]
ru, rd, rc = (np.concatenate([p[i] for p in parts]) for i in range(3))
n = 100
good = rng.integers(len(ru), size=n)
r = V.validate("P3", ru[good], rd[good], ru, rd, rc, active_bytes=0, replicates=240)
assert r["pass"], r
r = V.validate("P3", ru[good] * (ru[good] > 0) + 40 * (ru[good] == 0), rd[good], ru, rd, rc, active_bytes=30, replicates=240)
assert not r["pass"] and r["tests"]["busy"]["percentile"] > r["tau_star"], r     # every second looks active
r = V.validate("P4", ru[good], rd[good], ru, rd, rc, active_bytes=0, replicates=120)
assert {"ad", "q99"} <= set(r["tests"])
print("ALL VALIDATE_TWIN TESTS PASSED")
