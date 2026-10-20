# Testbed context — for external review of the flooding-vs-high-load dataset

Ngày: 2026-10-19. Mục đích: cung cấp đủ chi tiết testbed/telemetry/traffic để soi
lại confound trong dataset v3 (phát hiện: trên trục đã match volume yếu ~AUC 0.83,
nhưng có confound thổi phồng separability). Mọi số dưới đây lấy trực tiếp từ code,
không phải mô tả lý tưởng.

---

## 1. Testbed

- **Nền tảng:** Kubernetes một node (minikube, context `oai-lab`). Không có SDR/RF thật.
- **RAN:** OAI gNB (monolithic) + OAI NR-UE, chạy qua **OAI RFSIMULATOR** (RF simulator
  nội bộ của OAI, truyền qua **TCP socket** — **KHÔNG dùng ZMQ**; ZMQ là của srsRAN).
  Một cell, FR1 TDD, băng thông theo profile RFsim pinned.
- **Core/UPF:** **OAI 5G Core v2.2.0** (AMF, SMF, UPF, NRF, UDM/UDR/AUSF, PCF, NSSF).
  Một slice. UPF là OAI-UPF (có thêm **eBPF/XDP profiler** đếm packet-mix per-UE).
- **Số UE:** **2 UE hoạt động** — ue1 `imsi-001010123456780`, ue2 `...781`. Harness hỗ
  trợ tới ue4 nhưng chỉ ue1/ue2 được deploy.
- **RIC:** FlexRIC **near-RT RIC** (E2) + xApp "monitor" tự viết (E2SM-KPM để đo,
  E2SM-RC để điều khiển). **Non-RT RIC A1-EI**: `urr-ei-producer` → `a1-ei-adapter` →
  `informationservice` (ICS) đưa EI job về xApp.
- **Giới hạn vật lý đã biết:** TCP qua RFsim bị loss UL kẹp ~330 kbps (congestion control
  sập); benign high-load gói lớn phải dùng UDP. hping3 `-f` không tạo IP fragment thật
  qua tunnel GTP (frag_flood bị loại).

---

## 2. KPM (E2SM-KPM)

- **Kiểu:** REPORT, event trigger format 1. **`report_period_ms = 1000`**,
  **`gran_period_ms = 1000`** → **1 báo cáo/giây**. (nguồn: `xapp_kpm_moni.c:31,519`,
  `defense.c:300`.)
- **Granularity: per-UE** (theo `amf_ue_ngap_id`, map sang SUPI). Per-cell được **suy
  ra** bằng cách cộng PRB share của các UE trong cửa sổ 1.5 s (`features.c` `cell_load`).
- **Metric đang lấy và ánh xạ feature** (`defense.c:308-313`):
  | E2SM-KPM measurement | feature | ghi chú |
  |---|---|---|
  | `DRB.PdcpSduVolumeUL/DL` | `rate_ul/dl_kbps` | volume (Mb) / period → kbit/s |
  | `DRB.UEThpUl/Dl` | `thp_ul/dl_kbps` | throughput khi có data đệm (TS 28.552; một UE 2 Mbps có thể đọc 3.6 Mbps cạnh flood) |
  | `RRU.PrbTotUl/Dl` | `prb_ul/dl_pct` | % PRB used per-UE |
  | (suy ra) | `cell_prb_ul/dl_pct` | tổng PRB share các UE trong cell (cửa sổ 1.5 s) |

  Lưu ý: `rate_*` (PDCP volume) và `thp_*` (UEThp) là **hai định nghĩa tải khác nhau** —
  `thp` cao hơn `rate` khi buffer đầy. Band/overlap trong report dùng `thp_ul_kbps`.

---

## 3. URR (PFCP usage reporting) + profiler

- **Nguồn:** SMF `Nsmf_EventExposure` subscription sự kiện **`QOS_MON`** → SMF gửi PFCP
  usage report → `urr-ei-producer` (callback `/callbacks/smf`) → chuẩn hoá → A1-EI →
  xApp.
