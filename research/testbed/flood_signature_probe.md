# Flood signature probe — Phase E mechanism validation

Date: 2026-10-19. Campaign `artifacts/experiments/20261019-111509_flood-probe`
(detection OFF, ue1 subject, ue2 benign background, 1 rep). **This is a mechanism
check, not dataset v1.** It answers one question: does each hping3 flood style
traverse the testbed and leave a distinct, volume-independent signature in the
eBPF UPF profiler? Yes.

## Per-phase profiler signature (ue1, mean over the phase, n≈36 rows each)

| phase | urr kbps | prof pps | mean B | udp | syn | icmp | frag | dns | dst_est | prb UL% | cell UL% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| benign-heavy | 2161 | 219 | 1286 | 219 | 0 | 0 | 0 | 0 | 1.01 | 48 | 70 |
| udp-flood | 335 | 389 | 150 | 389 | 0 | 0 | 0 | 0 | 1.01 | 25 | 51 |
| syn-flood | 168 | 390 | 98 | ~0 | 390 | 0 | 0 | 0 | 1.04 | 18 | 49 |
| icmp-flood | 332 | 388 | 150 | ~0 | 0 | 388 | 0 | 0 | 1.01 | 25 | 51 |
| frag-flood | 4905 | 12354 | 94 | 12354 | 0 | 0 | 12354 | 0 | 1.01 | 64 | 81 |
| dns-flood | 330 | 387 | 150 | 0 | 0 | 0 | 0 | 387 | 1.01 | 25 | 50 |
| fanout | 329 | 390 | 150 | 390 | 0 | 0 | 0 | 0 | **185** | 25 | 51 |

## What this proves

1. **Each family is cleanly distinguishable by behaviour, not volume:**
   - protocol mix isolates the family: syn→`tcp_syn`, icmp→`icmp`, dns→`dns`
     (UDP:53 correctly classed as DNS), frag→`frag`+`udp`, udp/fanout→`udp`.
   - `mean_bytes`: benign 1286 B vs every flood 94–150 B — a strong separator
     orthogonal to throughput.
   - `prof_pps`: benign 219 vs floods ~390 (per byte-rate, floods are packet-dense).
   - `dst_estimate`: fanout **185 distinct destinations** vs ~1 for a single-server
     upload or a single-target flood — captures DDoS-style fan-out.
2. **URR/profiler bind correctly under flood** (0 % missingness across 780 rows),
   so there is no label-correlated missingness to leak.
3. **PRB tracks load** (resource impact), not maliciousness — belongs to the
   prioritiser, not the detector, exactly as designed.

## Two issues to fix before dataset v1

- **Load is NOT matched yet** (this probe was not meant to be): benign ≈2160 kbps
  while most floods ≈330 kbps, and frag overshot to 4905 kbps. So here *volume*
  also separates the classes — the NCSRD confound. Dataset v1 must match the
  byte-rate (what URR/KPM see) across benign and malicious so that **only
  behaviour** can separate them.
- **frag_flood is uncontrolled:** hping `-f` fragments at 16 B boundaries, so a
  1400 B payload became ~82 fragments → 12354 pps / 4905 kbps at a nominal 150 pps.
  Fix with an explicit fragment size (`--mtu`) so frag load is controllable.

## Enabling finding for load-matching

The frag phase shows the UE/RFsim sustained **>12000 small frames/s**. So raising
a small-packet flood to ~1700 pps (≈2 Mbit/s at 150 B) to overlap a legitimate
heavy upload is feasible — load-matched benign-vs-malicious across a real range is
achievable, not pps-bound at the levels we need.
