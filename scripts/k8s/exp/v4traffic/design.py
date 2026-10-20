"""v4 Phase 3 campaign design (NO testbed): build a counterbalanced manifest + audit it.

Subcommands:
  sizes   dry-run of the shared size prior (per-cell vs pooled overlap; shared-draw fix).
  plan    generate the campaign manifest (runs -> phases -> per-UE flow specs + seeds),
          write per-run scenario YAMLs, and print the balance audit, ETA and the
          section-6.3 cell list per UE. Does NOT run anything.
  audit   re-audit an existing manifest/design.json.

Balance is STRUCTURAL, not probabilistic (plan conditions):
  - attacker and benign counterpart run CONCURRENTLY in each phase, so every phase emits
    exactly one MALICIOUS and one BENIGN row sharing the phase-level factors (load,
    victim_mode, congestion) -> P(malicious | those) = 0.5 automatically;
  - every phase is emitted with its UE mirror (ue1-attacks / ue2-attacks) -> P(mal|ue)=0.5;
  - dual-use backends (pacer/hping/iperf) are kept 0.5 by same-backend-both-sides where
    natural, and the attacker-only use of a dual-use tool in SYN/DNS floods is cancelled
    by UE-mirrored compensation phases (role-pure synflood attacker vs a dual-use benign),
    so each dual-use backend is attacker in exactly half of its phases.

  .venv-ml/bin/python -I scripts/k8s/exp/v4traffic/design.py plan [--reps N] [--seed S]
"""
import argparse, json, pathlib, random, sys
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


# ----------------------------------------------------------------- campaign plan
LOADS = [("L1", 0.4), ("L2", 0.8), ("L3", 1.2)]        # Mbit/s, in the Phase-0 linear region
VICTIMS = ["silent", "responsive"]
DUAL_USE = ("pacer", "hping", "iperf")                 # backends used in BOTH classes (audited 0.5)

# section-6.3 pairs. attacker tools are (backend, mode, model); benign counterpart uses the
# SAME dual-use backend where natural (so that backend stays 0.5), else a role-pure backend.
FAMILIES = [
    {"key": "udp", "atk_family": "udp_flood", "benign_class": "udp_bidir", "size_matched": True,
     "atk_tools": [("pacer", None, "fgn"), ("hping", "udp", "mmpp2"), ("iperf", None, "cbr")],
     "benign_same_backend": True, "benign_model": "cbr"},
    {"key": "pulsing", "atk_family": "pulsing_udp", "benign_class": "onoff_pareto", "size_matched": True,
     "atk_tools": [("pacer", None, "pulsing")], "benign": ("pacer", None, "onoff_pareto")},
    {"key": "mimicry", "atk_family": "mimicry_udp", "benign_class": "udp_nofeedback", "size_matched": True,
     "stress": True, "dl_feedback": 0, "atk_tools": [("pacer", None, "onoff_pareto")],
     "benign": ("pacer", None, "onoff_pareto")},
    {"key": "fanout", "atk_family": "fanout_udp", "benign_class": "fanout_benign", "size_matched": True,
     "fanout": 16, "atk_tools": [("pacer", None, "cbr")], "benign": ("pacer", None, "cbr")},
    {"key": "icmp", "atk_family": "icmp_flood", "benign_class": "icmp_ping", "size_matched": False,
     "atk_tools": [("hping", "icmp", "cbr")], "benign": ("hping", "icmp", "cbr")},
    {"key": "syn", "atk_family": "syn_flood", "benign_class": "tcp_shortconn", "size_matched": False,
     "atk_tools": [("hping", "syn", "hawkes"), ("synflood", None, "hawkes")],
     "benign": ("tcp_shortconn", None, "hawkes"), "load_scale": 0.5},
    {"key": "dns", "atk_family": "dns_flood", "benign_class": "dns_heavy", "size_matched": False,
     "atk_tools": [("pacer", None, "cbr"), ("hping", "udp", "cbr")],
     "benign": ("dns_client", None, "poisson"), "load_scale": 0.5, "size_alpha": 0.2},
]


class _Seeder:
    def __init__(self, base): self.n = base
    def next(self):
        self.n += 1
        return self.n


