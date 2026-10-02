# Artifact Kubernetes lab

Bắt đầu từ [milestones.json](milestones.json) để xem tiến độ nghiệm thu.
Đây là dữ liệu sinh ra khi build/kiểm tra/triển khai; cấu hình nguồn ở
[deploy/k8s](../../deploy/k8s), hướng dẫn ở [K8S-LAB.md](../../docs/K8S-LAB.md).

| Thư mục | Nội dung | CLI dùng lại? |
|---|---|---|
| `state/` | `images.json` khóa tag/ID/hash source; `images.yaml` override image cho Helm; `current-run` khi có thí nghiệm | Có, cần giữ để chạy `up` |
| `build/` | Log build tools/UPF/radio, kết quả build dở và provenance source/patch/chart | Chủ yếu để đối chiếu; `images.partial.json` không phải lock hoàn chỉnh |
| `bootstrap/` | Kết quả probe, snapshot manifest/pod/values/image trong node, log bootstrap và kiểm tra context | Bằng chứng Mốc 1 |
| `core/` | Seed/idempotence, log NF, capture PFCP, snapshot XDP và core gate | Bằng chứng runtime Mốc 2 |
| `checks/` | Preflight, manifest render, lint/test/validation và các kiểm thử âm | Bằng chứng kiểm tra |
| `diagnostics/` | Lỗi gần nhất và snapshot status | Chẩn đoán; lỗi lịch sử không có nghĩa lab hiện vẫn lỗi |
| `baseline/` | Đối chiếu Compose | Bằng chứng baseline |

- JSON: dữ liệu máy đọc được (kết quả, image ID, trạng thái).
- YAML: cấu hình Helm sinh ra hoặc snapshot manifest/values để đối chiếu.
- LOG/TXT: đầu ra lệnh và log chẩn đoán.

Muốn sửa topology/config: sửa `deploy/k8s/values/minikube.yaml` hoặc chart nguồn.
`state/images.yaml` được `lab.sh build` sinh ra; không sửa snapshot trong `bootstrap/`
hoặc manifest trong `checks/` để cấu hình deployment.

Các file ở đây chủ yếu là snapshot gần nhất, một số giữ bằng chứng kiểm tra ban đầu.
Kết quả thí nghiệm E2E được tách riêng theo run ID tại `artifacts/experiments/<run-id>/`.
Việc chia lại thư mục không chạy lại workload hay thay đổi kết quả nghiệm thu.
