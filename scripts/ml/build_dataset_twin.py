#!/usr/bin/env python3
"""Dataset builder for the twin campaign (execution plan Phase 3, DRL design 5.2). Per UE, per measurement second: KPM and the profiler of that same second, their arrival times as data ages,
gate, per-second labels. No time-in-phase value or cumulative counter is a feature; t_window is meta for the replay environment only.

Inputs per run directory: raw/kpm.jsonl, core/core_received.jsonl (kind profile), run.json, traffic/flows.json. Usage: build_dataset_twin.py --out <dir> <run dir>..."""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_dataset_v4 import iso, jsonl, PROF_COUNTS
import tamper_replay as TR

KPM = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps", "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
PROF = ["prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps", "prof_ul_mean_bytes", "prof_dl_mean_bytes", "prof_ul_dst_estimate"] + \
       ["prof_ul_" + c for c in PROF_COUNTS] + ["prof_dl_" + c for c in PROF_COUNTS if c not in ("dns", "gtp_in_gtp")]
GATE = ["c_t", "c_t_w", "kpm_trust", "kpm_masked"]
FEATURES = KPM + PROF + GATE + ["kpm_trust_ue", "kpm_masked_ue", "kpm_age_s", "prof_age_s"]


def kpm_rows(run):
    out = {}
    for r in jsonl(run / "raw/kpm.jsonl"):
        if "arrival_ts" in r and "supi" in r:
            out[(r["supi"], int(np.floor(r["source_ts"])))] = r
    return out


def prof_rows(run):
    """The profile of one second, keyed by the second of observed_at, the one the xApp pairs with KPM."""
    out = {}
    for o in jsonl(run / "core/core_received.jsonl"):
        r = o.get("report") or {}
        if o.get("kind") != "profile" or "received_unix_ms" not in o or "supi" not in r or "observed_at" not in r:
            continue
        b = r.get("body") or {}
        w = (r.get("window_ms") or 1000) / 1000.0
        rec = {"arrival": o["received_unix_ms"] / 1000.0, "prof_ul_bytes": b.get("ul_bytes", 0), "prof_ul_pkts": b.get("ul_pkts", 0), "prof_window_s": w,
               "prof_ul_kbps": b.get("ul_bytes", 0) * 8 / 1000.0 / w, "prof_dl_kbps": b.get("dl_bytes", 0) * 8 / 1000.0 / w, "prof_ul_pps": b.get("ul_pkts", 0) / w, "prof_dl_pps": b.get("dl_pkts", 0) / w,
               "prof_ul_mean_bytes": b["ul_bytes"] / b["ul_pkts"] if b.get("ul_pkts") else 0.0, "prof_dl_mean_bytes": b["dl_bytes"] / b["dl_pkts"] if b.get("dl_pkts") else 0.0, "prof_ul_dst_estimate": b.get("ul_dst_estimate", 0.0)}
        for c in PROF_COUNTS:
            rec["prof_ul_" + c] = b.get("ul_" + c, 0)
            if c not in ("dns", "gtp_in_gtp"):
                rec["prof_dl_" + c] = b.get("dl_" + c, 0)
        out[(r["supi"], int(np.floor(iso(r["observed_at"]))))] = rec
    return out


def labels(run, ue_supi):
    """{(supi, second): label fields} from the flows actually run."""
    flows = json.loads((run / "traffic/flows.json").read_text())
    out = {}
    for f in flows:
        m = f.get("v4_meta") or {}
        if m.get("model") != "real_window":
            continue
        s0 = int(round(f["replay_start_at"]))
        for i in range(75):
            out[(ue_supi[f["ue"]], s0 + i)] = dict(phase=f["phase"], t_window=i, role="benign", attack_active=0, attack_bytes=0.0, onset_t=np.nan, band=m["band"], window_index=m["window"]["index"], seed=m["seed"], evasion="", vector="", anchor_bps=np.nan, attacker_ue="none", client_role="")
    for f in flows:
        m = f.get("v4_meta") or {}
        if m.get("model") != "flood_overlay":
            continue
        s0 = int(f["attack_start_at"]); supi = ue_supi[f["ue"]]
        active = m["attack_active"]
        attack = m.get("role", "attack") == "attack"
        onset = s0 + m["onset_s"]
        sent = {int(round(r["t"])): r.get("bytes") or 0.0 for r in f.get("rows") or []}
        for i, a in enumerate(active):
            k = (supi, s0 + i)
            if k not in out:
                continue
            if attack:
                out[k].update(role="attack", attack_active=int(a), attack_bytes=float(sent.get(s0 + i, 0.0)) if a else 0.0, onset_t=onset, evasion=m["evasion"], vector=f.get("mode") or f["backend"], anchor_bps=m["anchor_bps"])
            else:
                out[k]["client_role"] = f["backend"]
        if attack:
            for (s, t), v in out.items():
                if v["phase"] == f["phase"]:
                    v["attacker_ue"] = f["ue"]
    return out


def build_run(run, run_id=None):
    run = pathlib.Path(run)
    meta = json.loads((run / "run.json").read_text())
    ue_supi = {u: m["supi"] for u, m in meta["ues"].items()}
    supi_ue = {s: u for u, s in ue_supi.items()}
    K, P, L = kpm_rows(run), prof_rows(run), labels(run, ue_supi)
    rows = []
    for (supi, t), lab in sorted(L.items()):
        k, p = K.get((supi, t)), P.get((supi, t))
        row = {"run_id": run_id or str(run), "supi": supi, "ue": supi_ue[supi], "t_unix": t, **lab}
        for c in KPM:
            row[c] = k.get(c, np.nan) if k else np.nan
        row["kpm_age_s"] = k["arrival_ts"] - t if k else np.nan
        for c in PROF + ["prof_ul_bytes", "prof_ul_pkts", "prof_window_s"]:
            row[c] = p.get(c, np.nan) if p else np.nan
        row["prof_age_s"] = p["arrival"] - t if p else np.nan
        rows.append(row)
    df = pd.DataFrame(rows)
    df[["c_t", "c_t_w", "kpm_trust", "kpm_masked"]] = TR.gate(df, "node")
    u = TR.gate(df, "ue")
    df["kpm_trust_ue"], df["kpm_masked_ue"] = u["kpm_trust"], u["kpm_masked"]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True); ap.add_argument("runs", nargs="+")
    a = ap.parse_args()
    fr = []
    for r in a.runs:
        p = pathlib.Path(r)
        fr.append(build_run(p, "/".join(p.parts[-4:])))
    df = pd.concat(fr, ignore_index=True)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "rows.parquet", index=False)
    print(json.dumps({"rows": len(df), "runs": df.run_id.nunique(), "attack_active_s": int(df.attack_active.sum()), "no_kpm": round(float(df.rate_ul_kbps.isna().mean()), 4), "no_profile": round(float(df.prof_ul_kbps.isna().mean()), 4)}))


if __name__ == "__main__":
    main()
