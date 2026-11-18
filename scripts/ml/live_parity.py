#!/usr/bin/env python3
"""End-to-end parity of the embedded classifier (plan 2c): rebuild one live run offline from its own logs with the dataset
pipeline (build_dataset_twin.build_run, episodes/clf_features features, train_clf cur + win_summary per phase) and compare,
per UE and second, with what the xApp logged in defense/clf.jsonl (25 inputs, logit, alarms).
Two offline variants: "continuous" keeps the KPM trust gate over the whole run per UE (as the live xApp does) and is the
implementation check; "dataset" recomputes the gate per phase (as the training data did) and shows the effect of that choice.
Usage: live_parity.py <export dir with fold*_seed*> <run dir>..."""
import glob, json, pathlib, sys
import numpy as np
import xgboost as xgb
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ml")); sys.path.insert(0, str(ROOT / "scripts/drl"))
import build_dataset_twin as BD, tamper_replay as TR, clf_features  # noqa: F401  (clf_features patches episodes.features)
import episodes as EP


def cur(raw):  # train_clf.py cur(raw, "f15")
    prbk = np.log1p(raw[:, 2] * 100 / (1 + np.expm1(raw[:, 6])))[:, None]
    dlul = (raw[:, 7] - raw[:, 6])[:, None]
    return np.hstack([raw[:, [6, 7, 8, 9, 2, 3]], prbk, raw[:, [10, 11]], dlul, raw[:, [30, 26, 27, 28, 29]]])


def win_summary(raw, W):  # train_clf.py
    k, p, r = np.expm1(raw[:, 6]), np.expm1(raw[:, 8]), raw[:, 2] * 100
    T = len(k); out = np.zeros((T, 10), np.float32)
    for t in range(T):
        lo = max(0, t - W + 1); kk, pp, rr = k[lo:t + 1], p[lo:t + 1], r[lo:t + 1]
        m = kk.mean(); busy = kk >= 8
        run = best = 0
        for b in busy:
            run = 0 if b else run + 1; best = max(best, run)
        out[t] = [np.log1p(m), np.log1p(kk.max()), np.log1p(pp.mean()), np.log1p(pp.max()), rr.mean() / 100, rr.max() / 100,
                  busy.mean(), kk.std() / m if m > 0 else 0, kk.max() / m if m > 0 else 0, best / W]
    return out


from baselines_feat import coupling  # noqa: E402
NAMES = ["core_ul_kbps", "core_dl_kbps", "core_ul_pps", "core_dl_pps", "prb_ul", "prb_dl", "prb_ul_per_kbit", "size_ul", "size_dl",
         "dl_over_ul", "c_t_w", "trust", "mask", "kpm_age", "prof_age"] + ["w%d" % i for i in range(10)] + ["cpl%d" % i for i in range(6)]


def boosters(d):
    B = []
    for x in sorted(glob.glob(d.rstrip("/") + "/fold*_seed*")):
        b = xgb.Booster(); b.load_model(x + "/model.json"); B.append((b, json.load(open(x + "/config.json"))["temperature"]))
    return B


def k_of_n(z, k, n, th):
    return np.array([np.sum(z[max(0, t - n + 1):t + 1] > th) >= k for t in range(len(z))])


def block_rule(z, x, model):
    """The model's block rule: k2030 over all seconds, or a<k><n> over active seconds (core UL >= 8 kbit/s, x[:, 0] = log1p kbps)."""
    r = model["block"]["rule"]; th = model["block"]["threshold"]
    if r == "k2030":
        return k_of_n(z, 20, 30, th)
    src = open(str(ROOT / "scripts/ml/eval_block_rules.py")).read()      # rule table of the selection (a<k><n>, mean<n><k>)
    ns = {"np": np}; exec(compile(src[src.index("RULES = {"):src.index("def active(")], "rules", "exec"), ns)
    kind, k, n = ns["RULES"][r]
    out, hist = [], []
    for t in range(len(z)):
        if np.expm1(x[t, 0]) >= 8.0:
            hist.append(np.float32(z[t])); hist = hist[-n:]
        if kind == "mean":
            out.append(len(hist) >= k and np.mean(hist) > th)
        else:
            out.append(len(hist) >= k and sum(v > th for v in hist) >= k)
    return np.array(out)


