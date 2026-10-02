# Script entrypoints

Backend đang phát triển là Kubernetes/minikube và nằm trong `scripts/k8s/`:

- `lab.sh`: preflight, build, deploy, status, experiment và teardown của lab.
- `start-deployments.sh`: scale một hoặc nhiều Deployment core lên một replica và chờ rollout; không chạy lại Helm/bootstrap.
- `analyze.py`: phân tích artifact của thí nghiệm.

Ví dụ khởi động toàn bộ core hiện có theo thứ tự phụ thuộc:

```bash
scripts/k8s/start-deployments.sh
```

Chỉ khởi động một số thành phần:

```bash
scripts/k8s/start-deployments.sh nrf udr udm
scripts/k8s/start-deployments.sh smf dn upf
```

Backend Docker Compose/host cũ được giữ để đối chiếu tại `scripts/legacy/compose/`. Các script đó không được backend Kubernetes gọi.
