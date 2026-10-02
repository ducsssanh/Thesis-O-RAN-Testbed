# Báo cáo hiện trạng testbed

**Cập nhật:** 01/10/2026  
**Phạm vi:** cluster Minikube `oai-lab` và tích hợp OAI Core, RAN, FlexRIC/xApp, ICS/A1-EI.

## Đang chạy

Cluster Minikube hoạt động. Các workload chính ở `oai-core`, `oai-ran`, `near-rt-ric` và `non-rt-ric` đều `Ready`; subscriber Job ở trạng thái `Completed` là bình thường. Thành phần gồm OAI Core/UPF eBPF XDP-SKB, DN, gNB/UE RFsim, FlexRIC/KPM xApp, ICS, URR producer và A1-EI adapter.

Run [20260930T052819Z-m35](../artifacts/experiments/20260930T052819Z-m35/acceptance.json) đã PASS: UL/DL 10 Mbit/s × 120 giây, mỗi chiều receiver ghi 157290000 byte và 0% loss; PFCP Usage Report được chấp nhận; XDP-SKB hoạt động; KPM được ghi. [Correlation evidence](../artifacts/experiments/20260930T052819Z-m35/ei-correlation.json) xác nhận cùng `(SEID=1, UR-SEQN=9)` đi từ PFCP/SMF qua producer, adapter tới chính xApp, với counter khớp và KPM trong cùng khoảng thời gian.

Restart riêng xApp và adapter đã giữ dữ liệu; khi xApp tạm dừng, adapter giữ report trong queue và giao lại sau khi xApp hoạt động. Report runtime chi tiết: [xapp-urr-runtime-20260930.md](../artifacts/k8s/diagnostics/xapp-urr-runtime-20260930.md).

## Lỗi và việc còn thiếu

- Run kế tiếp `20260930T053547Z-m35` truyền UL/DL thành công, nhưng A1-EI gate thất bại: session mới tái sử dụng SEID/UR-SEQN cũ; dedup của producer bỏ qua report mới. Cần bổ sung **session epoch** xuyên producer → adapter → xApp rồi chạy lại lifecycle với PVC được giữ nguyên.
- Chưa hoàn tất kiểm thử restart UPF và chu kỳ down/up đầy đủ sau thay đổi URR→xApp.
- xApp đang nhận KPM và URR, nhưng chưa có preprocessing/join dữ liệu, phát hiện UE malicious hay hành động cô lập. **Closed loop chưa triển khai.** Thiết kế phòng thủ hai lớp (xApp là bộ não; eBPF UPF nhớ UE theo SUPI trong BPF map và thực thi; gNB thực thi qua E2) và tham số mặc định đã chốt ngày 01/10/2026 trong [TWO-LAYER-DEFENSE-PLAN.md](TWO-LAYER-DEFENSE-PLAN.md).
- Phase 0 của plan PASS ([20260930T073310Z-phase0-far](../artifacts/experiments/20260930T073310Z-phase0-far/summary.json)): PFCP Update FAR DROP/FORW làm `rules_match_pdr` đổi và traffic UL/DL 1 Mbit/s về 0 rồi phục hồi, TEID giữ nguyên. Chứng minh chuỗi control-plane UPF → BPF map → XDP drop; chưa phải đường điều khiển từ xApp.
- 01/10/2026: Phase A việc #1–3 xong và kiểm chứng trên cluster (UPF `oai-lab-upf:teardown-5f1ab8b55a95`): harness tự sửa route UE; UPF dọn sạch BPF map khi xóa session (sửa thêm lỗi layout key `rules_match_pdr` — mọi lệnh xóa trước đây nhắm sai entry); Update FAR không mang Apply Action giữ nguyên action. Chi tiết: mục 7 của [TWO-LAYER-DEFENSE-PLAN.md](TWO-LAYER-DEFENSE-PLAN.md).
- 01/10/2026: sau crash OOM khi build, cluster cần sửa hạ tầng mới chạy lại: Multus OOMKilled (giới hạn 50Mi → 300Mi), DNS treo vì resolver Docker trên host không phân giải tên ngoài (đã chặn trong CoreDNS bằng `scripts/k8s/coredns-search-guard.sh`; gốc ở Docker chưa sửa), và `lab.sh up` không `--stage` đã chạm vào release cũ `oai-lab` (11 Deployment rollback bị xóa). Xem [recover-20261001](../artifacts/k8s/diagnostics/recover-20261001/README.md).
- FlexRIC agent trong gNB assert khi `epoll_wait` trả EINTR (`asio_agent.c:134`): một signal làm gNB, FlexRIC, SMF cùng thoát mã 139 lúc 07:48 UTC 01/10. Chưa sửa.
- E2 control của OAI gNB hiện là stub (RC chỉ `printf`, SLICE indication là dữ liệu random, MAC/PDCP/GTP không hỗ trợ). Lớp RAN cần patch gNB trước khi có hành động thật.
- Phát hiện khi chạy Phase 0: `RemovePipeline` của UPF dừng giữa chừng khi một thao tác delete map lỗi (SEID 1 còn entry); session mồ côi sau khi pod UE restart (SEID 2 không có Deletion); route `172.30.26.0/24 dev oaitun_ue1` mất khi pod UE restart nên UL đi eth0 và DL iperf trông như hỏng; UPF ghi đè Apply Action kể cả khi Update FAR không mang IE này. (Ba lỗi route/dọn map/Apply Action đã sửa 01/10/2026 — xem dòng trên.)
- KPM/URR cùng được ghi nhận theo thời gian; ánh xạ UE ID sang SUPI cho nhiều UE chưa được chứng minh. ICS hiện là dịch vụ tối giản, không phải toàn bộ nền tảng Non-RT RIC/SMO.
- Một lần host reboot làm node Minikube dừng và mất interface Multus trong các pod cũ. Đã khôi phục bằng restart workload; hiện các pod chính Ready. Nguyên nhân reboot không được kết luận là OOM.

## Đánh giá bàn giao

Có thể bàn giao phần **URR thật được push vào binary KPM xApp**, gồm mã nguồn, image đã pin, chart, gate và bằng chứng runtime một run. Chưa nên gọi toàn bộ testbed hoặc lifecycle nhiều session là hoàn tất cho tới khi xử lý session epoch và chạy lại kiểm thử lặp session/down-up.