def main():
    import os
    B = boosters(sys.argv[1]); model = json.load(open(os.environ.get("CLF_MODEL", str(ROOT / "artifacts/clf/export/clf_model.json"))))
    sth, bth = model["soft"]["threshold"], model["block"]["threshold"]
    KN = {"thr": (1, 1), "k23": (2, 3), "k35": (3, 5)}[model["soft"]["rule"]]
    tot = dict(n=0, xbad=np.zeros(len(model["features"])), zdiff=[], soft_agree=0, block_agree=0, ds_soft_agree=0, ds_zdiff=[])
    for run in sys.argv[2:]:
        df = BD.build_run(run)
        live = {}
        for l in open(pathlib.Path(run) / "defense/clf.jsonl"):
            o = json.loads(l); live[(o["supi"], o["t"])] = o
        for variant in ("continuous", "dataset"):
            for (ph, s), g in df.sort_values("t_unix").groupby(["phase", "supi"], sort=False):
                g = g.copy()
                if variant == "continuous":
                    g["kpm_trust"], g["kpm_masked"] = g["kpm_trust_ue"], g["kpm_masked_ue"]
                else:
                    gg = TR.gate(df[df.phase == ph], "ue")
                    g[["c_t", "c_t_w", "kpm_trust", "kpm_masked"]] = gg.loc[g.index]
                raw = EP.features(g)
                x = np.hstack([cur(raw), win_summary(raw, 10)] + ([coupling(raw)] if len(model["features"]) == 31 else [])).astype(np.float32)
                z = np.mean([b.predict(xgb.DMatrix(x), output_margin=True) / T for b, T in B], 0)
                L = [live.get((s, int(t))) for t in g.t_unix]
                ok = np.array([o is not None for o in L])
                if not ok.any():
                    continue
                lx = np.array([o["x"] for o in L if o]); lz = np.array([o["z"] for o in L if o])
                if variant == "continuous":
                    tot["n"] += ok.sum()
                    tot["xbad"] += (np.abs(lx - x[ok]) > 1e-4).sum(0)
                    tot["zdiff"] += list(np.abs(lz - z[ok]))
                    tot["soft_agree"] += (k_of_n(z, *KN, sth)[ok] == np.array([o["soft"] for o in L if o])).sum()
                    tot["block_agree"] += (block_rule(z, x, model)[ok] == np.array([o["block"] for o in L if o])).sum()
                else:
                    tot["ds_zdiff"] += list(np.abs(lz - z[ok]))
                    tot["ds_soft_agree"] += (k_of_n(z, *KN, sth)[ok] == np.array([o["soft"] for o in L if o])).sum()
    n = tot["n"]; zd = np.array(tot["zdiff"]); dz = np.array(tot["ds_zdiff"])
    print("seconds compared %d (runs %d)" % (n, len(sys.argv) - 2))
    print("continuous gate (implementation check): |dz| median %.2g, q99 %.2g, max %.2g; |dz|>0.01 in %.2f%% of seconds" % (np.median(zd), np.quantile(zd, .99), zd.max(), 100 * np.mean(zd > .01)))
    print("  alarm agreement: rate limit %.2f%%, block %.2f%%" % (100 * tot["soft_agree"] / n, 100 * tot["block_agree"] / n))
    print("  inputs differing by > 1e-4 (share of seconds): " + ", ".join("%s %.1f%%" % (NAMES[i], 100 * v / n) for i, v in enumerate(tot["xbad"]) if v))
    print("gate per phase as in the dataset: |dz| median %.2g, q99 %.2g; rate-limit alarm agreement %.2f%%" % (np.median(dz), np.quantile(dz, .99), 100 * tot["ds_soft_agree"] / n))


if __name__ == "__main__":
    main()
