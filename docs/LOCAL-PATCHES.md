# Danh mục patch local — kiểm tra 2026-09-24

> **Từ 01/10/2026, danh mục đầy đủ và đã kiểm chứng so với upstream OAI theo mốc thời gian là [OAI-UPSTREAM-CHANGES.md](OAI-UPSTREAM-CHANGES.md)** (dựng lại từ GitHub/GitLab + `scripts/verify-oai-upstream.sh`). File này giữ chi tiết từng file patch cũ.

Đối chiếu với baseline trong `manifests/`, patch snapshot và checkout Git cũ trên máy; không phải so với upstream mới nhất. “Local” nghĩa là thay đổi tích hợp ngoài baseline OAI/FlexRIC/5gdeploy. Một số patch được kế thừa từ NIST testbed, không có nghĩa tất cả đều do tác giả workspace tự viết.

## UPF: thay đổi đã commit

`oai-upf-working-tree.patch` là file rỗng. Patch URR nằm trong commit riêng `00b7485329b2c07d6cf74bbfae53b7f7acf5de4e`, parent `9e93b63`. File `oai-upf-00b7485-pfcp-urr-reporting.patch` được xuất thêm ngày 2026-09-24 từ commit đó; không phải sửa implementation mới. Reverse check trên snapshot hiện tại thành công.

Commit sửa 13 file, +404/-126 dòng. Datapath eBPF và logic native → SKB đã có trong baseline; không nên tính chúng là tính năng mới do patch URR tạo ra.

## Bổ sung 01/10/2026

- [`patches/oai-upf-teardown-best-effort.patch`](../patches/oai-upf-teardown-best-effort.patch) — 5 file, +114/−22, áp lên cây UPF đang dùng cho image `qfi-f6d0516adf20`; image kết quả `oai-lab-upf:teardown-5f1ab8b55a95`. Nội dung: `BPFMap::RemoveIfPresent()` cho đường dọn session; `pdr_rule_key` dùng đúng struct kernel `pdrs_per_session` (trước đó layout ngược, mọi lệnh xóa nhắm sai entry); xóa theo `pdrs_uplink`/`pdrs_downlink`; quét theo SEID với đúng kiểu key; `pfcp_far::update()` chỉ set Apply Action khi IE có mặt. Source không có Git: bản gốc để tạo diff được dựng lại bằng cách đảo đúng các chỗ đã sửa; đã kiểm tra `patch -p1` lên bản gốc dựng lại cho ra đúng từng byte source hiện tại. Kiểm chứng runtime: mục 7 của [TWO-LAYER-DEFENSE-PLAN.md](TWO-LAYER-DEFENSE-PLAN.md).
- [`patches/oai-smf-v2.2.0-stale-session-release.patch`](../patches/oai-smf-v2.2.0-stale-session-release.patch) — A.3, 4 file, +69/−2, áp lên `src/oai-smf` (commit `d189066`, cùng patch IE 43 trong `oai-cn5g-common-src`); image `oai-lab-smf:v2.2.0-ie43-stale-2fa8f172`. Khi Create SM Context va chạm session cũ (cùng SUPI + PDU Session ID, INITIAL_REQUEST), SMF gửi N4 Session Deletion cho session cũ thay vì chỉ xóa trong bộ nhớ; thêm `ARG BUILD_CPUSET` vào Dockerfile SMF. `lab.py build` nay gắn tag SMF `v2.2.0-lab-<hash cả hai patch>` và reverse-check từng patch trên đúng cây của nó; image đang chạy được gắn lại tag `oai-lab-smf:v2.2.0-lab-837721c2` (cùng image ID `sha256:d1a14696…`). Chi tiết: [`orphan-a3-20261001/README.md`](../artifacts/k8s/diagnostics/orphan-a3-20261001/README.md).
- [`patches/oai-upf-session-teardown-ue-ip-mapping.patch`](../patches/oai-upf-session-teardown-ue-ip-mapping.patch) — thay đổi UPF ngày 28/09 (dọn ánh xạ UE IP, `RemovePipeline` theo session) **chưa từng được xuất patch**; phát hiện và xuất 01/10 khi dựng lại cây từ upstream. Phải áp trước `oai-upf-teardown-best-effort.patch`.
- [`patches/flexric-xapp-epoch-kpm-watchdog.patch`](../patches/flexric-xapp-epoch-kpm-watchdog.patch) — A.4: `session_epoch` trong receiver URR của xApp; watchdog KPM; CSV ghi tiếp khi restart. Image `oai-lab-xapp:8f07808f149594ee`.
- `deploy/k8s/vendor/multus.yaml` — sửa trực tiếp file vendor: request 100Mi / limit 300Mi bộ nhớ, CPU limit 500m (upstream 50Mi bị OOMKilled khi nhiều pod khởi động cùng lúc).
- `scripts/k8s/coredns-search-guard.sh` — không phải patch source; sửa ConfigMap CoreDNS trong cluster (idempotent), chạy lại sau mỗi `minikube start`.

