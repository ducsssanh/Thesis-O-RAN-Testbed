"""Index of real 75 s windows for the benign twin.

A testbed UE replays the UL and DL bytes per second of one real user: 15 s pre-roll + 60 s phase. A session of the band
is picked with probability proportional to W + 74 and the window start is uniform in [s0 - 74, s1], so the session
may already be running, start inside the window or end inside it: activity is spread evenly over the window instead
of being front-loaded. Only that session's seconds are kept; the rest is zero, because outside the session the RNTI
value may belong to another phone (expiration threshold T), so other activity of the same value is never bridged.
Sessions and bands follow madrid_profile.py (per-cell T, activity = UL or DL, bands from benign_profiles.json).
Bytes are TBS bits / 8.

Output (npz): per band ul_P<k>, dl_P<k> (windows x 75, bytes), src_P<k> (cell, rnti, start second); and the
reference distributions the validation uses, printed and stored: 60 s window mean (bit/s, seconds 15..74) and busy
share (active seconds / 60).
Usage: madrid_windows.py <benign_profiles.json> <out.npz> [<per_band>]"""
import json, sys, numpy as np, pandas as pd

LEN, PRE = 75, 15
lib = json.load(open(sys.argv[1]))
dst = sys.argv[2]
per_band = int(sys.argv[3]) if len(sys.argv) > 3 else 10_000
edges = np.array(lib["band_edges_bps"])
rng = np.random.default_rng(1)

cells = []
for k, c in enumerate(lib["cells"]):
    r = pd.read_parquet(c["file"], columns=["rnti", "sec", "ul_bytes", "dl_bytes"])
    r["ul_bytes"] = r["ul_bytes"] / 8
    r["dl_bytes"] = r["dl_bytes"] / 8
    r = r[(r.ul_bytes > 0) | (r.dl_bytes > 0)].sort_values(["rnti", "sec"]).reset_index(drop=True)
    sec, rn = r.sec.to_numpy(np.int64), r.rnti.to_numpy(np.int64)
    new = np.r_[True, (rn[1:] != rn[:-1]) | (np.diff(sec) > c["gap_s"])]
    sid = np.cumsum(new) - 1
    first = np.flatnonzero(new)
    last = np.r_[first[1:], len(sec)] - 1
    ul = np.bincount(sid, weights=r.ul_bytes.to_numpy())
    s0, s1 = sec[first], sec[last]
    wall = s1 - s0 + 1
    rate = 8 * ul / wall
    band = np.where(ul > 0, np.searchsorted(edges, rate, side="right"), -1)
    key = rn * 2**32 + sec                                        # sorted lookup key
    cells.append(dict(rnti=rn[first], s0=s0, s1=s1, wall=wall, band=band, key=key,
                      ub=r.ul_bytes.to_numpy(), db=r.dl_bytes.to_numpy()))
    print(f"{c['file']}: {len(first)} sessions")

out, ref = {}, {}
for b in range(4):
    weight = np.array([c["wall"][c["band"] == b].sum() for c in cells], float)
    n_cell = rng.multinomial(per_band, weight / weight.sum())    # cells in proportion to band session-seconds
    U, D, S = [], [], []
    for k, (c, n) in enumerate(zip(cells, n_cell)):
        idx = np.flatnonzero(c["band"] == b)
        w = c["wall"][idx].astype(float) + LEN - 1
        pick = idx[rng.choice(len(idx), n, p=w / w.sum())]
        start = c["s0"][pick] - (LEN - 1) + (rng.random(n) * (c["wall"][pick] + LEN - 1)).astype(np.int64)
        t = start[:, None] + np.arange(LEN)
        inside = (t >= c["s0"][pick][:, None]) & (t <= c["s1"][pick][:, None])
        q = c["rnti"][pick][:, None] * 2**32 + t
        pos = np.searchsorted(c["key"], q)
        pos = np.minimum(pos, len(c["key"]) - 1)
        hit = inside & (c["key"][pos] == q)
        U.append(np.where(hit, c["ub"][pos], 0).astype(np.uint32))
        D.append(np.where(hit, c["db"][pos], 0).astype(np.uint32))
        S.append(np.c_[np.full(n, k), c["rnti"][pick], start])
    ul, dl = np.concatenate(U), np.concatenate(D)
    out[f"ul_P{b + 1}"], out[f"dl_P{b + 1}"], out[f"src_P{b + 1}"] = ul, dl, np.concatenate(S)
    mean_bps = 8 * ul[:, PRE:].mean(axis=1)
    busy = ((ul[:, PRE:] + dl[:, PRE:]) > 0).mean(axis=1)
    grid = [.1, .25, .5, .75, .9, .99]
    ref[f"P{b + 1}"] = {"window_mean_ul_bps_q": np.quantile(mean_bps, grid).round(1).tolist(),
                        "busy_share_q": np.quantile(busy, grid).round(3).tolist(), "quantiles": grid}
    act = (ul + dl) > 0
    print(f"P{b + 1}: windows {len(ul)}; 60 s UL mean bit/s q10..q99 {ref[f'P{b + 1}']['window_mean_ul_bps_q']}; "
          f"busy share q10..q99 {ref[f'P{b + 1}']['busy_share_q']}; "
          f"active share first/middle/last 15 s {act[:, :15].mean():.3f}/{act[:, 30:45].mean():.3f}/{act[:, 60:].mean():.3f}")
np.savez_compressed(dst, ref=json.dumps(ref), **out)
