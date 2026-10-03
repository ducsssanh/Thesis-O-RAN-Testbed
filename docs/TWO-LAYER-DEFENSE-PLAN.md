# Plan và tiến độ: phòng thủ hai lớp RAN (xApp) + 5G core (eBPF UPF)

**Thiết kế (lý thuyết đã chốt, quyết định và lý do):** [TWO-LAYER-DEFENSE-DESIGN.md](TWO-LAYER-DEFENSE-DESIGN.md). File này chỉ chứa hiện trạng code, các phase, việc cần làm và kết quả.
**Khởi động session mới:** [SESSION-HANDOFF.md](SESSION-HANDOFF.md).

**Trạng thái (01/10/2026):** Phase 0 **PASS** (mục 6). Phase A: A.1–A.5 **xong, kiểm chứng trên cluster** (mục 7–9); A.6, A.7, A.8 (TTL session, đã thiết kế) chưa làm. Các phase R1–E chưa bắt đầu.

## 1. Lịch sử tài liệu

- 30/09: tạo plan N4 (`CLOSED-LOOP-N4-PLAN.md`), rồi đổi sang hai lớp; sửa lần 3: xApp là bộ não duy nhất, bỏ `core-actuator` và API enforcement ở SMF.
- 01/10: chốt tham số; Phase A #1–3 xong; tách lý thuyết sang file thiết kế.

## 2. Hiện trạng code liên quan

### RAN (OAI gNB E2 agent) — chưa có hành động thật
| SM | Handler | Thực tế |
|---|---|---|
| E2SM-RC | `write_ctrl_rc_sm` ([ran_func_rc.c](../src/oai-ran/openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c) dòng 872) | Chỉ "QoS flow mapping configuration", `printf`, không tác dụng |
| SLICE | `write_ctrl_slice_sm` | `printf`; indication là dữ liệu random |
| MAC/PDCP/GTP | `write_ctrl_*_sm` | "operation not supported" |

NR MAC không có slicing. Scheduler per-UE: `gNB_scheduler_{dl,ul}sch_default_policies.c`. RRC Release: `rrc_gNB_generate_RRCRelease` ([rrc_gNB.c](../src/oai-ran/openair2/RRC/NR/rrc_gNB.c) dòng 3737).

### UPF (eBPF)
- Pipeline tail-call: `PROG_SESSION_LOOKUP_IP=0 … PROG_MAR_APPLY=7`, `PROG_MAX=8`.
- Update FAR → `ModifyPipeline()` → `rules_match_pdr` (chứng minh ở Phase 0). VOLQU drop, VOLTH, PERIO, Time Quota trong XDP; ring buffer → PFCP report.
- Userspace control plane: `SessionManager`, `SessionProgramManager` (chỗ gắn dẫn xuất policy khi tạo/xóa session), `UrrReportConsumer`.
- `RemoveSession` dọn map khi xóa session: 3 lỗi (throw ENOENT, layout key ngược, sai danh sách PDR) đã sửa 01/10 — mục 7. Image hiện tại `oai-lab-upf:teardown-5f1ab8b55a95`.

### SMF v2.2.0
- Không gửi User ID IE (không có `user_id` trong SMF/UPF).
- `pfcp_create_urr()` cố định PERIO 10 s, VOLTH, TIMTH; VOLQU tắt.

### Đường URR
SMF → Event Exposure → `urr-producer` → ICS → `a1-ei-adapter` → xApp (đã chạy, PASS run `20260930T052819Z-m35`).

## 3. Các phase

Thứ tự "RAN trước": nền tảng → lớp RAN chạy độc lập → lớp core → vòng trao đổi → công cụ tấn công → nghiệm thu.

### Phase 0 — Chứng minh chuỗi control-plane → BPF map → XDP drop: PASS ✅
Mục 6.

### Phase A — Nền tảng (2–4 ngày) — ✅ XONG 03/10 (mục 7–11; Gate A đạt cho 1 UE)
1. ✅ Harness: kiểm tra/cài lại route `172.30.26.0/24 dev oaitun_ue1` trước mỗi experiment.
2. ✅ UPF `RemovePipeline`: tìm delete lỗi (`BPF map delete failed`), best-effort (bỏ qua ENOENT, xóa tiếp, log); kiểm tra không còn key của SEID sau deletion.
3. ✅ Session mồ côi khi UE restart không deregister (SEID 2): bảo đảm release và UPF nhận Deletion.
4. ✅ Session epoch producer → adapter → xApp.
5. ✅ UPF `pfcp_far::update()`: chỉ set Apply Action khi IE có mặt.
6. ✅ SMF: URR cấu hình được (PERIO, VOLTH, VOLQU) thay vì hardcode; PERIO 1 s cho thí nghiệm; đo tải PFCP/Event Exposure.
7. ✅ Hiệu chỉnh URR ↔ KPM PDCP volume trên traffic lành tính.
8. ✅ TTL session ba lớp (thiết kế: `TWO-LAYER-DEFENSE-DESIGN.md` mục 4.1): T1 SMF release session UP DEACTIVATED quá `session_ttl.deactivated_release_s`; T2 IE 117 User Plane Inactivity Timer → UPF báo UPIR → SMF đánh dấu, release nếu không có traffic trong `deactivated_release_s` (hiệu chỉnh 02/10: AMF OAI không trả 404, design 4.1); T3 UPF xóa session của association cũ khi SMF restart (Recovery Time Stamp đổi). Gate: 3 kịch bản trong mục 4.1.

