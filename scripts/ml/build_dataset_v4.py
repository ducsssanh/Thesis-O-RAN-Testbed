#!/usr/bin/env python3
"""v4 causal dataset builder (Phase 1 of the v4 data-generation plan).

Builds per-second per-UE rows from the RAW telemetry a harness run collects, by a
strictly CAUSAL as-of join. Fixes the v3 C5 leak: the xApp's features.jsonl
matched URR/profiler to the KPM second by window time with a +/-1 s (incl. +1 s =
future) fallback, ignoring when the record actually arrived.

Inputs, per run directory (artifacts/experiments/<campaign>/runs/<variant>/rep-NN,
as written by scripts/k8s/exp/run.py + collect.py):
  raw/kpm.jsonl            xApp raw KPM tap: {source_ts, arrival_ts, supi, amf_ue_ngap_id,
                           rate_*_kbps, thp_*_kbps, prb_*_pct, cell_prb_*_pct}
  core/urr_received.jsonl  URR at the xApp: report.{observed_at, supi, session_epoch, ur_seqn,
                           ul/dl_bytes, ul/dl_packets (PER-PERIOD volumes), duration_seconds
                           (CUMULATIVE)}; received_unix_ms (ms arrival; older images only have
                           second-precision received_at -> padded +1 s, flagged)
  core/core_received.jsonl kind=profile: report.{observed_at, supi, window_ms, body{...}};
                           received_unix_ms
  run.json                 phases [{name, t_start, t_end}], ues {ue: {supi}}
  traffic/flows.json       [{phase, ue, attack: family|null, ...}]  (experimental control)

Causality: a feature at grid second t uses only records with arrival_ts <= t;
*_age_s = t - source_ts, value NaN beyond --age-cap. URR rate follows the xApp's
semantics (volume / measurement period, period = delta of the cumulative
duration within one PDU session), computed from causal records only.
Labels come only from the experiment schedule: MALICIOUS if the UE ran an attack
flow in the phase, BENIGN if it ran only benign flows, IDLE otherwise (gaps,
warm-up, a UE with no flow) -- IDLE is never merged into BENIGN.
Output: rows.parquet + rows.csv; features in FEATURES, metadata as meta_*.
"""
import argparse, bisect, datetime, json, pathlib, sys
import numpy as np, pandas as pd

KPM = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps",
       "prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct"]
URR = ["urr_ul_kbps", "urr_dl_kbps", "urr_ul_pps", "urr_dl_pps"]
PROF_COUNTS = ["tcp", "tcp_syn", "udp", "icmp", "frag", "dns", "gtp_in_gtp"]
PROF = ["prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps",
        "prof_ul_mean_bytes", "prof_dl_mean_bytes"] + \
       ["prof_ul_" + c for c in PROF_COUNTS] + \
       ["prof_dl_" + c for c in PROF_COUNTS if c not in ("dns", "gtp_in_gtp")] + \
       ["prof_ul_dst_estimate"]
FEATURES = KPM + URR + PROF
META = ["run_id", "supi", "ue", "phase", "attack_family", "t_unix", "t_since_phase_start",
        "guard", "attack_active", "kpm_age_s", "urr_age_s", "prof_age_s", "urr_arrival_exact"]


def iso(s):
    """ISO-8601 (optionally with ns fraction, Z) -> unix seconds float."""
    s = s.rstrip("Z")
    frac = 0.0
    if "." in s:
        s, f = s.split(".", 1)
        frac = float("0." + f)
    dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp() + frac


def jsonl(p):
    p = pathlib.Path(p)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


# ------------------------------------------------------------------ loaders
def load_kpm(run):
    return [r for r in jsonl(run / "raw/kpm.jsonl") if "arrival_ts" in r and "supi" in r]


