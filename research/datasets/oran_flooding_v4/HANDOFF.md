# HANDOFF — dataset v4 (flooding vs legitimate high-load), 2026-10-21

## 1. Mục tiêu & phạm vi
- Sinh dữ liệu có nhãn từ testbed OAI 5G (gNB + 2 NR-UE RFsim, OAI 5GC, FlexRIC, URR, eBPF UPF profiler),
  tách flooding khỏi tải cao hợp lệ; detection/mitigation TẮT khi thu.
- Spec gốc: "PROMPT: Xây dựng pipeline sinh dữ liệu v4" (§0–10). **File `prompt_v4_datagen.md` KHÔNG có trong repo**
  (đã tìm); spec chỉ nằm trong hội thoại. Nên commit bản spec vào repo.
- Chi tiết kỹ thuật: `docs/SESSION-HANDOFF-V4.md` (gitignored), `research/testbed/phase0_v4.md`.

## 2. Trạng thái hiện tại
- Code/manifest commit: `2889d05` (trên `8760c4d`). Tác giả ducsssanh, không co-author.
- Manifest: 88 run / 528 phase (`manifest/design.json`, seed 20261020, checkpoint [8, 42]). Run 84–88 là both-attack.
- **Đã thu 42/88 run, 42 run có `meta_run_ok=1`, 0 run lỗi trong batch 2c.** Camp dirs (gitignored, `artifacts/experiments/`):
  `20261020-232552_v4campaign_batch1c` (rep 1–8), `20261021-093244_v4campaign_batch2` (rep 9),
  `20261021-102436_v4campaign_batch2b` (rep 10 FAILED, giữ lại, `error.txt`), `20261021-102738_v4campaign_batch2c` (rep 10–42).
  Còn `20261020-213040_v4campaign_batch1` và `…214714_v4campaign_batch1b` (chưa kiểm vai trò; `package_v4` sẽ liệt kê trong `runs_index`).
- Chưa có `research/datasets/oran_flooding_v4/{raw,rows.parquet,qa_report.md,calibration.md,DATASHEET.md}`;
  chỉ có `manifest/`. Dữ liệu tạm tới run 42: `…batch2c/dataset_sofar/rows.parquet`.
- Campaign DỪNG ở checkpoint 42 do stop-gate (tiến trình đã thoát sạch).
- Lệnh resume (sau khi xử lý mục 7a):
  `nohup systemd-inhibit --what=sleep:idle:handle-lid-switch --who=v4campaign --why=v4 .venv-ml/bin/python scripts/k8s/exp/v4traffic/campaign.py run --lo 42 --hi 88 --tag batch3 --prior <4 camp dir ở trên, không gồm batch2b> > artifacts/experiments/campaign_batch3.log 2>&1 &`
- Đóng gói cuối: `.venv-ml/bin/python scripts/ml/package_v4.py --out research/datasets/oran_flooding_v4 <mọi camp dir>`
  (tự chọn attempt ok, ghi mọi attempt kể cả lỗi vào `manifest/runs_index.json`).

## 3. Quyết định thiết kế đã chốt
- UE-mirror packing: mỗi cặp (ue1 tấn công / ue2 tấn công) nằm cùng 1 run ⇒ mọi prefix cân bằng UE (`design.py`, `deb1309`).
- `benign_benign` (cả 2 UE hợp lệ, backend dual-use): bù bề mặt tấn công SYN/DNS để P(mal|backend) ≈ 0.5, không dùng comp phase.
- `size_seed` chung cho cặp size-matched ⇒ phân bố kích thước gói trùng (overlap 0.83–0.97); SYN/ICMP/DNS khác nhau do giao thức (hợp lệ).
- `victim_mode` (silent/responsive) ghi trên mỗi flow, độc lập nhãn ⇒ DL không lộ nhãn (C2).
- Fan-out: alias IP trên DN + `udpecho` sink làm đích có phản hồi.
- ≥2 tool cho SYN (hping, synflood) và DNS (pacer, hping); iperf chỉ UDP CBR (`-b` hiệu chỉnh theo header).
- achieved = mean; gate ở mức cell (backend×role×load, median ±10%, cell cần ≥3 phase) + gate đối xứng tải MAL vs BEN (±0.05).
- Gate cân bằng là TƯƠNG ĐỐI theo base rate thực tế (không phải 0.5 tuyệt đối), vì benign_benign đẩy base ≈ 0.44.
- Block/structural block balance (`0b64d4b`). IDLE giữ riêng, không gộp BENIGN. Chia QA theo `run_id`.
- Both-attack (runs 84–88): thêm vì P(mal|UE) theo giây chỉ 0.445/0.431 ở 83 run (user chọn). Runs 1–83 giữ nguyên.

