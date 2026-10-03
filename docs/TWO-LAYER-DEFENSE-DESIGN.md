# Thiết kế: phòng thủ hai lớp RAN (xApp) + 5G core (eBPF UPF)

**Trạng thái:** thiết kế đã chốt ngày 01/10/2026. File này chỉ chứa lý thuyết và quyết định; tiến độ, kết quả và việc cần làm nằm ở [TWO-LAYER-DEFENSE-PLAN.md](TWO-LAYER-DEFENSE-PLAN.md). Khi thay đổi một quyết định, cập nhật mục 9 (nhật ký quyết định) trước.

## 1. Bài toán

Phát hiện và cô lập UE tấn công **flooding/DDoS** trong testbed O-RAN + 5G SA (OAI RAN/RFsim, FlexRIC, OAI 5GC, eBPF UPF), kể cả khi **kênh E2 bị MITM sửa KPM** để che giấu tấn công.

**Mô hình đe dọa**
- Kẻ tấn công điều khiển một hoặc nhiều UE hợp lệ (có SIM), gửi traffic UL lớn hoặc kéo DL lớn, có thể ngắt rồi kết nối lại để đổi IP/session.
- Kẻ tấn công on-path trên E2 (lab không có IPsec E2) có thể đọc/sửa RIC Indication (KPM) và có thể chặn/sửa E2 control. Hiện tượng sửa KPM đã được nêu trong nhiều nghiên cứu quốc tế.
- Ngoài phạm vi: chiếm quyền 5GC, chiếm N4/SBI, tấn công vật lý vô tuyến (jamming).

**Kịch bản chuẩn**

| ID | Kịch bản | Phát hiện chính | Lớp kia bổ sung |
|---|---|---|---|
| S1 | UE flooding, E2 bình thường | RAN (KPM) | UPF nhớ theo SUPI; reconnect vẫn bị chặn |
| S2 | UE flooding, reconnect/đổi IP để né | RAN + core | UPF áp policy từ gói đầu tiên của session mới |
| S3 | UE flooding, **KPM bị MITM sửa thành bình thường** | **Core** (guard + URR) | xApp phát hiện KPM bị sửa (so với URR), hạ tin cậy KPM của E2 node |
| S4 | UE bị UPF chặn nhưng vẫn gửi UL (chiếm PRB) | RAN (PRB UL) + bộ đếm drop của UPF | RAN leo thang lên RRC Release |

## 2. Vì sao cần hai lớp

| | Lớp 1 — RAN (xApp + E2) | Lớp 2 — Core (eBPF UPF) |
|---|---|---|
| Bảo vệ | Tài nguyên vô tuyến: PRB, scheduler, UE khác trong cell | Mạng lõi, DN, đích tấn công, traffic DL từ DN |
| Tốc độ | Near-RT 10 ms – 1 s | XDP µs–ms |
| Danh tính | RNTI / RAN UE ID, mất khi reconnect hoặc đổi cell | SUPI (qua PFCP User ID IE), bền qua session |
| Nguồn số liệu | KPM do gNB tự báo qua E2 (**có thể bị sửa**) | Đếm byte thật trong datapath, độc lập E2 |
| Điểm mù | Không thấy volume tới DN; không nhớ qua reconnect; phải tin KPM | Chặn ở UPF không giải phóng PRB mà UE dùng để gửi UL |

Hai lớp có điểm mù ngược nhau. Lớp RAN **triển khai trước** (tuyến đầu, mức xử lý thấp, nhanh, dễ gỡ); lớp core là hậu thuẫn bền theo danh tính và là nguồn sự thật khi E2 không đáng tin.

## 3. Nguyên tắc thiết kế

1. **Một bộ não duy nhất: xApp.** Mọi quyết định (phát hiện, fusion, escalation, danh tiếng UE) nằm trong xApp. Không thêm NF/module "tư duy" nào vào 5G core.
2. **eBPF UPF là một lớp UPF triển khai được trong thực tế.** Logic bảo mật thêm vào là mở rộng của chính UPF (XDP kernel + control plane userspace sẵn có), không phải module mới, không phải can thiệp sản phẩm đóng.
3. **UPF là cảm biến + bộ nhớ + cơ chế thực thi**, không ra quyết định — ngoại trừ phản xạ có giới hạn (guard quota) do SMF cấu hình.
4. **Lớp bảo mật tách khỏi rule PFCP.** Policy bảo mật nằm trong map riêng, kiểm tra trước PDR/FAR. Rule do SMF sở hữu không bị sửa ⇒ state SMF–UPF không lệch.
5. **Thay đổi ở SMF chỉ là chuẩn:** gửi IE *User ID* (TS 29.244 §8.2.101) trong Session Establishment và cấu hình URR. Không API riêng, không logic riêng.
6. **UPF tự bảo vệ trước bộ não:** chỉ chấp nhận lệnh trong giới hạn (action cho phép, TTL có trần, rate limit, tỉ lệ UE bị chặn, audit). Guard quota chạy độc lập với xApp.
7. **Hai tầng state:** trí nhớ dài hạn theo danh tính tách khỏi state datapath theo session (mục 4).

