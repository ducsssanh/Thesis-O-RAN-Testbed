#!/usr/bin/env python3
"""Campaign manifest for the twinned dataset, fixed with a seed before any run (TRAFFIC-TWINNING-PLAN 5, execution plan Phase 6).
Size comes from what the evaluation reads per evasion level: 144 attack episodes per level give a detection rate of 0.90 to about +-5 % (95 %). A run has 6 phases of 75 s, so 432 phases = 72 runs,
about 10 min each. In every phase one UE runs its twin plus the attack, the other its twin; roles alternate inside a run. L3 phases give the other UE the same client as a benign hard negative
in the rhythm of a real window (no benign heavy-UL TCP backend follows a window; recorded as an assumption). Twin bands follow WEIGHTS. Only the step onset is used: hping3 cannot ramp, and
react needs the defence on, while the campaign runs with detection off.
Usage: design_twin.py [--out f.json] [--seed 20261104]"""
import argparse, json, pathlib
import numpy as np
ANCHORS = {"q0.90": 52536.0, "q0.95": 111088.0, "q0.99": 409856.0}
CELLS = [dict(evasion="L1", mode=m, anchor=a, victim="silent" if m == "udp" else "responsive", n=16) for m in ("udp", "syn", "icmp") for a in ANCHORS] + \
        [dict(evasion="L2", anchor=a, victim="silent", n=48) for a in ANCHORS] + \
        [dict(evasion="L3", backend=b, anchor=a, victim="responsive", n=24) for b in ("tcp_shortconn", "dns_client") for a in ANCHORS]
WEIGHTS = {"P1": .25, "P2": .25, "P3": .20, "P4": .30}   # TRAFFIC-TWINNING-PLAN 4.B; real Madrid about .50 .40 .09 .01
PHASES_PER_RUN = 6


def design(seed):
    rng = np.random.default_rng(seed)
    cells = [dict(c) for c in CELLS for _ in range(c["n"])]
    order = rng.permutation(len(cells))
    runs, s = [], 700000
    for r in range(len(cells) // PHASES_PER_RUN):
        phases = []
        for j, i in enumerate(order[r * PHASES_PER_RUN:(r + 1) * PHASES_PER_RUN]):
            c = {k: v for k, v in cells[i].items() if k != "n"}
            b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
            s += 10
            phases.append(dict(c, name="p%d" % (j + 1), attacker="ue%d" % (1 + (j + r) % 2), bands={"ue1": b[0], "ue2": b[1]}, seed=s))
        runs.append(dict(id="c%03d" % r, phases=phases))
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, phases_per_run=PHASES_PER_RUN, runs=runs)


def scenario(run):
    """The scenario of one manifest run for run.py."""
    phases = [{"name": "idle", "duration": 10}]
    for p in run["phases"]:
        fl = {}
        for k, ue in enumerate(("ue1", "ue2")):
            f = {"ul": {"v4": True, "model": "real_window", "backend": "pacer", "band": p["bands"][ue], "grid": "gnb", "timing": "tti", "role": "benign", "seed": p["seed"] + k + 1}}
            spec = {"v4": True, "evasion": p["evasion"], "anchor_bps": ANCHORS[p["anchor"]], "band": "P4", "timing": "tti", "victim_mode": p["victim"]}
            for x in ("mode", "backend"):
                if x in p:
                    spec[x] = p[x]
            if ue == p["attacker"]:
                f["ul_attack"] = dict(spec, role="attack", seed=p["seed"] + 5)
            elif p["evasion"] == "L3":
                f["ul_client"] = dict(spec, role="benign", seed=p["seed"] + 6)
            fl[ue] = f
        phases.append({"name": p["name"], "duration": 75, "attack": True, "flows": fl})
    return {"name": "ds-flood-twin-" + run["id"], "description": "Twin campaign run %s" % run["id"], "ues": {"ue1": "benign", "ue2": "benign"}, "reps": 1,
            "drain": {"quiet_kbps": 300, "timeout_s": 120}, "tail_s": 5, "variants": [{"name": "detection-off", "defense": {"enabled": False, "core": False}}], "phases": phases}


# L2 campaign (2026-11-09, nhật ký thực nghiệm vòng 4): every attack phase is L2, 72 phases per anchor; the benign UE of a
# phase favours P4 (the band the L2 threshold is set against); the attacker's own twin keeps WEIGHTS. Runs 0-23 add training
# data, runs 24-35 are a clean test that no model has seen.
L2_CELLS = [dict(evasion="L2", anchor=a, victim="silent", n=72) for a in ANCHORS]
BENIGN_L2 = {"P1": .15, "P2": .15, "P3": .20, "P4": .50}