**Gate A:** ✅ 3 chu kỳ detach/attach, BPF map chỉ còn session đang sống; URR 1 s tới xApp; bảng hiệu chỉnh (mô hình theo gói thay cho r̂ cố định) và ε. Còn mở: kiểm chứng ε với nhiều UE (cùng R1).

### Phase R1 — Ánh xạ RAN UE ID ↔ SUPI, nhiều UE (2–3 ngày) — ✅ XONG 03/10 (mục 12)
- KPM v3 UE ID: AMF-UE-NGAP-ID + GUAMI → SUPI qua AMF (log có cấu trúc hoặc API nhỏ trên AMF; ghi rõ không chuẩn).
- Thêm UE thứ 2 (`configs/ue/ue2.conf` đã có).
- **Gate R1:** ✅ 2 UE, xApp gắn đúng KPM ↔ URR ↔ SUPI cho từng UE.

### Phase R2 — Hành động RAN thật trong gNB (4–6 ngày)
1. Giới hạn PRB/MCS theo UE trong scheduler DL/UL.
2. RRC Release UE chỉ định (hoặc NGAP UE Context Release Request để AMF biết).
3. Nhận lệnh qua E2SM-RC control, thay handler stub; ưu tiên style chuẩn (Style 2 cho PRB; style access/release tùy FlexRIC hỗ trợ), thiếu encoder thì dùng action ID riêng và ghi rõ.
4. Patch `patches/oai-ran-e2-rc-enforcement.patch`, image gNB mới.
- **Gate R2 ("Phase 0 của RAN"):** PRB cap làm throughput UE giảm đúng mức, UE khác không ảnh hưởng; Release đưa UE ra khỏi RRC_CONNECTED.

### Phase R3 — Lớp RAN chạy độc lập (2–3 ngày)
- xApp: detector KPM (rule tĩnh: PRB UL/BSR/throughput vượt ngưỡng k/n), DB danh tiếng SQLite, escalation phần RAN.
- **Gate R3 (S1 chỉ RAN):** flood → PRB cap ≤ 2 s → cell phục hồi cho UE khác. Ghi nhận giới hạn: reconnect thì thoát.

### Phase C — SMF: chỉ thay đổi chuẩn (1–2 ngày) — ✅ XONG 03/10 (mục 10)
1. ✅ Gửi **User ID IE** (IMSI từ SUPI; tùy chọn IMEI từ PEI) trong PFCP Session Establishment Request.
2. ◐ Tạo URR guard (Volume Quota + Measurement Period) cho mọi session từ cấu hình (nối tiếp A.6) — SMF đã gửi được (`urr.guard.*`), đang **tắt** tới khi UPF có ngữ nghĩa theo cửa sổ (Phase G).
3. ✅ Kiểm chứng UPF decode được User ID (decoder có sẵn; sửa lỗi độ dài IE ở encoder SMF — C20).
4. ✅ Patch `patches/oai-smf-v2.2.0-user-id-urr-config-ttl.patch` (+ `oai-smf-v2.2.0-common-src-user-id-length.patch`, `oai-upf-user-id-session-ttl.patch`).
- **Gate C:** ✅ PCAP Establishment có User ID đúng IMSI; UPF log in ra SUPI của session.

