# Figures plan — conference paper (12 pages) vs thesis

Mermaid for structure (architecture, flows, sequences, state machines); matplotlib (`scripts/ml/figures_v5.py`,
PDF in `../`) for data — Mermaid charts have no error bars or grouped bars, so data plots stay in matplotlib.
Render: `npx @mermaid-js/mermaid-cli -i P1_architecture.mmd -o P1.pdf` or paste into mermaid.live / draw.io
(Arrange → Insert → Mermaid). Not render-tested here (mermaid-cli download blocked); syntax checked by hand.

## Conference paper: 5 figures + 3 tables
| # | content | source |
|---|---|---|
| Fig. 1 | system architecture: two telemetry domains, xApp + sidecar, two actuators | `P1_architecture.mmd` |
| Fig. 2 | per-UE decision step: integrity check → trust → fusion → isolate / block | `P2_decision_pipeline.mmd` |
| Fig. 3 | config comparison, attack blocked + benign wrongly blocked, 6 scenarios, 95 % CI | `../fig_a_live_configs.pdf` |
| Fig. 4 | one live run (KPM hidden ×0.1): KPM vs URR, integrity alarm / trust, action, DN packets | `../fig_c_timeline.pdf` |
| Fig. 5 | tamper-factor sensitivity, replay lines + live points | `../fig_b_tamper_sensitivity.pdf` (drop first if space is short) |
| Table I | scenarios / threat model / configurations | live_results_v5 §1 headers |
| Table II | headline numbers: proposed vs naive vs RAN-only vs core-only (hide, frame, outage isolate/block, honest) | live_results_v5 §1, §B |
| Table III | control-loop latency (E2 indication, sidecar, RC ack, RAN loop, core loop, URR delay) | live_results_v5 §G |
In the text only: icmp control (one sentence + numbers), L3 decided vs enforced, carry-over deviation, failures.

## Thesis: everything above, plus
| content | source |
|---|---|
| testbed deployment (namespaces, Multus interfaces) | `T1_testbed_deployment.mmd` |
| telemetry + actuation timing of one loop iteration | `T2_telemetry_sequence.mmd` |
| escalation state machine per UE | `T3_escalation_state.mmd` |
| KPM trust / core trust state machines | `T4_trust_state.mmd` |
| one run on the time axis (phases, gaps, resets, checks) | `T5_run_timeline.mmd` |
| unattended supervisor + QA | `T6_supervisor_flow.mmd` |
| deviation: L3 carried over across the gap | `T7_carryover_sequence.mmd` |
| core outage: isolate vs block, outage vs core-present phases | table live_results_v5 §B |
| icmp control pair | table §A |
| kpm hide: time to block, DN bytes before / after | table §C |
| L3 decided vs enforced (UPF block-ratio guard) | table §I |
| offline replay vs live | table §J |
| sensitivity (flagged runs), failed attempts per cell, carry-over per cell | tables §D, §F, §E |
