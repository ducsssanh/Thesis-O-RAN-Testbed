# Session handoff — đọc file này trước tiên

**Cập nhật:** 03/10/2026 tối (A.6 tải + A.7 hiệu chỉnh xong ⇒ Gate A đạt cho 1 UE; C25 mở rộng: report PERIO theo chu kỳ).

## 1. Hệ thống trong 6 dòng

- Testbed O-RAN + 5G SA trên minikube `oai-lab`, 4 namespace: `oai-core` (OAI 5GC + eBPF UPF XDP-SKB + DN), `oai-ran` (gNB/UE RFsim), `near-rt-ric` (FlexRIC + KPM xApp + A1-EI adapter), `non-rt-ric` (ICS + URR producer).
- Đã chạy: URR thật từ eBPF UPF → SMF → producer → ICS → adapter → **xApp**; KPM từ gNB → FlexRIC → **xApp**.
- Đề tài: **phòng thủ hai lớp** chống UE flooding/DDoS, kể cả khi KPM bị MITM sửa trên E2. Lớp 1 RAN (xApp + E2 control, làm trước), lớp 2 core (eBPF UPF).
- **xApp là bộ não duy nhất**; eBPF UPF là cảm biến + bộ nhớ UE theo SUPI (BPF map pinned) + thực thi (stage XDP mới) + phản xạ guard quota. Không thêm module ra quyết định vào core.
- SMF chỉ thay đổi chuẩn (PFCP User ID IE + cấu hình URR). Hai tầng state: trí nhớ theo SUPI (tầng 1) vs map theo session phải dọn sạch (tầng 2).
- Closed loop **chưa triển khai**; đang ở Phase A (nền tảng).

## 2. Bản đồ tài liệu (mở đúng chỗ cần)

| Cần gì | Mở |
|---|---|
| Lý thuyết đã chốt, lý do, phương án bị loại, tham số | `docs/TWO-LAYER-DEFENSE-DESIGN.md` (mục 3 nguyên tắc, 4 hai tầng state, 5 kiến trúc, 6 escalation + 6.1 tham số, 9 nhật ký quyết định) |
| Phase, gate, việc tiếp theo, kết quả | `docs/TWO-LAYER-DEFENSE-PLAN.md` (mục 3 phase, 5 việc làm ngay, 6–9 kết quả) |
| Trạng thái testbed tổng quát | `docs/TESTBED-STATUS.md` |
| Vận hành stack 4 namespace | `docs/K8S-A1-EI.md` (mục "Triển khai tuần tự") |
| **Mọi thay đổi so với upstream OAI, theo mốc thời gian** | `docs/OAI-UPSTREAM-CHANGES.md`; kiểm chứng: `scripts/verify-oai-upstream.sh` (phải MATCH) |
| Chi tiết file patch cũ | `docs/LOCAL-PATCHES.md` |
| Thiết kế TTL session (T1/T2/T3) | `docs/TWO-LAYER-DEFENSE-DESIGN.md` mục 4.1 |
| Sự cố khôi phục cluster 01/10 | `artifacts/k8s/diagnostics/recover-20261001/README.md` |
| **Không đọc** trừ khi bắt buộc | `docs/context.md` (319 KB, lịch sử cũ); log UPF/SMF thô (dòng JSON rất dài — luôn `grep -v '^ {'`) |

## 3. Trạng thái hiện tại