def design_l2(seed):
    rng = np.random.default_rng(seed)
    cells = [dict(c) for c in L2_CELLS for _ in range(c["n"])]
    order = rng.permutation(len(cells))
    runs, s = [], 900000
    for r in range(len(cells) // PHASES_PER_RUN):
        phases = []
        for j, i in enumerate(order[r * PHASES_PER_RUN:(r + 1) * PHASES_PER_RUN]):
            c = {k: v for k, v in cells[i].items() if k != "n"}
            att = "ue%d" % (1 + (j + r) % 2); ben = "ue1" if att == "ue2" else "ue2"
            bands = {att: str(rng.choice(list(WEIGHTS), p=list(WEIGHTS.values()))), ben: str(rng.choice(list(BENIGN_L2), p=list(BENIGN_L2.values())))}
            s += 10
            phases.append(dict(c, name="p%d" % (j + 1), attacker=att, bands=bands, seed=s))
        runs.append(dict(id="l2c%03d" % r, split="train" if r < 24 else "clean_test", phases=phases))
    return dict(seed=seed, weights=WEIGHTS, benign_weights=BENIGN_L2, anchors=ANCHORS, phases_per_run=PHASES_PER_RUN, runs=runs)


# Live detection test (2026-11-08, plan step 3): the whole xApp with the embedded model, observe mode (decisions logged,
# no action). Per attack phase the attacker's KPM is honest or hidden (x0.33, x0.1) from the phase start by the xApp ingest
# hook (emulated compromised E2 node / MITM). L2 half of the phases, L1 and L3 a quarter each; 24 attack runs + 6 benign-only
# runs (false alarms). Twin windows are drawn so that no window of either dataset is replayed (users unseen in training).
LIVE_CASES = {"honest": None, "hide0.33": 0.33, "hide0.1": 0.1}
LIVE_DEFENSE = {"enabled": True, "core": True, "mode": "slice", "classifier": "xgb", "actuate": False, "clear_tamper": True}


def used_windows():
    import pandas as pd
    root = pathlib.Path(__file__).resolve().parents[4]
    out = set()
    for d in ("oran_flooding_twin", "oran_flooding_twin_l2"):
        df = pd.read_parquet(root / "research/datasets" / d / "rows.parquet", columns=["band", "window_index"]).drop_duplicates()
        out |= {(b, int(i)) for b, i in zip(df.band, df.window_index)}
    return out


def design_live(seed):
    import schedules
    rng = np.random.default_rng(seed)
    used = used_windows(); n_skip = 0

    def fresh(band, s):
        """seed s gives a window not replayed before (planbuilder.build_replay draws the window first from default_rng(s))."""
        w = schedules.real_window(band, np.random.default_rng(s))["index"]
        return (band, w) not in used, w

    cells = [dict(evasion="L1", mode=m, anchor=a, victim="silent" if m == "udp" else "responsive") for m in ("udp", "syn", "icmp") for a in ANCHORS for _ in range(4)] + \
            [dict(evasion="L2", anchor=a, victim="silent") for a in ANCHORS for _ in range(24)] + \
            [dict(evasion="L3", backend=b, anchor=a, victim="responsive") for b in ("tcp_shortconn", "dns_client") for a in ANCHORS for _ in range(6)]
    for L in ("L1", "L2", "L3"):                       # cases balanced inside each level
        idx = [i for i, c in enumerate(cells) if c["evasion"] == L]
        cs = [k for k in LIVE_CASES for _ in range(len(idx) // 3)]
        for i, k in zip(idx, rng.permutation(cs)):
            cells[i]["case"] = str(k)
    cells = [cells[i] for i in rng.permutation(len(cells))] + [None] * (6 * PHASES_PER_RUN)   # None: benign-only phase
    runs, s = [], 1_100_000
    for r in range(len(cells) // PHASES_PER_RUN):
        phases = []
        for j in range(PHASES_PER_RUN):
            c = cells[r * PHASES_PER_RUN + j]
            b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
            while True:                                 # both twins of the phase unseen and not repeated in this campaign
                s += 10
                ok = [fresh(b[k], s + k + 1) for k in range(2)]
                if all(o for o, _ in ok) and ok[0][1:] != ok[1][1:] or (all(o for o, _ in ok) and b[0] != b[1]):
                    used |= {(b[k], ok[k][1]) for k in range(2)}
                    break
                n_skip += 1
            ph = dict(name="p%d" % (j + 1), bands={"ue1": b[0], "ue2": b[1]}, seed=s)
            if c is not None:
                ph.update(c, attacker="ue%d" % (1 + (j + r) % 2))
            phases.append(ph)
        runs.append(dict(id="lv%03d" % r, live=True, benign_only=c is None, phases=phases))
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, cases=LIVE_CASES, defense=LIVE_DEFENSE, phases_per_run=PHASES_PER_RUN,
                windows_skipped=n_skip, runs=runs)


def scenario_live(run):
    """run.py scenario of a live run: the twin scenario, attack-free phases kept benign, KPM tamper key, detection on in observe mode."""
    phases = [{"name": "idle", "duration": 10}]
    for p in run["phases"]:
        if "evasion" not in p:
            fl = {ue: {"ul": {"v4": True, "model": "real_window", "backend": "pacer", "band": p["bands"][ue], "grid": "gnb", "timing": "tti",
                              "role": "benign", "seed": p["seed"] + k + 1}} for k, ue in enumerate(("ue1", "ue2"))}
            phases.append({"name": p["name"], "duration": 75, "attack": False, "flows": fl, "reset_defense": True})
            continue
        ph = scenario({"id": run["id"], "phases": [p]})["phases"][1]
        if p["case"] == "mimic":
            # 75 s of the donor trace (the xApp REST body limit is 4 KiB); the hook loops it if the phase runs longer
            ph["tamper"] = {"ue": p["attacker"], "series": p["donor"][:75]}
        else:
            f = LIVE_CASES.get(p["case"])
            if f is not None:
                ph["tamper"] = {"ue": p["attacker"], "factor": f}
        ph["case"] = p["case"]
        ph["reset_defense"] = True                  # levels and tamper of the previous phase do not carry over
        phases.append(ph)
    sc = scenario({"id": run["id"], "phases": []})
    sc.update(name="ds-flood-live-" + run["id"], description="Live detection run %s (observe mode)" % run["id"], phases=phases,
              variants=[{"name": "detection-observe", "defense": dict(LIVE_DEFENSE)}])
    return sc


# Live detection test v2 (2026-11-09, after the KPM-tamper root cause): tamper cases honest / mimic (the attacker's KPM replaced
# by a recorded benign KPM trace) / hide0.1 (naive scaling, for comparison). Option (b): each run keeps ONE attacker UE and ONE
# case for all its phases, so a tampered UE never becomes the benign UE of the next phase; the other UE is never tampered.
# Donor traces: benign UE-phases of the first live campaign (oran_flooding_live, test side, never a training donor).
LIVE2_CASES = ("honest", "mimic", "hide0.1")
LIVE2_DEFENSE = dict(LIVE_DEFENSE)


def donor_pool():
    import pandas as pd
    root = pathlib.Path(__file__).resolve().parents[4]
    r = pd.read_parquet(root / "artifacts/clf/live/rows.parquet")
    cols = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps", "prb_ul_pct", "prb_dl_pct"]
    out = []
    for _, g in r.groupby(["run_id", "phase", "supi"]):
        if (g.role == "benign").all() and (g.client_role == "").all() and len(g) >= 75 and "hide" not in str(g.run_id.iloc[0]):
            out.append(np.round(g.sort_values("t_unix")[cols].fillna(0).to_numpy(), 3))
    return out


def design_live2(seed):
    import schedules
    rng = np.random.default_rng(seed)
    used = used_windows(); used |= set()
    pool = donor_pool()
    fresh = lambda band, s: schedules.real_window(band, np.random.default_rng(s))["index"]
    # attack runs: 8 per case; per case 24 L2, 12 L1, 12 L3 phases
    runs, s = [], 1_300_000
    for ci, case in enumerate(LIVE2_CASES):
        cells = [dict(evasion="L1", mode=m, anchor=a, victim="silent" if m == "udp" else "responsive") for m in ("udp", "syn", "icmp") for a in ANCHORS for _ in range(1)] + \
                [dict(evasion="L1", mode=str(rng.choice(["udp", "syn", "icmp"])), anchor=str(rng.choice(list(ANCHORS))), victim="silent") for _ in range(3)] + \
                [dict(evasion="L2", anchor=a, victim="silent") for a in ANCHORS for _ in range(8)] + \
                [dict(evasion="L3", backend=b, anchor=a, victim="responsive") for b in ("tcp_shortconn", "dns_client") for a in ANCHORS for _ in range(2)]
        for c in cells:
            if c["evasion"] == "L1" and c["mode"] != "udp":
                c["victim"] = "responsive"
        cells = [cells[i] for i in rng.permutation(len(cells))]
        for r in range(8):
            att = "ue%d" % (1 + (r + ci) % 2)
            phases = []
            for j in range(PHASES_PER_RUN):
                b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
                while True:
                    s += 10
                    w = [(b[k], fresh(b[k], s + k + 1)) for k in range(2)]
                    if not any(x in used for x in w) and w[0] != w[1]:
                        used |= set(w); break
                ph = dict(cells[r * PHASES_PER_RUN + j], name="p%d" % (j + 1), bands={"ue1": b[0], "ue2": b[1]}, seed=s, attacker=att, case=case)
                if case == "mimic":
                    i1, i2 = rng.choice(len(pool), 2, replace=False)
                    ph["donor"] = np.r_[pool[i1], pool[i2]][:150].tolist()
                phases.append(ph)
            runs.append(dict(id="lw%03d" % len(runs), live=True, benign_only=False, case=case, phases=phases))
    for r in range(6):                                   # benign-only runs
        phases = []
        for j in range(PHASES_PER_RUN):
            b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
            while True:
                s += 10
                w = [(b[k], fresh(b[k], s + k + 1)) for k in range(2)]
                if not any(x in used for x in w) and w[0] != w[1]:
                    used |= set(w); break
            phases.append(dict(name="p%d" % (j + 1), bands={"ue1": b[0], "ue2": b[1]}, seed=s))
        runs.append(dict(id="lw%03d" % len(runs), live=True, benign_only=True, phases=phases))
    order = rng.permutation(len(runs))                   # cases interleaved over the campaign
    runs = [runs[i] for i in order]
    for k, r in enumerate(runs):
        r["id"] = "lw%03d" % k
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, cases=list(LIVE2_CASES), defense=LIVE2_DEFENSE, phases_per_run=PHASES_PER_RUN, runs=runs)


# Live v5 (2026-11-10): blind test of the round-v5 model (trained on the twin data + live 1, live v2, live v4). Same structure as
# live v2 (8 runs per case honest / mimic / hide0.1, 6 benign-only runs), new seed. Every twin window comes from a Madrid user
# (cell, RNTI) never replayed before: not in the twin datasets nor in any earlier live campaign. Mimic donors: benign UE-phases of
# the 6 benign-only runs of live v4, which were kept out of training.
def used_users(live=("oran_flooding_live", "oran_flooding_live2", "oran_flooding_live3", "oran_flooding_live4")):
    """(band, window) and (cell, rnti) of every window replayed so far: twin datasets and the given live designs (default 1-4)."""
    import schedules
    root = pathlib.Path(__file__).resolve().parents[4]
    used = used_windows()
    for name in live:
        for r in json.load(open(root / "research/datasets" / name / "manifest/design.json"))["runs"]:
            for p in r["phases"]:
                for k, ue in enumerate(("ue1", "ue2")):
                    b = p["bands"][ue]; used.add((b, schedules.real_window(b, np.random.default_rng(p["seed"] + k + 1))["index"]))
    d = np.load(schedules.WINDOWS_NPZ)
    users = {tuple(int(x) for x in d["src_" + b][i][:2]) for b, i in used}
    return used, users


def donor_pool_live4():
    import pandas as pd
    root = pathlib.Path(__file__).resolve().parents[4]
    r = pd.read_parquet(root / "artifacts/clf/live4/rows.parquet")
    bo = set(json.load(open(root / "artifacts/clf/live4/split_live4_trainside.json"))["test"])
    cols = ["rate_ul_kbps", "rate_dl_kbps", "thp_ul_kbps", "thp_dl_kbps", "prb_ul_pct", "prb_dl_pct"]
    out = []
    for (run, _, _), g in r.groupby(["run_id", "phase", "supi"]):
        if run in bo and (g.role == "benign").all() and (g.client_role == "").all() and len(g) >= 75:
            out.append(np.round(g.sort_values("t_unix")[cols].fillna(0).to_numpy(), 3))
    return out


def design_live5(seed):
    import schedules
    rng = np.random.default_rng(seed)
    used, users = used_users()
    pool = donor_pool_live4()
    assert len(pool) >= 40, len(pool)
    win = np.load(schedules.WINDOWS_NPZ)

    def fresh(band, s):
        i = schedules.real_window(band, np.random.default_rng(s))["index"]
        return i, tuple(int(x) for x in win["src_" + band][i][:2])

    def draw(s):
        while True:
            s += 10
            b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
            w = [(b[k],) + fresh(b[k], s + k + 1) for k in range(2)]
            if all((x[0], x[1]) not in used and x[2] not in users for x in w) and w[0][2] != w[1][2]:
                for x in w:
                    used.add((x[0], x[1])); users.add(x[2])
                return s, b
    runs, s = [], 1_500_000
    for ci, case in enumerate(LIVE2_CASES):
        cells = [dict(evasion="L1", mode=m, anchor=a, victim="silent" if m == "udp" else "responsive") for m in ("udp", "syn", "icmp") for a in ANCHORS for _ in range(1)] + \
                [dict(evasion="L1", mode=str(rng.choice(["udp", "syn", "icmp"])), anchor=str(rng.choice(list(ANCHORS))), victim="silent") for _ in range(3)] + \
                [dict(evasion="L2", anchor=a, victim="silent") for a in ANCHORS for _ in range(8)] + \
                [dict(evasion="L3", backend=b, anchor=a, victim="responsive") for b in ("tcp_shortconn", "dns_client") for a in ANCHORS for _ in range(2)]
        for c in cells:
            if c["evasion"] == "L1" and c["mode"] != "udp":
                c["victim"] = "responsive"
        cells = [cells[i] for i in rng.permutation(len(cells))]
        for r in range(8):
            att = "ue%d" % (1 + (r + ci) % 2)
            phases = []
            for j in range(PHASES_PER_RUN):
                s, b = draw(s)
                ph = dict(cells[r * PHASES_PER_RUN + j], name="p%d" % (j + 1), bands={"ue1": b[0], "ue2": b[1]}, seed=s, attacker=att, case=case)
                if case == "mimic":
                    i1, i2 = rng.choice(len(pool), 2, replace=False)
                    ph["donor"] = np.r_[pool[i1], pool[i2]][:150].tolist()
                phases.append(ph)
            runs.append(dict(id="lz%03d" % len(runs), live=True, benign_only=False, case=case, phases=phases))
    for r in range(6):
        phases = []
        for j in range(PHASES_PER_RUN):
            s, b = draw(s)
            phases.append(dict(name="p%d" % (j + 1), bands={"ue1": b[0], "ue2": b[1]}, seed=s))
        runs.append(dict(id="lz%03d" % len(runs), live=True, benign_only=True, phases=phases))
    order = rng.permutation(len(runs))
    runs = [runs[i] for i in order]
    for k, r in enumerate(runs):
        r["id"] = "lz%03d" % k
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, cases=list(LIVE2_CASES), defense=LIVE2_DEFENSE, phases_per_run=PHASES_PER_RUN, runs=runs,
                note="live v5: blind test, Madrid users (cell, rnti) never replayed before; donors = live v4 benign-only runs (not in training)")


def design_live6(seed, n_runs=84):
    """Advisor step 4 (2026-11-10): benign-only live runs, about 20 UE-hours (n_runs x 6 phases x 75 s x 2 UEs), same format as the
    benign-only runs of the live test (KPM as reported, xApp in observe mode, deployed model and rules unchanged); Madrid users
    (cell, rnti) never replayed before, the live-test users included; same band weights."""
    import schedules
    rng = np.random.default_rng(seed)
    used, users = used_users(("oran_flooding_live", "oran_flooding_live2", "oran_flooding_live3", "oran_flooding_live4", "oran_flooding_live5"))
    win = np.load(schedules.WINDOWS_NPZ)

    def fresh(band, s):
        i = schedules.real_window(band, np.random.default_rng(s))["index"]
        return i, tuple(int(x) for x in win["src_" + band][i][:2])

    runs, s = [], 1_700_000
    for r in range(n_runs):
        phases = []
        for j in range(PHASES_PER_RUN):
            while True:
                s += 10
                b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
                w = [(b[k],) + fresh(b[k], s + k + 1) for k in range(2)]
                if all((x[0], x[1]) not in used and x[2] not in users for x in w) and w[0][2] != w[1][2]:
                    for x in w:
                        used.add((x[0], x[1])); users.add(x[2])
                    break
            phases.append(dict(name="p%d" % (j + 1), bands={"ue1": b[0], "ue2": b[1]}, seed=s))
        runs.append(dict(id="lb%03d" % r, live=True, benign_only=True, phases=phases))
    return dict(seed=seed, weights=WEIGHTS, defense=LIVE2_DEFENSE, phases_per_run=PHASES_PER_RUN, runs=runs,
                note="live benign-only (advisor step 4): Madrid users (cell, rnti) never replayed before, live-test users included")


# End-to-end mitigation (2026-11-13, advisor: 20-30 attack runs; bytes to the DN, decision-to-effect latency, escalation at
# L2, TTL). Actions ON (actuate), deployed model and thresholds unchanged. A run keeps ONE attacker UE and ONE KPM case
# for all its phases (the MITM is there before, during and after the attack), and the defence state carries over between
# phases (no reset) so the TTL ladder and the repeat offence are seen:
#   p0 benign | p1 attack (onset U(0,15) s) | p2 attack carried on (onset 0) | p3-p5 attacker silent (225 s >= the e2e TTL
#   ladder 120 + 60 + 30 s) | p6 attack again, inside the probation | p7 attacker silent.
# Both UEs run their twin as a REACTIVE benign flow (backs off on loss, pacer.py "reactive"); the attacker does not react.
# 24 attack runs: L2 12, L1 6 (udp/syn/icmp x2), L3 6 (tcp_shortconn/dns_client x3); KPM honest / hide0.1 / mimic balanced
# inside each level; anchors rotate. Madrid users (cell, rnti) never replayed before (all earlier designs and the given
# calibration designs). Mimic donors: benign UE-phases of the live v4 benign-only runs (as live v5).
E2E_PHASES = ("p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7")
E2E_ATTACK = {"p1": None, "p2": 0, "p6": None}          # attack phase -> onset_s (None: drawn as usual)
# releaseOnBlock false: on RFsim the OAI nrUE released by the gNB goes RRC_IDLE and never comes back on UL data (no
# service request; its RRC queue overflows), checked 2026-11-13; the block level is then block slice + UPF block.
E2E_TIMING = {"expiryS": [30, 60, 120, 0], "probationS": 180, "fusionS": 10, "releaseOnBlock": False}
E2E_DEFENSE = {"enabled": True, "core": True, "mode": "slice", "classifier": "xgb", "actuate": True, "clear_tamper": True,
               "timing": E2E_TIMING, "escalation": {"enabled": True, "graceS": 5, "hits": 8, "samples": 10, "overRatio": 0.25}}
E2E_LIVE = ("oran_flooding_live", "oran_flooding_live2", "oran_flooding_live3", "oran_flooding_live4", "oran_flooding_live5",
            "oran_flooding_live6")


def design_e2e(seed, n_runs=None, levels=None, prefix="le", exclude=(), note=""):
    """levels: list of cells (dict evasion/mode/backend) or None for the campaign mix; exclude: extra design dirs whose
    users are excluded (calibration runs)."""
    import schedules
    rng = np.random.default_rng(seed)
    used, users = used_users(E2E_LIVE + tuple(exclude))
    pool = donor_pool_live4()
    win = np.load(schedules.WINDOWS_NPZ)

    def fresh(band, s):
        i = schedules.real_window(band, np.random.default_rng(s))["index"]
        return i, tuple(int(x) for x in win["src_" + band][i][:2])

    if levels is None:
        levels = [dict(evasion="L2") for _ in range(12)] + [dict(evasion="L1", mode=m) for m in ("udp", "syn", "icmp") for _ in range(2)] + \
                 [dict(evasion="L3", backend=b) for b in ("tcp_shortconn", "dns_client") for _ in range(3)]
    cells = [dict(c) for c in levels]
    for L in sorted({c["evasion"] for c in cells}):     # KPM cases balanced inside each level (unless given)
        idx = [i for i, c in enumerate(cells) if c["evasion"] == L and "case" not in c]
        cs = [LIVE2_CASES[k % 3] for k in range(len(idx))]
        for i, k in zip(idx, rng.permutation(cs)):
            cells[i]["case"] = str(k)
    anchors = list(ANCHORS)
    for k, c in enumerate(cells):
        c["anchor"] = anchors[k % 3]
        c["victim"] = "responsive" if c["evasion"] == "L3" or c.get("mode") in ("syn", "icmp") else "silent"
    cells = [cells[i] for i in rng.permutation(len(cells))][:n_runs or len(cells)]
    runs, s = [], 1_900_000 + (seed % 1000) * 1000
    for r, c in enumerate(cells):
        att = "ue%d" % (1 + r % 2)
        phases = []
        for name in E2E_PHASES:
            while True:
                s += 10
                b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
                w = [(b[k],) + fresh(b[k], s + k + 1) for k in range(2)]
                if all((x[0], x[1]) not in used and x[2] not in users for x in w) and w[0][2] != w[1][2]:
                    for x in w:
                        used.add((x[0], x[1])); users.add(x[2])
                    break
            ph = dict(name=name, bands={"ue1": b[0], "ue2": b[1]}, seed=s, attacker=att, case=c["case"])
            if name in E2E_ATTACK:
                ph.update({k: v for k, v in c.items() if k != "case"})
                if E2E_ATTACK[name] is not None:
                    ph["onset_s"] = E2E_ATTACK[name]
            if c["case"] == "mimic":
                i1, i2 = rng.choice(len(pool), 2, replace=False)
                ph["donor"] = np.r_[pool[i1], pool[i2]][:75].tolist()
            phases.append(ph)
        runs.append(dict(id="%s%03d" % (prefix, r), live=True, e2e=True, benign_only=False, case=c["case"], attacker=att,
                         evasion=c["evasion"], phases=phases))
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, cases=list(LIVE2_CASES), defense=E2E_DEFENSE, phases=list(E2E_PHASES),
                attack_phases=E2E_ATTACK, runs=runs, note=note or "end-to-end mitigation: actions on, reactive benign, one attacker and one KPM case per run")


