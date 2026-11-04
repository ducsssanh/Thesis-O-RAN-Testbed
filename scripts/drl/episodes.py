#!/usr/bin/env python3
"""Replay data of the DRL (DRL design 3, 5): per UE episode and tamper scenario, 30 features per second, labels, attack bytes. Decision at t + 0.2 s: a profile that arrives later counts as missing at that second.
Gate columns are per UE and recomputed after tampering. Labels: `run` = 1 from the attack onset to the end of the episode; an alarm from then on is a true alarm, including in the silent seconds of L2.
Usage: episodes.py <rows.parquet> <out.pkl>"""
import pickle, sys, pathlib
import numpy as np, pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ml"))
import tamper_replay as TR
DELTA = 0.2
PROTO_UL = ["prof_ul_tcp", "prof_ul_tcp_syn", "prof_ul_udp", "prof_ul_icmp", "prof_ul_dns", "prof_ul_frag", "prof_ul_gtp_in_gtp"]
PROTO_DL = ["prof_dl_tcp", "prof_dl_tcp_syn", "prof_dl_udp", "prof_dl_icmp", "prof_dl_frag"]
NAMES = ["rate_ul", "rate_dl", "prb_ul", "prb_dl", "cell_ul", "cell_dl", "core_ul_kbps", "core_dl_kbps", "core_ul_pps", "core_dl_pps", "size_ul", "size_dl"] + [c[5:] for c in PROTO_UL] + ["dst_ul"] + [c[5:] for c in PROTO_DL] + ["c_t", "trust", "masked", "kpm_age", "prof_age"]
GROUPS = {"kpm": list(range(6)), "volume": list(range(6, 10)), "behaviour": list(range(10, 25)), "gate": [25, 26], "context": [27, 28, 29]}
PROTOCOL = list(range(12, 19)) + list(range(20, 25))


def features(g):
    """g: one UE in time order, gate columns already there. Returns T x 30."""
    late = (g.prof_age_s.to_numpy() > DELTA) | np.isnan(g.prof_age_s.to_numpy())
    f = np.zeros((len(g), 30), np.float32)
    mask = g.kpm_masked.to_numpy().astype(bool)
    for i, c in enumerate(("rate_ul_kbps", "rate_dl_kbps")):
        f[:, i] = np.log1p(g[c].fillna(0).to_numpy())
    for i, c in enumerate(("prb_ul_pct", "prb_dl_pct", "cell_prb_ul_pct", "cell_prb_dl_pct")):
        f[:, 2 + i] = g[c].fillna(0).to_numpy() / 100
    f[mask, :6] = 0
    for i, c in enumerate(("prof_ul_kbps", "prof_dl_kbps", "prof_ul_pps", "prof_dl_pps")):
        f[:, 6 + i] = np.log1p(g[c].fillna(0).to_numpy())
    f[:, 10] = g.prof_ul_mean_bytes.fillna(0).to_numpy() / 1500
    f[:, 11] = g.prof_dl_mean_bytes.fillna(0).to_numpy() / 1500
    ul, dl = g.prof_ul_pps.fillna(0).to_numpy().clip(1), g.prof_dl_pps.fillna(0).to_numpy().clip(1)
    for i, c in enumerate(PROTO_UL):
        f[:, 12 + i] = g[c].fillna(0).to_numpy() / ul
    f[:, 19] = np.log1p(g.prof_ul_dst_estimate.fillna(0).to_numpy())
    for i, c in enumerate(PROTO_DL):
        f[:, 20 + i] = g[c].fillna(0).to_numpy() / dl
    f[late, 6:25] = 0
    f[:, 25] = np.clip(np.nan_to_num(g.c_t.to_numpy()), -3, 3)
    f[late, 25] = 0
    f[:, 26] = g.kpm_trust.to_numpy()
    f[:, 27] = mask
    f[:, 28] = np.clip(np.nan_to_num(g.kpm_age_s.to_numpy(), nan=3), 0, 3)
    f[:, 29] = np.clip(np.nan_to_num(g.prof_age_s.to_numpy(), nan=3), 0, 3)
    return f


def first(c):
    """The value of a label column: the flow of a phase can start one second after its twin, so its first row may be empty."""
    v = c[c != ""]
    return v.iloc[0] if len(v) else ""


def main():
    df = pd.read_parquet(sys.argv[1]).sort_values(["run_id", "phase", "supi", "t_unix"]).reset_index(drop=True)
    rng = np.random.default_rng(20261105)
    out = []
    for (run, phase), ph in df.groupby(["run_id", "phase"], sort=False):
        ues = list(ph.supi.unique())
        att = ph[ph.role == "attack"].supi.unique()
        attacker = att[0] if len(att) else None
        onset = ph[ph.attack_active == 1].t_unix.min() if attacker else None
        other = next((s for s in ues if s != attacker), None)

        def scen(d):
            g = TR.gate(d, "ue")
            d = d.copy()
            d[["c_t", "c_t_w", "kpm_trust", "kpm_masked"]] = g
            return d
        H0 = scen(ph)
        first_s = int(ph.t_unix.min())
        Sw = None
        if attacker is not None and other is not None:     # swap, from a start that does not depend on the attack onset
            Sw = scen(TR.tamper(ph, attacker, first_s + int(rng.integers(0, 15)), 10**12, swap_with=other))
        for s in ues:
            g0 = H0[H0.supi == s]
            is_att = s == attacker
            run_lab = (g0.t_unix.to_numpy() >= onset).astype(np.int8) if is_att else np.zeros(len(g0), np.int8)
            scs = {"honest": features(g0)}
            # any UE can be hidden or framed, from a start drawn the same way for all, so neither the sign of c_t nor its first second tells the label
            for f in (.1, .33, .8, 1.25, 2, 5):
                d = scen(TR.tamper(ph, s, first_s + int(rng.integers(0, 15)), 10**12, factor=f))
                scs[("hide%s" if f < 1 else "frame%s") % f] = features(d[d.supi == s])
            if is_att:
                d = scen(TR.tamper(ph, s, first_s + int(rng.integers(0, 15)), 10**12, factor=.33, on_only=True))
                scs["hide0.33on"] = features(d[d.supi == s])
            if Sw is not None:
                scs["swap"] = features(Sw[Sw.supi == s])
            oth = ph[ph.supi != s].set_index("t_unix").rate_ul_kbps.reindex(g0.t_unix).fillna(0).to_numpy() if other is not None else np.zeros(len(g0))
            out.append(dict(run=run, phase=phase, supi=s, attack=is_att, evasion=(first(g0.evasion) if is_att else ""), vector=(first(g0.vector) if is_att else ""), other_evasion=(first(ph[ph.role == "attack"].evasion) if attacker else ""),
                            client=first(g0.client_role) != "", band=g0.band.iloc[0], anchor=float(g0.anchor_bps.max()) if is_att else 0.0, run_lab=run_lab, active=g0.attack_active.to_numpy().astype(np.int8), bytes=g0.attack_bytes_core.to_numpy().astype(np.float32), other_ul=oth.astype(np.float32), scen=scs))
    pathlib.Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(dict(names=NAMES, groups=GROUPS, protocol=PROTOCOL, episodes=out), open(sys.argv[2], "wb"))
    print("episodes", len(out), "attack", sum(e["attack"] for e in out), "T", sorted({len(e["run_lab"]) for e in out})[:4], "scenarios", sorted({k for e in out for k in e["scen"]}))


if __name__ == "__main__":
    main()
