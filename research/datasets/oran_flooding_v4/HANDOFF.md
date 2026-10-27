# HANDOFF — dataset v4 (flooding vs legitimate high-load), cập nhật 2026-10-22 ~06:00 — CAMPAIGN XONG (88/88)

> Session mới: đọc file này TRƯỚC, rồi mới mở `SPEC`/code khi cần cho việc cụ thể. `DATASHEET.md` đã có (đọc nó cho chi tiết sự cố + QA cuối).

## 0. Quy tắc làm việc của user (bắt buộc)
- Tiết kiệm token: không đọc lại toàn repo/log; `tail`/`grep` có giới hạn; không dán log dài.
- Báo cáo = bảng số + kết luận, không kể lại quá trình. Báo sau mỗi bước.
- **Không restart/redeploy testbed nếu chưa có root cause + proof** (mục 5). Không đụng core khi lỗi chỉ ở RAN/E2.
- **Không tự nới tiêu chí gate**; hỏi user khi cần quyết định.
- **Không xóa dữ liệu đã thu**; attempt hỏng giữ lại với `meta_run_ok=0` + lý do. **Không xóa gì khi campaign đang chạy.**
- Commit: tác giả ducsssanh, không push.
- Lệnh cần sudo: đưa lệnh chính xác, user tự chạy.

## 1. Mục tiêu & phạm vi
- Sinh dữ liệu có nhãn từ testbed OAI 5G (gNB + 2 NR-UE RFsim, OAI 5GC, FlexRIC, URR, eBPF UPF profiler),
  tách flooding khỏi tải cao hợp lệ; detection/mitigation TẮT khi thu. Một hàng = 1 giây × 1 UE (KPM + URR + prof,
  as-of join nhân quả theo `arrival_ts`).
- Spec gốc: "PROMPT: Xây dựng pipeline sinh dữ liệu v4" (§0–10) — chỉ có trong hội thoại cũ, không có file trong repo.
- Chi tiết kỹ thuật: `docs/archive/SESSION-HANDOFF-V4.md` (gitignored), `research/testbed/phase0_v4.md`.
- Code chính: `scripts/k8s/exp/v4traffic/{design,campaign,integrity,runner}.py`, `backends/*.py`;
  `scripts/ml/{build_dataset_v4,qa_v4,package_v4}.py`.

## 2. Trạng thái hiện tại (2026-10-22 ~06:00)
- **Mục 8 cũ (bước 1–8, 10) XONG.** Bước 9 (dọn log) chỉ còn chờ user tự chạy lệnh xóa (agent bị chặn quyền xóa).
- Commits: `08a3641` (fix iperf + flow-row guard + `--reps`), commit cuối = DATASHEET + HANDOFF.
- Dataset cuối: `research/datasets/oran_flooding_v4/` — 88/88 run chọn, 87 294 hàng, `rows.parquet/csv`, `raw/`,
  `manifest/runs_index.json` (120 attempt, 24 invalid kèm lý do), `qa_report.md` (§11 acceptance ALL PASS),
  `calibration.md`, `reproducibility.txt`, `unit_tests.txt`, `DATASHEET.md`.
- Camp dirs: xem bảng trong `DATASHEET.md` §Batches. Mới: `20261022-012451_v4campaign_rerun_iperf` (dừng ở 59),
  `20261022-030535_v4campaign_rerun_iperf_b` (59, 62, 66–68, 76–88; checkpoint cuối 1..88 PASS).
- Backup mới: `/home/ducsssanh/DATN-backup/20261022/artifacts+manifest-20261022.tar.zst` (500 MB, 10 704 file,
  `SHA256SUMS` OK, `src_filecount.txt`). Cùng ổ với repo ⇒ **user cần tự chép ra ổ ngoài/cloud**.
