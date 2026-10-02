# Chạy thử OAI eBPF UPF trong Codebase

Cập nhật audit 26/09/2026: trước khi dùng các bước chạy dưới đây, cần xử lý sự không nhất quán BPF/capability trong `configure-core.sh`. Script chưa truyền `--oai-upf-bpf=true` cho 5gdeploy, nên Compose hiện chỉ thêm NET_ADMIN cho UPF dù YAML bật eBPF. Xem mục 8 của [BUILD-FROM-SCRATCH.md](BUILD-FROM-SCRATCH.md). Hướng dẫn cũ chưa tính thiếu sót này; audit mới chưa sửa runtime script.

Kiểm tra ngày 2026-09-24. Các lệnh dưới đây để người vận hành thực hiện; lần audit này chưa khởi động stack, chưa build lại và chưa sửa cấu hình mạng. Triển khai dùng Docker Compose cho core, tiến trình host cho RAN/FlexRIC và namespace cho UE. Máy có interface Kubernetes nhưng runner này không dùng Kubernetes.

## 1. Chuẩn bị

Chạy từng khối, chỉ tiếp tục khi lệnh trước thành công. Dùng một terminal Bash:

```bash
bash
cd /home/ducsssanh/6G/O-RAN/DATN/Codebase
export CODEBASE_ROOT="$PWD"
unset RAN_SRC UPF_SRC FLEXRIC_SRC DEPLOY_SRC CONFIG_ROOT CORE_OPTIONS
unset CORE_COMPOSE_DIR PATCH_ROOT FLEXRIC_PREFIX LOG_ROOT ARTIFACT_ROOT EXPERIMENT_ROOT
sudo -v
docker info >/dev/null
yq --version
gcc --version
swig -version
```

Cần Mike Farah yq v4, GCC/toolchain phù hợp với RAN/FlexRIC (hướng dẫn testbed yêu cầu GCC >=13, SWIG >=4.1), Docker Compose, Node/Corepack. Runtime cần iperf2, iproute2, iptables, chrony, dumpcap/tshark/capinfos, rsync, ripgrep, Python3, setsid và script. `iperf3` không thay thế được `iperf` trong script hiện tại. `bpftool` dùng cho kiểm chứng XDP.

```bash
(cd src/5gdeploy && corepack pnpm install --frozen-lockfile)
python3 tests/test_ported_scripts.py
bash tests/test_oai_upf_profile.sh
python3 tests/test_background_sudo.py
```

## 2. Build và sinh lại cấu hình

Giữ profile hiện có: `core_to_use/upf_to_use: 5gdeploy-oai`, `datapath: xdp-skb`, `enable_usage_reporting: true`, image `oai-upf-research:local`, threshold `104857600`. Threshold này hiện là giá trị kiểm tra/metadata, chưa được helper truyền vào SMF; chưa đổi sang ngưỡng nhỏ rồi kỳ vọng SMF làm theo.

Nếu đang chạy stack này, dừng trước bằng `bash scripts/legacy/compose/stop-stack.sh 1`. Lệnh configure-core thay đổi forwarding/NAT/SCTP trên host và sinh lại scenario/subscriber; cần kiểm tra thông báo lỗi trước khi tiếp tục.

```bash
bash scripts/legacy/compose/build-upf.sh
bash scripts/legacy/compose/build-flexric.sh
RADIO_TYPE=SIMU bash scripts/legacy/compose/build-ran.sh
bash scripts/legacy/compose/configure-core.sh
bash scripts/legacy/compose/configure-flexric.sh
RADIO_TYPE=SIMU bash scripts/legacy/compose/configure-gnb.sh
RADIO_TYPE=SIMU bash scripts/legacy/compose/configure-ue.sh 1
docker compose -f compose/core/compose.yml config --quiet
```

Máy đã có image và binary; có thể bỏ bước build nếu giữ nguyên source và biết artifact khớp source. Build lại là cách tránh dùng binary cũ. Script sẽ nhận ra các patch nhỏ đã áp dụng; không tự `git apply` các patch tổng hợp lần nữa. Nếu cache CMake báo checkout cũ, dùng `CLEAN_INSTALL=true` với đúng script build thành phần đó; kiểm tra đường dẫn source được in trước khi chạy clean.

Compose hiện lưu một số đường dẫn checkout cũ, vì vậy nên sinh lại. `configure-core.sh` sinh địa chỉ AMF trước, `configure-gnb.sh` mới đọc các địa chỉ đó.

## 3. Kiểm tra core và XDP trước

```bash
bash scripts/legacy/compose/start-core.sh
docker compose -f compose/core/compose.yml ps
docker logs smf 2>&1 | rg -i 'pfcp|association|error|fail'
docker logs upf1 2>&1 | rg -i 'xdp|bpf|urr|association|error|fail'

UPF_PID=$(docker inspect -f '{{.State.Pid}}' upf1)
test "$UPF_PID" -gt 0 && sudo nsenter -t "$UPF_PID" -n bpftool net
```

