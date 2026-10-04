# Session handoff — đọc file này trước tiên

**Cập nhật:** 04/10/2026. Phase 0, A, C và R1 đã xong; việc tiếp theo là **R2**. Đọc hết file này (ngắn); chỉ mở tài liệu khác **đúng mục cần**. Khi kết thúc một phiên, cập nhật mục 3, 4, 5.

## 1. Hệ thống trong 6 dòng

- Testbed O-RAN + 5G SA trên minikube `oai-lab`, 4 namespace: `oai-core` (OAI 5GC + eBPF UPF XDP-SKB + DN), `oai-ran` (gNB + **2 UE** RFsim), `near-rt-ric` (FlexRIC + KPM xApp + A1-EI adapter), `non-rt-ric` (ICS + URR producer).
- Đường dữ liệu chạy: URR từ eBPF UPF → SMF → producer → ICS → adapter → **xApp** (1 report/s/UE, đúng chuẩn "lượng dùng kể từ report trước"); KPM gNB → FlexRIC → **xApp**; xApp gắn **SUPI** vào từng dòng KPM (R1).
- Đề tài: **phòng thủ hai lớp** chống UE flooding/DDoS, kể cả khi KPM bị MITM sửa trên E2. Lớp 1 RAN (xApp + E2 control), lớp 2 core (eBPF UPF).
- **xApp là bộ não duy nhất**; eBPF UPF là cảm biến + bộ nhớ UE theo SUPI (BPF map pinned) + thực thi (stage XDP mới) + phản xạ guard quota. Không thêm module ra quyết định vào core.
- Core chỉ dùng thủ tục chuẩn (PFCP User ID IE, URR cấu hình được, TTL session T1/T2/T3) cộng các bản sửa lỗi OAI có sẵn (C01–C28). Hai tầng state: trí nhớ theo SUPI (tầng 1) vs map theo session phải dọn sạch (tầng 2, đã kiểm chứng sạch).
- **Hệ thống mới quan sát và đối chiếu được, chưa tự chặn**: chưa có hành động RAN (R2), chưa có stage chặn trong UPF (U, G), chưa có bộ não escalation (L).

## 2. Bản đồ tài liệu (mở đúng chỗ cần)

| Cần gì | Mở |
|---|---|
| Lý thuyết đã chốt, lý do, phương án bị loại, tham số | `docs/TWO-LAYER-DEFENSE-DESIGN.md` (3 nguyên tắc, 4 hai tầng state + 4.1 TTL, 5 kiến trúc, 6 escalation + **6.1 tham số**, **7 mô hình nhất quán KPM↔URR**, **8 giới hạn/lệch chuẩn**, 9 nhật ký quyết định) |
| Phase, gate, kết quả | `docs/TWO-LAYER-DEFENSE-PLAN.md` (3 phase, 5 việc làm ngay, kết quả: 6 Phase 0, 7–9 A.1–A.5, 10 A.6/C/A.8, 11 A.7, **12 R1**) |
| **Mọi thay đổi so với upstream OAI (C01–C28)** | `docs/OAI-UPSTREAM-CHANGES.md`; kiểm chứng `scripts/verify-oai-upstream.sh` (phải 5/5 MATCH) |
| Bằng chứng từng gate | `artifacts/k8s/diagnostics/{orphan-a3-20261001, epoch-a4-20261001, ttl-a8-20261003, calib-a7-20261003, r1-20261003}/` |
| Vận hành stack 4 namespace | `docs/K8S-A1-EI.md` (mục "Triển khai tuần tự") + mục 6, 7 file này |
| Sự cố khôi phục cluster 01/10 | `artifacts/k8s/diagnostics/recover-20261001/README.md` |
| Lỗi thời, chưa cập nhật | `docs/TESTBED-STATUS.md`; plan mục 1 "Lịch sử tài liệu" và mục 2 "Hiện trạng code" (vẫn ghi SMF chưa gửi User ID) |
| **Không đọc** trừ khi bắt buộc | `docs/context.md` (319 KB lịch sử cũ); log UPF/SMF thô (dòng JSON rất dài — luôn `grep -v '^ {'`) |

## 3. Trạng thái hiện tại (04/10/2026)