## 4. Hai tầng state

| | Tầng 1 — Bộ nhớ UE | Tầng 2 — State datapath theo session |
|---|---|---|
| Nội dung | UE nào từng vi phạm, mức, hạn, score, bằng chứng | Gói của session X xử lý thế nào (PDR/FAR/QER/URR, TEID) |
| Key | **SUPI** (tùy chọn IMEI) | `(SEID, PDR ID)`, UE IP, TEID |
| Nơi lưu | DB SQLite của xApp (nguồn sự thật) + `sec_policy_by_supi` pinned trong UPF (bản chiếu) | `rules_match_pdr_map`, `session_by_ue_ip_map`, `pdrs_per_session_map`, `urr_*`, `sec_policy_by_seid` |
| Vòng đời | Qua nhiều session/restart; chỉ đổi theo policy (escalation, decay, hết hạn) | Sinh khi tạo session, **phải xóa sạch** khi session kết thúc |
| "Mạnh dần" | Có | Không — chỉ là bản chiếu của tầng 1 cho một session |

**Vì sao tầng 2 phải dọn sạch** (không phải để "quên" UE — trí nhớ ở tầng 1):
1. **SEID và UE IP bị cấp lại** (đã quan sát: SEID 2 tái sử dụng ở run `053547Z`; SEID đánh lại từ 1 sau mỗi lần UPF restart; UE đổi 10.1.0.2 → 10.1.0.3). Entry sót lại bị session mới **thừa hưởng**: forward tới TEID cũ hoặc DROP nhầm.
2. **Lớp bảo mật dựa trên các map này:** UE lành tính nhận lại SEID cũ có thể bị chặn nhầm; policy có thể gắn vào entry rác.
3. **Map có kích thước giới hạn** (`rules_match_pdr_map` 800 entry): rò rỉ làm đầy map, session mới không ghi được rule.

**Vì sao tầng 1 không nằm trong map theo SEID/IP:** datapath chỉ thấy TEID/IP; blocklist theo IP chặn nhầm UE vô tội nhận lại IP cũ và để lọt UE malicious đổi IP; map mất khi node reboot. Tầng 1 trong UPF dùng **key SUPI** (cần User ID IE) và là bản chiếu; nguồn sự thật là DB của xApp.

### 4.1. Vòng đời tầng 2: TTL của session (thiết kế 01/10/2026, duyệt 02/10; ✅ triển khai và kiểm chứng 03/10 — 3 kịch bản PASS)

**Vấn đề.** A.3 sửa trường hợp UE *quay lại* (SMF xóa session cũ khi va chạm PDU Session ID). Còn hở: khi gNB chết, AMF OAI đưa UE về DEREGISTERED và xóa UE context **không** gọi Release SM Context (lệch TS 23.502: mất AN chỉ đưa UE về CM-IDLE, giữ RM-REGISTERED). Nếu UE **không bao giờ** đăng ký lại, SMF giữ session ở trạng thái UP DEACTIVATED vô thời hạn và UPF giữ đủ entry tầng 2. Hai biến thể cùng lớp: (a) AMF chết hẳn, SMF tưởng session vẫn ACTIVATED; (b) SMF restart nhanh hơn ngưỡng heartbeat, UPF giữ session của association cũ, SMF mới cấp lại SEID trùng.

**Nguyên tắc.** TTL chỉ áp cho **tầng 2** (state theo session). Trí nhớ theo SUPI (tầng 1) **không** hết hạn theo session; nó có vòng đời riêng do xApp quyết định (mục 5.5). Kẻ tấn công làm rơi/tạo lại session không xóa được lịch sử của mình. Không thêm module ra quyết định vào core: mỗi lớp dưới đây là thủ tục 3GPP có sẵn (chỉ cần hoàn thiện trong OAI), tham số nằm trong cấu hình.

**Ba lớp dọn, độc lập, lớp sau bắt cái lớp trước bỏ sót:**

