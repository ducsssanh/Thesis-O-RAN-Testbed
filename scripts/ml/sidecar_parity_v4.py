#!/usr/bin/env python3
"""Feature/decision parity of the live sidecar (stage B) with the offline v4 pipeline.

  .venv-ml/bin/python -I scripts/ml/sidecar_parity_v4.py [--runs N | --all] [--out DIR]

Replays recorded v4 test runs through sidecar_v4.Sidecar as the xApp would call it: for every UE and
grid second t (the rows of build_dataset_v4) one /classify request with now = t, the newest KPM
vector received by t, the latest URR record received by t with the receiver's ring of the last 16
(urr_receiver.c; the sidecar finds the URR period from it) and the latest profiler record received by
t. Checks, per run:
  rows      sidecar row == rows.parquet row (31 features + ages; NaN pattern identical)
  features  sidecar rolling vector == prep_v4_windows.rolling on the whole timeline (atol=rtol=1e-6),
            and == roll_v4.npz at the run's window ends
  scores    z of the 3 models (max |diff|)
  decisions hit / L1 / L3 / integrity / kpm_trust / core_trust of all 5 configurations == fusion_v4.run_engine
  latency   in-process /classify time p50 / p99 (budget p99 < 50 ms)
Also counts grid seconds without a new KPM vector (the live sidecar steps once per KPM vector, the
offline grid once per second: a structural live/offline difference, reported, not hidden).
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts/k8s/classifier"))
import prep_v4_windows as P
import fusion_v4 as F
import defence_engine_v4 as D
import sidecar_v4 as S

DATA = ROOT / "research/datasets/oran_flooding_v4"
WIN = ROOT / "artifacts/ml/v4"
EXP = ROOT / "artifacts/experiments"


def jsonl(p):
    out = []
    for line in pathlib.Path(p).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def requests(rd):
    """Simulated xApp requests {supi: [(t, req, new_kpm)]} on the build_dataset_v4 grid."""
    kpm = {}
    for r in jsonl(rd / "raw/kpm.jsonl"):
        if "arrival_ts" in r and "supi" in r:
            kpm.setdefault(r["supi"], []).append(r)
    urr = {}
    for o in jsonl(rd / "core/urr_received.jsonl"):          # file order = receipt order (urr_receiver.c)
        r = o.get("report") or {}
        if "supi" not in r or "observed_at" not in r or "received_unix_ms" not in o:
            continue
        urr.setdefault(r["supi"], []).append({"arrival": o["received_unix_ms"] / 1000.0, "rec": {
            "observed_at": r["observed_at"], "received_ms": o["received_unix_ms"], "seid": r.get("seid"),
            "session_epoch": r.get("session_epoch") or "", "ur_seqn": r.get("ur_seqn") or 0,
            "duration_seconds": r.get("duration_seconds"), "ul_bytes": r.get("ul_bytes") or 0, "dl_bytes": r.get("dl_bytes") or 0,
            "ul_packets": r.get("ul_packets") or 0, "dl_packets": r.get("dl_packets") or 0}})
    prof = {}
    for o in jsonl(rd / "core/core_received.jsonl"):
        if o.get("kind") != "profile" or "received_unix_ms" not in o:
            continue
        r = o.get("report") or {}
        if "supi" not in r or "observed_at" not in r:
            continue
        prof.setdefault(r["supi"], []).append({"arrival": o["received_unix_ms"] / 1000.0, "rec": {
            "observed_at": r["observed_at"], "received_ms": o["received_unix_ms"], "window_ms": r.get("window_ms") or 1000,
            **(r.get("body") or {})}})
    out = {}
    for supi, ks in kpm.items():
        ks = sorted(ks, key=lambda r: r["arrival_ts"])
        ka = np.array([r["arrival_ts"] for r in ks])
        us = sorted(urr.get(supi, []), key=lambda r: r["arrival"]); ua = np.array([r["arrival"] for r in us])
        ps = sorted(prof.get(supi, []), key=lambda r: r["arrival"]); pa = np.array([r["arrival"] for r in ps])
        seq_prev, lst = None, []
        for t in range(int(np.ceil(ka[0])), int(np.floor(ka[-1])) + 1):
            i = int(np.searchsorted(ka, t, side="right")) - 1
            k = ks[i]
            vec = {"seq": t, "at_ms": int(k["arrival_ts"] * 1000), "collect_ms": k["source_ts"] * 1000.0,
                   "amf_ue_ngap_id": k.get("amf_ue_ngap_id"), "e2_node": "replay",
                   **{c: k[c] for c in S.KPM if c in k}}
            j = int(np.searchsorted(ua, t, side="right")) - 1 if len(ua) else -1
            q = int(np.searchsorted(pa, t, side="right")) - 1 if len(pa) else -1
            ur = None
            if j >= 0:                                # latest URR + the receiver ring (URR_RING = 16)
                ur = dict(us[j]["rec"], history=[{"seq": x["rec"]["ur_seqn"], "session": x["rec"]["session_epoch"],
                                                  "duration": x["rec"]["duration_seconds"], "received_ms": x["rec"]["received_ms"]}
                                                 for x in us[max(0, j - 15):j + 1]])
            req = {"supi": supi, "since_seq": 0, "now_ms": t * 1000.0, "window": [vec],
                   "core": {"urr": ur, "prof": ps[q]["rec"] if q >= 0 else None}}
            lst.append((t, req, i != seq_prev))
            seq_prev = i
        out[supi] = lst
    return out


def close(a, b, atol=1e-6, rtol=1e-6):
    a, b = np.asarray(a, float), np.asarray(b, float)
    na, nb = np.isnan(a), np.isnan(b)
    ok = (na == nb) & (na | (np.abs(a - b) <= atol + rtol * np.abs(b)))
    d = np.where(na | nb, 0, np.abs(a - b))
    return ok, float(d.max()) if d.size else 0.0


def check_run(run, df_all, scorer, rule, roll, wins):
    rd = EXP / run
    reqs = requests(rd)
    sc = S.Sidecar(D.MODELS, "xd-trust-v2", log=None)
    sc.trace = []
    new_kpm = {}
    for supi in sorted(reqs):
        for t, req, nk in reqs[supi]:
            sc.classify(req)
            new_kpm[(supi, t)] = nk
    tr = sc.trace
    df = df_all[df_all.meta_run_id == run].sort_values(["meta_run_id", "meta_supi", "meta_t_unix"]).reset_index(drop=True)
    key_on = [(x["supi"], int(round(x["row"]["t"]))) for x in tr]
    key_off = list(zip(df.meta_supi, df.meta_t_unix.astype(int)))
    res = {"run": run, "rows_offline": len(df), "rows_sidecar": len(tr), "same_grid": key_on == key_off}
    if not res["same_grid"]:
        return res
    cols = scorer.spec["raw_features"]
    # rows
    agecols = {"kpm_age_s": "meta_kpm_age_s", "urr_age_s": "meta_urr_age_s", "prof_age_s": "meta_prof_age_s"}
    bad_rows = {}
    for c in cols:
        ok, _ = close([x["row"][c] for x in tr], df[c].to_numpy(float), 1e-9, 1e-9)
        if (~ok).any():
            bad_rows[c] = int((~ok).sum())
    for c, m in agecols.items():
        ok, dmax = close([x["row"][c] for x in tr], df[m].to_numpy(float), 2e-3, 0)
        if (~ok).any():
            bad_rows[c] = int((~ok).sum())
    res["row_mismatch"] = bad_rows
    # features
    X = P.transform(df, cols)
    Roff, names = P.rolling(df, X, cols)
    Ron = np.stack([x["R"] for x in tr])
    ok, dmax = close(Ron, Roff)
    res["feature_cells_mismatch"] = int((~ok).sum())
    res["feature_rows_mismatch"] = int((~ok.all(1)).sum())
    res["feature_max_abs_diff"] = dmax
    end, _ = P.windows(df, 10)
    m = wins == run
    ok2, dmax2 = close(Ron[end], roll[m])
    res["roll_v4_windows"] = int(m.sum())
    res["roll_v4_same_count"] = int(m.sum()) == len(end)
    res["roll_v4_cells_mismatch"] = int((~ok2).sum()) if len(end) == int(m.sum()) else None
    res["roll_v4_max_abs_diff"] = dmax2
    # scores
    zoff = scorer.z(Roff, names)
    res["z_max_abs_diff"] = {k: float(np.max(np.abs(np.array([x["z"][k] for x in tr]) - zoff[k]))) for k in zoff}
    zrel = {k: np.abs(np.array([x["z"][k] for x in tr]) - zoff[k]) for k in zoff}
    res["z_alarm_flips"] = {k: int(((np.array([x["z"][k] for x in tr]) >= 1) != (zoff[k] >= 1)).sum()) for k in zoff}
    # decisions
    tau, mm, bias = rule
    dmis = {}
    for mode, cfg in D.MODES.items():
        off = F.run_engine(df, zoff, cfg, tau, mm, bias)
        for k in ("hit", "l1", "l3", "integrity", "kt", "ct"):
            on = np.array([x["dec"][cfg][k] for x in tr], float)
            n = int((np.abs(on - off[k].astype(float)) > 1e-12).sum())
            if n:
                dmis["%s/%s" % (mode, k)] = n
    res["decision_mismatch"] = dmis
    lat = np.array([x["latency_ms"] for x in tr])
    res["latency_ms"] = {"p50": round(float(np.percentile(lat, 50)), 3), "p99": round(float(np.percentile(lat, 99)), 3),
                         "max": round(float(lat.max()), 3)}
    res["grid_seconds_without_new_kpm"] = int(sum(1 for v in new_kpm.values() if not v))
    res["attack_rows"] = int((df.label == "MALICIOUS").sum())
    res["l3_rows_v2"] = int(sum(x["dec"][D.CONFIGS[4]]["l3"] for x in tr))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(WIN / "sidecar_parity"))
    a = ap.parse_args()
    sp = json.loads((WIN / "meta.json").read_text())["split_runs"]["test"]
    runs = sp if a.all else sp[:a.runs]
    df_all = pd.read_parquet(DATA / "rows.parquet")
    scorer = D.Scorer()
    rule = D.load_rule()
    rl = np.load(WIN / "roll_v4.npz")
    wins = np.load(WIN / "windows_v4.npz")["run"]
    out = []
    for run in runs:
        r = check_run(run, df_all, scorer, rule, rl["R"], wins)
        print(json.dumps(r), flush=True)
        out.append(r)
    ok = all(r.get("same_grid") and not r["row_mismatch"] and r["feature_cells_mismatch"] == 0 and
             r["roll_v4_cells_mismatch"] == 0 and not r["decision_mismatch"] for r in out)
    lat99 = max(r["latency_ms"]["p99"] for r in out if "latency_ms" in r)
    summary = {"runs": len(out), "parity_ok": ok, "latency_p99_ms_max": lat99, "latency_ok": lat99 < 50}
    print(json.dumps(summary))
    o = pathlib.Path(a.out); o.mkdir(parents=True, exist_ok=True)
    (o / "parity.json").write_text(json.dumps({"summary": summary, "runs": out}, indent=1) + "\n")


if __name__ == "__main__":
    main()
