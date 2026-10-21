#!/usr/bin/env python3
"""Unit tests for build_dataset_v4.py (Phase 1 §4) on synthetic fixtures in the
harness-native run layout. No cluster, no captured data.

  .venv-ml/bin/python -I scripts/ml/test_build_dataset_v4.py
"""
import datetime, json, math, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_dataset_v4 as B

T0 = 1_792_413_850
A, Bs = "imsi-001010123456780", "imsi-001010123456781"


def iso(t, frac=True):
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + (".%09dZ" % round((t % 1) * 1e9) if frac else "Z")


def kpm(t, supi, thp):
    return {"source_ts": t + 0.1999, "arrival_ts": t + 0.2005, "supi": supi, "amf_ue_ngap_id": 3,
            "rate_ul_kbps": thp, "rate_dl_kbps": 0.0, "thp_ul_kbps": thp, "thp_dl_kbps": 0.0,
            "prb_ul_pct": 2.0, "prb_dl_pct": 0.0, "cell_prb_ul_pct": 4.0, "cell_prb_dl_pct": 0.0}


def urr(supi, seq, dur, ul, observed, arrival=None, session="S1", legacy_second=None):
    o = {"event_id": f"{supi}:{seq}", "report": {"observed_at": iso(observed), "supi": supi, "session_epoch": session,
         "ur_seqn": seq, "duration_seconds": dur, "ul_bytes": ul, "dl_bytes": 0, "ul_packets": ul // 1000, "dl_packets": 0}}
    if legacy_second is not None:
        o["received_at"] = iso(legacy_second, frac=False)
    else:
        o["received_at"] = iso(int(arrival), frac=False)
        o["received_unix_ms"] = int(arrival * 1000)
    return o


def prof(supi, observed, arrival, ul_bytes, ul_pkts, syn=0):
    return {"kind": "profile", "report": {"observed_at": iso(observed), "supi": supi, "window_ms": 1000,
            "body": {"ul_bytes": ul_bytes, "ul_pkts": ul_pkts, "dl_bytes": 0, "dl_pkts": 0, "ul_tcp_syn": syn,
                     "ul_udp": ul_pkts, "ul_dst_estimate": 1.0}},
            "received_unix_ms": int(arrival * 1000)}


def wr(p, recs):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in recs))


def make_run(tmp):
    run = pathlib.Path(tmp) / "c/runs/off/rep-01"
    # KPM: A thp=100, B thp=200 for T0..T0+19; hole for A in T0+6..T0+10 (age-cap test)
    k = [kpm(T0 + i, A, 100) for i in range(20) if not 6 <= i <= 10] + [kpm(T0 + i, Bs, 200) for i in range(20)]
    wr(run / "raw/kpm.jsonl", k)
    u = [urr(A, 1, 100, 0, T0 + 1.5, arrival=T0 + 1.6),
         urr(A, 2, 101, 125000, T0 + 2.5, arrival=T0 + 2.6),            # 1000 kbps over 1 s
         urr(A, 3, 103, 250000, T0 + 4.5, arrival=T0 + 4.6),            # 1000 kbps over 2 s (delta duration)
         urr(A, 1, 5, 999999, T0 + 12.5, arrival=T0 + 12.6, session="S2"),   # new session, no predecessor
         urr(Bs, 1, 50, 0, T0 + 1.5, legacy_second=T0 + 2),             # legacy second-precision stamp
         urr(Bs, 2, 51, 62500, T0 + 2.5, legacy_second=T0 + 3)]         # usable only from T0+4 (padded +1 s)
    wr(run / "core/urr_received.jsonl", u)
    p = [prof(A, T0 + 1.3, T0 + 1.4, 1250, 10),
         prof(A, T0 + 3.3, T0 + 15.4, 99_999_000, 5, syn=5)]            # arrives very late -> future for t<T0+16
    wr(run / "core/core_received.jsonl", p)
    meta = {"ues": {"ue1": {"supi": A}, "ue2": {"supi": Bs}},
            "phases": [{"name": "idle", "t_start": T0, "t_end": T0 + 2},
                       {"name": "atk", "t_start": T0 + 2, "t_end": T0 + 14},
                       {"name": "gap", "t_start": T0 + 14, "t_end": T0 + 17}]}
    (run / "run.json").write_text(json.dumps(meta))
    wr(run / "traffic/flows.json", [])
    (run / "traffic/flows.json").write_text(json.dumps([
        {"phase": "atk", "ue": "ue1", "attack": "udp_flood"},
        {"phase": "atk", "ue": "ue2", "attack": None}]))
    return run