| Lớp | Ai | Kích hoạt | Hành động | Chuẩn |
|---|---|---|---|---|
| **T1 — TTL session ngủ** | SMF | UP connection của PDU session chuyển DEACTIVATED (AN release, mất gNB) → bắt timer `session_ttl.deactivated_release_s`; hủy khi UP được kích hoạt lại (Service Request → Update SM Context có N2 setup) | Hết hạn ⇒ **network-requested PDU Session Release** (TS 23.502 §4.3.4.2): N4 Session Deletion → `SMContextStatusNotify(RELEASED)` tới `smContextStatusUri` của AMF (AMF không còn UE ⇒ 404, bỏ qua) → giải phóng IP/TEID/ID | SMF được release theo chính sách cục bộ |
| **T2 — Không hoạt động user plane** | UPF đo, SMF quyết | SMF gửi **User Plane Inactivity Timer** (IE 117, TS 29.244 §8.2.83) trong Establishment = `session_ttl.up_inactivity_s`; eBPF UPF ghi thời điểm gói cuối theo session (map tầng 2, chỉ ghi, không quyết định); userspace UPF gửi **Session Report, Report Type UPIR** khi quá ngưỡng | SMF xử lý UPIR (hiện là `// TODO` ở `smf_context.cpp` ~dòng 706): yêu cầu AMF deactivate UP (`N1N2MessageTransfer` + N2 PDU Session Resource Release, TS 23.502 §4.2.6). AMF trả **404 (không có UE context)** ⇒ đây chính là tín hiệu "UE đã mất" ⇒ release ngay như T1. AMF chấp nhận ⇒ session DEACTIVATED ⇒ T1 tiếp quản | IE 117 + UPIR là cơ chế chuẩn cho "UP deactivation do không hoạt động" |
| **T3 — Mất/khởi động lại control plane** | UPF | (i) heartbeat tới SMF hết retry — **đã có** (`timeout_heartbeat_request` → `del_sessions()`); (ii) **Association Setup** từ cùng Node ID với **Recovery Time Stamp khác** (SMF restart nhanh hơn ngưỡng heartbeat) — cần bổ sung | Xóa mọi PFCP session của association cũ qua đúng đường `RemoveSession` (dọn đủ BPF map, xem A.2) trước khi chấp nhận association mới | TS 29.244 §6.2.6 (Association Setup khi CP restart; trừ khi CP yêu cầu giữ session) — đối chiếu lại số mục khi viết luận văn |

**Hiệu chỉnh T2 khi triển khai (02/10/2026).** Đọc mã AMF OAI v2.2.0: `N1N2MessageTransfer` trả **200** khi không có PDU session context (không bao giờ 404), và `supi2ue_ctx` không bao giờ bị xóa — SMF không có cách nào hỏi AMF "UE còn không". Vì vậy T2 chỉ dùng bản tin PFCP chuẩn: UPIR đánh dấu session "UP không hoạt động", Usage Report có volume > 0 xóa dấu, và bộ quét của SMF release session nào đã DEACTIVATED (T1) *hoặc* không hoạt động kể từ UPIR (T2) liên tục ≥ `deactivated_release_s`. Đây là chính sách "release theo không hoạt động" (tương tự PDN connection inactivity timer của EPC), không phải "deactivate UP". Hệ quả: UE còn sống nhưng im lặng > `up_inactivity_s + deactivated_release_s` mất PDU session (OAI SMF không có NAS PDU Session Release Command do mạng khởi tạo nên UE không được báo — giới hạn ghi ở mục 8). Lab chạy keep-alive lành tính 1 gói UDP/20 s trong pod UE (`defense.ueKeepaliveS`), đúng ràng buộc `up_inactivity_s` > chu kỳ keep-alive. Gate (2) đổi thành: tắt keep-alive ⇒ UPIR sau `up_inactivity_s`, release sau thêm `deactivated_release_s`; bật lại traffic trước hạn ⇒ session sống. Khi làm T3 phát hiện đường xóa theo association (heartbeat timeout) của UPF chưa dọn BPF map — đã sửa cùng (C21).

**Tham số** (thêm vào mục 6.1): `session_ttl.deactivated_release_s` = 120 (lab) / chính sách nhà mạng ở production (giờ–ngày, thường gắn với timer reachability của AMF); `session_ttl.up_inactivity_s` = 60 (lab); `0` = tắt. Ràng buộc: `up_inactivity_s` lớn hơn chu kỳ keep-alive của ứng dụng lành tính; T1 phải lớn hơn thời gian Service Request bình thường để không release UE chỉ đang idle ngắn.

**Tương tác với A.3 và A.4.** UE quay lại trước khi TTL hết ⇒ đường A.3 (va chạm PDU Session ID) dọn ngay, timer T1 của session cũ bị hủy theo. Session bị release bởi TTL không phát URR nữa; nếu SEID sau này bị cấp lại, epoch A.4 tách hai session.

