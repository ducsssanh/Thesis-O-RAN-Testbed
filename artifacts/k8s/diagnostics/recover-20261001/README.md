# Khôi phục cluster sau crash OOM — 01/10/2026

Bối cảnh: build image UPF với 18 job song song làm host tràn RAM và crash (host không bật swap: `/swapfile` 20 GB có sẵn nhưng không có trong `/etc/fstab`). Đã thay bằng swap 16 GB, có trong `/etc/fstab`; build UPF dùng `--build-arg BUILD_CPUSET=0-5`.

## Chuỗi lỗi sau khi node minikube khởi động lại

1. **Nhầm release cũ.** `scripts/k8s/lab.sh up` *không có* `--stage` đi vào `lab.py` (release `oai-lab`, baseline/rollback), không phải stack 4 namespace. Helm revision 106 của `oai-lab` đã:
   - tạo `oai-lab-db-0`, `oai-lab-dn` trong namespace `oai-lab` (chưa chạy, đã scale về 0 ngay);
   - **xóa 11 Deployment cũ** vốn ở replicas 0 (điểm rollback theo `docs/K8S-A1-EI.md`). `lab.sh rollback` hiện không còn workload để phục hồi. Khôi phục bằng `helm rollback oai-lab 105` sẽ bật ngay pod cũ trùng IP Multus với stack thật — chỉ làm khi stack 4 namespace đã scale về 0, rồi scale release cũ về 0 lại.
   - Stack 4 namespace dùng: `new-run`, `up --stage core|nonrt|near-rt`, `gate-ei`, `up --stage ran`, `rollout upf <image>`.
2. **Multus OOMKilled.** DaemonSet `kube-multus-ds` giới hạn 50Mi; ~20 pod cùng gửi CNI ADD sau reboot → OOMKilled → CrashLoopBackOff, mọi pod (kể cả CoreDNS) không tạo được sandbox (`multus-shim ... Post "http://dummy/cni": EOF`). Sửa: `deploy/k8s/vendor/multus.yaml` request 100Mi / limit 300Mi, CPU limit 500m.
3. **DNS treo ~4 s mỗi lookup.** Resolver Docker trên node (`192.168.49.1`) không trả lời tên bên ngoài (15 s timeout; `docker run ... getent hosts example.com` cũng timeout trên host), trong khi host hỏi DNS công ty chỉ ~0.1 s. Pod dùng `ndots:5` + search domain host `fsoft.fpt.vn` nên mọi FQDN `*.svc.cluster.local` đi qua truy vấn `...cluster.local.fsoft.fpt.vn` bị forward ra resolver hỏng. Hệ quả: SMF/UDM/UPF không đăng ký được NRF (`HTTP Code: 0`); SMF phân giải ngược Node ID UPF `172.30.24.20` mất ~38 s → `Resolving of PFCP Node ID not possible` → PFCP association timeout.
   - Sửa trong cluster, không phụ thuộc mạng host: `scripts/k8s/coredns-search-guard.sh` thêm vào Corefile (a) NXDOMAIN cho mọi tên `*.cluster.local.<x>` (tên rác của search path), (b) NXDOMAIN cho PTR `30.172.in-addr.arpa` (mạng lab). Corefile trước khi sửa: [`../dns-20261001/coredns-before.yaml`](../dns-20261001/coredns-before.yaml).
   - Nguyên nhân gốc ở Docker trên host **chưa sửa**: `sudo systemctl restart docker` có thể khắc phục nhưng sẽ khởi động lại toàn bộ node minikube.
   - Lưu ý: `minikube start` có thể ghi lại ConfigMap CoreDNS; chạy lại script (idempotent) sau mỗi lần start.
4. **SMF/UDM/UPF không tự phục hồi** sau khi DNS ổn — chỉ khi lookup nhanh trở lại; restart UDM/SMF không cần thiết nếu guard được cài trước.

## Kết quả

Sau các sửa trên: `up --stage core` (Core integration gate PASS), `rollout upf`, `up --stage nonrt`, `up --stage near-rt`, `gate-ei` (fixture PASS), `up --stage ran` (RAN/E2/KPM gate PASS). Log từng bước trong thư mục này.
