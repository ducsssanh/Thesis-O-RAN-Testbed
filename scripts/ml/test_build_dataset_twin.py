#!/usr/bin/env python3
"""Tests of the twin builder on a small synthetic run: right second, labels, no future data, gate replay, tamper keeps the KPM grid. Usage: .venv-ml/bin/python scripts/ml/test_build_dataset_twin.py"""
import datetime, json, pathlib, sys, tempfile
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_dataset_twin as B, tamper_replay as TR
T0 = 1793700000
A, C = "imsi-1", "imsi-2"


def make_run(d):
    d = pathlib.Path(d)
    for s in ("raw", "core", "traffic"):
        (d / s).mkdir()
    kl, pl = [], []
    for s, tw in ((A, 2000), (C, 1000)):
        for i in range(80):
            t = T0 + i
            kl.append({"source_ts": t + .0005, "arrival_ts": t + .001, "supi": s, "rate_ul_kbps": tw * 8 / 1000, "rate_dl_kbps": 1.0, "thp_ul_kbps": 1.0, "thp_dl_kbps": 1.0, "prb_ul_pct": 10.0, "prb_dl_pct": 1.0, "cell_prb_ul_pct": 20.0, "cell_prb_dl_pct": 2.0})
            iso = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.5Z")
            pl.append({"kind": "profile", "received_unix_ms": (t + 1) * 1000, "report": {"supi": s, "observed_at": iso, "window_ms": 1000, "body": {"ul_bytes": tw + 57 * 2, "ul_pkts": 2, "dl_bytes": 0, "dl_pkts": 0}}})
    (d / "raw/kpm.jsonl").write_text("\n".join(map(json.dumps, kl)) + "\n")
    (d / "core/core_received.jsonl").write_text("\n".join(map(json.dumps, pl)) + "\n")
    (d / "run.json").write_text(json.dumps({"ues": {"ue1": {"supi": A}, "ue2": {"supi": C}}}))
    tw = lambda u, k: {"phase": "p1", "ue": u, "replay_start_at": float(T0 + 2), "v4_meta": {"model": "real_window", "band": "P4", "window": {"index": k}, "seed": k}}
    active = [0] * 5 + [1] * 70
    atk = {"phase": "p1", "ue": "ue1", "attack_start_at": T0 + 2, "backend": "hping", "mode": "syn", "rows": [{"t": float(T0 + 2 + i), "bytes": 100.0} for i in range(75)], "v4_meta": {"model": "flood_overlay", "role": "attack", "attack_active": active, "onset_s": 5, "evasion": "L1", "anchor_bps": 1e5}}
    cli = {"phase": "p1", "ue": "ue2", "attack_start_at": T0 + 2, "backend": "dns_client", "rows": [], "v4_meta": {"model": "flood_overlay", "role": "benign", "attack_active": active, "onset_s": 0, "evasion": "L3", "anchor_bps": 1e5}}
    (d / "traffic/flows.json").write_text(json.dumps([tw("ue1", 1), tw("ue2", 2), atk, cli]))
    return d


def main():
    with tempfile.TemporaryDirectory() as tmp:
        df = B.build_run(make_run(tmp))
    assert len(df) == 150
    a, c = df[df.supi == A], df[df.supi == C]
    assert (a.t_window.to_numpy() == np.arange(75)).all() and a.t_unix.iloc[0] == T0 + 3
    assert a.attack_active.sum() == 70 and c.attack_active.sum() == 0 and (c.role == "benign").all() and (c.client_role == "dns_client").all()
    assert a.attack_active.iloc[4] == 0 and a.attack_active.iloc[5] == 1 and a.onset_t.iloc[0] == T0 + 8 and a.attack_bytes.iloc[4] == 0 and a.attack_bytes.iloc[5] == 100
    assert (a.vector == "syn").all() and (a.attacker_ue == "ue1").all() and (c.attacker_ue == "ue1").all()
    assert (a.prof_ul_kbps == (2000 + 114) * 8 / 1000).all() and (a.prof_age_s == 1.0).all() and (a.kpm_age_s > 0).all(), "the profile of second t arrives after t"
    assert abs(a.c_t).max() < 1e-9 and not df.kpm_masked.any() and (df.kpm_trust == 1).all()
    for bad in ("time_in_phase", "cum_bytes"):
        assert bad not in B.FEATURES
    assert "t_window" not in B.FEATURES and "onset_t" not in B.FEATURES and "attack_active" not in B.FEATURES
    # hiding: outside the band after the 3 s window, masked after 2 updates
    t = TR.tamper(df, A, T0 + 20, T0 + 40, factor=.1)
    g = TR.gate(t, "ue").loc[t.supi == A]
    b = g.c_t_w.to_numpy()
    assert abs(b[16]) < .2 and abs(b[17]) > .2 and g.kpm_masked.iloc[18] and not g.kpm_masked.iloc[16]
    n = TR.gate(t, "node")
    assert (n.kpm_trust[t.supi == A].min() > g.kpm_trust.min()), "the honest UE dilutes node trust"
    q = t[(t.supi == A) & (t.t_unix >= T0 + 20) & (t.t_unix < T0 + 40)]
    assert np.allclose(q.prb_ul_pct, 1.0) and np.allclose(q.cell_prb_ul_pct, 11.0) and np.allclose(q.rate_ul_kbps / TR.RATE_STEP, np.round(q.rate_ul_kbps / TR.RATE_STEP))
    h = t[(t.supi == C)]
    assert (h.rate_ul_kbps == c.rate_ul_kbps.to_numpy()).all(), "other UE untouched"
    # on-only and swap
    o = TR.tamper(df, A, T0, T0 + 200, factor=2, on_only=True)
    assert (o[(o.supi == A)].prb_ul_pct.to_numpy()[:5] == 10).all() and (o[(o.supi == A)].prb_ul_pct.to_numpy()[5:] == 20).all()
    s = TR.tamper(df, A, T0 + 20, T0 + 40, swap_with=C)
    assert (s[(s.supi == A) & (s.t_unix == T0 + 25)].rate_ul_kbps.iloc[0] == 8.0) and (s[(s.supi == C) & (s.t_unix == T0 + 25)].rate_ul_kbps.iloc[0] == 16.0)
    print("ALL BUILDER TESTS PASSED")


if __name__ == "__main__":
    main()
