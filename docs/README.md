# Tài liệu Codebase

- [BUILD-FROM-SCRATCH.md](BUILD-FROM-SCRATCH.md): nguồn repo/commit, khôi phục source + patch, gom thành monorepo, dependency và build.
- [PATCH-DETAILS.md](PATCH-DETAILS.md): giải thích từng patch thay đổi gì so với baseline, gồm 13 file của commit UPF.
- [PATCH-PROVENANCE.md](PATCH-PROVENANCE.md): đối chiếu blob của từng patch với fork NIST testbed cũ, tách kế thừa khỏi thay đổi chưa xác định nguồn tác giả.
- [LOCAL-PATCHES.md](LOCAL-PATCHES.md): danh mục đường dẫn patch và file đích.
- [RUN-EBPF-UPF.md](RUN-EBPF-UPF.md): chạy thử, capture, log và tiêu chí nghiệm thu; đọc cập nhật capability ở đầu file trước.
- [KUBERNETES-MIGRATION.md](KUBERNETES-MIGRATION.md): trạng thái Docker/Kubernetes thực tế ngày 26/09/2026, độ khó và lộ trình minikube.
- [TESTBED-SYSTEM-DESIGN.md](TESTBED-SYSTEM-DESIGN.md): kiến trúc testbed hiện tại, bốn namespace, topology/giao thức, thứ tự khởi tạo, UL/DL, URR–A1-EI–KPM, bằng chứng và giới hạn nghiên cứu; có sơ đồ Mermaid.
- [SESSION-HANDOFF.md](SESSION-HANDOFF.md): **đọc đầu tiên khi mở session mới** — tóm tắt hệ thống, trạng thái, việc đã xong, việc tiếp theo, runbook và bẫy vận hành.
- [TWO-LAYER-DEFENSE-DESIGN.md](TWO-LAYER-DEFENSE-DESIGN.md): thiết kế phòng thủ hai lớp đã chốt — nguyên tắc, hai tầng state, kiến trúc, escalation, tham số, kịch bản MITM, giới hạn, nhật ký quyết định.
- [TWO-LAYER-DEFENSE-PLAN.md](TWO-LAYER-DEFENSE-PLAN.md): hiện trạng code, các phase và gate, việc làm ngay, kết quả Phase 0 và Phase A.

Tài liệu audit cũ được giữ để đối chiếu nguồn. Backend Kubernetes mới và bằng chứng triển khai theo mốc được mô tả riêng trong K8S-LAB.md; chưa được suy diễn bootstrap thành nghiệm thu toàn stack. Snapshot hiện tại không có Git root.

## Backend Kubernetes

Xem [K8S-LAB.md](K8S-LAB.md) và [K8S-A1-EI.md](K8S-A1-EI.md) cho lệnh vận hành backend minikube theo bốn release, patch XDP/chart và bằng chứng theo mốc. Backend Compose vẫn được giữ để đối chiếu.