def nan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def main():
    fails = []
    def check(cond, msg):
        if not cond:
            fails.append(msg)
    with tempfile.TemporaryDirectory() as tmp:
        rows = B.build_run(make_run(tmp), age_cap=3.0, core_age_cap=3.0)
        by = {}
        for r in rows:
            by.setdefault(r["supi"], {})[r["t_unix"]] = r
        a, b = by[A], by[Bs]

        # 1 causality: the late profile (arrival T0+15.4) never appears before it arrived
        check(all(r["prof_ul_kbps"] != 99_999_000 * 8 / 1000 for t, r in a.items() if t < T0 + 15.4),
              "causality: future-arriving profile used early")
        # 2 URR per-period semantics: before seq2 arrives -> NaN; after -> 1000 kbps
        check(nan(a[T0 + 2]["urr_ul_kbps"]), "urr: rate before a causal predecessor should be NaN")
        check(abs(a[T0 + 3]["urr_ul_kbps"] - 1000.0) < 1e-9, f"urr: expected 1000 kbps at T0+3, got {a[T0+3]['urr_ul_kbps']}")
        # 3 period = delta of cumulative duration (2 s) -> still 1000 kbps
        check(abs(a[T0 + 5]["urr_ul_kbps"] - 1000.0) < 1e-9, f"urr: delta-duration period wrong, got {a[T0+5]['urr_ul_kbps']}")
        # 4 new session without predecessor -> NaN (no cross-session delta)
        check(nan(a[T0 + 13]["urr_ul_kbps"]), "urr: cross-session delta used")
        # 5 legacy second-precision arrival padded +1 s: seq2 (received_at T0+3) usable only at T0+4
        check(nan(b[T0 + 3]["urr_ul_kbps"]), "urr: legacy stamp not padded (used at T0+3)")
        check(abs(b[T0 + 4]["urr_ul_kbps"] - 500.0) < 1e-9, f"urr: legacy record not used at T0+4, got {b[T0+4]['urr_ul_kbps']}")
        check(b[T0 + 4]["urr_arrival_exact"] == 0 and a[T0 + 3]["urr_arrival_exact"] == 1, "urr: arrival_exact flag")
        # 6 non-negative URR everywhere
        check(all(nan(r["urr_ul_kbps"]) or r["urr_ul_kbps"] >= 0 for s in by.values() for r in s.values()), "urr: negative rate")
        # 7 UE join: A carries 100, B carries 200, never swapped
        check(all(nan(r["thp_ul_kbps"]) or r["thp_ul_kbps"] == 100 for r in a.values()), "join: A got B's KPM")
        check(all(r["thp_ul_kbps"] == 200 for r in b.values()), "join: B got A's KPM")
        # 8 age cap: A's last causal KPM before the hole is T0+5 -> at T0+9 age ~3.8 s > 3 -> NaN
        check(nan(a[T0 + 9]["thp_ul_kbps"]), "age cap not applied to KPM")
        # 9 labels from schedule; IDLE kept apart from BENIGN
        check(a[T0 + 5]["label"] == "MALICIOUS" and a[T0 + 5]["attack_family"] == "udp_flood", "label: ue1 in atk")
        check(b[T0 + 5]["label"] == "BENIGN", "label: ue2 benign flow in atk")
        check(a[T0 + 1]["label"] == "IDLE" and a[T0 + 15]["label"] == "IDLE", "label: idle/gap must be IDLE")
        check(a[T0 + 2]["guard"] == 1 and a[T0 + 8]["guard"] == 0, "guard band")
        # 10 separation
        df = B.to_frame(rows)
        feat = set(B.FEATURES)
        check(not any(c.startswith("meta_") for c in feat) and "label" not in feat, "FEATURES contain meta/label")
        check(all(c in feat or c.startswith("meta_") or c == "label" for c in df.columns), "unexpected column in frame")
        # 11 per-second attack gate m_t (pulsing square wave) matches schedules.pulsing
        lab = {"label": "MALICIOUS", "gate": {"started": 100.0, "period": 10, "on": 2, "offset": 9}}
        got = [B.attack_active_at(lab, 100.0 + s) for s in range(20)]
        want = [int(((s + 9) % 10) < 2) for s in range(20)]
        check(got == want, "pulsing gate m_t != schedule")
        check(B.attack_active_at({"label": "MALICIOUS", "gate": None}, 5) == 1, "non-pulsing attack gate must be 1")
        check(B.attack_active_at({"label": "BENIGN"}, 5) == 0, "benign gate must be 0")
    if fails:
        print("FAIL:"); [print("  -", f) for f in fails]; sys.exit(1)
    print("ALL TESTS PASSED (causality, urr per-period, delta-duration, session reset, legacy +1s pad, "
          "non-negative, ue-join, age-cap, labels+IDLE, guard, separation, attack gate)")


if __name__ == "__main__":
    main()
