# OAI lab trên minikube

Mốc 3.5 (split release, Non-RT RIC, A1-EI) và lệnh triển khai mới: [K8S-A1-EI.md](K8S-A1-EI.md). Chart/release `oai-lab` mô tả bên dưới được giữ làm baseline/rollback.

Backend mới nằm trong `deploy/k8s` và `scripts/k8s`. Backend này không gọi 5gdeploy, pipework hoặc launcher NIST. Compose và source cũ vẫn được giữ để đối chiếu. Minikube dùng Docker driver để tạo node; workload bên trong node dùng containerd và Kubernetes.

## Phạm vi và trạng thái

**Mốc 1 đã hoàn tất ngày 26/09/2026.** Build image, Helm lint/render và server dry-run đã qua; cả 5 Job bootstrap (hai đầu mạng, BPF, TUN, radio libraries) đã Completed trên `oai-lab`. Bằng chứng: [milestones.json](../artifacts/k8s/milestones.json), [bootstrap.json](../artifacts/k8s/bootstrap/bootstrap.json), [image lock](../artifacts/k8s/state/images.json). Context mặc định vẫn là `kubernetes-admin@kubernetes`.

Mốc 0 đã sửa/kiểm chứng capability generator Compose, nhưng chưa có baseline traffic Compose. Mốc 2 và Mốc 3 đã được nghiệm thu. Hai lượt traffic Mốc 4 trước và sau khi restart UPF đều đạt 10 Mbit/s × 120 giây mỗi chiều; receiver UL/DL đều nhận 157290000 byte, PFCP/SMF/A1-EI/KPM đối chiếu được. Còn thiếu kiểm tra chu kỳ down/up. Lần thử seed ban đầu phát hiện lỗi tách SQL comment; file schema đã được sửa và seed/authentication thực tế đã được kiểm chứng ở Mốc 2.

**Mốc 2 đã hoàn tất ngày 27/09/2026.** DB và subscriber Job idempotent đã PASS; NRF/UDR/UDM/AUSF/AMF/SMF/UPF đều Ready và các NF ứng dụng đều REGISTERED trong NRF. DN có route trả `10.1.0.0/16` qua UPF N6. UPF gắn XDP-SKB thật trên N3/N6 (program ID 3457/3464 tại run nghiệm thu).

SMF dùng image riêng `oai-lab-smf:v2.2.0-ie43-771248b5`, vẫn dựa trên v2.2.0 và chỉ thêm patch decoder IE 43 forward-compatible. PCAP xác nhận Association Response cause=1 chứa IE 43 length 8; SMF không còn decoder exception và 14 cặp heartbeat request/response được ghép đúng sequence. CLI giờ yêu cầu đồng thời NF registration, association, ít nhất hai heartbeat, IE 43 length 8, DN route và XDP-SKB trước khi PASS core. Bằng chứng chính: [core-gate.json](../artifacts/k8s/core/core-gate.json), [runtime summary](../artifacts/k8s/core/runtime-verify-final/summary.json) và [milestones.json](../artifacts/k8s/milestones.json).

**Mốc 3 đã hoàn tất ngày 27/09/2026.** FlexRIC nhận E2 Setup từ gNB; UE đăng ký, tạo PDU session và nhận địa chỉ `10.1.0.2`; xApp ghi 128 mẫu KPM với node `gNB:3584` và UE ID `1`. XDP-SKB vẫn gắn trên N3/N6 sau khi session được tạo. Run nghiệm thu là `20260927T163834Z-k8s`; log, PCAP, metadata và CSV nằm trong [`artifacts/experiments/20260927T163834Z-k8s`](../artifacts/experiments/20260927T163834Z-k8s/).

Các sửa nhỏ trong lượt này: Multus cài binary bằng atomic rename để tránh `Text file busy` khi resume; capture sidecar thêm CHOWN/SETUID/SETGID cho tcpdump; probe UPF kiểm tra socket UDP/8805 thay TCP/80, không phụ thuộc peer PFCP. Đã giữ nguyên context mặc định và dữ liệu PVC; các pod core còn chạy để kiểm tra.

