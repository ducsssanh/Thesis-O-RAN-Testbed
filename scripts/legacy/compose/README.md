# Backend legacy Compose/host

Đây là lớp automation NIST đã port cho Docker Compose và các process chạy trực
tiếp trên host. Backend Kubernetes không gọi các file trong thư mục này; chúng
được giữ để đối chiếu và rollback.

Các script chạy bằng **Bash**, từ thư mục làm việc bất kỳ. Ví dụ dưới đây chạy tại thư mục gốc `Codebase`.

## Đường dẫn dùng chung

`env.sh` khai báo đường dẫn; nạp file này không tạo thư mục hay chạy dịch vụ.

- Mã nguồn: `src/oai-upf`, `src/5gdeploy`, `src/flexric`, `src/oai-ran`.
- Cấu hình: `configs/core`, `configs/flexric`, `configs/gnb`, `configs/ue`.
- Cấu hình Core dùng chung: `configs/core/options.yaml`.
- Docker Compose sinh ra: `compose/core`.
- Log hoạt động: `artifacts/logs/{core,flexric,gnb,ue}`.
- Kết quả thí nghiệm: `artifacts/experiments/<run-id>`; `latest` trỏ tới lần chạy gần nhất.
- Patch hỗ trợ build: `patches/ran`, `patches/flexric`.

Có thể đặt `CONFIG_ROOT`, `CORE_OPTIONS`, `ARTIFACT_ROOT`, `LOG_ROOT`, `EXPERIMENT_ROOT`, `CORE_COMPOSE_DIR`, `RAN_SRC`, `UPF_SRC`, `FLEXRIC_SRC`, `DEPLOY_SRC` bằng biến môi trường. Dùng đường dẫn tuyệt đối. Các script con kế thừa các biến này.

## Những phần đã port, theo thứ tự

| Nhóm | Nguồn logic | Lệnh mới |
|---|---|---|
| 1 | Core `oai_upf_profile.sh`, `build_research_upf.sh` | `build-upf.sh`, `lib/oai-upf-profile.sh` |
| 2 | Core generate/run/stop | `configure-core.sh`, `start-core.sh`, `stop-core.sh` |
| 3 | FlexRIC build/config/run | `build-flexric.sh`, `configure-flexric.sh`, `start-flexric.sh` |
| 4 | OAI gNB/UE build/config/run | `build-ran.sh`, `configure-gnb.sh`, `configure-ue.sh`, `start-gnb.sh`, `start-ue.sh` |
| 5 | UE namespace setup/revert | `setup-ue-network.sh`, `stop-ue-network.sh` |
| 6 | Traffic Core→UE / UE→Core | `traffic-dl.sh`, `traffic-ul.sh` |
| 7 | KPM xApp ghi CSV | `start-xapp.sh` |
| 8 | Runner KPM/URR | `run-experiment.sh` |

`stop-gnb.sh`, `stop-ue.sh`, `stop-flexric.sh`, `stop-stack.sh` phục vụ dừng thủ công và cleanup của runner. Thư mục `lib/` chứa helper của backend legacy này.

Bản port Core này dùng **5gdeploy** (bao gồm OAI, Free5GC và Open5GS qua 5gdeploy). Native Open5GS ngoài Docker không có trong các script Core nguồn được yêu cầu port. Cấu hình hiện tại chọn `5gdeploy-oai`.

## Chuẩn bị và build

Mã nguồn hiện là snapshot không có `.git`; commit gốc và trạng thái snapshot có trong `manifests/`. Script không tự clone phiên bản mới. Với UPF snapshot, build argument `GIT_COMMIT=snapshot` thể hiện rằng script không xác minh được Git HEAD của thư mục nguồn. Khi có `.git`, script lấy HEAD và cập nhật các submodule như trước.

Cần có toolchain và dependency của nguồn đang dùng. Script FlexRIC cũ yêu cầu GCC ≥13 và SWIG ≥4.1; RAN cũ yêu cầu GCC ≥13. Các lệnh build mới dùng compiler hiện được cấu hình trên máy, không tự đổi compiler mặc định. Cần `cmake`, `make`, `ninja` cho các bước build tương ứng; ZMQ cần `libzmq` và `libczmq` đã cài.

