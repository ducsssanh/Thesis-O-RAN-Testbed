# Changes to the upstream sources

`scripts/verify-oai-upstream.sh` fetches each upstream tree at its pinned commit, applies the files of this directory
and the new files kept in `src/`, and compares the result with the trees in `src/` (or writes them with `--into`).

| Upstream tree | Pinned commit | Applied, in order |
|---|---|---|
| OAI UPF (`oai-cn5g-upf`) | `9e93b63` | `oai-upf.patch`, then the new files of `src/upf/` |
| OAI SMF (`oai-cn5g-smf`, v2.2.0) | `d189066`, common-src `b5042f5` | `oai-smf-common-src.patch`, `oai-smf.patch` |
| FlexRIC | `ef6d722` | `base/flexric.patch` and the files of `base/flexric/`, `flexric-epoll-eintr.patch`, `flexric.patch`, then the xApp sources of `src/xapp/` |
| OAI RAN (`openairinterface5g`) | `26efcc4` | `base/oai-ran.patch`, `oai-ran.patch`; its embedded FlexRIC gets `base/` and `flexric-epoll-eintr.patch` |
| OAI Helm charts | `7925f93` | `oai-charts.patch` (the result is committed in `deploy/k8s/vendor/`) |
| Multus v4.2.2 | | `multus-atomic-install.patch` (the result is `deploy/k8s/vendor/multus.yaml`) |

## What each patch holds

- `base/`: the changes of the O-RAN testbed this work started from, the NIST O-RAN-Testbed-Automation project (E2AP v3 and KPM v3 settings, E2 node identity,
  metrics output of the monitoring xApp, build fixes). They are kept unchanged and apart from the thesis's own
  changes. `base/flexric/.../xapp_kpm_moni_write_to_csv.c` is the monitoring xApp the defense xApp grew out of; the
  version that is built is `src/xapp/xapp_kpm_moni_write_to_csv.c`.
- `oai-upf.patch`: PFCP usage reports from the eBPF URR events, explicit XDP mode, CP-initiated association, session
  teardown and UE-IP mapping, PFCP User ID and session TTL, the per-SUPI security policy in the XDP programs, and the
  per-session profiler with its telemetry endpoint. The new files of these features are in `src/upf/`.
- `oai-smf-common-src.patch`, `oai-smf.patch`: tolerant decoding of the UP Function Features IE, release of stale
  sessions, PFCP User ID with configurable URR, re-association, usage report times.
- `oai-ran.patch`: per-UE KPM counters, E2SM-RC control (per-UE PRB quota, slice handover that keeps the PDU session)
  and its enforcement in the MAC scheduler.
- `flexric-epoll-eintr.patch`: the event loops retry `epoll_wait` after `EINTR` (xApp, RIC and agent).
- `flexric.patch`: the defense sources in the build of the xApp, and the xApp database switch.
