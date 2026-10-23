#!/usr/bin/env python3
"""Two mini-simulations on the v4 test runs for model_eval_v4.md (offline, models frozen).

  .venv-ml/bin/python -I scripts/ml/mini_sim_v4.py [--boot 1000]

1. k-of-n alarm rule: each GBDT alone (activity-gated z >= 1), alarm when k of the last n seconds
   fire; phase level: attack phases detected, time to detect, benign phases with an alarm.
2. KPM tamper per model: the same detectors (3 of 5) when the attacker's KPM is deflated (hide x f)
   or a benign UE's KPM inflated (frame x f), as in fusion_v4.scenario: which single model a
   compromised E2 node blinds (hide) or turns against an innocent UE (frame).
Phase level, icmp control excluded, 95% bootstrap CI by run (detection / benign alarm).
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fusion_v4 as F
import v4_eval as E

OUT = HERE.parents[1] / "research/datasets/oran_flooding_v4/reports"
KN = [(1, 1), (2, 3), (3, 5), (4, 5), (5, 5)]
MODELS = ("xd", "core", "ran")


def gate(df, key):
    """10 s mean UL >= GATE_KBPS, as the engine gates: ran = KPM view, core = URR (else profiler) view,
    xd = core view while URR is fresh, else KPM view."""
    keys = [df.meta_run_id, df.meta_supi]
    roll = lambda s: s.groupby(keys, sort=False).transform(lambda x: x.rolling(10, min_periods=1).mean())
    ran = roll(df.rate_ul_kbps.fillna(0))
    core = roll(df.urr_ul_kbps.where(df.urr_ul_kbps.notna(), df.prof_ul_kbps))
    fresh = (df.meta_urr_age_s.fillna(99) <= F.D.CORE_AGE_S) & df.urr_ul_kbps.notna()
    ul = {"ran": ran, "core": core.where(fresh, np.nan), "xd": core.where(fresh, ran)}[key]
    return (ul >= F.GATE_KBPS).to_numpy()


def kofn(df, a, k, n):
    s = pd.Series(a.astype(int)).groupby([df.meta_run_id.to_numpy(), df.meta_supi.to_numpy()], sort=False)
    return (s.transform(lambda x: x.rolling(n, min_periods=1).sum()) >= k).to_numpy()


def phases(df, alarm, tampered):
    ph = df.meta_phase.fillna("")
    sel = ph.str.startswith("p") & (df.meta_pair != E.CONTROL) & df.label.isin(["BENIGN", "MALICIOUS"])
    t = df.meta_t_since_phase_start.to_numpy()
    rows = []
    for (run, ue, p), g in df[sel].groupby(["meta_run_id", "meta_ue", "meta_phase"], sort=False):
        ix = g.index.to_numpy()
        ix = ix[np.argsort(t[ix])]
        rows.append({"run": run, "mal": int(g.label.iloc[0] == "MALICIOUS"), "tampered": bool(tampered[ix].any()),
                     "alarm": bool(alarm[ix].any()), "t": float(t[ix][np.argmax(alarm[ix])]) if alarm[ix].any() else np.nan})
    return pd.DataFrame(rows)


def summ(pm, B, which=None):
    a, b = pm[pm.mal == 1], pm[pm.mal == 0]
    if which == "hide":
        a = a[a.tampered]
    if which == "frame":
        b = b[b.tampered]
    return {"attack_detected": round(a.alarm.mean(), 3), "ci_attack": F.boot(a, lambda x: x.alarm.mean(), B),
            "t_median": round(a.t.median(), 1) if a.alarm.any() else None,
            "benign_alarm": round(b.alarm.mean(), 3), "ci_benign": F.boot(b, lambda x: x.alarm.mean(), B)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000)
    a = ap.parse_args()
    spec, models = F.load_models()
    sp = json.loads((F.WIN / "meta.json").read_text())["split_runs"]
    base = pd.read_parquet(F.DATA / "rows.parquet")
    base = base[base.meta_run_id.isin(sp["test"])]
    res = {"kofn": {}, "tamper": {}}
    plan = [("honest", None)] + [("kpm_hide", f) for f in (0.1, 0.33, 0.5)] + [("kpm_frame", f) for f in (2.0, 5.0)]
    for sc, f in plan:
        df0, tmask = F.scenario(base, sc, f)
        df, R, names = F.features(df0)
        order = df0.sort_values(["meta_run_id", "meta_supi", "meta_t_unix"]).index
        tm = tmask.loc[order].to_numpy()
        z = F.score(df, R, names, spec, models)
        key = sc if f is None else "%s x%g" % (sc, f)
        for m in MODELS:
            hit = (z[m] >= 1) & gate(df, m)
            if sc == "honest":
                for k, n in KN:
                    res["kofn"].setdefault(m, {})["%d of %d" % (k, n)] = summ(phases(df, kofn(df, hit, k, n), tm), a.boot)
            res["tamper"].setdefault(key, {})[m] = summ(phases(df, kofn(df, hit, 3, 5), tm), a.boot,
                                                        "hide" if sc == "kpm_hide" else "frame" if sc == "kpm_frame" else None)
            print(key, m, res["tamper"][key][m], flush=True)
    (F.WIN / "mini_sim_v4.json").write_text(json.dumps(res, indent=1) + "\n")
    L = ["## Mini-simulations (added with stage B, offline, test runs, models frozen)\n",
         "Each GBDT alone, activity-gated alarm z ≥ 1, phase level (icmp control excluded); brackets = 95% bootstrap "
         "CI by run (`scripts/ml/mini_sim_v4.py`).\n",
         "### k-of-n alarm rule (honest telemetry)\n",
         "| model | rule | attack phases detected | median t (s) | benign phases with an alarm |", "|---|---|---:|---:|---:|"]
    for m in MODELS:
        for r, s in res["kofn"][m].items():
            L.append("| %s | %s | %s %s | %s | %s %s |" % (m, r, s["attack_detected"], s["ci_attack"], s["t_median"],
                                                         s["benign_alarm"], s["ci_benign"]))
    L += ["", "### KPM tamper per model (3 of 5)\n",
          "hide ×f: attacker's KPM UL deflated (detection on the tampered attack phases); frame ×f: a benign UE's KPM "
          "UL inflated (alarm on the framed benign phases).\n",
          "| scenario | model | attack detected | benign (framed) alarm |", "|---|---|---:|---:|"]
    for k, by in res["tamper"].items():
        for m, s in by.items():
            L.append("| %s | %s | %s %s | %s %s |" % (k, m, s["attack_detected"], s["ci_attack"], s["benign_alarm"], s["ci_benign"]))
    (F.WIN / "mini_sim_v4.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