**An toàn.** TTL không mở hướng tấn công mới: chỉ release session của chính UE đã mất kết nối/không có traffic; UE thật chỉ cần tạo lại PDU session. Kẻ tấn công treo nhiều session mồ côi (crash gNB giả, đăng ký rồi bỏ) bị chặn trên ở `T1 × tốc độ tạo session` thay vì tích lũy vô hạn (map `rules_match_pdr` 800 entry). Không dùng TTL thuần trong UPF (UPF tự xóa session khi SMF vẫn giữ): lệch state với control plane, đúng loại phương án đã loại ở mục 9.

**Gate (Phase A.8, xem plan):** (1) kill gNB+UE rồi giữ UE ở 0 replica: sau `deactivated_release_s` UPF nhận N4 Deletion, mọi map tầng 2 sạch, SMF log release; (2) UE còn kết nối nhưng ngừng traffic: UPIR sau `up_inactivity_s`, AMF còn UE ⇒ chỉ deactivate (không release), traffic lại ⇒ session sống; (3) restart SMF (không restart UPF): UPF xóa session của association cũ khi association mới tới; không còn va chạm SEID trong UPF.

## 5. Kiến trúc

```
 ┌────────────────────────── xApp (Near-RT RIC) — bộ não duy nhất ─────────────────────────┐
 │ detector KPM · kiểm tra nhất quán KPM↔URR · trust theo E2 node · DB danh tiếng theo SUPI │
 │ escalation/decay · fusion có trọng số · kiểm chứng hành động · đối chiếu policy với UPF   │
 └──────┬──────────────────────────────────────────────┬───────────────────────▲──────────┘
        │ E2SM-RC control                              │ UPF Security API       │ URR + sec stats
        ▼                                              ▼ (mTLS, có giới hạn)    │
 gNB (lớp 1): PRB cap, RRC Release          eBPF UPF (lớp 2)                    │
        ▲                                     userspace: API, dẫn xuất policy   │
        │ E2 KPM (MITM có thể sửa)            theo SEID khi tạo/xóa session     │
        │                                     XDP: entry → session lookup →     │
        │                                          SEC_POLICY (mới) → PDR → FAR/QER/URR(guard)
        │                                     maps: sec_policy_by_supi (pinned),
        │                                           sec_policy_by_seid, sec_stats
        │                                              │ PFCP (User ID IE, URR cfg) ▲
        │                                            SMF ──Event Exposure── urr-producer ── ICS ── adapter
```

### 5.1. Bộ nhớ UE trong UPF
```
sec_policy_by_supi  HASH, pinned   key IMSI → {action, rate_ul, rate_dl, expires_at_ns, epoch, level}   ← chỉ xApp ghi (API)
sec_policy_by_seid  HASH           key SEID → {action, rate_ul, rate_dl, expires_at_ns, epoch}          ← UPF dẫn xuất; xóa khi session kết thúc
seid_supi           userspace/HASH SEID → IMSI (cập nhật session đang sống khi policy SUPI đổi)
sec_stats_by_seid   PERCPU_HASH    key SEID → {drop_ul/dl_pkts, drop_ul/dl_bytes, last_drop_ns}
```
- `expires_at_ns` so với `bpf_ktime_get_ns()` trong XDP; hết hạn thì XDP bỏ qua, userspace dọn sau.
- `epoch` do xApp tăng mỗi lần đổi policy; UPF bỏ qua lệnh có epoch cũ hơn.
- Map pinned sống tới khi node reboot; xApp đối chiếu định kỳ và khi `boot_id` của UPF đổi.
- **Chế độ suy giảm** khi SMF không gửi User ID: áp theo SEID sau khi xApp thấy session mới qua URR (khoảng hở vài giây sau reconnect); guard quota che một phần.

### 5.2. Stage `PROG_SEC_POLICY` trong XDP
- Chèn giữa `PROG_SESSION_LOOKUP_IP` và `PROG_PDR_MATCH` (đã biết SEID, chưa đụng rule PFCP). Không có policy ⇒ chuyển tiếp ngay (1 hash lookup).
- Action: `block` (DROP UL/DL), `ratelimit` (token bucket per-SEID, UL/DL riêng), `monitor` (không drop, đếm chi tiết).
- **Mọi gói bị drop được đếm vào `sec_stats_by_seid`** vì không còn tới URR — để xApp biết UE còn cố tấn công (S4).

### 5.3. UPF Security API
- HTTPS + mTLS, chỉ chấp nhận cert của xApp. `PUT/DELETE /v1/ues/{imsi}`, `PUT /v1/sessions/{seid}` (chế độ suy giảm), `GET /v1/ues`, `GET /v1/stats?seid=`, `GET /v1/info` (`boot_id`).
- Giới hạn tự áp: action ∈ {block, ratelimit, monitor}; TTL ≤ trần; ≤ N lệnh/giây; ≤ tỉ lệ UE bị chặn đồng thời; audit JSONL.

