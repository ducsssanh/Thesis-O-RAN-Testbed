# Nội dung trước/sau của từng patch

Đối chiếu với baseline trong manifests; đây là mô tả kỹ thuật, không phải chứng nhận tác giả. Patch gộp và patch con có phần trùng nhau. Đường dẫn tương đối tính từ root Codebase.

## [patches/5gdeploy-working-tree.patch](../patches/5gdeploy-working-tree.patch)

ipalloc.ts: 172.25.192.0/18→172.25.160.0/20; helpers.ts: gNB ID khởi đầu 1→3584; phones-vehicles.ts: TAC 5→7; download.sh: tải file tạm, retry, fallback Git fetch. Không chứa scenario/orantestbed untracked.

## [patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_gtp_mac_rlc_pdcp_moni.c.patch)

Cập nhật callback service model của xApp mẫu để nhận thêm global_e2_node_id_t const* node_id, tương thích API dispatcher mới. Đây là bản con của correcting_e2_node_id/patch.patch.

## [patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_rc_moni.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/monitor/xapp_rc_moni.c.patch)

Cập nhật callback service model của xApp mẫu để nhận thêm global_e2_node_id_t const* node_id, tương thích API dispatcher mới. Đây là bản con của correcting_e2_node_id/patch.patch.

## [patches/flexric/correcting_e2_node_id/examples/xApp/c/orange/xapp_es_with_cell_util.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/orange/xapp_es_with_cell_util.c.patch)

Cập nhật callback service model của xApp mẫu để nhận thêm global_e2_node_id_t const* node_id, tương thích API dispatcher mới. Đây là bản con của correcting_e2_node_id/patch.patch.

## [patches/flexric/correcting_e2_node_id/examples/xApp/c/slice/xapp_slice_moni_ctrl.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/slice/xapp_slice_moni_ctrl.c.patch)

Cập nhật callback service model của xApp mẫu để nhận thêm global_e2_node_id_t const* node_id, tương thích API dispatcher mới. Đây là bản con của correcting_e2_node_id/patch.patch.

## [patches/flexric/correcting_e2_node_id/examples/xApp/c/tc/xapp_tc_all.c.patch](../patches/flexric/correcting_e2_node_id/examples/xApp/c/tc/xapp_tc_all.c.patch)

Cập nhật callback service model của xApp mẫu để nhận thêm global_e2_node_id_t const* node_id, tương thích API dispatcher mới. Đây là bản con của correcting_e2_node_id/patch.patch.

## [patches/flexric/correcting_e2_node_id/patch.patch](../patches/flexric/correcting_e2_node_id/patch.patch)

Patch gộp truyền E2 node ID từ act_proc qua message handler/dispatcher tới callback và sửa chữ ký callback ở xApp mẫu. Không apply thêm các patch con cùng nhóm.

## [patches/flexric/correcting_e2_node_id/src/xApp/act_proc.c.patch](../patches/flexric/correcting_e2_node_id/src/xApp/act_proc.c.patch)

Đổi kiểu callback đăng ký trong add_act_proc để nhận global_e2_node_id_t.

## [patches/flexric/correcting_e2_node_id/src/xApp/act_proc.h.patch](../patches/flexric/correcting_e2_node_id/src/xApp/act_proc.h.patch)

Đổi declaration add_act_proc tương ứng chữ ký callback mới.

## [patches/flexric/correcting_e2_node_id/src/xApp/e42_xapp_api.h.patch](../patches/flexric/correcting_e2_node_id/src/xApp/e42_xapp_api.h.patch)

Đổi typedef sm_cb từ một tham số dữ liệu thành dữ liệu + E2 node ID.

## [patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.c.patch](../patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.c.patch)

Worker gọi callback với cả msg->rd và msg->e2_node.

## [patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.h.patch](../patches/flexric/correcting_e2_node_id/src/xApp/msg_dispatcher_xapp.h.patch)

Thêm field e2_node và cập nhật chữ ký sm_cb trong message queue.

## [patches/flexric/correcting_e2_node_id/src/xApp/msg_handler_xapp.c.patch](../patches/flexric/correcting_e2_node_id/src/xApp/msg_handler_xapp.c.patch)

