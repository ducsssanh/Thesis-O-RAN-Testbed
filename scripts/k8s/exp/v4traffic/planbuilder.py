"""Assemble a concrete per-second backend plan (v4 plan §5) from a schedule model,
a load level, the shared size prior and (for attackers) the mixer. One place ties
schedules.py + sizes.py + mixer.py together so BOTH classes of one design cell are
built the same way and are load-matched.

A "spec" (from a scenario YAML or the design) names:
  backend : pacer | hping | iperf | tcp_shortconn | dns_client
  model   : cbr|poisson|mmpp2|onoff_pareto|fgn|hawkes|pulsing   (rate schedule)
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


def build_plan(spec, T, dst, bind, port):
    """Return (plan, meta). plan -> runner.run_backend; meta -> flows.json label.

    `seed` drives the behaviour (schedule/mixer). The size prior is drawn from a
    SEPARATE `size_seed` (default = seed): the Phase-3 design gives both flows of one
    size-matched cell the same `size_seed` so their packet-size mix is identical
    per-phase (the dry-run in design.py shows independent draws leave per-cell size
    overlap ≈ 0 even across many reps), while keeping distinct behaviour seeds."""
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