### 5.4. Guard quota theo cửa sổ (phản xạ tự động)
- XDP đã có Volume Quota (hết quota ⇒ DROP + report VOLQU). Mở rộng: quota tính **trong từng cửa sổ W**; vượt Q byte ⇒ DROP phần còn lại của cửa sổ, one-shot VOLQU/cửa sổ, sang cửa sổ mới tự gỡ. Tùy chọn `hold`: N cửa sổ vi phạm liên tiếp ⇒ giữ DROP một TTL.
- Q, W do **SMF cấu hình qua PFCP** (Create/Update URR: Volume Quota + Measurement Period) ⇒ SMF biết trạng thái.
- Chạy không cần xApp: lớp an toàn khi bộ não chậm, bị làm mù (S3) hoặc bị chiếm.

### 5.5. DB danh tiếng trong xApp
```json
{"supi":"imsi-…","level":2,"expires_at":"…","score":7.5,"epoch":17,
 "evidence":[{"at":"…","layer":"core","kind":"guard_volqu","severity":3,"ref":"urr:seid=3/seqn=12","trust":1.0},
             {"at":"…","layer":"ran","kind":"kpm_prb_ul","severity":2,"ref":"kpm:node=3584/ue=1","trust":0.2}],
 "actions":[{"at":"…","layer":"ran","action":"prb_cap","verified":false},
            {"at":"…","layer":"core","action":"block","verified":true,"upf_epoch":17}]}
```
Bảng tin cậy theo E2 node: `{e2_node, kpm_trust, ctrl_trust, last_mismatch, alarm}`.

## 6. Escalation và fusion (trong xApp)

| Level | Điều kiện vào | Lớp RAN (E2) | Lớp core (UPF API) | `production` | `lab` |
|---|---|---|---|---|---|
| 0 | bình thường | — | guard quota mặc định | — | — |
| 1 | nghi ngờ (1 lớp) | Giới hạn PRB/MCS | `monitor` | 5 phút | 1 phút |
| 2 | xác nhận | Giữ giới hạn PRB | `ratelimit` | 1 giờ | 3 phút |
| 3 | tái phạm | RRC Release | **`block`** theo SUPI (cả session sau) | 24 giờ | 10 phút |
| 4 | cố chấp | Release ngay khi UE kết nối | `block` TTL = trần, xApp gia hạn liên tục | tới khi admin gỡ | tới khi admin gỡ |

- Level ≥ 3 cần bằng chứng từ **cả hai lớp**; một lớp đơn lẻ tối đa level 2 (chống báo nhầm).
- **Ngoại lệ S3:** `kpm_trust` của E2 node phục vụ UE dưới ngưỡng ⇒ bằng chứng core được một mình đẩy tới level 3. "RAN im lặng" ≠ "RAN nói bình thường".
- Score = Σ severity × trust, có decay; hết hạn ⇒ hạ một level, không về 0 ngay.
- Level 4 dùng `block` + gia hạn vì UPF áp trần TTL ⇒ xApp chết thì block tự hết hạn (đánh đổi có chủ đích).
- Profile `lab` để một lượt thí nghiệm ~15 phút đi qua được level 1 → 3 và quan sát decay; luận văn báo cáo theo `lab`, nêu `production` là khuyến nghị.

### 6.1. Tham số mặc định (chốt 01/10/2026, sửa được; phải nằm trong file cấu hình, không hardcode)

| Thành phần | Khóa | Giá trị | Lý do |
|---|---|---|---|
| xApp | `escalation.profile` | `lab` | xem bảng trên |
| UPF | `security.max_ttl_s` | 86400 | giới hạn thiệt hại khi xApp bị chiếm |
| UPF | `security.max_cmds_per_s` | 10 | vượt ⇒ 429 + cảnh báo |
| UPF | `security.max_blocked_ratio` | 0.5 (lab) | vượt ⇒ 403, cần admin; production thấp hơn |
| SMF | `urr.guard.window_s` | 1 | khớp chu kỳ KPM |
| SMF | `urr.guard.quota_ul_bytes` / `quota_dl_bytes` | 3125000 / 3125000 | ≈ 25 Mbit/s; > mức hợp lệ lab (10 Mbit/s), < flood (50–100 Mbit/s) |
| SMF/UPF | `urr.guard.mode` | `per-window` | `standard-replenish` chỉ để đối chứng |
| SMF/UPF | `urr.guard.hold_after_windows` / `hold_ttl_s` | 3 / 30 | chế độ `hold` |
| SMF | `urr.periodic_s` | 1 | đủ mịn cho kiểm tra nhất quán |
| SMF | `session_ttl.deactivated_release_s` | 120 (lab) | T1, mục 4.1: release session có UP DEACTIVATED quá lâu |
| SMF→UPF | `session_ttl.up_inactivity_s` | 60 (lab) | T2, mục 4.1: IE 117, UPF báo UPIR |
| xApp | `consistency.overhead_ul_bytes` / `overhead_dl_bytes` | 16,3 / 57,3 | A.7, mục 7: overhead URR mỗi gói theo chiều |
| xApp | `consistency.dl.window_s` / `epsilon` / `consecutive` | 1 / 0,02 / 1 | A.7: FPR 0/339 trên traffic lành tính |
| xApp | `consistency.ul.window_s` / `epsilon` / `consecutive` | 2 / 0,15 / 2 | A.7: FPR 0/159; đuôi UL dày ở W = 1 s |

