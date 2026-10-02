# Thay đổi so với mã nguồn gốc OAI — tổng hợp theo mốc thời gian

**Cập nhật:** 01/10/2026. Tài liệu này là **danh mục đầy đủ** mọi chỗ code trong `src/` và `deploy/k8s/vendor/` khác với mã gốc của OpenAirInterface (OAI) / FlexRIC tại commit đã pin. [LOCAL-PATCHES.md](LOCAL-PATCHES.md) (24/09) là bản kiểm kê cũ theo file patch; khi hai tài liệu khác nhau, **tài liệu này được ưu tiên**.

## 1. Phương pháp và kết quả kiểm chứng

Mã gốc được tải trực tiếp từ GitHub/GitLab của OAI tại đúng commit đã pin (shallow fetch theo SHA), kể cả submodule. Sau đó **dựng lại** từng cây bằng cách áp lần lượt các patch trong `patches/` theo thứ tự thời gian, rồi so sánh từng file với code thật trong repo. Script: [`scripts/verify-oai-upstream.sh`](../scripts/verify-oai-upstream.sh) (~4 phút, cache ở `~/.cache/oai-upstream`).

| Thành phần | Upstream (URL @ commit) | Cây local | Kết quả 01/10/2026 |
|---|---|---|---|
| OAI UPF (eBPF) | `github.com/openairinterface/oai-cn5g-upf` @ `9e93b6383803` + `oai-cn5g-common-src` @ `ef4ddb0ee95a` + `oai-cn5g-common-build` @ `7b20f7ff8a29` | `src/oai-upf` (không có Git) | **MATCH** từng byte, 7 patch |
| OAI SMF v2.2.0 | `github.com/openairinterface/oai-cn5g-smf` @ `d18906656ca8` + `oai-cn5g-common-src` @ `b5042f5f52cb` + `common-build` @ `bd36b5c7ee80` | `src/oai-smf` (Git, HEAD = upstream) | **MATCH** từng byte, 2 patch |
| FlexRIC (nearRT-RIC, xApp) | `gitlab.eurecom.fr/mosaic5g/flexric` @ `ef6d722f2219` | `src/flexric` (không có Git) | **MATCH** (bỏ qua khoảng trắng), 4 patch + 4 file thêm |
| OAI RAN (gNB, nrUE) | `gitlab.eurecom.fr/oai/openairinterface5g` @ `26efcc498931`, submodule FlexRIC @ `ef6d722f2219` | `src/oai-ran` (không có Git) | **MATCH** (bỏ qua khoảng trắng), 1 patch tổng hợp + FlexRIC nhúng |
| OAI Helm charts | `gitlab.eurecom.fr/oai/orchestration/charts` @ `7925f939ea36` | `deploy/k8s/vendor` | **MATCH** từng byte, 1 patch |

Quy ước khi so sánh: bỏ qua `.git`, thư mục build, `ci-scripts/common` (submodule CI của upstream, không sửa), file `*.previous*` (bản sao lưu do helper patch của NIST testbed sinh ra, không được build) và `compile_commands.json`. "Bỏ qua khoảng trắng" chỉ cần cho hai patch cũ được snapshot với dòng trống/thụt lề lệch; nội dung code trùng khớp.

**Phát hiện khi kiểm chứng (đã xử lý 01/10):** hai thay đổi đang chạy nhưng **chưa có file patch** — (1) bước sửa UPF ngày 28/09 (`RemovePipeline` theo session, dọn ánh xạ UE IP), nay xuất thành `oai-upf-session-teardown-ue-ip-mapping.patch`; (2) thay đổi xApp ngày 01/10 (epoch + watchdog KPM), nay là `flexric-xapp-epoch-kpm-watchdog.patch`. Patch `oai-upf-teardown-best-effort.patch` được tạo trên nền (1), nên (1) phải áp trước.

