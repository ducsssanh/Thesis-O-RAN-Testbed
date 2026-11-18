# Nghiệm thu hệ thống phòng thủ flooding liên miền trong O-RAN

Trạng thái ngày 2026-11-05. Tài liệu này là nguồn thống nhất cho những gì đã chốt.

**Dataset cuối cùng:** [`research/datasets/oran_flooding_twin/`](research/datasets/oran_flooding_twin/)
(đường dẫn đầy đủ: `/home/ducsssanh/6G/O-RAN/DATN/Codebase/research/datasets/oran_flooding_twin/`)

**Tên đề tài:** Cross-Domain Detection and Mitigation of Uplink Flooding in O-RAN With KPM Trust Verification and an eBPF-Based UPF.

## 1. Bài toán

Một UE đã xác thực gửi flood đường lên ở mức tải giống người dùng nặng thật, nên riêng tốc độ không đủ để phát hiện. Đồng thời KPM có thể bị giả mạo, hoặc do E2 node bị chiếm, hoặc do MITM trên đường E2.

| Giả mạo KPM | Mức tiêm | Khi tiêm |
|---|---|---|
| Giấu (hiding) | ×0,1; ×0,33; ×0,8 | Tiêm khi replay, không có trong dữ liệu ghi |
| Vu (framing) | ×1,25; ×2; ×5 | Như trên |
| Chỉ giây có traffic | Như trên | Như trên |
| Tráo định danh hai UE | | Như trên |

Rate, PRB UE và PRB cell được sửa đồng thời. Core được tin cậy và luôn gửi được telemetry.

**Ba đóng góp:** phòng thủ liên miền (gate độ tin KPM, eBPF UPF profiler, giảm thiểu trong kernel); dataset KPM và core ghép theo UE, theo giây, có nhãn; twinning là phương pháp tạo dataset, không phải đóng góp riêng.

## 2. Twinning benign

Mỗi UE trên testbed replay một cửa sổ 75 s thật (15 s pre-roll + 60 s pha) của một người dùng thật trong dữ liệu Madrid LTE. Không fit mô hình, không rescale.

| Bước | Làm gì | Công thức hoặc giá trị | Vì sao |
|---|---|---|---|
| 1. Rút gọn | Cộng grant 1 ms thành byte theo giây | $B^d(r,t)=\frac{1}{8}\sum_{TTI\in t}TBS^d$ | Cùng thang 1 s với KPM; TBS tính bằng bit |
| 2. Cắt session | Tách khi im lặng quá T, đo theo từng cell bằng phương pháp inter-transmission của Attanasio et al. | $t_2-t_1>T_{cell}$; I-2650 59,3 s, I-1815 59,3 s, II-816 28,4 s, II-1835 41,0 s | Sau T, RNTI có thể đã đổi chủ, nên không nối session |
| 3. Xếp band | Tốc độ trung bình session, tính cả khoảng im | $\bar r_s=8\sum B_{UL}(t)/W_s$, $W_s=t_{last}-t_{first}+1$; biên 1,25, 7,85, 45,1 kbit/s | Kiểm soát số người dùng nặng; P4 cùng mức tải với tấn công |
| 4. Rút cửa sổ | Chọn session tỉ lệ $W_s+74$, điểm đầu đều | $x_t=B_{UL}(r^*,a+t)$, $y_t=B_{DL}(r^*,a+t)$, $a\sim U[s_0-74,s_1]$ | Giữ nhịp thật và ghép UL–DL của một người |
| 5. Phát gói | Số gói từ byte, mỗi gói đúng thời điểm TTI thật | $packets_t=x_t/E[S]$ | Kích thước gói lấy từ dữ liệu app 5G Hàn Quốc |
| 6. Tỉ lệ band | Lấy mẫu thừa nhóm nặng, số báo nhầm quy về tỉ lệ thật | $FA_{real}=\sum_k\pi_{real,k}FA_k$ | Train đủ ca khó, số báo cáo vẫn đúng với cell thật |

| Band | Khoảng tốc độ | Tỉ lệ thật | Tỉ lệ dataset | App tham chiếu |
|---|---|---|---|---|
| P1 nhẹ, thưa | ≤ 1,25 kbit/s | 0,50 | 0,25 | Roblox, YouTube Live |
| P2 nhẹ, đều | 1,25–7,85 kbit/s | 0,40 | 0,25 | Battleground, TFT |
| P3 vừa | 7,85–45,1 kbit/s | 0,09 | 0,20 | GeForce Now |
| P4 nặng | > 45,1 kbit/s | 0,01 | 0,30 | Zoom |

