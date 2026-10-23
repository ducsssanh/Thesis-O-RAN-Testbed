#!/usr/bin/env python3
"""UL-only GBDT baselines + robustness on the v4 windows (local, CPU, a few minutes).

  .venv-ml/bin/python -I scripts/ml/baseline_v4.py --win artifacts/ml/v4

Detector is UL-only by design (threat model = UL flood from the UE; the testbed's benign DL is a
designed feedback channel and a near-label proxy). DL features appear only in the appendix row.
All models: HistGradientBoosting, trained on TRAIN main windows with the negative-control pair
(icmp_flood~icmp_ping) excluded, threshold frozen on VAL at benign FPR 1%, reported on TEST with
scripts/ml/v4_eval.py (same code the LSTM uses).
Feature sets (from roll_v4.npz: the 1 s value + causal mean/std/slope/max over 5/10/30 s):
  nuisance (meta) | UL volume (kbps, rolling) | per-second UL (1 s values only)
  GBDT rolling: RAN-UL | RAN-UL without PRB | URR-UL | prof-UL | URR+prof (UL) | cross-domain UL
  appendix: cross-domain incl. DL
Robustness (cross-domain UL rolling = the LSTM's direct competitor, plus every set where cheap):
  bootstrap 95% CI by run; 3 run-split seeds (mean ± std); leave-UE-out, leave-generator-out,
  victim_mode transfer.
"""
import argparse, json, pathlib, sys
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v4_eval as E

UL_KBPS = ("rate_ul_kbps", "thp_ul_kbps", "urr_ul_kbps", "prof_ul_kbps")
RAN_UL = ("rate_ul_kbps", "thp_ul_kbps", "prb_ul_pct", "cell_prb_ul_pct")
HEADLINE = "GBDT rolling cross-domain UL"
HEADLINE_10 = "GBDT rolling <=10 s cross-domain UL"          # same history as the 10 s LSTM window
PAIRED = ("GBDT rolling URR+prof (UL)", "GBDT rolling RAN-UL", "GBDT rolling URR-UL", "GBDT rolling prof-UL", HEADLINE_10)
SPLIT_SEEDS = (None, 1, 2)                     # None = the stored split (same as the LSTM package)


def base_of(n):
    return n.split("@")[0]


def nuisance_matrix(d):
    ue = (d["ue"] == "ue2").astype(np.float32)
    vm = np.where(d["victim"] == "silent", 1.0, np.where(d["victim"] == "responsive", 0.0, np.nan))
    return np.stack([ue, d["load"], vm, d["t_since"]], 1).astype(np.float32)


def feature_sets(names, d):
    ul = lambda c: "_dl" not in c
    pick = lambda f: np.array([i for i, n in enumerate(names) if f(n)])
    return {
        "nuisance (meta only)": nuisance_matrix(d),
        "UL volume (kbps, rolling)": pick(lambda n: base_of(n) in UL_KBPS),
        "per-second UL (1 s)": pick(lambda n: n.endswith("@1") and ul(n)),
        "GBDT rolling RAN-UL": pick(lambda n: base_of(n) in RAN_UL),
        "GBDT rolling RAN-UL no PRB": pick(lambda n: base_of(n) in ("rate_ul_kbps", "thp_ul_kbps")),
        "GBDT rolling URR-UL": pick(lambda n: base_of(n).startswith("urr_ul")),
        "GBDT rolling prof-UL": pick(lambda n: base_of(n).startswith("prof_ul")),
        "GBDT rolling URR+prof (UL)": pick(lambda n: base_of(n).startswith(("urr_ul", "prof_ul"))),
        HEADLINE: pick(lambda n: ul(base_of(n))),
        HEADLINE_10: pick(lambda n: ul(base_of(n)) and "@30_" not in n),
        "GBDT rolling <=10 s URR+prof (UL)": pick(lambda n: base_of(n).startswith(("urr_ul", "prof_ul")) and "@30_" not in n),
        "APPENDIX GBDT rolling incl. DL": pick(lambda n: True),
    }