Đợi NF sẵn sàng và PFCP association thành công. `bpftool net` phải cho thấy XDP program trên interface thích hợp; kiểm tra lại sau khi UE tạo session nếu một phần chương trình được nạp theo session. Log attach có `mode=native ...` hoặc `mode=SKB ...` và log consumer có `URR report ring buffer consumer started`. Đừng lấy trạng thái container `Up` làm bằng chứng datapath hoạt động.

Nếu lỗi attach/verifier, xem toàn bộ `docker logs upf1` trước. Profile tên `xdp-skb` chưa ép SKB: `ProgramLifeCycle.hpp` thử native rồi fallback SKB khi native không hỗ trợ. Native thành công vẫn có thể dùng để kiểm tra eBPF; chỉ cần bổ sung lựa chọn mode nếu thí nghiệm yêu cầu SKB cố định.

Nếu gNB không kết nối AMF, so `configs/core/get_amf_address.txt` với `configs/gnb/gnb.conf` và `ip -br address`: cấu hình hiện kỳ vọng địa chỉ host N2 `192.168.62.1`, N3 `192.168.63.1`. Chúng phải tồn tại sau khi core/network được dựng.

## 4. Chạy thí nghiệm tự động

Runner tự khởi động core, FlexRIC, gNB, capture PFCP trước UE, xApp và traffic. Dừng core vừa thử để runner bắt đầu từ trạng thái sạch:

```bash
bash scripts/legacy/compose/stop-core.sh
bash scripts/legacy/compose/run-experiment.sh --dry-run
bash scripts/legacy/compose/run-experiment.sh --ue 1 --keep-running
```

Nếu còn thành phần của stack đang chạy, dừng bằng `stop-stack.sh 1` trước hoặc dùng `--restart` khi chủ động muốn runner dừng và chạy lại stack này. Không chạy song song với bộ start thủ công khác.

Mặc định traffic 10M trong 120 giây mỗi chiều (~150 MB dữ liệu phát/chiều), phù hợp hơn `--smoke` khi kiểm tra ngưỡng 100 MiB. Đây là offered traffic; lượng thực tế qua UPF phải được đo. Smoke 1M x 10 giây không đủ vượt ngưỡng và có thể fail bước URR dù kết nối hoạt động.

Xem kết quả sau khi runner kết thúc:

```bash
cat artifacts/experiments/latest/metadata/result.env
cat artifacts/experiments/latest/capture/pfcp_urr_config.csv
cat artifacts/experiments/latest/capture/pfcp_urr.csv
head artifacts/experiments/latest/kpm/KPI_Metrics.csv
tshark -r artifacts/experiments/latest/capture/pfcp.pcapng \
  -Y 'pfcp' -V > /tmp/codebase-pfcp-decoded.txt
```

Tiêu chí đạt:

- UE log có `Received PDU Session Establishment Accept` và IP PDU.
- Iperf server có dữ liệu nhận thật ở cả UL/DL; không chỉ dựa vào exit code client.
- XDP program đã attach và mode thực tế được ghi lại.
- Capture có Create URR với trigger/ngưỡng thực tế.
- Capture có Session Report Request chứa Usage Report từ UPF và response của SMF với cause chấp nhận.
- Counter UL/DL/total hợp lý; KPM CSV có mẫu dữ liệu.

Runner có kiểm tra URR nhưng không thay thế việc xem response/cause từ SMF và packet loss ở iperf receiver. Nếu runner fail, xem `metadata/current_stage.txt`, `automation/`, `core/upf1.log`, `core/smf.log`, `gnb/`, `ue/`, và `capture/tshark_*.log`.

Với `--keep-running`, có thể phát thêm traffic sau thí nghiệm (capture của runner đã dừng, nên traffic bổ sung không nằm trong pcap vừa thu):

```bash
bash scripts/legacy/compose/traffic-dl.sh 1 10M 120
bash scripts/legacy/compose/traffic-ul.sh 1 10M 120
bash scripts/legacy/compose/stop-stack.sh 1
```

## 5. Nếu gặp lỗi cũ

- UE timeout RF simulator: kiểm tra gNB còn sống và `ss -ltnp` có port 4043; xem `configs/ue/get_rfsim_server_address.txt`. Launcher gNB hiện đồng bộ endpoint sang UE. Địa chỉ host cũ `192.168.1.14` không phải địa chỉ Wi-Fi hiện tại. Không dùng loopback host cho UE nằm trong namespace riêng.
- E2 timeout/assertion: chạy FlexRIC trước gNB; kiểm tra log `E2 SETUP-REQUEST`, RIC IP `127.0.0.1`, E2AP v3/KPM v3 và port 36421 ở hai phía.
- Không có Usage Report: kiểm tra Create URR trước, rồi byte thực nhận và log consumer; implementation chỉ hỗ trợ một URR/session.
- Runner báo sai threshold: đọc threshold thực trong capture. Helper `scripts/legacy/compose/lib/oai-upf-profile.sh` hiện chỉ ghi giá trị mong đợi; không thêm một YAML key SMF chưa hỗ trợ. Muốn ngưỡng tùy chỉnh cần kiểm tra khả năng cấu hình của đúng SMF image v2.2.0, sau đó sửa generator hoặc build SMF tùy chỉnh. Source SMF chưa nằm trong workspace này.

Danh mục patch: [LOCAL-PATCHES.md](LOCAL-PATCHES.md).
