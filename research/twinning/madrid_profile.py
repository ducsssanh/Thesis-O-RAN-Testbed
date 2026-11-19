"""Build the benign profile library from the reduced (rnti, sec) tables of the build cells and the attack load anchors (§5.2).

Units: the reduced columns hold TBS **bits** (madrid_reduce.py); they are divided by 8 here.
Activity: a second is active in a direction when its bytes > 0; a session is one RNTI value with no silence (UL or
DL) longer than GAP seconds, GAP = the measured RNTI expiration threshold (madrid_session_rule.py, §3.1a).
Per session: wallclock W (first to last active second, silences included), long-run UL rate r = 8 * UL bytes / W,
DL/UL byte ratio rho; UL and DL ON runs (consecutive active seconds) and OFF gaps (silences inside the session).
Bands P1..P4 cut r at the pooled q50 / q90 / q99. Per band the library holds the r quantile table (inverse-CDF draw),
ON/OFF samples, rho quantiles, the active-second UL rate quantiles (check only) and a short-lag ACF reference.
Usage: madrid_profile.py <out.json> <cell.parquet>:<gap_s> [<cell.parquet>:<gap_s> ...]   (gap per cell, §3.1a)"""
import json, sys, numpy as np, pandas as pd

dst = sys.argv[1]
cells = [(c.rsplit(":", 1)[0], float(c.rsplit(":", 1)[1])) for c in sys.argv[2:]]
rng = np.random.default_rng(0)
GRID = np.linspace(0, 1, 1001)       # quantile grid of the stored distributions
SAMPLE = 200_000                     # ON/OFF values kept per band and direction
ACF_SESS, ACF_LAGS, ACF_MIN = 20_000, 10, 15


def runs(sec, sess):
    """ON-run lengths and OFF-gap lengths (s) of sorted active seconds, split by session."""
    new = np.r_[True, (sess[1:] != sess[:-1]) | (np.diff(sec) != 1)]
    rid = np.cumsum(new) - 1
    on = np.bincount(rid)
    first = np.flatnonzero(new)
    inner = first[1:][sess[first[1:]] == sess[first[1:] - 1]]  # run starts that continue a session
    off = sec[inner] - sec[inner - 1] - 1
    return on, sess[first], off, sess[inner]


S, U, D = [], [], []                 # per session; UL / DL run tables
active_ul = []
for k, (path, gap) in enumerate(cells):
    r = pd.read_parquet(path, columns=["rnti", "sec", "ul_bytes", "dl_bytes"])
    r["ul_bytes"] = r["ul_bytes"] / 8
    r["dl_bytes"] = r["dl_bytes"] / 8
    r = r[(r.ul_bytes > 0) | (r.dl_bytes > 0)].sort_values(["rnti", "sec"]).reset_index(drop=True)
    sec, rn = r.sec.to_numpy(np.int64), r.rnti.to_numpy()
    new = np.r_[True, (rn[1:] != rn[:-1]) | (np.diff(sec) > gap)]
    sess = np.cumsum(new) - 1 + k * 10**9                      # unique across cells
    r["sess"] = sess
    g = r.groupby("sess", sort=False).agg(s0=("sec", "min"), s1=("sec", "max"),
                                          ul=("ul_bytes", "sum"), dl=("dl_bytes", "sum"))
    g["wall"] = g.s1 - g.s0 + 1
    g["rate"] = 8 * g.ul / g.wall                              # bit/s, long-run (silences included)
    g["cell"] = k
    S.append(g[["wall", "ul", "dl", "rate", "cell"]])
    for direction, out in (("ul_bytes", U), ("dl_bytes", D)):
        a = r[r[direction] > 0]
        on, on_s, off, off_s = runs(a.sec.to_numpy(np.int64), a.sess.to_numpy())
        out.append((on, on_s, off, off_s))
    au = r[r.ul_bytes > 0]
    active_ul.append(pd.DataFrame({"sess": au.sess.to_numpy(), "bps": 8 * au.ul_bytes.to_numpy(),
                                   "sec": au.sec.to_numpy(np.int64)}))
    print(f"{path}: {len(r)} active seconds, {len(g)} sessions")

S = pd.concat(S)
S = S[S.ul > 0]
edges = S.rate.quantile([.5, .9, .99]).to_numpy()
S["band"] = np.searchsorted(edges, S.rate.to_numpy(), side="right")  # 0..3 = P1..P4
band_of = S.band
A = pd.concat(active_ul)
A["band"] = band_of.reindex(A.sess.to_numpy()).to_numpy()


def table(parts, b):
    on = np.concatenate([p[0][band_of.reindex(p[1]).to_numpy() == b] for p in parts])
    off = np.concatenate([p[2][band_of.reindex(p[3]).to_numpy() == b] for p in parts])
    take = lambda x: rng.choice(x, min(SAMPLE, len(x)), replace=False).astype(int).tolist() if len(x) else []
    return take(on), take(off)


def acf(b):
    """mean ACF (lags 1..10) of the normalised UL series of sessions with W >= ACF_MIN in band b."""
    ids = S.index[(S.band == b) & (S.wall >= ACF_MIN)]
    ids = rng.choice(ids, min(ACF_SESS, len(ids)), replace=False)
    sub = A[A.sess.isin(ids)]
    vals = []
    for _, grp in sub.groupby("sess"):
        s0, s1 = grp.sec.min(), grp.sec.max()
        x = np.zeros(s1 - s0 + 1)
        x[grp.sec.to_numpy() - s0] = grp.bps.to_numpy()
        x = x / x[x > 0].mean() - 1
        den = (x * x).sum()
        if den > 0:
            vals.append([(x[:-l] * x[l:]).sum() / den for l in range(1, ACF_LAGS + 1)])
    return np.mean(vals, axis=0).round(4).tolist() if vals else []


q = lambda s: np.quantile(s, GRID).round(3).tolist()
lib = {"cells": [{"file": p, "gap_s": g} for p, g in cells], "units": {"rate": "bit/s", "runs": "s"},
       "band_edges_bps": edges.round(1).tolist(), "bands": {}}
for b in range(4):
    sb = S[S.band == b]
    ul_on, ul_off = table(U, b)
    dl_on, dl_off = table(D, b)
    lib["bands"][f"P{b + 1}"] = {
        "real_share": round(len(sb) / len(S), 4), "sessions": len(sb),
        "rate_q": q(sb.rate), "rho_q": q(sb.dl / sb.ul),
        "active_ul_bps_q": q(A.bps[A.band == b]),
        "ul_on": ul_on, "ul_off": ul_off, "dl_on": dl_on, "dl_off": dl_off,
        "acf_ul": acf(b), "wall_q": q(sb.wall)}
    print(f"P{b + 1}: sessions {len(sb)}, rate p50 {sb.rate.median():.0f} bit/s, rho p50 {(sb.dl / sb.ul).median():.2f}")
lib["attack_anchor_bps"] = {f"q{p}": round(float(np.quantile(A.bps, p)), 1) for p in (0.90, 0.95, 0.99)}
print("band edges bit/s:", lib["band_edges_bps"], "| attack anchors (active-second UL bit/s):", lib["attack_anchor_bps"])
json.dump(lib, open(dst, "w"))
