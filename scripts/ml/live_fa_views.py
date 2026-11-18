#!/usr/bin/env python3
"""False alarms of the live xApp shown as rates (benign UEs only, observe mode): per band and overall, (1) share of benign
episodes (one UE, one 75 s phase) with at least one decision, (2) share of benign seconds with a decision, (3) share of benign
uplink bytes (UPF profiler) carried in seconds with a decision, (4) alarms per benign UE-hour as before. Rate limit = attack
decision (want level >= 2), block = want level 3. Usage: live_fa_views.py <manifest dir> <rows.parquet of the same runs>"""
import json, pathlib, sys, runpy, io, contextlib
import numpy as np, pandas as pd
M, ROWS = sys.argv[1:3]
sys.argv = ["live_report.py", M, "/dev/null", "--boot", "1"]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(str(pathlib.Path(__file__).parent / "live_report.py"))
E, outcome = g["E"], g["outcome"]
r = pd.read_parquet(ROWS, columns=["supi", "t_unix", "phase", "run_id", "prof_ul_kbps"])
by = {}
for x in r.itertuples():
    by[(x.run_id.split("_ds-flood-live-")[1][:5] if "_ds-flood-live-" in x.run_id else x.run_id, x.phase, x.supi, int(x.t_unix))] = x.prof_ul_kbps
PI = {"P1": .50, "P2": .40, "P3": .09, "P4": .01}
rows = []
for e in E:
    if e["attack"]:
        continue
    # bytes per second of this benign episode, in time order (rows of the same phase and UE)
    k = [v for (rid, ph, s, t), v in by.items() if rid == e["run"] and ph == e["phase"] and s == e["supi"]]
    rows.append((e, k))
print("benign episodes", len(rows))


def stats(R, key):
    ep = np.mean([any(e[key]) for e, _ in R]) * 100
    sec = sum(sum(e[key]) for e, _ in R) / sum(len(e[key]) for e, _ in R) * 100
    tot = sum(np.nansum(b) for _, b in R)
    hit = sum(np.nansum([b[i] for i in range(min(len(b), len(e[key]))) if e[key][i]]) for e, b in R)
    o = [outcome(e, e[key]) for e, _ in R]
    h = sum(x["benign_s"] for x in o) / 3600
    return ep, sec, 100 * hit / tot if tot else np.nan, sum(x["early"] for x in o) / h


for key, name in (("soft", "Rate limit"), ("block", "Block")):
    print("\n%s: band | episodes with a false alarm | benign seconds flagged | benign UL bytes flagged | alarms per UE-hour" % name)
    agg = {}
    for b in ("P1", "P2", "P3", "P4"):
        R = [(e, x) for e, x in rows if e["band"] == b]
        s = stats(R, key); agg[b] = s
        print("  %s  n %3d | %5.1f %% | %5.2f %% | %5.2f %% | %.2f" % (b, len(R), *s))
    s = stats(rows, key)
    print("  all n %3d | %5.1f %% | %5.2f %% | %5.2f %% | %.2f" % (len(rows), *s))
    w = [sum(PI[b] * agg[b][i] for b in PI) for i in range(4)]
    print("  real band mix  | %5.1f %% | %5.2f %% | %5.2f %% | %.2f" % tuple(w))