- Cluster chạy đủ 4 namespace; run hiện tại `20261003T114119Z-m35` (capture đã đóng sau gate ⇒ trước `experiment` phải: UE về 0, `new-run`, `up --stage ran`). UE IP 10.1.0.2, có sidecar keep-alive.
- Image (lock `artifacts/k8s/state/images.{json,yaml}`, bản trước `*.bak-ttl-20261003`): SMF `oai-lab-smf:v2.2.0-lab-838baa19`; UPF `oai-lab-upf:ttl-afdf292e9d3a`; radio `oai-lab-radio:faa627d484cce732`; tools `oai-lab-tools:30e854d39b1192d1`; xApp `oai-lab-xapp:e4b86a7522ad333c`; producer/adapter như cũ (`ei-images.json`).
- Cấu hình phòng thủ: `global.lab.defense` trong `deploy/k8s/values/minikube.yaml` (TTL 60/120 s, PERIO 1 s, User ID bật, guard tắt, keep-alive 20 s).
- Release cũ `oai-lab`: đã `helm rollback oai-lab 105`, 11 Deployment + DB/DN ở replicas 0 (điểm rollback khôi phục). Pod Job `oai-lab-subscriber` của rev 105 có thể còn trong namespace `oai-lab` — vô hại.
- DNS Docker đã sửa (bỏ `dns` trong `/etc/docker/daemon.json`). Host: swap 16 GB; CoreDNS guard chạy lại sau mỗi `minikube start`.
- Repo: https://github.com/ducsssanh/Thesis-O-RAN-Testbed (`main`); clone mới: `scripts/verify-oai-upstream.sh --into src`.

## 4. Đã xong

| Việc | Kết quả / bằng chứng |
|---|---|
| Phase 0: PFCP Update FAR → BPF map → XDP DROP | PASS: UL/DL 1050 kbps → 0 → 1050. `artifacts/experiments/20260930T073310Z-phase0-far`; hồi quy trên image mới `20261001T102111Z-phase0-far-teardown` |
| A.1 route UE tự sửa trong harness | `ensure_ue_route()` ở `scripts/k8s/staged.py` + `lab.py`; 6 unit test |
| A.2 dọn BPF map khi xóa session | Sửa 3 lỗi UPF (throw ENOENT, **layout key `rules_match_pdr` ngược**, sai danh sách PDR); 3/3 chu kỳ sạch. `patches/oai-upf-teardown-best-effort.patch`; `artifacts/k8s/diagnostics/teardown-final-20261001` |
| A.3 session mồ côi (gốc: gNB chết → AMF bỏ UE không Release SM Context → SMF va chạm PDU Session ID chỉ xóa cục bộ) | Sửa SMF gửi N4 Deletion cho session cũ. Baseline FAIL `[1 2 3]`; sau sửa gnb×3 + ue×3 PASS, mọi map 1 session. `patches/oai-smf-v2.2.0-stale-session-release.patch`; `artifacts/k8s/diagnostics/orphan-a3-20261001`; script `scripts/k8s/phase0/orphan_cycle.sh` |
| A.4 session epoch producer → adapter → xApp | Epoch = `smf_timestamp − Duration`; khóa `(SEID, epoch, UR-SEQN)`. SEID 1 tái sử dụng sau restart SMF: 26/26 report tới xApp. `artifacts/k8s/diagnostics/epoch-a4-20261001`; plan mục 9 |
| Độ bền KPM | Watchdog xApp (`KPM_STALE_S`) + harness tự restart FlexRIC khi kẹt + `experiment` dừng sớm nếu KPM cũ; kill gNB ⇒ KPM tự phục hồi |
| Thiết kế TTL session (thay cho sửa AMF) | Design mục 4.1: T1 SMF timer UP-deactivated, T2 IE 117/UPIR, T3 UPF purge khi SMF restart |
| Tài liệu thay đổi so với OAI | `docs/OAI-UPSTREAM-CHANGES.md` (C01–C18); dựng lại từ upstream: 5/5 MATCH; phát hiện + xuất 2 patch còn thiếu |
| A.5 Update FAR không có Apply Action giữ nguyên action | Kiểm chứng none/drop/none/forw |
| GitHub + dựng lại upstream byte-exact (02/10) | `verify-oai-upstream.sh --into`; so sánh nghiêm ngặt; thử trên clone sạch |
| A.7 hiệu chỉnh + tải A.6 (03/10) | Mô hình `KPM ≈ URR − c·pkts` (c 16,3/57,3 B), ε DL 0,02@1 s, UL 0,15×2@2 s, FPR 0; URR ≈ 2,7% core/UE. [`calib-a7-20261003`](../artifacts/k8s/diagnostics/calib-a7-20261003/README.md), plan mục 11 |
| A.6 + Phase C + A.8 + FlexRIC EINTR (02–03/10) | Gate C, URR 1 s, TTL 3 kịch bản PASS; sửa thêm C24 (SMF mất FTUP khi UPF re-associate), C25 (URR lũy kế). [`ttl-a8-20261003`](../artifacts/k8s/diagnostics/ttl-a8-20261003/README.md), plan mục 10 |
| Thiết kế hai lớp + tham số mặc định | `docs/TWO-LAYER-DEFENSE-DESIGN.md` |

