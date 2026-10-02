# Mốc 4: UE PDU timeout sau khi restart UPF (2026-09-29)

- Run thất bại: `20260929T093643Z-m35`. UE đăng ký nhưng nhận `FGS_PDU_SESSION_ESTABLISHMENT_REJ`; SMF báo `UPF selection failed`. Log trích tại `m4-upf-restart-pfcp-failure.log` cho thấy PFCP heartbeat fail, rồi UPF graph rỗng.
- Khi UPF mới dùng lại N4 `172.30.24.20`, SMF vẫn giữ MAC cũ `fe:08:23:bf:20:be`. PCAP từ SMF cho thấy Association Setup Request gửi tới MAC cũ. UPF mới có MAC `c6:a1:1c:e4:34:03`, nên không nhận request. Đây là race neighbor/ARP với IP Multus tĩnh khi pod được thay trực tiếp.
- Kiểm chứng fix: scale UE về 0; scale UPF về 0 và chờ pod xóa; `ip neigh flush to 172.30.24.20 dev n4` trong SMF capture sidecar; scale UPF lên 1. UPF mới có MAC `a2:81:74:f5:04:94`; SMF ARP khớp, nhận Association Setup Response, thêm UPF graph edge và nhận heartbeat.
- Run mới `20260929T095013Z-m35`: `up --stage ran` PASS, UE có PDU IP `10.1.0.2`, E2/KPM PASS. XDP generic/SKB có program ID N3 `1776`, N6 `1783`. UL và DL smoke 500 Kbit/s × 5 giây đều nhận 324000 byte tại receiver; CSV tại `post-restart-{ul,dl}-{sender,receiver}.csv`.
- CLI thêm `restart-upf` và đổi `rollout upf`/core stage sang trình tự giải phóng neighbor. RAN stage kiểm tra MAC N4, PFCP association và heartbeat trước khi bật UE. Chưa chạy lại nghiệm thu 120 giây hoặc vòng down/up, vì vậy Mốc 4 vẫn PARTIAL.
