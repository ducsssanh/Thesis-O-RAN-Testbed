"""Attack mixing (v4 plan §5.3): x_t = b_t + ρ·m_t·a_t.

An attacking UE runs a benign background b (20–60 % of the level, drawn at
random) concurrently with the attack component a, gated by m_t (attack_active,
1 = on; pulsing attacks switch it per second). ρ is chosen so the attacking UE's
mean total equals the load level of the benign counterpart in the same design
cell: E[b] + ρ·E[m·a] = level.
"""
import numpy as np


def background_share(rng, lo=0.2, hi=0.6):
    return float(rng.uniform(lo, hi))


def rho_for(level, b, a, m):
    gated = float(np.mean(m * a))
    if gated <= 0:
        raise ValueError("attack component has zero gated mean")
    return (level - float(np.mean(b))) / gated


def mix(level, b, a, m):
    """Returns (x, rho, attack_part) with mean(x) == level."""
    m = np.asarray(m, dtype=float)
    rho = rho_for(level, b, a, m)
    part = rho * m * np.asarray(a, dtype=float)
    return np.asarray(b, dtype=float) + part, rho, part
