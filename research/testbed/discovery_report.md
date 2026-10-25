# Testbed Discovery Report — O-RAN flooding dataset campaign

Date: 2026-10-19. Phase A (discovery) + Phase B (minimum viable collection) of the
dataset master plan. Everything here is backed by commands run against the live
`oai-lab` cluster; nothing is assumed. Companion to `docs/archive/SESSION-HANDOFF-AI-PHASE.md`.

## TL;DR

- The testbed is **live and healthy** after one recovery step (see Blocker 1).
- The experiment harness (`scripts/k8s/exp/`) and scenario format already produce a
  **three-layer, cross-domain, per-SUPI-per-second labeled dataset** — most of master
  plan Phases B–I already exist. We reuse, not rebuild.
- **Decisive capability finding:** the testbed emits far richer telemetry than NCSRD —
  genuine **per-UE PRB** (E2SM-KPM) *and* **UPF packet-behaviour features** (protocol
  mix, mean packet size, pps, destination fan-out). These are the volume-independent
  signals needed to test "malicious ≠ high-load," which NCSRD lacked.
- **Gate B passed** (verified end-to-end with the `smoke` run, see below).
- **One real gap for the science (Phase E/F):** the traffic generator is iperf2-UDP
  only. The `attacker` role / `attack:true` flag are *labels only* — they do not change
  the packets. So today a benign and a malicious flow at matched rate are
  behaviourally identical. Controlled flooding generators with distinct, profiler-
  observable signatures must be implemented before the load-matched campaign.

## 1. Repository & runtime

Working dir `/home/ducsssanh/6G/O-RAN/DATN/Codebase`, branch `main`. Git: only
untracked `research/`, `scripts/ml/`, `artifacts/ml/` and a modified `.gitignore`
(provisional ML phase; nothing committed, by instruction). No commits made.

Cluster: single-node minikube, context **`oai-lab`** (always pass `--context oai-lab`).
All pods on node `oai-lab`.

### Deployed components (verified running)

| Layer | Pods | Image |
|---|---|---|
| Core (OAI 5GC) | amf, ausf, nrf, udm, udr, smf, upf, db, dn | OAI `v2.2.0`; SMF `oai-lab-smf:v2.2.0-lab-e2aa7c54`; **UPF `oai-lab-upf:reflex-...` (eBPF "reflex")** |
| RAN | gnb, nr-ue, nr-ue2 (RFsim) | `oai-lab-radio:...` |
| Near-RT RIC | flexric, **xapp** (KPM + defense), a1-ei-adapter | `oai-lab-xapp:...`, `oai-lab-radio:...` (flexric) |
| Non-RT RIC | informationservice, urr-ei-producer | O-RAN SC ICS; `oai-lab-urr-ei-producer:...` |

- Up to **4 UEs** are wired in the harness (`exp/lab.py:UES`, ue1–ue4); **ue1, ue2
  deployed today** (ue3/ue4 are scale-up headroom, not running).
- DN endpoint `172.30.26.10` is an **isolated in-cluster lab DN** (N6). All traffic in
  the harness targets it — no public egress path.
- UPF has a **Security API** at `oai-upf-security.oai-core.svc:8095` (`/v1/sessions`,
  policies, stats) — the mitigation/enforcement surface and a UPF telemetry source.
- xApp exposes a **defense API** on pod loopback `127.0.0.1:8090` (`/v1/defense/state`,
  mode/core/timing/classifier/policy/reset/enabled). Reached by exec-ing into the xApp
  pod (see `exp/lab.py:http_many`); there is no host port-forward.

## 2. Existing data pipeline (reused, not rebuilt)

`scripts/k8s/exp/run.py` is a complete scenario orchestrator. A *campaign* = one
scenario × variants × reps; each run writes a self-describing directory
(`artifacts/experiments/<ts>_<scenario>[_tag]/runs/<variant>/rep-NN/`) with:

- **raw** — `ran/kpm.csv`, `ran/kpm_cells.csv`, `core/urr_received.jsonl`,
  `core/pfcp_usage_reports.csv` + `pfcp.pcap`, `traffic/flows.json` (offered **and**
  achieved per flow), `dataplane/dn_per_second.csv` (ground-truth bytes/pkts at N6),
  compressed `logs/*`.
- **synchronized** — `defense/features.jsonl`: **one row per SUPI per second** joining
  RAN (KPM) + Core (URR) + UPF-profiler, with timestamps and ages.
- **ground truth** — `run.json` (per-UE role, SUPI, IP history, PDU session),
  `phases.csv` (`attack`/`baseline`/`reconnect` flags, start/stop epochs).

This matches the master plan's raw/synchronized/model-ready layering and its
identity/timestamp/offered-vs-achieved requirements. `collect.py`, `metrics.py`,
`report.py`, `ingest_check.py` support it.

