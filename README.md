# Thesis O-RAN Testbed — two-layer defense against UE flooding

O-RAN + 5G SA testbed on minikube (OAI 5GC with eBPF UPF, OAI gNB/UE RFsim,
FlexRIC + KPM xApp, Non-RT RIC A1-EI). The xApp is the single decision point;
the eBPF UPF acts as sensor, per-SUPI memory and enforcement.

- **Start here: `research/CROSS-DOMAIN-DEFENCE.md`** — the single reference: testbed, threat model, defence
  design, offline (v4) and live (v5) experiments, results, credibility, figures, reproduction
- ML foundations and model / xApp design choices: `research/ML-FOUNDATIONS.md`
- Current state / next steps: `research/datasets/oran_flooding_v5_live/HANDOFF.md`
- Design rationale (history): `docs/TWO-LAYER-DEFENSE-DESIGN.md`; outdated documents: `docs/archive/`,
  `research/archive/`
- Upstream OAI/FlexRIC sources are not committed. After cloning, rebuild them
  byte-exact from pinned upstream commits plus `patches/`:

  ```bash
  scripts/verify-oai-upstream.sh --into src   # writes src/{oai-upf,oai-smf,flexric,oai-ran}
  scripts/verify-oai-upstream.sh              # must print MATCH for every tree
  ```

  See `docs/OAI-UPSTREAM-CHANGES.md` for every local change and its rationale.
