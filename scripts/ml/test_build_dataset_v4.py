#!/usr/bin/env python3
"""Unit tests for build_dataset_v4.py (Phase 1 §4). Synthetic fixtures only —
proves the causal-join logic without any cluster or captured data.

  .venv-ml/bin/python -I scripts/ml/test_build_dataset_v4.py
"""
import json, pathlib, tempfile, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_dataset_v4 as B
import numpy as np

T0 = 1_000_000


def write(run, name, recs):
    p = run / "raw"; p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text("".join(json.dumps(r) + "\n" for r in recs))


def kpm_rec(t, supi, thp):
    return {"source_ts": t, "arrival_ts": t, "supi": supi, "amf_ue_ngap_id": 1,
            "rate_ul_kbps": thp, "rate_dl_kbps": 0, "thp_ul_kbps": thp, "thp_dl_kbps": 0,
            "prb_ul_pct": 10, "prb_dl_pct": 0, "cell_prb_ul_pct": 10, "cell_prb_dl_pct": 0}


def make_run(tmp):
    run = pathlib.Path(tmp) / "20260101-000000_test"
    run.mkdir(parents=True)
    # KPM: ue 001 thp=100, ue 002 thp=200, every second T0..T0+9
    kpm = [kpm_rec(T0 + i, "001", 100) for i in range(10)] + \
          [kpm_rec(T0 + i, "002", 200) for i in range(10)]
    # age-cap hole for 001: no KPM between T0+4..T0+8 (last causal at T0+3 -> age grows)
    kpm = [r for r in kpm if not (r["supi"] == "001" and T0 + 4 <= r["source_ts"] <= T0 + 8)]
    write(run, "kpm.jsonl", kpm)
    # URR 001 cumulative with a RESET (counter goes down at T0+2 -> negative delta)
    urr = [
        {"source_ts": T0 + 0, "arrival_ts": T0 + 0, "supi": "001", "ul_bytes": 0, "dl_bytes": 0, "ul_packets": 0, "dl_packets": 0},
        {"source_ts": T0 + 1, "arrival_ts": T0 + 1, "supi": "001", "ul_bytes": 100000, "dl_bytes": 0, "ul_packets": 100, "dl_packets": 0},
        {"source_ts": T0 + 2, "arrival_ts": T0 + 2, "supi": "001", "ul_bytes": 500, "dl_bytes": 0, "ul_packets": 1, "dl_packets": 0},  # RESET
        {"source_ts": T0 + 3, "arrival_ts": T0 + 3, "supi": "001", "ul_bytes": 50500, "dl_bytes": 0, "ul_packets": 51, "dl_packets": 0},
    ]
    write(run, "urr.jsonl", urr)
    # profiler 001: a normal sample at T0+1, and a FUTURE-arriving sample (arrival T0+6) with a telltale value
    prof = [
        {"source_ts": T0 + 1, "arrival_ts": T0 + 1, "supi": "001", "prof_ul_kbps": 10, "prof_dl_kbps": 0,
         "prof_ul_pps": 5, "prof_dl_pps": 0, "prof_ul_mean_bytes": 250, "prof_dl_mean_bytes": 0,
         "prof_ul_tcp": 0, "prof_ul_tcp_syn": 0, "prof_ul_udp": 5, "prof_ul_icmp": 0, "prof_ul_frag": 0,
         "prof_ul_dns": 0, "prof_ul_gtp_in_gtp": 0, "prof_dl_tcp": 0, "prof_dl_tcp_syn": 0, "prof_dl_udp": 0,
         "prof_dl_icmp": 0, "prof_dl_frag": 0, "prof_ul_dst_estimate": 1},
        {"source_ts": T0 + 6, "arrival_ts": T0 + 6, "supi": "001", "prof_ul_kbps": 99999, "prof_dl_kbps": 0,
         "prof_ul_pps": 5, "prof_dl_pps": 0, "prof_ul_mean_bytes": 250, "prof_dl_mean_bytes": 0,
         "prof_ul_tcp": 0, "prof_ul_tcp_syn": 0, "prof_ul_udp": 5, "prof_ul_icmp": 0, "prof_ul_frag": 0,
         "prof_ul_dns": 0, "prof_ul_gtp_in_gtp": 0, "prof_dl_tcp": 0, "prof_dl_tcp_syn": 0, "prof_dl_udp": 0,
         "prof_dl_icmp": 0, "prof_dl_frag": 0, "prof_ul_dst_estimate": 1},
    ]
    write(run, "prof.jsonl", prof)
    flows = {"phases": [{"phase": "p1", "start": T0, "end": T0 + 10,
                         "ues": {"ue1": {"supi": "001", "attack_family": "udp_flood"},
                                 "ue2": {"supi": "002", "attack_family": None}}}]}
    (run / "flows.json").write_text(json.dumps(flows))
    return run


def main():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        run = make_run(tmp)
        rows = B.build_run(run, age_cap=3.0)
        by = {}
        for r in rows:
            by.setdefault(r["supi"], {})[r["t_unix"]] = r

        # 1) CAUSALITY: the future-arriving prof (arrival T0+6, value 99999) must never
        #    appear at any t < T0+6.
        leak = [t for t, r in by["001"].items() if t < T0 + 6 and r.get("prof_ul_kbps") == 99999]
        if leak:
            fails.append(f"causality: future prof used at t={leak}")

        # 2) URR non-negative despite a counter reset.
        negs = [(s, t, r.get("urr_ul_kbps")) for s in by for t, r in by[s].items()
                if r.get("urr_ul_kbps") is not None and not (isinstance(r["urr_ul_kbps"], float) and np.isnan(r["urr_ul_kbps"]))
                and r["urr_ul_kbps"] < 0]
        if negs:
            fails.append(f"urr delta negative: {negs[:3]}")

        # 3) UE JOIN: supi 001 rows carry thp 100, supi 002 carry 200, never swapped.
        bad001 = [t for t, r in by["001"].items() if r.get("thp_ul_kbps") == 200]
        bad002 = [t for t, r in by["002"].items() if r.get("thp_ul_kbps") == 100]
        if bad001 or bad002:
            fails.append(f"ue join mixed: 001@{bad001} 002@{bad002}")

        # 4) AGE CAP: at t=T0+8 the latest causal KPM for 001 is T0+3 (age 5 > 3) -> NaN.
        v = by["001"].get(T0 + 8, {}).get("thp_ul_kbps", None)
        if not (v is None or (isinstance(v, float) and np.isnan(v))):
            fails.append(f"age cap not applied: t=T0+8 thp={v}")

        # 5) SEPARATION: FEATURES and META are disjoint; label not a feature.
        if not set(B.FEATURES).isdisjoint(set(B.META)):
            fails.append("FEATURES and META overlap")
        if "label" in B.FEATURES:
            fails.append("label is in FEATURES")

        # 6) LABEL from schedule: 001 MALICIOUS (udp_flood), 002 BENIGN.
        if any(r["label"] != "MALICIOUS" for t, r in by["001"].items() if T0 <= t < T0 + 10):
            fails.append("001 not labelled MALICIOUS in phase")
        if any(r["label"] != "BENIGN" for t, r in by["002"].items() if T0 <= t < T0 + 10):
            fails.append("002 not labelled BENIGN in phase")

    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASSED (causality, urr-delta>=0, ue-join, age-cap, separation, labels)")


if __name__ == "__main__":
    main()