### Phase U — eBPF UPF security layer (5–7 ngày)
1. Kernel: map `sec_policy_by_supi` (pinned), `sec_policy_by_seid`, `sec_stats_by_seid`; stage `PROG_SEC_POLICY` giữa session lookup và PDR match; `block`/`ratelimit` (token bucket)/`monitor`; kiểm tra `expires_at` bằng `bpf_ktime_get_ns()`.
2. Userspace: khi Session Establishment, đọc User ID → tra `by_supi` → ghi `by_seid` **trước khi** pipeline của session được kích hoạt (không có cửa sổ gói lọt); khi Deletion thì xóa `by_seid` + `sec_stats`, giữ `by_supi`.
3. UPF Security API (thiết kế mục 5.3) với giới hạn tự áp và audit; `boot_id` để xApp phát hiện restart.
4. Đo overhead: pps tối đa và CPU khi có/không có stage mới, với 0/1k/10k policy.
- **Gate U:**
  - `PUT block` → traffic UE về 0 trong ≤ 1 s; rule PFCP (dump `rules_match_pdr`) **không đổi**; SMF không lỗi.
  - UE reconnect → session mới bị chặn từ gói đầu tiên (PCAP N3/N6 không có gói nào của UE ra DN).
  - `sec_stats` tăng khi UE tiếp tục gửi.
  - Vượt rate limit lệnh / số UE block → API từ chối.
  - UPF restart → `by_supi` còn (pinned), `by_seid` được dẫn xuất lại cho session được restore.

### Phase G — Guard quota theo cửa sổ (3–4 ngày)
1. `xdp_urr_apply_kern.c`: counter guard theo cửa sổ (map per-SEID), DROP khi vượt Q, one-shot VOLQU mỗi cửa sổ; chế độ `hold` với TTL.
2. Userspace: map guard config từ Create/Update URR vào `urr_config_map`.
3. Đo overhead XDP.
- **Gate G:** flood > Q/W bị drop trong cùng cửa sổ; đúng 1 VOLQU/cửa sổ tới xApp; traffic ≤ Q/W không bị ảnh hưởng; guard vẫn chạy khi xApp dừng.

### Phase M — Công cụ tấn công cho thí nghiệm (3–5 ngày, chỉ trong lab cô lập)
1. Traffic flood: iperf UDP tốc độ cao, nhiều UE, đích cố định; kịch bản bật/tắt theo thời gian.
2. **E2 MITM proxy:** pod trên mạng E2; gNB trỏ E2 tới proxy (giả lập on-path, lab không có IPsec E2). Dùng encoder/decoder E2AP/E2SM-KPM của FlexRIC để chuyển tiếp SCTP, giải mã RIC Indication, **sửa giá trị KPM**, mã hóa lại. Tùy chọn chặn/sửa E2 control.
3. Cờ bật/tắt; log mọi sửa đổi làm ground truth.
- **Gate M:** khi bật MITM, xApp nhận KPM đã sửa (khớp log proxy), URR phản ánh traffic thật.

### Phase L — Bộ não xApp và vòng trao đổi (4–5 ngày)
1. Client UPF Security API (libcurl + mTLS); lưu quyết định trước khi gửi; đối chiếu định kỳ `GET /v1/ues` với DB, đẩy lại khi lệch hoặc `boot_id` đổi.
2. Kiểm tra nhất quán KPM↔URR, `kpm_trust` theo E2 node (thiết kế mục 7).
3. Kiểm chứng hành động: PRB cap phải làm URR giảm, không thì `ctrl_trust` giảm; block phải làm URR về ~0.
4. S4: level ≥ 3 mà `sec_stats` drop UL tiếp tục tăng / KPM PRB UL cao → RRC Release.
5. Escalation + fusion có trọng số + ngoại lệ S3 (thiết kế mục 6); unit test cho policy.

### Phase E — Nghiệm thu E2E (3 ngày)
`tests/k8s/test_two_layer_gate.py`:

| # | Kịch bản | Kỳ vọng |
|---|---|---|
| E1 | S1, chỉ lớp RAN | PRB cap ≤ 2 s; reconnect thì thoát (giới hạn đã biết) |
| E2 | S1+S2, cả hai lớp | Reconnect bị chặn từ gói đầu tiên nhờ User ID + `by_supi` |
| E3 | **S3: flood + KPM MITM** | Detector KPM im lặng; guard chặn trong cửa sổ đầu; alarm `kpm_integrity` ≤ k cửa sổ; level 3 chỉ với bằng chứng core; UPF `block` |
| E4 | S3 + MITM chặn E2 control | PRB cap không có tác dụng theo URR → `ctrl_trust` giảm; core vẫn cô lập |
| E5 | S4 | UPF block, `sec_stats` drop UL tăng → RRC Release |
| E6 | Escalation/decay | Level 1→2→3 đúng bảng; hết hạn hạ level, traffic phục hồi |
| E7 | Restart UPF / xApp | UPF: `by_supi` còn; xApp: đối chiếu lại; không mở khóa nhầm |
| E8 | Không lẫn UE | UE lành tính nhận lại IP/SEID cũ không bị chặn |
| E9 | Lành tính tải cao | Không vượt level 1; ghi nhận FPR |
| E10 | xApp bị chiếm (giả lập) | Lệnh block hàng loạt bị UPF giới hạn; block tự hết hạn khi xApp ngừng gia hạn |

