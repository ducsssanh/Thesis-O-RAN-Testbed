#!/usr/bin/env python3
"""Paper/thesis figures of the live cross-domain defence (v5, stage B), static PDF + PNG.

  .venv-ml/bin/python -I scripts/ml/figures_v5.py --eval <reports dir> --run <one live run dir> [--out DIR]

Cells from live_results_v5.json (clean units: phases that started with a carried-over L3 dropped) when
present, else live_eval_v5.json (all units).

(a) per scenario, configuration comparison: attack phases blocked (L3) and benign phases wrongly
    blocked (L3; framed benign for kpm_frame), 95% run-bootstrap CIs, one panel per measure
(b) tamper-factor sensitivity: offline replay sweep (lines) with the live points (markers)
(c) timeline of one live run: attacker KPM UL vs URR UL, integrity alarm / kpm_trust, xApp level,
    attacker packets at the DN - stacked panels on a shared time axis (one y-scale each)
(The offline ML table (GBDT vs LSTM, cross-domain vs single domain) is model_eval_v4.md.)
Colors: categorical slots 1-6 in fixed order per configuration (validated palette, dataviz skill).
"""
import argparse, json, pathlib
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1].parent
CONFIGS = ["rules-v1", "ran-only", "core-only", "xd-naive", "xd-trust-v1", "xd-trust-v2"]
COLOR = dict(zip(CONFIGS, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]))
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LABEL = {"rules-v1": "Fair-use rules", "ran-only": "RAN-only", "core-only": "Core-only", "xd-naive": "Naive cross-domain",
         "xd-trust-v1": "Trust-weighted (v1)", "xd-trust-v2": "Trust-weighted (proposed)"}
SCN_LABEL = {"honest": "Honest", "kpm_hide_x0.1": "KPM hide\n×0.1", "kpm_hide_x0.33": "KPM hide\n×0.33",
             "kpm_frame_x2": "KPM frame\n×2", "kpm_frame_x5": "KPM frame\n×5", "core_outage": "Core telemetry\noutage"}
OFF_CFG = {"ran-only": "RAN-only (xApp KPM)", "core-only": "core-only (5GC)", "xd-naive": "cross-domain naive",
           "xd-trust-v1": "cross-domain trust-weighted", "xd-trust-v2": "cross-domain trust-weighted v2"}

plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "legend.frameon": False})


def save(fig, out, name):
    for ext in ("pdf", "png"):
        fig.savefig(out / ("%s.%s" % (name, ext)), dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_a(res, out):
    scen = [s for s in ("honest", "kpm_hide_x0.1", "kpm_hide_x0.33", "kpm_frame_x2", "kpm_frame_x5", "core_outage") if s in res]
    panels = [("attack_L3", "ci_attack_L3", "attack phases blocked"),
              ("benign_L3", "ci_benign_L3", "benign phases wrongly blocked\n(KPM frame: the framed UE)")]
    fig, axs = plt.subplots(len(panels), 1, figsize=(7.2, 5.2), sharex=True)
    w = 0.8 / len(CONFIGS)
    for ax, (k, ck, title) in zip(axs, panels):
        for j, c in enumerate(CONFIGS):
            xs, ys, lo, hi = [], [], [], []
            for i, s in enumerate(scen):
                r = res[s].get(c)
                if not r:
                    continue
                kk, cc = (("framed_benign_L3", "ci_framed_benign_L3") if k == "benign_L3" and "frame" in s else (k, ck))
                v, ci = r.get(kk), r.get(cc)
                if v is None:
                    continue
                xs.append(i - 0.4 + w * (j + 0.5)); ys.append(v)
                lo.append(v - ci[0] if ci else 0); hi.append(ci[1] - v if ci else 0)
            # a measured 0 is drawn as a thin baseline mark (0 must not read as "missing")
            ax.bar(xs, [max(y, 0.012) for y in ys], bottom=[-0.006 if y < 0.012 else 0 for y in ys], width=w * 0.86, color=COLOR[c], edgecolor=SURF, linewidth=1)
            ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=0.8, capsize=1.5)
        ax.set_ylim(-0.04, 1.05)                       # room under 0 for the zero marks
        ax.axhline(0, color=INK2, linewidth=0.8, zorder=0)
        ax.spines["bottom"].set_visible(False)
        ax.set_ylabel(title, fontsize=8)
    axs[-1].set_xticks(range(len(scen)), [SCN_LABEL.get(s, s) for s in scen])
    from matplotlib.patches import Patch
    axs[0].legend(handles=[Patch(color=COLOR[c], label=LABEL[c]) for c in CONFIGS], ncol=3, loc="lower center",
                  bbox_to_anchor=(0.5, 1.02), fontsize=7.5)
    save(fig, out, "fig_a_live_configs")