Chỉnh Q sau khi đo FPR (kịch bản E9); kiểm tra giới hạn API ở E10.

## 7. Kịch bản S3 và kiểm tra nhất quán KPM ↔ URR

```
t0        UE flood UL 50 Mbit/s; MITM sửa KPM (PdcpSduVolumeUL, UEThpUl, PRB) về mức bình thường → detector KPM im lặng
t0+~ms    XDP guard: byte UL trong cửa sổ > Q → DROP phần còn lại + VOLQU (DN được bảo vệ ngay)
t0+~ms    UPF → SMF: PFCP Session Report (Usage Report, VOLQU)
t0+~100ms SMF → urr-producer → ICS → adapter → xApp
t0+~1s    xApp: evidence core → level 1 → UPF `monitor`; so URR_UL với KPM PdcpSduVolumeUL cùng UE, cùng cửa sổ
          → mismatch k/n cửa sổ → kpm_trust(gNB) giảm, alarm "kpm_integrity"; thử PRB cap qua E2
t0+~2-5s  VOLQU lặp lại + kpm_trust thấp → ngoại lệ fusion → level 3 → PUT /v1/ues/{imsi} block → XDP DROP
Sau đó    URR về ~0; sec_stats cho biết UE còn gửi; PRB cap không làm URR giảm → ctrl_trust giảm.
          UE reconnect: Establishment có User ID → UPF dẫn xuất block ngay, không cần xApp.
```

- **Cặp đại lượng:** `DRB.PdcpSduVolumeUL/DL` ↔ URR UL/DL bytes (SDU PDCP là gói IP, cùng lớp với byte ở UPF sau decap).
- **Hiệu chỉnh (A.7, đo 03/10/2026, 6 profile lành tính 1–15 Mbit/s, payload 100–1400 B; [`calib-a7-20261003`](../artifacts/k8s/diagnostics/calib-a7-20261003/README.md)):** KPM đếm gói IP; URR đếm gói IP + overhead cố định mỗi gói (UL: Ethernet ≈ 14 B; DL: Ethernet + IP/UDP/GTP-U ngoài ≈ 58 B). **Tỉ số cố định r không dùng được**: KPM/URR thay đổi theo cỡ gói (DL 0,69 ở 100 B → 0,96 ở 1200 B), sai tới 25% chỉ vì cỡ gói — một flood gói nhỏ sẽ trông như MITM. Mô hình dùng: `KPM ≈ URR_bytes − c_dir·URR_packets` (URR mang sẵn số gói), c ước lượng **c_UL = 16,3**, **c_DL = 57,3** B/gói; sai số dư toàn run ≤ 1,5% (UL), ≤ 0,4% (DL).
- **Nhiễu theo cửa sổ (mô hình theo gói):** DL p99 = 0,5% ở W = 1 s; UL p50 ≈ 1–2,6% nhưng đuôi dày (p99 ≈ 19% ở W = 1 s) do jitter thời điểm indication KPM/report URR — UL lỏng hơn DL (ngược dự đoán ban đầu).
- **Căn thời gian:** dấu thời gian KPM (xApp nhận) lệch URR (UPF báo) −0,6…+1,8 s tùy run ⇒ xApp phải căn theo lag (ước lượng trên traffic lành tính, như `calibrate.py`) hoặc dùng W ≥ 2 s; cửa sổ chạm khoảng trống KPM (> 1,5 s) bị loại.
- **Timestamp gốc (kiểm tra 03/10):** chuẩn có sẵn — E2SM-KPM `IndicationHeader-Format1.colletStartTime` (KPM v3: `OCTET STRING (SIZE(8))`) và PFCP Usage Report Start/End Time (TS 29.244, NTP chỉ phần giây ⇒ độ phân giải 1 s). Thực tế OAI: gNB điền `colletStartTime` = thời điểm *tạo* indication (cuối chu kỳ, µs Unix) chứ không phải đầu chu kỳ; SMF OAI bỏ Start/End Time khi chuyển Usage Report qua event exposure (đường này vốn là mở rộng OAI, TS 29.508 không có). Dùng timestamp gốc chỉ làm lag *ổn định hơn* (bỏ độ trễ truyền), không triệt tiêu: cả hai bên chính xác tới 1 s và cần đồng bộ đồng hồ gNB–UPF ⇒ giữ dung sai (UL 2 cửa sổ liên tiếp).
- **Luật (chốt từ FPR đo được):** DL: `|e| > 0,02` ở W = 1 s (FPR 0/339 cửa sổ); UL: `|e| > 0,15` ở **2 cửa sổ liên tiếp** W = 2 s (FPR 0/159; độ trễ phát hiện ≤ 4 s). Với e = (KPM − (URR − c·pkts)) / (URR − c·pkts). Cần thêm dữ liệu nhiều UE/kênh xấu trước khi coi là cuối cùng.
- Cần ánh xạ KPM UE ID ↔ SUPI; chưa có thì so tổng theo cell (yếu hơn).