### Kiểm định twin

Twin đạt khi lệch khỏi dữ liệu thật không hơn mức hai cell thật lệch nhau.

- **Chuẩn hóa:** $\tilde x_t=x_t/\mathrm{mean}\{x_\tau:x_\tau>0\}$, nên chỉ so hình dạng.
- **38 phép:** 9 phép mỗi band, thêm 2 phép cho P4. Gồm KS tốc độ UL, DL, tỉ lệ DL/UL, độ dài ON, OFF, trung bình 60 s, busy share 60 s; tự tương quan $d_{ACF}$ lag 1–10 s; chênh Spearman; riêng P4 có Anderson–Darling và chênh q99.
- **Ngưỡng:** $T_m=\max_i pct_i(S_i(A_n^{(m)},B))$, $\tau^*=Q_{0,95}\{T_m\}$ với $m=1\ldots1000$. Twin đạt khi $\max_i pct_i(S_{i,twin})\le\tau^*$. Rút nguyên cửa sổ, cùng cỡ mẫu với twin.

| Lần kiểm tra | So với | τ* | Phân vị cao nhất | Kết quả |
|---|---|---|---|---|
| final2, sidecar 5% lõi | 4 cell build | 0,994–0,995 | 0,964 (P2 dACF) | Đạt |
| Campaign, sidecar 1 lõi | 4 cell build | 0,994–0,995 | 0,973 (P2 mean 60 s) | Đạt |
| Cell giữ lại I-796, II-2650, chạy đúng một lần | Cả 38 phép | 0,999 | 0,946 (P2 dACF); cao thứ hai 0,648 | Đạt |

Phân vị càng thấp càng tốt. τ\* là ngưỡng, không phải độ giống. Hai cell giữ lại đã dùng hết, không chạy lại.

Sensitivity với tốc độ ×2, ×4 trên P3, P4: MAC so với plan trong khoảng 1%, không có cửa sổ chết hay lỗi RLC. Phép này chặn ảnh hưởng lên testbed và gate, không cho biết TCP hay video thích nghi sẽ hành xử thế nào.

## 3. Sinh dataset

**Testbed:** OAI 5G SA với RF simulator (n78, 106 PRB), 2 UE, OAI core với eBPF/XDP UPF, FlexRIC và xApp, Non-RT RIC với A1-EI. Internet bị chặn, detection tắt trong campaign.

**Tấn công:** flood chồng lên twin của UE, từ thời điểm ngẫu nhiên trong 15 s đầu đến hết pha. Tải neo theo phân vị 0,90, 0,95, 0,99 của giây hoạt động thật: $r=\hat F^{-1}_{active}(q)$, tức 53, 111, 410 kbit/s.

| Mức | Khớp với benign | Công cụ | Đợt |
|---|---|---|---|
| L1 | Tốc độ neo | hping3: UDP, SYN, ICMP | 144 |
| L2 | Thêm nhịp ON/OFF, TTI, kích thước của cửa sổ thật | Bộ gửi UDP theo cửa sổ | 144 |
| L3 | Thêm hành vi ứng dụng | Client TCP và DNS thật; UE kia chạy cùng client với vai benign | 144 |

**Campaign:** manifest cố định trước khi chạy (seed 20261104), 72 run × 6 pha × 75 s. Nhãn chỉ lấy từ manifest. Vai tấn công đổi giữa các UE. QA từng run; 14 lần lỗi được chạy lại cùng seed.

Hàng của giây t chứa traffic của [t−1, t). Gate offline khớp xApp live 99,9% giá trị c và 99,8% mask.

## 4. Dataset cuối cùng

**Thư mục:** [`research/datasets/oran_flooding_twin/`](research/datasets/oran_flooding_twin/). Chưa công bố.