def fig_b(res, out):
    off = json.loads((ROOT / "artifacts/ml/v4/fusion/fusion_results.json").read_text())["results"]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.8))
    sides = [("kpm_hide", [0.1, 0.2, 0.33, 0.5], "attack_blocked_L3", "attack_L3", "attack phases blocked", "KPM hide factor (attacker's KPM × f)"),
             ("kpm_frame", [2.0, 3.0, 5.0, 10.0], "framed_benign_blocked_L3", "framed_benign_L3", "framed benign UE blocked", "KPM frame factor (benign KPM × f)")]
    for ax, (sc, fs, ok, lk, ylab, xlab) in zip(axs, sides):
        for c in ("ran-only", "xd-naive", "xd-trust-v2"):
            ys = [(off.get("%s x%g" % (sc, f)) or {}).get(OFF_CFG[c], {}).get(ok) for f in fs]
            ax.plot(fs, ys, color=COLOR[c], linewidth=2, label="%s (replay)" % LABEL[c])
            live = [(f, (res.get("%s_x%g" % (sc, f)) or {}).get(c, {}).get(lk)) for f in fs]
            live = [(f, v) for f, v in live if v is not None]
            if live:
                ax.plot(*zip(*live), "o", color=COLOR[c], markersize=7, markeredgecolor=SURF, markeredgewidth=1.5,
                        label="%s (live)" % LABEL[c])
        ax.set_xscale("log")
        ax.set_xticks(fs, [("%g" % f) for f in fs])
        ax.minorticks_off()
        ax.set_ylim(-0.03, 1.05)
        ax.set_xlabel(xlab); ax.set_ylabel(ylab, fontsize=8)
    axs[1].legend(fontsize=7, loc="center left", bbox_to_anchor=(1.02, 0.5))
    fig.tight_layout()
    save(fig, out, "fig_b_tamper_sensitivity")


def fig_c(rd, out):
    rd = pathlib.Path(rd)
    m = json.loads((rd / "run.json").read_text())
    sc = [json.loads(l) for l in (rd / "defense/sidecar.jsonl").read_text().splitlines() if '"row"' in l]
    tl = [json.loads(l) for l in (rd / "defense/state_timeline.jsonl").read_text().splitlines()]
    dn = pd.read_csv(rd / "dataplane/dn_per_second.csv")
    t0 = m["t_start"]
    ph = [p for p in m["phases"] if p["name"].startswith("p")]
    # the attacker of the first attack phase
    atk_ue = json.loads((rd / "traffic/flows.json").read_text())
    atk_ue = next((f["ue"] for f in atk_ue if f["phase"] == ph[0]["name"] and f.get("role") == "attack"), "ue1")
    supi, ip = m["ues"][atk_ue]["supi"], m["ues"][atk_ue]["ip_history"][0][1]
    s = [r for r in sc if r["supi"] == supi]
    t = np.array([r["ts"] - t0 for r in s])
    fig, axs = plt.subplots(4, 1, figsize=(7.2, 6.0), sharex=True, gridspec_kw={"height_ratios": [2, 1, 1, 1.4]})
    g = lambda k: np.array([np.nan if r["row"].get(k) is None else r["row"][k] for r in s], float)
    axs[0].plot(t, g("rate_ul_kbps"), color=COLOR["ran-only"], linewidth=1.5, label="KPM UL (RAN, as reported)")
    axs[0].plot(t, g("urr_ul_kbps"), color=COLOR["core-only"], linewidth=1.5, label="URR UL (core)")
    axs[0].set_ylabel("kbit/s"); axs[0].legend(fontsize=7, ncol=2, loc="upper right")
    axs[1].plot(t, [r["kt"] for r in s], color=INK2, linewidth=1.5, label="KPM trust")
    integ = np.array([r["integrity"] for r in s])
    axs[1].fill_between(t, 0, 1, where=integ, color=COLOR["xd-naive"], alpha=0.35, step="mid", linewidth=0, label="integrity alarm")
    axs[1].set_ylim(-0.05, 1.05); axs[1].legend(fontsize=7, ncol=2, loc="upper right")
    lt = [(r["t"] - t0, (r["ues"].get(supi) or {}).get("level") or 0) for r in tl]
    axs[2].step(*zip(*lt), where="post", color=COLOR["xd-trust-v2"], linewidth=2)
    axs[2].set_yticks([0, 1, 3], ["none", "isolate", "block"]); axs[2].set_ylabel("xApp action")
    d = dn[(dn.ue_ip == ip) & (dn.dir == "ul")]
    axs[3].bar(d.t - t0, d.pkts, width=0.9, color=COLOR["rules-v1"], linewidth=0)
    axs[3].set_ylabel("UL pkt/s at DN"); axs[3].set_xlabel("time since run start (s)")
    for ax in axs:
        for p in ph:
            ax.axvspan(p["t_start"] - t0, p["t_end"] - t0, color=GRID, alpha=0.35, linewidth=0, zorder=0)
    for p in ph:
        axs[0].text((p["t_start"] + p["t_end"]) / 2 - t0, 1.0, p["name"], transform=axs[0].get_xaxis_transform(),
                    ha="center", va="bottom", fontsize=7, color=INK2)
    fig.suptitle("KPM hidden ×0.1, %s — UE %s (attacker in the first phase)" % (LABEL.get(m.get("config"), m.get("config")), atk_ue[-1]),
                 fontsize=9, color=INK) if m.get("scenario") == "kpm_hide_x0.1" else \
        fig.suptitle("%s / %s — UE %s" % (m.get("scenario"), LABEL.get(m.get("config"), m.get("config")), atk_ue[-1]), fontsize=9, color=INK)
    fig.tight_layout()
    save(fig, out, "fig_c_timeline")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True, help="dir with live_eval_v5.json")
    ap.add_argument("--run", help="one live run dir for the timeline")
    ap.add_argument("--out", default=str(ROOT / "research/datasets/oran_flooding_v5_live/reports/figures"))
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    clean = pathlib.Path(a.eval) / "live_results_v5.json"      # primary analysis: clean units (live_extra_v5.py)
    if clean.exists():
        res = {}
        for k, v in json.loads(clean.read_text())["cells"].items():
            sc, c = k.split("/")
            res.setdefault(sc, {})[c] = v["clean"]
    else:
        res = json.loads((pathlib.Path(a.eval) / "live_eval_v5.json").read_text())["results"]
    fig_a(res, out)
    fig_b(res, out)
    if a.run:
        fig_c(a.run, out)
    print("figures in", out)


if __name__ == "__main__":
    main()