def _flow(backend, mode, model, role, level_mbps, seed, size_seed=None, **extra):
    s = {"v4": True, "backend": backend, "model": model, "role": role,
         "level_mbps": round(level_mbps, 4), "seed": seed}
    if mode:
        s["mode"] = mode
    if size_seed is not None:
        s["size_seed"] = size_seed
    s.update(extra)
    return s


def _emit_pair(fam, tool, load_mbps, victim, cong, ue_attacks, seeder, cellid, rng):
    """One phase: attacker (ue_attacks) + benign counterpart (other UE), load-matched."""
    be, mode, model = tool
    scale = fam.get("load_scale", 1.0)
    lvl = load_mbps * scale
    pair = fam["atk_family"] + "~" + fam["benign_class"]
    size_seed = cellid if fam["size_matched"] else None
    atk_extra, ben_extra = {"pair": pair}, {"pair": pair}
    if fam.get("fanout"):
        atk_extra["fanout"] = ben_extra["fanout"] = fam["fanout"]
    if fam.get("stress"):
        atk_extra["stress_cell"] = True
    if fam.get("dl_feedback") == 0:
        atk_extra["dl_feedback"] = ben_extra["dl_feedback"] = 0
    if fam.get("size_alpha"):
        atk_extra["size_alpha"] = fam["size_alpha"]
    atk = _flow(be, mode, model, "attack", lvl, seeder.next(), size_seed, **atk_extra)
    if fam.get("benign_same_backend"):
        bb, bm, bmd = be, mode, fam.get("benign_model", "cbr")
    else:
        bb, bm, bmd = fam["benign"]
    if fam["size_matched"]:
        ben_extra.setdefault("size_alpha", fam.get("size_alpha", 1.0))
    ben = _flow(bb, bm, bmd, "benign", lvl, seeder.next(), size_seed, **ben_extra)
    a_ue, b_ue = ("ue1", "ue2") if ue_attacks == "ue1" else ("ue2", "ue1")
    ph = {"family": fam["key"], "pair": pair, "atk_family": fam["atk_family"], "benign_class": fam["benign_class"],
          "attacker_ue": ue_attacks, "atk_backend": be, "benign_backend": bb,
          "load": load_mbps, "victim_mode": victim, "congestion": cong,
          "duration": int(rng.integers(30, 91)), "gap": int(rng.integers(8, 16)),
          "flows": {a_ue: {"ul": atk}, b_ue: {"ul": ben}}}
    if cong:
        ph["congestion_cfg"] = {"rate": "4mbit"}
    return ph


def _benign_benign(d_backend, load_mbps, victim, cong, seeder, rng):
    """A both-benign phase: both UEs legit high-load on dual-use backend d (a concurrent
    heavy-load scenario). Adds BENIGN uses of d to offset its SYN/DNS attacker surplus,
    without any attacker. meta_pair = benign_benign. UE-symmetric by construction."""
    mode = "udp" if d_backend == "hping" else None
    f1 = _flow(d_backend, mode, "fgn", "benign", load_mbps, seeder.next(), pair="benign_benign")
    f2 = _flow(d_backend, mode, "cbr", "benign", load_mbps, seeder.next(), pair="benign_benign")
    ph = {"family": "benign_benign", "pair": "benign_benign", "atk_family": "", "benign_class": d_backend,
          "attacker_ue": None, "atk_backend": None, "benign_backend": d_backend,
          "load": load_mbps, "victim_mode": victim, "congestion": cong,
          "duration": int(rng.integers(30, 91)), "gap": int(rng.integers(8, 16)),
          "flows": {"ue1": {"ul": f1}, "ue2": {"ul": f2}}}
    if cong:
        ph["congestion_cfg"] = {"rate": "4mbit"}
    return ph