**Tổng quy mô** (dòng đếm từ các patch): UPF 7 patch, +730/−225 trên 27 file (3 file mới); SMF 2 patch, +84/−14 trên 5 file; FlexRIC 4 patch, +798/−290 trên 23 file sửa, cộng 6 file mới (`metrics_factory.c/.h`, `xapp_kpm_moni_write_to_csv.c`, `xapp_kpm_moni_write_to_influxdb.c`, `urr_receiver.c/.h`); RAN +40/−18 trên 9 file và con trỏ submodule FlexRIC; chart +120 trên 25 template.

## 2. Dòng thời gian

Mỗi mục: **mã** · thành phần · patch · phạm vi · nội dung · lý do · trạng thái. "NIST" = kế thừa từ bộ patch của NIST O-RAN testbed (không do tác giả viết); còn lại là thay đổi của đề tài.

### 19–22/08/2026 — Nhập bộ patch NIST testbed (RAN 20/08, FlexRIC 22/08)

**C01 · OAI RAN · NIST** — `patches/ran/**` (7 patch nhỏ), gộp trong `oai-ran-working-tree.patch`.
- `CMakeLists.txt`: mặc định `E2AP_V3`, `KPM_V3_00` (thay `E2AP_V2`, `KPM_V2_03`) — khớp FlexRIC dùng E2AP v3/KPM v3.
- `executables/nr-softmodem.c`: đổi chỗ `nb_id` ↔ `cu_du_id` khi tạo E2 node ID — sửa định danh E2 node sai ở gNB monolithic.
- `openair3/NAS/NR_UE/nr_nas_msg.c`: chuỗi phiên bản OpenSSL theo `OPENSSL_VERSION_TEXT` (biên dịch với OpenSSL 3).
- `openair3/UICC/pdu_session.c`: miền kiểm tra PDU session ID `1..4` → `0..255`.
- `radio/zmq/*`: cú pháp khởi tạo `std::atomic`/`unique_ptr` để biên dịch với GCC mới.
- `cmake_targets/tools/build_helper`: nhận diện Linux Mint như Ubuntu tương ứng.
- Trạng thái: đang dùng (image radio).

**C02 · FlexRIC · NIST** — `patches/flexric/correcting_e2_node_id`, `disable_database_option`, `examples/**`, gộp trong `flexric-working-tree.patch` (21 file, +451/−285) + file thêm `metrics_factory.c/.h`, `xapp_kpm_moni_write_to_influxdb.c`, `xapp_kpm_moni_write_to_csv.c`.
- Callback SM của xApp nhận thêm `global_e2_node_id_t` (sửa xác định E2 node trong xApp đa node): `e42_xapp_api.h`, `act_proc.*`, `msg_dispatcher_xapp.*`, `msg_handler_xapp.c` và mọi xApp ví dụ.
- Tùy chọn `XAPP_DB=NONE_XAPP` (tắt SQLite/MySQL của xApp): `db.h`, `db_generic.h`, `db/CMakeLists.txt`, `e42_xapp.c`.
- `metrics_factory` + viết lại `xapp_kpm_moni`, `xapp_kpm_rc`; xApp ghi KPM ra CSV/InfluxDB.
- Trạng thái: đang dùng (xApp `xapp_kpm_moni_write_to_csv` là xApp duy nhất chạy trong lab).
- Không áp dụng: `patches/flexric/fixed_64_bit_collectStartTime.zip` (cho KPM v2.03; build dùng `KPM_V3_00`).

### 23/08/2026 — KPM PDCP volume dạng số thực

**C03 · OAI RAN (E2 agent)** — trong `oai-ran-working-tree.patch`, file `openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_kpm_subs.c` (+8/−6).
- `DRB.PdcpSduVolumeDL/UL` gửi `REAL_MEAS_VALUE` (Mb, số thực) thay vì số nguyên `bytes*8/1e6` — bản gốc làm tròn mọi mẫu < 1 Mb về 0.
- Lý do: cần lưu lượng mỗi giây ở mức kbps để đối chiếu KPM ↔ URR. Trạng thái: đang dùng.

