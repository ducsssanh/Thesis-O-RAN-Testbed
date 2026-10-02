# Đánh giá chuyển Codebase sang Kubernetes/minikube

Bản phân tích ban đầu ngày 26/09/2026 được giữ bên dưới để đối chiếu. Backend Kubernetes hiện đã được bổ sung; xem [K8S-LAB.md](K8S-LAB.md) cho cách dựng, patch và ranh giới nghiệm thu. Các nhận xét “chưa chạy” bên dưới mô tả thời điểm audit ban đầu, không phải trạng thái triển khai mới.

## Trạng thái thật trên máy

| Phạm vi | Kết quả |
|---|---|
| Codebase: core | `scripts/legacy/compose/start-core.sh` gọi `compose/core/compose.sh up`, bên trong là `docker compose up -d` |
| Codebase: gNB/UE/RIC/xApp | Chạy binary host bằng script; UE có Linux network namespace |
| Docker lúc kiểm tra | Không có container core/UPF chạy; chỉ `oransim` đã Exited |
| RAN/FlexRIC host | Không thấy tiến trình nr-softmodem/nr-uesoftmodem/nearRT-RIC đang chạy |
| Kubernetes context | `kubernetes-admin@kubernetes` |
| Node | Một node control-plane Ready; Kubernetes v1.33.13, containerd 2.3.5 |
| Workload cluster | Có các workload SMO/nonrtric/ONAP và nhiều pod cũ lỗi/pending; không thấy pod/image OAI UPF, gNB, SMF hoặc FlexRIC của Codebase |
| minikube | Profile Docker cũ tồn tại nhưng inspect báo không có container node `minikube`; không phải cluster hiện đang Ready |

Vì thế “hệ thống đang chạy trên Docker” cần sửa thành: **kiến trúc Codebase dùng Compose + host processes, stack hiện không chạy; máy đồng thời có Kubernetes cho hệ thống khác**. Không suy từ `docker ps` ra tình trạng containerd; đã kiểm tra riêng bằng kubectl.

## Có đơn giản không?

Control-plane NF có thể tái dùng image, config và chart; phần UPF eBPF/mạng RAN cần thiết kế lại. Không phải chỉ đổi Compose sang YAML Deployment. Đánh giá độ khó dưới đây là suy luận từ implementation local:

| Phần | Mức thay đổi | Công việc |
|---|---|---|
| AMF/SMF/NRF/AUSF/UDM/UDR | Vừa | Image giữ được; ConfigMap, Service/DNS, probe, subscriber/DB config |
| MariaDB | Vừa | PVC/StatefulSet hoặc chart DB, init schema/subscriber |
| UPF research | Cao | Custom image, quyền BPF, kernel, interface N3/N4/N6, route/ARP, XDP attach/cleanup |
| gNB/UE RFsim | Vừa–cao | Containerize đúng binary patched, SCTP/GTP-U/RFsim, tun, CPU và đường đi hai chiều |
| FlexRIC/xApp | Vừa | Image riêng, config/library path, E2 SCTP, CSV volume |
| Runner | Cao | Docker/host-PID/netns assumptions phải chuyển sang pod readiness/exec/log/capture |

