#!/usr/bin/env python3
"""v5 live (stage B) design manifest: the cross-domain defence ON in the testbed, scenarios x
configurations x repetitions, pre-registered before any run.

  python3 scripts/k8s/exp/v4traffic/design_v5.py [--reps 6] [--seed 20261024] [--out research/datasets/oran_flooding_v5_live/manifest/design.json]

Traffic (design.py generators, fresh seeds — never the v4 flows the models were trained on):
  a run = 4 phases of 60 s with 15 s gaps: two attack pairs, each mirrored (ue1 attacks, then ue2),
  the benign counterpart load-matched on the other UE (design.py _emit_pair). The pairs rotate over
  the reps so each of udp, syn, dns, pulsing, mimicry and fanout appears in 2 of the 6 reps; load
  cycles 0.4/0.8/1.2 Mbit/s, victim mode alternates, no N6 congestion. icmp_control runs = the
  icmp_flood~icmp_ping pair mirrored (2 phases).
  The traffic of a rep is the SAME for every scenario and configuration (paired comparisons).
Scenarios (phase annotations the harness applies; the dataset labels never change):
  honest            telemetry as is
  kpm_hide_x0.1/0.33 attacker UE's KPM UL rate/throughput/PRB x f at xApp ingest during attack phases
  kpm_frame_x2/x5   benign UE's KPM UL x f (PRB capped at 100 %) during attack phases
  core_outage       A1-EI adapter scaled to 0 for phases 0 and 3 (URR + profiler absent), back to 1 after
  icmp_control      negative control pair, honest telemetry
Configurations: rules-v1 (xApp classifier v1, its own ladder) and the sidecar modes ran-only,
core-only, xd-naive, xd-trust-v1, xd-trust-v2 (main). Defence timing (all configs): L1 expiry 3 s
(refreshed by every attack label, so L1 holds while the alarm holds, as in the replay), L3 expiry
120 s, no repeat-offence ladder for the sidecar modes (probation 0; the sidecar decides L3), no RRC
release (UPF block only), defence state reset (levels, tamper) at every gap; the sidecar state is
reset only at the run start (its rolling history and trust carry over like the replay's).
Run order: rep-major; within a rep the scenario x config cells in a seeded random order.
"""
import argparse, json, pathlib, random, sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import design as D4

ROOT = HERE.parents[3]
OUT = ROOT / "research/datasets/oran_flooding_v5_live/manifest/design.json"
PHASE_S, GAP_S = 60, 15
ROTATION = [("udp", "syn"), ("dns", "pulsing"), ("mimicry", "fanout"), ("udp", "dns"), ("syn", "pulsing"), ("mimicry", "fanout")]
LOADS = [0.4, 0.8, 1.2]
SCENARIOS = {
    "honest": {},
    "kpm_hide_x0.1": {"tamper": "attacker", "factor": 0.1},
    "kpm_hide_x0.33": {"tamper": "attacker", "factor": 0.33},
    "kpm_frame_x2": {"tamper": "benign", "factor": 2.0},
    "kpm_frame_x5": {"tamper": "benign", "factor": 5.0},
    "core_outage": {"core_outage_phases": [0, 3]},
    "icmp_control": {"icmp": True},
}
CONFIGS = ["rules-v1", "ran-only", "core-only", "xd-naive", "xd-trust-v1", "xd-trust-v2"]
_COMMON = {"enabled": True, "core": True, "mode": "slice", "clear_tamper": True}
_TIMING_SIDECAR = {"expiryS": [3, 3, 120, 0], "probationS": 0, "fusionS": 10, "releaseOnBlock": False}
DEFENSE = {c: {**_COMMON, "classifier": "external", "sidecar_mode": c, "timing": _TIMING_SIDECAR} for c in CONFIGS[1:]}
DEFENSE["rules-v1"] = {**_COMMON, "classifier": "rules",
                       "timing": {"expiryS": [3, 3, 120, 0], "probationS": 180, "fusionS": 10, "releaseOnBlock": False}}


def fam(key):
    return next(f for f in D4.FAMILIES if f["key"] == key)


def rep_traffic(r, seeder, rng):
    """(attack phases, icmp phases) of rep r (0-based); durations/gaps fixed."""
    load, victim = LOADS[r % 3], D4.VICTIMS[r % 2]

    def mirrored(key, cellid):
        f = fam(key)
        tool = f["atk_tools"][r % len(f["atk_tools"])]
        out = []
        for ue in ("ue1", "ue2"):
            ph = D4._emit_pair(f, tool, load, victim, 0, ue, seeder, cellid, rng)
            ph["duration"], ph["gap"] = PHASE_S, GAP_S
            out.append(ph)
        return out
    a, b = ROTATION[r]
    return mirrored(a, 10_000 + 10 * r) + mirrored(b, 10_000 + 10 * r + 1), mirrored("icmp", 10_000 + 10 * r + 2)


def annotate(phases, scn):
    s = SCENARIOS[scn]
    out = []
    for j, ph in enumerate(phases):
        ph = json.loads(json.dumps(ph))
        if "tamper" in s:
            atk = ph["attacker_ue"]
            ue = atk if s["tamper"] == "attacker" else ("ue2" if atk == "ue1" else "ue1")
            ph["tamper"] = {"ue": ue, "factor": s["factor"]}
        if j in s.get("core_outage_phases", []):
            ph["core_outage"] = True
        out.append(ph)
    return out


def build(reps, seed):
    rng = np.random.default_rng(seed)
    seeder = D4._Seeder(seed * 10)
    order = random.Random(seed)
    runs = []
    for r in range(reps):
        atk, icmp = rep_traffic(r, seeder, rng)
        cells = [(s, c) for s in SCENARIOS for c in CONFIGS]
        order.shuffle(cells)
        for s, c in cells:
            runs.append({"id": len(runs) + 1, "rep": r + 1, "scenario": s, "config": c, "defense": DEFENSE[c],
                         "phases": annotate(icmp if SCENARIOS[s].get("icmp") else atk, s)})
    return {"seed": seed, "reps": reps, "scenarios": list(SCENARIOS), "configs": CONFIGS, "phase_s": PHASE_S, "gap_s": GAP_S,
            "rotation": ROTATION, "n_runs": len(runs), "defense": DEFENSE, "runs": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261024)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    m = build(a.reps, a.seed)
    out = pathlib.Path(a.out)
    if out.exists():
        sys.exit("%s exists: the manifest is pre-registered, never overwritten" % out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, indent=1) + "\n")
    print(json.dumps({"runs": m["n_runs"], "per_cell": a.reps, "cells": len(SCENARIOS) * len(CONFIGS)}))


if __name__ == "__main__":
    main()
