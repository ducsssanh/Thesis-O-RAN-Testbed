# PFCP IE 43 compatibility experiment (2026-09-27)

## Baseline and patch boundaries

The workspace is a source snapshot without component Git metadata. UPF provenance is recorded in `manifests/oai-upf.commit`: fork commit `00b7485329b2c07d6cf74bbfae53b7f7acf5de4e`, with upstream parent `9e93b6383803fd0eea2d18d9953670af17c0de64` (2026-08-26). Upstream UPF v2.2.0 is `e025cdfb3a9c18a228f2efe36bd06b9de998554c` (2025-12-12). This is not a same-release baseline with SMF v2.2.0.

- `patches/oai-upf-00b7485-pfcp-urr-reporting.patch`: 13 files, includes ring-buffer/PFCP report integration and kernel/userspace URR map/trigger corrections. These are one combined research patch, not independent eBPF and reporting layers.
- `patches/oai-upf-xdp-mode.patch`: explicit XDP mode/attachment handling, separate from URR.
- eBPF/XDP datapath already exists upstream; it is not all locally implemented research code.
- Backporting onto UPF v2.2.0 has NOT been performed or validated. It needs a separate compatibility audit; do not describe the current tree as that architecture.

## Decoder patch

`patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch` applies with `patch -p1` at the SMF common-source submodule root, pinned to `b5042f5f52cbb0dd61e9a1421b34a9fc030c685f` from SMF v2.2.0. It is an SMF compatibility patch, separate from UPF research patches. The baseline header snapshot is `artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp`.

The decoder requires at least two octets, zeros six known feature octets, reads exactly the declared payload length, retains the first six octets and consumes extensions without interpreting them. A truncated stream throws. FTUP remains set; UPF encoding is unchanged. This patch does not merely raise the upper bound or claim support for unknown feature bits.

Run method-level regression:

```sh
python3 tests/pfcp/check_smf_features.py \
  artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp \
  artifacts/k8s/core/pfcp.pcap
```

The test compiles the exact original and patched method bodies with minimal TLV/exception stubs. It checks the 20 captured IE43 payloads, reproduces the original length=8 rejection, and checks FTUP, lengths 2–9 and 255, nonzero unknown octets, next-IE alignment, and short/truncated payload rejection. It does NOT test the full PFCP message decoder or a deployed SMF.

## Runtime result

The patched image `oai-lab-smf:v2.2.0-ie43-771248b5` (image ID `sha256:f6d5b12cdb52ff6aca5332b88ca88bf7c68452e9a0ca48651b99f4b23ba012a9`) was built and deployed on 2026-09-27. Runtime capture contains an accepted Association Setup Response with IE 43 length 8. SMF recorded the association, continued bidirectional PFCP heartbeat, and emitted no bad-length exception. UPF attached XDP in generic/SKB mode on N3 and N6.

The core integration gate also verifies NRF registration, at least two matched heartbeat request/response sequences, the DN return route, and both XDP attachments. Evidence is in `artifacts/k8s/core/core-gate.json` and `artifacts/k8s/core/runtime-verify-final/`. The official SMF v2.2.0 image remains the values baseline; the generated image overlay and lock select the patched image for this lab.

Sources: [UPF parent](https://github.com/openairinterface/oai-cn5g-upf/commit/9e93b6383803fd0eea2d18d9953670af17c0de64), [UPF release](https://github.com/openairinterface/oai-cn5g-upf/commit/e025cdfb3a9c18a228f2efe36bd06b9de998554c), [SMF submodule pin](https://github.com/openairinterface/oai-cn5g-smf/tree/v2.2.0/src), [ETSI TS 29.244 §8.2.25](https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/17.06.00_60/ts_129244v170600p.pdf).
