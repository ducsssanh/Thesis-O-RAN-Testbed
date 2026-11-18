#!/usr/bin/env python3
"""Example time series of one end-to-end run (advisor, 2026-11-13): attack bytes sent vs at the DN per second and the
attacker's defence level, over the whole run (decision -> limit -> escalation -> block -> expiry -> second attack).
The run is picked by a rule fixed before the campaign results were read: the first kept run in manifest order with L2
and honest KPM (or --run). No smoothing.
Usage (repo root): e2e_timeseries.py --manifest research/datasets/oran_flooding_e2e/manifest [--run le0xx]
                   [--out research/clf/fig/e2e_timeseries.png]"""
import argparse, sys

ap = argparse.ArgumentParser(); ap.add_argument("--manifest", required=True); ap.add_argument("--run")
ap.add_argument("--out", default="research/clf/fig/e2e_timeseries.png")
b = ap.parse_args()
sys.argv = [sys.argv[0], "--manifest", b.manifest]
exec(open("scripts/ml/e2e_report.py").read().split("\ndef fmt(")[0])   # loaders only

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rid = b.run or next(i for i in DESIGN if i in KEPT and DESIGN[i].get("evasion") == "L2" and DESIGN[i]["case"] == "honest")
r = DESIGN[rid]; meta, ev, clf, audit, flows, ph, dn = load(KEPT[rid])
att = r["attacker"]; supi = meta["ues"][att]["supi"]; ip = ue_ip(meta, att)
T0, T1 = ph["p0"][0], ph["p7"][1]
sent, got = {}, {}
for f in flows:
    if f["ue"] == att and f.get("role") == "attack":
        for t, v in sent_flow(f).items(): sent[t] = sent.get(t, 0) + v
        for t, v in dn_flow(dn, ip, f).items(): got[t] = got.get(t, 0) + v
ts = list(range(int(T0), int(T1)))
x = [t - T0 for t in ts]
ks = lambda d: [d.get(t, 0) * 8 / 1e3 for t in ts]   # kbit/s
steps = level_at(ev, supi)
lv = [lvl(steps, t + .5) for t in ts]

INK, INK2, GRID, AX = "#0b0b0b", "#52514e", "#e6e5e0", "#b5b4ae"
C1, C2 = "#2a78d6", "#eb6834"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": AX, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})
fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 4.8), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
for p in ("p1", "p2", "p6"):
    for ax in (a1, a2):
        ax.axvspan(ph[p][0] - T0, ph[p][1] - T0, color="#f0efec", lw=0, zorder=0)
for p in ("p1", "p6"):
    a1.text(ph[p][0] - T0 + 3, 1.0, "first attack" if p == "p1" else "second attack", transform=a1.get_xaxis_transform(),
            va="top", fontsize=8, color=INK2)
a1.plot(x, ks(sent), color=C1, lw=1.5, label="sent by the attacker", zorder=3)
a1.plot(x, ks(got), color=C2, lw=1.5, label="reaching the DN", zorder=4)
lim = 1.25 * a.cap_ul_kbps
a1.axhline(lim, color=INK2, lw=.8, ls=(0, (4, 3)), zorder=2)
a1.text((ph["p2"][1] + ph["p6"][0]) / 2 - T0, lim, "1.25 x UPF cap = %.0f kbit/s" % lim, va="bottom", ha="center", fontsize=7.5, color=INK2)
a1.set_ylabel("attack UL (kbit/s)")
a1.set_ylim(bottom=0)
a1.legend(loc="upper right", bbox_to_anchor=(1, .93), frameon=False, fontsize=8)
a1.set_title("%s: L2 flood, honest KPM, attacker %s; attack bytes per second and the defence level" % (rid, att),
             loc="left", fontsize=10, color=INK)
a2.step(x, lv, where="post", color=C1, lw=1.5)
a2.set_yticks([0, 1, 2, 3, 4], ["0", "1", "2 limit", "3 block", "4"]); a2.set_ylim(-.3, 4.3)
a2.set_ylabel("defence level")
a2.set_xlabel("time since the start of the run (s)")
a2.text(x[-1], 4.3, "limit = RAN slice 5% PRB + UPF 32 kbit/s; block = RAN slice 1% PRB + UPF 0", va="top", ha="right", fontsize=7.5, color=INK2)
for ax in (a1, a2):
    ax.grid(True, axis="y", color=GRID, lw=.6); ax.spines[["top", "right"]].set_visible(False); ax.set_xlim(0, x[-1])
fig.tight_layout()
fig.savefig(b.out, dpi=200)
print("wrote", b.out, "run", rid)