def load_urr(run):
    out = []
    for o in jsonl(run / "core/urr_received.jsonl"):
        r = o.get("report") or {}
        if "supi" not in r or "observed_at" not in r:
            continue
        exact = "received_unix_ms" in o
        arrival = o["received_unix_ms"] / 1000.0 if exact else iso(o["received_at"]) + 1.0
        out.append({"source_ts": iso(r["observed_at"]), "arrival_ts": arrival, "exact": exact,
                    "supi": r["supi"], "session": r.get("session_epoch") or "", "seq": r.get("ur_seqn") or 0,
                    "duration": r.get("duration_seconds"), "ul_bytes": r.get("ul_bytes") or 0,
                    "dl_bytes": r.get("dl_bytes") or 0, "ul_packets": r.get("ul_packets") or 0,
                    "dl_packets": r.get("dl_packets") or 0})
    return out


def load_prof(run):
    out = []
    for o in jsonl(run / "core/core_received.jsonl"):
        if o.get("kind") != "profile" or "received_unix_ms" not in o:
            continue
        r = o.get("report") or {}
        b = r.get("body") or {}
        if "supi" not in r or "observed_at" not in r:
            continue
        w = (r.get("window_ms") or 1000) / 1000.0
        rec = {"source_ts": iso(r["observed_at"]), "arrival_ts": o["received_unix_ms"] / 1000.0, "supi": r["supi"],
               "prof_ul_kbps": b.get("ul_bytes", 0) * 8 / 1000.0 / w,
               "prof_dl_kbps": b.get("dl_bytes", 0) * 8 / 1000.0 / w,
               "prof_ul_pps": b.get("ul_pkts", 0) / w, "prof_dl_pps": b.get("dl_pkts", 0) / w,
               "prof_ul_mean_bytes": b["ul_bytes"] / b["ul_pkts"] if b.get("ul_pkts") else 0.0,
               "prof_dl_mean_bytes": b["dl_bytes"] / b["dl_pkts"] if b.get("dl_pkts") else 0.0,
               "prof_ul_dst_estimate": b.get("ul_dst_estimate", 0.0)}
        for c in PROF_COUNTS:
            rec["prof_ul_" + c] = b.get("ul_" + c, 0)
            if c not in ("dns", "gtp_in_gtp"):
                rec["prof_dl_" + c] = b.get("dl_" + c, 0)
        out.append(rec)
    return out


def load_schedule(run):
    meta = json.loads((run / "run.json").read_text())
    flows = json.loads((run / "traffic/flows.json").read_text()) if (run / "traffic/flows.json").exists() else []
    ue_supi = {ue: m["supi"] for ue, m in (meta.get("ues") or {}).items()}
    phases = []
    for p in meta.get("phases") or []:
        per_ue = {}
        for ue in ue_supi:
            fl = [f for f in flows if f.get("phase") == p["name"] and f.get("ue") == ue]
            fams = sorted({f["attack"] for f in fl if f.get("attack")})
            label = "MALICIOUS" if fams else ("BENIGN" if fl else "IDLE")
            per_ue[ue] = {"label": label, "family": "+".join(fams)}
        phases.append({"name": p["name"], "start": p["t_start"], "end": p["t_end"], "ues": per_ue})
    return ue_supi, phases


# ------------------------------------------------------------------ causal join
class AsOf:
    """Records of one SUPI sorted by arrival; latest with arrival_ts <= t."""
    def __init__(self, recs):
        self.recs = sorted(recs, key=lambda r: r["arrival_ts"])
        self.keys = [r["arrival_ts"] for r in self.recs]

    def upto(self, t):
        return bisect.bisect_right(self.keys, t)          # number of causal records

    def latest(self, t):
        n = self.upto(t)
        return self.recs[n - 1] if n else None


def urr_at(idx, t):
    """xApp URR semantics from causal records only: volume / delta(cumulative duration)."""
    n = idx.upto(t)
    if not n:
        return None, None
    last = idx.recs[n - 1]
    prev = None
    for r in reversed(idx.recs[:n - 1]):                # causal predecessor in the same session
        if r["session"] == last["session"] and r["seq"] < last["seq"]:
            prev = r
            break
    if prev is None or last["duration"] is None or prev["duration"] is None:
        return last, None
    period = last["duration"] - prev["duration"]
    if period <= 0:
        return last, None
    return last, {"urr_ul_kbps": max(last["ul_bytes"], 0) * 8 / 1000.0 / period,
                  "urr_dl_kbps": max(last["dl_bytes"], 0) * 8 / 1000.0 / period,
                  "urr_ul_pps": max(last["ul_packets"], 0) / period,
                  "urr_dl_pps": max(last["dl_packets"], 0) / period}


