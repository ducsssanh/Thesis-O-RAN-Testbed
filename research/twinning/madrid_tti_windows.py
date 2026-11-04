#!/usr/bin/env python3
"""Per-TTI bytes of every window in benign_windows.npz, from the raw Madrid parquet (build cells only; read only).
Output research/twinning/benign_windows_tti.npz, per band and direction: <d>_<band>_off (n+1 row offsets per window),
<d>_<band>_ms (uint32, ms from the window start), <d>_<band>_b (float32, bytes = tbs_sum / 8, tbs_sum is in bits).
Checks that the TTIs of each window sum to its per-second row in benign_windows.npz and prints the share that match.
Usage: madrid_tti_windows.py [heldout]   heldout: the windows of heldout_windows.npz from the raw I-796 and II-2650, for the gate check of TRAFFIC-TWINNING-PLAN 6.7"""
import pathlib, sys
import numpy as np
import pyarrow.parquet as pq

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE.parents[1] / "data/external/madrid"
CELLS = [["I-2650-raw-df-ms.parquet"], ["I-1815-raw-df-ms.parquet"],
         ["II-816-raw-df-ms-part1.parquet", "II-816-raw-df-ms-part2.parquet"],
         ["II-1835-raw-df-ms-part1.parquet", "II-1835-raw-df-ms-part2.parquet"]]
BANDS, LEN = ("P1", "P2", "P3", "P4"), 75
HELD = len(sys.argv) > 1 and sys.argv[1] == "heldout"
if HELD:
    CELLS = [["I-796-raw-df-ms.parquet"], ["II-2650-raw-df-ms.parquet"]]

z = np.load(HERE / ("heldout_windows.npz" if HELD else "benign_windows.npz"))
rows = {(b, d): [[] for _ in range(len(z["src_" + b]))] for b in BANDS for d in (0, 1)}
for c, parts in enumerate(CELLS):
    wins = {}
    for b in BANDS:
        src = z["src_" + b]
        for i in np.flatnonzero(src[:, 0] == c):
            wins.setdefault(int(src[i, 1]), []).append((int(src[i, 2]), b, int(i)))
    for k in wins:
        wins[k].sort()
    keys = np.fromiter(wins, dtype=np.int64)
    for part in parts:
        f = pq.ParquetFile(RAW / part)
        for batch in f.iter_batches(batch_size=2_000_000, columns=["timestamp", "rnti", "direction", "tbs_sum"]):
            frame = batch.to_pandas().dropna()   # some raw rows have null fields; the per-second check below shows if this loses bytes
            t, r, d, b = [frame[n].to_numpy() for n in ("timestamp", "rnti", "direction", "tbs_sum")]
            m = (b > 0) & np.isin(r, keys)
            t, r, d, b = t[m], r[m], d[m], b[m]
            lo, hi = t.min() if t.size else 0, t.max() if t.size else 0
            order = np.argsort(r, kind="stable")
            t, r, d, b = t[order], r[order], d[order], b[order]
            uniq, first = np.unique(r, return_index=True)
            bounds = np.r_[first, r.size]
            for j, key in enumerate(uniq):
                tt, dd, bb = t[bounds[j]:bounds[j + 1]], d[bounds[j]:bounds[j + 1]], b[bounds[j]:bounds[j + 1]]
                for start, band, i in wins[int(key)]:
                    if start > hi or start + LEN <= lo:
                        continue
                    w = (tt >= start) & (tt < start + LEN)
                    if w.any():
                        for dr in (0, 1):
                            q = w & (dd == dr)
                            if q.any():
                                rows[band, dr][i].append((np.floor((tt[q] - start) * 1000).astype(np.uint32), (bb[q] / 8).astype(np.float32)))
        print("done", part, flush=True)

out = {}
for b in BANDS:
    for dr, name in ((0, "ul"), (1, "dl")):
        off, ms, by, good, active = [0], [], [], 0, 0
        ref = z[name + "_" + b]
        for i, parts in enumerate(rows[b, dr]):
            a = np.concatenate([p[0] for p in parts]) if parts else np.empty(0, np.uint32)
            v = np.concatenate([p[1] for p in parts]) if parts else np.empty(0, np.float32)
            o = np.argsort(a, kind="stable")
            ms.append(a[o]); by.append(v[o]); off.append(off[-1] + a.size)
            per = np.bincount(np.minimum(a // 1000, LEN - 1).astype(int), weights=v, minlength=LEN)
            act = ref[i] > 0
            active += int(act.sum())
            good += int((np.abs(per[act] - ref[i][act]) <= np.maximum(1, 0.01 * ref[i][act])).sum())
        out[f"{name}_{b}_off"] = np.array(off, np.int64)
        out[f"{name}_{b}_ms"] = np.concatenate(ms)
        out[f"{name}_{b}_b"] = np.concatenate(by)
        print(b, name, "TTIs", off[-1], "active seconds matching the per-second row: %d / %d" % (good, active), flush=True)
DST = HERE / ("heldout_windows_tti.npz" if HELD else "benign_windows_tti.npz")
np.savez_compressed(DST, **out)
print("saved", DST.stat().st_size)