CLOSED_LOOP = {"rtt_budget_s": 0.25, "timeout_s": 1.0}   # planbuilder.closed_loop_params
E2E_FORCE = {"p1": "ue1", "p2": "ue2", "p4": "ue1", "p5": "ue2"}   # calibration: benign UE forced to level 2 for 60 s


def design_e2e_calib(seed):
    """Calibration before the campaign (not in the results): 4 benign-only runs in which each benign UE is forced to
    level 2 for 60 s four times per run (16 forced limits per 2 runs: does escalation by response wrongly block a reactive
    benign UE, how fast does it back off), plus 4 L2 attack runs in the end-to-end format (checks the measurement path)."""
    d = design_e2e(seed, levels=[dict(evasion="L2") for _ in range(4)], prefix="lc", note="end-to-end calibration (not in results)")
    import schedules
    rng = np.random.default_rng(seed + 1)
    used, users = used_users(E2E_LIVE)
    for r in d["runs"]:
        for p in r["phases"]:
            for k, ue in enumerate(("ue1", "ue2")):
                b = p["bands"][ue]; i = schedules.real_window(b, np.random.default_rng(p["seed"] + k + 1))["index"]
                used.add((b, i)); users.add(tuple(int(x) for x in np.load(schedules.WINDOWS_NPZ)["src_" + b][i][:2]))
    win = np.load(schedules.WINDOWS_NPZ)
    s = 2_500_000 + (seed % 1000) * 1000
    for r in range(4):
        phases = []
        for name in E2E_PHASES:
            while True:
                s += 10
                b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
                w = []
                for k in range(2):
                    i = schedules.real_window(b[k], np.random.default_rng(s + k + 1))["index"]
                    w.append((b[k], i, tuple(int(x) for x in win["src_" + b[k]][i][:2])))
                if all((x[0], x[1]) not in used and x[2] not in users for x in w) and w[0][2] != w[1][2]:
                    for x in w:
                        used.add((x[0], x[1])); users.add(x[2])
                    break
            ph = dict(name=name, bands={"ue1": b[0], "ue2": b[1]}, seed=s, case="honest")
            if name in E2E_FORCE:
                ph["force"] = {"ue": E2E_FORCE[name], "level": 2, "ttl_s": 60}
            phases.append(ph)
        d["runs"].append(dict(id="lc%03d" % len(d["runs"]), live=True, e2e=True, benign_only=True, case="honest", phases=phases))
    return d


