#!/usr/bin/env python3
"""Does a composed usage history help to tell a flood from high benign traffic? Classifier per second, cross-validated by run, trained on L1 + L2 as in the DRL design, with and without history. Checks: history alone must not know the label; final2 against the campaign.
Usage: history_check.py <rows.parquet> <final2 rows.parquet>"""
import os, sys, pathlib
os.environ.setdefault("OMP_NUM_THREADS", "4")
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier as HGB
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts/ml"))
import history_features as H
d = pd.read_parquet(sys.argv[1]); f2 = pd.read_parquet(sys.argv[2])
d = d.sort_values(["run_id", "phase", "supi", "t_unix"]).reset_index(drop=True)
print("benign twin-only episodes: campaign", d[(d.role == "benign") & (d.client_role == "")].groupby(["run_id", "phase", "supi"]).ngroup().nunique(), "final2", f2.groupby(["run_id", "phase", "supi"]).ngroup().nunique())
SH = ["prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp", "prof_ul_dns", "prof_ul_frag", "prof_dl_tcp", "prof_dl_udp", "prof_dl_icmp"]
BASE = ["rate_ul_kbps", "rate_dl_kbps", "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct", "prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps", "prof_ul_mean_bytes", "prof_dl_mean_bytes", "prof_ul_dst_estimate"]


def feats(x):
    x = x.copy()
    for c in SH:
        p = x.prof_ul_pps if "_ul_" in c else x.prof_dl_pps
        x[c + "_s"] = x[c] / p.clip(lower=1)
    cols = BASE + [c + "_s" for c in SH]
    g = x.groupby(["run_id", "phase", "supi"], sort=False)
    m = g[cols].transform(lambda s: s.rolling(10, min_periods=1).mean())
    m.columns = [c + "_m10" for c in cols]
    return pd.concat([x[cols], m], axis=1)


X0 = feats(d)
y = d.attack_active.to_numpy()
runs = d.run_id.to_numpy()
ur = np.unique(runs)
fold_of = {}
for i, (_, te) in enumerate(GroupKFold(5).split(ur, groups=ur)):
    for j in te:
        fold_of[ur[j]] = i
f2_runs = np.unique(f2.run_id); frng = np.random.default_rng(1)
f2_fold = dict(zip(f2_runs, frng.integers(5, size=len(f2_runs))))


def pools_for(folds, use_f2):
    a = d[d.run_id.map(fold_of).isin(folds)]
    p = H.pool(a)
    if use_f2:
        q = H.pool(f2[f2.run_id.map(f2_fold).isin(folds)])
        for k, v in q.items():
            p.setdefault(k, []).extend(v)
    return p


Z_W = np.load(pathlib.Path(__file__).resolve().parent / "benign_windows.npz")


def run(seed, use_f2, match=False):
    rng = np.random.default_rng(seed)
    pred = {k: np.zeros(len(d)) for k in ("base", "hist", "only")}
    for k in range(5):
        tr_f = [i for i in range(5) if i != k]
        pt, pe = pools_for(tr_f, use_f2), pools_for([k], use_f2)
        h = pd.DataFrame(index=d.index, columns=H.HIST, dtype=float)
        for key, ep in d.groupby(["run_id", "phase", "supi"], sort=False):
            h.loc[ep.index] = H.add_history(ep, pe if fold_of[key[0]] == k else pt, rng, level=float(Z_W["ul_" + ep.band.iloc[0]][int(ep.window_index.iloc[0])].sum()) if match else None).to_numpy()
        fold = d.run_id.map(fold_of).to_numpy()
        tr = (fold != k) & (d.evasion != "L3").to_numpy() & (d.client_role == "").to_numpy()
        te = fold == k
        for name, Z in (("base", X0.to_numpy()), ("hist", np.c_[X0.to_numpy(), h.to_numpy()]), ("only", h.to_numpy())):
            pred[name][te] = HGB(max_iter=120, random_state=seed).fit(Z[tr], y[tr]).predict_proba(Z[te])[:, 1]
    return pred


def report(p, tag):
    hi = (d.rate_ul_kbps >= 50).to_numpy()
    print(tag, "| history alone, seconds at 50 kbit/s or more: AUC %.3f" % roc_auc_score(y[hi], p["only"][hi]))
    print("  seconds at 50 kbit/s or more (flood against high benign), AUC without and with history:")
    neg0 = hi & (y == 0) & (d.client_role == "").to_numpy()
    negc = hi & (y == 0) & (d.client_role != "").to_numpy()
    for lv in ("L1", "L2", "L3"):
        pos = hi & (y == 1) & (d.evasion == lv).to_numpy()
        for bn, b in (("all", np.ones(len(d), bool)), ("P1-P3", d.band.isin(["P1", "P2", "P3"]).to_numpy()), ("P4", (d.band == "P4").to_numpy())):
            m = (pos | neg0) & b
            s = "    %s %-6s n+ %5d n- %5d  %.3f -> %.3f" % (lv, bn, (pos & b).sum(), (neg0 & b).sum(), roc_auc_score(y[m], p["base"][m]), roc_auc_score(y[m], p["hist"][m]))
            if lv == "L3":
                mc = (pos | negc) & b
                if (negc & b).sum() > 50:
                    s += " | against the same client as benign n- %d  %.3f -> %.3f" % ((negc & b).sum(), roc_auc_score(y[mc], p["base"][mc]), roc_auc_score(y[mc], p["hist"][mc]))
            print(s, flush=True)


# final2 against the campaign, on the same benign episodes features
def ep_feats(x):
    return np.array([[s[:, 0].mean(), s[:, 1].mean(), s[:, 2].mean()] for v in H.pool(x).values() for s in v])
A, B = ep_feats(d), ep_feats(f2)
Z = np.r_[A, B]; L = np.r_[np.zeros(len(A)), np.ones(len(B))]
idx = np.random.default_rng(0).permutation(len(L)); c = len(L) // 2
print("final2 against the campaign, 3 episode-level history values: AUC %.3f (n %d, %d)" % (roc_auc_score(L[idx[c:]], HGB(max_iter=40).fit(Z[idx[:c]], L[idx[:c]]).predict_proba(Z[idx[c:]])[:, 1]), len(A), len(B)))
report(run(0, False), "campaign episodes, history of the same band")
report(run(0, False, True), "campaign episodes, history matched to the level of the twin window")