## 5. Việc tiếp theo (theo thứ tự)

1. **R1** ánh xạ KPM UE ID ↔ SUPI với 2 UE (đường găng; cũng để kiểm chứng ε của A.7 với nhiều UE).
2. **R2** patch gNB: PRB cap + RRC Release qua E2SM-RC (handler stub ở `src/oai-ran/openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c:872`) → Gate R2.
3. **R3** xApp detector KPM + hành động RAN; sau đó U → G → M → L → E (theo plan).
4. Việc nhỏ: gate `pfcp_peer_ready` 90 s có lúc hết giờ khi UPF vừa thay; harness `new-run` không báo lỗi khi UE còn chạy (dẫn tới run ID bị dùng lại trong `calib_sweep.sh`).

**Quyết định đã chốt (02/10/2026, tác giả đồng ý cả 4):**
- Khôi phục điểm rollback `oai-lab`: làm sau khi restart Docker (stack 4 namespace về 0 → `helm rollback oai-lab 105` → scale release cũ về 0 → dựng lại stack).
- Sửa gốc DNS Docker: restart Docker **không** đủ (đã thử 02/10 16:34); gốc là `dns` cố định trong `daemon.json` (mục 3).
- Thiết kế TTL (design 4.1, `session_ttl.*` mục 6.1) được duyệt ⇒ triển khai A.8 cùng đợt A.6.
- Lỗi FlexRIC agent assert khi `epoll_wait` trả EINTR (`asio_agent.c:134`) đưa vào danh sách sửa (bỏ qua EINTR thay vì assert; cần patch + mục trong `OAI-UPSTREAM-CHANGES.md`).

**Repo:** https://github.com/ducsssanh/Thesis-O-RAN-Testbed (public, nhánh `main`). Cây upstream OAI/FlexRIC trong `src/` bị `.gitignore`; dựng lại bằng `scripts/verify-oai-upstream.sh`.

## 6. Runbook (lệnh đúng, đã kiểm chứng)

```bash
cd /home/ducsssanh/6G/O-RAN/DATN/Codebase
K="kubectl --context oai-lab"           # context mặc định của user trỏ cluster khác — luôn dùng --context
# Stack 4 namespace (KHÔNG chạy `lab.sh up` thiếu --stage: nó đụng release cũ oai-lab)
scripts/k8s/lab.sh new-run
scripts/k8s/lab.sh up --stage core      # rồi: up --stage nonrt; up --stage near-rt; gate-ei; up --stage ran
scripts/k8s/lab.sh experiment           # traffic thật + analyzer
# Sau mỗi minikube start / node reboot
scripts/k8s/coredns-search-guard.sh     # idempotent; thiếu nó NF không tới được NRF, PFCP association timeout
# Pod kẹt Unknown sau reboot: scale RAN + near-rt về 0, xóa pod Unknown, rồi chạy lại chuỗi stage
# Build + rollout UPF (giới hạn job, 18 job từng làm host OOM)
docker build -f src/oai-upf/docker/Dockerfile.upf.ubuntu --target oai-upf \
  --build-arg BUILD_CPUSET=0-5 --build-arg GIT_COMMIT=<tag> -t oai-lab-upf:<tag> src/oai-upf
#   cập nhật artifacts/k8s/state/images.{json,yaml} (mục upf + sourceHash = fingerprint 4 thư mục, xem lab.py fingerprint())
$K -n oai-ran scale deployment/oai-nr-ue --replicas=0
scripts/k8s/lab.sh rollout upf oai-lab-upf:<tag> && scripts/k8s/lab.sh new-run && scripts/k8s/lab.sh up --stage ran
# Đọc/quan sát BPF map (host không có sudo; dùng docker privileged read-only)
scripts/k8s/phase0/bpftool.sh map show | grep rules_match_pdr
scripts/k8s/phase0/watchmap.sh 60       # in (seid,pdr) mỗi khi map đổi
scripts/k8s/phase0/orphan_cycle.sh <out> 3 ue|gnb   # kill UE (hoặc gNB+UE) N lần, PASS nếu map chỉ còn session sống
scripts/k8s/phase0/ttl_gate.sh <out> lost|idle|smf   # gate TTL A.8 (lost: sau đó `up --stage ran`)
scripts/verify-oai-upstream.sh          # dựng lại cây OAI từ upstream + patches/, phải MATCH (~4 phút)
scripts/k8s/lab.sh build-ei && scripts/k8s/lab.sh build-xapp   # rồi rollout xapp → adapter → producer (UE ở 0)
# PFCP Update FAR thử nghiệm (bỏ qua SMF — luôn trả về forw sau đó)
$K -n oai-core exec -i deploy/oai-smf -c capture -- python3 - --upf 172.30.24.20 --src 172.30.24.10 \
  --seid <n> --far 1 --far 2 --action drop|forw|none < scripts/k8s/phase0/pfcp_far_probe.py
scripts/k8s/phase0/run.sh <out-dir> <seid> <ue-ip>   # Phase 0 đầy đủ có traffic
# Log gọn
$K -n oai-core logs deploy/oai-upf | grep -v '^ {' | grep -E 'N4_SESSION|RemovePipeline|swept'
```

