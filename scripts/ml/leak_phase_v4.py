#!/usr/bin/env python3
"""Leak check through the previous phase (v4): can the 30 s rolling history carry the label of the
phase before the current one?

  .venv-ml/bin/python -I scripts/ml/leak_phase_v4.py --win artifacts/ml/v4

1. Run structure: how often is a phase's previous pNN phase (same run) its UE-mirror (same pair,
   attacker swapped)? AUC of "previous phase label of the same UE" as a predictor of the current label
   (main windows; 0.5 = no information, far from 0.5 either way = exploitable).
2. How much of each main window's rolling history (5/10/30 s) crosses the phase start.
3. GBDT rolling with history CUT at the phase start (roll_cut_v4.npz) vs the normal history, same
   split / threshold / gate / v4_eval. Writes reports/leak_phase_v4.md.
"""
import argparse, json, pathlib, re, sys
import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v4_eval as E
import baseline_v4 as B

SETS = (B.HEADLINE, B.HEADLINE_10, "GBDT rolling URR+prof (UL)", "GBDT rolling RAN-UL", "GBDT rolling URR-UL",
        "GBDT rolling prof-UL", "UL volume (kbps, rolling)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="artifacts/ml/v4")
    ap.add_argument("--out", default="research/datasets/oran_flooding_v4/reports/leak_phase_v4.md")
    a = ap.parse_args()
    w = pathlib.Path(a.win)
    d = dict(np.load(w / "windows_v4.npz"))
    mm = d["kind"] == E.MAIN
    # phase-level table: (run, phase index) -> pair, {ue: label}
    ph = {}
    for r, u, p, pr, y in zip(d["run"][mm], d["ue"][mm], d["phase"][mm], d["pair"][mm], d["y"][mm]):
        j = int(re.match(r"p(\d+)_", p).group(1))
        e = ph.setdefault((r, j), {"pair": pr, "lab": {}})
        e["lab"][u] = int(y)
    mirror_prev, n_prev = 0, 0
    for (r, j), e in ph.items():
        q = ph.get((r, j - 1))
        if q is None:
            continue
        n_prev += 1
        if q["pair"] == e["pair"] and "~" in e["pair"] and all(q["lab"].get(u) == 1 - v for u, v in e["lab"].items()):
            mirror_prev += 1
    # previous-phase label of the same UE as a predictor of the current label
    prev = np.full(len(d["y"]), np.nan)
    for i in np.flatnonzero(mm):
        j = int(re.match(r"p(\d+)_", d["phase"][i]).group(1))
        q = ph.get((d["run"][i], j - 1))
        if q is not None and d["ue"][i] in q["lab"]:
            prev[i] = q["lab"][d["ue"][i]]
    has = mm & ~np.isnan(prev) & (d["pair"] != E.CONTROL)
    auc_prev = roc_auc_score(d["y"][has], prev[has])
    agree = float((prev[has] == d["y"][has]).mean())
    ts = d["t_since"][mm]
    cross = {wn: round(float((ts < wn - 1).mean()), 4) for wn in (5, 10, 30)}
    # GBDT normal vs cut history
    rl, rc = np.load(w / "roll_v4.npz"), np.load(w / "roll_cut_v4.npz")
    names = [str(x) for x in rl["names"]]
    fs = B.feature_sets(names, d)
    test = d["split"] == 2
    rows = {}
    for name in SETS:
        for tag, R in (("normal", rl["R"]), ("cut at phase start", rc["R"])):
            X = R[:, fs[name]]
            p = B.fit_predict(X, d)
            thr = E.val_threshold(p, d)
            rows["%s — %s" % (name, tag)] = E.report(p, d, test, thr, E.val_threshold(p, d, gated=False))
            print(name, tag, rows["%s — %s" % (name, tag)]["roc_auc"], flush=True)
    L = ["# Leak check through the previous phase (v4)\n",
         "## 1. Run structure\n",
         "- Phases whose previous pNN phase in the same run is their UE-mirror (same pair, attacker swapped): "
         "**%d / %d = %.1f%%**." % (mirror_prev, n_prev, 100.0 * mirror_prev / max(n_prev, 1)),
         "- Previous-phase label of the same UE as a predictor of the current label (main windows, control excluded, "
         "n = %d): **AUC %.3f** (agreement %.3f; 0.5 = no information)." % (int(has.sum()), auc_prev, agree),
         "\n## 2. Rolling history crossing the phase start (main windows)\n",
         "| history | share of main windows whose history starts before the phase start |", "|---|---:|"]
    L += ["| %d s | %.3f |" % (k, v) for k, v in cross.items()]
    L += ["\nMain windows end ≥ 12 s into a phase (3 s guard + 10 s window), so the 5/10 s statistics never cross; "
          "only the 30 s statistics do.\n", "## 3. GBDT rolling: normal history vs history cut at the phase start\n",
          "Same split, val threshold (benign FPR 1%), gate and v4_eval. A drop when the history is cut = the model "
          "used pre-phase seconds. (A deployed xApp does not know phase boundaries; the cut is a diagnostic.)\n",
          E.md_table(rows)]
    out = pathlib.Path(a.out)
    out.write_text("\n".join(L) + "\n")
    (w / "leak_phase_v4.json").write_text(json.dumps({"mirror_prev": [mirror_prev, n_prev], "auc_prev_label": auc_prev,
                                                      "agree": agree, "history_cross": cross, "rows": rows}, indent=1, default=str) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
