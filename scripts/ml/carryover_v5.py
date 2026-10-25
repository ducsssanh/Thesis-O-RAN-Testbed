#!/usr/bin/env python3
"""v5 live: units that START a phase already at L3 (block carried over from the previous phase).

At every gap the harness resets the xApp level to 0, but the sidecar (not reset at gaps, by design)
still answers L3 for the last step of the phase just ended, so the xApp sets L3 again (model_level)
with a fresh 120 s expiry: the UE enters the next phase blocked. Marks every unit whose UE was at
level >= 3 at the phase start (first state-timeline sample in [t_start, t_start + 2 s]) and
recomputes the cells on the clean units.

  .venv-ml/bin/python -I scripts/ml/carryover_v5.py      (after live_eval_v5.py)
"""
import json, pathlib, sys
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live_eval_v5 as LE

REP = HERE.parents[1] / "research/datasets/oran_flooding_v5_live/reports"


def level_at_start(units):
    out, cache = [], {}
    for _, u in units.iterrows():
        rd = pathlib.Path(u.run)
        if rd not in cache:
            m = json.loads((rd / "run.json").read_text())
            cache[rd] = (m, LE.jsonl(rd / "defense/state_timeline.jsonl"))
        m, tl = cache[rd]
        t0 = next(p["t_start"] for p in m["phases"] if p["name"] == u.phase)
        supi = m["ues"][u.ue]["supi"]
        lv = [(r["ues"].get(supi) or {}).get("level") or 0 for r in tl if t0 <= r["t"] <= t0 + 2]
        out.append(lv[0] if lv else 0)
    return out


def main():
    U = pd.read_csv(REP / "live_units_v5.csv")
    U["level_at_start"] = level_at_start(U)
    U["carried_l3"] = (U.level_at_start >= 3).astype(int)
    U.to_csv(REP / "live_units_v5_carryover.csv", index=False)
    keys = ["attack_L1", "attack_L3", "benign_L3", "framed_benign_L3", "attack_delivered_frac", "benign_delivered_frac"]
    rows = []
    for (s, c), g in U[U.control == 0].groupby(["scenario", "config"]):
        a, b = LE.cell(g, 0), LE.cell(g[g.carried_l3 == 0], 0)
        rows.append({"scenario": s, "config": c, "units": len(g), "carried": int(g.carried_l3.sum()),
                     "carried_attack": int(g[g.mal == 1].carried_l3.sum()), "carried_benign": int(g[g.mal == 0].carried_l3.sum()),
                     **{k: a.get(k) for k in keys}, **{k + "_clean": b.get(k) for k in keys}})
    R = pd.DataFrame(rows)
    R.to_csv(REP / "carryover_v5.csv", index=False)
    pd.set_option("display.width", 250)
    print("units", int((U.control == 0).sum()), "carried L3", int(U[U.control == 0].carried_l3.sum()),
          "| icmp units", int((U.control == 1).sum()), "carried", int(U[U.control == 1].carried_l3.sum()))
    print(R[["scenario", "config", "units", "carried_attack", "carried_benign", "attack_L3", "attack_L3_clean",
             "benign_L3", "benign_L3_clean", "framed_benign_L3", "framed_benign_L3_clean"]].to_string(index=False))


if __name__ == "__main__":
    main()