Tùy chọn `--install-deps` của `build-flexric.sh` cài các gói build cơ bản bằng apt; tùy chọn tương tự của `build-ran.sh` gọi `build_oai -I`. Chúng không thay thế việc chuẩn bị GCC/SWIG phù hợp. Các bước clone, nâng compiler toàn hệ thống, cài InfluxDB/Grafana trong bộ `full_install.sh` cũ không được chạy tự động bởi lệnh build mới.

Core cần Docker truy cập được, **Mike Farah yq v4**, Node.js/Corepack và dependency đã khóa của 5gdeploy:

```bash
(cd src/5gdeploy && corepack pnpm install --frozen-lockfile)

# 1. Build UPF theo options.yaml
bash scripts/legacy/compose/build-upf.sh

# 2. Sinh Core config (có cấu hình forwarding/NAT/SCTP trên host)
bash scripts/legacy/compose/configure-core.sh

# 3. Build FlexRIC; cuối bước này tự sinh flexric.conf
bash scripts/legacy/compose/build-flexric.sh

# 4. Build UE rồi gNB trong cùng một cây mã nguồn
bash scripts/legacy/compose/build-ran.sh
bash scripts/legacy/compose/configure-gnb.sh
bash scripts/legacy/compose/configure-ue.sh
```

`configure-core.sh` tạo 10 subscriber như script cũ. Compose được sinh và patch trong thư mục tạm trước khi thay thế `compose/core`; bản Compose trước đó được giữ trong `compose/core.previous.*`. Hãy dừng Core trước khi sinh lại cấu hình đang triển khai. Việc sinh Core vẫn cập nhật scenario và danh sách SIM trong `src/5gdeploy` như logic nguồn.

`configure-ue.sh` mặc định cấu hình UE 3, 2, 1; có thể truyền danh sách, ví dụ `bash scripts/legacy/compose/configure-ue.sh 1 2 3 4`. Với UE lớn hơn 3, helper ghi subscriber vào `sims.tsv`; cần sinh lại Core trước khi triển khai. Nếu muốn dùng UE ngoài phạm vi 1–10, phải cập nhật `UE_NUMBERS` trong `configure-core.sh` để lần sinh Core tiếp theo không bỏ subscriber đó.

Các lựa chọn build giữ mặc định:

- E2AP `E2AP_V3`, KPM `KPM_V3_00`, cổng E2 `36421`.
- FlexRIC `NONE_XAPP`, Release, prefix `src/flexric/build/flexric_libraries`.
- RAN `SIMU`, `--ninja`, UE `--nrUE`, gNB `--gNB --build-e2`, telnet được build.
- `CLEAN_INSTALL=false`, `DEBUG_SYMBOLS=false`, `APPLY_PATCHES=true`.
- RAN: `RADIO_TYPE=SIMU|ZMQ|USRP`, `TELNET_SERVER=true`, `NRSCOPE_GUI=false`.
- FlexRIC: `BUILD_JOBS` mặc định bằng `nproc`.

Ví dụ `DEBUG_SYMBOLS=true bash scripts/legacy/compose/build-ran.sh`. Clean RAN chỉ thực hiện ở lần build UE đầu tiên, để lần build gNB không xóa binary UE trong thư mục chung. Patch đã áp dụng được giữ nguyên; patch xung đột báo lỗi thay vì `git restore` mã đang sửa.

## Chạy tự động

Xem kế hoạch, không khởi động dịch vụ hay tạo thư mục kết quả:

```bash
bash scripts/legacy/compose/run-experiment.sh --dry-run --smoke
```

Sau khi build và cấu hình xong:

```bash
bash scripts/legacy/compose/run-experiment.sh
```

Runner dùng `sudo` cho các thao tác cần quyền, khởi động chrony, Core, FlexRIC, gNB, UE, xApp, bắt PFCP, tạo traffic DL/UL và thu kết quả. Cần các công cụ runtime liệt kê trong runner, gồm `dumpcap`, `tshark`, `capinfos`, `iperf` **phiên bản 2**, `rg`, `rsync`, `setsid`, `ip`, `iptables`, `python3`, `script` và `yq`.

- `--ue 2`: chọn UE.
- `--restart`: dừng stack hiện có trước khi chạy.
- `--keep-running`: giữ Core/FlexRIC/gNB/UE sau khi kết thúc; xApp và capture vẫn dừng.
- `--run-id ten-lan-chay`: đặt tên thư mục kết quả mới.
- `--capture-interface IF`: chọn interface bắt PFCP.
- `--help`: xem thời lượng, tốc độ traffic và các tùy chọn khác.

