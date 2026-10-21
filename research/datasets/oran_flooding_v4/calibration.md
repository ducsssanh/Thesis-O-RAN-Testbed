# v4 calibration (measured on the testbed)

All numbers below come from live measurement; sources are `research/testbed/phase0_v4.md`, `research/testbed/calib_v4.jsonl`, `research/testbed/calib_pps_v4.json` and, for the arrival lag, the campaign rows themselves.

## Arrival lag of URR / profiler at the row's second (this campaign)

`*_age_s` = t − source_ts of the latest record with arrival_ts ≤ t (causal as-of join).

| stream | n | median | p90 | p99 | max |
|---|---:|---:|---:|---:|---:|
| kpm | 87294 | 0.83 | 1.00 | 1.00 | 1.03 |
| urr | 86937 | 2.16 | 3.19 | 4.08 | 5.55 |
| prof | 87196 | 1.84 | 2.83 | 3.69 | 4.51 |

## Rate, MTU, pps ceilings and load levels (Phase 0, 2026-10-20)

### §3.2 Calibration — now MEASURED (defense off, 2026-10-20), `research/testbed/calib_v4.jsonl`
- **Per-UE UDP UL rate (payload 1200 B):** achieved = offered and **0% loss** at
  1/2/4/8 Mbit/s; **plateau/ceiling ≈ 8.4 Mbit/s** (16 & 32 Mbit/s offered →
  ~8.4 achieved, 0% loss). Both ue1 and ue2 behave identically (ue2 ceiling ~8.0).
  → **linear region per UE ≈ up to 8 Mbit/s** — well above the v3 ~330 kbps TCP cap.
- **MTU / fragmentation:** payload ≤1200 B clean; **≥1472 B (near/over the 1500 MTU)
  unreliable** over the GTP tunnel (no delivery) → v4 keeps payloads ≤1200 B;
  fragmentation attacks cannot be generated this way (consistent with v3 frag_flood
  exclusion).
- URR/profiler arrival-lag already measured earlier from v3 rows (causal join cap 3–4 s).

### §3.2 pps ceiling + pacer validation — MEASURED 2026-10-20, `research/testbed/calib_pps_v4.json`
Live run of the v4 pacer (ue1, defense off); delivery counted on the DN with a silent
`iptables … -j DROP` rule on udp/5401 (IP-level pkts+bytes, no ICMP back), 3 s drain
before the read. Confirms the pacer follows byte/pps targets AND fixes the §3.2 ceiling:
- **64 B small packets:** sent == delivered, **0% loss up to 8000 pps** (4.1 Mbit/s);
  12000 pps → 0.3% loss, 16000 → 1.3%. **Usable small-packet pps ceiling ≈ 8000 pps/UE.**
- **1228 B packets:** 0% loss through **10 Mbit/s**; 12 Mbit/s → 3.3% loss. Large-packet
  linear region ≈ 10 Mbit/s (consistent with the earlier ~8.4 plateau, slightly higher
  with the settle). → keep attack/benign byte-rates within these regions so loss is not
  itself a label signal.
- Pacer validated live: realised sent rate matched target within ~2% across the sweep.

### Proposed load levels (CONFIRMED in-region)
L1 ≈ 0.4, L2 ≈ 0.8, L3 ≈ 1.2 Mbit/s offered UL (payload ≤1200 B) — all inside the
linear region with headroom; could extend to 2–4 Mbit/s if higher separation wanted.

**Phase 0 is COMPLETE.** Next per the v4 plan: Phase 1 (raw KPM/URR/prof loggers +
causal `build_dataset.py` + unit tests), gated on approval. The watchdog/resume
harness should precede the full 48h campaign.

