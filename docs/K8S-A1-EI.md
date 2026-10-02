# Mốc 3.5: Non-RT RIC và A1-EI trên minikube

## Ranh giới giao thức

UPF gửi PFCP Usage Report cho SMF theo [ETSI TS 129 244](https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/17.10.00_60/ts_129244v171000p.pdf). OAI SMF chuyển report thành `QOS_MON` Event Exposure callback. Repo OAI hiện dùng `customized_data["Usage Report"]` và `QOS_MON` được đánh dấu là customized event trong source; vì vậy đây không phải mapping URR→A1-EI được 3GPP hoặc O-RAN chuẩn hóa. Nsmf Event Exposure được mô tả trong [ETSI TS 129 508](https://www.etsi.org/deliver/etsi_ts/129500_129599/129508/18.08.00_60/ts_129508v180800p.pdf).

`urr-ei-producer` chuẩn hóa callback của OAI thành Information Type riêng `oai-urr_1.0.0`. O-RAN SC ICS quản lý Information Type, Information Producer và Information Job; dữ liệu được producer gửi thẳng đến `a1-ei-adapter`. Adapter dùng [A1-EI API của ICS](https://docs.o-ran-sc.org/projects/o-ran-sc-nonrtric-plt-informationcoordinatorservice/en/latest/ics-api.html) để tạo job và đọc trạng thái `ENABLED`. Kiến trúc A1 và giao thức ứng dụng/transport tham chiếu [ETSI TS 103 982](https://www.etsi.org/deliver/etsi_ts/103900_103999/103982/08.00.00_60/ts_103982v080000p.pdf), [TS 103 983](https://www.etsi.org/deliver/etsi_ts/103900_103999/103983/04.00.00_60/ts_103983v040000p.pdf), [TS 103 987](https://www.etsi.org/deliver/etsi_ts/103900_103999/103987/04.03.00_60/ts_103987v040300p.pdf), [TS 103 986](https://www.etsi.org/deliver/etsi_ts/103900_103999/103986/03.03.00_60/ts_103986v030300p.pdf) và [TS 103 988](https://www.etsi.org/deliver/etsi_ts/103900_103999/103988/09.00.00_60/ts_103988v090000p.pdf).

## Các release

| Release/namespace | Workload | Mạng phụ |
|---|---|---|
| `oai-core` | DB, NRF, UDR, UDM, AUSF, AMF, SMF, UPF, DN | N2/N3/N4/N6 |
| `oai-ran` | gNB, UE | N2/N3/E2 |
| `near-rt-ric` | FlexRIC, KPM xApp, A1-EI adapter | E2 |
| `non-rt-ric` | ICS, URR producer | Pod network |

Chart cũ `deploy/k8s/chart` và release `oai-lab` là điểm rollback. Các chart mới ở `deploy/k8s/charts`; IP Multus được giữ nguyên nên pod telecom cũ và mới không thể chạy đồng thời. PVC, Secret và NAD riêng theo namespace. `oai-core` là namespace duy nhất đặt Pod Security privileged cho UPF eBPF.

## Triển khai tuần tự

```bash
scripts/k8s/lab.sh check
scripts/k8s/lab.sh resume
scripts/k8s/lab.sh certs
scripts/k8s/lab.sh build-ei
scripts/k8s/lab.sh cutover
scripts/k8s/lab.sh up --stage core
scripts/k8s/lab.sh up --stage nonrt
scripts/k8s/lab.sh up --stage near-rt
scripts/k8s/lab.sh gate-ei
scripts/k8s/lab.sh up --stage ran
scripts/k8s/lab.sh experiment
```

`check` lint/render và server dry-run. `resume` chỉ kiểm tra API hoặc khởi động lại profile, không rebootstrap. `certs` tạo private CA và HTTPS Secret; private key không được ghi vào repo hoặc artifact. `build-ei` build hai image Go với tag hash và lưu ID. `cutover` lưu snapshot Helm/workload rồi scale pod cũ về 0, giữ PVC/release. Core stage seed subscriber idempotent, chạy tuần tự NF và gate NRF/PFCP/XDP. Non-RT stage chạy ICS trước producer; Near-RT stage chạy FlexRIC trước adapter. RAN stage yêu cầu EI fixture gate trước khi start UE và xApp. `experiment` chạy traffic thật và phân tích PCAP/KPM bằng analyzer hiện có.

Sau một run lỗi, dừng UE rồi gọi `scripts/k8s/lab.sh new-run` trước khi khởi động lại core/RAN. Lệnh này flush PCAP cũ và cấp run ID mới để artifact/KPM của lần chạy lại không trộn với lần trước.

Khi cần quay lại release cũ:

```bash
scripts/k8s/lab.sh rollback
```

Lệnh rollback scale pod mới về 0, chờ IP được giải phóng rồi phục hồi replica từ `artifacts/k8s/state/pre-cutover.json`. Không xóa release hoặc PVC mới. Image không cần build lại khi chỉ đổi values; ví dụ cập nhật UPF:

```bash
scripts/k8s/lab.sh rollout upf oai-lab-upf:<tag>
```

Khi chỉ cần restart UPF đang dùng cùng image: dừng UE (`kubectl --context=oai-lab -n oai-ran scale deployment/oai-nr-ue --replicas=0`), chờ pod UE xóa, rồi chạy `scripts/k8s/lab.sh restart-upf`. Lệnh này giải phóng IP N4 của pod UPF cũ, xóa ARP/neighbor N4 ở SMF, và đợi PFCP heartbeat sau khi pod mới chạy. `rollout upf` cũng thực hiện trình tự này. Sau đó tạo `new-run` và chạy lại stage RAN trước experiment; IP PDU của UE có thể thay đổi.

## Gate và giới hạn hiện tại

`gate-ei` kiểm tra ICS, producer, SMF subscription, job `ENABLED`, sau đó inject một notification giả có `UR-SEQN=999999999` để thử delivery/dedup. Fixture không phải bằng chứng runtime URR. `gate-ei --real` chỉ chấp nhận report khác fixture có byte thực ở adapter. Artifact gate nằm ở `artifacts/k8s/core/ei-gate.json`; thí nghiệm lưu trong `artifacts/experiments/<run-id>`.

OAI SMF v2.2.0 ở repo này chưa implement GET/DELETE individual Event Exposure subscription. Producer lưu UID pod SMF trong BoltDB: restart producer trên cùng pod SMF không POST lặp, còn SMF pod mới được subscribe lại. Nếu SMF tạo lại state mà UID không đổi, cần tái tạo SMF pod. HTTPS dùng CA nội bộ và server authentication; OAuth2/mTLS chưa bật. Minikube bridge CNI không được coi là thực thi NetworkPolicy.

ICS image `1.6.1` của lab trả HTTP 400 cho EI Job có `statusNotificationUri` dù trường này là tùy chọn trong API; cùng payload bỏ trường đó trả HTTP 201. Adapter vẫn có callback trạng thái nhưng bản triển khai này lấy trạng thái qua `GET /A1-EI/v1/eijobs/{id}/status` mỗi chu kỳ reconcile. Cần xác minh lại callback trạng thái khi nâng ICS; không dùng HTTP 400 như bằng chứng job đã tạo.

Mốc 3.5 chỉ PASS khi có URR thật trong callback OAI, producer artifact và adapter artifact, cùng một `(SEID, UR-SEQN)`. Mốc 4 cần thêm report PFCP được SMF chấp nhận, traffic UL/DL, KPM đồng thời, UPF restart và vòng đời down/up; một fixture PASS không thay thế những gate này.

### Ghi nhận lần chạy đầu trên bốn namespace

Run `20260928T154831Z-m35` đã PASS core, UE/PDU/E2/KPM và A1-EI fixture. Thí nghiệm thật FAIL: UPF log `Could not send PFCP_SESSION_REPORT_REQUEST, cause association not found for cp_fseid`; PCAP không có PFCP Session Report Request nên producer chỉ có fixture. Root cause là nhánh UPF nhận Association Setup Request từ SMF vẫn gọi `add_association()`, nhưng hàm đó chỉ đưa một candidate có sẵn vào association map. Patch `patches/oai-upf-cp-initiated-association.patch` tạo candidate cho CP-initiated peer trước khi promote. Đường receiver iperf cũ cũng không ghi CSV vì server nền không kết thúc; runner nay dùng `iperf -1` và đợi CSV. Cần build/rollout UPF đã sửa và chạy lại traffic trước khi đánh dấu Mốc 3.5 PASS.

Image UPF có thể build với `BUILD_CPUSET=16-17` trên máy hiện tại để compile trên hai E-core; Dockerfile mặc định vẫn dùng toàn CPU khi không truyền build arg. Tùy chọn build này được tách trong `patches/oai-upf-build-jobs.patch`.

Run `20260928T165903Z-m35`: lần đầu `up --stage ran` dừng ở KPM dù UE đã có PDU session. gNB đã hoàn tất E2 setup với pod FlexRIC cũ, nhưng Helm upgrade đổi `global.lab.currentRun` làm checksum toàn bộ lab thay đổi và restart FlexRIC sau khi gNB kết nối. Chart Near-RT nay bỏ `currentRun` khỏi checksum của FlexRIC. CLI kiểm tra SCTP E2 đang ESTABLISHED trước khi bật UE và restart xApp sau khi UE có PDU IP, vì xApp khởi động sớm chỉ ghi mẫu cell. Sau sửa, stage RAN PASS; `KPI_Metrics.csv` đã tăng lên 27 dòng khi kiểm tra. Log: `artifacts/k8s/diagnostics/m35-ran-e2-recovery.log`. Do nhiệt CPU đạt 99°C, gNB/UE/xApp được scale về 0 sau gate; cần chạy lại `up --stage ran` trước traffic thật. Đây mới là gate RAN/E2/KPM; chưa thay thế gate URR thật hoặc thực nghiệm UL/DL.

## Mapping từ backend cũ

| Việc cũ | Thành phần mới |
|---|---|
| 5gdeploy/Compose khởi động core | Helm release `oai-core` |
| Script host tạo bridge/pipework | Multus NAD theo namespace |
| Script host khởi động RFsim | Helm release `oai-ran` |
| Cụm Non-RT RIC/OOM trước đây | ICS tối giản trong `non-rt-ric` |
| Script thí nghiệm host | `lab.sh experiment` và PVC artifact theo namespace |

### Tiếp tục kiểm chứng ngày 2026-09-29

Run `20260928T172739Z-m35` đã xác nhận Mốc 3.5 bằng URR thật, không phải fixture. PCAP `artifacts/k8s/diagnostics/m35-live-urr-ran-restart.pcap` có PFCP Session Report Request với SEID 1, UR-SEQN 3, DL volume 681528 byte/438 gói và Session Report Response Cause 1 (accepted). Cùng report xuất hiện trong raw QOS_MON của SMF, normalized producer và artifact của adapter; bản ghi đối chiếu nằm tại `artifacts/k8s/diagnostics/m35-real-report-pipeline/real-report-seid1-seq3.json`. SMF log trả HTTP 204. Core, NRF registration, PFCP heartbeat, XDP generic trên N3/N6, DN route, ICS producer và EI Job vẫn hoạt động. RAN/E2/KPM gate cũng PASS sau khi bật lại stage ran; UE nhận PDU IP `10.1.0.3`.

Mốc 4 chưa PASS. Smoke DL từ DN báo đã gửi datagram nhưng UE receiver không ghi CSV/dữ liệu nhận; vì vậy URR DL counter chỉ chứng minh UPF/SMF báo cáo được lượng traffic quan sát ở dataplane, không chứng minh traffic tới ứng dụng UE. PFCP Create PDR/FAR trong PCAP đặt UE IP `10.1.0.2` và N3 tunnel endpoint `172.30.23.20`; UPF log ghi ARP entry cho N3 peer. Chưa có packet capture/counter tại N3 đủ để kết luận gói bị rơi ở encap, redirect, gNB hay UE, nên root cause user-plane vẫn mở. Cần phép thử kế tiếp có iperf server chạy foreground qua một phiên `kubectl exec` còn mở, sender DL ngắn, và đo đồng thời RX của `oaitun_ue1`, N3 TX/GTP-U cùng receiver CSV.

Sau khi RAN/E2/KPM gate vừa PASS, CPU package đạt 99°C. Để máy nguội, gNB, UE và xApp đã scale về 0; core, ICS/producer, FlexRIC và adapter được giữ nguyên. Chưa chạy traffic 10 Mbit/s × 120 giây, restart UPF, hay chu kỳ down/up. `artifacts/k8s/milestones.json` ghi Mốc 3.5 PASS và Mốc 4 PARTIAL, không đánh dấu migration hoàn tất.

The final `gate-ei --real` recheck after `up --stage ran` failed because that stage had most recently delivered the `UR-SEQN=999999999` fixture to the adapter; there was no new real report after this stage. The earlier real record remains independently verifiable in the saved PFCP/raw/producer/adapter evidence above. The real gate now searches adapter report history for a non-fixture URR received within five minutes, so a newer fixture no longer hides a fresh real report and an old report cannot satisfy a new run.