## 8. Giới hạn và điểm lệch chuẩn (phải ghi trong luận văn)

- MITM "vừa đủ lệch" có thể lọt dưới ε. MITM kiểm soát toàn bộ E2 ⇒ lớp RAN mất tác dụng (PRB cap, RRC Release đều qua E2); lớp core vẫn bảo vệ DN và chặn theo SUPI qua reconnect nhưng không giải phóng tài nguyên vô tuyến. Biện pháp gốc là **IPsec trên E2** (O-RAN WG11); hệ thống này là phát hiện theo chiều sâu.
- **Giao diện xApp → UPF không có trong chuẩn O-RAN/3GPP** — đóng góp nghiên cứu; tối giản, mTLS, audit.
- **Miền RAN điều khiển được core** ⇒ rủi ro nếu xApp bị chiếm; giảm bằng giới hạn tự áp trong UPF, trần TTL, guard độc lập.
- **Guard "quota theo Measurement Period"** là mở rộng ngữ nghĩa TS 29.244; phương án chuẩn (SMF cấp lại quota mỗi chu kỳ bằng Update URR) chỉ dùng đối chứng, tốn 1 message PFCP/UE/chu kỳ.
- **Ánh xạ KPM UE ID ↔ SUPI qua AMF** không chuẩn hóa. Cài đặt (R1, 03/10): E2SM-KPM UE ID của gNB OAI là AMF UE NGAP ID (+ GUAMI); producer ở Non-RT đọc bảng "UEs' Information" mà AMF OAI in định kỳ (~20 s) trong log, qua Kubernetes API, rồi gắn vào URR ⇒ xApp dựng bảng UE ID → SUPI. Phụ thuộc định dạng log OAI; trễ tối đa ~20 s sau khi UE đăng ký (cửa sổ KPM chưa có SUPI bị bỏ qua, không tính là lệch); chỉ đúng với 1 AMF (cần thêm GUAMI khi nhiều AMF). Hệ thống thật cần NWDAF/Namf hoặc RAN cung cấp ánh xạ.
- **AMF OAI lệch chuẩn khi mất gNB** (UE → DEREGISTERED, không Release SM Context); không sửa AMF, bù bằng A.3 + TTL session (mục 4.1). Session epoch (A.4) suy ra từ `smf_timestamp − Duration` ở producer vì callback OAI không mang định danh session.
- **AMF OAI không báo được UE đã mất** (N1N2MessageTransfer luôn 200, UE context theo SUPI không bị xóa) và **SMF OAI không có network-requested PDU Session Release có N1** ⇒ T2 release session không hoạt động mà không báo UE; UE thật cần keep-alive dưới `up_inactivity_s` (mục 4.1).
- Chuyển UE sang slice cô lập **không làm được bằng N4 modification** (cần release + tạo lại PDU session với S-NSSAI khác) — ngoài phạm vi chính.

## 9. Nhật ký quyết định (gồm phương án bị loại)