def build_manifest(reps=3, seed=20261020, phases_per_run=6):
    rng = np.random.default_rng(seed)
    seeder = _Seeder(seed * 10)
    # GROUP each UE-mirror pair (the 2 phases of one cell) so they stay in the SAME run:
    # then EVERY prefix of runs is UE-balanced (the design is exact only over whole mirror
    # pairs; a flat shuffle splits them and makes an early checkpoint look imbalanced).
    groups = []
    cell = 0
    for rep in range(reps):
        for fam in FAMILIES:
            for (lname, lmb) in LOADS:
                for victim in VICTIMS:
                    for tool in fam["atk_tools"]:
                        cell += 1
                        groups.append([_emit_pair(fam, tool, lmb, victim, 0, ue, seeder, cell, rng)
                                       for ue in ("ue1", "ue2")])
            cell += 1                                      # ~1 congestion cell per family per rep
            groups.append([_emit_pair(fam, fam["atk_tools"][0], 0.8, "responsive", 1, ue, seeder, cell, rng)
                           for ue in ("ue1", "ue2")])
    # offset each dual-use backend's attacker ROW surplus with both-benign phases, factors
    # sampled from the real distribution so per-level balance holds. Each is its own group.
    flat = [ph for g in groups for ph in g]
    factors = [(ph["load"], ph["victim_mode"], ph["congestion"]) for ph in flat]
    # per-backend offset benign_benign groups, tagged by backend
    bb_by = {d: [] for d in DUAL_USE}
    for d, s in _dualuse_row_surplus(flat).items():
        for _ in range(max(s, 0) // 2):
            load, victim, cong = factors[int(rng.integers(len(factors)))]
            bb_by[d].append([_benign_benign(d, load, victim, cong, seeder, rng)])

    # STRUCTURAL BLOCK BALANCE (Q2): a group is dual-use-"surplus" for backend d when its
    # attacker uses d but its benign counterpart is role-pure (SYN/DNS floods) -> +2 attacker
    # rows of d. Pair each such group with one matching-backend benign_benign group (+2 benign
    # rows of d) into a backend-NEUTRAL unit. Self-balanced groups (same backend both sides)
    # are already neutral. Every unit is backend-neutral, so any prefix of runs is balanced.
    def surplus_backend(g):
        a, b = g[0]["atk_backend"], g[0]["benign_backend"]
        return a if (a in DUAL_USE and b not in DUAL_USE) else None
    units = []
    for g in groups:
        d = surplus_backend(g)
        if d and bb_by[d]:
            units.append(g + bb_by[d].pop())          # surplus group + its offset -> neutral unit
        else:
            units.append(g)
    for d in DUAL_USE:                                 # any leftover offsets as their own units
        units.extend(bb_by[d])
    rng2 = random.Random(seed)
    rng2.shuffle(units)
    phases = [ph for u in units for ph in u]
    runs = [phases[i:i + phases_per_run] for i in range(0, len(phases), phases_per_run)]
    return {"seed": seed, "reps": reps, "phases_per_run": phases_per_run,
            "n_runs": len(runs), "n_phases": len(phases),
            "checkpoints": sorted({max(1, round(len(runs) * f)) for f in (0.10, 0.50)}), "runs": runs}


def _dualuse_row_surplus(phases):
    """attacker ROWS - benign ROWS per dual-use backend (each phase has 1-2 UE flows)."""
    a = {d: 0 for d in DUAL_USE}
    b = {d: 0 for d in DUAL_USE}
    for ph in phases:
        for fl in ph["flows"].values():
            be, role = fl["ul"]["backend"], fl["ul"]["role"]
            if be in a:
                (a if role == "attack" else b)[be] += 1
    return {d: a[d] - b[d] for d in DUAL_USE}


# ----------------------------------------------------------------- audit
def audit_manifest(man):
    """Per-row (one MALICIOUS + one BENIGN per phase) crosstab of P(malicious | factor)."""
    rows = []
    for run in man["runs"]:
        for ph in run:
            for ue, fl in ph["flows"].items():
                spec = fl["ul"]
                rows.append({"ue": ue, "label": "MALICIOUS" if spec["role"] == "attack" else "BENIGN",
                             "backend": spec["backend"], "victim_mode": ph["victim_mode"],
                             "load": ph["load"], "congestion": ph["congestion"], "family": ph["family"],
                             "pair": spec.get("pair", ph.get("pair", ""))})
    import pandas as pd
    df = pd.DataFrame(rows)
    out = {"n_rows": len(df), "mal_fraction": round(float((df.label == "MALICIOUS").mean()), 4), "by": {}}
    out["by_pair"] = {str(k): {"MALICIOUS": int((g.label == "MALICIOUS").sum()),
                               "BENIGN": int((g.label == "BENIGN").sum())}
                      for k, g in df.groupby("pair")}
    for col in ("ue", "victim_mode", "load", "congestion"):
        pm = (df.label == "MALICIOUS").groupby(df[col]).mean()
        out["by"][col] = {str(k): round(float(v), 4) for k, v in pm.items()}
    # dual-use backends only
    du = df[df.backend.isin(DUAL_USE)]
    pm = (du.label == "MALICIOUS").groupby(du.backend).mean()
    out["by"]["backend(dual-use)"] = {str(k): round(float(v), 4) for k, v in pm.items()}
    out["backend_all"] = {str(k): round(float((g.label == "MALICIOUS").mean()), 4)
                          for k, g in df.groupby("backend")}
    # cells per section-6.3 family per UE (attacker side only)
    atk = df[df.label == "MALICIOUS"]
    out["cells_per_fam_ue"] = {fam: {ue: int(((atk.family == fam) & (atk.ue == ue)).sum())
                                     for ue in ("ue1", "ue2")}
                               for fam in sorted(atk.family.unique())}
    return out


def eta(man, overhead_s=80, warmup_s=15):
    total = 0
    for run in man["runs"]:
        total += warmup_s + overhead_s
        for ph in run:
            total += ph["duration"] + ph["gap"]
    return {"hours": round(total / 3600, 2), "runs": man["n_runs"], "phases": man["n_phases"],
            "avg_phase_s": round(sum(ph["duration"] for r in man["runs"] for ph in r) / man["n_phases"], 1)}


def cmd_plan(args):
    man = build_manifest(reps=args.reps, seed=args.seed)
    out = pathlib.Path("research/datasets/oran_flooding_v4/manifest")
    out.mkdir(parents=True, exist_ok=True)
    (out / "design.json").write_text(json.dumps(man, indent=1) + "\n")
    aud = audit_manifest(man)
    (out / "audit.json").write_text(json.dumps(aud, indent=1) + "\n")
    e = eta(man)
    print("# v4 Phase-3 campaign plan\n")
    print(f"runs={man['n_runs']}  phases={man['n_phases']}  reps={man['reps']}  "
          f"phases/run={man['phases_per_run']}  ETA≈{e['hours']} h  avg phase {e['avg_phase_s']} s\n")
    print("## Balance audit — P(malicious | factor), target 0.50\n")
    for col, d in aud["by"].items():
        print(f"- {col}: " + ", ".join(f"{k} {v:.2f}" for k, v in d.items()))
    print(f"\n(dual-use backend surplus after compensation: {_dualuse_row_surplus([ph for r in man['runs'] for ph in r])})")
    print("\n## Phases per section-6.3 family, per UE (attacker side; target ≥3)\n")
    print("| family | ue1 | ue2 |\n|---|---:|---:|")
    for fam, d in aud["cells_per_fam_ue"].items():
        print(f"| {fam} | {d['ue1']} | {d['ue2']} |")
    print(f"\nmeta_pair row counts (MAL / BEN): " +
          ", ".join(f"{k} {v['MALICIOUS']}/{v['BENIGN']}" for k, v in aud["by_pair"].items()))
    print(f"\nManifest: {out}/design.json  ·  audit: {out}/audit.json")
    print("Batch plan: batch 1 = first ceil(12%) runs -> auto qa_v4; STOP if nuisance-only AUC>0.6, "
          "P(mal|ue/backend)∉[0.45,0.55], achieved_ok<85%, or size-matched per-cell overlap<0.6; "
          "else batch 2 to ~50% checkpoint, then the rest.")


def cmd_audit(args):
    man = json.loads(pathlib.Path(args.manifest).read_text())
    print(json.dumps(audit_manifest(man), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sizes").set_defaults(fn=lambda a: cmd_sizes([]))
    pp = sub.add_parser("plan")
    pp.add_argument("--reps", type=int, default=3)
    pp.add_argument("--seed", type=int, default=20261020)
    pp.set_defaults(fn=cmd_plan)
    pa = sub.add_parser("audit")
    pa.add_argument("manifest")
    pa.set_defaults(fn=cmd_audit)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
