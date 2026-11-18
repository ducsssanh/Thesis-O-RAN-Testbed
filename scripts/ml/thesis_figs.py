#!/usr/bin/env python3
"""Figures of the thesis that are drawn from recorded data and reports (2026-11-15, advisor's list of figures).
  gate       KPM against the core per second and the gate statistic c_t,w, one column per KPM case
             (honest, hiding x0.33, framing x2, mimicry), from the defence-off runs of the main design;
             tampering and the gate are those of the training replay (scripts/ml/tamper_replay.py)
  far-band   live blind test, false alarms per benign UE-hour by band with exact Poisson intervals
             (numbers of research/clf/LIVE6_benign_fa.txt, "pooled")
  e2e-bytes  end-to-end campaign, attack bytes that reached the DN by the attacker's level
             (numbers of research/clf/E2E_thesis_extra.txt, section 2)
The curves of detection against the false-alarm rate are drawn by far_curves_fig.py --thesis.
Usage (repo root, .venv-ml): thesis_figs.py --out <figures dir> [--only gate far-band e2e-bytes]"""
import argparse, pathlib, re, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import chi2

ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--only", nargs="*")
a = ap.parse_args()
OUT = pathlib.Path(a.out); OUT.mkdir(parents=True, exist_ok=True)
INK, INK2, GRID, AXIS = "#0b0b0b", "#52514e", "#e6e5e0", "#b5b4ae"
SLOT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]        # categorical slots 1-4, validated in this order (dataviz validate_palette.js, light)
plt.rcParams.update({"font.family": "serif", "font.serif": ["TeX Gyre Termes", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
                     "mathtext.fontset": "stix", "pdf.fonttype": 42, "font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 9, "axes.titlecolor": INK})
want = lambda k: not a.only or k in a.only


def clean(ax):
    ax.grid(True, color=GRID, lw=.6, zorder=0); ax.spines[["top", "right"]].set_visible(False); ax.set_axisbelow(True)


def pois(k, T):
    return (chi2.ppf(.025, 2 * k) / 2 / T if k else 0.0), chi2.ppf(.975, 2 * k + 2) / 2 / T


# ---------------------------------------------------------------- gate
if want("gate"):
    import pandas as pd
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import tamper_replay as TR
    df = pd.read_parquet("research/datasets/oran_flooding_twin/rows.parquet").sort_values(["run_id", "phase", "supi", "t_unix"]).reset_index(drop=True)
    rng = np.random.default_rng(20261115)
    runs = {r: g for r, g in df.groupby("run_id", sort=False)}
    CASES = [("honest", "Honest KPM"), ("hide", "Hiding $\\times0.33$"), ("frame", "Framing $\\times2$"), ("mimic", "Mimicry")]
    pts = {k: [] for k, _ in CASES}

    def collect(key, d, supi, t0):
        g = TR.gate(d, "ue")
        m = ((d.supi == supi) & (d.t_unix >= t0)).to_numpy()
        kpm = d.rate_ul_kbps.to_numpy(float)[m]
        core = np.maximum(d.prof_ul_bytes.to_numpy(float) - TR.BETA * d.prof_ul_pkts.to_numpy(float), 0.0)[m] / d.prof_window_s.to_numpy(float)[m] / 125.0
        cw = g.c_t_w.to_numpy()[m]
        ok = ~(np.isnan(kpm) | np.isnan(core) | np.isnan(cw)) & ~((kpm <= 0) & (core <= 0))
        pts[key].append(np.c_[core[ok], kpm[ok], cw[ok]])

    for (run, phase), ph in df.groupby(["run_id", "phase"], sort=False):
        first_s = int(ph.t_unix.min())
        for s in ph.supi.unique():
            t0 = first_s + int(rng.integers(0, 15))            # start of the tampering, drawn as in the training replay
            collect("honest", ph, s, t0)
            collect("hide", TR.tamper(ph, s, t0, 10**12, factor=.33), s, t0)
            collect("frame", TR.tamper(ph, s, t0, 10**12, factor=2), s, t0)
            g0 = ph[ph.supi == s]
            pool = [g for (p2, u2), g in runs[run][(runs[run].phase != phase) & (runs[run].supi != s)].groupby(["phase", "supi"])
                    if (g.role == "benign").all() and (g.client_role == "").all() and len(g) >= len(g0)]
            if pool:                                           # mimicry: the KPM of s replaced by a benign KPM trace of another phase
                donor = pool[int(rng.integers(len(pool)))].sort_values("t_unix")
                collect("mimic", TR.tamper(ph, s, first_s, 10**12, donor=donor), s, first_s)
    pts = {k: np.vstack(v) for k, v in pts.items()}
    lo, hi = TR.LO, TR.HI
    fig, ax = plt.subplots(2, 4, figsize=(6.3, 3.9), gridspec_kw=dict(height_ratios=[1.25, 1]))
    xs = np.array([1, 3000.0]); note = []
    for j, (k, title) in enumerate(CASES):
        P = pts[k]; act = (P[:, 0] > 0) & (P[:, 1] > 0)
        sub = P[act]; sub = sub[rng.choice(len(sub), min(4000, len(sub)), replace=False)]
        t = ax[0, j]
        t.fill_between(xs, xs * np.exp(lo), xs * np.exp(hi), color="#8c8b85", alpha=.28, lw=0, zorder=1)
        t.plot(xs, xs, color=INK2, lw=.7, zorder=2)
        t.scatter(sub[:, 0], sub[:, 1], s=2.2, color=SLOT[0], alpha=.35, lw=0, zorder=3, rasterized=True)
        t.set_xscale("log"); t.set_yscale("log"); t.set_xlim(1, 3000); t.set_ylim(1, 3000); t.set_aspect("equal")
        t.set_title(title, loc="left"); clean(t)
        t.set_xlabel("core uplink (kbit/s)")
        if j == 0:
            t.set_ylabel("KPM uplink (kbit/s)")
        else:
            t.set_yticklabels([])
        b = ax[1, j]
        inside = np.mean((P[:, 2] >= lo) & (P[:, 2] <= hi))
        b.axvspan(lo, hi, color="#8c8b85", alpha=.28, lw=0, zorder=1)
        b.hist(np.clip(P[:, 2], -3, 3), bins=np.linspace(-3, 3, 61), weights=np.full(len(P), 100.0 / len(P)), color=SLOT[0], zorder=3)
        b.set_xlim(-3, 3); b.set_xticks([-2, 0, 2]); clean(b)
        b.set_xlabel("$c_{t,w}$")
        b.set_title("%.1f%% inside the band" % (100 * inside), loc="left", fontsize=8, color=INK2)
        if j == 0:
            b.set_ylabel("share of seconds (%)")
        note.append("%s: n = %d, %.1f%% of seconds with |c_t,w| <= %.1f" % (k, len(P), 100 * inside, hi))
    ym = max(x.get_ylim()[1] for x in ax[1]);
    for x in ax[1]: x.set_ylim(0, ym)
    for x in ax[1, 1:]: x.set_yticklabels([])
    fig.tight_layout(w_pad=.6, h_pad=.9)
    fig.savefig(OUT / "fig_gate.pdf", dpi=300); print("fig_gate.pdf |", " | ".join(note))

# ---------------------------------------------------------------- false alarms per band
if want("far-band"):
    txt = pathlib.Path("research/clf/LIVE6_benign_fa.txt").read_text().split("pooled")[1]
    T = {}
    for tier, key in (("rate limit", "rate"), ("block", "block")):
        line = next(l for l in txt.splitlines() if l.strip().startswith(tier))
        tot = re.search(r"(\d+) false alarms /\s*([\d.]+) benign", line)
        T[key] = dict(all=(int(tot.group(1)), float(tot.group(2))), **{b: (int(k), float(h)) for b, k, h in re.findall(r"(P\d) (\d+)/([\d.]+)h", line)})
    fig, ax = plt.subplots(1, 2, figsize=(6.3, 2.75))
    for a_, (key, title, budget) in zip(ax, (("rate", "Rate-limit tier", 2.0), ("block", "Block tier", 0.5))):
        names = ["P1", "P2", "P3", "P4", "all"]
        for i, n in enumerate(names):
            k, h = T[key][n]; r = k / h; lo, hi = pois(k, h)
            a_.plot([i, i], [lo, hi], color=SLOT[0], lw=2, solid_capstyle="round", zorder=3)
            a_.plot(i, r, "o", ms=6.5, color=SLOT[0], mec="white", mew=1.4, zorder=4)
            a_.annotate("%.2f" % r if k else "0", (i, r), xytext=(8, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
            a_.annotate("%d / %.1f h" % (k, h), (i, 0), xytext=(0, -24), textcoords="offset points", ha="center", va="top", fontsize=7.5, color=INK2, annotation_clip=False)
        a_.axhline(budget, color=INK2, lw=.9, ls=(0, (4, 3)), zorder=2)
        a_.annotate("budget %g" % budget, (-.45, budget), xytext=(0, 3), textcoords="offset points", fontsize=8, color=INK2)
        a_.axvline(3.5, color=AXIS, lw=.6)
        a_.set_xticks(range(5)); a_.set_xticklabels(["P1", "P2", "P3", "P4", "All"]); a_.set_xlim(-.5, 4.6); a_.set_ylim(0, None)
        a_.set_title(title, loc="left"); clean(a_); a_.grid(axis="x", visible=False)
    ax[0].set_ylabel("false alarms per benign UE-hour")
    fig.tight_layout(w_pad=1.6); fig.subplots_adjust(bottom=.24)
    fig.savefig(OUT / "fig_far_band.pdf"); print("fig_far_band.pdf", T)

# ---------------------------------------------------------------- end-to-end bytes at the DN by level
if want("e2e-bytes"):
    rep = pathlib.Path("research/clf/E2E_thesis_extra.txt").read_text().split("\n2. ")[1].split("\n3. ")[0]
    rows = []
    for blk in rep.split("attack p")[1:]:
        head = re.search(r"sent ([\d.]+) kB, at the DN ([\d.]+) kB \(([\d.]+)% stopped\)", blk)
        seg = [float(x) for x in re.findall(r"\s([\d.]+) kB\s+[\d.]+% of the bytes", blk)]
        rows.append((float(head.group(1)), float(head.group(2)), float(head.group(3)), seg))
    labels = ["First attack", "Repeated attack"]
    segn = ["before the first decision", "at the limit level", "at the block level", "after the level expired"]
    fig, a_ = plt.subplots(figsize=(6.3, 2.3))
    for i, (sent, dn, stop, seg) in enumerate(rows):
        y = 1 - i; x = 0.0
        for j, v in enumerate(seg):
            if v <= 0:
                continue
            a_.barh(y, v, left=x, height=.5, color=SLOT[j], edgecolor="#fcfcfb", lw=1.4, zorder=3)
            if v / dn > .08:
                a_.text(x + v / 2, y, "%.0f kB (%.0f%%)" % (v, 100 * v / dn), ha="center", va="center", fontsize=8, color="white" if j < 2 else INK, zorder=4)
            x += v
        small = "; ".join("%s %.0f kB" % (segn[j].split(" the ")[-1].replace("level expired", "expiry").replace(" level", ""), v) for j, v in enumerate(seg) if 0 < v / dn <= .08)
        a_.text(x + 25, y, "%.0f kB reach the DN of %.0f kB sent (%.1f%% stopped)%s" % (dn, sent, stop, ("\n" + small) if small else ""),
                va="center", fontsize=8, color=INK)
    a_.set_yticks([1, 0]); a_.set_yticklabels(labels); a_.set_ylim(-.55, 1.75)
    a_.set_xlim(0, max(r[1] for r in rows) * 1.95); a_.set_xlabel("attack bytes that reached the data network (kB)")
    clean(a_); a_.grid(axis="y", visible=False)
    from matplotlib.patches import Patch
    a_.legend(handles=[Patch(color=SLOT[j], label=segn[j]) for j in range(4)], loc="upper center", bbox_to_anchor=(.5, 1.2), ncol=4, frameon=False,
              fontsize=7.8, handlelength=1.1, columnspacing=1.2)
    fig.tight_layout()
    fig.savefig(OUT / "fig_e2e_bytes.pdf"); print("fig_e2e_bytes.pdf", rows)