- Watchdog: `userplane_watchdog.py watch --interval 60 --recover --fail-ticks 3` chạy lại 03:05 bằng code hiện tại
  (chỉ `recover_core_ordered.sh`). Tiến trình cũ (từ 20/10, code cũ restart core đồng thời) đã bị dừng.

- **27/10:** toàn bộ phần ML (train, model, đánh giá) đã bị xoá — chuyển hướng DRL (`research/DRL-DIRECTION.md`);
  backup artifacts ML: `~/backups/oran-ml-artifacts-20261027.tar.gz`. Dataset giữ nguyên.

## 3. Quyết định thiết kế đã chốt
- UE-mirror packing: mỗi cặp (ue1 tấn công / ue2 tấn công) cùng run ⇒ prefix cân bằng UE (`deb1309`).
- `benign_benign` bù bề mặt tấn công SYN/DNS cho backend dual-use (pacer/hping/iperf); gắn với cặp "surplus" thành unit trung tính.
- **Từ run 43 mọi phase trong một unit dùng CHUNG duration** (`design.py share-dur`) ⇒ cân bằng chính xác theo hàng.
  Run 1–42 không đổi (đã thu) ⇒ lệch P(mal|ue) theo hàng ở 1–42 không sửa được.
- `size_seed` chung cho cặp size-matched; `victim_mode` (silent=DROP trên DN / responsive) độc lập nhãn (C2).
- ≥2 tool cho SYN, DNS; iperf chỉ UDP CBR.
- Gate cân bằng TƯƠNG ĐỐI theo base rate (benign_benign đẩy base ≈ 0.44). IDLE giữ riêng. QA chia theo `run_id`.
- Both-attack (run 84–88) để kéo P(mal|ue) lên.
- Checkpoint trung gian đặt ở 64 (không phải 65) vì 64 là ranh giới prefix gần nhất không cắt đôi unit.

## 4. Gate & guard hiện hành
- Stop-gate (`campaign.py` `STOP_GATES`, `checkpoint_qa`, tính theo HÀNG): |P(mal|ue) − base| ≤ 0.05;
  |P(mal|backend dual-use) − base_du| ≤ 0.05; cell_achieved_pass_rate ≥ 0.85 (cell ≥3 phase, median ±10%);
  load symmetry |median MAL − BEN| ≤ 0.05 mỗi mức tải; nuisance AUC ≤ 0.6; size overlap cặp size-matched ≥ 0.6.
- Integrity mỗi run (`integrity.py`, gọi trong `campaign.py` + mục 10b `qa_v4`): duration mỗi phase lệch kế hoạch ≤ 20%;
  không có gap KPM/URR/prof > 3 s trong phase (theo SUPI, kể cả biên); không có kernel `PM: suspend entry/exit` chồng
  thời gian run; run lỗi trước phase đầu ⇒ hỏng; **mỗi flow `traffic/*.csv` có ≥ 90% số giây phase với `bytes` biết được** (mới 22/10). Vi phạm ⇒ `meta_run_ok=0` + STOP.
- `prof_assert`: mỗi phase tấn công, peak `prof_ul_pps` của attacker ≥ 20 (khớp theo SUPI ⇒ không phụ thuộc mapping IP).
  Hồi tố 42 run: 223 (phase, UE) đều qua, min peak 24 pps (sát ngưỡng).
- `supi_ip_mapping`: UPF API không trả IP ⇒ `record_mapping` đọc log SMF (PAA → PDU_SES_EST SUPI). 42 run cũ đã backfill từ
  `preflight.ues` (`supi_ip_mapping_source`), khớp `ip_history`.