## 4. Stop-gate hiện hành (`campaign.py` `STOP_GATES`, `checkpoint_qa`)
- |P(mal|ue) − base| ≤ 0.05; |P(mal|backend dual-use) − base_dual_use| ≤ 0.05 (tính theo HÀNG).
- cell_achieved_pass_rate ≥ 0.85 (chỉ áp khi cell có ≥3 phase); |median ratio MAL − BEN| ≤ 0.05 mỗi mức tải.
- nuisance AUC ≤ 0.6; size overlap mỗi cặp size-matched ≥ 0.6; run lỗi / preflight lỗi ⇒ STOP.

## 5. Failure mode testbed & phục hồi
- SMF↔UPF PFCP không hình thành (SMF discover NRF chạy trước UPF + NRF giữ subscription cũ ⇒ HTTP 0).
  Phục hồi THEO THỨ TỰ: `scripts/k8s/phase0/recover_core_ordered.sh`. **Cấm restart SMF đơn lẻ / restart core đồng thời.**
- Sau host suspend/power-cycle: `scripts/k8s/phase0/recover_ran.sh` → `ip route replace 172.30.26.0/24 dev oaitun_ue1` trên cả 2 UE
  → tắt defense → kiểm 2 SUPI.
- **Host suspend → E2 SCTP mất → `recover_ran.sh`** (gặp 2026-10-21, suspend 15:48→16:08): FlexRIC log
  `SCTP_SEND_FAILED` / `Communication with E2 Node lost?` / `xApp N disconnected!` ngay lúc resume; xApp restart rồi lặp
  `[E2AP]: Resending Setup Request after timeout` ⇒ API `:8090` không lên ⇒ preflight `defense state HTTP 0`. Core/URR/PFCP
  vẫn khỏe (không đụng core). Phục hồi: `recover_ran.sh` → route `172.30.26.0/24 dev oaitun_ue1` trên 2 UE → POST
  `/v1/defense/{core,enabled}` false → preflight. Kiểm sau phục hồi: `defense_state.ues` đủ 2 SUPI, log xApp có KPM
  cho cả 2 `amf_ue_ngap_id`, 0 dòng "Resending Setup", URR age < 3 s, IP↔SUPI từ log SMF (PAA → PDU_SES_EST SUPI).
  Phòng ngừa: sleep/suspend/hibernate/hybrid-sleep/suspend-then-hibernate targets đã `mask`, logind drop-in
  `/etc/systemd/logind.conf.d/99-nosleep.conf` (lid/keys/idle = ignore), GNOME `sleep-inactive-{ac,battery}-type=nothing`.
  Nguyên nhân 3 lần suspend ban ngày (02:04, 09:47, 14:33, 15:48): idle action của gsd-power (không có sự kiện lid);
  17:47 là lid close. `systemd-inhibit` không chặn được vì gsd-power chỉ giữ inhibitor kiểu delay.
- Multus race khi `minikube start`: rollout-restart core sau khi Multus sẵn sàng.
- SMF segfault ~5.5 h (watchdog tự hồi phục). Preflight mỗi run kiểm PFCP association.
- Luôn `kubectl --context oai-lab`; luôn tắt defense trước khi flood.

## 6. QA mới nhất (checkpoint 42, tính theo HÀNG; `…batch2c/campaign.json`)
- P(mal|ue): ue1 0.429, ue2 0.381; base 0.405; base dual-use 0.448.
- P(mal|backend): hping 0.382, iperf 0.500, pacer 0.497 ⇒ STOP.
- cell-achieved pass 1.0 (28 cell đánh giá được); load_symmetry max 0.025.
- nuisance AUC 0.54 (feature "innocent": `meta_ue, meta_t_since_phase_start, meta_load_mbps, meta_victim_mode, meta_congestion`; không có backend).
- size overlap: dns 0.038, syn 0.052 (khác nhau do giao thức, gate bỏ qua), udp 0.97, icmp 1.0, fanout 0.87, mimicry 0.84, pulsing 0.83.
- Phase-weighted (giây, từ manifest, run 1–42): hping MAL 4570 s / BEN 4643 s; iperf 1352/1352; pacer 6579/6656.

