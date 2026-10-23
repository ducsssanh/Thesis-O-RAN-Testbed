#!/usr/bin/env python3
"""Tabular baselines on the v4 windows (run locally, CPU, ~1 min).

  .venv-ml/bin/python -I scripts/ml/baseline_v4.py --win artifacts/ml/v4

Each baseline = HistGradientBoosting on per-window aggregates (mean/std/min/max/last of each
telemetry column over the window), trained on TRAIN main windows only, threshold frozen on VAL
(benign FPR 1%), reported on TEST with scripts/ml/v4_eval.py (same metrics as the LSTM).
Feature sets:
  nuisance  - meta only (ue, load, victim_mode, t_since_phase_start): must stay ~0.5
  volume    - kbps of every domain (rate/thp/urr/prof ul+dl): load-matched, so near chance is good
  ran / urr / prof / all - per telemetry domain and all together (cross-domain value)
"""
import argparse, json, pathlib, sys
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v4_eval as E

DOMAINS = {"ran": ("rate", "thp", "prb", "cell"), "urr": ("urr",), "prof": ("prof",)}


def cols_for(meta, pred):
    return [i for i, n in enumerate(meta["agg_features"]) if pred(n.split("_", 1)[1])]


def nuisance_matrix(d):
    ue = (d["ue"] == "ue2").astype(np.float32)
    vm = np.where(d["victim"] == "silent", 1.0, np.where(d["victim"] == "responsive", 0.0, np.nan))
    return np.stack([ue, d["load"], vm, d["t_since"]], 1).astype(np.float32)


def fit_score(Xall, d, model="hgb", seed=0):
    tr = (d["split"] == 0) & (d["kind"] == E.MAIN)
    if model == "hgb":
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.1, random_state=seed)
        clf.fit(Xall[tr], d["y"][tr])
        return clf.predict_proba(Xall)[:, 1]
    X = np.nan_to_num(Xall)
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-6
    clf = LogisticRegression(max_iter=2000).fit((X[tr] - mu) / sd, d["y"][tr])
    return clf.predict_proba((X - mu) / sd)[:, 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", default="artifacts/ml/v4")
    ap.add_argument("--fpr", type=float, default=0.01)
    a = ap.parse_args()
    w = pathlib.Path(a.win)
    d = dict(np.load(w / "windows_v4.npz", allow_pickle=False))
    meta = json.loads((w / "meta.json").read_text())
    agg = d["agg"]
    sets = {
        "nuisance (meta only)": (nuisance_matrix(d), "hgb"),
        "UL mean kbps only": (agg[:, [i for i, n in enumerate(meta["agg_features"])
                                      if n.startswith("mean_") and n.endswith("_ul_kbps")]], "hgb"),
        "UL kbps (mean/std/min/max/last)": (agg[:, cols_for(meta, lambda c: c.endswith("_ul_kbps"))], "hgb"),
        "DL kbps only": (agg[:, cols_for(meta, lambda c: c.endswith("_dl_kbps"))], "hgb"),
        "volume only (kbps)": (agg[:, cols_for(meta, lambda c: c.endswith("_kbps"))], "hgb"),
        "all minus DL": (agg[:, cols_for(meta, lambda c: "_dl" not in c)], "hgb"),
        "RAN (KPM)": (agg[:, cols_for(meta, lambda c: c.split("_")[0] in DOMAINS["ran"])], "hgb"),
        "URR": (agg[:, cols_for(meta, lambda c: c.split("_")[0] in DOMAINS["urr"])], "hgb"),
        "profiler (eBPF UPF)": (agg[:, cols_for(meta, lambda c: c.split("_")[0] in DOMAINS["prof"])], "hgb"),
        "RAN + URR": (agg[:, cols_for(meta, lambda c: c.split("_")[0] in DOMAINS["ran"] + DOMAINS["urr"])], "hgb"),
        "all (HGB)": (agg, "hgb"),
        "all (logistic)": (agg, "logreg"),
    }
    out = {}
    for name, (X, model) in sets.items():
        p = fit_score(X, d, model)
        vm = (d["split"] == 1) & (d["kind"] == E.MAIN)
        thr = E.threshold_at_fpr(p[vm], d["y"][vm], a.fpr)
        out[name] = {"n_features": int(X.shape[1]), "val": E.report(p, d, 1, thr), "test": E.report(p, d, 2, thr)}
        t = out[name]["test"]["main"]
        print("%-22s test ROC-AUC %s PR-AUC %s TPR %s FPR %s" % (name, t["roc_auc"], t["pr_auc"], t["tpr"], t["fpr"]), flush=True)
    (w / "baseline_v4.json").write_text(json.dumps(out, indent=1) + "\n")
    L = ["# v4 baselines (test split, %d runs; threshold frozen on val at benign FPR %g)\n"
         % (len(meta["split_runs"]["test"]), a.fpr), E.md_table({k: v["test"] for k, v in out.items()}), "",
         "## Per pair (all-HGB, test): AUC / TPR / FPR\n", "| pair | AUC | TPR | FPR | n |", "|---|---:|---:|---:|---:|"]
    for pr, v in out["all (HGB)"]["test"]["per_pair"].items():
        L.append("| %s | %s | %s | %s | %d |" % (pr, v["auc"], v["tpr"], v["fpr"], v["n"]))
    L += ["", "## Per pair AUC by feature set (test)\n"]
    pairs = list(out["all (HGB)"]["test"]["per_pair"])
    L.append("| set | " + " | ".join(pairs) + " |")
    L.append("|---|" + "---:|" * len(pairs))
    for k, v in out.items():
        L.append("| %s | " % k + " | ".join(str(v["test"]["per_pair"].get(pr, {}).get("auc")) for pr in pairs) + " |")
    t = out["all (HGB)"]["test"]
    L += ["", "## all-HGB breakdowns (test)", "- victim_mode: %s" % t["per_victim_mode"],
          "- dual-use backend AUC: %s" % t["per_dual_use_backend_auc"], "- UE AUC: %s" % t["per_ue_auc"],
          "- TPR by attack_active: %s" % t["tpr_by_attack_active"], "- TTD: %s" % t["time_to_detect_s"]]
    (w / "baseline_v4.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