| File | Nội dung |
|---|---|
| [`rows.parquet`](research/datasets/oran_flooding_twin/rows.parquet) | 64 800 hàng, mỗi hàng một UE trong một giây |
| [`windows.csv`](research/datasets/oran_flooding_twin/windows.csv) | Byte dự định và byte tới nơi của từng cửa sổ twin |
| [`DATASHEET.md`](research/datasets/oran_flooding_twin/DATASHEET.md) | Mô tả dữ liệu |
| [`manifest/design.json`](research/datasets/oran_flooding_twin/manifest/design.json) | Thiết kế campaign |
| [`manifest/campaign_log.jsonl`](research/datasets/oran_flooding_twin/manifest/campaign_log.jsonl) | Nhật ký QA, chứa đường dẫn 72 run gốc |
| [`../oran_flooding_twin_package.tar.gz`](research/datasets/oran_flooding_twin_package.tar.gz) | Gói local 10 MiB |

Dữ liệu thô của 72 run nằm trong `artifacts/experiments/*_ds-flood-twin-c0*`, đúng các đường dẫn trong `campaign_log.jsonl`.

**Quy mô:** 72 run, 864 đợt UE (432 có tấn công, 432 benign, trong đó 144 chạy client L3), 25 806 giây tấn công. Thiếu KPM 0%, thiếu profiler 0,01%.

**Đầu vào được dùng:** KPM, profiler, `c_t`, `c_t_w`, tuổi dữ liệu, và `kpm_trust_ue`, `kpm_masked_ue`. Các cột `kpm_trust`, `kpm_masked` là theo node, không dùng.

**Nhãn và meta, không bao giờ là đầu vào:** `role`, `attack_active`, `attack_bytes`, `attack_bytes_core`, `onset_t`, `t_window`, `evasion`, `vector`, `anchor_bps`, `band`, `window_index`, `attacker_ue`, `client_role`, `run_id`, `phase`, `seed`.

| Loại | Đợt | Giây | Có traffic | UL q50 / q90 (kbit/s) | Gói/s | IP len (B) | PRB UE (%) |
|---|---|---|---|---|---|---|---|
| Benign P1 | 70 | 5 250 | 1,1% | 11,6 / 28,7 | 8 | 163 | 5 |
| Benign P2 | 73 | 5 475 | 2,4% | 21,8 / 50,8 | 37 | 68 | 7 |
| Benign P3 | 55 | 4 125 | 9,4% | 20,2 / 83,0 | 10 | 285 | 7 |
| Benign P4 | 90 | 6 750 | 36,5% | 81,0 / 534,1 | 14 | 750 | 20 |
| Client TCP benign | 72 | 5 400 | 63,0% | 87,2 / 526,5 | 151 | 56 | 18 |
| Client DNS benign | 72 | 5 400 | 59,7% | 99,5 / 508,0 | 173 | 56 | 17 |
| L1 UDP | 48 | 3 266 | 100% | 118,2 / 396,5 | 484 | 29 | 29 |
| L1 SYN | 48 | 3 270 | 100% | 112,5 / 403,8 | 338 | 41 | 27 |
| L1 ICMP | 48 | 3 257 | 100% | 113,6 / 400,0 | 480 | 29 | 27 |
| L2 UDP | 144 | 6 293 | 89,0% | 109,1 / 558,6 | 19 | 746 | 34 |
| L3 TCP | 72 | 4 839 | 99,8% | 112,5 / 431,8 | 251 | 56 | 25 |
| L3 DNS | 72 | 4 881 | 100% | 112,4 / 424,0 | 249 | 56 | 22 |

Hàng tấn công chỉ tính giây tấn công và đã gồm twin của UE. Tốc độ, gói/s, IP len, PRB đọc trên giây có từ 1 kB.

## 5. xApp phòng thủ

xApp là điểm quyết định duy nhất. Image hiện tại `oai-lab-xapp:59036cb09c33d372`, các patch nằm trong `patches/` và được kiểm tra bằng `scripts/verify-oai-upstream.sh`.

| Nguồn | Cho biết | Độ tin | Đến xApp sau KPM (p50 / p99) |
|---|---|---|---|
| KPM (gNB, E2SM-KPM) | Tốc độ UL/DL, PRB theo UE | Có thể bị giả | 0 (mốc) |
| eBPF UPF profiler, nguồn core chính | Byte, gói, giao thức, đích theo session, đếm trước policy | Tin cậy | 0,09 s / 0,11 s |
| URR (PFCP qua SMF) | Byte đã chuyển, đếm sau policy | Tin cậy | 0,58 s / 0,78 s; chỉ để xác minh hành động |