Chép ans.val.e2_node vào message dispatch trước khi enqueue.

## [patches/flexric/disable_database_option/patch.patch](../patches/flexric/disable_database_option/patch.patch)

Trước: build xApp gắn backend database. Sau: có NONE_XAPP, handler giả và DB operations no-op; guard khởi tạo SQLite, bổ sung hướng dẫn README.

## [patches/flexric/examples/xApp/c/kpm_rc/CMakeLists.txt.patch](../patches/flexric/examples/xApp/c/kpm_rc/CMakeLists.txt.patch)

Thêm metrics_factory.c vào xapp_kpm_rc và link libm.

## [patches/flexric/examples/xApp/c/kpm_rc/xapp_kpm_rc.c.patch](../patches/flexric/examples/xApp/c/kpm_rc/xapp_kpm_rc.c.patch)

Dùng metrics factory cho label/đơn vị, bổ sung lọc SST/SD từ env, cập nhật callback mang node ID và bỏ qua report style không hỗ trợ; điều chỉnh logging KPM.

## [patches/flexric/examples/xApp/c/monitor/CMakeLists.txt.patch](../patches/flexric/examples/xApp/c/monitor/CMakeLists.txt.patch)

Thêm metrics_factory/libm cho monitor, target ghi CSV và InfluxDB cùng dependency liên quan; xem diff để biết cấu hình từng target.

## [patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni.c.patch](../patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni.c.patch)

Tương tự KPM monitor: metrics factory, label, in giá trị/đơn vị, callback node ID, lọc S-NSSAI SST/SD và skip report style chưa hỗ trợ.

## [patches/flexric-working-tree.patch](../patches/flexric-working-tree.patch)

Tổng hợp tracked diff FlexRIC: API node ID, DB optional, KPM và giới hạn đường dẫn FR_CONF_FILE_LEN 128→1024. Không chứa bốn file mới metrics_factory/CSV/InfluxDB.

## [patches/oai-ran-working-tree.patch](../patches/oai-ran-working-tree.patch)

Tổng hợp tracked diff của RAN. Ngoài 7 patch nhỏ còn có default E2AP_V3/KPM_V3_00, PDCP SDU volume real thay integer, và marker FlexRIC dirty. Marker không chứa nội dung submodule.

## [patches/oai-upf-00b7485-pfcp-urr-reporting.patch](../patches/oai-upf-00b7485-pfcp-urr-reporting.patch)

Xuất từ commit riêng 00b7485 ngày 24/09/2026. Thêm consumer URR→PFCP, sửa kernel/userspace map và cơ chế gửi report; chi tiết 13 file bên dưới.

## [patches/oai-upf-working-tree.patch](../patches/oai-upf-working-tree.patch)

File rỗng, không có delta chưa commit ở thời điểm snapshot. Không đại diện cho toàn bộ khác biệt UPF với upstream.

## [patches/ran/cmake_targets/tools/build_helper.patch](../patches/ran/cmake_targets/tools/build_helper.patch)

Trước: distro matcher không nhận Linux Mint theo cách testbed cần. Sau: nhận Linux Mint, ánh xạ phiên bản sang Ubuntu và bổ sung Ubuntu 20.04; thay đổi phục vụ build.

## [patches/ran/executables/nr-softmodem.c.patch](../patches/ran/executables/nr-softmodem.c.patch)

Trước: nhánh DU gán gNB ID và DU ID ngược biến. Sau: nb_id lấy gnb_id, cu_du_id lấy gNB_DU_id.

## [patches/ran/openair3/NAS/NR_UE/nr_nas_msg.c.patch](../patches/ran/openair3/NAS/NR_UE/nr_nas_msg.c.patch)

Sửa điều kiện tiền xử lý OpenSSL, dùng OPENSSL_VERSION_TEXT và guard hàm SUCI dùng OpenSSL 3; phục vụ tương thích build.

## [patches/ran/openair3/UICC/pdu_session.c.patch](../patches/ran/openair3/UICC/pdu_session.c.patch)

Giới hạn SST trong validation từ 1..4 thành 0..255.