def fit_predict(X, d, extra=None, seed=0):
    tr = E.train_mask(d, extra)
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1, random_state=seed)
    clf.fit(X[tr], d["y"][tr])
    return clf.predict_proba(X)[:, 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="artifacts/ml/v4")
    ap.add_argument("--fpr", type=float, default=0.01)
    ap.add_argument("--boot", type=int, default=1000)
    a = ap.parse_args()
    w = pathlib.Path(a.win)
    d = dict(np.load(w / "windows_v4.npz"))
    rl = np.load(w / "roll_v4.npz")
    R, names = rl["R"], [str(x) for x in rl["names"]]
    sets = {k: (v if v.ndim == 2 else R[:, v]) for k, v in feature_sets(names, d).items()}
    test = d["split"] == 2
    out, ci, seeds, scores, thrs = {}, {}, {}, {}, {}
    for name, X in sets.items():
        p = fit_predict(X, d)
        thr = E.val_threshold(p, d, a.fpr)
        scores[name], thrs[name] = p, thr
        out[name] = {"n_features": int(X.shape[1]),
                     "test": E.report(p, d, test, thr, E.val_threshold(p, d, a.fpr, gated=False))}
        ci[name] = E.bootstrap_ci(p, d, test, thr, B=a.boot)
        # split-seed repeat
        rows = []
        for s in SPLIT_SEEDS:
            dd = d if s is None else {**d, "split": E.split_from_windows(d, 20261023 + 100 * s)}
            ps = p if s is None else fit_predict(X, dd)
            rs = E.report(ps, dd, dd["split"] == 2, E.val_threshold(ps, dd, a.fpr))
            rows.append([rs[k] if rs[k] is not None else np.nan for k in ("roc_auc", "pr_auc", "tpr", "pair_macro_auc",
                                                                           "mimicry_auc", "pulsing_auc", "neg_control_auc")])
        R3 = np.array(rows, float)
        seeds[name] = {k: [round(float(np.nanmean(R3[:, j])), 4), round(float(np.nanstd(R3[:, j])), 4)]
                       for j, k in enumerate(("roc_auc", "pr_auc", "tpr", "pair_macro_auc", "mimicry_auc",
                                              "pulsing_auc", "neg_control_auc"))}
        t = out[name]["test"]
        print("%-32s ROC %s PR %s TPR %s macro %s ctrl %s" % (name, t["roc_auc"], t["pr_auc"], t["tpr"],
              t["pair_macro_auc"], t["neg_control_auc"]), flush=True)
    np.savez_compressed(w / "baseline_scores_v4.npz", **{k: v for k, v in scores.items()},
                        **{"thr::" + k: np.array(v) for k, v in thrs.items()})
    paired = {"%s - %s" % (HEADLINE, k): E.paired_bootstrap(scores[HEADLINE], scores[k], d, test, thrs[HEADLINE], thrs[k],
                                                           B=a.boot) for k in PAIRED}
    # transfers for the headline set (+ clean leave-generator-out: a = train+test inside the cells made by
    # >=2 dual-use tools; b = train on everything except tool b, test only on b's clean cells)
    X = sets[HEADLINE]
    transfers = {}
    for tname, ftrain, ftest in E.all_transfer_protocols(d):
        p = fit_predict(X, d, extra=ftrain)
        thr = E.val_threshold(p, d, a.fpr, extra=ftrain)
        transfers[tname] = E.short(E.report(p, d, test & ftest, thr))
        print("%-32s %s" % (tname, transfers[tname]), flush=True)
    res = {"sets": out, "bootstrap_ci": ci, "split_seeds": seeds, "transfers_headline": transfers, "paired": paired,
           "fpr_target": a.fpr, "boot": a.boot}
    (w / "baseline_v4.json").write_text(json.dumps(res, indent=1) + "\n")
    main_sets = {k: v["test"] for k, v in out.items() if not k.startswith("APPENDIX")}
    L = ["# v4 UL-only baselines (test = %d held-out runs; threshold frozen on val at benign FPR %g; "
         "operating point = activity gate UL >= 50 kbps, ungated in parentheses)\n"
         % (len(np.unique(d["run"][test])), a.fpr),
         "Negative control icmp_flood~icmp_ping is excluded from training, headline and macro; its AUC is "
         "reported alone (expected ~0.5). Brackets = 95% bootstrap CI by run.\n",
         E.md_table(main_sets, ci), "",
         "## Split-seed repeat (3 run splits, mean ± std)\n",
         "| model | ROC-AUC | PR-AUC | TPR@FPR1% | pair macro | mimicry | pulsing | icmp control |",
         "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k, v in seeds.items():
        L.append("| %s | " % k + " | ".join("%.3f ± %.3f" % tuple(v[m]) for m in
                 ("roc_auc", "pr_auc", "tpr", "pair_macro_auc", "mimicry_auc", "pulsing_auc", "neg_control_auc")) + " |")
    L += ["", "## Transfers (%s; gated operating point)\n" % HEADLINE,
          "clean-a: train and test inside the generator cells (family × schedule × load) produced by ≥2 dual-use tools; "
          "clean-b: train on everything except tool b, test only on b's clean cells. In the design every attack "
          "(family, schedule) is produced by ONE tool (udp_flood: cbr=iperf, fgn=pacer, mmpp2=hping), so the plain "
          "leave-generator-out also removes a schedule; the clean cells hold only dns_flood (MAL, pacer/hping) and "
          "udp_bidir / benign_benign (BEN), so their AUC mixes pairs — read TPR / FPR.\n",
          "| protocol | n | ROC-AUC | PR-AUC | TPR | FPR | pair macro | mimicry | pulsing |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, v in transfers.items():
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (k, v["n_main"], v["roc_auc"], v["pr_auc"], v["tpr"],
                 v["fpr"], v["pair_macro_auc"], v["mimicry_auc"], v["pulsing_auc"]))
    L += ["", "## Paired bootstrap by run (difference A − B, 95% CI; same resampled runs)\n",
          "| A − B | ΔROC-AUC | ΔPR-AUC | ΔTPR@FPR1% | Δpair macro |", "|---|---:|---:|---:|---:|"]
    for k, v in paired.items():
        L.append("| %s | " % k + " | ".join("%+.4f [%+.4f, %+.4f]" % (v[m]["diff"], *v[m]["ci"]) for m in
                 ("roc_auc", "pr_auc", "tpr", "pair_macro_auc")) + " |")
    L += ["", "## Per-pair AUC (test)\n"]
    pairs = sorted({p for v in out.values() for p in v["test"]["per_pair_auc"]})
    L += ["| set | " + " | ".join(pairs) + " |", "|---|" + "---:|" * len(pairs)]
    for k, v in out.items():
        L.append("| %s | " % k + " | ".join(str(v["test"]["per_pair_auc"].get(p)) for p in pairs) + " |")
    h = out[HEADLINE]["test"]
    L += ["", "## %s breakdowns (test)" % HEADLINE, "- victim_mode: %s" % h["per_victim_mode"],
          "- dual-use backend AUC: %s" % h["per_dual_use_backend_auc"], "- UE AUC: %s" % h["per_ue_auc"],
          "- TPR by attack_active: %s" % h["tpr_by_attack_active"], "- TTD: %s" % h["ttd"],
          "", "## Appendix — with DL (caveat: designed benign DL feedback is a near-label proxy)\n",
          E.md_table({k: v["test"] for k, v in out.items() if k.startswith("APPENDIX")},
                     {k: v for k, v in ci.items() if k.startswith("APPENDIX")})]
    (w / "baseline_v4.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
