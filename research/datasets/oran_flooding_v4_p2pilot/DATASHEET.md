# Datasheet — ORAN flooding v4 (Phase 2 pilot)

Template datasheet for the v4 dataset, instantiated on the Phase 2 pilot. Follows
"Datasheets for Datasets" (Gebru et al.). The full-campaign dataset
(`research/datasets/oran_flooding_v4/`) will carry this datasheet forward.

## Motivation
Distinguish **malicious user-plane flooding** from **legitimate high load** in a 5G
O-RAN testbed, from cross-domain telemetry (RAN E2SM-KPM, PFCP URR, eBPF UPF
profiler). v3 was confounded (the label was separable from nuisance signals — UE
identity, generator tool, victim response, packet-size grid, phase-boundary time
leak). v4 is built by a controlled experiment that neutralises those confounds.

## Composition
- Unit: one per-second, per-UE row. Columns = features (`rate_*`, `thp_*`, `prb_*`,
  `cell_prb_*`, `urr_*`, `prof_*`) + `label` (BENIGN / MALICIOUS / IDLE) + `meta_*`.
- `meta_*` carries the experimental control and is **never** an input feature:
  `run_id, supi, ue, phase, backend, attack_family, benign_class, victim_mode,
  load_mbps, dl_feedback, native_unit, achieved_ok, t_since_phase_start, guard,
  attack_active, *_age_s, urr_arrival_exact`.
- IDLE (gaps, warm-up, a UE with no flow) is kept separate and never merged into BENIGN.

## Collection process
- Raw telemetry (`raw/kpm.jsonl`, `core/urr_received.jsonl`, `core/core_received.jsonl`)
  is logged with both source and arrival timestamps; the dataset is built **offline**
  by a strictly causal as-of join (a feature at second t uses only records with
  `arrival_ts ≤ t`; `*_age_s` records staleness; values past the age cap are NaN, never
  forward-filled indefinitely; never backfilled from the future). This removes the v3 C5
  time leak.
- Both traffic classes are generated from the **same** UE keepalive sidecar and egress,
  by a library of interchangeable backends (pacer/hping/iperf for both classes;
  tcp_shortconn/dns_client as benign hard-negatives), each following a rate schedule
  (CBR/Poisson/MMPP-2/on-off-Pareto/fGn/Hawkes/pulsing) drawn from a shared packet-size
  prior. Attackers run a load-matched benign background + attack component
  (`x = b + ρ·m·a`, mean = the benign counterpart's load level). Roles are swapped so
  neither UE owns a class. Detection/mitigation is OFF throughout.
- Ground truth = the experiment schedule (not volume/PRB). `meta_achieved_ok` flags that
  the intended load was actually realised (URR ground truth, per native unit).

## Key measurement decisions (and why)
- **`meta_achieved_ok` uses the phase MEAN rate (total volume / duration) vs the target
  mean, not the per-second median.** The target is a *mean* constraint; for bursty
  schedules (fGn, on-off-Pareto, pulsing, MMPP) the per-second distribution is
  right-skewed, so its median sits well below the mean and would wrongly fail a phase
  that delivered the full intended volume. Mean = total-volume/duration is the faithful
  "did we deliver the intended load" check. This deviates from the original plan's literal
  "median per phase"; it is a correctness fix (it does not loosen the ±10% tolerance).
  The ±90% `achieved_ok` acceptance bar is evaluated **campaign-wide**, not per phase —
  a single bursty phase can miss by sampling variance alone.
- **Achieved is checked in the backend's native unit:** bytes/s for rate backends
  (pacer/iperf/hping-UDP), packets/s for packet backends (SYN/DNS — URR packet count),
  connection-completion rate for tcp_shortconn (self-reported; URR bytes conflate the
  whole TCP exchange). Comparing a connection/query generator against a nominal byte
  target would bias the ratio.
- **Downlink is designed, not incidental (C2):** benign UDP gets a DN→UE feedback channel
  at 1–10% of UL; attacks' DL depends on `victim_mode` (silent = iptables DROP, no
  ICMP/RST, no DL; responsive = ICMP-unreachable/RST DL). `victim_mode` is a per-phase
  environment property recorded on every flow, so DL presence does not track the label.

## Known limitations (pilot; see research/testbed/phase2_v4.md)
- RFsim/GTP caps: UL linear region ≈ 10 Mbit/s per UE, payload ≤ 1200 B (no real
  fragmentation); TCP ≈ 330 kbps.
- iperf/hping realise only the per-phase mean rate at 1 s granularity; bursty schedules
  must run through the pacer (iperf + heavy-tailed on-off under-delivers when burst peaks
  exceed the linear-region ceiling).
- Pilot scale (1 run, 1 phase per cell): packet-size overlap and per-pair balance are
  noisy; the full campaign (many phases, shared size prior) must drive them, verified by
  adversarial validation + the nuisance-only baseline.

## Testbed configuration & recovery (affects every run)
- **SMF↔UPF association (FAILURE MODE 2).** The 5GC exhibited a startup race where the
  SMF's one-shot NRF-based UPF discovery (`discover_upf: yes`) ran before the UPF
  registered, and a stale-subscription-starved NRF timed the SMF out, so the PFCP N4
  association never formed → no PDU session → no GTP tunnel (memory
  `testbed-userplane-fragility` FAILURE MODE 2). **Mitigation applied:** the ordered
  recovery `recover_core_ordered.sh` (NRF→UPF/AMF→SMF→verify association→UEs) and the
  watchdog now calls only it (never a simultaneous rollout-restart) — this reliably
  prevents recurrence (proven: `Added PFCP association with UPF 172.30.24.20`).
  **Hardening evaluated but deferred — static UPF:** setting `discover_upf: no` would drop
  the NRF-discovery dependency entirely, but the existing `smf.upfs[0].host: oai-upf` entry
  is only for usage-reporting config (resolves to the UPF cluster/SBI IP, **not** the N4
  IP), so a naive flip would send PFCP to the wrong address; the correct minimal change is
  `discover_upf: no` **and** `host: 172.30.24.20` (N4), plus a configmap re-render + SMF
  redeploy + association re-proof. Deferred to a separate maintenance step because the
  ordered recovery already prevents recurrence and a redeploy mid-prep is riskier.
- **Ordered core recovery.** Any core/SMF fault is recovered with
  `scripts/k8s/phase0/recover_core_ordered.sh` (NRF → UPF/AMF → wait REGISTERED → SMF →
  verify PFCP association → UEs → routes → defense off → verify 2 SUPIs), never a
  simultaneous rollout-restart (which re-races). The watchdog calls only this script.
- **Per-run preflight (campaign.py).** Each run asserts, before generating traffic: PFCP
  association present, both UE tunnels up, the xApp knows both SUPIs, and fresh URR
  (age < 3 s) for both SUPIs; any failure sets `meta_run_ok=0` and stops the batch.
- **Power-cycle.** A host power-off leaves minikube Stopped; bring-up must be
  `minikube start` → fix the Multus interface race (rollout-restart core) →
  `recover_core_ordered.sh` → `recover_ran.sh` → re-add UE routes → defense off → relaunch
  the host-side watchdog. A bare `minikube start` is not sufficient. PVC data (URR raw)
  persists on the minikube hostpath.

## Distribution / maintenance
Internal research dataset; not for external release. Regenerable from `manifest/` + seed.
`rows.parquet`/`rows.csv` are build outputs (not committed); the datasheet and
`qa_report.md` are kept under version control.