Đường core là O-RAN-aligned, không phải luồng O-RAN chuẩn: A1-EI là giao diện chuẩn, còn đẩy telemetry UPF theo session dưới 1 s là cách dùng mở rộng. KPM và profiler ghép theo SUPI và giây đo, không theo thời điểm đến.

### Gate độ tin KPM

Gate là luật cố định, chạy **theo từng UE**. Nó trả lời "số KPM của UE này có đúng không", không phát hiện flood.

$$c_t=\log\frac{KPM^{UL}_t+\varepsilon}{\max(B_t-\beta N_t,0)+\varepsilon},\quad \beta=57\text{ B},\ \varepsilon=1\text{ kB}$$

$c_t\approx0$ là trung thực, $c_t\ll0$ là giấu, $c_t\gg0$ là vu. $c_t$ một giây chỉ là tín hiệu mềm, vì KPM và profiler chốt giây lệch nhau. Độ tin cập nhật trên $c_{t,w}$, cùng tỉ số đó tính trên tổng 3 s:

$$trust_t=trust_{t-1}+0{,}1\,(\mathbf 1[|c_{t,w}|\le0{,}2]-trust_{t-1})$$

KPM của UE bị che khi trust < 0,85 và dùng lại khi trust > 0,90.

| Kết quả | Số đo |
|---|---|
| Honest trên 2 cell giữ lại | Ngoài band 3 s tối đa 0,87%; KPM không bị che |
| Tiêm giả mạo trên 432 đợt tấn công | ×0,8 che 98,8%, ×1,25 che 99,5%, các mức khác 100%; trung vị 1–3 s; 1,6–4,6% byte tấn công tới core trước khi che |
| UE trung thực bên cạnh | Che nhầm 0,4% với trust theo UE, so với 76–97% nếu theo node |
| Live, traffic đều | Che UE bị giả trong 2,5–4,6 s; UE kia không bị che |
| Chỉ giả mạo giây ON, 144 đợt L2 | ×0,8 97,2%, ×1,25 98,6%, các mức khác 100%; không né được gate |
| Tráo định danh | Che 99,8% đợt; tương quan KPM–core theo giây 0,999 cùng UE, 0,014 khác UE |

## 6. Phát hiện bằng ML

**Đã chốt với thầy:** lớp quyết định chỉ dùng **classifier**. DRL đã bỏ, vì lần chạy thử không thắng classifier (`research/drl/out_r2n_cost.txt`). Chi tiết từng lần chạy ở nhật ký thực nghiệm (R000–R051).

| Mục | Đã chốt (R050) |
|---|---|
| Model | XGBoost, độ sâu chọn trong {4, 8} trên inner split; gộp 3 seed (trung bình logit); temperature scaling |
| Đầu vào | 15 feature mỗi giây (core UL/DL kbit/s và gói/s, PRB UL/DL, PRB trên kbit, kích thước gói UL/DL, DL/UL, `c_t_w`, trust, mask, tuổi KPM, tuổi profiler) + 10 feature tóm tắt cửa sổ 10 s = 25 số |
| Không đưa vào | Nhãn, meta, thời điểm trong pha, bộ đếm lũy kế |
| Chia dữ liệu | Theo nhóm cửa sổ Madrid (người dùng gốc), 3 seed; train L1 + L2 + L3 (Q6, chốt 2026-11-08; trước đó L3 chỉ test) |
| Báo động | Hai mức trên cùng model. Giới hạn tốc độ: mức 2 báo nhầm/UE-giờ, quy tắc 2 trong 3 giây. Chặn: mức 0,5, quy tắc 20 trong 30 giây. Ngưỡng chọn trên điểm ngoài mẫu của phần train |
| Báo nhầm | Mẫu số là thời gian benign thực sự quan sát; số quy về thật dùng tỉ lệ band 0,50 / 0,40 / 0,09 / 0,01 |

**Test sạch** (vòng 4, 12 run chưa model nào thấy, chỉ L2, người dùng chưa thấy; train 93 run: 72 cũ + 24 L2 mới, bỏ 3 run chung cửa sổ Madrid với test):