| Ngày | Quyết định | Phương án bị loại và lý do |
|---|---|---|
| 30/09 | Đường điều khiển về UPF phải qua cơ chế UPF hiểu (PFCP hoặc API của chính UPF), không ghi BPF map từ ngoài | Ghi map trực tiếp từ ngoài UPF: state lệch với control plane, UPF/SMF ghi đè |
| 30/09 | Phase 0: chứng minh PFCP Update FAR → `rules_match_pdr` → XDP DROP | — (đã PASS, xem plan) |
| 30/09 | Trí nhớ dài hạn theo **SUPI**, tách khỏi map theo session | Blocklist theo UE IP/SEID trong BPF map: IP/SEID bị cấp lại ⇒ chặn nhầm UE vô tội, UE malicious né bằng reconnect |
| 30/09 | Phòng thủ **hai lớp**, RAN đi trước; gNB phải được patch để có hành động thật | Chỉ lớp core: không giải phóng PRB; chỉ lớp RAN: quên UE khi reconnect, tin KPM |
| 30/09 | Kịch bản MITM sửa KPM: UPF phản xạ bằng **guard quota** (SMF cấu hình), xApp củng cố bằng **kiểm tra nhất quán KPM↔URR** và trust theo E2 node | UPF tự chặn tùy ý: lệch state với SMF, báo nhầm không giới hạn |
| 30/09 | **Bỏ `core-actuator`** (service ra quyết định ở core) | Tách bộ não sang core: trái nguyên tắc "không thêm module tư duy vào core" của tác giả |
| 30/09 | **Bỏ API enforcement riêng ở SMF và đường PCF/NEF** | API riêng ở SMF: kém thực tế nhất; PCF: lab không có PCF, SMF v2.2.0 không có handler `SmPolicyUpdateNotify` |
| 30/09 | **eBPF UPF là UPF triển khai được**; logic bảo mật là mở rộng UPF; xApp là bộ não duy nhất | Coi "gắn vào UPF" là thêm agent riêng: sai — userspace UPF đã có sẵn |
| 30/09 | Policy bảo mật là **overlay** (`sec_policy_*`, stage riêng trước PDR), không sửa FAR | Sửa FAR qua PFCP: SMF có thể ghi đè (service request, path switch, restore) |
| 30/09 | SMF chỉ thêm **User ID IE** + cấu hình URR | Không có User ID: khoảng hở sau reconnect (giữ làm chế độ suy giảm) |
| 01/10 | Tham số mặc định mục 6.1 | — |
| 01/10 | Tầng 2 phải dọn sạch khi xóa session (sửa lỗi UPF A.2) | "Để map tích lũy": map theo session không phải trí nhớ; rò rỉ gây thừa hưởng rule (mục 4) |
| 01/10 | A.3: SMF gửi N4 Deletion cho session cũ khi va chạm PDU Session ID | Sửa AMF: đúng gốc nhưng thêm thay đổi core ngoài SMF; vẫn cần cho trường hợp UE không quay lại ⇒ giải bằng TTL |
| 01/10 | TTL session ba lớp T1/T2/T3 bằng thủ tục chuẩn (mục 4.1) | TTL thuần trong UPF: UPF tự xóa khi SMF còn giữ ⇒ lệch state; TTL áp cho cả trí nhớ SUPI: kẻ tấn công xóa lịch sử bằng cách bỏ session |
| 02/10 | T2 = UPIR + release theo không hoạt động (mục 4.1), keep-alive lành tính trong pod UE | Deactivate UP qua AMF rồi dựa vào AMF 404: AMF OAI không trả 404 và không xóa UE context ⇒ không có tín hiệu; sửa AMF: thêm thay đổi core ngoài SMF/UPF; dò bằng Namf_Location: không đúng vai trò SMF và cũng thấy context cũ |
| 02/10 | T2 phía UPF theo dõi bộ đếm gói URR trong userspace (1 s) | Map "gói cuối" mới trong XDP: thêm ghi map trên đường nóng và thêm một map tầng 2 phải dọn; cần URR (lab luôn bật) là đánh đổi chấp nhận được |
| 02/10 | DNS Docker: bỏ `dns` cố định (1.1.1.1/8.8.8.8) trong `/etc/docker/daemon.json` | Hardcode DNS công ty: laptop đổi mạng thì hỏng lại |
| 01/10 | A.4: session epoch do producer gán = thời điểm bắt đầu session (`smf_timestamp − Duration`), khóa `(SEID, epoch, UR-SEQN)` xuyên producer/adapter/xApp | Sửa SMF thêm định danh session vào callback: thêm thay đổi SMF không chuẩn; xóa PVC/BoltDB khi đổi run: che lỗi, mất dữ liệu |

## 10. Thuật ngữ

- **SEID**: định danh PFCP session (UP-SEID do UPF cấp). **PDR/FAR/QER/URR**: rule phát hiện gói / chuyển tiếp / QoS / đo lưu lượng (TS 29.244).
- **URR report**: Usage Report trong PFCP Session Report; trigger PERIO (định kỳ), VOLTH (ngưỡng), VOLQU (hết quota).
- **KPM**: E2SM-KPM, số đo RAN do gNB báo qua E2. **E2SM-RC**: service model điều khiển RAN.
- **XDP**: hook eBPF sớm nhất trên đường nhận gói; UPF dùng chuỗi tail-call qua `tail_call_progs`.
- **Tầng 1 / tầng 2**: xem mục 4.
