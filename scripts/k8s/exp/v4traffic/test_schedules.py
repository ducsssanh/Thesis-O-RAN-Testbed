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

# ---- benign twin: packets of a real second, plan of a real window, pacer run, MAC counters ----------
import json, socket, subprocess, tempfile
import planbuilder as PB
q = Z.app_priors()["Zoom_2"]["ul_size_q"]
prng = np.random.default_rng(1)
for target in (5000.0, 73.0, 300.0, 1_000_000.0):
    pk = Z.packetize(target, q, prng)
    mac = sum(pk) + Z.MAC_OVERHEAD * len(pk)
    ok(0 <= target - mac < Z.MIN_IP + Z.MAC_OVERHEAD, f"packetize {target}: MAC bytes {mac}")
    ok(min(pk) >= Z.MIN_IP and max(pk) <= Z.MAX_IP, f"packetize {target}: length out of range")
ok(Z.packetize(0, q, prng) == [], "packetize: a silent second must send nothing")
pk = Z.packetize(20.0, q, prng); ok(pk == [Z.MIN_IP], f"packetize: below one packet gives the floor, got {pk}")
ok(len(Z.packetize(4_000_000.0, q, prng)) <= Z.MAX_PPS * 2, "packetize: pps cap")

tmp = pathlib.Path(tempfile.mkdtemp())
ul_w = np.zeros((2, 75), dtype=np.uint32); dl_w = np.zeros((2, 75), dtype=np.uint32)
ul_w[:, 10:20] = 900; dl_w[:, 15:25] = 3000; ul_w[:, 30] = 3_000_000
np.savez(tmp / "w.npz", ul_P4=ul_w, dl_P4=dl_w, src_P4=np.array([[1, 54628, 1586178760], [2, 7, 8]]))
spec = {"band": "P4", "seed": 5, "windows_npz": tmp / "w.npz", "role": "benign", "model": "real_window", "backend": "pacer"}
plan, meta = PB.build_plan(spec, 75, "127.0.0.1", "127.0.0.1", 5999)
plan2, _ = PB.build_plan(spec, 75, "127.0.0.1", "127.0.0.1", 5999)
ok(plan == plan2, "real_window: same seed did not reproduce the plan")
ok(all(not s["pkts"] for i, s in enumerate(plan["seconds"]) if not (10 <= i < 20 or i == 30)), "real_window: traffic outside the window's active seconds")
ok(all(s["pkts"] for i, s in enumerate(plan["seconds"]) if 10 <= i < 20), "real_window: active second without packets")
ok(all(bool(s["pkts"]) == (15 <= i < 25) for i, s in enumerate(plan["dl_seconds"])), "real_window: DL is not the window's DL")
ok(meta["ul_clipped_s"] == 1 and plan["seconds"][30]["bytes"] == PB.REPLAY_CAP_BYTES_S["ul"], "real_window: capacity clip not applied or not counted")
ok(meta["window"]["rnti"] in (54628, 7) and meta["app"] in Z.app_priors(), "real_window: window source not in the meta")
try:
    PB.build_plan(spec, 60, "127.0.0.1", "127.0.0.1", 5999); ok(False, "real_window accepted a phase that is not 75 s")
except ValueError:
    pass

# pacer: exact packets, sent on time, inside the span of their second, silent seconds stay silent
sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sink.bind(("127.0.0.1", 0)); sink.settimeout(3)
secs = [{"bytes": 0, "pkts": []}, {"bytes": 500, "pkts": [100, 29, 300]}, {"bytes": 0, "pkts": []}]
t0 = __import__("time").time() + 0.5
(tmp / "p.json").write_text(json.dumps({"dst": "127.0.0.1", "ports": [sink.getsockname()[1]], "process": "poisson", "span": [0.05, 0.75],
                                        "seconds": secs, "start_at": t0, "seed": 1}))
pc = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).parent / "backends/pacer.py"), str(tmp / "p.json")], stdout=subprocess.PIPE, text=True)
got = []
try:
    while len(got) < 3:
        d, _ = sink.recvfrom(4096); got.append((__import__("time").time() - t0, len(d)))
except socket.timeout:
    pass
rows = [json.loads(x) for x in pc.communicate(timeout=10)[0].splitlines()]
ok(sorted(g[1] for g in got) == [1, 72, 272], f"pacer: wrong datagram sizes {got}")
ok(all(1.0 <= g[0] <= 1.8 for g in got), f"pacer: packets outside second 1 span {got}")
ok([r["sent_pkts"] for r in rows] == [0, 3, 0] and rows[1]["sent_bytes"] == 429, f"pacer rows {rows}")
ok(rows[0]["late_s"] < 0.1, "pacer: started late")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import collect
raw = """@1793538766.384
UE RNTI 2580 CU-UE-ID 1 in-sync PH 48 dB
UE 2580: dlsch_rounds 14987/894/0/0, dlsch_errors 0
UE 2580: ulsch_rounds 103036/6768/0/0, ulsch_errors 0
UE 2580: LCID 1: TX            528 RX            294 bytes
UE 2580: LCID 2: TX              0 RX              0 bytes
UE 2580: LCID 4: TX         461910 RX      122273648 bytes
@1793538767.385
UE RNTI 2580 CU-UE-ID 1 in-sync PH 48 dB
UE 2580: dlsch_rounds 14990/894/0/0, dlsch_errors 0
UE 2580: ulsch_rounds 103040/6768/0/0, ulsch_errors 0
UE 2580: LCID 4: TX         461985 RX      122273700 bytes
"""
lines = collect.parse_mac_stats(raw, {"2580": "ue1"}).splitlines()
ok(lines[1] == "1793538766.384,2580,ue1,1,122273648,461910,103036,14987", f"mac csv row: {lines[1]}")
ok(lines[2] == "1793538767.385,2580,ue1,1,122273700,461985,103040,14990" and len(lines) == 3, f"mac csv: {lines}")

if fails:
    print("FAIL:"); [print("  -", f) for f in fails]; sys.exit(1)
print("ALL SCHEDULE TESTS PASSED (cbr, poisson, mmpp2, onoff_pareto, fgn H, hawkes, pulsing, sizes, mixer, seed-repro)")
