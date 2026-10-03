# A.7 — hiệu chỉnh URR ↔ KPM và tải đường URR (A.6), 03/10/2026

Image: UPF `oai-lab-upf:ttl-afdf292e9d3a` (C25 gồm report theo hết chu kỳ đo), SMF `v2.2.0-lab-838baa19`, radio `faa627d484cce732`.
Dữ liệu: 6 experiment lành tính (60 s mỗi chiều), danh sách ở `runs.txt`; phân tích `scripts/k8s/calibrate.py` → `calibration.json`.
Quét: `scripts/k8s/phase0/calib_sweep.sh runs.txt rate:payload ...`.

| Profile | KPM/URR UL | KPM/URR DL | Dư (mô hình gói) UL | DL | Lag KPM (s) |
|---|---|---|---|---|---|
| 1M / 100 B | 0,898 | 0,693 | +1,5% | +0,24% | +1,8 |
| 5M / 400 B | 0,964 | 0,882 | +0,13% | +0,04% | −0,6 |
| 10M / 800 B | 0,982 | 0,935 | +0,17% | 0,00% | −0,2 |
| 2M / 1400 B | 0,974 | 0,958 | −1,5% | −0,37% | −0,2 |
| 10M / 1200 B | 0,985 | 0,955 | −0,17% | −0,04% | −0,5 |
| 15M / 1200 B | 0,987 | 0,955 | +0,04% | −0,01% | −0,3 |

- Mô hình: `KPM ≈ URR_bytes − c·URR_packets`, **c_UL = 16,3 B, c_DL = 57,3 B** (lý thuyết 14 / 58). Tỉ số cố định sai tới 25% chỉ vì cỡ gói.
- Theo cửa sổ: DL p99 0,5% (W = 1 s). UL p50 1–2,6%, p99 19% (W = 1 s), 10% (W = 10 s).
- FPR: DL ε = 0,02 @ W = 1 s: 0/339. UL ε = 0,15, 2 cửa sổ liên tiếp @ W = 2 s: 0/159.
- Tải (1 UE, 1 report/s, `crictl stats` 60 s): SMF 1,16%, producer 0,23%, adapter 0,87%, xApp 0,43% một core (≈ 2,7%/UE ⇒ ~35 UE/core ở PERIO 1 s); PFCP 2 bản tin/s/UE; report 1,00/s kể cả khi im lặng. UPF 250–300% khi có traffic 10–15 Mbit/s (XDP generic/SKB, không do URR).

Sự cố môi trường trong lúc đo (đã sửa/ghi nhận): container `capture` thiếu `CAP_KILL` nên không dừng được tcpdump sau khi tcpdump hạ quyền ⇒ crash-loop, flush quá hạn (thêm `KILL` trong 4 chart); FlexRIC kẹt sau khi SMF restart (KPM stale) ⇒ `up --stage ran`.