Một UE, một slice, một UPF; PLMN 00101, TAC 7, SST 1, SD FFFFFF, DNN nist-dnn, PDU 10.1.0.0/16. Non-RT RIC tối giản có ICS và URR producer trong release riêng; không migrate SMO/ONAP. Chỉ UPF được privileged trong các workload ứng dụng; Multus là hạ tầng node và cần quyền riêng.

Mốc 1 xác nhận build/render/bootstrap/mạng, Mốc 2 xác nhận core/PFCP/XDP và Mốc 3 xác nhận radio/PDU/KPM. **Chưa đồng nghĩa nghiệm thu migration:** lượt traffic Mốc 4, đối chiếu URR và lượt chạy lại sau restart UPF đã PASS; chu kỳ `up/down/up` vẫn chưa kiểm chứng. Xem `artifacts/k8s/milestones.json` để biết trạng thái được kiểm chứng gần nhất.

## Cấu trúc implementation và artifact

| Đường dẫn | Vai trò |
|---|---|
| `deploy/k8s/values/minikube.yaml` | Cấu hình lab người dùng chỉnh: topology, NF, PLMN/slice, tài nguyên |
| `deploy/k8s/chart/` | Umbrella Helm chart: workload, Service, PVC, Secret references, Multus NAD, template config và probe |
| `deploy/k8s/vendor/` | Chart OAI và manifest Multus đã pin; provenance nguồn |
| `deploy/k8s/images/` | Dockerfile và runtime/entrypoint cho image tools và research |
| `scripts/k8s/lab.sh`, `lab.py` | CLI điều phối preflight, build, Helm/kubectl, startup gates, thu artifact |
| `scripts/k8s/start-deployments.sh` | Resume nhẹ: scale riêng deployment core lên một replica và chờ rollout, không chạy lại Helm/bootstrap |
| `scripts/k8s/analyze.py` | Phân tích traffic/PFCP/KPM và điều kiện nghiệm thu |
| `tests/k8s/` | Unit test, kiểm tra render và XDP mode |
| `patches/` | Patch UPF XDP mode, URR và patch chart OAI |
| `artifacts/k8s/` | File sinh ra; xem [README artifact](../artifacts/k8s/README.md) |

Luồng chính: **values + chart → Helm → workload Kubernetes**. CLI quản lý thứ tự
và kiểm tra; runtime trong image chuẩn bị config từ ConfigMap/Secret. JSON/YAML
trong artifact phục vụ chạy lại hoặc đối chiếu, không phải mỗi file là một thành
phần triển khai độc lập.

Artifact được chia thành `state/`, `build/`, `bootstrap/`, `checks/`, `diagnostics/`
và `baseline/`; chỉ README và báo cáo `milestones.json` ở cấp đầu. CLI đọc image
lock/override từ `state/`, ghi kết quả mới vào nhóm tương ứng. Kết quả thí nghiệm
vẫn nằm tại `artifacts/experiments/<run-id>/`.

## Dựng trên máy sạch

1. Tái dựng source và patch theo [BUILD-FROM-SCRATCH.md](BUILD-FROM-SCRATCH.md). Sau patch URR `00b7485`, áp dụng thêm:

   ```sh
   cd src/oai-upf
   git apply ../../patches/oai-upf-xdp-mode.patch
   cd ../..
   ```

   Bỏ qua thao tác apply nếu đang dùng snapshot workspace đã patch. Không áp dụng hai lần.

2. Cài Docker Engine và quyền truy cập Docker, minikube, Helm 3, kubectl, Python 3.12+ cùng PyYAML, tshark, iproute2 và g++. Máy cần ít nhất 8 CPU, 16 GiB cấp cho lab, RAM dư cho host/build và ít nhất 25 GiB đĩa còn trống tại preflight. Build lần đầu có thể cần nhiều hơn tùy cache. Sau khi tất cả image đã có trong runtime của cluster giữ lại, preflight tái triển khai chỉ yêu cầu 5 GiB trống cho dữ liệu/log; một lần build mới vẫn yêu cầu 25 GiB. CLI kiểm tra image trong node để phân biệt hai trường hợp, không tự xóa cache.