# Calibration of the relative escalation (2026-11-13, nhật ký "luật leo thang tương đối"): escalation in shadow mode
# (computed and logged, never acted on), relRatio 0.5 only to check the xApp against the offline replay online; rho is
# chosen offline by scripts/ml/esc_calib.py with the rule fixed in the logbook before these runs.
E2E_CALIB2_DEFENSE = dict(E2E_DEFENSE, escalation=dict(E2E_DEFENSE["escalation"], relRatio=0.5, refS=3, shadow=True))
CALIB2_FORCE = ("p1", "p2", "p4", "p5")                  # forced phases, UE alternating ue1 / ue2 as E2E_FORCE
# hard cases of the development campaign, replayed with a forced limit at the second of the natural one (at_s from
# second 0 of the UE's schedule, events.jsonl of the campaign): (new phase, source run, source phase, UE, at_s, ttl_s,
# client phase: the source phase whose L3 client of the benign UE runs in this phase)
CALIB2_REPLAY = [("p0", "le003", "p0", None, None, None, None),
                 ("p1", "le003", "p3", "ue1", 3.1, 60, None),      # branch A (le003)
                 ("p2", "le019", "p4", "ue1", 12.5, 60, None),     # branch A (le019, first limit)
                 ("p3", "le019", "p5", "ue1", 54.5, 60, None),     # branch B (le019: limit from expiry, blocked in p6 ...)
                 ("p4", "le019", "p6", None, None, None, "p6"),    # ... with the L3 client running)
                 ("p5", "le022", "p6", "ue2", 30.9, 60, "p6"),     # branch B (le022, L3 client)
                 ("p6", "le022", "p7", None, None, None, None),
                 ("p7", "le003", "p7", None, None, None, None)]