**Chỉ số đánh giá:** thời gian phát hiện; thời gian tới gói đầu tiên bị drop; byte lọt tới DN; TPR/FPR của detector KPM, guard và kiểm tra nhất quán (ROC theo ε, k/n); độ trễ từng chặng (E2, xApp, API UPF, XDP); overhead XDP theo số policy; tải PFCP/Event Exposure theo chu kỳ URR. Correlation theo `decision_id`/`epoch`.

### Phase F — Mở rộng (tùy chọn)
Throttle bằng QER chuẩn qua SMF; key IMEI (User ID IE có IMEI); chuyển UE sang slice cô lập (release + tạo lại session với S-NSSAI khác); detector học máy dùng DB evidence làm nhãn; nhiều UPF.

## 4. Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Không làm được ánh xạ KPM UE ID ↔ SUPI | R1 làm sớm; fallback so tổng theo cell |
| FlexRIC/OAI thiếu encoder cho RC style cần dùng | Action ID riêng, ghi rõ không chuẩn |
| Giao diện xApp → UPF không có trong chuẩn O-RAN/3GPP | Trình bày như đóng góp nghiên cứu; API tối giản, mTLS, audit |
| Miền RAN (xApp bị chiếm) điều khiển được core | Giới hạn tự áp trong UPF, trần TTL, guard độc lập; E10 |
| SMF không gửi User ID (core không hỗ trợ) | Chế độ suy giảm theo SEID + guard; đo khoảng hở trong E2 |
| Map pinned mất khi node reboot | DB xApp là nguồn sự thật; đối chiếu theo `boot_id` |
| URR 1 s gây tải PFCP/SBI | ✅ Đã đo (mục 11): ≈ 2,7% core/UE, 2 bản tin PFCP/s/UE; guard XDP không phụ thuộc chu kỳ report |
| Guard quota báo nhầm UE tải cao | Chặn giới hạn trong cửa sổ; E9 đo FPR |
| MITM kiểm soát hoàn toàn E2 | Core vẫn bảo vệ DN và chặn theo SUPI; ghi rõ giới hạn; khuyến nghị IPsec E2 |
| Overhead stage mới trong XDP | 1 hash lookup khi không có policy; đo trong Gate U |

## 5. Việc làm ngay

| # | Việc | Phase | Ước lượng | Phụ thuộc |
|---|---|---|---|---|
| 1 | ✅ Harness kiểm tra/cài lại route UE | A.1 | 0.5 h | — |
| 2 | ✅ `RemovePipeline` best-effort + kiểm tra map sạch (gồm sửa layout key, mục 7) | A.2 | 0.5–1 ngày | — |
| 3 | ✅ UPF chỉ set Apply Action khi IE có mặt | A.5 | 1 h | build UPF cùng #2 |
| 4 | ✅ Session mồ côi khi UE restart (sửa SMF, mục 8) | A.3 | 0.5–1 ngày | — |
| 5 | ✅ Session epoch (mục 9) | A.4 | 1 ngày | — |
| 6 | ✅ SMF URR cấu hình được, PERIO 1 s; đo tải (mục 10, 11) | A.6 | 1 ngày | — |
| 7 | ✅ Hiệu chỉnh URR ↔ KPM (mục 11) | A.7 | 0.5 ngày | 1, 6 |
| 7b | ✅ TTL session T1/T2/T3 — 3 kịch bản PASS (mục 10) | A.8 | 2–3 ngày | 4; làm cùng A.6/C vì cùng sửa Establishment |
| 7c | ✅ Phase C: User ID IE + URR từ cấu hình (Gate C PASS, mục 10) | C | 1–2 ngày | — |
| 8 | ✅ Ánh xạ KPM UE ID ↔ SUPI, 2 UE (mục 12) | R1 | 2–3 ngày | 1 |
| 9 | gNB: PRB cap + RRC Release qua E2SM-RC; Gate R2 | R2 | 4–6 ngày | — (song song A) |
| 10 | xApp detector KPM + hành động RAN; Gate R3 | R3 | 2–3 ngày | 8, 9 |

Sau đó: U → G → M → L → E (Phase 0, A, C đã xong). M có thể làm sớm để có dữ liệu flood thật cho ε.

Tham số mặc định đã chốt: [TWO-LAYER-DEFENSE-DESIGN.md](TWO-LAYER-DEFENSE-DESIGN.md) mục 6.1.

## 6. Kết quả Phase 0 — PASS

Run: [`artifacts/experiments/20260930T073310Z-phase0-far`](../artifacts/experiments/20260930T073310Z-phase0-far/summary.json). Công cụ: [`scripts/k8s/phase0/`](../scripts/k8s/phase0/) (`run.sh <out-dir> [up-seid] [ue-ip]`).