## 7. VẤN ĐỀ MỞ
a. **Phase `benign_benign` 1415.7 s (kế hoạch 38 s) — NGUYÊN NHÂN ĐÃ XÁC ĐỊNH: host suspend, không phải thiết kế.**
   - Chỉ MỘT phase: rep 37, `p05_benign_benign` (hping, load 1.2). Manifest: mọi `benign_benign` dài 31–89 s.
   - `journalctl`: `14:33:14 systemd-logind: The system will suspend now!`; máy dậy ~14:56:16. `phases.csv` rep 37: 1792567960→1792569375.
   - Hệ quả: ~2830 hàng BENIGN hping (cả 2 UE) thay cho ~76 ⇒ lệch cân bằng và confound `t_since_phase_start`.
   - Đã chạy `systemd-inhibit` mà logind vẫn suspend (chưa rõ nguyên nhân: lid/phím/GNOME; `systemd-inhibit --list` có GNOME block
     chỉ cho phím nguồn). Run vẫn ghi `meta_run_ok=1` ⇒ **harness không phát hiện phase dài bất thường.**
   - Kiểm chứng: loại phase này khỏi `dataset_sofar`: hping 0.500, iperf 0.500, pacer 0.497, base dual-use 0.499 ⇒ gate sẽ PASS.
   - ĐỀ XUẤT (chưa làm): chạy lại rep 37 (`--lo 36 --hi 37 --tag rerun37`), đánh dấu attempt cũ không hợp lệ kèm lý do trong
     `runs_index` (cần thêm cơ chế loại attempt vào `package_v4.py`; KHÔNG sửa `run.json` gốc, KHÔNG xóa). Thêm check
     "độ dài phase thực > 1.5× kế hoạch ⇒ `meta_run_ok=0`" vào `campaign.py`; ngăn suspend ở logind (`HandleLidSwitch=ignore`
     hoặc `systemctl mask sleep.target`) trước khi chạy tiếp.
   - Đề xuất "tách thành nhiều phase 30–90 s" KHÔNG cần: thiết kế đã đúng 31–89 s.
b. Gate cân bằng backend fail ở prefix 42: là hệ quả của (a) ở trên. Cần xác nhận lại bằng checkpoint sau khi chạy lại rep 37.
c. P(mal|ue) theo hàng sau khi loại phase hỏng vẫn thấp: ue1 0.468, ue2 0.417 (phase-count 0.4716). Run 84–88 both-attack
   được kỳ vọng kéo lên; **chưa đo**, tiêu chí §7.3 [0.45, 0.55] chưa chứng minh được.
d. Nuisance baseline chỉ dùng feature "innocent" (xem mục 6); thêm `meta_backend` là biến thể `with_backend`. Balance của stop-gate
   tính theo HÀNG; QA §3 và §11 tính theo PHASE (và theo giây khi nêu rõ). Cần ghi rõ trong DATASHEET.
e. Adversarial validation (9 run): `victim_mode|MAL` AUC 0.74–0.86 (kỳ vọng, C2), `backend` trong lớp 0.69–0.95 — cần ghi vào DATASHEET.
f. Run 84 có 4 phase hping ở tải 1.2 (theo dõi achieved_ok).
g. Chưa viết `DATASHEET.md`; `docs/`, `data/`, `artifacts/` bị gitignore ⇒ camp dirs chỉ ở máy này, nên sao lưu.

## 8. Bước tiếp theo
1. Chặn suspend ở cấp logind; thêm check độ dài phase; thêm cơ chế loại attempt vào `package_v4.py`.
2. Chạy lại rep 37 (trạng thái testbed: recover_ran nếu cần, routes, defense off); kiểm phase đúng 38 s.
3. Chạy `--lo 42 --hi 88 --tag batch3` (lệnh mục 2, `--prior` gồm cả camp rerun37, thay thế rep 37 cũ); checkpoint tại 88 build + QA.
4. `package_v4.py` ⇒ `rows.parquet`, `qa_report.md`, `calibration.md`; kiểm acceptance §7.3 (mục 11 của qa_report).
5. Viết `DATASHEET.md` (kế thừa p2pilot + số liệu campaign + both-attack + sự cố suspend + adversarial validation).
6. Commit (tác giả ducsssanh), không push.