### Feature schema (`defense/features.jsonl`) — measured, under load

Verified non-null and mutually consistent in the `smoke` run (ue1, UL ≈ 1.1 Mbit/s):

- **RAN / E2SM-KPM:** `rate_ul/dl_kbps`, `thp_ul/dl_kbps`, **`prb_ul_pct`=34,
  `prb_dl_pct`** (per-UE PRB), **`cell_prb_ul_pct`=71, `cell_prb_dl_pct`** (cell PRB),
  `e2_node`, `amf_ue_ngap_id`.
- **Core / URR (eBPF UPF via PFCP→SMF→producer→A1-EI→adapter):** `urr_ul/dl_kbps`=1083,
  `urr_ul/dl_pps`=109, `urr_age_s`, `urr_offset_s`, `seid`, `session_epoch`.
- **UPF profiler (behaviour):** `prof_ul/dl_kbps`=1142, `prof_ul/dl_pps`=111,
  `prof_ul/dl_mean_bytes`=1286, protocol counts `prof_{ul,dl}_{tcp,tcp_syn,udp,icmp,
  frag,dns,gtp_in_gtp}`, and **`prof_ul_dst_estimate`≈1.0** (destination fan-out).
- **Online decision outputs (NOT features — label-leakage risk, exclude from X):**
  `class`, `limit_ul/dl_kbps`, `level`, `limited`, `core_action`, `urr_at_decision`.

Three independent UL-rate measurements agreed within ~5 % (KPM 1111 / URR 1083 /
profiler 1142 kbit/s) → cross-domain time alignment and per-SUPI binding are real.

## 3. Component verification

- **Core / PFCP / PDU:** both UEs hold PDU sessions at the UPF (`/v1/sessions` →
  seid 7, 8). SMF↔UPF PFCP is operational; usage reports (msg type 56) captured in
  `pfcp_usage_reports.csv`. The historical IE-43 UP-Function-Features / PFCP length
  issue is **not reproduced** — associations and sessions establish and report.
- **Data plane:** iperf2 UDP UE→DN and DN→UE both deliver; offered = delivered = N6
  (1.05/1.05/1.03 Mbit/s UL, 2.10/2.10/2.04 DL). NAT/route to the DN works.
- **RAN / E2 / KPM:** gNB E2 agent associates with FlexRIC; xApp receives KPM
  indications every second (`KPM ind_msg latency ≈ 0–3 ms`); per-UE PRB + throughput
  populate under load.
- **Idle caveat:** at zero traffic the per-UE KPM/URR fields read null until the first
  report arrives after activity — expected, not a fault.

## 4. Gate B — PASSED (evidence)

`python3 scripts/k8s/exp/run.py run smoke --tag gateB` →
`artifacts/experiments/20261019-102934_smoke_gateB/`. One benign campaign, 2 UEs,
both defense layers on. Result: all record types exported (see the run-dir tree),
metrics computed, `benign_max_level=0`, `delivered_ratio=1.0`, 194 feature rows over
2 SUPIs. Per the master plan Gate B: working UE/PDU session ✓, benign scenario ✓, UPF
telemetry ✓, RAN telemetry ✓, synchronized timestamps ✓, correct identity binding ✓,
ground-truth metadata ✓.

## 5. PRB policy (master plan Phase C) — resolved favourably

Genuine resource context is **already available** via E2SM-KPM, so Phase C is not a
blocker and needs no MAC/E2 surgery:

- `cell_prb_ul_pct` / `cell_prb_dl_pct` — cell PRB utilisation (present).
- `prb_ul_pct` / `prb_dl_pct` — **per-UE PRB** (present; 34 % at 1.1 Mbit/s UL).

Keep the distinct concepts separate downstream: `ue_ul_throughput` (KPM/URR kbps) vs
`ue_ul_prb_allocation` (`prb_ul_pct`) vs `cell_ul_prb_utilization`
(`cell_prb_ul_pct`). TODO: confirm in the gNB/KPM source that `prb_ul_pct` is a true
scheduler PRB measure and not throughput-derived, before relying on it in ablations.

## 6. Blockers & recoveries

**Blocker 1 (resolved) — dead E2/SCTP after idle.** On entry the xApp was crash-looping
on `E2AP Resending Setup Request`, FlexRIC logged `SCTP_SEND_FAILED` / `xApp
disconnected`, and the defense API was down (HTTP conn-refused). This is the known
FlexRIC/E2 stale-association race. Fixed with the project's own
`scripts/k8s/phase0/recover_ran.sh` (ordered restart FlexRIC→gNB→UEs→xApp; ~2.5 min;
non-destructive `rollout restart`). After it: `[xApp] RAN control on 127.0.0.1:8090`,
KPM flowing, Gate B green. **Rollback:** none needed; routine recovery, no config
changed. Expect to re-run after any long idle, minikube restart, or UPF rollout.