### 03/09/2026 — UPF phát PFCP Usage Report từ sự kiện URR của eBPF

**C04 · OAI UPF** — `oai-upf-00b7485-pfcp-urr-reporting.patch` (commit `00b7485`, 13 file, +404/−127).
- Kernel: sửa `urr_types.h`, `urr_maps.h`, `xdp_urr_apply_kern.c` (đếm volume/packet, xét trigger, đẩy sự kiện vào ring buffer `urr_report_ring`).
- Userspace: `UrrReportConsumer` (mới) đọc ring buffer → PFCP **Session Report Request (Usage Report)** gửi SMF; `urr_apply_user.*`, `BPFMap.cpp`, `UserPlaneComponent.*`, `upf_n4.cpp`.
- Lý do: UPF gốc có datapath eBPF nhưng không nối sự kiện URR thành báo cáo PFCP. Trạng thái: đang dùng (nguồn URR thật tới xApp). Giới hạn: một URR/session.

### 15/09/2026 — Đường dẫn cấu hình FlexRIC dài hơn

**C05 · FlexRIC (cả bản trong `src/flexric` và bản nhúng trong RAN)** — trong `flexric-working-tree.patch`: `src/util/conf_file.h` `FR_CONF_FILE_LEN 128 → 1024`.
- Lý do: đường dẫn file cấu hình/thư mục SM trong container dài hơn 128 ký tự. Cùng ngày tạo snapshot `*-working-tree.patch`.

### 26/09/2026 — Chuyển sang Kubernetes: chế độ XDP và chart

**C06 · OAI UPF** — `oai-upf-xdp-mode.patch` (7 file, +82/−55).
- Khóa cấu hình YAML `xdp_mode` (`auto`/`native`/`skb`) thay cho thử native rồi fallback ngầm; `XdpMode.hpp` (mới), `upf_config*`, `Configuration.cpp`, `upf_network_config.h`, `ProgramLifeCycle.hpp` (gỡ XDP có kiểm tra quyền sở hữu interface).
- Lý do: veth trong pod Kubernetes không có native XDP; cần ép `skb` và không gỡ chương trình XDP của tiến trình khác. Trạng thái: đang dùng (`skb`).

**C07 · OAI charts** — `oai-charts-7925f93-lab.patch` (25 template, +120).
- Mỗi template NF (deployment/configmap/nad) thêm nhánh `if .Values.global.lab` gọi template tích hợp `lab.nf`; nhánh gốc OAI giữ nguyên.
- Lý do: dùng chart OAI làm subchart cho 4 namespace mà không fork nội dung. Trạng thái: đang dùng.

### 27/09/2026 — SMF đọc IE 43 dài 8 byte; xApp chạy trong Kubernetes

**C08 · OAI SMF (common-src)** — `oai-smf-v2.2.0-pfcp-up-features-extension.patch` (`pfcp/3gpp_29.244.hpp`, +15/−12).
- Decoder IE 43 (UP Function Features) đọc 6 octet đã biết và **bỏ qua phần mở rộng** thay vì ném exception khi độ dài > 6.
- Lý do: UPF mới gửi IE 43 dài 8 byte, SMF v2.2.0 từ chối Association Response. Chi tiết: [SMF-PFCP-COMPATIBILITY.md](SMF-PFCP-COMPATIBILITY.md). Trạng thái: đang dùng.

**C09 · FlexRIC** — `flexric-k8s-runtime.patch` (`src/xApp/db/db.c`, +2): bỏ `assert(db_filename)` khi `NONE_XAPP` (xApp không có DB vẫn khởi động).

**C10 · FlexRIC xApp** — bản `xapp_kpm_moni_write_to_csv.c` cập nhật trong `patches/flexric/...` (27/09): đọc danh sách measurement từ biến môi trường `KPM_MEAS_LIST_PATH`; ghi PDCP volume bằng **byte** (đổi từ Mb thực của C03). Bản nhúng trong `src/oai-ran` vẫn là bản NIST 20/08 (không được build).

