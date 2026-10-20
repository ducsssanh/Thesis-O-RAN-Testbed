#!/usr/bin/env python3
"""Tests for schedules/sizes/mixer (v4 plan §5.2: each model's mean and key property).

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/test_schedules.py
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np
import schedules as S, sizes as Z, mixer as M

RBAR, MS = 100_000.0, 600.0          # 800 kbit/s, 600 B mean packet
fails = []


def ok(cond, msg):
    if not cond:
        fails.append(msg)


def rel(a, b):
    return abs(a - b) / b


rng = np.random.default_rng(7)
T = 20_000

r = S.cbr(RBAR, 100)["bytes_s"]; ok(np.allclose(r, RBAR), "cbr not constant")

r = S.poisson(RBAR, T, rng, MS)["bytes_s"]
ok(rel(r.mean(), RBAR) < 0.01, f"poisson mean {r.mean():.0f}")
ok(rel((r / MS).var(), RBAR / MS) < 0.05, "poisson counts var != mean")

x = S.mmpp2(RBAR, T, rng, MS, ratio=6, q01=0.05, q10=0.15)
ok(rel(x["bytes_s"].mean(), RBAR) < 0.05, f"mmpp2 mean {x['bytes_s'].mean():.0f}")
ok((x["bytes_s"] / MS).var() > 2 * RBAR / MS, "mmpp2 not overdispersed vs Poisson")

x = S.onoff_pareto(RBAR, T, rng, K=4, a_on=1.5, a_off=1.5, t_on=1.0, t_off=2.0)
ok(rel(x["bytes_s"].mean(), RBAR) < 1e-9, "onoff mean not exact after rescale")
p_on = x["params"]["expected_on_fraction_per_source"]            # 1/3
ok(abs(x["params"]["realised_on_fraction_per_source"] - p_on) < 0.05,
   f"onoff ON fraction {x['params']['realised_on_fraction_per_source']:.3f} vs {p_on:.3f}")

for H in (0.7, 0.8, 0.9):
    g = S.fgn_series(1 << 15, H, np.random.default_rng(11))
    h = S.hurst_aggvar(g)
    ok(abs(h - H) < 0.06, f"fGn H={H} estimated {h:.3f}")
    ok(abs(np.var(g) - 1) < 0.1, f"fGn variance {np.var(g):.3f}")
x = S.fgn(RBAR, T, rng, H=0.8, c=0.5)
ok(rel(x["bytes_s"].mean(), RBAR) < 1e-9 and x["bytes_s"].min() >= 0, "fgn mean/nonneg")

x = S.hawkes(RBAR, T, rng, bytes_per_event=20000, alpha=0.6, beta=1.2)
ok(rel(x["events_s"].mean(), x["params"]["expected_event_rate"]) < 0.08,
   f"hawkes event rate {x['events_s'].mean():.3f} vs {x['params']['expected_event_rate']:.3f}")
ok(rel(x["bytes_s"].mean(), RBAR) < 0.08, "hawkes bytes mean")
c = x["events_s"]; ok(np.corrcoef(c[:-1], c[1:])[0, 1] > 0.05, "hawkes shows no self-excitation (lag-1 corr)")

x = S.pulsing(RBAR, 1000, rng, period=10, on=2)
r = x["bytes_s"]
ok(rel(r.mean(), RBAR) < 1e-9, "pulsing mean")
ok(abs((r > 0).mean() - 0.2) < 1e-9, "pulsing duty")
ok(np.allclose(r[:-10], r[10:]), "pulsing not periodic")

w = Z.draw_mix(rng); ok(abs(w.sum() - 1) < 1e-9 and (w >= 0).all(), "dirichlet weights")
ok(Z.BINS.max() - Z.HDR <= 1200, "largest bin exceeds calibrated payload")

b = S.cbr(0.4 * RBAR, 600)["bytes_s"]
a = S.pulsing(RBAR, 600, rng, period=10, on=3)["bytes_s"]
m = (a > 0).astype(float)
xx, rho, part = M.mix(RBAR, b, a, m)
ok(rel(xx.mean(), RBAR) < 1e-9 and rho > 0, f"mixer total {xx.mean():.0f}")

# reproducibility: same seed -> identical schedule
s1 = S.make("fgn", RBAR, 300, np.random.default_rng(3), MS)["bytes_s"]
s2 = S.make("fgn", RBAR, 300, np.random.default_rng(3), MS)["bytes_s"]
ok(np.array_equal(s1, s2), "same seed did not reproduce the schedule")

if fails:
    print("FAIL:"); [print("  -", f) for f in fails]; sys.exit(1)
print("ALL SCHEDULE TESTS PASSED (cbr, poisson, mmpp2, onoff_pareto, fgn H, hawkes, pulsing, sizes, mixer, seed-repro)")
