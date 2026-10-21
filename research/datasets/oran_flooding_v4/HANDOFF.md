# HANDOFF — dataset v4 (flooding vs legitimate high-load), cập nhật 2026-10-22 ~01:00

> Session mới: đọc file này TRƯỚC, rồi mới mở `SPEC`/code khi cần cho việc cụ thể. `DATASHEET.md` CHƯA tồn tại.

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
- Chi tiết kỹ thuật: `docs/SESSION-HANDOFF-V4.md` (gitignored), `research/testbed/phase0_v4.md`.
- Code chính: `scripts/k8s/exp/v4traffic/{design,campaign,integrity,runner}.py`, `backends/*.py`;
  `scripts/ml/{build_dataset_v4,qa_v4,package_v4}.py`.

## 2. Trạng thái hiện tại (2026-10-22 ~00:50)
- Commit gần nhất: `b0a12a9` (share-dur + checkpoint 42 PASS), `b0e68f7` (integrity + attempt_id).
  **Chưa commit:** `manifest/design.json` (thêm checkpoint 64) + file HANDOFF này.
- Manifest: 88 run / 528 phase, seed 20261020, checkpoints `[8, 42, 64]` (+ gate cuối tại `hi`=88).
  Extensions: `both_attack` (run 84–88), `share_durations` (from_run=42, 138 phase), `checkpoint` 64.
- **BATCH 3 ĐANG CHẠY** (run 43–88), bắt đầu 20:10:43 ngày 21/10, ~8.5 phút/run, dự kiến xong ~02:45 ngày 22/10.
  - Camp dir: `artifacts/experiments/20261021-201043_v4campaign_batch3`; log `artifacts/experiments/campaign_batch3.log`.
  - Tiến trình độc lập với session: `setsid nohup systemd-inhibit … campaign.py run --lo 42 --hi 88 --tag batch3 …`
    (PID inhibit 2561913, python 2561916; cha = `systemd --user`, session riêng, không TTY) ⇒ **clear/đóng session
    KHÔNG dừng batch 3**. Chỉ dừng nếu logout phiên desktop / reboot / tắt máy.
  - Kiểm: `pgrep -f "campaign.py run --lo 42"`; `grep -E "meta_run_ok|STOP|CHECKPOINT|Traceback" artifacts/experiments/campaign_batch3.log | tail`.
  - Tại 00:49: 33/46 run xong, tất cả `meta_run_ok=1`; **checkpoint 64 PASS** (mục 6).
- Attempt/camp dirs (gitignored, `artifacts/experiments/`):
  | camp | rep | ghi chú |
  |---|---|---|
  | `20261020-213040_v4campaign_batch1`, `…214714_v4campaign_batch1b` | 1–8 (thử sớm) | không được chọn; giữ |
  | `20261020-232552_v4campaign_batch1c` | 1–8 | hợp lệ |
  | `20261021-093244_v4campaign_batch2` | 9 | hợp lệ |
  | `20261021-102436_v4campaign_batch2b` | 10 | FAILED (`error.txt`), giữ |
  | `20261021-102738_v4campaign_batch2c` | 10–42 | hợp lệ trừ rep 37 (suspend ⇒ `meta_run_ok=0`, `meta_run_ok_prev=1`) |
  | `20261021-194045_…rerun37`, `20261021-194320_…rerun37` | 37 | preflight `defense state HTTP 0` (E2 mất), `meta_run_ok=0` |
  | `20261021-195218_v4campaign_rerun37b` | 37 | hợp lệ (attempt `…rerun37b_rep-37@1792587146`) |
  | `20261021-201043_v4campaign_batch3` | 43–88 | đang chạy |
- Chọn attempt: **attempt hợp lệ mới nhất theo `t_start`** (`package_v4.attempts`, `campaign.prior_run_dirs`). `runs_index.json`
  ghi mọi attempt + `invalid_reason`.
- Backup: `/home/ducsssanh/DATN-backup/20261021/artifacts+manifest-20261021.tar.zst` (444 MB, 7686 file, `SHA256SUMS` OK) —
  **cùng ổ với repo**; user sẽ tự chép ra ổ ngoài/cloud. Cần tạo lại sau khi xong mọi rerun (mục 8).