def build_run(run, age_cap=3.0, guard_s=3, run_id=None, core_age_cap=4.0):
    """age_cap applies to KPM; core_age_cap to URR/profiler (A1-EI path lag ~2 s, p99 ~3.8 s)."""
    run = pathlib.Path(run)
    ue_supi, phases = load_schedule(run)
    supi_ue = {s: u for u, s in ue_supi.items()}
    group = lambda recs: {s: AsOf([r for r in recs if r["supi"] == s]) for s in {r["supi"] for r in recs}}
    kpm, urr, prof = group(load_kpm(run)), group(load_urr(run)), group(load_prof(run))
    rows = []
    for supi, kidx in sorted(kpm.items()):
        if not kidx.recs:
            continue
        uidx, pidx = urr.get(supi, AsOf([])), prof.get(supi, AsOf([]))
        ue = supi_ue.get(supi, "")
        for t in range(int(np.ceil(kidx.keys[0])), int(np.floor(kidx.keys[-1])) + 1):
            k = kidx.latest(t)
            row = {"run_id": run_id or str(run), "supi": supi, "ue": ue, "t_unix": t,
                   "kpm_age_s": t - k["source_ts"]}
            ok = row["kpm_age_s"] <= age_cap
            for f in KPM:
                row[f] = k.get(f, np.nan) if ok else np.nan
            u, rate = urr_at(uidx, t)
            row["urr_age_s"] = (t - u["source_ts"]) if u else np.nan
            row["urr_arrival_exact"] = int(u["exact"]) if u else np.nan
            ok = u is not None and rate is not None and row["urr_age_s"] <= core_age_cap
            for f in URR:
                row[f] = rate[f] if ok else np.nan
            p = pidx.latest(t)
            row["prof_age_s"] = (t - p["source_ts"]) if p else np.nan
            ok = p is not None and row["prof_age_s"] <= core_age_cap
            for f in PROF:
                row[f] = p.get(f, np.nan) if ok else np.nan
            ph = next((x for x in phases if x["start"] <= t < x["end"]), None)
            lab = ph["ues"].get(ue) if ph else None
            row["phase"] = ph["name"] if ph else ""
            row["label"] = lab["label"] if lab else "IDLE"
            row["attack_family"] = lab["family"] if lab else ""
            row["attack_active"] = int(row["label"] == "MALICIOUS")
            row["t_since_phase_start"] = t - ph["start"] if ph else np.nan
            row["guard"] = int(bool(ph) and (t - ph["start"] < guard_s or ph["end"] - t <= guard_s))
            rows.append(row)
    return rows


def to_frame(rows):
    df = pd.DataFrame(rows)
    df = df.rename(columns={m: "meta_" + m for m in META})
    cols = [c for c in FEATURES if c in df.columns] + sorted(c for c in df.columns if c.startswith("meta_")) + ["label"]
    return df[cols]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--age-cap", type=float, default=3.0, help="KPM max age (s)")
    ap.add_argument("--core-age-cap", type=float, default=4.0, help="URR/profiler max age (s)")
    ap.add_argument("runs", nargs="+", help="run dirs (runs/<variant>/rep-NN)")
    a = ap.parse_args()
    rows = []
    for rd in a.runs:
        rd = pathlib.Path(rd)
        if not (rd / "raw/kpm.jsonl").exists():
            print("skip (no raw/kpm.jsonl -- pre-v4 run):", rd, file=sys.stderr)
            continue
        rows += build_run(rd, a.age_cap, run_id="/".join(rd.parts[-4:]), core_age_cap=a.core_age_cap)
    if not rows:
        sys.exit("no rows built")
    df = to_frame(rows)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "rows.parquet", index=False)
    df.to_csv(out / "rows.csv", index=False)
    print(json.dumps({"rows": len(df), **df["label"].value_counts().to_dict(),
                      "urr_present": round(float(df["urr_ul_kbps"].notna().mean()), 3),
                      "prof_present": round(float(df["prof_ul_kbps"].notna().mean()), 3)}, indent=2))


if __name__ == "__main__":
    main()
