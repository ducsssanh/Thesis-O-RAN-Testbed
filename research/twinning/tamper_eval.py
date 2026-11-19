#!/usr/bin/env python3
"""Gate on replayed tampering over the whole campaign. Each attack episode of the attacker UE is tampered from the onset to its end, one factor at a time, the gate replayed from the start of its run, node trust (as live) against per-UE trust.
Per factor: share of episodes masked, gate seconds and wall seconds to the mask, attack bytes reaching the core before it, and masking of the honest UE of the node. Also ON-only tampering and identity swap. Usage: tamper_eval.py <rows.parquet>"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts/ml"))
import tamper_replay as TR
df = pd.read_parquet(sys.argv[1])
runs = {k: g.copy() for k, g in df.groupby("run_id")}
eps = df[df.attack_active == 1].groupby(["run_id", "phase", "supi"]).agg(t0=("t_unix", "min"), t1=("t_unix", "max"), ev=("evasion", "first")).reset_index()
print("attack episodes", len(eps))
GATE = lambda x: (x.rate_ul_kbps * 125 >= 1000) | (x.prof_ul_kbps * 125 >= 1000)
for name, kw in [("x0.1", dict(factor=.1)), ("x0.33", dict(factor=.33)), ("x0.8", dict(factor=.8)), ("x1.25", dict(factor=1.25)), ("x2", dict(factor=2)), ("x5", dict(factor=5)), ("ON-only x0.33", dict(factor=.33, on_only=True)), ("ON-only x2", dict(factor=2, on_only=True)), ("swap", None)]:
    for scope in ("node", "ue"):
        R = []
        for e in eps.itertuples():
            d = runs[e.run_id]
            d = d[d.t_unix <= e.t1 + 1]
            d = d[d.phase == e.phase]                    # the gate restarts for each episode: no carry-over between tampers
            other = next((s for s in d.supi.unique() if s != e.supi), None)
            if kw is None:
                if other is None:
                    continue
                t = TR.tamper(d, e.supi, e.t0, e.t1 + 1, swap_with=other)
            else:
                t = TR.tamper(d, e.supi, e.t0, e.t1 + 1, **kw)
            g = TR.gate(t, scope)
            me = (t.supi == e.supi) & (t.t_unix >= e.t0)
            hit = t.t_unix[me & g.kpm_masked]
            first = hit.min() if len(hit) else None
            active = me & GATE(t) & (t.t_unix < (first if first else 1e18))
            before = t.attack_bytes_core[me & (t.t_unix < (first if first else 1e18))].sum()
            hon = (t.supi != e.supi) & (t.t_unix >= e.t0) & GATE(t)
            R.append(dict(ev=e.ev, masked=first is not None, wall=(first - e.t0) if first else np.nan, gate_s=int(active.sum()), bytes=before, total=t.attack_bytes_core[me].sum(), honest_masked=g.kpm_masked[hon].mean() if hon.any() else np.nan))
        r = pd.DataFrame(R)
        print("%-14s %-4s n %d masked %5.1f%% | L1 %3.0f%% L2 %3.0f%% L3 %3.0f%% | wall q50/q90 %4.1f/%4.1f s gate s q50 %3.0f | core bytes before mask q50 %6.1f kB, share %4.1f%% | honest UE masked %5.1f%%" % (name, scope, len(r), 100 * r.masked.mean(), *[100 * r[r.ev == l].masked.mean() for l in ("L1", "L2", "L3")], r.wall.quantile(.5), r.wall.quantile(.9), r[r.masked].gate_s.median(), r[r.masked].bytes.median() / 1e3, 100 * (r.bytes.sum() / max(r.total.sum(), 1)), 100 * r.honest_masked.mean()), flush=True)
