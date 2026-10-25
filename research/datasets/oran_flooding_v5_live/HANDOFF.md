# HANDOFF — v5 live (stage B: cross-domain defence ON), cập nhật 2026-10-25 — MAIN CAMPAIGN XONG (224/224)

## 0. Quy tắc làm việc (bắt buộc)
Commit chỉ tên ducsssanh, không push; `kubectl --context oai-lab`; lệnh sudo đưa cho user; không xoá dữ liệu
(raw v1–v5 giữ nguyên); không retune trên dữ liệu main; mọi thay đổi sau pre-registration ghi vào `PREREGISTRATION.md`.

## 1. Trạng thái
- Gate A (pilot 42/42) và main campaign (224/224 valid, 30 attempt hỏng đã chạy lại) xong. Defence đang OFF, testbed idle.
- Kết quả chính: `reports/live_results_v5.md` (clean units); bản đúng như pre-register: `reports/live_eval_v5.md`.
- Hình: `reports/figures/fig_{a,b,c}*.{pdf,png}` (clean units). Datasheet: `DATASHEET.md`.

## 2. Pipeline phân tích (chạy lại theo thứ tự)
1. `scripts/ml/live_eval_v5.py --manifest research/datasets/oran_flooding_v5_live/manifest/design.json <camps main>`
   (camps = `artifacts/experiments/*_v5live_main_s*`) → live_eval_v5.{md,json}, live_units_v5.csv
2. `scripts/ml/carryover_v5.py` → live_units_v5_carryover.csv, carryover_v5.csv
3. `scripts/ml/loop_latency_v5.py` → loop_latency_v5.json
4. `scripts/ml/live_extra_v5.py` → live_results_v5.{md,json} (bảng chính, A icmp, B core outage L1/L3, C kpm_hide
   thời gian tới block + bytes DN, D sensitivity, E carry-over, F failures, G latency, I L3 quyết định vs thi hành,
   J replay vs live, H giả thuyết)
5. `scripts/ml/figures_v5.py --eval research/datasets/oran_flooding_v5_live/reports --run <run kpm_hide ×0.1 trust-v2>`
   (đã dùng `artifacts/experiments/20261024-164959_v5live_main_s1/runs/xd-trust-v2/rep-41`)

## 3. Sự cố trong campaign và đã xử lý thế nào (chi tiết: PREREGISTRATION "Main campaign, tooling fix 1–5")
- QA dừng supervisor 3 lần vì rule quá chặt (chunk nhỏ, fallback trong gap, fallback lẻ) → nới thành chỉ dừng khi lỗi
  nghiêm trọng (residual, KPM cũ, sidecar p99 > 200 ms, < 50 % valid, recovery fail).
- Recovery fail 1 lần (03:25, xApp↔FlexRIC E42 kẹt association SCTP cũ) → supervisor giờ chạy recover_ran.sh thêm 1 lần.
- Testbed: UE radio-link failure → PDU session không kích hoạt lại → SMF TTL release 120 s; mất PFCP; xApp container
  restart. Tần suất 30–90 phút/lần khi máy tải cao (load 12–16/18 core).

## 4. Phát hiện sau campaign (đã ghi deviation)
- **L3 carry-over:** reset ở gap bị sidecar ghi đè (~0.1 s sau) → UE vào phase sau đang bị block. 63/1536 phase; trust-v2 = 0.
  Xử lý bằng loại phase khỏi phân tích chính (user chọn, không rerun). Sửa cho lần sau: reset level lần 2 sau câu trả lời
  đầu tiên của sidecar sau phase, hoặc reset L3 hold của sidecar theo UE ở gap.
- **L3 ≠ block thật:** UPF maxBlockedRatio 0.5 từ chối block UE thứ 2 (403).
- Run 11 (batch 1, failed) là do carry-over, không phải mất PDU session như log ban đầu.

## 5. Việc còn lại
- Viết chương kết quả thesis + paper từ `live_results_v5.md` (đề xuất hình: paper 5 hình + 2–3 bảng, thesis thêm sơ đồ
  kiến trúc/sequence/state machine; code Mermaid ở `reports/figures/mermaid/`).
- (Tuỳ chọn) chạy lại các config bị carry-over với harness đã sửa để kiểm tra chéo.
- Cập nhật `docs/SESSION-HANDOFF.md` (đã thêm con trỏ tới file này).