- Cluster chạy đủ 4 namespace, 2 UE: `oai-nr-ue` (IMSI `001010123456780`, IP 10.1.0.3) và `oai-nr-ue2` (IMSI + 1, IP 10.1.0.2). Run `20261003T164156Z-m35` (capture PFCP của run này chưa bật — trước `experiment` phải chạy chuỗi ở mục 6).
- Image (lock `artifacts/k8s/state/images.{json,yaml}`, `ei-images.json`, `xapp-image.json`; bản trước `*.bak-r1-20261003`): SMF `oai-lab-smf:v2.2.0-lab-e2aa7c54`, UPF `oai-lab-upf:ttl-afdf292e9d3a`, radio (gNB/UE/FlexRIC) `oai-lab-radio:bf98ff282ed25e3f`, tools `oai-lab-tools:r1-1a8c19404f3d`, producer `oai-lab-urr-ei-producer:b98232e86a28f2a5`, adapter `oai-lab-a1-ei-adapter:3ef4b8571b1a3f4d`, xApp `oai-lab-xapp:83dd0681a6a4691b`.
- Cấu hình phòng thủ trong `deploy/k8s/values/minikube.yaml` → `global.lab.defense` (TTL 60/120 s, PERIO 1 s, User ID bật, guard **tắt** tới Phase G, keep-alive UE 20 s) và `extraUes`/`extraUeReplicas` (UE2).
- Hạ tầng: DNS Docker đã sửa (bỏ `dns` trong `/etc/docker/daemon.json`); release cũ `oai-lab` đã khôi phục điểm rollback (`helm rollback oai-lab 105`, mọi workload replicas 0); swap 16 GB; Multus limit 300Mi.
- Repo: https://github.com/ducsssanh/Thesis-O-RAN-Testbed (public, `main`). Commit chỉ mang tên `ducsssanh` — **không thêm dòng `Co-Authored-By`**. Cây OAI/FlexRIC trong `src/` không commit; clone mới chạy `scripts/verify-oai-upstream.sh --into src`. Nhánh local `backup-before-trailer-removal` (lịch sử cũ) có thể xóa.

## 4. Đã xong (theo mốc thời gian)

| Mốc | Việc | Kết quả / bằng chứng |
|---|---|---|
| 30/09 | Phase 0: PFCP Update FAR → BPF map → XDP DROP | PASS (UL/DL 1050 kbps → 0 → 1050), plan mục 6 |
| 01/10 | A.1 route UE tự sửa; A.2 dọn BPF map khi xóa session (3 lỗi UPF); A.5 Update FAR giữ Apply Action | plan mục 7, `teardown-final-20261001` |
| 01/10 | A.3 session mồ côi (SMF gửi N4 Deletion cho session cũ) | gnb×3 + ue×3 PASS, `orphan-a3-20261001` |
| 01/10 | A.4 session epoch (khóa `SEID, epoch, UR-SEQN`); watchdog KPM | 26/26 report sau restart SMF, `epoch-a4-20261001` |
| 02/10 | GitHub; dựng lại upstream byte-exact (`verify-oai-upstream.sh --into`, so sánh nghiêm ngặt) | thử trên clone sạch + cache rỗng: diff 0 |
| 03/10 | **Phase C** (User ID IE) + **A.6** (URR từ cấu hình, PERIO 1 s) + **A.8** (TTL T1/T2/T3) + FlexRIC EINTR | Gate C, URR 1 s, TTL 3 kịch bản PASS, `ttl-a8-20261003`, plan mục 10 |
| 03/10 | Lỗi OAI có sẵn tìm ra khi kiểm chứng: C24 SMF mất FTUP khi UPF re-associate (mất toàn bộ UL); C25 URR lũy kế + report PERIO trễ khi UE im lặng | đã sửa, kiểm chứng |
| 03/10 | **A.7** hiệu chỉnh URR↔KPM + đo tải A.6 | mô hình `KPM ≈ URR − c·pkts` (c_UL 16,3, c_DL 57,3 B); ε DL 0,02 @1 s, UL 0,15 ×2 cửa sổ @2 s, FPR 0; tải ≈ 2,7% core/UE; `calib-a7-20261003`, plan mục 11 |
| 03/10 | **Gate A** đạt (1 UE) | map sạch qua attach/detach, URR 1 s, bảng hiệu chỉnh |
| 03–04/10 | **R1** ánh xạ KPM UE ID ↔ SUPI với 2 UE: producer đọc bảng UE của AMF (Non-RT) → `ran_identity` trong URR → xApp gắn SUPI + timestamp gốc vào KPM; SMF chuyển Start/End Time (C26) | **Gate R1 PASS**: 68/68 dòng KPM đúng SUPI, URR 35/35 đúng `ran_identity`, volume theo SUPI lệch ≤ 5% (đảo thì 77–297%); `r1-20261003`, plan mục 12 |
| 04/10 | Lỗi OAI có sẵn: C27 bộ đếm KPM của gNB theo vị trí UE (volume tráo giữa UE, tràn 2³²) | đã sửa, thử UE vào/ra giữa lúc có traffic |
| 02–04/10 | Harness: gate `pfcp_peer_ready` chấp nhận re-association; container capture có `CAP_KILL`; payload iperf cấu hình được; analyzer chấp nhận URR chỉ PERIO; UE2 trong chart | unit test 25 + 19 OK |