## Toàn bộ file .patch trong patches/

Các file `*-working-tree.patch` là bản tổng hợp phục vụ đối chiếu. Build script chỉ áp dụng patch nhỏ trong `patches/ran` và `patches/flexric`; không áp lại bản tổng hợp lên cây đã patch. Các patch con trong `correcting_e2_node_id/src` và `examples` trùng nhóm với `correcting_e2_node_id/patch.patch`, và được helper bỏ qua để tránh áp hai lần.

### [patches/5gdeploy-working-tree.patch](../patches/5gdeploy-working-tree.patch)

- Kích thước: 3559 byte.
- File đích:
  - `compose/ipalloc.ts`
  - `netdef/helpers.ts`
  - `oai/download.sh`
  - `scenario/common/phones-vehicles.ts`

### [patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c.patch)

- Kích thước: 1283 byte.
- File đích:
  - `examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c`

### [patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_rc_moni.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_rc_moni.c.patch)

- Kích thước: 526 byte.
- File đích:
  - `examples/xApp/c/monitor/xapp_rc_moni.c`

### [patches/flexric/correcting_e2_node_id/examples/xApp/c/orange/xapp_es_with_cell_util.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/orange/xapp_es_with_cell_util.c.patch)

- Kích thước: 550 byte.
- File đích:
  - `examples/xApp/c/orange/xapp_es_with_cell_util.c`

### [patches/flexric/correcting_e2_node_id/examples/xApp/c/slice/xapp_slice_moni_ctrl.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/slice/xapp_slice_moni_ctrl.c.patch)

- Kích thước: 504 byte.
- File đích:
  - `examples/xApp/c/slice/xapp_slice_moni_ctrl.c`

### [patches/flexric/correcting_e2_node_id/examples/xApp/c/tc/xapp_tc_all.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/tc/xapp_tc_all.c.patch)

- Kích thước: 911 byte.
- File đích:
  - `examples/xApp/c/tc/xapp_tc_all.c`

### [patches/flexric/correcting_e2_node_id/patch.patch](../patches/flexric/correcting_e2_node_id/patch.patch)

- Kích thước: 6924 byte.
- File đích:
  - `examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c`
  - `examples/xApp/c/monitor/xapp_rc_moni.c`
  - `examples/xApp/c/orange/xapp_es_with_cell_util.c`
  - `examples/xApp/c/slice/xapp_slice_moni_ctrl.c`
  - `examples/xApp/c/tc/xapp_tc_all.c`
  - `src/xApp/act_proc.c`
  - `src/xApp/act_proc.h`
  - `src/xApp/e42_xapp_api.h`
  - `src/xApp/msg_dispatcher_xapp.c`
  - `src/xApp/msg_dispatcher_xapp.h`
  - `src/xApp/msg_handler_xapp.c`

### [patches/flexric/correcting_e2_node_id/src/xApp/act_proc.c.patch](../patches/flexric/correcting_e2_node_id/src/xApp/act_proc.c.patch)

- Kích thước: 614 byte.
- File đích:
  - `src/xApp/act_proc.c`

### [patches/flexric/correcting_e2_node_id/src/xApp/act_proc.h.patch](../patches/flexric/correcting_e2_node_id/src/xApp/act_proc.h.patch)

- Kích thước: 630 byte.
- File đích:
  - `src/xApp/act_proc.h`

### [patches/flexric/correcting_e2_node_id/src/xApp/e42_xapp_api.h.patch](../patches/flexric/correcting_e2_node_id/src/xApp/e42_xapp_api.h.patch)

- Kích thước: 407 byte.
- File đích:
  - `src/xApp/e42_xapp_api.h`

### [patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.c.patch](../patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.c.patch)

- Kích thước: 398 byte.
- File đích:
  - `src/xApp/msg_dispatcher_xapp.c`

### [patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.h.patch](../patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.h.patch)

- Kích thước: 637 byte.
- File đích:
  - `src/xApp/msg_dispatcher_xapp.h`

### [patches/flexric/correcting_e2_node_id/src/xApp/msg_handler_xapp.c.patch](../patches/flexric/correcting_e2_node_id/src/xApp/msg_handler_xapp.c.patch)