3. Chạy từ root workspace:

   ```sh
   scripts/k8s/lab.sh check
   scripts/k8s/lab.sh build
   scripts/k8s/lab.sh up --stage bootstrap
   scripts/k8s/lab.sh status
   ```

   Build tuần tự tools → UPF → radio → SMF patched khi source/patch SMF có trong workspace. Radio image chứa gNB, UE, FlexRIC và xApp build từ source local; không thay bằng image `develop`. Compiler ASN.1 được pin commit `940dd5fa9f3917913fd487b13dfddfacd0ded06e`, cùng pin trong RAN build helper. Xem log tại `artifacts/k8s/build/*-build.log`.

4. Khi Mốc 1 đã qua, tiếp tục từng giai đoạn:

   ```sh
   scripts/k8s/lab.sh up --stage core
   scripts/k8s/lab.sh up
   scripts/k8s/lab.sh experiment
   ```

   Các giai đoạn này đang cần nghiệm thu runtime; lỗi trả exit code khác 0. `up` tái đồng bộ release theo thứ tự và có thể tái tạo session, vì vậy không gọi trong lúc đang chạy experiment. Không coi pod Running hoặc kiểm thử giả lập là PASS end-to-end.

   Nếu release đã tồn tại và chỉ được scale xuống để giảm tải, resume mà không
   chạy lại Helm/bootstrap bằng:

   ```sh
   # Toàn bộ core theo thứ tự NRF → UDR → UDM → AUSF → AMF → SMF → DN → UPF
   scripts/k8s/start-deployments.sh

   # Hoặc chỉ các thành phần được chọn
   scripts/k8s/start-deployments.sh nrf smf dn upf
   ```

   Script này không khởi động profile minikube và không load image. Kiểm tra
   `minikube status -p oai-lab` trước khi dùng.

5. Dừng release, giữ dữ liệu:

   ```sh
   scripts/k8s/lab.sh down
   ```

   Giữ cluster, Secret, PVC database và artifact. Không xóa profile, namespace hoặc sửa cluster khác. Mọi lệnh kubectl dùng context `oai-lab`; CLI sử dụng kubectl tương ứng phiên bản minikube. `minikube start --keep-context` không đổi context mặc định của người dùng.

## Cấu hình và provenance

