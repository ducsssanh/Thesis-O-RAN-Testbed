"""v4 Phase 3 campaign design — dry-run tools (NO testbed).

`sizes` subcommand: simulate the shared packet-size prior across a whole campaign and
report, per attack↔benign counterpart pair (plan section 6.3), the EXPECTED packet-size
overlap under two prior-sampling policies:
  - independent: attacker and its counterpart each draw their own Dirichlet weights
    (what the Phase-2 pilot did);
  - shared-per-cell: the two flows of one design cell share ONE draw.
It separates POOLED overlap (across all cells) from PER-CELL overlap (within one phase,
which is what a per-phase detector sees). This answers whether a low per-pair overlap is
fixable by design (shared draw) or merely hidden by averaging over reps.

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/design.py sizes
"""
import json, pathlib, sys
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sizes

# section 6.3 pairs; size_matched = both are UDP drawing from the shared prior (sizes
# must match — the class is told apart by behaviour/time/fan-out, not packet size).
# protocol_distinct = sizes differ by protocol on purpose (a VALID signal, not a confound).
PAIRS = [
    ("udp_flood", "udp_bidir", "size_matched", "distinguish by feedback/congestion response"),
    ("dns_flood", "dns_heavy", "size_matched", "distinguish by answer ratio"),
    ("fanout_udp", "fanout_benign", "size_matched", "distinguish by dst fan-out"),
    ("pulsing_udp", "onoff_pareto", "size_matched", "distinguish by timing (pulse period)"),
    ("mimicry_udp", "udp_nofeedback", "size_matched", "match on ALL axes (stress; train-excluded)"),
    ("syn_flood", "tcp_shortconn", "protocol_distinct", "SYN 60B vs full TCP exchange — valid"),
    ("icmp_flood", "icmp_ping", "protocol_distinct", "ICMP echo fixed 84B — valid"),
]


def _ovl(a, b, bins=16):
    edges = np.histogram_bin_edges(np.concatenate([a, b]), bins=bins)
    pa = np.histogram(a, edges)[0] / len(a)
    pb = np.histogram(b, edges)[0] / len(b)
    return float(np.minimum(pa, pb).sum())


def simulate_sizes(cells=400, pkts_per_sec=160, secs=40, alpha=1.0, seed=0):
    """Per cell, draw size weights and realise per-second mean packet sizes (each second
    is the mean of `pkts_per_sec` packet sizes drawn from the weights). Compare the two
    flows' per-second size samples:
      pooled   : all seconds of all cells (attacker vs counterpart) — the campaign-level view;
      per_cell : within each cell, attacker-vs-counterpart overlap, averaged over cells —
                 what the detector sees inside one phase.
    Done for independent and shared-per-cell draws."""
    rng = np.random.default_rng(seed)
    BINS = sizes.BINS
    out = {}
    for policy in ("independent", "shared_per_cell"):
        pooled_a, pooled_b, per_cell = [], [], []
        for _ in range(cells):
            wa = rng.dirichlet(np.full(len(BINS), alpha))
            wb = wa if policy == "shared_per_cell" else rng.dirichlet(np.full(len(BINS), alpha))
            # per-second mean size = mean of pkts_per_sec packet-size draws from the weights
            sa = np.array([rng.choice(BINS, size=pkts_per_sec, p=wa).mean() for _ in range(secs)])
            sb = np.array([rng.choice(BINS, size=pkts_per_sec, p=wb).mean() for _ in range(secs)])
            pooled_a.append(sa); pooled_b.append(sb)
            per_cell.append(_ovl(sa, sb))
        pooled = _ovl(np.concatenate(pooled_a), np.concatenate(pooled_b))
        out[policy] = {"pooled_overlap": round(pooled, 3),
                       "per_cell_overlap_median": round(float(np.median(per_cell)), 3),
                       "per_cell_overlap_p10": round(float(np.quantile(per_cell, 0.1)), 3)}
    return out


def cmd_sizes(_):
    sim = simulate_sizes()
    print("# Phase-3 size-prior dry-run (no testbed)\n")
    print("Simulated per-second mean packet size, shared Dirichlet prior over bins",
          [int(x) for x in sizes.BINS], "\n")
    print("| policy | pooled overlap | per-cell overlap (median) | per-cell (p10) |")
    print("|---|---:|---:|---:|")
    for pol, v in sim.items():
        print(f"| {pol} | {v['pooled_overlap']} | {v['per_cell_overlap_median']} | {v['per_cell_overlap_p10']} |")
    ind, sh = sim["independent"], sim["shared_per_cell"]
    print(f"\n**Finding:** pooled overlap is high either way ({ind['pooled_overlap']} vs "
          f"{sh['pooled_overlap']}) — so averaging over reps HIDES the problem — but the "
          f"per-cell overlap stays low under independent draws "
          f"({ind['per_cell_overlap_median']}) and only shared-per-cell draws make it high "
          f"({sh['per_cell_overlap_median']}). A per-phase detector sees the per-cell gap, so "
          f"**size-matched pairs MUST share one size draw per cell** (fix the prior before Phase 3; "
          f"reps will not fix it).\n")
    print("Per section-6.3 pair:\n")
    print("| attack | counterpart | policy | note |\n|---|---|---|---|")
    for atk, ben, kind, note in PAIRS:
        pol = "shared-per-cell draw" if kind == "size_matched" else "sizes differ by protocol (valid)"
        print(f"| {atk} | {ben} | {pol} | {note} |")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sizes":
        cmd_sizes(sys.argv[2:])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