**Mục đích trong thiết kế hiện tại:** chứng minh control plane của UPF chuyển một thay đổi thành cập nhật BPF map và XDP thi hành ngay, không làm mất session. Thiết kế cuối dùng overlay `sec_policy_*` thay vì sửa FAR.

**Cách làm.** `pfcp_far_probe.py` (stdlib) chạy trong sidecar `capture` của pod SMF (cùng netns, N4 `172.30.24.10`, port ngẫu nhiên, không đụng socket 8805 của SMF), gửi Session Modification Request tới UPF `172.30.24.20:8805` cho UP-SEID 3: Update FAR 1 (UL) và FAR 2 (DL), mỗi cái chỉ gồm FAR ID và Apply Action. UPF không kiểm tra nguồn request, chỉ tra SEID ([pfcp_switch.cpp](../src/oai-upf/src/upf_app/simpleswitch/pfcp_switch.cpp) dòng 951). SMF không biết thay đổi nên phải gửi FORW khôi phục. `rules_match_pdr` đọc bằng bpftool của host qua container privileged tạm thời ([bpftool.sh](../scripts/k8s/phase0/bpftool.sh)).

**Kết quả** (iperf UDP 1 Mbit/s mỗi chiều, 45 s, báo cáo mỗi giây; DROP ở t≈12.0 s, FORW ở t≈27.8 s):

| | Trước DROP | Khi DROP | Sau FORW |
|---|---|---|---|
| UL (DN nhận) | 1049.6 kbps | **0** (13/13 giây) | 1049.2 kbps |
| DL (UE nhận) | 1050.4 kbps | **0** (13/13 giây) | 1048.8 kbps |

- PFCP: 2 cặp Request/Response, Cause 1, RTT UPF ~0.4 ms; `n4.pcap` giải mã đúng FAR ID 1, 2 và cờ DROP/FORW.
- `rules_match_pdr` SEID 3: `forw=1` → `drop=1,forw=0` (PDR 1, 2) → `forw=1`; TEID DL `0x53257f3c` giữ nguyên.
- Traffic bị chặn trong cùng khoảng 1 s với lệnh, khôi phục ngay giây kế tiếp. Độ trễ mức ms chưa đo (Phase E).
- SMF không lỗi, vẫn nhận URR; UE giữ PDU session.

**Phát hiện phụ (đưa vào Phase A):**
1. `pfcp_far::update()` ghi Apply Action vô điều kiện ([pfcp_far.cpp](../src/oai-upf/src/upf_app/simpleswitch/pfcp_far.cpp) dòng 111). → A.5.
2. Entry cũ của SEID 1, 2 trong map. `RemoveSession` **có** code dọn map; nguyên nhân thật: SEID 1 có Deletion nhưng `RemovePipeline failed ...: BPF map delete failed` dừng giữa chừng (→ A.2); SEID 2 chưa từng có Deletion, là session mồ côi sau khi UE restart (→ A.3). Khi sửa A.2 phát hiện thêm nguyên nhân sâu hơn — xem mục 7.
3. Route `172.30.26.0/24 dev oaitun_ue1` mất khi pod UE restart: UL đi eth0, iperf2 DL `connect()` nhầm local `10.244.1.82`. Trông như DL hỏng dù GTP tới gNB và tun. → A.1.

## 7. Kết quả Phase A việc #1–3 (01/10/2026)

Image UPF: `oai-lab-upf:teardown-5f1ab8b55a95` (`sha256:b949128a…`), patch [`patches/oai-upf-teardown-best-effort.patch`](../patches/oai-upf-teardown-best-effort.patch) (5 file, +114/−22) trên nền `qfi-f6d0516adf20`. Lock: `artifacts/k8s/state/images.{json,yaml}` (bản cũ `*.bak-qfi-20261001`). Bằng chứng: [`artifacts/k8s/diagnostics/teardown-final-20261001`](../artifacts/k8s/diagnostics/teardown-final-20261001/), hồi quy traffic [`20261001T102111Z-phase0-far-teardown`](../artifacts/experiments/20261001T102111Z-phase0-far-teardown/summary.json).

**#1 — route UE (A.1).** `ensure_ue_route()` trong `scripts/k8s/staged.py` (đường chạy thật của `lab.sh experiment`/`up --stage ran`) và `scripts/k8s/lab.py` (baseline): kiểm tra route hiệu lực bằng `ip -j route get <DN>`, cài lại `172.30.26.0/24 dev oaitun_ue1 src <UE>` nếu sai, fail rõ ràng nếu vẫn sai; gọi ở stage RAN và trước mỗi chiều traffic. Unit test: `tests/test_k8s_staged.py` (3 test mới), `tests/k8s/test_lab.py` (3 test mới). Runtime: `ip route get 172.30.26.10` → `dev oaitun_ue1 prefsrc 10.1.0.2`.