- Values chính: `deploy/k8s/values/minikube.yaml`; image override sinh ra ở `artifacts/k8s/state/images.yaml`. `images.json` ghi hash source, image ID và digest registry nếu có. Image local không có RepoDigest thì ghi image ID, không tự tạo digest giả.
- OAI charts vendored tại commit `7925f939ea36a3c4c1df5525f3718ce8470f6b3f`, dependency local trong umbrella chart. `vendor/PROVENANCE.json` ghi nguồn và phiên bản Multus. `Chart.lock` pin dependency.
- `patches/oai-charts-7925f93-lab.patch` thêm nhánh opt-in `global.lab` cho deployment, bỏ ConfigMap/NAD mặc định trong nhánh lab. Service/selectors/chart metadata của OAI vẫn được dùng. Nhánh lab gọi helper deployment của umbrella, tạo bridge/static NAD và cấu hình tập trung.
- `patches/oai-upf-xdp-mode.patch` độc lập patch URR. YAML thêm `upf.support_features.xdp_mode`: auto mặc định giữ đường Compose, skb bắt buộc SKB, native bắt buộc driver. Chỉ auto được fallback khi native trả EOPNOTSUPP. Teardown kiểm tra program ID và expected FD trước detach bằng đúng mode.
- `patches/oai-upf-00b7485-dl-qfi-from-access-pdr.patch` xử lý trường hợp OAI SMF gửi QFI trên ACCESS PDR nhưng DL CORE PDR không có QFI/QER. UPF chỉ kế thừa khi tất cả ACCESS PDR có cùng một QFI hợp lệ; nếu không xác định được thì ghi cảnh báo, không hardcode QFI 1. Traffic UDP của runner dùng datagram 1200 byte để còn chỗ cho 44 byte GTP-U/IPv4/UDP trên N3 MTU 1500. Đây là patch tích hợp riêng, cần nghiệm thu receiver UL/DL sau mỗi rollout.
- DN chart tắt TX checksum offload trên N6 bằng init container trước khi chạy traffic. Với XDP-SKB hiện tại, nếu DN để `CHECKSUM_PARTIAL`, gói DL tới UE TUN nhưng UDP checksum sai và kernel loại bỏ. Thử DL 5 giây sau rollout DN nhận 324000/324000 byte tại UE, không mất gói và không tăng `InCsumErrors`; xem `artifacts/k8s/diagnostics/m4-dl-path/ROOT-CAUSE.md`. Đây là mitigation trong lab, chưa thay thế việc xử lý checksum đúng trong dataplane cho mọi loại nguồn traffic. Một lần thử Mốc 4 trước đó phải dừng ở UL vì CPU package 100–101°C; kết quả runtime mới được ghi ở mục xApp bên dưới.
- Config NF, gNB, UE, FlexRIC được template; các placeholder credential chỉ thay ở init container từ Secret. Values và ConfigMap không chứa khóa SIM. UE1 hiện có là nguồn credential mẫu lần tạo Secret đầu; Secret được tái sử dụng sau down/up.
- Schema SQL là DDL snapshot OAI, không chứa subscriber có sẵn và không DROP DATABASE. Job seed dùng upsert cùng khóa duy nhất và giữ SQN khi chạy lại.
- SMF vẫn dựa trên v2.2.0 và có patch decoder IE 43 tách riêng. Không có tham số tùy chỉnh threshold URR mới; analyzer đọc threshold thực từ Create URR.

## Mapping từ script cũ

| Trách nhiệm trước đây | Kubernetes |
|---|---|
| `configure-core.sh`, generator 5gdeploy | Helm values, ConfigMap và Secret |
| `compose.sh`, `start-core.sh` | Helm release, Deployment/StatefulSet và rollout gates |
| `bridge.sh`, pipework, IP host | Multus bridge/static NetworkAttachmentDefinition trong node |
| subscriber SQL/script | MariaDB PVC và Job upsert |
| `start-gnb.sh`, `start-ue.sh`, namespace/veth host | Pod gNB/UE, Service RFsim, TUN và NET_ADMIN của UE |
| FlexRIC/xApp launcher | Deployment, E2 IP tĩnh và artifact PVC |
| traffic/capture host | DN image iperf2, SMF capture sidecar, runner Kubernetes |
| stop/cleanup host | Helm uninstall giới hạn release, giữ PVC |

## Kiểm chứng

```sh
python3 -m unittest discover -s tests/k8s -v
g++ -std=c++17 -Isrc/oai-upf/src/upf_app/include tests/k8s/xdp_mode.cpp -o /tmp/oai-xdp-mode-test
/tmp/oai-xdp-mode-test
bash tests/test_oai_upf_profile.sh
```

Bootstrap tạo hai Job với IP .250/.251 trên mỗi mạng secondary; đây là IP dành riêng cho probe, không dùng cho NF. Probe xác nhận địa chỉ/interface, UDP liên pod trên cả 5 mạng, SCTP liên pod trên N2, DNS và không có default route secondary. Hai Job mạng không privileged. Job `bootstrap-radio` kiểm tra bốn binary và dependency thư viện; Job `bootstrap-ue-tun` thực sự tạo rồi đóng TUN với NET_ADMIN. Job `bootstrap-upf-bpf` dùng image UPF privileged để probe khả năng load BPF/XDP; đây chưa phải attach datapath N3/N6. Kết quả nằm tại `artifacts/k8s/bootstrap/bootstrap-{server,client}.json`.