## [patches/ran/radio/zmq/ring_buffer.cpp.patch](../patches/ran/radio/zmq/ring_buffer.cpp.patch)

std::make_unique cho mảng đổi thành unique_ptr với new và value initialization; tránh yêu cầu API C++ mới hơn.

## [patches/ran/radio/zmq/zmq_imported.cpp.patch](../patches/ran/radio/zmq/zmq_imported.cpp.patch)

std::scoped_lock đổi thành std::lock_guard<std::mutex>; giữ khóa mutex cho transmit, sửa tương thích chuẩn C++.

## [patches/ran/radio/zmq/zmq_imported.h.patch](../patches/ran/radio/zmq/zmq_imported.h.patch)

Khởi tạo atomic dùng dấu ngoặc nhọn thay phép gán giá trị ban đầu.

## Chi tiết 13 file trong commit UPF 00b7485

| File (dưới src/oai-upf/) | Thay đổi |
|---|---|
| `src/upf_app/CMakeLists.txt` | Đưa control/UrrReportConsumer.cpp vào build. |
| `src/upf_app/app/upf_n4.cpp` | Nhận ITTI N4_SESSION_REPORT_REQUEST, cấp transaction ID ở N4 và enqueue thay gửi trực tiếp từ consumer. |
| `src/upf_app/control/UrrReportConsumer.cpp` | File mới: poll ring buffer, tìm session từ SEID, dựng PFCP Usage Report gồm volume/packet/time/trigger, gửi tới CP F-SEID. |
| `src/upf_app/control/UrrReportConsumer.h` | File mới: khai báo vòng đời consumer, worker, ring buffer và sequence state. |
| `src/upf_app/control/UserPlaneComponent.cpp` | Tạo/start/stop consumer cùng vòng đời user-plane khi URR được bật. |
| `src/upf_app/control/UserPlaneComponent.h` | Thêm forward declaration và member sở hữu UrrReportConsumer. |
| `src/upf_app/kernel/include/urr_maps.h` | Chỉ sửa comment tên consumer sang UrrReportConsumer.cpp; map đã có ở baseline. |
| `src/upf_app/kernel/include/urr_types.h` | Thêm reported_triggers vào urr_config để chống report lặp, sửa comment consumer; event fields urr_id/start_time_ns đã có từ trước. |
| `src/upf_app/kernel/xdp/xdp_urr_apply_kern.c` | Thêm atomic one-shot latch cho volume/time threshold/quota và dropped-DL threshold, tránh mỗi packet sau ngưỡng lại phát report. Periodic không dùng latch. |
| `src/upf_app/user/urr_apply_user.cpp` | Chuyển PFCP URR thành urr_config, trigger bitmask, key SEID, monotonic time, xử lý lỗi map; từ chối nhiều URR/session. |
| `src/upf_app/user/urr_apply_user.h` | Đồng bộ declarations với map key/counter mới; bỏ kiểu trung gian không còn dùng. |
| `src/upf_app/user/wrappers/BPFMap.cpp` | Triển khai truy cập FD của map để tạo ring buffer consumer. |
| `src/upf_app/user/wrappers/BPFMap.hpp` | Khai báo accessor FD tương ứng. |

## File mới ngoài diff tracked

- `metrics_factory.c/.h`: helper tạo label/đơn vị và xử lý metrics cho xApp.
- `xapp_kpm_moni_write_to_csv.c`: xuất CSV, node/UE ID, timestamp và PDCP volume theo byte; bản standalone hiện khác CSV trong FlexRIC nhúng.
- `xapp_kpm_moni_write_to_influxdb.c`: xuất dữ liệu sang InfluxDB; tồn tại source không có nghĩa InfluxDB đang chạy.
- `src/5gdeploy/scenario/orantestbed/*`: scenario local; config generator có thể dựng lại từ scenario 20230817 rồi chỉnh slice/SIM/DNN.
- `scripts/`, `configs/`, `tests/`: lớp tích hợp Codebase; không thể tái dựng chỉ bằng clone OAI và apply UPF patch.

Các file backup `.previous` lưu tham chiếu trước sửa; không coi đó là service hoặc patch bổ sung cần build.