- `research/datasets/oran_flooding_v4/` mới chỉ có `manifest/` + HANDOFF; chưa có `raw/`, `rows.parquet`, `qa_report.md`,
  `calibration.md`, `DATASHEET.md`.

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
  thời gian run; run lỗi trước phase đầu ⇒ hỏng. Vi phạm ⇒ `meta_run_ok=0` + STOP.
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
- Multus race sau `minikube start`; SMF segfault ~5.5 h (watchdog). Luôn `kubectl --context oai-lab`; luôn tắt defense trước flood.
- Python: dùng `.venv-ml/bin/python` (system python3 không có pandas).

## 6. QA đã có
| chỉ số | ckpt 42 row-w | ckpt 42 phase-w | ckpt 64 row-w |
|---|---|---|---|
| P(mal\|ue) ue1 / ue2 (base) | 0.467 / 0.416 (0.441) | 0.444 / 0.440 (0.442) | 0.456 / 0.426 (0.441) |
| P(mal\|backend) hping / iperf / pacer (base du) | 0.496 / 0.500 / 0.497 (0.497) | 0.500 ×3 | 0.497 / 0.500 / 0.498 (0.498) |
| cell-achieved pass | 1.0 (28) | | 0.964 (28) — fail `iperf/MAL/1.2 = 0.77` |
| load symmetry max / nuisance AUC | 0.025 / 0.513 | | 0.014 / 0.513 |
- Size overlap @64: udp 0.973, icmp 1.0, fanout 0.87, mimicry 0.834, pulsing 0.833 (dns 0.041 / syn 0.062: khác giao thức).
- Kế hoạch (manifest) 1–88 row-w: ue1 0.484 / ue2 0.461; backend hping 0.527 / pacer 0.541 / iperf 0.5 (base du 0.532).
- Integrity 42 run: lệch duration max 0.6%, gap max 2.73 s (sát 3 s).

## 7. VẤN ĐỀ MỞ
a. **[MỚI, NGHIÊM TRỌNG — user đã duyệt hướng sửa] iperf + victim silent ⇒ tấn công bị xung ON/OFF, lộ nhãn.**
   - Triệu chứng (dataset_sofar @64, median sau giây 5): iperf MAL silent prof_ul 561 kbps @0.8 (BEN 874), 576 kbps @1.2
     (BEN 1298); responsive bình thường (853/1269). achieved MAL silent: 0.68 @0.8, 0.56 @1.2, 1.38 @0.4 (giả).
   - Root cause: `backends/iperf.py` chạy mỗi giây một lệnh `iperf -u -c … -t 1` với `subprocess.run(timeout=3)`. Victim
     silent DROP gói attacker ⇒ iperf2 client chờ ack/stats cuối của server ⇒ mỗi block treo tới timeout 3 s ⇒ ~1 s ON / 2 s OFF
     (rep 59 `p04_udp`: phase 31 s chỉ có 10 dòng). Khi timeout, `tx` bị gán = target ⇒ achieved giả.
     Benign iperf và attack iperf responsive không bị (server ack).
   - Gate không bắt được vì load symmetry lấy median gộp mọi backend.
   - Phạm vi: 18 phase (~894 s kế hoạch), **10 run: 7, 16, 17, 47, 59, 62, 66, 67, 68, 78** (78 chạy trong batch 3).
   - Sửa: iperf 2.1.9 trên UE có `--no-udp-fin` ("No final server to client stats at end of UDP test").
b. P(mal|ue) row-w ue2 0.416–0.426 < 0.45 (§7.3 tuyệt đối) do run 1–42; kỳ vọng ~0.461 ở 88 (theo manifest) — cần đo.
c. Nuisance baseline chỉ dùng feature "innocent"; balance stop-gate theo HÀNG, QA §3/§11 theo PHASE ⇒ ghi rõ trong DATASHEET.
d. Adversarial validation (9 run): `victim_mode|MAL` AUC 0.74–0.86 (kỳ vọng, C2), `backend` trong lớp 0.69–0.95 ⇒ DATASHEET.
e. Run 84 có 4 phase hping tải 1.2 (theo dõi achieved).
f. Stream gap max 2.73 s và prof peak min 24 pps sát ngưỡng — theo dõi, KHÔNG nới.

## 8. BƯỚC TIẾP THEO (thứ tự, đã được user duyệt) — ETA tổng ~3 h 50 từ 00:50
1. **Chờ batch 3 xong** (~02:45). KHÔNG sửa `backends/iperf.py` khi batch 3 còn chạy (file được đọc mỗi phase).
   Nếu STOP ở giữa: báo user, không tự chạy tiếp.