`experiment` tạo capture trước session UE mới, lưu receiver CSV iperf2, giữ schema `KPI_Metrics.csv`, `pfcp_messages.csv`, `pfcp_urr_config.csv`, `pfcp_urr.csv`, `phases.csv`, bổ sung metadata/image/source/chart/XDP. Thiếu báo cáo URR hoặc KPM phải FAIL. Analyzer ghép Usage Report và response bằng sequence + cặp IP; yêu cầu cause accepted, volume UL/DL dương. Nếu traffic chưa đạt threshold, tăng `global.lab.experiment.duration` và chạy lại. Không chỉnh threshold metadata để giả lập hỗ trợ SMF.

Trong lượt traffic dài, CLI in lúc bắt đầu mỗi chiều, nhịp tiến độ mỗi 15 giây và số byte/mất gói từ receiver sau khi mỗi chiều hoàn thành. Dòng tiến độ chỉ cho biết client còn chạy; kết quả receiver mới là bằng chứng traffic tới đích. Correlation đọc SEID PFCP ở dạng hex và chỉ so khớp URR/SMF/producer/adapter trong cửa sổ thời gian của experiment, tránh lấy nhầm dữ liệu lịch sử trên PVC.

Mỗi lần nghiệm thu mới phải có run ID và PCAP mới bắt đầu **trước khi UE tạo PDU session**. Nếu `capture.stop` của run hiện tại đã tồn tại, dừng UE rồi chạy tuần tự:

```sh
kubectl --context=oai-lab -n oai-ran scale deployment/oai-nr-ue --replicas=0
kubectl --context=oai-lab -n oai-ran wait --for=delete pod -l oai-lab/component=nr-ue --timeout=120s
scripts/k8s/lab.sh new-run
scripts/k8s/lab.sh up --stage ran
scripts/k8s/lab.sh experiment
```

CLI từ chối dùng lại capture đã đóng. Analyzer kiểm tra PCAP phủ khoảng thời gian UL/DL và đọc ngưỡng URR theo cả ba trường PFCP: total, uplink và downlink volume. Ví dụ SMF hiện gửi `DLVOL=1000`, không có `TOVOL`; một PCAP cũ có ngưỡng đúng vẫn không được dùng để PASS traffic mới.

Restart UPF, tái tạo session, chạy lại experiment và vòng down/up/upgrade giữ subscriber/PVC là các bước nghiệm thu tiếp theo; một file acceptance PASS cho một lần đo chưa chứng minh toàn bộ lifecycle. Trước khi restart hoặc rollout UPF, scale UE về 0 và chờ pod cũ biến mất. Dùng `scripts/k8s/lab.sh restart-upf` cho cùng image, hoặc `scripts/k8s/lab.sh rollout upf <image>` cho image mới. Hai lệnh dừng UPF cũ, xóa neighbor N4 của SMF, bật UPF và đợi PFCP heartbeat với MAC mới. Sau đó chạy `new-run`, `up --stage ran`, rồi `experiment`. Tránh `kubectl rollout restart deployment/oai-upf` trực tiếp: khi IP N4 tĩnh chuyển sang MAC pod mới, Association Request có thể đi tới MAC cũ; SMF mất UPF graph và từ chối PDU session của UE.