## 7. Bẫy đã gặp (đừng lặp lại)

- Shell là **zsh**: `$VAR` chứa lệnh không tự tách từ; định nghĩa `k(){…}` lỗi vì alias. Dùng `bash -c '…'` hoặc script wrapper.
- **Không có sudo không mật khẩu** trên host; lệnh cần sudo phải để user chạy ở terminal riêng (`!` trong Claude Code không nhập được mật khẩu).
- `/tmp` (scratchpad) bị xóa khi reboot — script hữu ích phải nằm trong repo.
- Route `172.30.26.0/24 dev oaitun_ue1` mất khi pod UE restart (harness đã tự sửa; khi test tay thì gọi lại hoặc dùng `iperf -B <ue-ip>`).
- Xóa pod: `kubectl delete pod/<name>` (không thêm chữ `pod` khi đã dùng dạng `pod/<name>`).
- Không dùng `kubectl rollout restart deployment/oai-upf` (N4 IP tĩnh ⇒ SMF mất UPF) — dùng `lab.sh rollout upf` / `restart-upf`.
- Build UPF: không đổi source khi đang build; mỗi lần đổi source tag đổi theo fingerprint.
- `minikube start` có thể ghi đè ConfigMap CoreDNS ⇒ chạy lại guard.
- Kill/restart gNB: xApp tự thoát và đăng ký lại KPM (watchdog). Nếu FlexRIC log lặp `MSG ALREADY PENDING` thì RIC đã kẹt: xApp crash-loop, `experiment` báo "KPM is stale" ⇒ scale UE 0, `new-run`, `up --stage ran` (tự restart RIC + gNB).
- Mọi thay đổi code OAI mới phải có file patch + mục trong `docs/OAI-UPSTREAM-CHANGES.md` + `verify-oai-upstream.sh` MATCH.
- `lab.sh rollout smf` cũng làm pod UPF khởi động lại (helm upgrade chart core) ⇒ dừng UE trước.
- Build SMF: `docker build -f docker/Dockerfile.smf.ubuntu --target oai-smf --build-arg BUILD_CPUSET=0-7 --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t oai-lab-smf:<tag> .` trong `src/oai-smf` (~11 phút, base layer có cache nên không cần DNS ngoài).

## 8. Mẹo tiết kiệm context cho session mới

- Bắt đầu bằng: "Đọc `docs/SESSION-HANDOFF.md`, làm việc #N ở mục 5." Không cần dán lại lịch sử.
- Chỉ mở file thiết kế/plan theo số mục ở bảng mục 2.
- Khi đọc log, luôn lọc (`grep -v '^ {'`, `--since=`, `tail`); khi đọc code, đọc theo dòng (`sed -n a,bp`) thay vì cả file.
- Ghi kết quả mới vào plan (mục 7 trở đi) và cập nhật mục 3–5 của file này trước khi kết thúc phiên.
