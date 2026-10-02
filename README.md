# Thesis O-RAN Testbed — two-layer defense against UE flooding

O-RAN + 5G SA testbed on minikube (OAI 5GC with eBPF UPF, OAI gNB/UE RFsim,
FlexRIC + KPM xApp, Non-RT RIC A1-EI). The xApp is the single decision point;
the eBPF UPF acts as sensor, per-SUPI memory and enforcement.

- Start here: `docs/SESSION-HANDOFF.md`
- Design: `docs/TWO-LAYER-DEFENSE-DESIGN.md`, plan: `docs/TWO-LAYER-DEFENSE-PLAN.md`
- Upstream OAI sources are not committed. They are rebuilt from pinned
  upstream commits plus `patches/` by `scripts/verify-oai-upstream.sh`
  (see `docs/OAI-UPSTREAM-CHANGES.md`).