### 28/09/2026 — PFCP association do SMF khởi tạo; giới hạn build; bước dọn session đầu tiên

**C11 · OAI UPF** — `oai-upf-cp-initiated-association.patch` (`upf_n4.cpp`, +9): khi SMF chủ động gửi Association Setup, UPF đăng ký peer trước `add_association()`; bản gốc chỉ "thăng cấp" peer do UPF tự tạo nên map association rỗng ⇒ mọi Session Establishment bị từ chối.

**C12 · OAI UPF** — `oai-upf-build-jobs.patch` (Dockerfile, +6/−1): `ARG BUILD_CPUSET` → `taskset` cho `build_upf --jobs` (build 18 job từng làm host hết RAM).

**C13 · OAI UPF** — `oai-upf-session-teardown-ue-ip-mapping.patch` (+58/−14; **xuất bổ sung 01/10** từ bản dựng lại, xem mục 1).
- `RemovePipeline`/`RemoveSession` nhận `pfcp_session` thay vì SEID; xóa mọi entry `session_by_ue_ip` trỏ về SEID bị xóa; khi cài session mới, entry UE IP thuộc SEID khác bị **thay** thay vì gộp.
- Lý do: UE IP được cấp lại sau reconnect ⇒ session mới "thừa hưởng" SEID đã xóa. Là bước đầu của A.2; C16 hoàn thiện.

### 29/09/2026 — QFI cho GTP-U downlink

**C14 · OAI UPF** — `oai-upf-00b7485-dl-qfi-from-access-pdr.patch` (`SessionProgramManager.cpp`, +57/−6).
- Khi SMF không đặt QFI/QER trên PDR CORE, UPF lấy QFI duy nhất của PDR ACCESS cùng session để ghi vào PDU Session Container của GTP-U downlink; nhiều QFI khác nhau ⇒ không đoán.
- Lý do: thiếu QFI làm gNB OAI bỏ gói DL. Trạng thái: đang dùng.

### 30/09/2026 — xApp nhận URR qua HTTPS

**C15 · FlexRIC xApp** — `flexric-xapp-urr-receiver.patch` (4 file, +265).
- `urr_receiver.c/.h` (mới): endpoint HTTPS `POST /v1/urr/events` trong tiến trình xApp (libmicrohttpd + TLS), kiểm tra schema, chống trùng theo `event_id`, ghi SQLite (WAL, `synchronous=FULL`) **trước** khi ACK, xuất JSONL theo run; `GET /v1/urr/status`.
- `CMakeLists.txt` link `microhttpd json-c sqlite3 crypto`; `xapp_kpm_moni_write_to_csv.c` khởi động/dừng receiver.
- Lý do: đưa URR từ A1-EI adapter vào xApp (bộ não duy nhất). Trạng thái: đang dùng.

### 01/10/2026 — Nền tảng Phase A: dọn state, session mồ côi, session epoch

**C16 · OAI UPF** — `oai-upf-teardown-best-effort.patch` (5 file, +114/−22) — **A.2, A.5**.
- `BPFMap::RemoveIfPresent()` (ENOENT không phải lỗi) cho mọi bước dọn; `pdr_rule_key` dùng đúng `struct pdrs_per_session` của kernel (layout cũ ngược pdr_id/seid ⇒ xóa nhầm entry); xóa theo `pdrs_uplink`/`pdrs_downlink`; quét bổ sung theo SEID.
- `pfcp_far::update()` chỉ đổi Apply Action khi IE có mặt (Update FAR không có Apply Action trước đây xóa action).
- Bằng chứng: [`teardown-final-20261001`](../artifacts/k8s/diagnostics/teardown-final-20261001/), mục 7 của [plan](TWO-LAYER-DEFENSE-PLAN.md).