**#2 — dọn BPF map khi xóa session (A.2).** Ba lỗi chồng nhau trong UPF:
1. `BPFMap::Remove()` throw với mọi lỗi kể cả ENOENT; `sdf_filters_map` không có entry khi tắt QoS → exception sau PDR đầu tiên, bỏ dở toàn bộ phần dọn còn lại. Sửa: `RemoveIfPresent()` (ENOENT không phải lỗi, lỗi khác chỉ log) cho mọi map trong `RemoveSession`.
2. **Layout key sai:** `PdrMatchProgram` tự định nghĩa `pdr_rule_key {u64 seid; u32 pdr_id; u32 pad}` packed, trong khi kernel và `CreatePipeline` dùng `struct pdrs_per_session {u16 pdr_id; u64 seid}` (pdr_id offset 0, seid offset 8). Mọi lệnh xóa (SEID s, PDR p) thực chất nhắm (PDR s, SEID p): trúng nhầm entry khác hoặc ENOENT im lặng. Sửa: `using pdr_rule_key = struct pdrs_per_session`, `MakePdrKey` xóa sạch byte đệm. `PopulateSdfFilterMap`/`PopulateRulesMatchPdrMap` (không được gọi ở đâu) vẫn dùng kiểu key này; không sửa thêm.
3. `session->pdrs` đã rỗng lúc xóa; datapath dựng từ `pdrs_uplink`/`pdrs_downlink`. Sửa: xóa theo danh sách UL+DL.
- Lưới an toàn: quét theo SEID (`SweepSeid<Key>` đúng kiểu key từng map: `pdrs_per_session`, `session_qfi`), cảnh báo `swept N stale entries` chỉ khi còn sót.
- Kết quả 3 chu kỳ UE (xóa pod → Deletion → session mới): 3/3 `Pipeline removed`, 6/6 entry `rules_match` xóa đúng bởi vòng lặp, 0 lỗi, 0 lần quét bổ sung; theo dõi map ~1 s/lần: map rỗng ngay sau mỗi Deletion, cuối cùng chỉ còn session đang sống.
- Ghi chú trung thực: một lượt với image trung gian `teardown-69941eee966b` (cùng logic UL/DL, ít log hơn) vẫn thấy vòng lặp không xóa được và bước quét phải dọn; chưa giải thích được. Bản chẩn đoán và bản cuối cho kết quả đúng ổn định (6/6 Deletion qua hai image).

**#3 — Apply Action có điều kiện (A.5).** `pfcp_far::update()` chỉ set khi IE có mặt. Runtime (probe `--action none|drop|forw`): none → giữ FORW; drop → DROP; none → **giữ DROP**; forw → FORW; Cause 1 tất cả.

**Hồi quy:** Phase 0 trên image cuối — UL/DL ~1050 kbps → 0 (13/13 s) khi DROP → ~1046 kbps sau FORW.

**Chưa xong của Phase A:** A.3 xem mục 8. A.4 session epoch, A.6–A.7 chưa bắt đầu.

**Sự cố hạ tầng phát sinh khi deploy** (chi tiết: [`recover-20261001/README.md`](../artifacts/k8s/diagnostics/recover-20261001/README.md)): Multus OOMKilled (tăng limit), DNS search-path/PTR treo do resolver Docker hỏng (`scripts/k8s/coredns-search-guard.sh`), `lab.sh up` không `--stage` chạm vào release cũ `oai-lab` (đã xóa 11 Deployment rollback).

## 8. Kết quả Phase A việc #4 — A.3 session mồ côi (01/10/2026)

**Nguyên nhân gốc** (không phải UE chết đột ngột, mà **gNB chết**): AMF nhận SCTP Shutdown → UP Deactivation → đặt UE DEREGISTERED, xóa UE context **không** Release SM Context. UE đăng ký lại với cùng PDU Session ID → Create SM Context mới → SMF phát hiện va chạm (`PDU Session already existed`) nhưng `remove_pdu_session()` chỉ xóa trong bộ nhớ SMF, không N4 Deletion → session cũ (FAR FORW, TEID cũ) ở lại trong mọi BPF map. Khi chỉ UE chết, gNB còn sống nên AMF Release SM Context bình thường — đó là lý do lần thử trước 6/6 sạch.