Nguồn: [OAI charts](https://gitlab.eurecom.fr/oai/orchestration/charts/-/tree/7925f939ea36a3c4c1df5525f3718ce8470f6b3f), [Multus v4.2.2](https://github.com/k8snetworkplumbingwg/multus-cni/tree/v4.2.2), [minikube start](https://minikube.sigs.k8s.io/docs/commands/start/).

### Bổ sung đường URR vào chính KPM xApp

Receiver HTTPS đã được thêm vào binary C của KPM xApp; adapter dùng queue BoltDB và xApp dùng SQLite/PVC. Build và rollout theo thứ tự:

```bash
scripts/k8s/lab.sh certs
scripts/k8s/lab.sh build-xapp
tests/k8s/test_urr_receiver.sh "$(python3 -c 'import json;print(json.load(open("artifacts/k8s/state/xapp-image.json"))["image"])')"
scripts/k8s/lab.sh rollout xapp "$(python3 -c 'import json;print(json.load(open("artifacts/k8s/state/xapp-image.json"))["image"])')"
scripts/k8s/lab.sh build-ei
scripts/k8s/lab.sh rollout adapter "$(python3 -c 'import json;print(json.load(open("artifacts/k8s/state/ei-images.json"))["adapter"]["image"])')"
scripts/k8s/lab.sh gate-xapp --fixture
```

XApp được build qua target Docker `xapp`, không compile lại gNB/UE. Lượt build đầu cần mạng để tải package Ubuntu và `asn1c`; các lớp này được Docker cache cho lần sau. `rollout xapp` chỉ đổi Deployment `oai-lab-xapp`; `rollout adapter` chỉ đổi adapter. Xem queue bằng `GET /v1/delivery/status` ở adapter và số bản ghi nhận bằng `GET /v1/urr/status` ở xApp, đều qua HTTPS với lab CA. Gate fixture không thay cho thực nghiệm thật.

Sau khi UE tạo PDU session mới và có URR thật, chạy `scripts/k8s/lab.sh gate-xapp --real`. Với run mới, `scripts/k8s/lab.sh experiment` sẽ yêu cầu một cặp `(SEID, UR-SEQN)` có mặt tại PFCP, callback SMF, producer, adapter **và xApp**, với counter khớp và KPM cùng khoảng thời gian. Artifact `urr-received.jsonl` được xuất từ SQLite của xApp. Đường push adapter → xApp là giao thức nội bộ của testbed; preprocessing và closed loop thuộc bước sau.

Runtime đã PASS ở `artifacts/experiments/20260930T052819Z-m35`: UL/DL 10 Mbit/s × 120 giây, mỗi receiver nhận 157290000 byte (0% loss); `ei-correlation.json` xác nhận cùng SEID 1 / UR-SEQN 9 tại PFCP, SMF callback, producer, adapter, xApp và KPM cùng khoảng thời gian. Restart riêng xApp và adapter giữ 20 report trong SQLite; report mới SEID 2 / UR-SEQN 27 được xApp nhận sau restart. Khi scale xApp về 0, adapter retry SEID 2 / UR-SEQN 28; khi xApp lên lại, lần thử thứ 7 được ACK HTTP 201 và SQLite chỉ có một bản ghi cho cặp này.

**Giới hạn lifecycle đã quan sát:** run `20260930T053547Z-m35` truyền UL/DL thành công nhưng A1-EI gate FAIL. SMF gửi raw callback cho SEID 2 / UR-SEQN 1–26, còn producer bỏ qua vì BoltDB đã thấy cùng cặp ở session trước. Dedup hiện không có session epoch; không được dùng `(SEID, UR-SEQN)` làm định danh toàn cục khi UPF tái sử dụng SEID. Cần bổ sung session epoch xuyên suốt producer → adapter → xApp trước khi nghiệm thu lặp session/long lifecycle. Không xóa state PVC để che lỗi này.

Các kiểm thử nhánh lỗi thiếu image/SMF chưa ready/xApp không có mẫu trong `tests/k8s` là unit test, không thay thế nghiệm thu NF thật. Có bằng chứng runtime riêng cho BPF thiếu quyền, YAML XDP mode sai và CLI từ chối subnet trùng trong `artifacts/k8s/checks/negative-bpf.json`, `artifacts/k8s/checks/invalid-xdp.json`, `artifacts/k8s/checks/negative-subnet.json`.

Phân tích baseline UPF và patch decoder SMF: [SMF-PFCP-COMPATIBILITY.md](SMF-PFCP-COMPATIBILITY.md). Method test, image build và runtime PFCP integration đều đã PASS ở Mốc 2.