- **Trigger: PERIODIC (PERIO) mỗi 1 giây — theo THỜI GIAN, không phải volume-threshold**
  (`features.c:64` "PERIO 1 s"). OAI báo cáo **cumulative**; feature chia cho
  `interval_seconds` để ra rate.
- **Trường dùng:** `ul_bytes, dl_bytes, ul_packets, dl_packets, interval_seconds` →
  `urr_ul/dl_kbps = bytes*8/1000/interval`, `urr_ul/dl_pps = packets/interval`
  (`features.c:83-86`).
- **Profiler (`prof_*`) — eBPF/XDP trong UPF, per-UE, cửa sổ `window_ms`** (`features.c:
  205-219`): `prof_ul/dl_kbps`, `prof_ul/dl_pps`, `prof_ul/dl_mean_bytes`, đếm protocol
  `prof_{ul,dl}_{tcp, tcp_syn, udp, icmp, frag, dns, gtp_in_gtp}`, và
  `prof_ul_dst_estimate` (ước lượng số đích phân biệt → fan-out). Đây là tín hiệu
  **packet-level, độc lập volume**.
- **Nguồn tính:** `rate/thp/prb` ← KPM; `urr_*` ← PFCP usage report; `prof_*` ← eBPF UPF.
  Ba lớp độc lập.

---

## 4. Sinh traffic hiện tại

Detection **OFF** trong toàn bộ scenario dataset (mitigation không bóp méo traffic).

- **Benign (iperf2):**
  - UDP UL: `iperf -c <DN> -u -b <rate> -l <pkt> -t <dur> -p <port>` (chạy trong nr-ue).
  - TCP bulk: `iperf -c <DN> -w 1024k -t <dur>` (không `-b`; RFsim tự throttle) — có
    **DL ACK**.
  - ue2 = nền benign **400k UL cố định** trong MỌI scenario (kể cả scenario tấn công).
- **Malicious (hping3, từ sidecar `keepalive` của UE, egress `oaitun_ue1`):**
  base `hping3 -I oaitun_ue1 -i u<interval_us> -c <count> -d <pkt> -q` + cờ họ:
  | family | cờ | nhãn |
  |---|---|---|
  | udp_flood | `--udp -p <port>` | malicious |
  | syn_flood | `-S -p <port>` | malicious |
  | icmp_flood | `-1` (ICMP echo) | malicious |
  | dns_flood | `--udp -p 53` | malicious |
  | fanout_udp | `--udp -p <port> --rand-dest` (quét DN /24) | malicious |
  | frag_flood | `--udp -f --mtu <mtu>` | **LOẠI** (không tạo fragment thật) |
  | icmp_ping | `-1` pps thấp | benign control |
  | dns_query | `--udp -p 53` pps thấp | benign control |
- **Rate→pps:** `pps = rate_bps / 8 / (pkt + header)`, cap 20000 pps. Header: UDP/ICMP 28 B,
  SYN 40 B.
- **Load matching:** offered **UL byte-rate 500k & 1200k** cho CẢ hai lớp. Packet size:
  flood 64 B (nhỏ, pps cao) và 1400 B; benign 120 B và 1400 B. → match trên **offered UL
  rate**, KHÔNG match DL/pps/packet-size.
