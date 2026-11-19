"""Assemble a concrete per-second backend plan (v4 plan §5) from a schedule model,
a load level, the shared size prior and (for attackers) the mixer. One place ties
schedules.py + sizes.py + mixer.py together so BOTH classes of one design cell are
built the same way and are load-matched.

A "spec" (from a scenario YAML or the design) names:
  backend : pacer | hping | iperf | tcp_shortconn | dns_client
  model   : cbr|poisson|mmpp2|onoff_pareto|fgn|hawkes|pulsing   (rate schedule)
            real_window = benign twin, replay of a real window; takes `band` and `seed`, no `level`
  level   : mean IP bytes/s (the load level L1/L2/L3 -> bytes/s)
  role    : "benign" | "attack"
  seed    : int (reproducible)
  mode    : hping mode (udp|syn|icmp); size_alpha: Dirichlet concentration

For role="attack" the UE also runs a benign background b (20-60% of level) and the
attack component a, gated by m (all-on, or the pulsing square wave); x = b + ρ·m·a
with mean(x)=level, so the attacker and its benign counterpart in the same cell
carry the SAME mean load — volume cannot separate them (the thesis control).
"""
import numpy as np

import schedules
import sizes

BACKEND_FIXED = {"syn": "syn", "icmp": "icmp"}        # hping modes with protocol-fixed size


def _mean_size_for(spec, rng):
    """Size prior mean + the bin list the pacer will sample from."""
    mode = spec.get("mode")
    if spec["backend"] == "synflood":
        return float(sizes.FIXED["syn"]), None       # raw 40/60 B SYN, no size prior
    if spec["backend"] == "hping" and mode in BACKEND_FIXED:
        s = sizes.FIXED[{"syn": "syn", "icmp": "icmp_echo"}[mode]]
        return float(s), [[s, 1.0]]
    if spec["backend"] in ("tcp_shortconn", "dns_client"):
        return None, None                            # count-driven, size is protocol-fixed
    w = sizes.draw_mix(rng, spec.get("size_alpha", 1.0))
    return sizes.mean_size(w), sizes.mix_list(w)


def _series(model, rbar, T, rng, mean_size, **kw):
    r = schedules.make(model, rbar, T, rng, mean_size or 256.0, **kw)
    return np.asarray(r["bytes_s"], dtype=float), r["params"], r.get("process", "even")


# Capacity of the path: the OAI UE queues what it cannot send (up to 50 MB UL), which would smear a
# real window over later seconds. Seconds above this are cut and counted in the meta.
REPLAY_CAP_BYTES_S = {"ul": 1_000_000, "dl": 1_000_000}
REPLAY_SPAN = [0.05, 0.75]     # send inside this part of each second, so a second's bytes stay in one stats second


