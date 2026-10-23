#!/usr/bin/env python3
"""Build research/datasets/oran_flooding_v4/reports/model_eval_v4.md from the saved results.

  .venv-ml/bin/python -I scripts/ml/report_model_eval_v4.py [--lstm artifacts/ml/colab-v4/v4_lstm_results]

Inputs: artifacts/ml/v4/{windows_v4.npz, baseline_v4.json, baseline_scores_v4.npz, leak_phase_v4.json} and
the LSTM run dirs (metrics.json + scores.npz per run). Every LSTM number is RE-EVALUATED here with the
current scripts/ml/v4_eval.py from its scores, so LSTM and GBDT go through identical code.
"""
import argparse, json, pathlib, sys
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v4_eval as E

G30, G10 = "GBDT rolling cross-domain UL", "GBDT rolling <=10 s cross-domain UL"
GUP, GUP10 = "GBDT rolling URR+prof (UL)", "GBDT rolling <=10 s URR+prof (UL)"
COLS = ("roc_auc", "pr_auc", "tpr", "pair_macro_auc", "mimicry_auc", "pulsing_auc", "neg_control_auc")


def row(r):
    t = r["ttd"]
    return [r[k] for k in COLS] + [r["fpr"], r["idle_fpr"], r["ungated"]["idle_fpr"], t["detected_within_10s"],
                                   t["detected_within_20s"], t["median_s"], r["benign_phases_alarmed"]]


HDR = ("ROC-AUC", "PR-AUC", "TPR@FPR1%", "pair macro", "mimicry", "pulsing", "icmp control", "FPR", "idle FPR",
       "idle FPR ungated", "det ≤10 s", "det ≤20 s", "TTD med s", "benign phases alarmed")