2. **Sửa iperf** (`scripts/k8s/exp/v4traffic/backends/iperf.py`):
   - thêm `--no-udp-fin` vào `argv` (mọi lời gọi, cả 2 nhãn ⇒ đối xứng);
   - khi `TimeoutExpired` hoặc không parse được: `tx = NaN`/None (KHÔNG gán = target), achieved để trống;
   - cập nhật `test_backends.py` nếu có assert liên quan.
3. **Guard mới trong `integrity.py`**: mỗi flow trong `traffic/*.csv` phải có số dòng ≥ 90% duration phase
   (bắt kiểu treo như trên). Chạy hồi tố trên mọi run; báo run nào bị bắt (kỳ vọng đúng 10 run ở mục 7a).
4. **Đánh hỏng 10 run** (7, 16, 17, 47, 59, 62, 66, 67, 68, 78): `meta_run_ok=0`, `meta_run_ok_prev=1`, lý do
   "iperf silent-victim FIN stall (pre-fix backend)" trong `integrity.reasons`. Không xóa.
5. **Thử 1 phase iperf + silent** sau khi sửa (vd. rep 59 chạy riêng, hoặc script 1 phase): achieved MAL silent phải trong ±10%
   và số dòng = duration. Không đạt ⇒ DỪNG, báo user.
6. **Thêm `--reps` vào `campaign.py run`** (danh sách rep không liên tiếp, 1 checkpoint ở cuối trên prefix đầy đủ 1–88
   gồm attempt mới nhất hợp lệ), rồi chạy lại:
   `setsid nohup systemd-inhibit --what=sleep:idle:handle-lid-switch --who=v4campaign --why=v4rerun-iperf .venv-ml/bin/python scripts/k8s/exp/v4traffic/campaign.py run --reps 7 16 17 47 59 62 66 67 68 78 --tag rerun_iperf --prior <mọi camp dir hợp lệ + batch3> > artifacts/experiments/campaign_rerun_iperf.log 2>&1 < /dev/null & disown`
   (~1 h 27). Trước khi chạy: kiểm testbed (preflight, E2, URR, defense off).
7. **QA cuối toàn campaign** (`package_v4.py --out research/datasets/oran_flooding_v4 <mọi camp dir kể cả attempt hỏng>`),
   gửi user: P(mal|ue), P(mal|backend) **cả row- và phase-weighted**; danh sách mọi attempt `meta_run_ok=0` + lý do;
   size overlap theo cặp; nuisance AUC; cell-achieved (tách theo victim_mode cho iperf); acceptance §7.3.
8. **Backup lại**: `tar.zst` gồm `artifacts/` (campaign 1–88 + mọi attempt) + `research/datasets/oran_flooding_v4/manifest`,
   kèm `SHA256SUMS` + đếm file, vào `/home/ducsssanh/DATN-backup/<ngày>/`. User tự chép ra ngoài.
9. **Dọn log** (chỉ khi KHÔNG có campaign chạy, sau khi đã gửi QA cuối):
   - Danh sách đề xuất (43 mục, ~78 MB; bản mới nhất mỗi loại được giữ): `*-m35` cũ (24), `*-k8s` cũ (8), `ingest-two-sources` (2),
     `flood-probe` (1), `ds-v4smoke*` cũ (2), `k8s/diagnostics` teardown-verify cũ (3) + xapp-build cũ (1), `k8s/build`
     upf-teardown-build cũ (2). Danh sách chính xác (43 path): `artifacts/DELETE_CANDIDATES_20261021.txt` (gitignored).
   - **GIỮ**: mọi `ds-*_v1/_v2/_v3` (cần raw để dựng lại v3 bằng join nhân quả cho so sánh v3↔v4), mọi `v4campaign*`,
     `v4pilot/p2gate`, `ipcal`, `userplane_watchdog*`, `campaign_*.log`, `artifacts/ml`, `artifacts/k8s/state`, `src/`, `data/`.
   - Trước khi xóa: grep từng path trên manifest/builder/DATASHEET/README của dataset v1–v4 và `scripts/`; mục còn được tham
     chiếu ⇒ bỏ khỏi danh sách, báo user. Xóa phần còn lại; ghi danh sách đã xóa vào `artifacts/CLEANUP_<ngày>.txt`.
10. Viết `DATASHEET.md` (p2pilot + campaign + both-attack + sự cố suspend/E2 + lỗi iperf FIN + adversarial validation +
    2 kiểu trọng số). Cập nhật HANDOFF + commit (ducsssanh, không co-author, không push).
