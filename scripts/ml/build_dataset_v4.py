#!/usr/bin/env python3
"""v4 causal dataset builder (Phase 1 of the v4 data-generation plan).

Builds per-second per-UE rows from RAW telemetry streams by a strictly CAUSAL
as-of join, fixing the v3 C5 leak (the xApp's ±1 s / +1 s *future* backfill). Does
NOT touch the cluster; consumes the raw logger's output.

Raw schema (one JSON object per line; ts are unix seconds, float):
  raw/kpm.jsonl  : {source_ts, arrival_ts, supi, amf_ue_ngap_id,
                    rate_ul_kbps, rate_dl_kbps, thp_ul_kbps, thp_dl_kbps,
                    prb_ul_pct, prb_dl_pct, cell_prb_ul_pct, cell_prb_dl_pct}
  raw/urr.jsonl  : {source_ts, arrival_ts, supi, ul_bytes, dl_bytes,
                    ul_packets, dl_packets}          # CUMULATIVE counters
  raw/prof.jsonl : {source_ts, arrival_ts, supi, prof_ul_kbps, prof_dl_kbps,
                    prof_ul_pps, prof_dl_pps, prof_ul_mean_bytes, prof_dl_mean_bytes,
                    prof_ul_tcp, prof_ul_tcp_syn, prof_ul_udp, prof_ul_icmp,
                    prof_ul_frag, prof_ul_dns, prof_ul_gtp_in_gtp,
                    prof_dl_tcp, prof_dl_tcp_syn, prof_dl_udp, prof_dl_icmp,
                    prof_dl_frag, prof_ul_dst_estimate}
  flows.json     : {phases: [{phase, start, end, ues: {ue: {supi, attack_family|null}}}]}

Causality guarantee: a feature at grid time t uses only records with
arrival_ts <= t. `*_age_s = t - source_ts` is recorded; if age > --age-cap the
value is NaN (never forward-filled indefinitely, never from the future).

Output: rows.parquet (+ rows.csv) with KPM/URR/prof features and meta_* columns.
meta_* and label are kept strictly OUT of the feature set.
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

KPM = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
       "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
URR = ["urr_ul_kbps", "urr_dl_kbps", "urr_ul_pps", "urr_dl_pps"]
PROF = ["prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps",
        "prof_ul_mean_bytes", "prof_dl_mean_bytes",
        "prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp",
        "prof_ul_frag", "prof_ul_dns", "prof_ul_gtp_in_gtp",
        "prof_dl_tcp", "prof_dl_tcp_syn", "prof_dl_udp", "prof_dl_icmp",
        "prof_dl_frag", "prof_ul_dst_estimate"]
FEATURES = KPM + URR + PROF
META = ["run_id", "supi", "ue", "phase", "label", "attack_family",
        "t_unix", "t_since_phase_start", "guard", "attack_active",
        "urr_age_s", "prof_age_s", "kpm_age_s"]


def read_jsonl(p):
    p = pathlib.Path(p)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def asof(records, t, key="arrival_ts"):
    """Latest record with record[key] <= t (causal). records sorted by key."""
    best = None
    for r in records:
        if r[key] <= t:
            best = r
        else:
            break
    return best


def urr_rate(prev, cur):
    """Non-negative rate from cumulative counters between two URR samples."""
    dt = cur["source_ts"] - prev["source_ts"]
    if dt <= 0:
        return None
    out = {}
    for src, kb in [("ul_bytes", "urr_ul_kbps"), ("dl_bytes", "urr_dl_kbps")]:
        d = cur[src] - prev[src]
        d = max(d, 0.0)                       # counter reset / reattach
        out[kb] = d * 8.0 / 1000.0 / dt
    for src, pp in [("ul_packets", "urr_ul_pps"), ("dl_packets", "urr_dl_pps")]:
        d = max(cur.get(src, 0) - prev.get(src, 0), 0.0)
        out[pp] = d / dt
    return out


def build_run(run_dir, age_cap, guard_s=3):
    run_dir = pathlib.Path(run_dir)
    kpm = sorted(read_jsonl(run_dir / "raw/kpm.jsonl"), key=lambda r: r["arrival_ts"])
    urr = sorted(read_jsonl(run_dir / "raw/urr.jsonl"), key=lambda r: r["arrival_ts"])
    prof = sorted(read_jsonl(run_dir / "raw/prof.jsonl"), key=lambda r: r["arrival_ts"])
    flows = json.loads((run_dir / "flows.json").read_text())
    run_id = run_dir.name
    supis = sorted({r["supi"] for r in kpm})

    def by_supi(recs):
        d = {}
        for r in recs:
            d.setdefault(r["supi"], []).append(r)
        return d
    kpm_s, urr_s, prof_s = by_supi(kpm), by_supi(urr), by_supi(prof)

    def phase_at(t):
        for p in flows["phases"]:
            if p["start"] <= t < p["end"]:
                return p
        return None

    rows = []
    for supi in supis:
        ks = kpm_s.get(supi, [])
        if not ks:
            continue
        us = urr_s.get(supi, [])
        ps = prof_s.get(supi, [])
        t0 = int(np.floor(ks[0]["arrival_ts"]))
        t1 = int(np.ceil(ks[-1]["arrival_ts"]))
        for t in range(t0, t1 + 1):
            kr = asof(ks, t)
            if kr is None:
                continue                      # no causal KPM yet
            row = {"t_unix": t, "supi": supi, "run_id": run_id,
                   "kpm_age_s": t - kr["source_ts"]}
            for f in KPM:
                row[f] = kr.get(f, np.nan) if (t - kr["source_ts"]) <= age_cap else np.nan
            # URR: causal as-of, rate from the two latest causal cumulative samples
            u_causal = [r for r in us if r["arrival_ts"] <= t]
            if len(u_causal) >= 2 and (t - u_causal[-1]["source_ts"]) <= age_cap:
                rate = urr_rate(u_causal[-2], u_causal[-1])
                row["urr_age_s"] = t - u_causal[-1]["source_ts"]
                for f in URR:
                    row[f] = rate[f] if rate else np.nan
            else:
                row["urr_age_s"] = np.nan
                for f in URR:
                    row[f] = np.nan
            # profiler: causal as-of
            pr = asof(ps, t)
            if pr is not None and (t - pr["source_ts"]) <= age_cap:
                row["prof_age_s"] = t - pr["source_ts"]
                for f in PROF:
                    row[f] = pr.get(f, np.nan)
            else:
                row["prof_age_s"] = np.nan
                for f in PROF:
                    row[f] = np.nan
            # label + meta from the experiment schedule (never from volume)
            ph = phase_at(t)
            if ph is None:
                row["label"] = "IDLE"; row["phase"] = ""; row["ue"] = ""
                row["attack_family"] = ""; row["t_since_phase_start"] = np.nan
                row["guard"] = 0; row["attack_active"] = 0
            else:
                ue = next((u for u, m in ph["ues"].items() if m["supi"] == supi), "")
                fam = ph["ues"].get(ue, {}).get("attack_family") if ue else None
                row["ue"] = ue; row["phase"] = ph["phase"]
                row["label"] = "MALICIOUS" if fam else "BENIGN"
                row["attack_family"] = fam or ""
                tss = t - ph["start"]
                row["t_since_phase_start"] = tss
                row["guard"] = int(tss < guard_s or (ph["end"] - t) <= guard_s)
                row["attack_active"] = int(bool(fam))
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--age-cap", type=float, default=3.0, help="max *_age_s before NaN")
    ap.add_argument("runs", nargs="+", help="run dirs with raw/ + flows.json")
    args = ap.parse_args()
    rows = []
    for rd in args.runs:
        rows += build_run(rd, args.age_cap)
    if not rows:
        sys.exit("no rows built")
    df = pd.DataFrame(rows)
    # enforce column separation: X = FEATURES only; meta_ prefix on metadata
    ren = {m: ("meta_" + m if m not in ("label",) else m) for m in META}
    df = df.rename(columns=ren)
    cols = [c for c in FEATURES if c in df.columns] + \
           [c for c in df.columns if c.startswith("meta_")] + ["label"]
    df = df[cols]
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "rows.parquet", index=False)
    df.to_csv(out / "rows.csv", index=False)
    n = len(df); b = int((df.label == "BENIGN").sum()); m = int((df.label == "MALICIOUS").sum())
    print(json.dumps({"rows": n, "benign": b, "malicious": m,
                      "idle": int((df.label == "IDLE").sum()),
                      "feature_cols": [c for c in FEATURES if c in df.columns],
                      "meta_cols": [c for c in df.columns if c.startswith("meta_")]}, indent=2))


if __name__ == "__main__":
    main()
