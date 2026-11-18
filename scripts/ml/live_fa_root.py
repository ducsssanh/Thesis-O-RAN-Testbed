#!/usr/bin/env python3
"""Root cause of the live false alarms (2026-11-10): for every false alarm of an operating point (first decision of a benign
episode, or of an attack episode before its onset), the UE's state at the alarm: band, its KPM-gate state (trust, masked) at
the phase start and at the alarm, whether the same UE was tampered (attacker with a mimic/hide case) in the previous run, and
the top feature contributions of the embedded ensemble (xgboost pred_contribs, mean over seeds, / T) at the alarm second.
Also: benign seconds that start a phase masked, split by whether the UE was tampered in the previous run.
Usage: live_fa_root.py <manifest dir> <model dir with fold*_seed*> [soft|block] > out.txt"""
import contextlib, glob, io, json, pathlib, runpy, sys
import numpy as np
import xgboost as xgb
M, MD = sys.argv[1:3]; KEY = sys.argv[3] if len(sys.argv) > 3 else "block"
sys.argv = ["live_report.py", M, "/dev/null", "--boot", "1"]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(str(pathlib.Path(__file__).parent / "live_report.py"))
E, outcome, kept, design = g["E"], g["outcome"], g["kept"], g["design"]
order = [json.loads(l)["id"] for l in open(pathlib.Path(M) / "campaign_log.jsonl") if '"event": "kept"' in l]
prev = {order[i]: (order[i - 1] if i else None) for i in range(len(order))}
B = []
for d in sorted(glob.glob(MD.rstrip("/") + "/fold*_seed*")):
    b = xgb.Booster(); b.load_model(d + "/model.json"); B.append((b, json.load(open(d + "/config.json"))["temperature"]))
import os
NAMES = json.load(open(os.environ.get("CLF_MODEL", "artifacts/clf/mimic/export_e3/clf_model.json")))["features"]


def tampered(rid, ue):
    """case of `ue` in run rid if it was a tampered attacker there, else ''"""
    if rid is None:
        return ""
    r = design[rid]
    cases = {p.get("case", "") for p in r["phases"] if p.get("attacker") == ue and p.get("case") not in (None, "", "honest")}
    return ",".join(sorted(cases))


X = {}   # (run, supi, t) -> x, from the run's clf.jsonl


def xrec(rid, supi, s0):
    key = (rid, supi)
    if key not in X:
        X[key] = {}
        for l in open(pathlib.Path(kept[rid]) / "defense/clf.jsonl"):
            o = json.loads(l)
            if o["supi"] == supi:
                X[key][o["t"]] = o
    return X[key]


def contribs(x):
    c = np.mean([b.predict(xgb.DMatrix(np.asarray([x], np.float32)), pred_contribs=True)[0] / T for b, T in B], 0)
    return c


fa = []
for e in E:
    o = outcome(e, e[KEY])
    if not o["early"]:
        continue
    first = next(t for t, v in enumerate(e[KEY]) if v)
    fa.append((e, first))
print("%s false alarms: %d over %d episodes" % (KEY, len(fa), len(E)))
for e, t in fa:
    run = pathlib.Path(kept[e["run"]]); meta = json.loads((run / "run.json").read_text())
    flows = json.loads((run / "traffic/flows.json").read_text())
    f = next(x for x in flows if x["phase"] == e["phase"] and x["ue"] == e["ue"] and (x.get("v4_meta") or {}).get("model") == "real_window")
    s0 = int(np.floor(f["replay_start_at"])) + 1
    rec = xrec(e["run"], e["supi"], s0)
    o = rec.get(s0 + t); o0 = rec.get(s0)
    pt = tampered(prev[e["run"]], e["ue"]); ct = tampered(e["run"], e["ue"])
    c = contribs(o["x"]) if o else None
    top = sorted(range(len(c) - 1), key=lambda i: -c[i])[:5] if c is not None else []
    print("\n%s %s %s band %s attack=%s on=%s alarm at %ds z=%.2f | phase-start trust %.3f masked %s | at alarm trust %.3f masked %s | "
          "masked share of episode %.2f | tampered here: %s | tampered in previous run (%s): %s" % (
              e["run"], e["phase"], e["ue"], e["band"], e["attack"], e["on"], t, o["z"] if o else np.nan, o0["trust"] if o0 else np.nan,
              o0["masked"] if o0 else None, o["trust"] if o else np.nan, o["masked"] if o else None, np.mean(e["masked"]), ct or "-",
              prev[e["run"]], pt or "-"))
    if c is not None:
        print("   bias %.2f; top contributions: %s" % (c[-1], ", ".join("%s %+.2f (x=%.3g)" % (NAMES[i] if NAMES else i, c[i], o["x"][i]) for i in top)))
    zs = [rec[s0 + k]["z"] if (s0 + k) in rec else np.nan for k in range(max(0, t - 12), t + 1)]
    print("   z over the 12 s before: " + " ".join("%.1f" % z for z in zs))

# benign UE-phases that start masked, by whether the UE was tampered in the previous run
print("\nBenign episodes (not attackers) by gate state at phase start:")
rows = []
for e in E:
    if e["attack"]:
        continue
    o = outcome(e, e[KEY])
    pt = tampered(prev[e["run"]], e["ue"]) if e["phase"] == "p1" else tampered(e["run"], e["ue"])
    rows.append((e["masked"][0], bool(pt), o["early"], e["band"]))
for m in (False, True):
    for p in (False, True):
        S = [r for r in rows if r[0] == m and r[1] == p]
        if S:
            print("  masked at start=%s, tampered just before=%s: %d episodes, %d with a %s false alarm" % (m, p, len(S), sum(r[2] for r in S), KEY))
