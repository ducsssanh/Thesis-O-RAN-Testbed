#!/usr/bin/env python3
"""Campaign manifest for the twinned dataset, fixed with a seed before any run (TRAFFIC-TWINNING-PLAN 5, execution plan Phase 6).
Size comes from what the evaluation reads per evasion level: 144 attack episodes per level give a detection rate of 0.90 to about +-5 % (95 %). A run has 6 phases of 75 s, so 432 phases = 72 runs,
about 10 min each. In every phase one UE runs its twin plus the attack, the other its twin; roles alternate inside a run. L3 phases give the other UE the same client as a benign hard negative
in the rhythm of a real window (no benign heavy-UL TCP backend follows a window; recorded as an assumption). Twin bands follow WEIGHTS. Only the step onset is used: hping3 cannot ramp, and
react needs the defence on, while the campaign runs with detection off.
Usage: design_twin.py [--out f.json] [--seed 20261104]"""
import argparse, json, pathlib
import numpy as np
ANCHORS = {"q0.90": 52536.0, "q0.95": 111088.0, "q0.99": 409856.0}
CELLS = [dict(evasion="L1", mode=m, anchor=a, victim="silent" if m == "udp" else "responsive", n=16) for m in ("udp", "syn", "icmp") for a in ANCHORS] + \
        [dict(evasion="L2", anchor=a, victim="silent", n=48) for a in ANCHORS] + \
        [dict(evasion="L3", backend=b, anchor=a, victim="responsive", n=24) for b in ("tcp_shortconn", "dns_client") for a in ANCHORS]
WEIGHTS = {"P1": .25, "P2": .25, "P3": .20, "P4": .30}   # TRAFFIC-TWINNING-PLAN 4.B; real Madrid about .50 .40 .09 .01
PHASES_PER_RUN = 6


def design(seed):
    rng = np.random.default_rng(seed)
    cells = [dict(c) for c in CELLS for _ in range(c["n"])]
    order = rng.permutation(len(cells))
    runs, s = [], 700000
    for r in range(len(cells) // PHASES_PER_RUN):
        phases = []
        for j, i in enumerate(order[r * PHASES_PER_RUN:(r + 1) * PHASES_PER_RUN]):
            c = {k: v for k, v in cells[i].items() if k != "n"}
            b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
            s += 10
            phases.append(dict(c, name="p%d" % (j + 1), attacker="ue%d" % (1 + (j + r) % 2), bands={"ue1": b[0], "ue2": b[1]}, seed=s))
        runs.append(dict(id="c%03d" % r, phases=phases))
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, phases_per_run=PHASES_PER_RUN, runs=runs)


def scenario(run):
    """The scenario of one manifest run for run.py."""
    phases = [{"name": "idle", "duration": 10}]
    for p in run["phases"]:
        fl = {}
        for k, ue in enumerate(("ue1", "ue2")):
            f = {"ul": {"v4": True, "model": "real_window", "backend": "pacer", "band": p["bands"][ue], "grid": "gnb", "timing": "tti", "role": "benign", "seed": p["seed"] + k + 1}}
            spec = {"v4": True, "evasion": p["evasion"], "anchor_bps": ANCHORS[p["anchor"]], "band": "P4", "timing": "tti", "victim_mode": p["victim"]}
            for x in ("mode", "backend"):
                if x in p:
                    spec[x] = p[x]
            if ue == p["attacker"]:
                f["ul_attack"] = dict(spec, role="attack", seed=p["seed"] + 5)
            elif p["evasion"] == "L3":
                f["ul_client"] = dict(spec, role="benign", seed=p["seed"] + 6)
            fl[ue] = f
        phases.append({"name": p["name"], "duration": 75, "attack": True, "flows": fl})
    return {"name": "ds-flood-twin-" + run["id"], "description": "Twin campaign run %s, research/datasets/oran_flooding_twin/manifest/design.json" % run["id"], "ues": {"ue1": "benign", "ue2": "benign"}, "reps": 1,
            "drain": {"quiet_kbps": 300, "timeout_s": 120}, "tail_s": 5, "variants": [{"name": "detection-off", "defense": {"enabled": False, "core": False}}], "phases": phases}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="research/datasets/oran_flooding_twin/manifest/design.json"); ap.add_argument("--seed", type=int, default=20261104)
    a = ap.parse_args()
    d = design(a.seed)
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d, indent=1) + "\n")
    print(len(d["runs"]), "runs", sum(len(r["phases"]) for r in d["runs"]), "phases")