**Quyết định của tác giả còn hiệu lực:** L-XAI (LSTM có giải thích + LLM phân tích nguồn gốc) **để ngoài plan**; căn chỉnh KPM↔URR theo cửa sổ để trong xApp, việc hiệu chỉnh tham số có thể đưa lên rApp Non-RT sau; giới hạn "ánh xạ đọc từ log AMF OAI, không chuẩn" đã ghi ở design mục 8 (khóa nối GUAMI + AMF-UE-NGAP-ID là chuẩn, bước tra cứu sang SUPI thì không).

## 5. Việc tiếp theo (theo thứ tự)

1. **R2 — hành động RAN thật trong gNB** (plan mục 3, Phase R2):
   - Giới hạn PRB/MCS theo UE trong scheduler DL/UL (`gNB_scheduler_{dl,ul}sch_default_policies.c` trong `src/oai-ran/openair2/LAYER2/NR_MAC_gNB/`).
   - RRC Release UE chỉ định (`rrc_gNB_generate_RRCRelease` ở `openair2/RRC/NR/rrc_gNB.c`) hoặc NGAP UE Context Release Request.
   - Nhận lệnh qua E2SM-RC control: thay handler stub `write_ctrl_rc_sm` ở `src/oai-ran/openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c:875`; ưu tiên style chuẩn (Style 2 cho PRB), thiếu encoder thì dùng action ID riêng và ghi rõ. Cần kiểm tra FlexRIC xApp có gửi được RC control (xApp mẫu `examples/xApp/c/kpm_rc`).
   - Patch `patches/oai-ran-e2-rc-enforcement.patch` + mục C29; image radio mới.
   - **Gate R2:** PRB cap làm throughput UE bị giới hạn giảm đúng mức, **UE kia không bị ảnh hưởng** (đã có 2 UE); Release đưa UE ra khỏi RRC_CONNECTED. Định danh UE trong lệnh RC = UE ID E2 (AMF-UE-NGAP-ID + GUAMI), xApp tra từ SUPI qua bảng R1.
2. **R3 — lớp RAN chạy độc lập:** detector KPM theo UE (dùng cột SUPI + kiểm tra nhất quán A.7), DB danh tiếng SQLite, escalation phần RAN. Gate R3: flood → PRB cap ≤ 2 s → cell phục hồi cho UE khác.
3. Sau đó theo plan: **U** (stage `PROG_SEC_POLICY` + map theo SUPI + UPF Security API) → **G** (guard quota theo cửa sổ, rồi bật `urr.guard.enabled`) → **M** (công cụ tấn công) → **L** (bộ não, fusion) → **E** (nghiệm thu).
4. Việc nhỏ / nợ kỹ thuật:
   - Harness: `up --stage ran` chưa biết UE2; `new-run` không báo lỗi khi UE còn chạy (gây dùng lại run ID); `rollout` dùng `--reuse-values` (mục 7).
   - FlexRIC kẹt sau gNB/SMF restart (KPM stale, xApp assert subscription timeout) — hiện xử lý tay (mục 6).
   - Kiểm chứng lại ε của A.7 với 2 UE (dữ liệu R1 đã có: lệch 3–5% ở tổng 40 s).
   - Đo CPU producer/adapter trong `calib_sweep.sh` bằng `crictl stats`; cập nhật `TESTBED-STATUS.md` và plan mục 1–2.