- **Thời lượng session:** phases `idle 15s` → `(attack|benign) 30s` → `gap 12s` → … Ví dụ
  ds-flood-udp: 15+30+12+30+12+30+12+30 ≈ **171 s/session** + tail 12s + drain. **reps=6**
  (gộp với v2's 3 reps = tối đa 9 session độc lập/scenario). 6 scenario:
  ds-benign-bulk (UDP lớn + TCP), ds-benign-light (UDP nhỏ + icmp-ping + dns-query),
  ds-flood-udp, ds-flood-proto (syn/icmp/dns), ds-flood-special (fanout), ds-mixed.

**⚠️ Confound quan trọng vừa phát hiện:** flood kích **traffic trả về** từ DN (TCP RST /
ICMP port-unreachable / ICMP echo-reply) → DL nhỏ nhưng **có hệ thống**; benign UDP UL
gần như **0 DL**; benign TCP bulk có DL ACK. ⇒ DL byte-rate tương quan với nhãn vì lý do
**phụ** (phản ứng của victim), không phải traffic của chính attack. Đây là nghi phạm số 1
cho việc `bytes-only` tách lớp ~0.99 dù UL throughput chỉ tách 0.83.

---

## 5. Gán nhãn & join

- **Nhãn theo (phase, UE):** MALICIOUS nếu UE đó chạy flow có `attack:<family>` trong
  phase đó (đọc từ `traffic/flows.json`); ngược lại BENIGN. **Ground truth = điều khiển
  thực nghiệm, KHÔNG suy từ volume/PRB.** Hàng ngoài mọi phase (warmup/tail) bị drop.
- **Granularity hàng: per-giây** (mỗi KPM sample = 1 hàng có nhãn). **Không** gán theo
  session, **không** cửa sổ cố định. "Session" = `(campaign, run, supi)`.
- **Join KPM↔URR↔profiler:** KPM là đồng hồ per-giây; giây = `collect_us` làm tròn. URR và
  profiler match theo **đúng giây đó, lệch ±1 s** làm stand-in (chúng đến trễ 1–2 s, được
  backfill — `features.c` `core_usage`/`core_profile`/`features_fill_urr`). Khớp theo UE
  qua `amf_ue_ngap_id → SUPI`.
- **Loại leakage:** output quyết định của xApp (`class, limit_*, level, limited,
  core_action, urr_at_decision`) **không** vào X.
- **Split:** `StratifiedGroupKFold` theo `(campaign, run, supi)` — không session nào nằm cả
  train lẫn test.

---

## 6. Mục tiêu paper

- **Claim chính:** một detector **cross-domain** (RAN KPM per-UE PRB + core PFCP/URR + UPF
  behavioural profiler) phân biệt **flooding user-plane độc hại** với **tải cao hợp pháp**
  — tức KHÔNG chỉ học volume. Claim phụ: kiến trúc hai lớp xApp (não) + eBPF-UPF (cơ bắp),
  detection→mitigation vòng kín qua A1-EI/E2SM-RC.
- **Trạng thái bằng chứng hôm nay:** trên trục đã match (UL throughput) volume **yếu**
  (AUC 0.83 trong dải va chạm), behaviour mạnh (mean_bytes 0.98, pps 0.93) → **ủng hộ
  claim**. NHƯNG `bytes-only` naive đạt ~0.99 do **confound** (DL return-traffic bất đối
  xứng; benign/malicious sinh bằng tool khác nhau; chỉ match offered UL rate). Model có thể
  tách lớp vì lý do sai.
- **Thay đổi testbed còn khả thi trước deadline** *(cần bổ sung cụ thể theo deadline của
  mày)*:
  - Diệt confound DL: chặn/bỏ feature DL return, hoặc làm im traffic phản hồi, hoặc thêm
    benign có DL tương đương.
  - Match chặt hơn: benign gói-nhỏ-pps-cao + flood gói-lớn **trong cùng band**; cân nhắc
    bỏ hàng idle.
  - Thống nhất công cụ sinh (giảm chữ ký tool iperf2 vs hping3).
  - Hạ guard mapping/URR xuống mức-rep (đang mất vài rep khi NGAP churn).
  - (tuỳ) bring-up ue3/ue4 cho đa dạng UE.

**[Mày điền]:** venue + deadline + phạm vi thay đổi được phép (chỉ phân tích lại, hay cho
sinh lại dữ liệu / đổi generator / đổi profiler).

---

### Phụ lục: kết quả ablation v3 (StratifiedGroupKFold, F1 / AUC, positive=MALICIOUS)

Trong dải va chạm UL [440,560) kbps (benign p50 453, malicious p50 486): `thp_ul` đơn
biến AUC **0.834**; `UL pps` 0.926; `mean_bytes UL` 0.984; **`DL bytes` 0.989 (nghi
confound)**; `UL bytes (4 đo)` 0.988. Full test: mọi ablation F1 0.94–0.99; LSTM full
0.992, bytes-only 0.975. Chi tiết: `research/datasets/oran_flooding_v3/reports/
model_eval.md` và `model_eval_lstm.md`.
