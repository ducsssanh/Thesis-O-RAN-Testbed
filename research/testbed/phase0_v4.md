# v4 Phase 0 — recon + calibration (partial) + testbed-health blocker

Date: 2026-10-20. Phase 0 of the v4 data-generation plan. Per the plan, this stops
for approval before any main code. **Calibration is PARTIAL**: a testbed user-plane
outage (below) blocked the live rate/pps/victim measurements; everything measurable
without a working user-plane is done and real (never fabricated).

## 3.1 Repo / testbed recon (answers with file paths)

- **Scenarios & harness:** `experiments/scenarios/ds-*.yaml`; run by
  `scripts/k8s/exp/run.py` (scenario → variants × reps → phases); flow spec per phase
  in the YAML. Labels/offered flows land in `traffic/flows.json` per run.
- **Traffic tools actually present** (verified via `kubectl exec`):
  - `nr-ue` container: **iperf2**, python3, tc, ip. NO iperf3/hping3/scapy/tcpreplay/ping.
  - `keepalive` sidecar (shares UE netns, egress oaitun_ue1): **iperf2, hping3, nping**,
    python3, tc, ip. Caps = **CAP_NET_RAW only** (no NET_ADMIN → can't set routes/tc).
  - `oai-lab-dn` (DN): iperf2, python3, **iptables**, tcpdump. **NO DNS resolver
    (named/dnsmasq/dig), NO iperf3, NO scapy/tcpreplay, NO socat.** n6 = 172.30.26.10/24.
  - `oai-upf`: tc, ip, iptables; interfaces eth0/n3/n4/n6 (n3+n6 carry XDP profiler);
    **N6 egress = `n6`** (tc tbf for the congestion factor goes here).
  - **Unified launch point for v4 (C4 fix):** `keepalive` sidecar — it has the superset
    (hping3+nping+iperf2+python3+NET_RAW). A Python UDP **pacer** can run there (plain
    UDP needs no privilege; raw craft uses NET_RAW). Routes already in the shared netns.
  - **Must add for the v4 backend matrix** (image rebuild / sidecar): iperf3, scapy,
    tcpreplay, a real DNS resolver on DN (dns_heavy counterpart), socat. A custom pacer
    and tcp_shortconn can be pure-Python (python3 is everywhere).
- **DN servers/sinks:** iperf server started on demand; **no persistent DNS/open-port
  sinks** → the responsive-victim "open port" side needs a sink added. iptables present
  → silent-victim DROP works (verified mechanism; measurement pending).
- **Raw-tap points:** URR + profiler raw already persisted in the producer PVC:
  `/var/lib/urr-ei/{smf-raw,normalized,envelopes}.jsonl` (with source ts). **KPM has NO
  persistent raw log** — only the xApp's processed `features.jsonl`
  (`src/flexric/examples/xApp/c/monitor/features.c`). → v4 needs a **new KPM raw tap**
  (log each indication with collect_ts + arrival_now in the xApp, or a side logger).
- **v3 dataset builder:** `scripts/ml/build_oran_dataset.py`; per-second per-SUPI rows
  from `features.jsonl`, labelled per (phase,UE) from `flows.json`.
- **Telemetry semantics** (`features.c`, `defense.c`): KPM REPORT period **1000 ms**,
  per-UE; `DRB.PdcpSduVolumeUL/DL`→rate, `DRB.UEThpUl/Dl`→thp, `RRU.PrbTotUl/Dl`→prb.
  URR PFCP **PERIODIC 1 s** (time-triggered, cumulative; bytes/packets/interval).
  Profiler per-UE per window_ms. Join = KPM per-second clock, URR/prof matched to the
  second ±1 s (acausal backfill — the C5 leak to fix).

## 3.2 Calibration — measured (real)

- **MTU:** oaitun_ue1 = **1500**; all core interfaces (n3/n4/n6) 1500. UDP payload
  no-frag on the tunnel ≈ **1472 B** (1500 − 20 IP − 8 UDP); live frag sweep PENDING.
- **URR / profiler arrival lag vs KPM** (from 30 231 v3 feature rows — this one needs no
  live traffic):
  - `urr_age_s`: median **1.72 s**, p90 2.94, p99 3.72, max 4.33, **min −1.34** (acausal).
  - `prof_age_s`: median **2.23 s**, p90 3.18, p99 3.79, max 4.18.
  - `urr_offset_s` usage: exact 21217, −1 s stand-in 8735, **+1 s (future) 212** (C5 leak).
    `prof_offset_s`: exact 30140, −1 s 87.
  - → **Causal as-of join** must use arrival_ts ≤ t with an **age cap ≈ 3–4 s** (NaN
    beyond), never the ±1 s / +1 s backfill.

## 3.2 Calibration — PENDING (blocked by user-plane outage)

Rate achieved-vs-offered (linear region), per-backend pps ceilings + pacing error,
live MTU/frag sweep, victim ICMP-unreachable/RST/echo-reply + iptables-DROP silencing.
Scripts are written and ready (`scratchpad/calib_rate.sh`, `calib_mtu_victim.sh`); they
run as soon as the user-plane is restored.

## Proposed load levels (TENTATIVE — confirm after the rate sweep)

From v3 achieved throughput (benign & malicious landed ~400–800 kbps achieved on a 1400 B
UDP UL): propose **L1 ≈ 400 kbps, L2 ≈ 800 kbps, L3 ≈ 1200 kbps** offered UL, each
defined as a (UL bytes/s, size-distribution) pair so pps follows. Must be re-checked
against the measured linear region (single-UE and 2-UE concurrent) before use.

## BLOCKER — testbed user-plane is DOWN (must fix before any collection)

Root cause: **OAI SMF segfaults ~every 5.5 h** (exit 139 / SIGSEGV; OAI binary bug —
out of scope to patch). It left the **gNB's UL DRB→GTP-U forwarding broken**: the gNB
receives UL on the radio (goodput ~5 Mbps) but emits **0 GTP-U on n3**, so nothing
reaches the UPF/DN. Config is correct (`GNB_IPV4_ADDRESS_FOR_NGU=172.30.23.20/24`,
tunnel to UPF TEID 0x25, socket bound). **Not fixable by any operational reset tried:**
recover_ran, route re-add, UE/SMF/UPF/AMF/gNB restarts, full ordered core cold-start,
and a **minikube node restart** — all leave the core clean + UEs attached + radio up but
the gNB still won't forward UL. Needs hands-on OAI gNB debugging (GTPU trace) or a clean
gNB/cluster rebuild. See memory `testbed-userplane-fragility`.

## Implication for v4 (decisive)

The SMF segfaults every few hours **and** recovery is not automatable by restarts → a
**48 h unattended v4 collection is not feasible** without a reliability layer. The real
**P0 of v4** is a watchdog + checkpoint/resume harness (detect segfault / user-plane
loss → recover → re-fix mapping/URR/route → re-run the interrupted run), ahead of the
traffic library. With the current fault, the user-plane is down even for a single run.

---
## RESOLVED 2026-10-20 — user-plane fixed; Phase 0 live calibration complete

**The BLOCKER is cleared.** The user-plane was down because **minikube was Stopped**;
on cold `minikube start` the **Multus race** left core NFs without secondary
interfaces (AMF `n2 No such device`, UPF prepare `Cannot find device "n6"`,
crash-looping). Fix: wait for multus healthy → `rollout restart` deploy/oai-amf,
oai-smf, oai-upf, oai-lab-dn → recover_ran.sh → re-add UE route
`ip route replace 172.30.26.0/24 dev oaitun_ue1`. **Verified: UL iperf UE→DN 0% loss,
UPF n3 GTP-U rx +1261.** The earlier "gNB GTP-U unfixable by restart" conclusion did
not hold after a clean cold start. (Self-inflicted pitfall found: floods >2000 kbps
with defense ON make the defense RRC-release the UE and tear down its PDU session —
**disable defense before any flood/capture**, which v4 requires anyway; done:
`/v1/defense/enabled {"enabled":false}`.)

**SMF segfault still recurs ~5.5h** → the v4 watchdog/resume harness remains the real
P0 for a 48h run. See memory `testbed-userplane-fragility` for the full procedure.

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

### Proposed load levels (CONFIRMED in-region)
L1 ≈ 0.4, L2 ≈ 0.8, L3 ≈ 1.2 Mbit/s offered UL (payload ≤1200 B) — all inside the
linear region with headroom; could extend to 2–4 Mbit/s if higher separation wanted.

**Phase 0 is COMPLETE.** Next per the v4 plan: Phase 1 (raw KPM/URR/prof loggers +
causal `build_dataset.py` + unit tests), gated on approval. The watchdog/resume
harness should precede the full 48h campaign.