def fmt(v):
    return "–" if v is None or (isinstance(v, float) and np.isnan(v)) else ("%.3f" % v if isinstance(v, float) else str(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="artifacts/ml/v4")
    ap.add_argument("--lstm", default="artifacts/ml/colab-v4/v4_lstm_results")
    ap.add_argument("--out", default="research/datasets/oran_flooding_v4/reports/model_eval_v4.md")
    a = ap.parse_args()
    w, lr = pathlib.Path(a.win), pathlib.Path(a.lstm)
    d = dict(np.load(w / "windows_v4.npz"))
    base = json.loads((w / "baseline_v4.json").read_text())
    bs = np.load(w / "baseline_scores_v4.npz")
    leak = json.loads((w / "leak_phase_v4.json").read_text())
    test = d["split"] == 2

    def lstm_scores(tag):
        s = np.load(lr / tag / "scores.npz")
        assert (s["y"] == d["y"]).all()
        return s["p"], s["split"]

    def lstm_report(tag, transfer=None):
        p, sp = lstm_scores(tag)
        dd = {**d, "split": sp}
        ftr, fte = None, None
        if transfer:
            P = {n: (x, y) for n, x, y in E.all_transfer_protocols(dd)}
            ftr, fte = P[transfer]
        sel = (sp == 2) if fte is None else (sp == 2) & fte
        return E.report(p, dd, sel, E.val_threshold(p, dd, extra=ftr), E.val_threshold(p, dd, extra=ftr, gated=False)), p, dd

    L = ["# v4 model evaluation — UL-only detector (2026-10-23)\n",
         "Test = 18 held-out runs (split by run, seed 20261023); threshold frozen on val at benign FPR 1%; operating "
         "point = activity gate (10 s mean UL ≥ 50 kbps, fixed); icmp_flood↔icmp_ping = negative control (out of "
         "training, headline and macro). LSTM: 2×64, 10 s window, 17 UL features, trained on Colab T4, re-evaluated "
         "here with the same `v4_eval.py` as the GBDTs. DL features only in the appendix (designed benign DL "
         "feedback is a near-label proxy). Details: `baseline_ul_v4.md`, `leak_phase_v4.md`, `dl_leak_check_v4.md`.\n",
         "## 1. Headline (test)\n", "| model | " + " | ".join(HDR) + " |", "|---|" + "---:|" * len(HDR)]
    lst = {}
    for f in ("ul", "urr_prof_ul"):
        R = np.array([[np.nan if v is None else v for v in row(lstm_report("%s_s%d" % (f, s))[0])] for s in range(3)], float)
        lst[f] = R
        L.append("| **LSTM %s** (3 seeds, mean ± std) | " % f + " | ".join(
            "%.3f ± %.3f" % (m, sd) for m, sd in zip(np.nanmean(R, 0), np.nanstd(R, 0))) + " |")
    for k in (G30, G10, GUP, GUP10, "GBDT rolling RAN-UL", "GBDT rolling URR-UL", "GBDT rolling prof-UL",
              "per-second UL (1 s)", "UL volume (kbps, rolling)", "nuisance (meta only)"):
        L.append("| %s | " % k + " | ".join(fmt(v) for v in row(base["sets"][k]["test"])) + " |")
    # CIs
    ci_l = E.bootstrap_ci(lstm_report("ul_s0")[1], d, test, E.val_threshold(lstm_report("ul_s0")[1], d))
    L += ["", "95%% bootstrap CI by run — LSTM ul seed 0: ROC %s, PR %s, TPR %s, macro %s, icmp %s; GBDT 30 s: ROC %s, TPR %s; "
          "GBDT ≤10 s: ROC %s, TPR %s." % (ci_l["roc_auc"], ci_l["pr_auc"], ci_l["tpr"], ci_l["pair_macro_auc"],
                                         ci_l["neg_control_auc"], base["bootstrap_ci"][G30]["roc_auc"], base["bootstrap_ci"][G30]["tpr"],
                                         base["bootstrap_ci"][G10]["roc_auc"], base["bootstrap_ci"][G10]["tpr"])]
    # val -> test gap
    L += ["", "## 2. Validation → test gap\n", "| model | val ROC-AUC | test ROC-AUC | gap |", "|---|---:|---:|---:|"]
    ens = np.mean([lstm_scores("ul_s%d" % s)[0] for s in range(3)], 0)
    for n, p in (("LSTM ul seed 0", lstm_scores("ul_s0")[0]), ("LSTM ul 3-seed score mean", ens), (G10, bs[G10]), (G30, bs[G30])):
        rv = E.report(p, d, d["split"] == 1, E.val_threshold(p, d))["roc_auc"]
        rt = E.report(p, d, test, E.val_threshold(p, d))["roc_auc"]
        L.append("| %s | %.3f | %.3f | %+.3f |" % (n, rv, rt, rt - rv))
    # paired
    L += ["", "## 3. Paired bootstrap by run (A − B, 95% CI)\n", "| A − B | ΔROC-AUC | ΔPR-AUC | ΔTPR@FPR1% | Δpair macro |",
          "|---|---:|---:|---:|---:|"]
    p0 = lstm_scores("ul_s0")[0]
    pairs = [("LSTM ul s0", p0, G10, bs[G10]), ("LSTM ul s0", p0, G30, bs[G30]), ("LSTM ul 3-seed mean", ens, G10, bs[G10])]
    for an, pa, bn, pb in pairs:
        r = E.paired_bootstrap(pa, pb, d, test, E.val_threshold(pa, d), E.val_threshold(pb, d))
        L.append("| %s − %s | " % (an, bn) + " | ".join("%+.3f [%+.3f, %+.3f]" % (r[k]["diff"], *r[k]["ci"])
                                                       for k in ("roc_auc", "pr_auc", "tpr", "pair_macro_auc")) + " |")
    for k, v in base["paired"].items():
        L.append("| %s | " % k + " | ".join("%+.3f [%+.3f, %+.3f]" % (v[m]["diff"], *v[m]["ci"])
                                           for m in ("roc_auc", "pr_auc", "tpr", "pair_macro_auc")) + " |")
    # shuffle
    sh = [json.loads((lr / ("ul_s%d" % s) / "metrics.json").read_text())["test"]["shuffled_time_roc_auc"] for s in range(3)]
    L += ["", "## 4. Does the LSTM use time order? (time steps permuted inside every test window)\n",
          "LSTM ul: ROC-AUC %.3f ± %.3f → shuffled %.3f ± %.3f (Δ %.3f). The LSTM is nearly order-blind: it behaves as a "
          "bag of 10 seconds." % (np.nanmean(lst["ul"][:, 0]), np.nanstd(lst["ul"][:, 0]), np.mean(sh), np.std(sh),
                                  np.mean(sh) - np.nanmean(lst["ul"][:, 0]))]
    # split seeds
    S = ("roc_auc", "pr_auc", "tpr", "pair_macro_auc", "mimicry_auc", "pulsing_auc", "neg_control_auc")
    A = np.array([[np.nan if lstm_report(t)[0][k] is None else lstm_report(t)[0][k] for k in S] for t in ("ul_s0", "ul_split1", "ul_split2")], float)
    L += ["", "## 5. Split-seed repeat (3 run splits, mean ± std)\n", "| model | " + " | ".join(S) + " |", "|---|" + "---:|" * len(S),
          "| LSTM ul | " + " | ".join("%.3f ± %.3f" % (m, s) for m, s in zip(np.nanmean(A, 0), np.nanstd(A, 0))) + " |"]
    for k in (G30, G10):
        L.append("| %s | " % k + " | ".join("%.3f ± %.3f" % tuple(base["split_seeds"][k][m]) for m in S) + " |")
    # transfers
    L += ["", "## 6. Transfers (UL, gated)\n",
          "clean-a / clean-b: leave-generator-out restricted to the generator cells (family × schedule × load) made by ≥2 "
          "dual-use tools (a: train and test inside them; b: train on everything except tool b, test on b's clean cells). "
          "Those cells hold only dns_flood on the attack side and udp_bidir / benign_benign on the benign side, so their "
          "AUC mixes pairs: read TPR / FPR.\n",
          "| protocol | LSTM ROC | GBDT ROC | LSTM TPR | GBDT TPR | LSTM FPR | GBDT FPR |", "|---|---:|---:|---:|---:|---:|---:|"]
    for i, (n, _, _) in enumerate(E.all_transfer_protocols(d)):
        l = lstm_report("ul_transfer%d" % i, transfer=n)[0]
        g = base["transfers_headline"][n]
        L.append("| %s | %s | %s | %s | %s | %s | %s |" % (n, fmt(l["roc_auc"]), fmt(g["roc_auc"]), fmt(l["tpr"]), fmt(g["tpr"]),
                                                         fmt(l["fpr"]), fmt(g["fpr"])))
    # per pair
    prs = [p for p in base["sets"][G30]["test"]["per_pair_auc"]]
    A = np.array([[np.nan if lstm_report("ul_s%d" % s)[0]["per_pair_auc"].get(p) is None else lstm_report("ul_s%d" % s)[0]["per_pair_auc"][p]
                   for p in prs] for s in range(3)], float)
    L += ["", "## 7. Per-pair AUC (test)\n", "| model | " + " | ".join(prs) + " |", "|---|" + "---:|" * len(prs),
          "| LSTM ul (3 seeds) | " + " | ".join("%.3f" % v for v in np.nanmean(A, 0)) + " |"]
    for k in (G30, G10, GUP):
        L.append("| %s | " % k + " | ".join(fmt(base["sets"][k]["test"]["per_pair_auc"].get(p)) for p in prs) + " |")
    # appendix + leak
    la = lstm_report("all_appendix_s0")[0]
    L += ["", "## 8. Appendix — with DL (not a result: designed DL feedback ≈ label)\n",
          "LSTM all features: ROC %.3f, TPR %.3f, macro %.3f. GBDT rolling incl. DL: ROC %.3f, TPR %.3f." % (
              la["roc_auc"], la["tpr"], la["pair_macro_auc"], base["sets"]["APPENDIX GBDT rolling incl. DL"]["test"]["roc_auc"],
              base["sets"]["APPENDIX GBDT rolling incl. DL"]["test"]["tpr"]),
          "", "## 9. Leak checks (summary)\n",
          "- Indirect DL through RAN UL ratios: overall AUC 0.525 / 0.503 (`dl_leak_check_v4.md`).",
          "- Previous phase: previous-phase label AUC %.3f (inverted), but cutting the rolling history at the phase start "
          "does not lower any GBDT (`leak_phase_v4.md`)." % leak["auc_prev_label"],
          "- Negative control (icmp): ~0.5 for every model using URR/prof; RAN-UL GBDT 0.614 [0.512–0.719] (CI contains 0.5)."]
    cf = pathlib.Path(a.out).with_name("model_eval_v4_conclusions.md")
    L += ["", "## 10. Conclusions\n", cf.read_text().strip() if cf.exists() else "<!-- write model_eval_v4_conclusions.md -->"]
    pathlib.Path(a.out).write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