- Kích thước: 464 byte.
- File đích:
  - `src/xApp/msg_handler_xapp.c`

### [patches/flexric/disable_database_option/patch.patch](../patches/flexric/disable_database_option/patch.patch)

- Kích thước: 3664 byte.
- File đích:
  - `README.md`
  - `src/xApp/db/CMakeLists.txt`
  - `src/xApp/db/db.h`
  - `src/xApp/db/db_generic.h`
  - `src/xApp/e42_xapp.c`

### [patches/flexric/examples/xApp/c/kpm_rc/CMakeLists.txt.patch](../patches/flexric/examples/xApp/c/kpm_rc/CMakeLists.txt.patch)

- Kích thước: 820 byte.
- File đích:
  - `examples/xApp/c/kpm_rc/CMakeLists.txt`

### [patches/flexric/examples/xApp/c/kpm_rc/xapp_kpm_rc.c.patch](../patches/flexric/examples/xApp/c/kpm_rc/xapp_kpm_rc.c.patch)

- Kích thước: 13894 byte.
- File đích:
  - `examples/xApp/c/kpm_rc/xapp_kpm_rc.c`

### [patches/flexric/examples/xApp/c/monitor/CMakeLists.txt.patch](../patches/flexric/examples/xApp/c/monitor/CMakeLists.txt.patch)

- Kích thước: 2807 byte.
- File đích:
  - `examples/xApp/c/monitor/CMakeLists.txt`

### [patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni.c.patch](../patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni.c.patch)

- Kích thước: 27036 byte.
- File đích:
  - `examples/xApp/c/monitor/xapp_kpm_moni.c`

### [patches/flexric-working-tree.patch](../patches/flexric-working-tree.patch)

- Kích thước: 55495 byte.
- File đích:
  - `README.md`
  - `examples/xApp/c/kpm_rc/CMakeLists.txt`
  - `examples/xApp/c/kpm_rc/xapp_kpm_rc.c`
  - `examples/xApp/c/monitor/CMakeLists.txt`
  - `examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c`
  - `examples/xApp/c/monitor/xapp_kpm_moni.c`
  - `examples/xApp/c/monitor/xapp_rc_moni.c`
  - `examples/xApp/c/orange/xapp_es_with_cell_util.c`
  - `examples/xApp/c/slice/xapp_slice_moni_ctrl.c`
  - `examples/xApp/c/tc/xapp_tc_all.c`
  - `src/util/conf_file.h`
  - `src/xApp/act_proc.c`
  - `src/xApp/act_proc.h`
  - `src/xApp/db/CMakeLists.txt`
  - `src/xApp/db/db.h`
  - `src/xApp/db/db_generic.h`
  - `src/xApp/e42_xapp.c`
  - `src/xApp/e42_xapp_api.h`
  - `src/xApp/msg_dispatcher_xapp.c`
  - `src/xApp/msg_dispatcher_xapp.h`
  - `src/xApp/msg_handler_xapp.c`

### [patches/oai-ran-working-tree.patch](../patches/oai-ran-working-tree.patch)

- Kích thước: 8908 byte.
- File đích:
  - `CMakeLists.txt`
  - `cmake_targets/tools/build_helper`
  - `executables/nr-softmodem.c`
  - `openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_kpm_subs.c`
  - `openair2/E2AP/flexric`
  - `openair3/NAS/NR_UE/nr_nas_msg.c`
  - `openair3/UICC/pdu_session.c`
  - `radio/zmq/ring_buffer.cpp`
  - `radio/zmq/zmq_imported.cpp`
  - `radio/zmq/zmq_imported.h`

### [patches/oai-upf-00b7485-pfcp-urr-reporting.patch](../patches/oai-upf-00b7485-pfcp-urr-reporting.patch)

- Kích thước: 34230 byte.
- File đích:
  - `src/upf_app/CMakeLists.txt`
  - `src/upf_app/app/upf_n4.cpp`
  - `src/upf_app/control/UrrReportConsumer.cpp`
  - `src/upf_app/control/UrrReportConsumer.h`
  - `src/upf_app/control/UserPlaneComponent.cpp`
  - `src/upf_app/control/UserPlaneComponent.h`
  - `src/upf_app/kernel/include/urr_maps.h`
  - `src/upf_app/kernel/include/urr_types.h`
  - `src/upf_app/kernel/xdp/xdp_urr_apply_kern.c`
  - `src/upf_app/user/urr_apply_user.cpp`
  - `src/upf_app/user/urr_apply_user.h`
  - `src/upf_app/user/wrappers/BPFMap.cpp`
  - `src/upf_app/user/wrappers/BPFMap.hpp`