## 6. Runbook (lệnh đúng, đã kiểm chứng)

```bash
cd /home/ducsssanh/6G/O-RAN/DATN/Codebase
K="kubectl --context oai-lab"           # luôn --context; trong zsh dùng bash -c '...' khi K chứa lệnh
# Sau minikube start / reboot
minikube start -p oai-lab && scripts/k8s/coredns-search-guard.sh
# Stack 4 namespace (KHÔNG chạy `lab.sh up` thiếu --stage: nó đụng release cũ oai-lab)
scripts/k8s/lab.sh new-run              # UE phải ở 0 replica
scripts/k8s/lab.sh up --stage core      # rồi: up --stage nonrt; up --stage near-rt; gate-ei; up --stage ran
#   gate core "PFCP association timed out" ngay sau khi thay UPF: chạy lại lệnh (đã sửa gate, có thể vẫn cần 1 lần nữa)
scripts/k8s/lab.sh experiment           # traffic thật + analyzer (1 UE)
# Bật UE2 (sau up --stage ran), rồi restart xApp KHI CẢ HAI UE ĐÃ CÓ IP
bash -c 'cd scripts/k8s && python3 -c "import staged as s; s.release(\"ran\",[\"replicas=1\",\"oai-gnb.enabled=true\",\"oai-nr-ue.enabled=true\",\"oai-nr-ue2.enabled=true\",\"global.lab.extraUeReplicas=1\"])"'
$K -n near-rt-ric rollout restart deploy/oai-lab-xapp
# FlexRIC kẹt (xApp crash "Timeout waiting for subscription"): restart flexric → gnb → 2 UE → (chờ IP) → xApp
# Gate / đo
python3 scripts/k8s/phase0/r1_gate.py <out> 40              # Gate R1 (2 UE)
scripts/k8s/phase0/ttl_gate.sh <out> lost|idle|smf           # Gate A.8 (lost: sau đó up --stage ran)
scripts/k8s/phase0/orphan_cycle.sh <out> 3 ue|gnb            # hồi quy A.3
scripts/k8s/phase0/calib_sweep.sh <list> 1M:100 10M:1200 ... # A.7: experiment theo profile + CPU
python3 scripts/k8s/calibrate.py <out> $(cat <list>)          # A.7: c, ε, FPR
LAB_EXPERIMENT_RATE=5M LAB_EXPERIMENT_LENGTH=400 scripts/k8s/lab.sh experiment   # đổi profile 1 lần
# Build (tag theo quy ước; xem lab.py build/fingerprint)
#   SMF (~10 phút, tag = v2.2.0-lab-<hash các patch SMF>, danh sách patch trong lab.py):
#     cd src/oai-smf && docker build -f docker/Dockerfile.smf.ubuntu --target oai-smf --build-arg BUILD_CPUSET=0-7 --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t oai-lab-smf:<tag> .
#   UPF (~6 phút): docker build -f src/oai-upf/docker/Dockerfile.upf.ubuntu --target oai-upf --build-arg BUILD_CPUSET=0-5 --build-arg GIT_COMMIT=<tag> -t oai-lab-upf:<tag> src/oai-upf
#   radio (gNB/UE/FlexRIC, ~11 phút): docker build -f deploy/k8s/images/Dockerfile.radio --target radio -t oai-lab-radio:<fingerprint16> .
#   tools: docker build -f deploy/k8s/images/Dockerfile.tools -t oai-lab-tools:<tag> .
#   producer/adapter/xApp: scripts/k8s/lab.sh build-ei && scripts/k8s/lab.sh build-xapp
# Rollout (UE ở 0): lab.sh rollout upf|smf|xapp|adapter|producer <image>  — thứ tự EI: xapp → adapter → producer
#   Đổi radio/tools/currentRun/adapter.allUes: cập nhật images.{json,yaml} rồi dùng staged.release() hoặc helm --set (mục 7)
# Quan sát
scripts/k8s/phase0/bpftool.sh map show | grep rules_match_pdr
scripts/k8s/phase0/watchmap.sh 60
scripts/verify-oai-upstream.sh          # phải 5/5 MATCH sau mọi thay đổi OAI
$K -n oai-core logs deploy/oai-upf | grep -v '^ {' | grep -E 'N4_SESSION|RemovePipeline|PFCP session established|Inactivity'
$K -n oai-core logs deploy/oai-amf -c amf --since=60s | grep -A6 "UEs' Information"   # bảng UE ↔ AMF-UE-NGAP-ID
```

