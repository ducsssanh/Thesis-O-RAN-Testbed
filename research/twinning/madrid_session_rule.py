"""Measure, on the raw 1 ms Madrid decode, what the session rule needs (TRAFFIC-TWINNING-PLAN §3.1a): the RNTI
expiration threshold T, the RNTI allocation rule and the RNTI reuse interval. Build cells only.

Method (Attanasio et al., Computer Networks 219, 2022, Sec. 4.1.1, same IMDEA group and FALCON sniffer): the
inter-transmission time of one RNTI value falls fast (1-3 s), then decreases smoothly while the same UE still owns
the value, then levels out where only reassignments to new UEs remain. T is placed right after the knee between the
smooth decrease and the levelling out. Here the knee is the first log-spaced bin above 10 s whose count per bin is
within KNEE x the plateau (median of the bins from PLATEAU[0] to PLATEAU[1] s), and T is the upper edge of that bin.
The plateau is taken before a few minutes: group II cells show a large hump at 3-8 min (values handed out again from
a frequently used subset, the paper's interval-based allocation), which would otherwise inflate it. A fixed-delay release signature was
tried first (gap before the final grant of an episode) and shows no peak, so it is not used.

- allocation rule: for new episodes (silence > LONG), is the next new value close to the previous one (round robin,
  the paper finds it below 32060 for Spanish operators A, B) or random;
- reuse interval: silence before a value starts a new episode.

RNTI values are processed in ranges (one pass over the file per range) so that a large cell fits in memory.
Usage: madrid_session_rule.py <out.txt> <ranges> <raw.parquet> [<raw-part2.parquet> ...]"""
import sys, numpy as np, pyarrow.compute as pc, pyarrow.parquet as pq

LONG = 60.0                # s; silence that starts a new episode for the allocation and reuse views
PLATEAU = (40.0, 125.0)    # s; where the levelling-out stage is measured (before the group II hump)
KNEE = 2.0                 # a bin within this factor of the plateau is past the knee
RR_LIMIT = 32060           # paper: round-robin values lie below this for Spanish operators A, B
dst, ranges, *srcs = sys.argv[1:]
out = open(dst, "w")


def say(*a):
    print(*a)
    print(*a, file=out)


def load(lo, hi):
    """timestamp and rnti of values in [lo, hi), all source parts, malformed epochs dropped."""
    ts, rn = [], []
    for src in srcs:
        for b in pq.ParquetFile(src).iter_batches(batch_size=8_000_000, columns=["timestamp", "rnti"]):
            r = b.column("rnti")
            t = b.filter(pc.and_(pc.greater_equal(r, lo), pc.less(r, hi)))
            x = t.column("timestamp").to_numpy(zero_copy_only=False)
            ok = (x > 1.5e9) & (x < 2e9)
            ts.append(x[ok]); rn.append(t.column("rnti").to_numpy(zero_copy_only=False)[ok].astype(np.uint16))
    return np.concatenate(ts), np.concatenate(rn)


log_edges = np.logspace(np.log10(0.5), np.log10(1e6), 80)
lin_edges = np.arange(0, 121, 1.0)
h_log = np.zeros(len(log_edges) - 1, np.int64)
h_lin = np.zeros(len(lin_edges) - 1, np.int64)
starts, reuse = [], []
n = 0
edges = np.linspace(0, 65536, int(ranges) + 1).astype(int)
for lo, hi in zip(edges[:-1], edges[1:]):
    ts, rn = load(lo, hi)
    o = np.lexsort((ts, rn))
    ts, rn = ts[o], rn[o]
    n += len(ts)
    gap = np.r_[np.inf, np.diff(ts)]
    gap[np.r_[True, rn[1:] != rn[:-1]]] = np.inf                 # first grant of a value: no previous silence
    fin = gap[np.isfinite(gap)]
    h_log += np.histogram(fin, log_edges)[0]
    h_lin += np.histogram(fin, lin_edges)[0]
    s = gap > LONG
    starts.append(np.c_[ts[s], rn[s]])
    reuse.append(gap[s & np.isfinite(gap)])
    say(f"rnti [{lo}, {hi}): grants {len(ts)}")
starts = np.concatenate(starts); reuse = np.concatenate(reuse)
say(f"\nfiles: {' '.join(srcs)}\ngrants {n}")

# --- expiration threshold: knee between the smooth decrease and the levelling out ---
say("\nINTER-TRANSMISSION TIME (same RNTI value), count per log bin")
for a, b, c in zip(log_edges[:-1], log_edges[1:], h_log):
    if 1 <= a <= 3600:
        say(f"  {a:9.1f} - {b:9.1f} s: {c}")
mid = np.sqrt(log_edges[:-1] * log_edges[1:])
plateau = np.median(h_log[(mid >= PLATEAU[0]) & (mid <= PLATEAU[1])])
past = np.where((log_edges[:-1] >= 10) & (h_log <= KNEE * plateau))[0]
knee = log_edges[past[0] + 1] if len(past) else float("nan")
say(f"  plateau (median count per bin, {PLATEAU[0]:.0f}-{PLATEAU[1]:.0f} s): {plateau:.0f}")
say(f"  T (upper edge of the first bin above 10 s within {KNEE}x the plateau): {knee:.1f} s")
say("  per-second counts 0..120 s:", h_lin.tolist())

# --- allocation rule ---
say(f"\nALLOCATION: new episodes (silence > {LONG:.0f} s) in time order")
o = np.argsort(starts[:, 0], kind="stable")
v = starts[o, 1].astype(np.int64)
for name, m in [(f"< {RR_LIMIT}", v < RR_LIMIT), (f">= {RR_LIMIT}", v >= RR_LIMIT)]:
    d = np.diff(v[m])
    say(f"  values {name}: {int(m.sum())} episodes; next value within +1..+20 of the previous: "
        f"{np.mean((d >= 1) & (d <= 20)):.3f}; median |difference| {np.median(np.abs(d)):.0f}")
say(f"  value range {v.min()}..{v.max()}")

# --- reuse interval ---
q = np.quantile(reuse, [.01, .05, .5, .95])
say(f"\nREUSE: silence before a value starts a new episode, p1 / p5 / p50 / p95 (s): "
    + " / ".join(f"{x:.0f}" for x in q))
out.close()