**Blocker 2 (resolved) — stale KPM/SUPI mapping, NOT fixed by recover_ran.** During
the dataset campaign, preflight failed with "ueX is not known to the xApp (KPM/SUPI
mapping)" and `defense_state` listed zero UEs, even though both UEs were AMF-registered
and KPM was flowing (ngap 28/29). Root cause: the xApp learns `amf_ue_ngap_id -> SUPI`
only from the `urr-ei-producer`, which parses the OAI AMF's periodic "UEs' Information"
table from AMF logs and attaches it to URR. recover_ran restarts FlexRIC/gNB/UEs/xApp
but NOT the producer/adapter, so after repeated UE restarts bumped the AMF UE NGAP ID,
the producer's watcher stayed on a stale table and the join produced nothing. **Fix:**
`kubectl -n non-rt-ric rollout restart deploy/urr-ei-producer` (+ `a1-ei-adapter`) —
mapping repopulated in seconds. The campaign driver now guards each scenario by waiting
for both SUPIs to map and restarting the producer if not, instead of recover_ran.

## 7. Gaps before the science

1. **Flooding generators (Phase E/F) — the critical gap.** `exp/traffic.py:Flow` is
   iperf2-UDP only (rate, packet length, duration, single DN). The `attacker` role and
   `attack:true` flag change *labels only*, not packets. Matched-rate benign vs
   malicious would be byte-identical → a detector could only learn volume (the NCSRD
   trap). Must add controlled flooding workloads whose signatures land in the
   already-measured profiler features: small-packet/high-pps UDP (`prof_*_mean_bytes`↓,
   `prof_*_pps`↑), SYN flood (`prof_ul_tcp_syn`), ICMP flood (`prof_ul_icmp`),
   fragmented (`prof_ul_frag`), multi-destination fan-out (`prof_ul_dst_estimate`↑).
2. **Load-matched scenario set (Phase F).** New scenario YAMLs pairing legitimate
   heavy upload (P2) against each flooding style (P4) at matched offered load (P5),
   plus mixed benign+malicious UEs (P6), many independent reps.
3. **Dataset assembler (Phases I–K).** Aggregate many campaigns' `features.jsonl` +
   ground truth into `research/datasets/oran_flooding_v1/` with leakage-free,
   capture-group splits and quality/overlap reports. (Keep NCSRD separate.)
4. **Scale-up (optional).** ue3/ue4 for multi-UE scenarios; verify RFsim/CPU headroom.

## 7b. Phase E progress (2026-10-19) — flooding toolchain deployed

Done, verified:
- `deploy/k8s/images/Dockerfile.tools` now installs `hping3` + `nmap` (nping).
- Built **`oai-lab-tools:flood-4c47c320`** (host docker), loaded into the `oai-lab`
  node (containerd), and set it as the `keepalive` sidecar image on `oai-nr-ue` and
  `oai-nr-ue2`. The sidecar shares the UE pod netns, so it originates from
  `oaitun_ue1` (the UE IP). hping3 3.0.0 + nping 0.7.94 confirmed present in-netns; a
  bounded UDP probe to the DN returned ICMP port-unreachable → packets traverse
  RAN→UPF→DN. Pipeline re-verified green by a second `smoke` run after the change
  (`20261019-104758_smoke_postflood`).
- **Rollback:** `kubectl --context oai-lab -n oai-ran set image deploy/oai-nr-ue
  keepalive=oai-lab-tools:r1-1a8c19404f3d` (and `oai-nr-ue2`). The `kubectl set image`
  patch is overwritten by the next `helm upgrade`; a clean `lab.py build` will also
  re-tag all images once because the tools Dockerfile hash feeds the shared fingerprint
  — expected and desired (records the tools change), not a failure.

Gotchas for integrating flooding into the harness (Phase E next step):
- Flood must run **inside** `run.py` so routes/binding/timing match iperf. Standalone
  floods read null in `features.jsonl` because the per-UE KPM↔SUPI binding needs the
  harness preflight/drain sequence and sustained traffic.
- The DN route (`ip route replace 172.30.26.0/24 dev oaitun_ue1`) must be set from the
  **nr-ue** container (has NET_ADMIN); `keepalive` cannot set routes. `lab.ue_ip()`
  already does this during preflight.
- hping/nping run in the `keepalive` container (`kubectl exec ... -c keepalive`).

## 8. Next action

Implement Phase E flooding generators + Phase F load-matched scenarios, run a small
pilot (≥3 independent reps/scenario, ~2–3 min active each), then build dataset v1 and
run the volume-only / RAN-only / UPF-only / behaviour-only ablations. The science
question is now *reachable*: the profiler already exposes behaviour orthogonal to
volume — the pilot must show whether it separates matched-load benign from malicious.