## 5. Failure mode testbed & phục hồi
- SMF↔UPF PFCP không hình thành ⇒ `scripts/k8s/phase0/recover_core_ordered.sh`. **Cấm restart SMF đơn lẻ / core đồng thời.**
- **Host suspend → E2 SCTP mất → `recover_ran.sh`** (2026-10-21, suspend 15:48→16:08): FlexRIC `SCTP_SEND_FAILED` /
  `Communication with E2 Node lost?`; xApp lặp `[E2AP]: Resending Setup Request after timeout` ⇒ `:8090` không lên ⇒
  preflight `defense state HTTP 0`. Core/URR/PFCP vẫn khỏe. Phục hồi: `recover_ran.sh` → `ip route replace 172.30.26.0/24
  dev oaitun_ue1` trên 2 UE → POST `/v1/defense/core` và `/v1/defense/enabled` `{"enabled": false}` → preflight.
  Kiểm: `defense_state.ues` đủ 2 SUPI, KPM cho cả 2 `amf_ue_ngap_id`, 0 dòng "Resending Setup", URR age < 3 s, IP↔SUPI từ SMF.
- Chống suspend (đã làm, verify `systemctl is-enabled sleep.target` = `masked`): mask sleep/suspend/hibernate/hybrid-sleep/
  suspend-then-hibernate; `/etc/systemd/logind.conf.d/99-nosleep.conf`; GNOME `sleep-inactive-{ac,battery}-type 'nothing'`.
  Nguyên nhân suspend ban ngày: idle action gsd-power (inhibitor chỉ kiểu delay ⇒ `systemd-inhibit` không đủ); 17:47 = lid.
- **UE radio-link failure** (rep 76): gNB `UL Failure on PUSCH` → `UEContextReleaseRequest` cause 21 ⇒ `recover_ran.sh` (không đụng core).
- **Core release UE** (rerun 59): PFCP mất sau restart đồng thời ⇒ `recover_core_ordered.sh`. Không dùng watchdog code cũ.
- Multus race sau `minikube start`; SMF segfault ~5.5 h (watchdog). Luôn `kubectl --context oai-lab`; luôn tắt defense trước flood.
- Python: dùng `.venv-ml/bin/python` (system python3 không có pandas).

## 6. QA cuối (@88, full prefix) — chi tiết trong DATASHEET §Final QA
| chỉ số | row-w | phase-w |
|---|---|---|
| base | 0.472 | 0.472 |
| P(mal\|ue1/ue2) | 0.483 / 0.461 | 0.472 / 0.472 |
| P(mal\|hping/iperf/pacer) (base du 0.532) | 0.526 / 0.500 / 0.540 | 0.530 / 0.500 / 0.543 |
- cell-achieved 1.0 (28), load sym max 0.015, nuisance AUC 0.487, size overlap udp 0.96 fanout 0.87 mimicry 0.84
  pulsing 0.84 icmp 1.0. iperf silent MAL achieved 1.007–1.026 (trước sửa 0.56–0.68).

## 7. VẤN ĐỀ MỞ
a. Nguyên nhân gốc của việc core release UE2 lúc 02:50 (`REL_DUE_TO_REACTIVATION`, NAS deregister) chưa rõ — log
   AMF/SMF mất do watchdog cũ restart. Nếu tái diễn: lưu log AMF/SMF NGAY trước khi recovery.
b. Hai phiên bản backend iperf cùng tồn tại (pre-fix ở các run qua guard ≥ 90%, post-fix ở rerun + 76–88) — nuisance
   cấp run, không tương quan nhãn; đã ghi trong DATASHEET limitations.
c. Stream gap / prof peak sát ngưỡng — không nới.
d. Lý do hiển thị "35 rows vs 39s (90% < 90%)" (rep 19) do làm tròn %.0f: thực tế 89.7%.

## 8. BƯỚC TIẾP THEO
1. Hướng DRL cho lớp quyết định: xem `research/DRL-DIRECTION.md`.
2. (Tùy chọn, eval-only) tập realism closed-loop app thật; tập FPR tải thấp.
3. User: chép backup `/home/ducsssanh/DATN-backup/20261022/` ra ngoài; chạy lệnh dọn log trong `artifacts/CLEANUP_20261022_delete.txt`.