OAI có [Helm Chart Catalog](https://gitlab.eurecom.fr/oai/orchestration/charts). Có thể dùng làm nền, nhưng chưa kiểm tra chart version cụ thể với image UPF research commit `00b7485`; không khẳng định chỉ thay image là chạy.

## Những chỗ không thể bê nguyên Compose

1. UPF hiện nhận nhiều interface có tên cố định `cp`, `n3`, `n4`, `n6`, `n9`, IP tĩnh và `remote_n6_gw`. Pod network mặc định không tự tái tạo topology này. Đề xuất dùng secondary networks qua [Multus](https://github.com/k8snetworkplumbingwg/multus-cni) với bridge/IPAM cho lab single-node; giữ địa chỉ/interface nhất quán với YAML UPF.
2. `5gdeploy.localhost/bridge` dùng pipework/Docker tooling và host network. Không mang container này sang để quản lý pod. Thay nhiệm vụ nối mạng bằng CNI/Multus và route setup thích hợp.
3. PFCP UDP/8805, GTP-U UDP/2152, NGAP SCTP/38412 và E2 SCTP/36421 cần đường đi đúng. [Kubernetes Service](https://kubernetes.io/docs/concepts/services-networking/service/) có hỗ trợ SCTP với điều kiện network plugin hỗ trợ; Ingress HTTP không thay thế topology telecom. Với lab một UPF, dùng N3/N4 trực tiếp thay vì giả định cân bằng tải Service sẽ giữ được toàn bộ state PFCP/GTP.
4. Quyền BPF phải được xác nhận ở pod/loader trên kernel node. Capabilities, seccomp, AppArmor và privileged mode là các cơ chế khác nhau; [tài liệu Kubernetes](https://kubernetes.io/docs/concepts/security/linux-kernel-security-constraints/) mô tả cách chúng ảnh hưởng container. Lab UPF riêng có thể bắt đầu privileged để xác định khả năng chạy rồi thu hẹp quyền; không suy ra production cần privileged cho mọi NF. Không mount Docker socket vào pod để giữ logic cũ.
5. eBPF chạy trong kernel node. BPF object/loader phải load được, interface attach đúng, MTU/route phù hợp, map và link phải xử lý khi pod restart. Chưa có bằng chứng kernel hiện tại đã chạy thành công UPF này.
6. `hostNetwork: true` có thể giảm một phần routing ở thử nghiệm hẹp, nhưng không tự tạo đủ interface, và nhiều UPF sẽ đụng cổng/interface/state. Với minikube Docker driver, hostNetwork là namespace mạng node container, không phải mặc nhiên namespace mạng laptop.
7. Script hiện dùng `docker exec dn_internet`, `docker inspect`, bridge Docker, `sudo ip netns exec`, process PID và log file host. Thay bằng selector/pod name, `kubectl exec/logs`, pod lifecycle và PVC/collector; không dùng tên pod động hard-code.

## Lộ trình đề xuất

**Mốc 0 — Có baseline đo được:** sửa thiếu cờ BPF/capability của Compose, chạy một UE/một slice/UPF dùng thực, thu PDU accept, iperf receiver, PFCP và KPM. Nếu chưa có baseline, khó phân biệt lỗi implementation cũ với lỗi migration.

**Mốc 1 — Chọn cluster:** máy đã có cluster thật nhưng nhiều workload khác lỗi/pending. Kiểm tra resource/taint/CNI trước khi dùng; không tự xóa pod hoặc đổi CNI đang phục vụ hệ thống khác. Nếu cần lab tách biệt, tạo profile minikube tên riêng. [Docker driver](https://minikube.sigs.k8s.io/docs/drivers/docker/) chạy node Kubernetes trong Docker trên Linux; vì vậy chuyển orchestration sang Kubernetes không đồng nghĩa máy hết dùng Docker.

Ví dụ khởi tạo lab, cần điều chỉnh tài nguyên theo máy (8 CPU/16 GiB chỉ là điểm bắt đầu đề xuất, không phải minimum đã benchmark):

```bash
minikube start -p oai-lab --driver=docker --container-runtime=containerd \
  --cpus=8 --memory=16384
kubectl --context=oai-lab get nodes
minikube -p oai-lab image load oai-upf-research:local
```

Chưa chạy các lệnh này trong audit. Image local phải được load vào runtime của node hoặc push registry; `docker images` trên host không chứng minh node thấy image. Xem [minikube image loading](https://minikube.sigs.k8s.io/docs/handbook/pushing/). Pin image bằng tag theo source/patch digest thay vì chỉ `local` cho các lần đo.

**Mốc 2 — Core trước:** namespace `oai-lab`; MariaDB + CP NF + đúng một custom UPF + DN. Pin chart/image version tương thích; Multus secondary networks cho N3/N4/N6, khai báo route/forwarding, bổ sung ConfigMap/Secret/PVC và probes. Kiểm tra NRF registration, PFCP association, loader và XDP trước khi thêm radio. Không cấu hình thêm service mesh cho datapath trong lần thử đầu.

**Mốc 3 — RAN/RIC:** containerize RAN/FlexRIC từ source đã patch, đưa gNB/UE RFsim vào cùng lab để giảm routing host↔node. Mỗi UE cần tun/network riêng; mount thư viện SM đúng image. Thay RIC `127.0.0.1` bằng endpoint reach được nếu khác pod. Với RFsim kiểm tra TCP/4043, E2 setup và PDU session.

**Mốc 4 — Runner:** tạo backend Kubernetes cho startup/readiness/cleanup/capture/log/traffic. Capture PFCP phải bắt đầu trước UE. Xuất cùng schema KPM/URR/phases như baseline Compose để so sánh; chưa xóa backend Compose cho đến khi đạt parity.

**Mốc 5 — Nghiệm thu:** PFCP report request có Usage Report, response cause accepted; iperf receiver UL/DL có dữ liệu; XDP mode/interface có bằng chứng; KPM có mẫu; pod restart không để stale XDP/map/route. Sau đó mới mở rộng nhiều UPF/slice và tối ưu quyền/CPU.

## Kết luận kỹ thuật

Minikube single-node phù hợp làm lab chức năng cho mục tiêu này, với điều kiện kernel/quyền/CNI đáp ứng loader và đủ CPU/RAM. Chuyển control plane tương đối thẳng; chuyển toàn bộ eBPF UPF + RAN + runner là công việc migration riêng, không phải vài lệnh đổi định dạng YAML. Kết luận khả thi là đánh giá thiết kế, chưa phải kết quả chạy thực nghiệm.
