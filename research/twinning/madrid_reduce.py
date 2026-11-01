"""Stream a Madrid TTI-level parquet and reduce it to per-(rnti,second): UL and DL bytes, PRB sum, TTI count
(direction 0 = UL, 1 = DL); per-TTI timestamps are not kept. A row exists when the RNTI had a grant in either
direction that second; a direction without grants has 0 bytes / 0 TTIs. Column `ttis` is the UL TTI count (rev-1
name), `dl_ttis` the DL one.

The raw files are time-ordered (checked), so each batch's seconds before its last second are final and written
out at once; only the last second is carried into the next batch. Memory stays at one batch, which the large
cells (II-816, II-1835: two parts, ~14 GB raw) need. Multi-part cells are passed in time order.
Usage: madrid_reduce.py <raw.parquet> [<raw-part2.parquet> ...] <out.parquet>"""
import sys, numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq

# compact types (ranges checked on I-2650: rnti < 65536, per-second bytes < 2^32, TTIs <= 2000) + zstd
TYPES = {"rnti": "uint16", "sec": "uint32", "ul_bytes": "uint32", "ul_prb": "uint32", "ttis": "uint16",
         "dl_bytes": "uint32", "dl_prb": "uint32", "dl_ttis": "uint16"}


def agg(d):
    return d.groupby(["rnti", "sec", "direction"], sort=False).agg(
        bytes=("bytes", "sum"), prb=("prb", "sum"), ttis=("ttis", "sum")).reset_index()


def widen(r):
    ul = r[r.direction == 0].drop(columns="direction").rename(
        columns={"bytes": "ul_bytes", "prb": "ul_prb"})
    dl = r[r.direction == 1].drop(columns="direction").rename(
        columns={"bytes": "dl_bytes", "prb": "dl_prb", "ttis": "dl_ttis"})
    w = ul.merge(dl, on=["rnti", "sec"], how="outer")
    for c, t in TYPES.items():
        if w[c].max() > np.iinfo(t).max:
            sys.exit(f"{c} exceeds {t}")
        w[c] = w[c].fillna(0).astype(t)
    return w[list(TYPES)]


*srcs, dst = sys.argv[1:]
writer = None
carry = None
seen = {0: 0, 1: 0}
dropped = 0
stats = {"rows": 0, "ul": 0, "dl": 0, "smin": None, "smax": None}
rntis = set()
last_ts = -np.inf


def emit(w):
    global writer
    if w.empty:
        return
    t = pa.Table.from_pandas(w, preserve_index=False)
    if writer is None:
        writer = pq.ParquetWriter(dst, t.schema, compression="zstd")
    writer.write_table(t)
    stats["rows"] += len(w)
    stats["ul"] += int((w.ul_bytes > 0).sum())
    stats["dl"] += int((w.dl_bytes > 0).sum())
    stats["smin"] = w.sec.min() if stats["smin"] is None else min(stats["smin"], w.sec.min())
    stats["smax"] = w.sec.max() if stats["smax"] is None else max(stats["smax"], w.sec.max())
    rntis.update(w.rnti.unique().tolist())


for src in srcs:
    pf = pq.ParquetFile(src)
    for b in pf.iter_batches(batch_size=4_000_000, columns=["timestamp", "rnti", "direction", "tbs_sum", "nof_prb"]):
        d = b.to_pandas()
        # malformed rows at the head/tail of some cells: NaN or out-of-range epoch (I-796: 4 NaN + 18 out of range,
        # e.g. 11.5 or 1.6e11; II-2650: 2 NaN + 1 at 1.6e18); keep 2017..2033
        bad = ~d["timestamp"].between(1.5e9, 2e9)
        if bad.any():
            dropped += int(bad.sum())
            d = d[~bad]
            if d.empty:
                continue
        if d.timestamp.iloc[0] < last_ts or (np.diff(d.timestamp.to_numpy()) < 0).any():
            sys.exit(f"{src}: rows not time-ordered; streaming reduction is invalid")
        last_ts = d.timestamp.iloc[-1]
        for k in (0, 1):
            seen[k] += int((d["direction"] == k).sum())
        d["sec"] = np.floor(d["timestamp"]).astype("int64")
        d = d.rename(columns={"tbs_sum": "bytes", "nof_prb": "prb"})
        d["ttis"] = 1
        r = agg(d[["rnti", "sec", "direction", "bytes", "prb", "ttis"]])
        if carry is not None:
            r = agg(pd.concat([carry, r], ignore_index=True))
        cut = r.sec.max()
        emit(widen(r[r.sec < cut]))
        carry = r[r.sec == cut]
if carry is not None:
    emit(widen(carry))
writer.close()
print("UL TTIs:", seen[0], "| DL TTIs:", seen[1], "| malformed rows dropped:", dropped,
      "| (rnti,sec) rows:", stats["rows"],
      "| UL-active:", stats["ul"], "| DL-active:", stats["dl"], "| RNTIs:", len(rntis),
      "| sec span h:", round((stats["smax"] - stats["smin"]) / 3600, 1))