**Sửa (SMF, hành vi chuẩn TS 23.502 khi va chạm PDU Session ID):** `smf_context::release_stale_pdu_session()` gửi N4 Session Deletion tới mọi UPF của session cũ (bỏ qua nếu đã release, `up_fseid.seid == 0`), giải phóng tài nguyên, rồi mới xử lý Establishment mới; Deletion tới UPF trước Establishment. Patch [`oai-smf-v2.2.0-stale-session-release.patch`](../patches/oai-smf-v2.2.0-stale-session-release.patch); image `oai-lab-smf:v2.2.0-ie43-stale-2fa8f172`.

**Kiểm chứng** (`scripts/k8s/phase0/orphan_cycle.sh <out> <N> ue|gnb`; bằng chứng [`orphan-a3-20261001`](../artifacts/k8s/diagnostics/orphan-a3-20261001/README.md)):
- SMF cũ, kill gNB+UE ×2: **FAIL**, map `[1 2 3]` (mỗi lần +1 session mồ côi) — tái hiện có kiểm soát.
- SMF mới, kill gNB+UE ×3: **PASS**, chỉ còn SEID 4, Deletion cho 1/2/3. Kill UE ×3: **PASS**, chỉ còn SEID 7.
- Sau 6 chu kỳ: `rules_match_pdr` 2 entry (UL+DL), `session_rules_enabled`, `session_by_ue_ip`, `pdrs_per_session`, `urr_volume_count`, `urr_config_map` mỗi map 1 entry — chỉ session sống (phần map của Gate A).
- Hồi quy `lab.sh experiment` run `20261001T123315Z-m35`: PASS.

**Giới hạn còn lại:** AMF lệch chuẩn (mất gNB ⇒ DEREGISTERED thay vì CM-IDLE) không sửa; nếu UE không bao giờ quay lại, session cũ treo đến khi UPF restart. Sau khi kill gNB phải `up --stage ran` (restart xApp) để có lại subscription KPM.

## 9. Kết quả Phase A việc #5 — A.4 session epoch và độ bền KPM (01/10/2026)

**Session epoch.** Callback OAI không mang định danh session (`pduSeId` luôn 0; SEID là CP SEID của SMF, đánh lại từ 1 sau mỗi lần SMF restart). Nhưng `Duration` và `Volume` trong Usage Report **cộng dồn từ đầu session** ⇒ `smf_timestamp − Duration` = thời điểm bắt đầu session, ổn định (±1 s) qua mọi report. Producer (`src/urr-producer/internal/producer/epoch.go`) gán `session_epoch` (dạng `20261001T140605Z`) theo (SUPI, SEID): mở epoch mới khi ước lượng lệch > 3 s, hoặc khi khóa `(SEID, epoch, UR-SEQN)` đã có với nội dung khác; trùng nội dung = gửi lại ⇒ bỏ. Schema 1.1.0; adapter và xApp dùng cùng khóa (`event_id = job:SEID:epoch:UR-SEQN`); bản ghi cũ không có epoch giữ khóa cũ. Unit test: producer (5 kịch bản), adapter (409 chỉ khi cùng epoch), smoke test receiver xApp. Image: producer `oai-lab-urr-ei-producer:5dc07af1a610989e`, adapter `oai-lab-a1-ei-adapter:2ff96bc6adf5169c`, xApp `oai-lab-xapp:8f07808f149594ee`.

**Kiểm chứng** ([`epoch-a4-20261001`](../artifacts/k8s/diagnostics/epoch-a4-20261001/summary.txt)): mỗi session đúng một epoch (27/27, 26/26 report); sau restart SMF, session mới nhận lại **SEID 1** với UR-SEQN 1–26 đã có từ session trước ⇒ epoch mới `20261001T140605Z`, 26/26 report tới xApp (khóa cũ sẽ nuốt cả 26). `experiment` run `20261001T140526Z-m35` PASS.

**Độ bền KPM (phát sinh khi kiểm chứng).** (1) xApp đăng ký KPM một lần lúc khởi động; gNB khởi động lại ⇒ KPM mất im lặng. Thêm watchdog: không có indication `KPM_STALE_S` giây ⇒ xApp thoát, Kubernetes khởi động lại và đăng ký lại; xApp chờ E2 node thay vì `assert`; CSV ghi tiếp thay vì ghi đè. Kill gNB+UE: xApp khởi động lại 1 lần, KPM tươi (1 s) sau ~1 phút. (2) FlexRIC có thể **kẹt** sau khi một E2 node chết khi đang xóa subscription (lặp `MSG ALREADY PENDING`/`Pending event timeout`), từ chối xApp mới — lỗi FlexRIC, chỉ hết khi restart RIC. Harness: `up --stage ran` phát hiện và restart RIC (rồi gNB); `experiment` dừng sớm với hướng dẫn nếu KPM cũ > 30 s.

