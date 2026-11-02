"""Shared packet-size prior (v4 plan §5.3) — the SAME prior for both classes.

Sizes are IP-level packet lengths (what URR/profiler/KPM count), so a size s
means a UDP payload of s - 28 bytes. Per phase a Dirichlet draw over the bins gives
the size mix; benign and attack flows of one design cell use draws from the same
prior. Calibration: payloads above ~1200 B are unreliable over the GTP tunnel
(research/testbed/phase0_v4.md), so the largest bin is 1228 B IP (1200 B payload).

Families whose packet size is fixed by the protocol (SYN, ICMP echo) bypass the
prior; each has a benign counterpart with the same fixed size (v4 plan §6.3).
"""
import json
import pathlib

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


# ---- per-app prior for the benign twin (TRAFFIC-TWINNING-PLAN §0a rev 4, step 4.2) ----------------
# kr5g_app_priors.json holds 101 quantiles of the IP-level packet length per app, per direction.
# The smallest value in the captures (31-33 B) is below an Ethernet + IP + UDP frame, so the captured
# frame length is the IP length, without a link header.
MAC_OVERHEAD = {"ul": 11, "dl": 7}  # bytes per packet in the gNB DRB counter above the IP length: least-squares slope on
                                    # 2026-11-01 validation runs with small packets (ul 9.9-11.2, dl 5.8-6.8)
MIN_IP = 29          # IPv4 + UDP + 1 B payload: the smallest datagram the pacer sends
MAX_IP = 1228        # above this the GTP path is unreliable (see the module docstring)
MAX_PPS = 2000       # above this a second is sent with MAX_IP packets (per-second load, not packet shape)


APP_PRIORS = pathlib.Path(__file__).resolve().parents[4] / "research/twinning/kr5g_app_priors.json"
_apps = {}


def app_priors(path=APP_PRIORS):
    if path not in _apps:
        _apps[path] = json.loads(pathlib.Path(path).read_text())["apps"]
    return _apps[path]


def packetize(target, quantiles, rng, overhead):
    """IP lengths of the packets of one second, so that their bytes at the gNB MAC add up to `target`.
    Lengths are drawn from the app's quantile table; the last one is cut to fit. A target too small
    for one packet (below MIN_IP + overhead) still gives one packet, reported by the caller as
    floored. Returns a list of ints."""
    if target <= 0:
        return []
    q = np.minimum(np.maximum(np.asarray(quantiles, dtype=float), MIN_IP), MAX_IP)
    if target / (q.mean() + overhead) > MAX_PPS:
        q = np.array([float(MAX_IP)])
    pkts, left = [], float(target)
    while True:
        n = max(int(left / (q.mean() + overhead)), 1)
        for ln in np.interp(rng.random(n), np.linspace(0, 1, q.size), q):
            ln = int(round(ln))
            if ln + overhead >= left:
                ln = int(left - overhead)
                if ln >= MIN_IP or not pkts:
                    pkts.append(max(ln, MIN_IP))
                return pkts
            pkts.append(ln)
            left -= ln + overhead


def place(pkts, overhead, tti_s, tti_bytes):
    """Send time of each packet in its second (TTI replay): a packet goes at the TTI where the second's TTI bytes,
    cumulated, reach the middle of that packet in the second's MAC bytes. tti_s is sorted, in [0, 1)."""
    if not pkts:
        return []
    if len(tti_s) == 0:
        raise ValueError("a second with packets needs TTIs")
    mac = np.asarray(pkts, dtype=float) + overhead
    mid = (np.cumsum(mac) - mac / 2) / mac.sum()
    cum = np.cumsum(np.asarray(tti_bytes, dtype=float))
    idx = np.minimum(np.searchsorted(cum / cum[-1], mid), len(tti_s) - 1)
    return [round(float(x), 4) for x in np.asarray(tti_s, dtype=float)[idx]]
