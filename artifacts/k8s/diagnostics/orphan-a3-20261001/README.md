# A.3 — session mồ côi trong UPF (01/10/2026)

## Nguyên nhân gốc

Session mồ côi chỉ xuất hiện khi **gNB chết** (SCTP shutdown), không phải khi chỉ UE chết:

1. AMF nhận SCTP Shutdown → `Trigger PDU Session UP Deactivation` (Update SM Context, đúng chuẩn) → rồi đặt UE `5GMM-DEREGISTERED` và xóa UE context **mà không gọi Release SM Context** (`before-amf.log`). SMF vẫn giữ session; UPF vẫn giữ N4 session.
2. UE đăng ký lại (initial registration) với cùng PDU Session ID 1 → AMF không còn PDU session context → `Create SM Context` mới.
3. SMF `smf_app.cpp` bước 5 phát hiện va chạm (`PDU Session already existed`) — comment ghi "Delete the local context (including any associated resources in the UPF and PCF)" nhưng code chỉ gọi `remove_pdu_session()` (xóa trong bộ nhớ SMF). **Không có N4 Session Deletion** → session cũ ở lại trong mọi BPF map của UPF, FAR vẫn FORW với TEID DL cũ.

Khi chỉ UE chết (gNB sống): gNB báo AMF → AMF gửi `Release SM Context` → N4 Deletion bình thường (~9 s sau khi kill). Đường này không lỗi.

## Sửa (SMF, đúng chuẩn — không thêm logic quyết định)

`patches/oai-smf-v2.2.0-stale-session-release.patch` (4 file, +69/−2):
- `smf_context::release_stale_pdu_session()`: nếu session cũ còn N4 session (`up_fseid.seid != 0`), duyệt UPF graph như `session_release_sm_context_procedure`, gửi N4 Session Deletion tới từng UPF (fire-and-forget; response không khớp procedure nên bị bỏ qua có log debug), `deallocate_ressources()`, rồi xóa khỏi danh sách. Nếu `seid == 0` (đã Release SM Context trước đó, session chỉ còn vỏ đã `clear()`) thì chỉ xóa cục bộ.
- `smf_app.cpp` bước 5 gọi hàm trên thay cho `remove_pdu_session()`.
- `docker/Dockerfile.smf.ubuntu`: thêm `ARG BUILD_CPUSET` (taskset cho `build_smf --jobs`), giống UPF.
- Thứ tự: Deletion được đẩy vào hàng ITTI N4 trước Establishment của session mới → UPF nhận Deletion trước (cách 1 ms), nên xóa `session_by_ue_ip` của session cũ không đè session mới.

Image: `oai-lab-smf:v2.2.0-ie43-stale-2fa8f172` (`sha256:d1a14696dd05…`). Hậu tố tag được tính trên diff có lẫn dòng submodule; patch sạch có sha256 bắt đầu `1dcf66c7`. Bản trung gian `stale-a24b4de3` (chưa có guard seid 0) gửi Deletion SEID 0x0 vô hại trong kịch bản UE-only — đã thay.

## Bằng chứng (`scripts/k8s/phase0/orphan_cycle.sh <out> <N> ue|gnb`)

| Thư mục | SMF | Kịch bản | Kết quả |
|---|---|---|---|
| `before-*` | cũ `ie43-771248b5` | sự cố gNB/FlexRIC crash tự nhiên 13:32 | 6 lần `already existed`, chỉ SEID 3 có Deletion; map còn SEID 4,5,6 mồ côi + 7 sống |
| `baseline-gnb/` | cũ | kill gNB+UE ×2 | **FAIL**: map `[1 2 3]` — mỗi lần thêm 1 session mồ côi |
| `fixed-gnb/` | mới | kill gNB+UE ×3 | **PASS**: map `[4]`; 3 `Release stale PDU Session`, Deletion 0x1/0x2/0x3 |
| `fixed-ue/` | mới | kill UE ×3 | **PASS**: map `[7]`; Deletion qua Release SM Context, 0 Deletion SEID 0 |
| `fixed-all-maps.txt` | mới | sau 6 chu kỳ | `rules_match_pdr` 2 (UL+DL), `session_rules_enabled`/`session_by_ue_ip`/`pdrs_per_session`/`urr_volume_count`/`urr_config_map` 1 entry |

Hồi quy: run `20261001T123315Z-m35` — RAN/E2/KPM, A1-EI (real), xApp URR (real), traffic **PASS**. (Một lần `experiment` ngay sau `fixed-gnb` FAIL "No KPM timestamp overlaps" vì kill gNB 3 lần làm mất subscription KPM của xApp; `up --stage ran` restart xApp và hết lỗi — không liên quan bản sửa.)

## Còn lại / ngoài phạm vi

- AMF vẫn đánh dấu UE DEREGISTERED khi mất gNB mà không release SM context (lệch TS 23.502: AN release phải giữ RM-REGISTERED/CM-IDLE). Nếu UE **không bao giờ** đăng ký lại, session vẫn treo đến khi UE quay lại hoặc UPF restart. Không sửa AMF (nguyên tắc: thay đổi core tối thiểu); ghi nhận cho luận văn.
- Một lần gNB crash có thể kéo theo nhiều Create SM Context (12:17 có 3 lần liên tiếp) — mỗi lần đều đi qua đường mới nên vẫn sạch.
