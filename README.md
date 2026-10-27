# Thesis O-RAN Testbed — two-layer defense against UE flooding

O-RAN + 5G SA testbed on minikube (OAI 5GC with eBPF UPF, OAI gNB/UE RFsim,
FlexRIC + KPM xApp, Non-RT RIC A1-EI). The xApp is the single decision point;
the eBPF UPF acts as sensor, per-SUPI memory and enforcement.

- **Start here: `research/CROSS-DOMAIN-DEFENCE.md`** — testbed, telemetry, KPM/URR join, threat model, actuation
  infrastructure, data generation (the earlier ML defence was removed on 2026-10-27)
- Next direction (study notes): `research/DRL-DIRECTION.md`
- Datasets: `research/datasets/oran_flooding_v4/`, `research/datasets/oran_flooding_v5_live/`
- Upstream OAI/FlexRIC sources are not committed. After cloning, rebuild them
  byte-exact from pinned upstream commits plus `patches/`:

  ```bash
  scripts/verify-oai-upstream.sh --into src   # writes src/{oai-upf,oai-smf,flexric,oai-ran}
  scripts/verify-oai-upstream.sh              # must print MATCH for every tree
  ```

  See `docs/OAI-UPSTREAM-CHANGES.md` for every local change and its rationale.