**C17 · OAI SMF** — `oai-smf-v2.2.0-stale-session-release.patch` (4 file, +69/−2) — **A.3**.
- `smf_context::release_stale_pdu_session()`: khi Create SM Context va chạm PDU session cũ (cùng SUPI + PDU Session ID, `INITIAL_REQUEST`), gửi **N4 Session Deletion** cho session cũ tới mọi UPF và giải phóng tài nguyên; bản gốc chỉ xóa trong bộ nhớ SMF dù comment ghi phải xóa cả ở UPF. Bỏ qua nếu session đã release (`up_fseid.seid == 0`).
- `docker/Dockerfile.smf.ubuntu`: `ARG BUILD_CPUSET` (giống C12).
- Lý do: gNB chết ⇒ AMF bỏ UE không Release SM Context ⇒ session mồ côi trong mọi BPF map. Bằng chứng: [`orphan-a3-20261001`](../artifacts/k8s/diagnostics/orphan-a3-20261001/README.md) (SMF gốc FAIL `[1 2 3]`, sau sửa PASS). Image `oai-lab-smf:v2.2.0-lab-837721c2`.

**C18 · FlexRIC xApp** — `flexric-xapp-epoch-kpm-watchdog.patch` (3 file, +80/−5) — **A.4** + độ bền KPM.
- `urr_receiver`: trường tùy chọn `session_epoch` (`[0-9TZ]{1,32}`); `event_id` = `job:SEID:epoch:UR-SEQN` khi có epoch.
- Watchdog KPM: không có indication trong `KPM_STALE_S` giây (mặc định 10, chart đặt `max(10, 10×chu kỳ)`) ⇒ thoát để Kubernetes khởi động lại và đăng ký KPM lại (xApp gốc đăng ký một lần, mất KPM im lặng khi gNB khởi động lại). Chờ E2 node thay vì `assert` khi khởi động.
- CSV KPM ghi tiếp (không ghi đè) khi xApp khởi động lại trong cùng run.
- Bằng chứng: [`epoch-a4-20261001`](../artifacts/k8s/diagnostics/epoch-a4-20261001/summary.txt): SEID 1 tái sử dụng sau restart SMF, 26/26 report được nhận (khóa cũ sẽ nuốt cả 26); KPM tự phục hồi sau khi kill gNB.

## 3. Thay đổi ngoài mã OAI (để phân biệt, không tính là sửa OAI)

| Ngày | Thành phần | Nội dung |
|---|---|---|
| 15/09 | `src/5gdeploy` (NIST, không phải OAI) | `5gdeploy-working-tree.patch` — chỉ dùng cho backend Compose cũ |
| 26/09 → | `deploy/k8s/charts/*`, `deploy/k8s/images/*`, `scripts/k8s/*`, `tests/` | Chart 4 namespace, image, harness — mã mới của đề tài |
| 27/09 | Multus CNI v4.2.2 (`deploy/k8s/vendor/multus.yaml`) | `multus-v4.2.2-atomic-install.patch` (cài binary CNI bằng file tạm + `mv`); 01/10 tăng limit bộ nhớ 300Mi |
| 28/09 → | `src/urr-producer`, `src/a1-ei-adapter` | Producer A1-EI và adapter — mã mới; 01/10 thêm `session_epoch` (A.4, schema 1.1.0) |

## 4. Quy tắc cập nhật tài liệu này

1. Mỗi thay đổi code OAI mới ⇒ một file `patches/<thành-phần>-<nội-dung>.patch` sinh bằng `git diff`/`diff -u` so với trạng thái ngay trước nó.
2. Thêm patch vào đúng thứ tự trong `scripts/verify-oai-upstream.sh`, chạy lại script: phải **MATCH** cho mọi thành phần.
3. Thêm một mục `Cxx` vào mục 2 dưới ngày tương ứng (nội dung, lý do, trạng thái, bằng chứng); cập nhật bảng quy mô ở mục 1.
