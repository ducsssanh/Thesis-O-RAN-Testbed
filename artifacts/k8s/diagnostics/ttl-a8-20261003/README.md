# A.6 + Phase C + A.8 — kiểm chứng trên cluster, 03/10/2026

Image: SMF `oai-lab-smf:v2.2.0-lab-838baa19` (C19, C20, C24), UPF `oai-lab-upf:ttl-72a4d1cb103f` (C21, C25),
radio `oai-lab-radio:faa627d484cce732` + xApp `oai-lab-xapp:e4b86a7522ad333c` (C22). Tham số `global.lab.defense` (TTL 60/120 s, PERIO 1 s, keep-alive UE 20 s).

| Gate | Kết quả | Bằng chứng |
|---|---|---|
| C — User ID | PASS: Establishment có User ID (IE 141) IMSI `001010123456780` = secret, IE 117 = 60 s; UPF log `PFCP session established … SUPI imsi-001010123456780` | PCAP run `20261003T102936Z-m35` |
| A.6 — URR 1 s | PASS: 242 report/≈240 s, xApp nhận 242/242, A1-EI thật PASS; tổng UL report 162,8 MB vs 157,3 MB payload (sau C25) | `artifacts/experiments/20261003T112656Z-m35` |
| A.8 (1) gNB chết hẳn | PASS: UPIR sau 56 s; T1 release sau 121 s (AMF gửi AN release ⇒ DEACTIVATED); 6 map sạch | `lost/` (`lost-gnb-replaced/`: gNB thay thế ⇒ AMF Release SM Context, dọn trước TTL) |
| A.8 (2) UE im lặng | PASS: UPIR ⇒ traffic ⇒ sống qua hạn; im lặng ⇒ UPIR lần 2 ⇒ T2 release sau 129 s; map sạch | `idle/` |
| A.8 (3) restart SMF | PASS: UPF xóa session association cũ (Recovery TS 4000015576 → 4000016937), map sạch | `smf/` |
| Hồi quy A.3 | PASS 3/3 chu kỳ kill UE | `orphan-ue/` |

Lỗi có sẵn phát hiện khi kiểm chứng: **C24** SMF xóa FTUP khi UPF re-associate ⇒ F-TEID N3 = IP N4, mất UL;
**C25** Usage Report mang volume lũy kế. Script: `scripts/k8s/phase0/ttl_gate.sh <out> lost|idle|smf`.