def heaviest_window(specs, width=10, last=60):
    """start (s) of the heaviest `width` s of the planned UL of a UE (sum of its flows), w in [0, last]: the same
    planbuilder run.py uses, so the forced second is that of the real schedule"""
    import planbuilder
    tot = np.zeros(75)
    for sp in specs:
        plan, _ = planbuilder.build_plan(sp, 75, "10.0.0.1", None, 5000)
        b = np.array([float(x.get("bytes") or 0.0) for x in plan["seconds"]][:75])
        tot[:len(b)] += b
    sums = [tot[w:w + width].sum() for w in range(0, last + 1)]
    return int(np.argmax(sums))


def design_e2e_calib2(seed):
    """Calibration of the relative escalation (not in the results), 12 runs, escalation in shadow mode:
    lk000: the hard benign cases of the development campaign replayed (le003, le019 x2, le022; L3 client closed loop);
    lk001-lk004: attack runs in the end-to-end format (L2 x2, L3 tcp / dns; KPM honest, hide0.1, mimic, honest);
    lk005-lk011: benign only, fresh users, 4 forced limits per run (p1, p2, p4, p5, UE alternating) at the heaviest
    10 s of the forced UE's schedule (at_s = w - 2), 2 on the twin alone and 2 with a closed-loop benign L3 client on
    that UE (dns / tcp alternating, anchor rotating): 14 twin, 7 dns, 7 tcp."""
    import schedules
    root = pathlib.Path(__file__).resolve().parents[4]
    old = {r["id"]: r for r in json.load(open(root / "research/datasets/oran_flooding_e2e/manifest/design.json"))["runs"]}
    runs = []
    # lk000: replay of the hard cases
    phases = []
    for name, src, sp, ue, at_s, ttl, cph in CALIB2_REPLAY:
        o = next(p for p in old[src]["phases"] if p["name"] == sp)
        ph = dict(name=name, bands=dict(o["bands"]), seed=o["seed"], case="honest", replay_of="%s %s" % (src, sp))
        if cph:
            c = next(p for p in old[src]["phases"] if p["name"] == cph)
            ben = "ue1" if c["attacker"] == "ue2" else "ue2"
            ph["client"] = {"ue": ben, "backend": c["backend"], "anchor": c["anchor"]}
            ph["seed"] = c["seed"]; ph["bands"] = dict(c["bands"])
        if ue:
            ph["force"] = {"ue": ue, "level": 2, "ttl_s": ttl, "at_s": at_s, "kind": "replay %s %s" % (src, sp)}
        phases.append(ph)
    runs.append(dict(id="lk000", live=True, e2e=True, benign_only=True, case="honest", phases=phases, defense=E2E_CALIB2_DEFENSE))
    # lk001-lk004: attack runs, cases given
    levels = [dict(evasion="L2", case="honest"), dict(evasion="L2", case="hide0.1"), dict(evasion="L3", backend="tcp_shortconn", case="mimic"),
              dict(evasion="L3", backend="dns_client", case="honest")]
    d = design_e2e(seed, levels=levels, prefix="lk", exclude=("oran_flooding_e2e", "oran_flooding_e2e_calib"),
                   note="calibration of the relative escalation (not in results)")
    for k, r in enumerate(d["runs"]):
        r["id"] = "lk%03d" % (1 + k); r["defense"] = E2E_CALIB2_DEFENSE
        runs.append(r)
    # lk005-lk011: benign only, fresh users (not in any earlier design nor in lk001-lk004)
    rng = np.random.default_rng(seed + 2)
    used, users = used_users(E2E_LIVE + ("oran_flooding_e2e", "oran_flooding_e2e_calib"))
    win = np.load(schedules.WINDOWS_NPZ)
    for r in d["runs"]:
        for p in r["phases"]:
            for k, ue in enumerate(("ue1", "ue2")):
                b = p["bands"][ue]; i = schedules.real_window(b, np.random.default_rng(p["seed"] + k + 1))["index"]
                used.add((b, i)); users.add(tuple(int(x) for x in win["src_" + b][i][:2]))
    s = 2_600_000 + (seed % 1000) * 1000
    anchors = list(ANCHORS); na = 0; nb = 0
    for r in range(7):
        kinds = [str(x) for x in rng.permutation(["twin", "twin", "client", "client"])]
        phases = []
        for name in E2E_PHASES:
            while True:
                s += 10
                b = rng.choice(list(WEIGHTS), size=2, p=list(WEIGHTS.values())).tolist()
                w = []
                for k in range(2):
                    i = schedules.real_window(b[k], np.random.default_rng(s + k + 1))["index"]
                    w.append((b[k], i, tuple(int(x) for x in win["src_" + b[k]][i][:2])))
                if all((x[0], x[1]) not in used and x[2] not in users for x in w) and w[0][2] != w[1][2]:
                    for x in w:
                        used.add((x[0], x[1])); users.add(x[2])
                    break
            ph = dict(name=name, bands={"ue1": b[0], "ue2": b[1]}, seed=s, case="honest")
            if name in CALIB2_FORCE:
                j = CALIB2_FORCE.index(name); ue = ("ue1", "ue2")[j % 2]; kind = kinds[j]
                k_ue = 0 if ue == "ue1" else 1
                specs = [{"v4": True, "model": "real_window", "backend": "pacer", "band": ph["bands"][ue], "grid": "gnb", "timing": "tti",
                          "role": "benign", "seed": s + k_ue + 1}]
                if kind == "client":
                    be = ("dns_client", "tcp_shortconn")[nb % 2]; nb += 1
                    ph["client"] = {"ue": ue, "backend": be, "anchor": anchors[na % 3]}; na += 1
                    kind = be
                    specs.append({"v4": True, "evasion": "L3", "anchor_bps": ANCHORS[ph["client"]["anchor"]], "band": "P4", "timing": "tti",
                                  "victim_mode": "responsive", "backend": be, "role": "benign", "seed": s + 6})
                wst = heaviest_window(specs)
                ph["force"] = {"ue": ue, "level": 2, "ttl_s": 60, "at_s": max(0, wst - 2), "kind": kind, "heavy_start_s": wst}
            phases.append(ph)
        runs.append(dict(id="lk%03d" % len(runs), live=True, e2e=True, benign_only=True, case="honest", phases=phases, defense=E2E_CALIB2_DEFENSE))
    return dict(seed=seed, weights=WEIGHTS, anchors=ANCHORS, cases=list(LIVE2_CASES), defense=E2E_CALIB2_DEFENSE, phases=list(E2E_PHASES),
                attack_phases=E2E_ATTACK, runs=runs, closed_loop=CLOSED_LOOP,
                note="calibration of the relative escalation (not in results): escalation shadow, forced limits at the heaviest 10 s, "
                     "closed-loop benign L3 clients, hard development cases replayed")