### [patches/oai-upf-working-tree.patch](../patches/oai-upf-working-tree.patch)

- Kích thước: 0 byte.
- Rỗng: không chứa working-tree diff.

### [patches/ran/cmake_targets/tools/build_helper.patch](../patches/ran/cmake_targets/tools/build_helper.patch)

- Kích thước: 1659 byte.
- File đích:
  - `cmake_targets/tools/build_helper`

### [patches/ran/executables/nr-softmodem.c.patch](../patches/ran/executables/nr-softmodem.c.patch)

- Kích thước: 798 byte.
- File đích:
  - `executables/nr-softmodem.c`

### [patches/ran/openair3/NAS/NR_UE/nr_nas_msg.c.patch](../patches/ran/openair3/NAS/NR_UE/nr_nas_msg.c.patch)

- Kích thước: 1304 byte.
- File đích:
  - `openair3/NAS/NR_UE/nr_nas_msg.c`

### [patches/ran/openair3/UICC/pdu_session.c.patch](../patches/ran/openair3/UICC/pdu_session.c.patch)

- Kích thước: 588 byte.
- File đích:
  - `openair3/UICC/pdu_session.c`

### [patches/ran/radio/zmq/ring_buffer.cpp.patch](../patches/ran/radio/zmq/ring_buffer.cpp.patch)

- Kích thước: 340 byte.
- Xem header `---`/`+++` trong file để biết file đích.

### [patches/ran/radio/zmq/zmq_imported.cpp.patch](../patches/ran/radio/zmq/zmq_imported.cpp.patch)

- Kích thước: 412 byte.
- Xem header `---`/`+++` trong file để biết file đích.

### [patches/ran/radio/zmq/zmq_imported.h.patch](../patches/ran/radio/zmq/zmq_imported.h.patch)

- Kích thước: 408 byte.
- Xem header `---`/`+++` trong file để biết file đích.

## Các file bổ sung không ở dạng .patch

Các file mới/untracked không nhất thiết được chứa trong working-tree diff. Manifest `.status` là bản ghi lúc tạo snapshot, không phải trạng thái Git sống.

- `patches/flexric/examples/xApp/c/metrics_factory.c` và `.h`.
- `patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c`.
- `patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_influxdb.c`.
- `src/5gdeploy/scenario/orantestbed/`.
- Lớp tích hợp `scripts/`, `configs/`, `tests/` và Compose sinh ra.

## Patch có sẵn trong upstream: không tính là patch local của testbed

Ví dụ trong OAI RAN: `cmake_targets/tools/uhd-4.x-tdd-patch.diff`, `uhd-3.15-tdd-patch.diff`, `install_wls_lib.patch`, `install_libraries_to_system.patch`, `oran_fhi_integration_patches/F/oaioran_F.patch`. Không phân loại chỉ dựa vào phần mở rộng `.patch`; cần đối chiếu baseline.

## Kiểm tra đã thực hiện

- 13/13 patch nhỏ mà helper áp dụng cho RAN/FlexRIC: reverse check thành công.
- 4 file bổ sung FlexRIC ở patches/ khớp bản trong src/flexric.
- `python3 tests/test_ported_scripts.py`: 13 tests PASS.
- `bash tests/test_oai_upf_profile.sh`: PASS.
- `python3 tests/test_background_sudo.py`: 1 test PASS.
- Đây là test script với mock; không chứng minh RF/E2/PFCP/datapath chạy thật.

## Patch phát sinh khi thêm backend Kubernetes

- `patches/oai-upf-xdp-mode.patch`: patch local mới, áp dụng sau URR `00b7485`; thêm YAML XDP mode và teardown có kiểm tra ownership. Không nằm trong source OAI baseline đã pin.
- `patches/oai-charts-7925f93-lab.patch`: patch local mới trên chart OAI commit `7925f939ea36a3c4c1df5525f3718ce8470f6b3f`; thêm nhánh deployment/config/network cho umbrella lab. Các file `deploy/k8s/chart`, `deploy/k8s/images`, `scripts/k8s`, `tests/k8s` là implementation tích hợp mới, không phải file nguyên bản OAI.
- `scripts/legacy/compose/configure-core.sh` truyền cờ BPF cho generator; `scripts/legacy/compose/lib/oai-upf-profile.sh` kiểm tra capability sinh ra. Các thay đổi này thuộc backend Compose để đối chiếu, không được backend Kubernetes gọi.

Xem [K8S-LAB.md](K8S-LAB.md) cho provenance và bằng chứng theo mốc.