def _replay_seconds(series, quantiles, rng, cap, overhead, tti=None, scale=1.0):
    """tti = (ms, bytes) of the window: each packet then carries its real send time inside the second.
    scale: LTE sensitivity only; every second is multiplied before the clip. Never used for the dataset."""
    out, clipped, floored, no_tti = [], 0, 0, 0
    for i, v in enumerate(series):
        v = float(v) * scale
        if v > cap:
            v, clipped = float(cap), clipped + 1
        floored += int(0 < v < sizes.MIN_IP + overhead)
        row = {"bytes": v, "pkts": sizes.packetize(v, quantiles, rng, overhead)}
        if tti is not None:
            m = (tti[0] // 1000) == i
            if row["pkts"] and not m.any():    # bytes without a TTI row (null raw rows): send mid-second, counted in meta
                row["offs"], no_tti = [0.5] * len(row["pkts"]), no_tti + 1
            else:
                row["offs"] = sizes.place(row["pkts"], overhead, (tti[0][m] % 1000) / 1000.0, tti[1][m])
        out.append(row)
    return out, clipped, floored, no_tti


def build_replay(spec, T, dst, bind, port):
    """Benign twin: replay of a real window of `band`. UL and DL come
    from the same window and are not rescaled; packet lengths come from one app of the band. The DL
    seconds are left in plan["dl_seconds"] for the caller."""
    if T != schedules.WINDOW_LEN:
        raise ValueError("real_window needs a phase of %d s, got %d" % (schedules.WINDOW_LEN, T))
    band = spec["band"]
    rng = np.random.default_rng(spec["seed"])
    w = schedules.real_window(band, rng, spec.get("windows_npz", schedules.WINDOWS_NPZ))
    apps = {k: v for k, v in sizes.app_priors().items() if v["band"] == band}
    app = spec.get("app") or sorted(apps)[int(rng.integers(len(apps)))]
    scale = float(spec.get("scale", 1.0))
    tti = {d: schedules.window_tti(band, w["index"], d, spec.get("tti_npz", schedules.WINDOWS_TTI_NPZ)) for d in ("ul", "dl")} if spec.get("timing") == "tti" else {"ul": None, "dl": None}
    ul, ul_clip, ul_floor, ul_no_tti = _replay_seconds(w["ul"], apps[app]["ul_size_q"], rng, REPLAY_CAP_BYTES_S["ul"], sizes.MAC_OVERHEAD["ul"], tti["ul"], scale)
    dl, dl_clip, dl_floor, dl_no_tti = _replay_seconds(w["dl"], apps[app]["dl_size_q"], rng, REPLAY_CAP_BYTES_S["dl"], sizes.MAC_OVERHEAD["dl"], tti["dl"], scale)
    plan = {"dst": dst, "bind": bind, "ports": [port], "backend": "pacer", "process": "poisson",
            "span": REPLAY_SPAN, "seconds": ul, "dl_seconds": dl, "seed": int(spec["seed"])}
    n_pkts = sum(len(x["pkts"]) for x in ul)
    meta = {"backend": "pacer", "model": "real_window", "role": "benign", "band": band, "app": app,
            "level_bytes_s": float(w["ul"].mean()), "seed": int(spec["seed"]),
            "mean_size": (sum(sum(x["pkts"]) for x in ul) / n_pkts) if n_pkts else None,
            "window": {"cell": w["src"][0], "rnti": w["src"][1], "start": w["src"][2], "index": w["index"]},
            "ul_clipped_s": ul_clip, "dl_clipped_s": dl_clip, "ul_floored_s": ul_floor, "dl_floored_s": dl_floor,
            "target_mean_bytes_s": float(np.mean([x["bytes"] for x in ul])),
            "target_dl_mean_bytes_s": float(np.mean([x["bytes"] for x in dl])), "timing": spec.get("timing", "second"), "scale": scale, "ul_no_tti_s": ul_no_tti, "dl_no_tti_s": dl_no_tti, "params": {}}
    return plan, meta


# hping3 packets without payload: the 42 / 54 / 42 B frames of 5G-NIDD minus 14 B Ethernet
ATTACK_IP_LEN = {"udp": 28, "syn": 40, "icmp": 28}
L3_UL_BYTES = {"tcp_shortconn": 300.0, "dns_client": 56.0}     # UL IP bytes of one exchange
PRE_ROLL_S = 15
L2_MIN_ACTIVE_S = 10


def build_attack(spec, T, dst, bind, port):
    """Attack flow laid over the benign twin of the same UE: the twin keeps its own flow, unscaled.
    `anchor_bps` is the UL rate of an active second, onset uniform over the pre-roll. evasion L1: hping3 at the anchor, default
    packets; L2: UDP in the rhythm, TTI times and sizes of another real window of `band`, active seconds scaled to the anchor mean;
    L3: real clients against the DN sink. No ramp or react here."""
    rng = np.random.default_rng(spec["seed"])
    evasion, anchor = spec["evasion"], float(spec["anchor_bps"])
    onset = int(rng.integers(0, PRE_ROLL_S))
    if spec.get("onset_s") is not None:                # end-to-end runs: an attack carried on from the previous phase starts at 0
        onset = int(spec["onset_s"])
    active = np.arange(T) >= onset
    extra = {}
    if evasion == "L1":
        backend, mode = "hping", spec["mode"]
        size = ATTACK_IP_LEN[mode]
        pps = int(round(anchor / 8.0 / size))
        seconds = [{"bytes": pps * size * float(a), "pps": pps if a else 0} for a in active]
        extra = {"mode": mode, "sizes": [[size, 1.0]]}
    elif evasion == "L2":
        backend, band = "pacer", spec["band"]
        for _ in range(100):
            w = schedules.real_window(band, rng, spec.get("windows_npz", schedules.WINDOWS_NPZ))
            if (np.asarray(w["ul"])[onset:] > 0).sum() >= L2_MIN_ACTIVE_S:
                break
        else:
            raise ValueError("no window of %s with %d active seconds" % (band, L2_MIN_ACTIVE_S))
        ul = np.asarray(w["ul"], float)
        ul[:onset] = 0
        scale = (anchor / 8.0) / ul[ul > 0].mean()
        apps = {k: v for k, v in sizes.app_priors().items() if v["band"] == band}
        app = spec.get("app") or sorted(apps)[int(rng.integers(len(apps)))]
        tti = schedules.window_tti(band, w["index"], "ul") if spec.get("timing") == "tti" else None
        seconds, _, _, _ = _replay_seconds(ul, apps[app]["ul_size_q"], rng, REPLAY_CAP_BYTES_S["ul"], sizes.MAC_OVERHEAD["ul"], tti, scale)
        active = ul > 0
        extra = {"process": "poisson", "span": REPLAY_SPAN}
        size = None
    elif evasion == "L3":
        backend = spec["backend"]
        size = L3_UL_BYTES[backend]
        rate = int(round(anchor / 8.0 / size))
        seconds = [{"bytes": rate * size * float(a), "pps": rate if a else 0} for a in active]
        if spec.get("role") == "benign":               # hard negative: the same client, in the rhythm of a real window; never labelled attack
            for _ in range(100):
                w = schedules.real_window(spec["band"], rng, spec.get("windows_npz", schedules.WINDOWS_NPZ))
                if (np.asarray(w["ul"]) > 0).sum() >= L2_MIN_ACTIVE_S:
                    break
            ul = np.asarray(w["ul"], float)
            n = np.round(rate * ul / ul[ul > 0].mean()).astype(int)
            seconds = [{"bytes": float(x) * size, "pps": int(x)} for x in n]
            active = n > 0
            extra = {"window": {"cell": w["src"][0], "rnti": w["src"][1], "start": w["src"][2], "index": w["index"]}}
    else:
        raise ValueError(evasion)
    plan = {"dst": dst, "bind": bind, "ports": [port], "backend": backend, "seconds": seconds, "seed": int(spec["seed"]),
            "attack_active": [int(a) for a in active], **extra}
    if evasion == "L3" and spec.get("role") == "benign" and spec.get("closed_loop"):
        plan["closed_loop"] = closed_loop_params(spec["closed_loop"], seconds)
    target = float(np.mean([x["bytes"] for x in seconds]))
    window_meta = extra.pop("window", None)
    plan.pop("window", None)
    meta = {"backend": backend, "model": "flood_overlay", "role": spec.get("role", "attack"), "window": window_meta, "evasion": evasion, "anchor_bps": anchor, "onset_s": onset,
            "level_bytes_s": anchor / 8.0, "mean_size": size, "seed": int(spec["seed"]), "attack_active": plan["attack_active"],
            "target_mean_bytes_s": target, "params": {}}
    if "closed_loop" in plan:
        meta["closed_loop"] = plan["closed_loop"]
    if evasion == "L2":
        meta["window"] = {"cell": w["src"][0], "rnti": w["src"][1], "start": w["src"][2], "index": w["index"], "scale": float(scale), "app": app}
    return plan, meta


def closed_loop_params(cl, seconds):
    """closed-loop benign L3 client (2026-11-13, backends dns_client.py / tcp_shortconn.py): the base window of
    outstanding queries / open connections by a fixed rule, never tuned by hand: max(16, ceil(1.5 x peak scheduled
    rate x the RTT budget)), RTT budget 0.25 s (raised only by the rule fixed in the logbook before the calibration);
    the window adapts per second as the reactive benign pacer (AIMD x0.7 on > 5 % lost, + 0.1 x base; the newest two
    seconds pooled, decided only with >= 20 outcomes: one late answer in a quiet second no longer cuts the window
    to 1, the fault found in the calibration oran_flooding_e2e_calib4, logbook 2026-11-13)."""
    cl = cl if isinstance(cl, dict) else {}
    rtt = float(cl.get("rtt_budget_s", 0.25))
    peak = max([int(x.get("pps") or 0) for x in seconds] + [0])
    return {"window": max(16, int(np.ceil(1.5 * peak * rtt))), "timeout_s": float(cl.get("timeout_s", 1.0)),
            "down": 0.7, "up": 0.1, "loss_thr": 0.05, "min_outcomes": 20, "rtt_budget_s": rtt, "peak_pps": peak}


def build_plan(spec, T, dst, bind, port):
    """Return (plan, meta). plan -> runner.run_backend; meta -> flows.json label.

    `seed` drives the behaviour (schedule/mixer). The size prior is drawn from a
    SEPARATE `size_seed` (default = seed): the Phase-3 design gives both flows of one
    size-matched cell the same `size_seed` so their packet-size mix is identical
    per-phase (the dry-run in design.py shows independent draws leave per-cell size
    overlap ≈ 0 even across many reps), while keeping distinct behaviour seeds."""
    if spec.get("model") == "real_window":
        return build_replay(spec, T, dst, bind, port)
    if spec.get("evasion"):
        return build_attack(spec, T, dst, bind, port)
    rng = np.random.default_rng(spec["seed"])
    size_rng = np.random.default_rng(spec.get("size_seed", spec["seed"]))
    backend = spec["backend"]
    model = spec.get("model", "cbr")
    level = float(spec["level"])
    mean_size, size_mix = _mean_size_for(spec, size_rng)

    if spec["role"] == "attack":
        from mixer import background_share, mix
        share = background_share(rng)
        b, _, _ = _series(spec.get("bg_model", "poisson"), share * level, T, rng, mean_size)
        a, aparams, process = _series(model, level, T, rng, mean_size)
        if model == "pulsing":
            m = (a > 0).astype(float)                # attack only while the pulse is on
        else:
            m = np.ones(T)
        x, rho, _ = mix(level, b, a, m)
        bytes_s, params, gate = x, {"attack_model": model, "rho": rho, "bg_share": share, **aparams}, m
    else:
        bytes_s, params, process = _series(model, level, T, rng, mean_size)
        gate = None

    # per-second targets; count-driven backends get pps instead of bytes
    if backend in ("tcp_shortconn", "dns_client"):
        per_unit = 200.0 if backend == "tcp_shortconn" else 1.0
        seconds = [{"pps": int(round(v / per_unit))} if per_unit > 1 else {"pps": int(round(v / 56.0))}
                   for v in bytes_s]                 # dns query ~56 B IP
    else:
        seconds = [{"bytes": float(v), "pps": None} for v in bytes_s]

    plan = {"dst": dst, "bind": bind, "ports": [port], "backend": backend,
            "process": params.get("process", "even") if isinstance(params, dict) else "even",
            "seconds": seconds, "seed": int(spec["seed"])}
    if size_mix:
        plan["sizes"] = size_mix
    if spec.get("mode"):
        plan["mode"] = spec["mode"]
    if gate is not None:
        plan["attack_active"] = [int(g > 0) for g in gate]

    meta = {"backend": backend, "model": model, "role": spec["role"], "level_bytes_s": level,
            "mean_size": mean_size, "seed": int(spec["seed"]), "params": params,
            "target_mean_bytes_s": float(np.mean(bytes_s))}
    return plan, meta