**Sửa nhỏ khác:** `lab.py build` gắn tag SMF theo hash mọi patch SMF (`v2.2.0-lab-<hash>`) và reverse-check từng patch; tài liệu tổng hợp thay đổi so với upstream OAI: [OAI-UPSTREAM-CHANGES.md](OAI-UPSTREAM-CHANGES.md).

## 10. Kết quả A.6, Phase C, A.8 (03/10/2026)

Chi tiết và bằng chứng: [`ttl-a8-20261003`](../artifacts/k8s/diagnostics/ttl-a8-20261003/README.md).
- **Gate C PASS**: User ID IE đúng IMSI trong PCAP; UPF gắn SUPI vào session.
- **A.6**: PERIO 1 s từ cấu hình; 1 report/s tới xApp qua A1-EI thật. Còn lại: đo tải PFCP/Event Exposure (CPU SMF/producer theo số UE).
- **A.8 PASS** cả 3 kịch bản (gNB chết hẳn ⇒ T1/T2; UE im lặng ⇒ T2, traffic giữ session; restart SMF ⇒ T3).
- Hai lỗi OAI có sẵn đã sửa: C24 (SMF mất FTUP khi UPF re-associate ⇒ mất toàn bộ UL — xảy ra mỗi lần `rollout upf`), C25 (Usage Report lũy kế ⇒ xApp/producer hiểu sai lượng theo chu kỳ; ảnh hưởng trực tiếp A.7).
- Quan sát: khi gNB được thay thế (NG Setup lại) hoặc chết hẳn, AMF OAI v2.2.0 trong lab này có báo SMF (Release SM Context / AN release); trường hợp AMF im lặng (A.3) vẫn có TTL bao phủ.

## 11. Kết quả A.7 hiệu chỉnh URR ↔ KPM và tải A.6 (03/10/2026)

Chi tiết: [`calib-a7-20261003`](../artifacts/k8s/diagnostics/calib-a7-20261003/README.md); mô hình và ngưỡng chốt ở design mục 7 + 6.1.
- Tỉ số cố định r̂ bị loại: phụ thuộc cỡ gói (sai tới 25%). Mô hình theo gói `KPM ≈ URR − c·pkts`, c_UL = 16,3, c_DL = 57,3 B.
- ε: DL 0,02 @ 1 s; UL 0,15 ở 2 cửa sổ liên tiếp @ 2 s; FPR 0 trên 6 profile lành tính.
- Tải đường URR ≈ 2,7% core/UE ở PERIO 1 s (SMF 1,2%, adapter 0,9%, xApp 0,4%, producer 0,2%).
- Sửa thêm khi đo: C25 report PERIO theo hết chu kỳ đo (trước đây chờ gói kế ⇒ report dồn, báo nhầm); `CAP_KILL` cho container capture.
- **Gate A**: map sạch qua chu kỳ attach/detach (A.3, A.8), URR 1 s tới xApp, bảng r̂/ε ⇒ **đạt** cho 1 UE. Còn mở: kiểm chứng ε với nhiều UE/kênh xấu (làm cùng R1).

## 12. Kết quả R1 — ánh xạ KPM UE ID ↔ SUPI với 2 UE (03/10/2026)

Bằng chứng: [`r1-20261003`](../artifacts/k8s/diagnostics/r1-20261003/) (`result.json`, `ue-churn/`); script `scripts/k8s/phase0/r1_gate.py`.
- Chuỗi: KPM (E2 node, AMF UE NGAP ID) ↔ [bảng AMF, đọc ở Non-RT] ↔ SUPI ↔ URR (SUPI từ SMF, SEID + epoch). Timestamp gốc: KPM `colletStartTime`, URR PFCP End Time (C26).
- **Gate R1 PASS** (UE1 4 Mbit/s, UE2 1 Mbit/s đồng thời, 40 s): bảng AMF 2 UE; 35/35 URR mỗi SUPI mang đúng `ran_identity` và End Time; 68/68 dòng KPM gắn đúng SUPI, 0 sai; volume UL theo SUPI lệch −3,1% / −4,9% so với `URR − 16,3·pkts`, gán đảo thì lệch −77% / +297%.
- Lỗi phát hiện và sửa: C27 (bộ đếm KPM của gNB theo vị trí UE ⇒ volume tráo giữa các UE, tràn 2³²). Thử UE2 bị xóa giữa lúc UE1 có traffic: không còn mẫu tràn/phình.
- Giới hạn: ánh xạ đọc từ log AMF OAI (design mục 8), trễ ≤ ~20 s sau đăng ký; mỗi UE 1 PDU session (nhiều session cần cộng URR theo SUPI).