def scenario_e2e(run):
    """run.py scenario of an end-to-end run: twin flows reactive on both UEs, attack flows in the attack phases, the
    attacker's KPM tampered in every phase (honest: none), defence state carried over between phases."""
    phases = [{"name": "idle", "duration": 10}]
    for p in run["phases"]:
        if "evasion" in p:
            ph = scenario({"id": run["id"], "phases": [p]})["phases"][1]
            if p.get("onset_s") is not None:
                for ue in ph["flows"]:
                    if "ul_attack" in ph["flows"][ue]:
                        ph["flows"][ue]["ul_attack"]["onset_s"] = p["onset_s"]
        else:
            fl = {ue: {"ul": {"v4": True, "model": "real_window", "backend": "pacer", "band": p["bands"][ue], "grid": "gnb", "timing": "tti",
                              "role": "benign", "seed": p["seed"] + k + 1}} for k, ue in enumerate(("ue1", "ue2"))}
            if p.get("client"):                         # calibration: a benign L3 client on one UE (spec as scenario())
                c = p["client"]
                fl[c["ue"]]["ul_client"] = {"v4": True, "evasion": "L3", "anchor_bps": ANCHORS[c["anchor"]], "band": "P4", "timing": "tti",
                                            "victim_mode": "responsive", "backend": c["backend"], "role": "benign", "seed": p["seed"] + 6}
            ph = {"name": p["name"], "duration": 75, "attack": False, "flows": fl}
        for ue in ph["flows"]:
            ph["flows"][ue]["ul"]["reactive"] = True
            if "ul_client" in ph["flows"][ue]:             # benign L3 client: closed loop (2026-11-13), the attacker stays open loop
                ph["flows"][ue]["ul_client"]["closed_loop"] = dict(run.get("closed_loop") or CLOSED_LOOP)   # per run: RTT budget raised by the logbook rule
        if p["case"] == "mimic":
            ph["tamper"] = {"ue": p["attacker"], "series": p["donor"][:75]}
        elif LIVE_CASES.get(p["case"]) is not None:
            ph["tamper"] = {"ue": p["attacker"], "factor": LIVE_CASES[p["case"]]}
        ph["case"] = p["case"]
        if p.get("force"):
            ph["force"] = p["force"]
        phases.append(ph)
    sc = scenario({"id": run["id"], "phases": []})
    sc.update(name="ds-flood-e2e-" + run["id"], description="End-to-end mitigation run %s (actions on)" % run["id"], phases=phases,
              variants=[{"name": "e2e-actuate", "defense": dict(run.get("defense") or E2E_DEFENSE)}])
    return sc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="research/datasets/oran_flooding_twin/manifest/design.json"); ap.add_argument("--seed", type=int, default=20261104)
    ap.add_argument("--l2", action="store_true"); ap.add_argument("--live", action="store_true"); ap.add_argument("--live2", action="store_true")
    ap.add_argument("--live5", action="store_true"); ap.add_argument("--live6", action="store_true"); ap.add_argument("--runs", type=int, default=84)
    ap.add_argument("--e2e", action="store_true"); ap.add_argument("--e2e-calib", action="store_true"); ap.add_argument("--e2e-calib2", action="store_true")
    ap.add_argument("--exclude", default="oran_flooding_e2e_calib", help="--e2e: comma-separated designs whose users are excluded")
    ap.add_argument("--prefix", default="le", help="--e2e: run id prefix")
    ap.add_argument("--rel-ratio", type=float, help="--e2e: relative escalation rho (frozen on the calibration), live (shadow off), refS 3; "
                    "written into every run's defence")
    ap.add_argument("--rtt-budget", type=float, help="--e2e: RTT budget of the closed-loop benign L3 clients, written into every run")
    a = ap.parse_args()
    if a.e2e or a.e2e_calib or a.e2e_calib2:
        if a.e2e_calib2:  # calibration of the relative escalation (12 runs, shadow mode)
            d = design_e2e_calib2(a.seed)
        elif a.e2e_calib:   # 4 L2 calibration runs, one per case and one extra honest; their users are excluded from the campaign
            d = design_e2e_calib(a.seed)
        else:
            d = design_e2e(a.seed, prefix=a.prefix, exclude=tuple(x for x in a.exclude.split(",") if x))
            if a.rel_ratio is not None:   # held-out campaign of the relative escalation: the parameters stated in every run
                dfn = dict(E2E_DEFENSE, escalation=dict(E2E_DEFENSE["escalation"], relRatio=a.rel_ratio, refS=3, shadow=False))
                d["defense"] = dfn
                for r in d["runs"]:
                    r["defense"] = dfn
            if a.rtt_budget is not None:
                d["closed_loop"] = dict(CLOSED_LOOP, rtt_budget_s=a.rtt_budget)
                for r in d["runs"]:
                    r["closed_loop"] = dict(d["closed_loop"])
        p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d, indent=1) + "\n")
        print(len(d["runs"]), "runs", sum(len(r["phases"]) for r in d["runs"]), "phases"); raise SystemExit
    d = design_live6(a.seed, a.runs) if a.live6 else design_live5(a.seed) if a.live5 else design_live2(a.seed) if a.live2 else design_live(a.seed) if a.live else design_l2(a.seed) if a.l2 else design(a.seed)
    p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d, indent=1) + "\n")
    print(len(d["runs"]), "runs", sum(len(r["phases"]) for r in d["runs"]), "phases")
