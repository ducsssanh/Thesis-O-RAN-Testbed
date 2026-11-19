#!/usr/bin/env python3
"""ON-only tampering on the L2 episodes, the only level whose attack is intermittent. Per factor, tamper of all seconds from the onset against tamper of attack seconds only, per-UE trust, gate restarted per episode.
Control x1. Usage: tamper_on_only_l2.py <rows.parquet>"""
import sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts/ml"))
import tamper_replay as TR
df = pd.read_parquet(sys.argv[1])
runs = {k: g for k, g in df.groupby("run_id")}
a = df[(df.attack_active == 1) & (df.evasion == "L2")]
eps = a.groupby(["run_id", "phase", "supi"]).agg(t0=("t_unix", "min"), t1=("t_unix", "max"), n=("t_unix", "size"), anchor=("anchor_bps", "first")).reset_index()
print("L2 episodes", len(eps), "attack seconds per episode q10/50/90", np.percentile(eps.n, [10, 50, 90]), "span q50", np.median(eps.t1 - eps.t0 + 1), "share of the span active %.2f" % (eps.n / (eps.t1 - eps.t0 + 1)).mean())
GATE = lambda x: (x.rate_ul_kbps * 125 >= 1000) | (x.prof_ul_kbps * 125 >= 1000)
out = []
for f in (1, .1, .33, .8, 1.25, 2, 5):
    for mode, on in (("all", False), ("ON-only", True)):
        if f == 1 and on:
            continue
        R = []
        for e in eps.itertuples():
            d = runs[e.run_id]; d = d[d.phase == e.phase]
            t = TR.tamper(d, e.supi, e.t0, e.t1 + 1, factor=f, on_only=on)
            g = TR.gate(t, "ue")
            me = (t.supi == e.supi) & (t.t_unix >= e.t0)
            hit = t.t_unix[me & g.kpm_masked]
            first = hit.min() if len(hit) else None
            lim = first if first is not None else 10**12
            on_s = me & (t.attack_active == 1)
            R.append(dict(anchor=e.anchor, masked=first is not None, wall=first - e.t0 if first is not None else np.nan, on_before=int((on_s & (t.t_unix < lim)).sum()), bytes=t.attack_bytes_core[me & (t.t_unix < lim)].sum(), total=t.attack_bytes_core[me].sum(),
                          out3=(g.c_t_w[on_s & GATE(t)].abs() > .2).mean(), masked_on=g.kpm_masked[on_s].mean(), other=g.kpm_masked[(t.supi != e.supi) & (t.t_unix >= e.t0)].mean()))
        r = pd.DataFrame(R)
        m = r[r.masked]
        print("x%-5s %-8s masked %5.1f%% | by anchor %s | wall q50/q90 %4.1f %4.1f s | attack seconds before mask q50 %2.0f | core bytes before mask %4.1f%% | ON seconds out 3 s %5.1f%% masked %5.1f%% | other UE masked %.1f%%" % (f, mode, 100 * r.masked.mean(), {int(k / 1e3): round(100 * v.masked.mean()) for k, v in r.groupby("anchor")}, m.wall.quantile(.5) if len(m) else np.nan, m.wall.quantile(.9) if len(m) else np.nan, m.on_before.median() if len(m) else np.nan, 100 * r.bytes.sum() / max(r.total.sum(), 1), 100 * r.out3.mean(), 100 * r.masked_on.mean(), 100 * r.other.mean()), flush=True)