## 7. Bẫy đã gặp (đừng lặp lại)

- Shell là **zsh**: `$K` chứa lệnh không tự tách từ (lỗi "command not found", kể cả trong Monitor); định nghĩa `k(){…}` lỗi vì alias. Dùng `bash -c '…'`.
- `pgrep -f '<chuỗi>'` khớp luôn dòng lệnh đang chứa chuỗi đó ⇒ vòng chờ treo vĩnh viễn. Chờ bằng file/log hoặc PID.
- **`lab.sh rollout` dùng `--reuse-values`**: giá trị mặc định mới của chart và overlay `images.yaml` (toolsImage, radio, `adapter.allUes`, `global.lab.currentRun`) **không** được áp. `up --stage core` cũng **không** đẩy image mới khi NF đã chạy. Dùng `staged.release(role, sets)` (đọc `-f minikube.yaml -f images.yaml`) hoặc `--set` tường minh, rồi kiểm tra image/env thật bằng `kubectl get deploy -o jsonpath`.
- Job `oai-lab-subscriber` bất biến: muốn seed lại (thêm UE) phải `kubectl delete job` rồi `release("core", [..., "seedEnabled=true", ...])`.
- xApp chỉ chụp danh sách UE khi đăng ký KPM: sau khi gNB/UE restart phải restart xApp **sau khi** mọi UE có IP. Bảng UE của AMF in ~20 s/lần ⇒ SUPI có thể trống tới ~20 s sau khi UE đăng ký.
- gNB còn giữ context cũ (UE ID của lần đăng ký trước, volume 0) vài giây sau khi UE đăng ký lại; dòng KPM của chúng không có SUPI — đúng hành vi.
- **Không có sudo không mật khẩu**; lệnh sudo để tác giả chạy ở terminal riêng.
- `/tmp` (scratchpad) bị xóa khi reboot — script hữu ích phải nằm trong repo.
- Route `172.30.26.0/24 dev oaitun_ue1` mất khi pod UE restart (harness tự sửa cho UE1; test tay thì `ip route replace` hoặc `iperf -B <ue-ip>`).
- Không dùng `kubectl rollout restart deployment/oai-upf` (N4 IP tĩnh) — dùng `lab.sh rollout upf` / `restart-upf`. `rollout smf` cũng restart UPF ⇒ dừng UE trước.
- `minikube start` có thể ghi đè ConfigMap CoreDNS ⇒ chạy lại guard.
- Mọi thay đổi code OAI mới phải có file patch + mục C-số trong `docs/OAI-UPSTREAM-CHANGES.md` + đăng ký trong `verify-oai-upstream.sh` (và `lab.py` nếu là patch SMF) + 5/5 MATCH. Patch xếp chồng: tạo diff từ cây `verify-oai-upstream.sh --into <dir>` mới nhất.
- Build song song nhiều image dễ làm host OOM — build tuần tự, giới hạn `BUILD_CPUSET`.
- Commit: không thêm `Co-Authored-By: Claude` (tác giả yêu cầu, lịch sử đã viết lại 03/10).

## 8. Mẹo tiết kiệm context cho session mới

- Bắt đầu bằng: "Đọc `docs/SESSION-HANDOFF.md`, làm việc #N ở mục 5." Không cần dán lại lịch sử.
- Chỉ mở file thiết kế/plan theo số mục ở bảng mục 2.
- Khi đọc log, luôn lọc (`grep -v '^ {'`, `--since=`, `tail`); khi đọc code, đọc theo dòng (`sed -n a,bp`).
- Ghi kết quả mới vào plan (mục 13 trở đi) và cập nhật mục 3–5 của file này trước khi kết thúc phiên.
