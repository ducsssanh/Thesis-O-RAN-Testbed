"""Shared packet-size prior (v4 plan §5.3) — the SAME prior for both classes.

Sizes are IP-level packet lengths (what URR/profiler/KPM count), so a size s
means a UDP payload of s - 28 bytes. Per phase a Dirichlet draw over the bins gives
the size mix; benign and attack flows of one design cell use draws from the same
prior. Calibration: payloads above ~1200 B are unreliable over the GTP tunnel
(research/testbed/phase0_v4.md), so the largest bin is 1228 B IP (1200 B payload).

Families whose packet size is fixed by the protocol (SYN, ICMP echo) bypass the
prior; each has a benign counterpart with the same fixed size (v4 plan §6.3).
"""
import numpy as np

HDR = 28                                  # IPv4 + UDP
BINS = np.array([64, 256, 576, 1024, 1228])
FIXED = {"syn": 60, "icmp_echo": 84}      # IP lengths of a default SYN and ICMP echo


def draw_mix(rng, alpha=1.0):
    """Dirichlet weights over BINS (one draw per phase)."""
    return rng.dirichlet(np.full(len(BINS), alpha))


def mean_size(weights):
    return float(np.dot(BINS, weights))


def mix_list(weights):
    return [[int(s), float(w)] for s, w in zip(BINS, weights)]


def fixed_mix(kind):
    return [[FIXED[kind], 1.0]]