| Hành động | Báo nhầm test /UE-giờ (quy về thật) | Phát hiện L2 | Độ trễ trung vị | Giây chưa phát hiện mỗi đợt [KTC 95%] |
|---|---|---|---|---|
| Giới hạn tốc độ | 1,07 (0,22) | 86,6% | 3,2 s | 14,0 [10,4; 17,0] |
| Chặn | 0 (0) | 63,0% | 20,2 s | 30,2 [26,3; 33,9] |

**L1 và L3** (vòng 3, test cũ đã xem; ngưỡng vẫn chọn ngoài mẫu): giới hạn tốc độ L1/L2/L3 99,1% / 90,5% / 98,6%; chặn 100% / 68,3% / 98,4%; client benign L3 bị tác động 39/432 và 6/432.

**Mốc so:** luật hiện có trong xApp (2 Mbit/s) phát hiện 0% ở các mức tải này. MLP và GRU kém XGBoost 6–8 s chưa phát hiện ở mức 0,5; chỉ RAN kém hơn core + RAN 4,9 s.

**Live trên testbed:** model đã nhúng trong xApp (`clf_xgb.c`, `classifier.kind: xgb`); kết quả phát hiện live ghi ở đây sau thử nghiệm.

## 7. Giảm thiểu

Khi báo động, hành động cố định theo trạng thái gate:

| Trạng thái gate | Hành động |
|---|---|
| KPM trung thực | Giới hạn tốc độ rồi chặn ở XDP, có TTL |
| KPM bị giấu ($c_t\ll0$) | Chặn dựa trên bằng chứng core, gắn cờ gNB |
| KPM bị vu ($c_t\gg0$) | Không xử lý UE, chỉ gắn cờ gNB |

| Điểm thực thi | Cơ chế |
|---|---|
| RAN | E2SM-RC, slice cách ly giới hạn PRB; UE giữ PDU session |
| UPF | Policy theo SUPI trong BPF map, kiểm tra trong XDP, chặn UL trước N6 |

Qua lời gọi trực tiếp tới UPF, policy có hiệu lực sau 26 ms và UL của UE bị chặn tại DN về gần 0. Con số này chỉ tính phía UPF. Đường chuẩn là xApp → NEF → PCF → SMF → N4 → eBPF UPF, chưa đo và chưa kiểm tra hỗ trợ trong OAI.

## 8. Giới hạn đã biết

- Madrid là LTE, chỉ lấy nhu cầu người dùng. Replay open loop, không phản ứng với mạng như TCP hay video thích nghi.
- 2 UE, 1 cell, RF simulator. Tác hại quy mô botnet không tái hiện được.
- Không suy được lịch sử dài của một người dùng từ Madrid, vì RNTI đổi chủ sau T.
- Kiểm tra twin trên cell giữ lại chạy lúc sidecar còn 5% lõi và không lặp lại được.
- Giả mạo tiêm khi replay để lại dấu hiệu ở cùng tốc độ UL (benign: AUC 0,67 ở ×0,8, 0,99 ở ×5).
- Chỉ onset dạng bậc, 3 trong 6 vector L1, DNS không ở cổng 53, 3 mức tải cố định.
- Burst một giây có thể mất byte tại testbed; dùng `attack_bytes_core` và `windows.csv`.

## 9. Chưa chốt

Các mục này chưa được đồng ý và không thuộc nghiệm thu:

1. Feature lịch sử theo UE.

Đã chốt sau khi viết mục này: pha L3 được đưa vào train (Q6, 2026-11-08; kết quả ở nhật ký thực nghiệm, vòng 2 và 3).

## 10. Nơi lưu

| Nội dung | Vị trí |
|---|---|
| Thiết kế và chạy campaign | `scripts/k8s/exp/v4traffic/{design_twin,campaign_twin,qa_twin,planbuilder}.py` |
| Dựng dataset | `scripts/ml/build_dataset_twin.py`, `scripts/ml/package_twin.py` |
| Bằng chứng twin và gate | `research/twinning/out_*`, `research/twinning/ct_root_cause/` |
| Số đo classifier | `research/drl/out_r2n_cost.txt`, `research/drl/out_r2n_report.txt` |
| Dựng lại testbed | `docs/BUILD-FROM-SCRATCH.md`, `docs/K8S-LAB.md`, `docs/K8S-A1-EI.md`, `docs/OAI-UPSTREAM-CHANGES.md` |