`--smoke` dùng traffic ngắn 1M × 10 giây mỗi chiều. Với ngưỡng URR hiện tại **104857600 byte**, lượng traffic đó có thể không tạo Usage Report theo ngưỡng; runner vẫn kiểm tra URR và có thể báo thất bại. Lần kiểm tra URR đầy đủ nên dùng tham số mặc định 10M × 120 giây mỗi chiều. Giá trị `enable_usage_reporting: false` và `build_local_image: false` được tôn trọng đúng trong profile mới.

## Chạy từng thành phần

```bash
bash scripts/legacy/compose/start-core.sh
bash scripts/legacy/compose/start-flexric.sh --background
bash scripts/legacy/compose/start-gnb.sh --background
bash scripts/legacy/compose/start-ue.sh --background 1

# Ở terminal riêng; mặc định mỗi 1000 ms, ghi artifacts/logs/flexric/KPI_Metrics.csv
bash scripts/legacy/compose/start-xapp.sh 1000

# UE phải có PDU session trước khi tạo traffic
bash scripts/legacy/compose/traffic-dl.sh 1 10M 120
bash scripts/legacy/compose/traffic-ul.sh 1 10M 120

# Dừng UE 1, gNB, FlexRIC rồi Core
bash scripts/legacy/compose/stop-stack.sh 1
```

Bỏ `--background` để chạy foreground. `start-ue.sh` tự gọi `setup-ue-network.sh`; không cần thiết lập namespace riêng trước. Có thể chạy riêng `setup-ue-network.sh 1` và `stop-ue-network.sh 1` khi xử lý mạng. Với nhiều UE, dừng từng UE bằng `stop-ue.sh N`; `stop-stack.sh N` chỉ dọn UE được chọn rồi dừng các thành phần chung. Lệnh dừng radio/RIC khớp đường dẫn config của repo này.

## Kiểm tra bản port

```bash
python3 tests/test_ported_scripts.py
bash tests/test_oai_upf_profile.sh
```

Test tạo cấu hình trong thư mục tạm, kiểm tra tham số build/start, profile, namespace, dry-run và cả vòng đời runner bằng lệnh giả lập. Các test không build nguồn thật, không chạy Docker thật, không sửa mạng host và không xác minh được kết nối RF/E2/PFCP thực tế.

Các helper và patch được chuyển từ bộ NIST testbed tại `scripts/legacy/` và bản checkout gốc cục bộ `O-RAN-Testbed-Automation`; thông báo nguồn NIST được giữ trong các file dẫn xuất. `tests/run_kpm_urr_experiment.sh` hiện chuyển tiếp tới runner mới để giữ lệnh gọi cũ.

### Khi build RAN báo khác biệt ở file xApp CSV

`build-ran.sh` dùng chế độ `flexric-agent` cho FlexRIC nhúng trong OAI: chỉ chuẩn bị giới hạn đường dẫn của agent; không đồng bộ mã xApp từ FlexRIC standalone. OAI liên kết các thư mục `agent/lib/sm/util`, còn CSV xApp được build bởi `build-flexric.sh`. Hai bản CSV có thể khác nhau mà không cản trở build RAN.

Nếu thông báo nguồn trỏ về checkout cũ, kiểm tra biến môi trường của terminal. Chạy từ Codebase để dùng lại đường dẫn mặc định của repo:

```bash
env -u CODEBASE_ROOT -u RAN_SRC -u PATCH_ROOT \
    CLEAN_INSTALL=true bash scripts/legacy/compose/build-ran.sh
```

Script in đường dẫn RAN và FlexRIC nhúng trước khi patch/build. Cả hai phải nằm trong cây nguồn dự định sử dụng.

### Quyền sudo khi chạy nền

Launcher gNB/UE xác thực sudo trên terminal hiện tại, cấp quyền rồi mới gọi `setsid`. Điều này tránh phụ thuộc vào sudo timestamp của terminal cũ sau khi tách phiên. Các biến đường dẫn của Codebase được truyền rõ ràng qua sudo. FlexRIC vẫn chạy dưới tài khoản hiện tại. Chế độ nền gNB/UE tắt ImScope GUI; dùng foreground nếu cần GUI.

Test cho thứ tự cấp quyền và tách phiên (sudo giả lập, không khởi động radio):

```bash
python3 tests/test_background_sudo.py
```
