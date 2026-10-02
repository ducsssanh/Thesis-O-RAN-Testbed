# Đánh giá eBPF UPF và các patch

> codebase này đã chạy được ebpf upf chưa? đã patch những gì so với toàn bộ các repo gốc của oai?

<details><summary>3 previous messages</summary>

> Mình sẽ kiểm tra cấu hình UPF/eBPF, các dấu hiệu build hoặc chạy thử, rồi đối chiếu thay đổi trong workspace với các repo OAI gốc.
>
> Cấu hình hiện đã bật eBPF/XDP-SKB và máy có image UPF build sẵn. Tuy nhiên hiện không có container UPF chạy; log UE lưu lại cho thấy lỗi kết nối RF simulator nên chưa đủ bằng chứng xác nhận traffic đi xuyên hệ thống. Mình cũng thấy nguồn là snapshot không có `.git`, nên cần phân biệt patch lưu trong workspace với những thay đổi có thể đã được commit từ trước.
>
> Đã tìm được checkout Git gốc trên máy: UPF có commit riêng `00b7485` bổ sung luồng **eBPF URR → PFCP Usage Report gửi SMF**. Vì thay đổi đã nằm trong commit nên file `oai-upf-working-tree.patch` rỗng không có nghĩa là UPF chưa được sửa. Một chi tiết nữa: profile tên `xdp-skb`, nhưng code attach thử native XDP trước rồi mới fallback sang SKB.
</details>

**Codebase đã tích hợp eBPF UPF và có Docker image build sẵn, nhưng chưa đủ bằng chứng để kết luận đã chạy thành công end-to-end.** Có patch riêng cho UPF, chủ yếu để đưa số liệu URR từ eBPF lên PFCP gửi về SMF.

**Trạng thái hiện tại**

| Hạng mục | Kết quả kiểm tra |
|---|---|
| Cấu hình eBPF | `enable_bpf_datapath: true` trên cả `upf1`, `upf140`, `upf141` |
| Usage reporting | Đã bật URR ở UPF và usage reporting ở SMF |
| Docker image | Có `oai-upf-research:local`, build ngày 03/09/2026, nhãn commit `00b7485` |
| UPF đang chạy | Không có container UPF đang chạy |
| Traffic UE ↔ DN | Chưa thấy kết quả iperf/capture chứng minh thành công trong artifacts |
| Log lần chạy lưu lại | UE không kết nối được RF simulator `192.168.1.14:4043`; gNB có SCTP timeout và assertion E2 agent |

Cấu hình nằm ở [options.yaml](./configs/core/options.yaml:30), lỗi UE ở [ue1_stdout.txt](./artifacts/logs/ue/ue1_stdout.txt:79). Đây là bằng chứng lần chạy lưu lại chưa thông; **không đủ để quy lỗi cho UPF**.

**Các thay đổi so với nguồn gốc**

Workspace là snapshot không có `.git`. Mình đã đọc manifests/patch và tìm được checkout Git cũ trên máy để xác minh thêm lịch sử UPF. Baseline dưới đây là các commit được lưu, không phải upstream mới nhất.

| Thành phần | Baseline | Những thay đổi chính |
|---|---|---|
| **OAI UPF** | Upstream `9e93b63` → commit riêng `00b7485` | Nối eBPF URR events với PFCP Usage Report; sửa cấu trúc map/counter, trigger và xử lý thời gian |
| **OAI RAN — gNB/UE** | `26efcc4989` | E2AP v3/KPM v3; sửa ID gNB/DU; giữ độ chính xác PDCP volume; mở rộng SST; tương thích build |
| **FlexRIC** | `ef6d722f` | Truyền E2 node ID vào callback xApp; cải tiến KPM; thêm CSV/InfluxDB; hỗ trợ tắt database |
| **5gdeploy — của NIST** | `c842a50e` | Đổi dải IP, gNB ID, TAC; bổ sung scenario testbed; cải thiện tải nguồn |
| **Lớp scripts/config** | Port từ NIST testbed | Build/start/stop, chọn datapath, namespace UE, traffic DL/UL, runner thu KPM và PFCP |

Cụ thể:

**1. UPF: patch đã được commit, nên file patch rỗng dễ gây hiểu nhầm.**

Commit `00b7485` — `feat(upf): emit PFCP usage reports from eBPF URR events` — sửa **13 file, +404/−126 dòng**:

- Thêm `UrrReportConsumer` đọc BPF ring buffer.
- Tạo PFCP Session Report Request chứa URR ID, sequence, trigger, byte/packet UL–DL–total và thời gian.
- Đẩy yêu cầu qua task N4; cấp transaction ID tại task gửi.
- Đồng bộ cấu trúc map giữa userspace/kernel, sử dụng SEID làm khóa.
- Dùng monotonic clock cho phép tính thời gian trong datapath.
- Giới hạn MVP: **mỗi PFCP session chỉ một URR**.

Xem [UrrReportConsumer.cpp](./src/oai-upf/src/upf_app/control/UrrReportConsumer.cpp:108).

Mình đối chiếu **350 file tracked của repo UPF chính** trong snapshot với commit này: không thấy khác biệt. `oai-upf-working-tree.patch` rỗng vì thay đổi đã commit; không phải UPF nguyên bản chưa sửa. eBPF datapath vốn đã có trong baseline, phần bổ sung chính ở đây là luồng reporting.

**2. RAN:**

- Default E2AP `V2 → V3`, KPM `V2_03 → V3_00`.
- Sửa việc gán nhầm `nb_id` và `cu_du_id` ở DU.
- PDCP volume UL/DL chuyển từ integer sang real, vẫn đơn vị Mb, tránh mẫu nhỏ bị làm tròn về 0.
- SST mở từ `1..4` sang `0..255`.
- Sửa tương thích OpenSSL, C++ trong ZMQ và nhận diện Linux Mint khi build.

Chi tiết: [oai-ran-working-tree.patch](./patches/oai-ran-working-tree.patch).

**3. FlexRIC:**

- Callback xApp nhận thêm `global_e2_node_id_t` để biết số liệu đến từ node nào.
- Thêm `metrics_factory`, xApp ghi CSV và InfluxDB.
- Điều chỉnh label/hiển thị KPM, lọc S-NSSAI theo `SST/SD`, bỏ qua report style không hỗ trợ.
- Thêm `NONE_XAPP` để chạy không cần database.
- Tăng giới hạn đường dẫn config `128 → 1024`.

Chi tiết: [flexric-working-tree.patch](./patches/flexric-working-tree.patch).

**4. 5gdeploy và automation:**

- Dải IP mặc định `172.25.192.0/18 → 172.25.160.0/20`.
- gNB ID khởi đầu `1 → 3584`; TAC `5 → 7`.
- Download có retry và fallback Git.
- Thêm scenario `orantestbed`, profile UPF local và runner KPM/URR.
- `traffic-dl.sh` chạy iperf2 từ `dn_internet` về IP PDU session trong namespace UE.

Chi tiết: [5gdeploy-working-tree.patch](./patches/5gdeploy-working-tree.patch), [scripts/README.md](./scripts/README.md).

**Hai điểm cần phân biệt khi đánh giá “đã chạy được”:**

- Profile gọi là `xdp-skb`, nhưng [code attach](./src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp:342) thử **native XDP trước**, chỉ fallback SKB khi driver báo không hỗ trợ. Tên profile chưa chứng minh mode thực tế.
- `volume_threshold_bytes: 104857600` được profile đọc và ghi metadata; helper hiện không đưa giá trị đó vào cấu hình SMF. Cần kiểm tra Create URR trong PFCP để xác nhận ngưỡng thực tế.

Để xác nhận hoàn tất, còn cần một lần chạy có **XDP attach thành công, PDU session thành công, traffic UL/DL và PFCP Usage Report nhận tại SMF**. Mình chưa khởi động lại stack hay thay đổi mã nguồn trong lần kiểm tra này.

> tóm tắt ngắn gọn lại thành mấy gạch đầu dòng thôi. thành phần nào đã có, thành phần nào còn thiếu, cái nào đã được có patch?

- **Đã có:** mã nguồn eBPF/XDP UPF, Docker image build sẵn, cấu hình bật eBPF/URR; OAI gNB/UE, FlexRIC, xApp KPM và script traffic DL/UL.
- **UPF đã patch:** đọc URR events từ eBPF và gửi **PFCP Usage Report về SMF**; sửa map/counter/thời gian. Hiện hỗ trợ **1 URR/session**.
- **RAN đã patch:** E2AP/KPM v3, sửa ID gNB/DU, tăng độ chính xác PDCP volume, mở rộng SST và sửa tương thích build.
- **FlexRIC đã patch:** thêm node ID vào callback, xuất KPM ra CSV/InfluxDB, lọc slice và tùy chọn tắt database.
- **5gdeploy/scripts đã patch:** IP/TAC/gNB ID, scenario testbed, profile UPF, build/start/stop và runner thu KPM/PFCP.
- **Còn thiếu xác minh:** chạy xuyên suốt UE ↔ UPF ↔ DN, traffic UL/DL thành công và SMF nhận Usage Report. Lần kiểm tra trước không có UPF chạy; log UE/gNB còn lỗi kết nối.
- **Còn thiếu hoàn thiện:** ép đúng chế độ XDP-SKB và nối tham số ngưỡng URR trong cấu hình vào SMF.

> implementation hiện tại như thế nào? có sử dụng k8s không?

**Hiện tại triển khai bằng Docker Compose kết hợp tiến trình chạy trực tiếp trên host, không dùng Kubernetes.**

- **5G Core:** 5gdeploy sinh cấu hình Docker Compose; các NF core và UPF chạy trong container. UPF dùng image tùy chỉnh `oai-upf-research:local`.
- **gNB/UE:** build từ OAI RAN, chạy trực tiếp trên host bằng script; UE sử dụng network namespace. Cấu hình đang hướng tới RF simulator.
- **FlexRIC/xApp:** chạy trực tiếp trên host; xApp nhận KPM qua E2 và có chức năng ghi CSV/InfluxDB.
- **Datapath UPF:** eBPF/XDP xử lý gói trong kernel. Code thử native XDP trước, fallback SKB khi không được hỗ trợ.
- **Usage reporting:** eBPF đếm traffic → BPF ring buffer → `UrrReportConsumer` trong userspace → task N4 → PFCP Usage Report gửi SMF.
- **Điều phối/thí nghiệm:** Bash scripts build/start/stop, tạo traffic iperf2, bắt PFCP và thu KPM; chưa có lớp orchestration bằng K8s.

Đây là cấu trúc implementation hiện có; chạy end-to-end thành công vẫn chưa được xác minh.

> hướng dẫn tao làm nốt các bước tiếp theo và chạy thử, đồng thời chỉ ra chính xác các file patch đã được tạo local mà không phải có sẵn trong repo của oai

<details><summary>4 previous messages</summary>

> Mình sẽ kiểm tra lại script và cấu hình để đưa ra thứ tự chạy thử cụ thể, đồng thời tách rõ patch tự tạo với patch vốn có trong OAI. Mình cũng sẽ kiểm tra các chỗ còn thiếu để tránh hướng dẫn chạy bằng cấu hình chưa khớp.
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `rg --files -g AGENTS.md -g '*.patch' patches; cat scripts/start-core.sh scripts/start-gnb.sh scripts/start-ue.sh; cat scripts/run-experiment.sh`
> - Ran `cat scripts/env.sh; rg -n '192\.168|127\.0|10\.|172\.|ric|amf|interface' configs/gnb/gnb.conf configs/flexric/flexric.conf; cat configs/gnb/radio_type.txt configs/ue/radio_type.txt; rg -n 'get_|IP|INTERFACE|RADIO_TYPE|source' scripts/configure-gnb.sh scripts/configure-flexric.sh; cat scripts/lib/apply-patches.sh; ls -l patches/*working-tree.patch`
> - Ran `docker ps -a --format '{{.Names}} {{.Status}}'; ip -br address; command -v yq docker corepack pnpm iperf tshark dumpcap capinfos bpftool; rg -n 'image:|enable_usage|enable_bpf|enable_urr' compose/core/compose.yml compose/core/cp-cfg/smf.yaml compose/core/up-cfg/upf1.yaml; cat manifests/oai-upf.submodules; rg -n 'volume_threshold' scripts/configure-core.sh scripts/lib/* src/5gdeploy/oai/*`
> - Ran `git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/5G_Core_Network/OAI_UPF_Research log --format='%h %s' upstream/develop..00b7485; git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/5G_Core_Network/OAI_UPF_Research show --format=fuller --stat 00b7485; rg -n 'Attached|attach|mode_str' src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp; sed -n '1,125p' compose/core/compose.sh; rg -n 'capture|KPM_DIR|METADATA_DIR|smoke|run-id' scripts/run-experiment.sh | head -30`
> - Ran `sed -n '215,285p' scripts/configure-gnb.sh; rg -n 'get_amf|ip addr|sudo|bridge|source|subnet' scripts/configure-core.sh; cat configs/core/get_amf_address.txt; sed -n '1,110p' scripts/build-ran.sh; sed -n '1,100p' scripts/build-flexric.sh; ls compose/core/cp-cfg; rg -n 'volume|usage_reporting' compose/core/cp-cfg/*; rg -n 'E2AP_VERSION|KPM_VERSION|CMAKE_HOME_DIRECTORY' src/flexric/build/CMakeCache.txt src/oai-ran/cmake_targets/ran_build/build/CMakeCache.txt; find /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation -path '*/flexric/.git' -print`
> - Ran `python3 tests/test_ported_scripts.py; bash tests/test_oai_upf_profile.sh; python3 tests/test_background_sudo.py`
>
> </details>
>
> Các test script/profile đã qua; mình đang kiểm tra nốt launcher chạy nền. Có hai điểm cần lưu ý: Compose còn đường dẫn checkout cũ nên nên sinh lại trước khi chạy; máy có interface Kubernetes, nhưng bộ script này vẫn triển khai bằng Docker Compose. Mình sẽ xuất riêng patch URR đã commit thành file để bạn dễ xem, kèm danh mục patch và hướng dẫn chạy từng bước.
>
> <details><summary>Created a file, ran 3 commands</summary>
>
> - Ran `python3 - <<'PY'
> from pathlib import Path
> import subprocess
> for kind in ('ran','flexric'):
>  tree=Path('src/oai-ran' if kind=='ran' else 'src/flexric').resolve()
>  for p in sorted(Path('patches',kind).rglob('*.patch')):
>   if 'correcting_e2_node_id/src/' in str(p) or 'correcting_e2_node_id/examples/' in str(p): continue
>   result=subprocess.run(['git','-C',str(tree),'apply','--reverse','--check','--ignore-whitespace',str(p.resolve())],capture_output=True,text=True)
>   print('APPLIED' if result.returncode==0 else 'CHECK NEEDED', p)
> for f in ['metrics_factory.h','metrics_factory.c','monitor/xapp_kpm_moni_write_to_csv.c','monitor/xapp_kpm_moni_write_to_influxdb.c']:
>  a=Path('patches/flexric/examples/xApp/c')/f;b=Path('src/flexric/examples/xApp/c')/f
>  print('MATCH' if a.read_bytes()==b.read_bytes() else 'DIFFERENT',f)
> PY
> sed -n '240,325p' scripts/configure-core.sh; rg -n 'build|docker|pnpm' scripts/configure-core.sh; sed -n '970,1038p' compose/core/compose.yml; rg -n 'volume_threshold|100 \*|104857600' /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/5G_Core_Network -g '*smf*' -g '*.cpp' -g '*.yaml' --max-count 2`
> - Ran ``python3 - <<'PY'
> from pathlib import Path
> import subprocess
> repo='/home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/5G_Core_Network/OAI_UPF_Research'
> p=Path('patches/oai-upf-00b7485-pfcp-urr-reporting.patch')
> data=subprocess.check_output(['git','-C',repo,'format-patch','-1','00b7485','--stdout'])
> if p.exists() and p.read_bytes()!=data:
>  raise SystemExit('Refusing to overwrite different patch')
> p.write_bytes(data)
> r=subprocess.run(['git','-C',str(Path('src/oai-upf').resolve()),'apply','--reverse','--check',str(p.resolve())],capture_output=True,text=True)
> print('UPF exported patch reverse check:',r.returncode,r.stderr)
> assert r.returncode==0
> out=Path('docs');out.mkdir(exist_ok=True)
> lines=['# Danh mục patch local — kiểm tra 2026-09-24','',
> 'Đối chiếu với baseline trong `manifests/`, patch snapshot và checkout Git cũ trên máy; không phải so với upstream mới nhất. “Local” nghĩa là thay đổi tích hợp ngoài baseline OAI/FlexRIC/5gdeploy. Một số patch được kế thừa từ NIST testbed, không có nghĩa tất cả đều do tác giả workspace tự viết.','',
> '## UPF: thay đổi đã commit','',
> '`oai-upf-working-tree.patch` là file rỗng. Patch URR nằm trong commit riêng `00b7485329b2c07d6cf74bbfae53b7f7acf5de4e`, parent `9e93b63`. File `oai-upf-00b7485-pfcp-urr-reporting.patch` được xuất thêm ngày 2026-09-24 từ commit đó; không phải sửa implementation mới. Reverse check trên snapshot hiện tại thành công.','',
> 'Commit sửa 13 file, +404/-126 dòng. Datapath eBPF và logic native → SKB đã có trong baseline; không nên tính chúng là tính năng mới do patch URR tạo ra.','',
> '## Toàn bộ file .patch trong patches/','',
> 'Các file `*-working-tree.patch` là bản tổng hợp phục vụ đối chiếu. Build script chỉ áp dụng patch nhỏ trong `patches/ran` và `patches/flexric`; không áp lại bản tổng hợp lên cây đã patch. Các patch con trong `correcting_e2_node_id/src` và `examples` trùng nhóm với `correcting_e2_node_id/patch.patch`, và được helper bỏ qua để tránh áp hai lần.','']
> for f in sorted(Path('patches').rglob('*.patch')):
>  lines.append(f'### [{f}](../{f})')
>  text=f.read_text()
>  targets=[s.split(' b/',1)[1] for s in text.splitlines() if s.startswith('diff --git ') and ' b/' in s]
>  lines += ['',f'- Kích thước: {f.stat().st_size} byte.']
>  if targets: lines += ['- File đích:']+['  - `'+x+'`' for x in targets]
>  elif not text: lines+=['- Rỗng: không chứa working-tree diff.']
>  else: lines+=['- Xem header `---`/`+++` trong file để biết file đích.']
>  lines+=['']
> lines += ['## Các file bổ sung không ở dạng .patch','',
> 'Các file mới/untracked không nhất thiết được chứa trong working-tree diff. Manifest `.status` là bản ghi lúc tạo snapshot, không phải trạng thái Git sống.','',
> '- `patches/flexric/examples/xApp/c/metrics_factory.c` và `.h`.',
> '- `patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c`.',
> '- `patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_influxdb.c`.',
> '- `src/5gdeploy/scenario/orantestbed/`.',
> '- Lớp tích hợp `scripts/`, `configs/`, `tests/` và Compose sinh ra.',
> '',
> '## Patch có sẵn trong upstream: không tính là patch local của testbed','',
> 'Ví dụ trong OAI RAN: `cmake_targets/tools/uhd-4.x-tdd-patch.diff`, `uhd-3.15-tdd-patch.diff`, `install_wls_lib.patch`, `install_libraries_to_system.patch`, `oran_fhi_integration_patches/F/oaioran_F.patch`. Không phân loại chỉ dựa vào phần mở rộng `.patch`; cần đối chiếu baseline.','',
> '## Kiểm tra đã thực hiện','',
> '- 13/13 patch nhỏ mà helper áp dụng cho RAN/FlexRIC: reverse check thành công.',
> '- 4 file bổ sung FlexRIC ở patches/ khớp bản trong src/flexric.',
> '- `python3 tests/test_ported_scripts.py`: 13 tests PASS.',
> '- `bash tests/test_oai_upf_profile.sh`: PASS.',
> '- `python3 tests/test_background_sudo.py`: 1 test PASS.',
> '- Đây là test script với mock; không chứng minh RF/E2/PFCP/datapath chạy thật.','']
> (out/'LOCAL-PATCHES.md').write_text('\n'.join(lines))
> print('Wrote',p,'and docs/LOCAL-PATCHES.md')
> PY``
> - Ran `git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/OpenAirInterface_Testbed/User_Equipment/openairinterface5g ls-tree -r --name-only 26efcc498931b8f6979c39f9f44400f3c965fdc4 cmake_targets/tools | rg 'uhd-4.x-tdd-patch|uhd-3.15-tdd-patch|install_wls_lib.patch|install_libraries_to_system.patch|oaioran_F.patch'; rg -n 'DOCKER|build|image' scripts/lib/generate-core-scenario.sh; cat scripts/lib/generate-core-scenario.sh | tail -45; ls -l src/oai-ran/cmake_targets/ran_build/build/nr-softmodem src/oai-ran/cmake_targets/ran_build/build/nr-uesoftmodem src/flexric/build/examples/ric/nearRT-RIC`
> - Wrote `./docs/RUN-EBPF-UPF.md` (+121 -0)
>
> </details>
</details>

Mình đã tạo hai tài liệu để bạn làm theo:

- [Hướng dẫn chạy thử từng bước]( /home/ducsssanh/6G/O-RAN/DATN/Codebase/docs/RUN-EBPF-UPF.md)
- [Danh mục chính xác từng patch local và file bị sửa](./docs/LOCAL-PATCHES.md)

**1. Các bước chạy tiếp theo**

Chạy từng lệnh, chỉ tiếp tục khi bước trước thành công. Từ thư mục `Codebase`:

```bash
# Chuẩn bị dependency cho 5gdeploy
(cd src/5gdeploy && corepack pnpm install --frozen-lockfile)

# Build
bash scripts/build-upf.sh
bash scripts/build-flexric.sh
RADIO_TYPE=SIMU bash scripts/build-ran.sh

# Sinh lại cấu hình, theo đúng thứ tự
bash scripts/configure-core.sh
bash scripts/configure-flexric.sh
RADIO_TYPE=SIMU bash scripts/configure-gnb.sh
RADIO_TYPE=SIMU bash scripts/configure-ue.sh 1
```

**Nên sinh lại Compose:** bản hiện tại còn một số đường dẫn checkout cũ. Nếu stack đang chạy, dừng trước bằng `bash scripts/stop-stack.sh 1`.

Sau đó kiểm tra riêng core:

```bash
bash scripts/start-core.sh
docker compose -f compose/core/compose.yml ps
docker logs upf1
docker logs smf
```

Cần thấy PFCP association thành công, không có lỗi BPF/verifier. Kiểm tra XDP trong network namespace UPF:

```bash
UPF_PID=$(docker inspect -f '{{.State.Pid}}' upf1)
sudo nsenter -t "$UPF_PID" -n bpftool net
```

Khi core ổn, dừng để runner tự dựng toàn bộ stack và bắt PFCP trước lúc UE kết nối:

```bash
bash scripts/stop-core.sh
bash scripts/run-experiment.sh --dry-run
bash scripts/run-experiment.sh --ue 1 --keep-running
```

**Dùng cấu hình mặc định 10M × 120 giây mỗi chiều**, tránh `--smoke` khi kiểm tra URR vì lượng traffic quá nhỏ để vượt ngưỡng 100 MiB.

Kết quả ở:

```text
artifacts/experiments/latest/
├── metadata/result.env
├── capture/pfcp.pcapng
├── capture/pfcp_urr_config.csv
├── capture/pfcp_urr.csv
├── kpm/KPI_Metrics.csv
└── traffic/
```

Chỉ kết luận chạy thành công khi có **PDU session, traffic nhận được cả UL/DL, XDP attach và Usage Report được SMF chấp nhận**. Cuối cùng dừng bằng:

```bash
bash scripts/stop-stack.sh 1
```

**2. Chính xác patch nào là local?**

| File/nhóm patch | Nội dung |
|---|---|
| [oai-upf-00b7485-pfcp-urr-reporting.patch](./patches/oai-upf-00b7485-pfcp-urr-reporting.patch) | **Mình vừa xuất** từ commit riêng `00b7485`: eBPF URR → PFCP Usage Report; 13 file, +404/−126 dòng |
| [oai-upf-working-tree.patch](./patches/oai-upf-working-tree.patch) | Rỗng vì thay đổi UPF đã commit |
| [oai-ran-working-tree.patch](./patches/oai-ran-working-tree.patch) | Tổng hợp thay đổi RAN: E2AP/KPM, node ID, PDCP volume, SST, tương thích build |
| [flexric-working-tree.patch](./patches/flexric-working-tree.patch) | Tổng hợp thay đổi FlexRIC/xApp |
| [5gdeploy-working-tree.patch](./patches/5gdeploy-working-tree.patch) | Đổi IP/gNB ID/TAC và download fallback |

Các patch nhỏ mà script build dùng nằm trong:

```text
patches/ran/
  cmake_targets/tools/build_helper.patch
  executables/nr-softmodem.c.patch
  openair3/NAS/NR_UE/nr_nas_msg.c.patch
  openair3/UICC/pdu_session.c.patch
  radio/zmq/ring_buffer.cpp.patch
  radio/zmq/zmq_imported.cpp.patch
  radio/zmq/zmq_imported.h.patch

patches/flexric/
  correcting_e2_node_id/patch.patch
  disable_database_option/patch.patch
  examples/xApp/c/kpm_rc/CMakeLists.txt.patch
  examples/xApp/c/kpm_rc/xapp_kpm_rc.c.patch
  examples/xApp/c/monitor/CMakeLists.txt.patch
  examples/xApp/c/monitor/xapp_kpm_moni.c.patch
```

Danh mục đã tạo liệt kê cả các patch con của `correcting_e2_node_id` và file bổ sung CSV/InfluxDB. **Không áp lại patch tổng hợp:** cây nguồn hiện đã chứa các thay đổi; mình xác nhận cả 13 patch nhỏ đều đã áp dụng.

“Local” ở đây là **ngoài baseline upstream**; một phần kế thừa từ NIST testbed, không phải tất cả tự viết mới. Các patch UHD/WLS có sẵn dưới `src/oai-ran/cmake_targets/tools/` không thuộc nhóm thay đổi local này.

**3. Hai phần cần hoàn thiện sau khi chạy thử**

- **Ép SKB:** hiện code thử native XDP trước. Chỉ cần sửa nếu thí nghiệm yêu cầu SKB cố định; native chạy được vẫn chứng minh eBPF hoạt động.
- **Ngưỡng URR:** `volume_threshold_bytes` chưa được truyền vào SMF. Trước tiên đọc ngưỡng thực trong capture; muốn tùy chỉnh phải kiểm tra đúng SMF v2.2.0 rồi sửa generator hoặc SMF, không chỉ đổi `options.yaml`.

Mình đã chạy các test script/profile/launcher: **đều PASS**. Lần này chỉ thêm tài liệu và xuất patch; chưa khởi động stack hay xác minh end-to-end.

> tao cần viết doc về cách xây dựng toàn bộ codebase này từ đầu (từ lúc clone các service về từ openairinterface, cách nhét chúng vào chung một repo/codebase, đến từng bản patch một khác gì so với nguyên bản). hãy tìm lại và report cho tao. ngoài ra make sure lại xem có phải hệ thống đang chạy trên docker không? tao muốn chuyển qua kubernetes (có thể chạy single node bằng minikube) thì có đơn giản không

<details><summary>7 previous messages</summary>

> Mình sẽ truy lại nguồn repo, commit, script cài đặt và từng patch để viết tài liệu dựng lại codebase từ đầu. Đồng thời mình sẽ kiểm tra trạng thái triển khai hiện tại và đánh giá phần nào cần đổi nếu chuyển sang Kubernetes/minikube.
>
> <details><summary>Ran 6 commands, searched the web</summary>
>
> - Ran `rg --files -g AGENTS.md -g '*install*' -g '*clone*' scripts; ls docs; cat manifests/*.commit; docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'; command -v kubectl minikube; ps -eo comm,args | rg 'nr-softmodem|nr-uesoftmodem|nearRT-RIC|kubelet|minikube' | head -15`
>
> - Ran `cat scripts/legacy/{ue,gnb,flexric}/install_scripts/git_clone.sh; cat scripts/legacy/core/5gdeploy/install.sh; cat manifests/*.submodules; git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation remote -v; git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation rev-parse HEAD; rg -n 'git clone|checkout|OAI_UPF|GIT_REPO|BRANCH|COMMIT' scripts/legacy/core scripts/legacy/{ue,gnb,flexric}/full_install.sh -g '*.sh' | head -70`
>
> - Ran `kubectl config current-context; kubectl --request-timeout=8s get nodes -o wide; kubectl --request-timeout=8s get pods -A -o wide; minikube profile list -o json; rg -n 'privileged|network_mode|devices:|cap_add|/sys|/lib/modules|build:|driver:|name:' compose/core/compose.yml | tail -75; du -sh src/*; cat scripts/lib/apply-patches.sh`
>
> Searched the web for `site.minikube.sigs.k8s.io docs drivers docker privileged networking ...`
>
> - Ran `kubectl config current-context; kubectl --request-timeout=5s get nodes -o wide; kubectl --request-timeout=5s get pods -A --no-headers | head -25; minikube profile list -o json; git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/OpenAirInterface_Testbed/RAN_Intelligent_Controllers/Flexible-RIC/flexric remote -v; cat src/5gdeploy/docker/build.sh | head -75; rg -n 'git_clone|git clone|https.*git|commit_hash' scripts/legacy/{core,ue,gnb,flexric}/full_install.sh; cat src/oai-upf/.gitmodules src/oai-ran/.gitmodules`
>
> Searched the web for `https://gitlab.eurecom.fr/oai/orchestration/charts`
>
> - Ran `kubectl --request-timeout=8s get pods -A -o json | python3 -c 'import sys,json; d=json.load(sys.stdin); rows=[(p["metadata"]["namespace"],p["metadata"]["name"],p["status"].get("phase"),[c["image"] for c in p["spec"]["containers"]]) for p in d["items"]]; print("Total pods:",len(rows)); print("\n".join(str(r) for r in rows if any(s in str(r).lower() for s in ("oai","upf","flexric","oran","gnb","smf"))))'; cat src/5gdeploy/docker/{bridge,dn}/Dockerfile; sed -n '1036,1093p' compose/core/compose.yml; cat patches/ran/executables/nr-softmodem.c.patch; rg '^diff --git' patches/flexric-working-tree.patch`
>
> - Ran `python3 - <<'PY'
> import pathlib, subprocess, tempfile, tarfile, io, json
> base=pathlib.Path('/home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation')
> repos={'oai-upf':base/'5G_Core_Network/OAI_UPF_Research','oai-ran':base/'OpenAirInterface_Testbed/User_Equipment/openairinterface5g','flexric':base/'OpenAirInterface_Testbed/RAN_Intelligent_Controllers/Flexible-RIC/flexric','5gdeploy':base/'5G_Core_Network/Additional_Cores_5GDeploy/5gdeploy'}
> for name,repo in repos.items():
>  sha=pathlib.Path('manifests',name+'.commit').read_text().strip()
>  with tempfile.TemporaryDirectory() as t:
>   data=subprocess.check_output(['git','-C',str(repo),'archive',sha]);tarfile.open(fileobj=io.BytesIO(data)).extractall(t,filter='data')
>   patch=pathlib.Path('patches',name+'-working-tree.patch').resolve()
>   if patch.stat().st_size:
>    r=subprocess.run(['git','-C',t,'apply','--exclude=openair2/E2AP/flexric',str(patch)],capture_output=True,text=True)
>    print(name,'aggregate apply',r.returncode,r.stderr[:500])
>   rows=subprocess.check_output(['git','-C',str(repo),'ls-tree','-rz',sha]).split(b'\0')
>   diff=[]
>   for row in rows:
>    if not row:continue
>    meta,p=row.split(b'\t'); mode,typ,h=meta.split();p=p.decode()
>    if typ!=b'blob':continue
>    a=pathlib.Path(t,p);b=pathlib.Path('src',name,p)
>    if not b.exists() or a.read_bytes()!=b.read_bytes():diff.append(p)
>   print(name,'current differences after saved patch:',json.dumps(diff))
> PY`
>
> </details>
>
> Có điểm cần nói chính xác hơn câu trả lời trước: **codebase này được cấu hình chạy core bằng Docker Compose, còn gNB/UE/FlexRIC chạy trên host; hiện stack đó không chạy**. Máy đồng thời có một cluster Kubernetes single-node đang `Ready`, dùng containerd, nhưng mình chưa thấy workload OAI/FlexRIC của codebase trong đó. Profile minikube cũ còn cấu hình nhưng container node đã mất.
>
> Mình cũng đang thử dựng lại source từ commit + patch lưu sẵn để kiểm tra tài liệu có bỏ sót thay đổi nào không.
>
> <details><summary>Explored 4 files, 2 searches, ran 4 commands, searched the web</summary>
>
> <details><summary>Explored 4 files, 2 searches</summary>
>
> - Read `./manifests/flexric.status`
> - Read `./patches/flexric-working-tree.patch`
> - Read `./src/5gdeploy/types/build-schema.sh`
> - Searched for `apt|gcc|swig|dependencies|DEP` in `full_install.sh`
> - Read `./src/oai-upf/docker/Dockerfile.upf.ubuntu`
> - Searched for `BPF|CAP_|cap_|privilege|rlimit|memlock` in `main.cpp`
>
> </details>
>
> - Ran `python3 - <<'PY'
> import subprocess,pathlib,hashlib
> r='/home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/OpenAirInterface_Testbed/RAN_Intelligent_Controllers/Flexible-RIC/flexric'
> sha=pathlib.Path('manifests/flexric.commit').read_text().strip();dst=pathlib.Path('src/oai-ran/openair2/E2AP/flexric')
> for row in subprocess.check_output(['git','-C',r,'ls-tree','-rz',sha]).split(b'\0'):
>  if not row:continue
>  meta,p=row.split(b'\t');m,t,h=meta.split();p=p.decode()
>  if t!=b'blob':continue
>  f=dst/p
>  if not f.exists(): print('MISSING',p);continue
>  data=f.read_bytes()
>  if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=h.decode():print('CHANGED',p)
> PY
> rg -n 'cap|setcap|USER|ENTRYPOINT|CMD|FROM|ARG BASE' src/oai-upf/docker/Dockerfile.upf.ubuntu; git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation ls-tree -r --name-only HEAD | rg '(patch|commit_hashes.json)' | head -45; head -50 scripts/configure-core.sh | tail -13; rg -n 'docker.sock|pid:|privileged:|network_mode:' compose/core/compose.yml`
>
> - Ran `python3 - <<'PY'
> import subprocess,pathlib
> r='/home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/OpenAirInterface_Testbed/RAN_Intelligent_Controllers/Flexible-RIC/flexric'
> for p in subprocess.check_output(['git','-C',r,'ls-tree','-r','--name-only','ef6d722f']).decode().splitlines():
>  a=pathlib.Path('src/flexric',p);b=pathlib.Path('src/oai-ran/openair2/E2AP/flexric',p)
>  if a.is_file() and b.is_file() and a.read_bytes()!=b.read_bytes():print(p)
> for p in ['examples/xApp/c/metrics_factory.c','examples/xApp/c/metrics_factory.h','examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c','examples/xApp/c/monitor/xapp_kpm_moni_write_to_influxdb.c']:
>  a=pathlib.Path('src/flexric',p);b=pathlib.Path('src/oai-ran/openair2/E2AP/flexric',p)
>  print(p,'same:',a.read_bytes()==b.read_bytes())
> PY
> sed -n '118,175p' src/oai-upf/docker/Dockerfile.upf.ubuntu; cat scripts/legacy/ue/commit_hashes.json 2>/dev/null | head -20; rg -n 'metrics|pdcp|byte|timestamp|CSV' patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c | head -25`
>
> - Ran ``python3 - <<'PY'
> import pathlib,subprocess,hashlib
> repo='/home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation'
> paths=subprocess.check_output(['git','-C',repo,'ls-tree','-rz','HEAD']).split(b'\0');byhash={}
> for row in paths:
>  if not row:continue
>  meta,p=row.split(b'\t');m,t,h=meta.split()
>  if t==b'blob':byhash.setdefault(h.decode(),[]).append(p.decode())
> lines=['# Nguồn gốc từng patch nhỏ','', 'So hash nội dung với commit `c1dd6ea68b7b236e7ff8e90994fba9138f28b457` của fork NIST testbed trên máy. Khớp chứng minh patch đã có trong checkout nền; không tự xác định tác giả hay chứng minh đã có ở upstream NIST. Không khớp không đủ để kết luận tác giả local.', '', '| Patch | Đối chiếu với fork testbed |','|---|---|']
> for p in sorted(pathlib.Path('patches').rglob('*.patch')):
>  d=p.read_bytes();h=hashlib.sha1(b'blob '+str(len(d)).encode()+b'\0'+d).hexdigest();matches=byhash.get(h,[])
>  lines.append('| `'+str(p)+'` | '+('Khớp: '+'; '.join('`'+x+'`' for x in matches) if matches else 'Không có blob giống hệt ở commit testbed đã kiểm tra.')+' |')
> pathlib.Path('docs/PATCH-PROVENANCE.md').write_text('\n'.join(lines)+'\n')
> print('Matched',sum('Khớp:' in x for x in lines),'patches')
> PY``
>
> Searched the web for `https://kubernetes.io/docs/concepts/security/linux-kernel-security-constraints/`
>
> - Ran `git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation/5G_Core_Network/OAI_UPF_Research rev-parse 00b7485^; cat src/5gdeploy/package.json | head -40; rg -n 'netdev|n3|n6' compose/core/up-cfg/upf1.yaml; rg -n 'socket|SYS_ADMIN|BPF|PERFMON' compose/core/compose.yml src/5gdeploy/oai/up.ts; sed -n '1380,1440p' patches/flexric-working-tree.patch; rg --files src/5gdeploy/scenario/orantestbed`
>
> </details>
>
> Mình tìm thêm một lỗi cấu hình đáng chú ý: profile bật eBPF trong YAML, nhưng Compose hiện chỉ cấp `NET_ADMIN` cho UPF. Trong khi đó, generator 5gdeploy có nhánh `--oai-upf-bpf` để thêm quyền BPF và các thiết lập liên quan; script hiện chưa truyền cờ này. Vì vậy chưa thể coi cấu hình hiện tại là đủ để chạy eBPF.
>
> Phần đối chiếu source đã xong: commit + patch tổng hợp khôi phục khớp các file tracked của cả bốn repo chính. Có 24 file patch khớp nguyên nội dung với fork NIST testbed cũ, nên tài liệu sẽ phân biệt rõ patch kế thừa và phần sửa riêng.
>
> <details><summary>Created 3 files, edited 3 files, explored 3 files, 4 searches, ran 4 commands</summary>
>
> - Ran `cat src/5gdeploy/oai/up.ts | head -100; rg -n 'oai-upf-bpf' src/5gdeploy; rg -n 'modprobe|kernel|seccomp|privileged' src/5gdeploy/oai/up.ts; git -C /home/ducsssanh/6G/O-RAN/O-RAN-Testbed-Automation log -1 --format='%h %s' upstream/main 2>/dev/null; head -10 docs/PATCH-PROVENANCE.md`
>
> - Wrote `./docs/BUILD-FROM-SCRATCH.md` (+214 -0)
> - Wrote `./docs/KUBERNETES-MIGRATION.md` (+72 -0)
>
> - Ran ``python3 - <<'PY'
> from pathlib import Path
> special={
> 'patches/ran/cmake_targets/tools/build_helper.patch':'Trước: distro matcher không nhận Linux Mint theo cách testbed cần. Sau: nhận Linux Mint, ánh xạ phiên bản sang Ubuntu và bổ sung Ubuntu 20.04; thay đổi phục vụ build.',
> 'patches/ran/executables/nr-softmodem.c.patch':'Trước: nhánh DU gán gNB ID và DU ID ngược biến. Sau: nb_id lấy gnb_id, cu_du_id lấy gNB_DU_id.',
> 'patches/ran/openair3/NAS/NR_UE/nr_nas_msg.c.patch':'Sửa điều kiện tiền xử lý OpenSSL, dùng OPENSSL_VERSION_TEXT và guard hàm SUCI dùng OpenSSL 3; phục vụ tương thích build.',
> 'patches/ran/openair3/UICC/pdu_session.c.patch':'Giới hạn SST trong validation từ 1..4 thành 0..255.',
> 'patches/ran/radio/zmq/ring_buffer.cpp.patch':'std::make_unique cho mảng đổi thành unique_ptr với new và value initialization; tránh yêu cầu API C++ mới hơn.',
> 'patches/ran/radio/zmq/zmq_imported.cpp.patch':'std::scoped_lock đổi thành std::lock_guard<std::mutex>; giữ khóa mutex cho transmit, sửa tương thích chuẩn C++.',
> 'patches/ran/radio/zmq/zmq_imported.h.patch':'Khởi tạo atomic dùng dấu ngoặc nhọn thay phép gán giá trị ban đầu.',
> 'patches/flexric/correcting_e2_node_id/patch.patch':'Patch gộp truyền E2 node ID từ act_proc qua message handler/dispatcher tới callback và sửa chữ ký callback ở xApp mẫu. Không apply thêm các patch con cùng nhóm.',
> 'patches/flexric/disable_database_option/patch.patch':'Trước: build xApp gắn backend database. Sau: có NONE_XAPP, handler giả và DB operations no-op; guard khởi tạo SQLite, bổ sung hướng dẫn README.',
> 'patches/flexric/examples/xApp/c/kpm_rc/CMakeLists.txt.patch':'Thêm metrics_factory.c vào xapp_kpm_rc và link libm.',
> 'patches/flexric/examples/xApp/c/monitor/CMakeLists.txt.patch':'Thêm metrics_factory/libm cho monitor, target ghi CSV và InfluxDB cùng dependency liên quan; xem diff để biết cấu hình từng target.',
> 'patches/flexric/examples/xApp/c/kpm_rc/xapp_kpm_rc.c.patch':'Dùng metrics factory cho label/đơn vị, bổ sung lọc SST/SD từ env, cập nhật callback mang node ID và bỏ qua report style không hỗ trợ; điều chỉnh logging KPM.',
> 'patches/flexric/examples/xApp/c/monitor/xapp_kpm_moni.c.patch':'Tương tự KPM monitor: metrics factory, label, in giá trị/đơn vị, callback node ID, lọc S-NSSAI SST/SD và skip report style chưa hỗ trợ.',
> 'patches/oai-upf-working-tree.patch':'File rỗng, không có delta chưa commit ở thời điểm snapshot. Không đại diện cho toàn bộ khác biệt UPF với upstream.',
> 'patches/oai-upf-00b7485-pfcp-urr-reporting.patch':'Xuất từ commit riêng 00b7485 ngày 24/09/2026. Thêm consumer URR→PFCP, sửa kernel/userspace map và cơ chế gửi report; chi tiết 13 file bên dưới.',
> 'patches/oai-ran-working-tree.patch':'Tổng hợp tracked diff của RAN. Ngoài 7 patch nhỏ còn có default E2AP_V3/KPM_V3_00, PDCP SDU volume real thay integer, và marker FlexRIC dirty. Marker không chứa nội dung submodule.',
> 'patches/flexric-working-tree.patch':'Tổng hợp tracked diff FlexRIC: API node ID, DB optional, KPM và giới hạn đường dẫn FR_CONF_FILE_LEN 128→1024. Không chứa bốn file mới metrics_factory/CSV/InfluxDB.',
> 'patches/5gdeploy-working-tree.patch':'ipalloc.ts: 172.25.192.0/18→172.25.160.0/20; helpers.ts: gNB ID khởi đầu 1→3584; phones-vehicles.ts: TAC 5→7; download.sh: tải file tạm, retry, fallback Git fetch. Không chứa scenario/orantestbed untracked.'}
> node={
> 'act_proc.c':'Đổi kiểu callback đăng ký trong add_act_proc để nhận global_e2_node_id_t.',
> 'act_proc.h':'Đổi declaration add_act_proc tương ứng chữ ký callback mới.',
> 'e42_xapp_api.h':'Đổi typedef sm_cb từ một tham số dữ liệu thành dữ liệu + E2 node ID.',
> 'msg_dispatcher_xapp.c':'Worker gọi callback với cả msg->rd và msg->e2_node.',
> 'msg_dispatcher_xapp.h':'Thêm field e2_node và cập nhật chữ ký sm_cb trong message queue.',
> 'msg_handler_xapp.c':'Chép ans.val.e2_node vào message dispatch trước khi enqueue.'}
> lines=['# Nội dung trước/sau của từng patch','', 'Đối chiếu với baseline trong manifests; đây là mô tả kỹ thuật, không phải chứng nhận tác giả. Patch gộp và patch con có phần trùng nhau. Đường dẫn tương đối tính từ root Codebase.','']
> for p in sorted(Path('patches').rglob('*.patch')):
>  s=str(p);ex=special.get(s)
>  if ex is None and 'correcting_e2_node_id/src/' in s:ex=node[p.name.removesuffix('.patch')]
>  if ex is None and 'correcting_e2_node_id/examples/' in s:ex='Cập nhật callback service model của xApp mẫu để nhận thêm global_e2_node_id_t const* node_id, tương thích API dispatcher mới. Đây là bản con của correcting_e2_node_id/patch.patch.'
>  assert ex is not None,s
>  lines += [f'## [{s}](../{s})','',ex,'']
> lines += ['## Chi tiết 13 file trong commit UPF 00b7485','', '| File (dưới src/oai-upf/) | Thay đổi |','|---|---|']
> upf={
> 'src/upf_app/CMakeLists.txt':'Đưa control/UrrReportConsumer.cpp vào build.',
> 'src/upf_app/app/upf_n4.cpp':'Nhận ITTI N4_SESSION_REPORT_REQUEST, cấp transaction ID ở N4 và enqueue thay gửi trực tiếp từ consumer.',
> 'src/upf_app/control/UrrReportConsumer.cpp':'File mới: poll ring buffer, tìm session từ SEID, dựng PFCP Usage Report gồm volume/packet/time/trigger, gửi tới CP F-SEID.',
> 'src/upf_app/control/UrrReportConsumer.h':'File mới: khai báo vòng đời consumer, worker, ring buffer và sequence state.',
> 'src/upf_app/control/UserPlaneComponent.cpp':'Tạo/start/stop consumer cùng vòng đời user-plane khi URR được bật.',
> 'src/upf_app/control/UserPlaneComponent.h':'Thêm include/member sở hữu UrrReportConsumer.',
> 'src/upf_app/kernel/include/urr_maps.h':'Map config dùng urr_config thống nhất với datapath.',
> 'src/upf_app/kernel/include/urr_types.h':'Event bổ sung thông tin phục vụ report như urr_id và start_time_ns.',
> 'src/upf_app/kernel/xdp/xdp_urr_apply_kern.c':'Cập nhật tạo event/report state cho consumer và xử lý thời điểm/counter khi reporting.',
> 'src/upf_app/user/urr_apply_user.cpp':'Chuyển PFCP URR thành urr_config, trigger bitmask, key SEID, monotonic time, xử lý lỗi map; từ chối nhiều URR/session.',
> 'src/upf_app/user/urr_apply_user.h':'Đồng bộ declarations với map key/counter mới; bỏ kiểu trung gian không còn dùng.',
> 'src/upf_app/user/wrappers/BPFMap.cpp':'Triển khai truy cập FD của map để tạo ring buffer consumer.',
> 'src/upf_app/user/wrappers/BPFMap.hpp':'Khai báo accessor FD tương ứng.'}
> for f,d in upf.items():lines.append('| `'+f+'` | '+d+' |')
> lines += ['', '## File mới ngoài diff tracked','',
> '- `metrics_factory.c/.h`: helper tạo label/đơn vị và xử lý metrics cho xApp.',
> '- `xapp_kpm_moni_write_to_csv.c`: xuất CSV, node/UE ID, timestamp và PDCP volume theo byte; bản standalone hiện khác CSV trong FlexRIC nhúng.',
> '- `xapp_kpm_moni_write_to_influxdb.c`: xuất dữ liệu sang InfluxDB; tồn tại source không có nghĩa InfluxDB đang chạy.',
> '- `src/5gdeploy/scenario/orantestbed/*`: scenario local; config generator có thể dựng lại từ scenario 20230817 rồi chỉnh slice/SIM/DNN.',
> '- `scripts/`, `configs/`, `tests/`: lớp tích hợp Codebase; không thể tái dựng chỉ bằng clone OAI và apply UPF patch.',
> '', 'Các file backup `.previous` lưu tham chiếu trước sửa; không coi đó là service hoặc patch bổ sung cần build.','']
> Path('docs/PATCH-DETAILS.md').write_text('\n'.join(lines))
> print('Wrote patch explanations:',len(special)+11)
> PY``
>
> - Wrote `./docs/BUILD-FROM-SCRATCH.md` (+1 -1)
> - Wrote `./docs/RUN-EBPF-UPF.md` (+2 -0)
>
> <details><summary>Explored 3 files, 4 searches</summary>
>
> - Searched for `^diff --git|^\+.*(Get|Consumer|time|curr|report)` in `oai-upf-00b7485-pfcp-urr-reporting.patch`
> - Searched for `Không có blob` in `PATCH-PROVENANCE.md`
> - Read `./scripts/configure-core.sh`
> - Searched for `CURDIR|include|SUBMODULE` in `build_helper`
> - Read `./src/flexric/.gitmodules`
> - Searched for `^\+.*(curl|influx|metrics|target|add_exe)` in `CMakeLists.txt.patch`
> - Read `./src/oai-upf/src/upf_app/control/UserPlaneComponent.h`
>
> </details>
>
> - Ran `sed -n '413,532p' patches/oai-upf-00b7485-pfcp-urr-reporting.patch; tail -50 patches/oai-upf-00b7485-pfcp-urr-reporting.patch; rg -n 'Không có blob' docs/PATCH-PROVENANCE.md; rg -n '^diff --git' patches/flexric/disable_database_option/patch.patch`
>
> - Wrote `./docs/PATCH-DETAILS.md` (+4 -4)
> - Wrote `./docs/README.md` (+10 -0)
>
> - Ran ````python3 - <<'PY'
> from pathlib import Path
> import re, subprocess
> broken=[];bad=[]
> for p in Path('docs').glob('*.md'):
>  s=p.read_text()
>  for target in re.findall(r'\]\(([^)]+)\)',s):
>   if '://' in target or target.startswith('#'):continue
>   if not (p.parent/target.split('#')[0]).exists():broken.append((str(p),target))
>  for i,code in enumerate(re.findall(r'```bash\n(.*?)```',s,re.S)):
>   r=subprocess.run(['bash','-n'],input=code,text=True,capture_output=True)
>   if r.returncode:bad.append((str(p),i,r.stderr))
> print('Broken document links:',broken)
> print('Bash snippet syntax errors:',bad)
> print('Patch inventory:',len(list(Path('patches').rglob('*.patch'))))
> assert not broken and not bad
> PY````
>
> </details>
>
> Bộ tài liệu đã có đủ phần clone/pin commit, áp patch, bổ sung các file không nằm trong Git diff, gom thành monorepo, build và lộ trình Kubernetes. Mình đã kiểm tra cú pháp các khối lệnh Bash và đường dẫn tài liệu.
>
> Điểm đáng lưu ý khi dựng lại: chỉ chạy build helper chưa khôi phục đủ snapshot; cần patch tổng hợp và các file mới của xApp/scenario. Riêng phần UPF, tài liệu ghi rõ eBPF datapath đã có từ upstream; patch riêng bổ sung luồng Usage Report và sửa tính nhất quán của URR.
</details>

Mình đã viết bộ tài liệu dựa trên checkout Git cũ, source hiện tại và từng patch:

- **[Dựng toàn bộ codebase từ đầu](./docs/BUILD-FROM-SCRATCH.md):** URL repo, commit, submodule, thứ tự clone/apply patch, gom thành monorepo, dependency và build.
- **[Giải thích từng patch](./docs/PATCH-DETAILS.md):** trước/sau của toàn bộ **29 file patch**, gồm chi tiết 13 file trong commit UPF.
- **[Nguồn gốc patch](./docs/PATCH-PROVENANCE.md):** patch nào khớp với fork NIST testbed cũ.
- **[Đánh giá chuyển Kubernetes](./docs/KUBERNETES-MIGRATION.md):** trạng thái thực tế, các phần phải đổi và lộ trình minikube.

**Các kết quả quan trọng khi truy lại**

- Codebase hiện là **snapshot gom chung, chưa phải Git monorepo**.
- Không clone source tất cả NF: AMF/SMF/NRF/AUSF/UDM/UDR dùng image OAI `v2.2.0`; RAN/UPF có source riêng.
- **24 patch khớp nguyên nội dung với fork NIST testbed cũ**, nên không thể gọi tất cả là patch tự viết.
- Mình dựng source tạm từ commit + patch tổng hợp: các file tracked của **bốn repo chính đều khớp** snapshot hiện tại. File mới của xApp/scenario phải bổ sung riêng.
- Quy trình clone Internet và build trên máy sạch **chưa được chạy thử toàn bộ**; tài liệu ghi rõ giới hạn này.

**Có đang chạy Docker không?**

Cần phân biệt kiến trúc và trạng thái hiện tại:

| Thành phần | Cách triển khai của Codebase | Lúc kiểm tra |
|---|---|---|
| Core/UPF | Docker Compose | Không chạy |
| gNB/UE/FlexRIC | Binary trên host, UE có namespace | Không thấy tiến trình chạy |
| Kubernetes trên máy | Cluster riêng, containerd | Một node `Ready`; chưa thấy workload OAI/FlexRIC của Codebase |
| Minikube | Profile cũ dùng Docker driver | Container node đã mất |

Vì vậy, **Codebase dùng Compose + host processes; máy đã có Kubernetes nhưng Codebase chưa được triển khai vào đó**.

**Chuyển minikube được, nhưng không chỉ đổi YAML.**

- Core control plane có thể tận dụng [Helm charts của OAI](https://gitlab.eurecom.fr/oai/orchestration/charts), nhưng cần kiểm tra tương thích với UPF tùy chỉnh.
- Phần khó là UPF eBPF: quyền load BPF, kernel node, interface N3/N4/N6, IP/route và vòng đời XDP. [Multus](https://github.com/k8snetworkplumbingwg/multus-cni) phù hợp để tạo nhiều interface cho pod.
- gNB/UE/FlexRIC cần đóng image từ source đã patch; runner phải thay các thao tác Docker/PID/netns bằng Kubernetes.
- Minikube Docker driver vẫn dùng Docker để chạy node Kubernetes; pod có thể dùng containerd bên trong. [Tài liệu minikube](https://minikube.sigs.k8s.io/docs/drivers/docker/).

**Phát hiện mới cần xử lý trước:** generator chưa được truyền `--oai-upf-bpf=true`. YAML bật eBPF nhưng Compose UPF hiện chỉ thêm `NET_ADMIN`, thiếu các quyền mà nhánh BPF của 5gdeploy bổ sung. Mình đã ghi vào tài liệu và cập nhật hướng dẫn chạy cũ; chưa sửa runtime script.

Lộ trình mình đề xuất: **sửa và xác nhận baseline Compose → đưa một UPF/core lên Kubernetes → thêm RAN/FlexRIC → chuyển runner**.

> dựa trên document BUILD-FROM-SCRATCH.md thì tức là codebase hiện tại của tao vẫn có nhiều phần đên từ repo cũ O-RAN-Testbed-Automation đúng không? trong đó thì có nhiều phần ví dụ như là 5gcore (5gdeploy) là không phải của openairinterface à? tao muốn chuyển qua dùng hết của openairinterface được không

Đúng. **Codebase hiện tại kết hợp OAI, FlexRIC và bộ automation của NIST**, không phải toàn bộ đều do OpenAirInterface cung cấp.

Điểm cần phân biệt: **5gdeploy không phải implementation 5G Core**. Nó là công cụ của NIST để sinh cấu hình, tạo mạng và triển khai các NF. Với cấu hình hiện tại, **AMF/SMF/UPF… vẫn là OAI**, chỉ được triển khai thông qua 5gdeploy.

| Thành phần | Nguồn hiện tại |
|---|---|
| gNB/UE | OAI RAN + patch |
| AMF/SMF/NRF/AUSF/UDM/UDR | Image OAI |
| UPF | OAI + patch URR riêng |
| Sinh cấu hình/triển khai core | **NIST 5gdeploy** |
| Script build/start/traffic | Kế thừa **O-RAN-Testbed-Automation**, đã port |
| near-RT RIC/xApp | **FlexRIC/Mosaic5G** + patch |

**Có thể bỏ NIST/5gdeploy và chuyển sang cách triển khai trực tiếp của OAI.** Việc này chủ yếu thay lớp triển khai, không cần viết lại core.

Với mục tiêu Kubernetes của bạn, hướng chuyển hợp lý là:

1. **Giữ source OAI RAN và UPF**, cùng các patch cần cho nghiên cứu.
2. **Thay 5gdeploy bằng Helm charts OAI**, tự quản lý cấu hình NF, subscriber và mạng.
3. **Thay script NIST bằng script riêng gọn hơn** để build image, triển khai Helm, tạo traffic và thu kết quả.
4. **Giữ FlexRIC nếu vẫn cần E2/KPM/xApp**. Bộ OAI Core không thay thế vai trò near-RT RIC.
5. Khi bản mới chạy đạt yêu cầu, bỏ dependency vào `src/5gdeploy` và `scripts/legacy`.

Có hai mục tiêu khác nhau:

- **“Dùng OAI cho RAN và 5G Core, bỏ automation NIST”**: làm được và phù hợp với hướng bạn đang muốn.
- **“Mọi thành phần đều nguyên bản OAI, không có phần ngoài hay patch”**: sẽ mất chức năng nghiên cứu riêng như luồng URR reporting và xApp CSV; các công cụ nền như Kubernetes/database cũng vẫn là dự án khác.

**Mình đề xuất chọn mục tiêu đầu:** OAI RAN + OAI Core/UPF, triển khai Kubernetes trực tiếp, giữ FlexRIC và chỉ giữ những patch đã xác định cần thiết. Như vậy nguồn gốc và phần đóng góp của bạn cũng dễ trình bày trong đồ án hơn.

> đoạn này thì nist đang triển khai thế nào

:codex-annotation{index="1"} Hiện phần kế thừa NIST triển khai bằng **5gdeploy + Docker Compose + Bash scripts**, theo luồng này:

```text
configs/core/options.yaml
          ↓ configure-core.sh
5gdeploy + scenario orantestbed
          ↓ sinh cấu hình
compose/core/
  ├── compose.yml          # Container, image, interface, IP, route
  ├── cp-cfg/              # Cấu hình các NF control plane
  └── up-cfg/              # Cấu hình UPF
          ↓ start-core.sh
Docker Compose chạy các NF OAI
```

**5gdeploy làm phần gì?**

- Nhận mô tả topology: gNB, UPF, slice, DNN và subscriber.
- Sinh cấu hình cho từng NF và database.
- Sinh Docker Compose, các mạng N2/N3/N4/N6…, địa chỉ và lệnh thiết lập route.
- Dùng image OAI để chạy core; thêm container hỗ trợ nối mạng và mô phỏng Data Network.

Scenario `orantestbed` được dựng từ `20230817` — file bạn đang mở là tài liệu của scenario nền, không nhất thiết phản ánh cấu hình cuối sau khi script chỉnh lại.

**Bash scripts làm phần gì?**

| Việc | Script hiện tại |
|---|---|
| Sinh cấu hình core | `configure-core.sh` |
| Build image UPF tùy chỉnh | `build-upf.sh` |
| Bật/tắt core qua Compose | `start-core.sh`, `stop-core.sh` |
| Chạy gNB/UE/FlexRIC trên host | `start-gnb.sh`, `start-ue.sh`, `start-flexric.sh` |
| Tạo namespace/mạng UE | `setup-ue-network.sh` |
| Phát traffic iperf2 | `traffic-dl.sh`, `traffic-ul.sh` |
| Chạy thí nghiệm, thu KPM/PFCP/log | `run-experiment.sh` |

**Không phải toàn bộ bảng trên là NIST nguyên bản:** các script hiện tại đã được port/chỉnh sửa; profile UPF research và runner KPM/URR là phần tích hợp local.

Khi chuyển sang Kubernetes, bạn thay **cơ chế sinh cấu hình và điều phối** này: Helm quản lý NF/config, CNI/Multus quản lý mạng pod, còn script riêng gọi Helm/kubectl để chạy thí nghiệm. Implementation AMF/SMF/UPF của OAI vẫn được giữ.

> tức là image core vẫn là của oai đúng không, còn nist chỉ configure về mặt network liên quan. list cho tao xem các script của nist và 5gdeploy đang cấu hình gì, và nếu tao chuyển qua chạy minikube thì sẽ phải cấu hình lại như thế nà o

<details><summary>2 previous messages</summary>

> Mình sẽ đối chiếu các script đang dùng để liệt kê chúng cấu hình gì, rồi chỉ ra phần tương ứng cần chuyển sang Helm/Kubernetes khi chạy minikube.
>
> <details><summary>Ran a command, searched the web</summary>
>
> - Ran `rg -n '^(#|[A-Z_]+=)|yq |sed |iptables|sysctl|modprobe|generate-core|profile_|cp |sims|docker' scripts/configure-core.sh | tail -130; rg -n 'iptables|ip |sysctl|route|namespace|veth' scripts/setup-ue-network.sh | tail -40; rg -n 'update_conf|SST|SD|DNN|IMSI|KEY|OPC|AMF|RIC|PORT' scripts/configure-ue.sh scripts/configure-flexric.sh scripts/configure-gnb.sh | tail -70; ls src/5gdeploy/oai; rg -n 'bridge|cap_add|sysctl|volume|image|network|address' src/5gdeploy/oai/{cn5g,cp,up}.ts | head -65`
>
> Searched the web for `site.minikube.sigs.k8s.io docs drivers docker containerd ...`
>
> </details>
</details>

**Đúng: các NF core vẫn dùng implementation/image OAI. Nhưng NIST/5gdeploy không chỉ cấu hình network** — nó còn cấu hình PLMN, slice, DNN, subscriber, database, quan hệ giữa NF và cách khởi động container.

Riêng UPF dùng **image tự build từ OAI + patch URR của bạn**, tên `oai-upf-research:local`.

**1. Các script hiện tại đang cấu hình gì?**

Đây là các bản đang dùng trong Codebase, đã port/chỉnh sửa từ testbed; không phải tất cả còn nguyên bản NIST.

| Script | Công việc hiện tại | Khi chuyển minikube |
|---|---|---|
| [configure-core.sh](./scripts/configure-core.sh) | Đọc PLMN/TAC/slice/DNN; tạo 10 subscriber; chọn core/UPF; sinh scenario, config NF và SQL; thiết lập forwarding/NAT/SCTP | Tách thành Helm values, cấu hình NF, dữ liệu subscriber và chuẩn bị mạng node |
| `lib/ue-credentials.sh` | Chuẩn bị thông tin subscriber/SIM cho UE và core | Giữ logic dữ liệu; đưa khóa vào Secret và nạp subscriber vào DB |
| `lib/generate-core-scenario.sh` | Chạy 5gdeploy tạo `netdef.json`, Compose và config liên quan | Thay bằng render/install Helm |
| `lib/oai-upf-profile.sh` | Chọn image UPF, bật BPF/URR, bật usage reporting phía SMF, ghi metadata | Chuyển vào values/ConfigMap và `securityContext` của UPF |
| `configure-gnb.sh` | Cấu hình PLMN/TAC/S-NSSAI, AMF IP, IP bind N2/N3, RFsim và đường dẫn thư viện E2 | ConfigMap cho gNB; đổi IP/interface và đường dẫn trong image |
| `configure-ue.sh` | Cấu hình SIM, PDU session, DNN/slice và radio | Secret + ConfigMap cho UE |
| `configure-flexric.sh` | Sinh cấu hình RIC, địa chỉ và đường dẫn thư viện | ConfigMap; đổi endpoint khi RIC/xApp nằm khác pod |
| `setup-ue-network.sh` | Tạo namespace UE, veth, subnet `/30`, route và NAT | Mỗi UE một pod; CNI tạo namespace/interface, vẫn phải cấu hình TUN và route PDU |
| `build-upf.sh` | Build image UPF research | Giữ được; load image vào minikube hoặc push registry |
| `build-ran.sh`, `build-flexric.sh` | Áp patch và build binary host | Tái sử dụng bước build, bổ sung Dockerfile cho binary/library |
| `start-*`, `stop-*` | Docker Compose cho core; process host cho RAN/RIC | Helm/Kubernetes quản lý vòng đời |
| `traffic-dl.sh`, `traffic-ul.sh` | `docker exec dn_internet` và `ip netns exec ueN` để chạy iperf2 | `kubectl exec` vào DN pod và UE pod |
| `run-experiment.sh` | Chờ readiness, chạy xApp/traffic, bắt PFCP, thu log/CSV | Viết backend Kubernetes cho readiness, capture, exec và logs |

Một chi tiết quan trọng: `configure-core.sh` còn sửa **SQL khởi tạo database**, DNN và khóa chính của bảng subscription. Vì vậy bỏ script này mà chỉ dựng lại mạng thì subscriber có thể chưa đăng ký được.

**2. Bên trong 5gdeploy làm những phần nào?**

| File/module trong `src/5gdeploy` | Trách nhiệm |
|---|---|
| `scenario/orantestbed/scenario.ts` | Mô tả topology: gNB, UPF, slice, Data Network |
| `scenario/common/phones-vehicles.ts` | Dựng network model chung, PLMN/TAC và các thành phần |
| `replace-sims/` | Đưa danh sách SIM vào mô hình triển khai |
| `compose/ipalloc.ts` | Cấp địa chỉ IP cho các mạng/container |
| `netdef-compose/` | Chuyển network model thành cấu hình triển khai Compose |
| `oai/cn5g.ts` | Chọn image OAI, gắn config, interface và thiết lập chung cho NF |
| `oai/cp.ts` | Sinh cấu hình control plane, dữ liệu subscriber/SQL, danh sách UPF và thông tin slice/DNN |
| `oai/up.ts` | Sinh config UPF: SMF peer, NRF, DNN, N6 gateway, forwarding và quyền BPF |
| `oai/download.sh` | Tải template cấu hình OAI FED/NWDAF |
| `docker/bridge/` | Công cụ hỗ trợ nối mạng bằng pipework/Docker |
| `docker/dn/` | Container mô phỏng Data Network để kiểm tra traffic |

Nói chính xác: **OAI cung cấp chương trình NF; 5gdeploy chuyển topology và tham số thí nghiệm thành cấu hình để các NF đó chạy cùng nhau.**

**3. Chuyển minikube: cấu hình lại theo từng lớp**

Mình đề xuất mô hình lab đầu tiên: **một UE, một gNB, một UPF**, cùng cluster; giữ FlexRIC/xApp khi kiểm tra KPM.

| Lớp cấu hình | Hiện tại | Thiết kế minikube đề xuất |
|---|---|---|
| Image NF | Image OAI + UPF local | Giữ image; khai báo trong Helm values |
| PLMN/TAC/slice/DNN | `options.yaml` → script sửa nhiều file | Một bộ values chung → config NF/gNB/UE nhất quán |
| Subscriber | `sims.tsv` → SQL | Dữ liệu SIM trong Secret, Job/init DB để nạp subscription |
| Config NF | Bind mount `cp-cfg/`, `up-cfg/` | ConfigMap mount vào đúng đường dẫn NF đọc |
| Database | Container MariaDB | DB workload + PVC; giữ dữ liệu qua lần restart |
| Khám phá NF | IP/hostname do generator sinh | Service/DNS cho SBI; cấu hình địa chỉ quảng bá khớp endpoint thực |
| Interface telecom | Docker networks có tên/IP cố định | Secondary interfaces qua Multus |
| Route/NAT | Lệnh trong Compose và iptables host | Route trong namespace pod và gateway/NAT được thiết kế rõ |
| Quyền eBPF | Capability của container | `securityContext`, kernel node và chính sách runtime phù hợp |
| Kết quả thí nghiệm | File trên host | Volume/PVC hoặc collector xuất artifact |

OAI có [Helm Chart Catalog](https://gitlab.eurecom.fr/oai/orchestration/charts) để làm nền. Tuy nhiên cần chọn phiên bản chart tương thích; không thể mặc định chart mới nhất chạy được với toàn bộ image/config hiện tại.

**4. Network cụ thể sẽ thay đổi thế nào?**

Đề xuất cho lab, chưa phải cấu hình đã triển khai:

| Kết nối | Hai đầu | Cách bố trí |
|---|---|---|
| SBI | NRF/AMF/SMF/AUSF/UDM/UDR | Mạng pod mặc định + Service/DNS |
| N2 — SCTP/38412 | gNB ↔ AMF | Secondary network N2 |
| N3 — UDP/2152 | gNB ↔ UPF | Secondary network N3 |
| N4 — UDP/8805 | SMF ↔ UPF | Secondary network N4 |
| N6 | UPF ↔ DN | Secondary network N6 + route về dải IP UE |
| E2 — SCTP/36421 | gNB ↔ FlexRIC | Mạng pod có SCTP hoạt động hoặc mạng riêng |
| RFsim — TCP/4043 | UE ↔ gNB | Mạng pod, endpoint gNB reach được từ UE |

[Multus](https://github.com/k8snetworkplumbingwg/multus-cni) cho phép gắn nhiều interface vào pod. Chẳng hạn UPF có `eth0` cho mạng mặc định và `n3`, `n4`, `n6` cho datapath. **Tên interface trong pod phải khớp YAML UPF.**

Bạn không bắt buộc giữ IP cũ. Nếu đổi IP, phải cập nhật đồng bộ:

- AMF N2 endpoint trong gNB.
- Địa chỉ N3 được gNB/UPF quảng bá.
- SMF–UPF N4 peer.
- N6 gateway và route trả về dải UE.
- RIC endpoint; `127.0.0.1` không còn đúng khi nằm khác pod.

Với [minikube Docker driver](https://minikube.sigs.k8s.io/docs/drivers/docker/), node nằm trong container Docker. Vì thế **không bê nguyên các lệnh iptables/bridge trên laptop vào rồi kỳ vọng mạng pod hoạt động tương tự**.

**5. Phần giữ và phần thay**

- **Giữ:** implementation/image OAI, patch URR, patch RAN/FlexRIC, thông số PLMN/SIM/slice/DNN và tiêu chí đo.
- **Thay:** 5gdeploy generator, Docker networks/pipework, launcher host, namespace UE thủ công và các thao tác Docker trong runner.
- **Kiểm tra lại:** quyền BPF, routing hai chiều, subscriber DB, endpoint NF và capture PFCP.

Đặc biệt, Compose hiện còn thiếu nhánh cấp quyền BPF dù YAML đã bật eBPF. Khi chuyển Kubernetes phải xử lý phần này rõ ràng, không sao chép nguyên quyền hiện tại sang pod.

> nói chung việc chuyển qua cài đặt trên kubernetes sẽ khiến việc config có hệ thống hơn đúng không. thay vì sử dụng một đống file shell script

**Đúng — nếu tổ chức tốt, Kubernetes/Helm sẽ giúp cấu hình có hệ thống và dễ tái lập hơn.** Bạn chuyển từ chuỗi script sửa file rồi chạy lệnh sang khai báo trạng thái mong muốn:

| Hiện tại | Kubernetes/Helm |
|---|---|
| Script sửa nhiều file bằng `sed`, `yq` | Bộ `values.yaml` sinh cấu hình qua template |
| Script start/stop, quản lý PID | Kubernetes quản lý vòng đời pod |
| Config rải rác, bind mount | ConfigMap; Secret cho khóa SIM/mật khẩu |
| Tạo mạng bằng script | CNI/Multus và khai báo network |
| Kiểm tra process/log để chờ sẵn sàng | Startup/readiness probes phù hợp |
| Thu log từng thành phần | Cách truy cập log thống nhất |

**Nhưng độ phức tạp không tự biến mất:** IP/interface, route, subscriber, slice và quyền eBPF vẫn phải cấu hình đúng. Nếu chuyển máy móc, bạn chỉ đổi “nhiều shell script” thành “nhiều YAML”.

Với codebase này, nên hướng tới:

- **Một bộ values cho mỗi môi trường**: thông số mạng, PLMN, slice, DNN, image.
- **Chart/template dùng chung**: sinh config và workload từ các values đó.
- **Script mỏng**: chỉ còn lệnh build/deploy và chạy thí nghiệm.
- **Runner riêng**: tạo traffic, bắt PFCP, thu KPM và đánh giá kết quả.

Như vậy, **Helm/Kubernetes quản lý triển khai; script quản lý thí nghiệm**. Không cần loại bỏ hoàn toàn shell, mà giảm việc shell phải sửa cấu hình và tự quản lý dịch vụ.

> tạo plan triển khai workload migrate sang k8s (minikube) dựa trên các phân tích bên trên

<details><summary>5 previous messages</summary>

> Mình sẽ kiểm tra tài nguyên máy và cấu hình hiện tại để chốt phạm vi migration, sau đó lập kế hoạch theo các mốc có thể kiểm thử: core/UPF, RAN/FlexRIC và runner thí nghiệm.
>
> <details><summary>Ran a command</summary>
>
> - Ran `free -h; nproc; df -h .; cat configs/core/options.yaml | head -58; rg -n 'enable_qer|enable_urr|enable_bpf' compose/core/up-cfg/upf1.yaml; ls docs; kubectl config current-context; minikube version; rg -n 'image:|subnet:' compose/core/compose.yml | tail -30`
>
> </details>
>
> Mình chốt phạm vi: toàn stack trên minikube, một UE/một slice/một UPF; backend mới không phụ thuộc 5gdeploy, giữ Compose để đối chiếu; UPF sẽ có cấu hình ép XDP-SKB. Mình sẽ kiểm tra tiếp chart OAI và chỗ cấu hình mode trong UPF để xác định cách triển khai cụ thể.
>
> <details><summary>Explored a file, a search, ran 5 commands, searched the web</summary>
>
> - Ran `rg -n 'xdp_flags_|ProgramLifeCycle\(' src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp; cat src/oai-upf/src/upf_app/include/upf_pipeline_config.h | head -100; rg -n 'enable_bpf|support_features' src/oai-upf/src/upf_app/app/upf_config_yaml.cpp | head -20; rg -n 'health|association' scripts/run-experiment.sh | head -20; cat configs/flexric/flexric.conf; rg -n 'BANDWIDTH_RBS|NUMEROLOGY|BAND=|FREQUENCY' scripts/start-ue.sh; command -v helm; ip -4 route | head -12`
>
> Searched the web for `site.gitlab.eurecom.fr/oai/orchestration/charts oai-upf multus values.yaml ...`
>
> - Ran `git ls-remote https://gitlab.eurecom.fr/oai/orchestration/charts.git HEAD 'refs/heads/*' 'refs/tags/v2.2*'`
>
> - Ran `python3 - <<'PY'
> import urllib.request,json
> u='https://gitlab.eurecom.fr/api/v4/projects/oai%2Forchestration%2Fcharts'
> try:
>  d=json.load(urllib.request.urlopen(u,timeout=15));print({k:d.get(k) for k in ['id','default_branch','web_url']})
> except Exception as e: print(type(e).__name__,str(e))
> PY`
>
> - Ran `python3 - <<'PY'
> import urllib.request,json
> base='https://gitlab.eurecom.fr/api/v4/projects/oai%2Forchestration%2Fcharts/repository/'
> for suffix in ['tree?ref=7925f939ea36a3c4c1df5525f3718ce8470f6b3f&per_page=100','files/README.md/raw?ref=7925f939ea36a3c4c1df5525f3718ce8470f6b3f']:
>  try:
>   data=urllib.request.urlopen(base+suffix,timeout=12).read().decode();print(data[:9000])
>  except Exception as e:print(type(e).__name__,str(e))
> PY`
>
> <details><summary>Explored 2 files, a search</summary>
>
> - Searched for `getenv|3642|3646|INADDR_ANY|inet_addr|get_ric` in `e42_xapp.c`
> - Read `./src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp`
> - Read `./src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp`
>
> </details>
>
> - Ran `python3 - <<'PY'
> import urllib.request,urllib.parse,concurrent.futures
> base='https://gitlab.eurecom.fr/api/v4/projects/6343/repository/files/'
> paths=['oai-5g-core/oai-upf/values.yaml','oai-5g-core/oai-smf/values.yaml','oai-5g-core/oai-5g-basic/Chart.yaml','oai-5g-ran/oai-flexric/values.yaml','oai-5g-ran/oai-gnb/values.yaml']
> def get(p):
>  try:
>   s=urllib.request.urlopen(base+urllib.parse.quote(p,safe='')+'/raw?ref=7925f939ea36a3c4c1df5525f3718ce8470f6b3f',timeout=15).read().decode()
>   keep=[line for line in s.splitlines() if any(x in line.lower() for x in ['multus','image','repository:','tag:','bpf','urr','privileg','mount','config','n3','n4','n6','ipadd','hostinterface','version:','name:','port:','type:'])]
>   return p+'\n'+'\n'.join(keep)[:6500]
>  except Exception as e:return p+' '+str(e)
> with concurrent.futures.ThreadPoolExecutor(max_workers=5) as e:
>  for s in e.map(get,paths):print(s+'\n')
> PY`
>
> </details>
>
> Plan
>
> # Migration toàn stack OAI sang Kubernetes single-node bằng minikube
>
> ## 1. Mục tiêu và phạm vi
>
> Triển khai **OAI Core + UPF eBPF + gNB/UE RFsim + FlexRIC/xApp** trên một cluster minikube riêng, với **một UE, một slice, một UPF**. Cấu hình được quản lý bằng Helm; backend mới không gọi 5gdeploy hoặc script legacy.
>
> Các lựa chọn đã chốt:
>
> - Giữ backend Compose để đối chiếu và rollback.
> - UPF bắt buộc chạy **XDP-SKB**, giữ patch URR reporting.
> - Giữ **OAI SMF v2.2.0**, chưa bổ sung tính năng tùy chỉnh ngưỡng URR.
> - Cho phép **UPF privileged trong lab**; không mở privileged mặc định cho mọi workload.
> - Không migrate SMO/ONAP/non-RT RIC đang có trên cluster khác.
> - Chưa triển khai multi-node, nhiều slice/UPF, USRP hoặc HA.
>
> Nghiệm thu phải có UE đăng ký và tạo PDU session, traffic UL/DL nhận được, PFCP Usage Report được SMF chấp nhận và xApp thu được KPM.
>
> ## 2. Kiến trúc triển khai
>
> **Cluster**
>
> - Tạo profile/context `oai-lab`, namespace `oai-lab`.
> - Minikube Docker driver, runtime containerd, Kubernetes `v1.33.13`, CNI mặc định `bridge`.
> - Phân bổ ban đầu **8 CPU, 16 GiB RAM**; build image tuần tự để giảm áp lực tài nguyên.
> - Preflight kiểm tra RAM, dung lượng đĩa, subnet, SCTP và BPF. Không tự xóa image/cache hay thay đổi cluster `kubernetes-admin@kubernetes`.
> - Mọi lệnh Kubernetes/Helm phải chỉ định context; thao tác dừng/xóa giới hạn trong lab.
>
> **Helm và image**
>
> - Lấy [OAI Helm charts](https://gitlab.eurecom.fr/oai/orchestration/charts) tại commit `7925f939ea36a3c4c1df5525f3718ce8470f6b3f` làm baseline, lưu provenance và patch chart riêng.
> - Dùng chart NF OAI cho core/RAN/FlexRIC; bổ sung chart tích hợp cho mạng lab, MariaDB, DN và xApp.
> - Giữ image AMF/SMF/NRF/AUSF/UDM/UDR `v2.2.0`, MariaDB `10.6`.
> - Build image UPF, gNB, UE và FlexRIC/xApp từ source đã patch trong workspace. Không dùng image `develop` thay thế binary research.
> - Khai báo image rõ ràng cho mọi workload, đặc biệt UPF: chart baseline đang có default repository không phù hợp.
> - Đặt tag image theo source/patch hash, load vào minikube, ghi image ID/digest trong artifact.
>
> **Mạng**
>
> Dùng Multus với bridge + static IPAM cho các interface telecom. Các bridge nằm trong node minikube; không dùng pipework/Docker bridge helper của 5gdeploy.
>
> | Mạng | Subnet mặc định | Endpoint |
> |---|---|---|
> | N2 | `172.30.22.0/24` | AMF `.10`, gNB `.20` |
> | N3 | `172.30.23.0/24` | UPF `.10`, gNB `.20` |
> | N4 | `172.30.24.0/24` | SMF `.10`, UPF `.20` |
> | N6 | `172.30.26.0/24` | DN `.10`, UPF `.20` |
> | E2/xApp | `172.30.27.0/24` | FlexRIC `.10`, gNB `.20`, xApp `.30` |
>
> - SBI/database sử dụng mạng pod mặc định và Service/DNS.
> - RFsim dùng Service TCP/4043 của gNB; entrypoint UE resolve endpoint thành địa chỉ phù hợp trước khi chạy.
> - Giữ dải PDU UE `10.1.0.0/16`; DN có route trả về qua UPF N6.
> - Traffic nghiệm thu chạy giữa DN và UE, chưa yêu cầu Internet breakout.
> - Không thêm default route từ secondary networks; khai báo các route cần thiết riêng.
> - Preflight từ chối subnet trùng. Tên interface `n2/n3/n4/n6/e2` phải khớp config ứng dụng.
> - Không dùng `hostNetwork` cho NF trong bản đầu, không cấu hình N9.
>
> ## 3. Thay đổi implementation
>
> **Cấu hình và dữ liệu**
>
> - Tạo một bộ values lab tại `deploy/k8s/values/minikube.yaml`, bao gồm topology, image, tài nguyên, PLMN/TAC, slice/DNN, radio và reporting.
> - Giữ các giá trị baseline: PLMN `00101`, TAC `7`, SST `1`, SD `FFFFFF`, DNN `nist-dnn`; giữ đúng cách biểu diễn “SD không chỉ định” theo từng NF.
> - Lấy UE1 hiện có làm subscriber mẫu; đưa khóa SIM/mật khẩu vào Secret, không ghi vào values hoặc log.
> - Template sinh ConfigMap NF/gNB/UE/FlexRIC từ values; không sửa source/config bằng chuỗi `sed`.
> - MariaDB dùng PVC; Job nạp subscriber phải chạy lặp an toàn, không `DROP DATABASE` mỗi lần deploy.
> - Cấu hình SMF chỉ một UPF, bật usage reporting; UPF bật BPF/URR. Ngưỡng thực lấy từ Create URR, không trình bày giá trị metadata như tham số SMF đã hỗ trợ.
>
> **UPF và XDP-SKB**
>
> - Bổ sung tùy chọn YAML `upf.support_features.xdp_mode` với `auto`, `skb`, `native`; mặc định `auto` để giữ tương thích Compose.
> - Values Kubernetes đặt `skb`; không thử native hoặc fallback âm thầm khi đã yêu cầu SKB.
> - Truyền mode từ parser đến loader; log interface, mode và program ID.
> - Sửa teardown dùng đúng mode attach, kiểm tra program thuộc instance trước khi detach.
> - Xuất patch riêng cho thay đổi này; giữ patch URR `00b7485` tách biệt.
> - UPF chạy privileged trong namespace lab; kiểm tra load/attach thật trên N3/N6 trước khi đưa UE vào.
>
> **RAN, RIC và traffic**
>
> - Giữ RFsim band 78, 106 PRB, numerology 1, tần số đang dùng; E2AP v3/KPM v3.
> - Image RAN chứa đúng thư viện E2/SM. FlexRIC và xApp dùng endpoint E2 tĩnh, không dùng `127.0.0.1` khi khác pod.
> - UE chạy trong namespace mạng pod, có `/dev/net/tun` và quyền `NET_ADMIN`; bỏ tạo namespace/veth bằng script host.
> - Tạo image DN có sẵn iperf2 và công cụ mạng; không cài package mỗi lần phát traffic.
> - gNB/UE/UPF dùng một replica và chiến lược Recreate để tránh trùng IP secondary khi upgrade.
>
> **Điều phối và artifact**
>
> - Tạo CLI mỏng tại `scripts/k8s/lab.sh` với các lệnh `check`, `build`, `up`, `status`, `experiment`, `down`.
> - CLI gọi Helm/kubectl; Helm quản lý cấu hình/workload, CLI quản lý trình tự và thí nghiệm.
> - Capture PFCP bằng sidecar trong SMF, bắt đầu trước UE; không dò bridge Docker.
> - xApp và capture ghi ra volume artifact; runner xuất về `artifacts/experiments/<run-id>`.
> - Giữ schema CSV KPM/URR/phases hiện tại, bổ sung backend, chart/source/image hash và XDP mode.
> - `down` giữ DB và artifact; không xóa cluster hoặc dữ liệu ngoài release lab.
>
> ## 4. Thứ tự thực hiện và kiểm thử
>
> **Mốc 0 — Chuẩn hóa baseline**
>
> - Sửa generator Compose truyền đúng cờ BPF và kiểm tra capability sinh ra.
> - Thu baseline Compose nếu chạy được; lưu cả lỗi nếu chưa chạy được, không dùng kết quả mock làm bằng chứng runtime.
> - Ghi nhận source/patch, config và image để so sánh với Kubernetes.
>
> **Mốc 1 — Render và bootstrap**
>
> - Vendor/pin chart và dependency CNI; thêm override cho custom image, network và config.
> - Chạy Helm lint/render, kiểm tra schema, image, interface, subscriber và subnet.
> - Tạo minikube riêng; kiểm tra Multus, secondary interfaces, DNS, SCTP và image availability.
> - Dừng ở preflight nếu thiếu tài nguyên hoặc xung đột; không tự đổi topology.
>
> **Mốc 2 — Database và core**
>
> - Khởi động DB, nạp subscriber, rồi NRF/UDR/UDM/AUSF/AMF/SMF/UPF/DN.
> - Kiểm tra NF registration, PFCP association, route N4/N6.
> - Xác nhận BPF loader không có lỗi và XDP-SKB attach được; kiểm tra lại sau khi có session nếu chương trình được nạp theo session.
> - Startup/readiness probes kiểm tra dịch vụ; PFCP association là integration gate, tránh liveness restart loop do peer chưa sẵn sàng.
>
> **Mốc 3 — Radio và KPM**
>
> - Khởi động FlexRIC → gNB → PFCP capture → UE → xApp.
> - Xác nhận E2 setup, RFsim connection, registration và PDU session.
> - Xác nhận xApp ghi mẫu KPM với node/UE identity đúng.
>
> **Mốc 4 — Nghiệm thu end-to-end**
>
> - Chạy mặc định iperf2 **10 Mbit/s × 120 giây mỗi chiều**; kiểm tra dữ liệu thực nhận ở receiver và packet loss.
> - Capture phải có Create URR, ngưỡng/trigger thực, Usage Report và response chấp nhận từ SMF.
> - Đối chiếu byte UL/DL/total trong report; không yêu cầu bằng tuyệt đối iperf vì cách đếm lớp giao thức có thể khác.
> - Nếu lượng traffic chưa vượt ngưỡng thực, báo rõ và chạy lại với thời lượng đủ; không đánh dấu PASS khi thiếu report.
> - Restart UPF, tái thiết lập session UE và chạy lại traffic; kiểm tra không còn stale XDP/IPAM/route.
> - Chạy `up/down/up` và upgrade lại cùng values: subscriber không nhân đôi, config nhất quán, artifact còn nguyên.
>
> **Kiểm thử âm bắt buộc:** image thiếu, subnet trùng, mode XDP không hợp lệ, thiếu quyền BPF, SMF chưa sẵn sàng, subscriber sai và xApp không có mẫu. Mỗi lỗi phải dừng đúng bước, thu log và trả exit code thất bại.
>
> ## 5. Bàn giao và giới hạn
>
> Bàn giao gồm chart/values đã pin, Dockerfile cho thành phần research, patch XDP mode, CLI lab, kiểm thử và hướng dẫn dựng lại trên máy sạch. Cập nhật tài liệu migration với mapping từ script cũ sang Helm/Kubernetes.
>
> Chỉ tuyên bố migration hoàn tất khi có artifact end-to-end trên minikube chứng minh **SKB + traffic UL/DL + URR + KPM**. Giữ Compose và source 5gdeploy để đối chiếu; backend Kubernetes không phụ thuộc chúng.
>
> Thu hẹp quyền UPF, tùy chỉnh ngưỡng SMF, nhiều UPF/slice, tối ưu hiệu năng và Internet breakout thuộc giai đoạn sau.
</details>

> PLEASE IMPLEMENT THIS PLAN:
> # Migration toàn stack OAI sang Kubernetes single-node bằng minikube
>
> ## 1. Mục tiêu và phạm vi
>
> Triển khai **OAI Core + UPF eBPF + gNB/UE RFsim + FlexRIC/xApp** trên một cluster minikube riêng, với **một UE, một slice, một UPF**. Cấu hình được quản lý bằng Helm; backend mới không gọi 5gdeploy hoặc script legacy.
>
> Các lựa chọn đã chốt:
>
> - Giữ backend Compose để đối chiếu và rollback.
> - UPF bắt buộc chạy **XDP-SKB**, giữ patch URR reporting.
> - Giữ **OAI SMF v2.2.0**, chưa bổ sung tính năng tùy chỉnh ngưỡng URR.
> - Cho phép **UPF privileged trong lab**; không mở privileged mặc định cho mọi workload.
> - Không migrate SMO/ONAP/non-RT RIC đang có trên cluster khác.
> - Chưa triển khai multi-node, nhiều slice/UPF, USRP hoặc HA.
>
> Nghiệm thu phải có UE đăng ký và tạo PDU session, traffic UL/DL nhận được, PFCP Usage Report được SMF chấp nhận và xApp thu được KPM.
>
> ## 2. Kiến trúc triển khai
>
> **Cluster**
>
> - Tạo profile/context `oai-lab`, namespace `oai-lab`.
> - Minikube Docker driver, runtime containerd, Kubernetes `v1.33.13`, CNI mặc định `bridge`.
> - Phân bổ ban đầu **8 CPU, 16 GiB RAM**; build image tuần tự để giảm áp lực tài nguyên.
> - Preflight kiểm tra RAM, dung lượng đĩa, subnet, SCTP và BPF. Không tự xóa image/cache hay thay đổi cluster `kubernetes-admin@kubernetes`.
> - Mọi lệnh Kubernetes/Helm phải chỉ định context; thao tác dừng/xóa giới hạn trong lab.
>
> **Helm và image**
>
> - Lấy [OAI Helm charts](https://gitlab.eurecom.fr/oai/orchestration/charts) tại commit `7925f939ea36a3c4c1df5525f3718ce8470f6b3f` làm baseline, lưu provenance và patch chart riêng.
> - Dùng chart NF OAI cho core/RAN/FlexRIC; bổ sung chart tích hợp cho mạng lab, MariaDB, DN và xApp.
> - Giữ image AMF/SMF/NRF/AUSF/UDM/UDR `v2.2.0`, MariaDB `10.6`.
> - Build image UPF, gNB, UE và FlexRIC/xApp từ source đã patch trong workspace. Không dùng image `develop` thay thế binary research.
> - Khai báo image rõ ràng cho mọi workload, đặc biệt UPF: chart baseline đang có default repository không phù hợp.
> - Đặt tag image theo source/patch hash, load vào minikube, ghi image ID/digest trong artifact.
>
> **Mạng**
>
> Dùng Multus với bridge + static IPAM cho các interface telecom. Các bridge nằm trong node minikube; không dùng pipework/Docker bridge helper của 5gdeploy.
>
> | Mạng | Subnet mặc định | Endpoint |
> |---|---|---|
> | N2 | `172.30.22.0/24` | AMF `.10`, gNB `.20` |
> | N3 | `172.30.23.0/24` | UPF `.10`, gNB `.20` |
> | N4 | `172.30.24.0/24` | SMF `.10`, UPF `.20` |
> | N6 | `172.30.26.0/24` | DN `.10`, UPF `.20` |
> | E2/xApp | `172.30.27.0/24` | FlexRIC `.10`, gNB `.20`, xApp `.30` |
>
> - SBI/database sử dụng mạng pod mặc định và Service/DNS.
> - RFsim dùng Service TCP/4043 của gNB; entrypoint UE resolve endpoint thành địa chỉ phù hợp trước khi chạy.
> - Giữ dải PDU UE `10.1.0.0/16`; DN có route trả về qua UPF N6.
> - Traffic nghiệm thu chạy giữa DN và UE, chưa yêu cầu Internet breakout.
> - Không thêm default route từ secondary networks; khai báo các route cần thiết riêng.
> - Preflight từ chối subnet trùng. Tên interface `n2/n3/n4/n6/e2` phải khớp config ứng dụng.
> - Không dùng `hostNetwork` cho NF trong bản đầu, không cấu hình N9.
>
> ## 3. Thay đổi implementation
>
> **Cấu hình và dữ liệu**
>
> - Tạo một bộ values lab tại `deploy/k8s/values/minikube.yaml`, bao gồm topology, image, tài nguyên, PLMN/TAC, slice/DNN, radio và reporting.
> - Giữ các giá trị baseline: PLMN `00101`, TAC `7`, SST `1`, SD `FFFFFF`, DNN `nist-dnn`; giữ đúng cách biểu diễn “SD không chỉ định” theo từng NF.
> - Lấy UE1 hiện có làm subscriber mẫu; đưa khóa SIM/mật khẩu vào Secret, không ghi vào values hoặc log.
> - Template sinh ConfigMap NF/gNB/UE/FlexRIC từ values; không sửa source/config bằng chuỗi `sed`.
> - MariaDB dùng PVC; Job nạp subscriber phải chạy lặp an toàn, không `DROP DATABASE` mỗi lần deploy.
> - Cấu hình SMF chỉ một UPF, bật usage reporting; UPF bật BPF/URR. Ngưỡng thực lấy từ Create URR, không trình bày giá trị metadata như tham số SMF đã hỗ trợ.
>
> **UPF và XDP-SKB**
>
> - Bổ sung tùy chọn YAML `upf.support_features.xdp_mode` với `auto`, `skb`, `native`; mặc định `auto` để giữ tương thích Compose.
> - Values Kubernetes đặt `skb`; không thử native hoặc fallback âm thầm khi đã yêu cầu SKB.
> - Truyền mode từ parser đến loader; log interface, mode và program ID.
> - Sửa teardown dùng đúng mode attach, kiểm tra program thuộc instance trước khi detach.
> - Xuất patch riêng cho thay đổi này; giữ patch URR `00b7485` tách biệt.
> - UPF chạy privileged trong namespace lab; kiểm tra load/attach thật trên N3/N6 trước khi đưa UE vào.
>
> **RAN, RIC và traffic**
>
> - Giữ RFsim band 78, 106 PRB, numerology 1, tần số đang dùng; E2AP v3/KPM v3.
> - Image RAN chứa đúng thư viện E2/SM. FlexRIC và xApp dùng endpoint E2 tĩnh, không dùng `127.0.0.1` khi khác pod.
> - UE chạy trong namespace mạng pod, có `/dev/net/tun` và quyền `NET_ADMIN`; bỏ tạo namespace/veth bằng script host.
> - Tạo image DN có sẵn iperf2 và công cụ mạng; không cài package mỗi lần phát traffic.
> - gNB/UE/UPF dùng một replica và chiến lược Recreate để tránh trùng IP secondary khi upgrade.
>
> **Điều phối và artifact**
>
> - Tạo CLI mỏng tại `scripts/k8s/lab.sh` với các lệnh `check`, `build`, `up`, `status`, `experiment`, `down`.
> - CLI gọi Helm/kubectl; Helm quản lý cấu hình/workload, CLI quản lý trình tự và thí nghiệm.
> - Capture PFCP bằng sidecar trong SMF, bắt đầu trước UE; không dò bridge Docker.
> - xApp và capture ghi ra volume artifact; runner xuất về `artifacts/experiments/<run-id>`.
> - Giữ schema CSV KPM/URR/phases hiện tại, bổ sung backend, chart/source/image hash và XDP mode.
> - `down` giữ DB và artifact; không xóa cluster hoặc dữ liệu ngoài release lab.
>
> ## 4. Thứ tự thực hiện và kiểm thử
>
> **Mốc 0 — Chuẩn hóa baseline**
>
> - Sửa generator Compose truyền đúng cờ BPF và kiểm tra capability sinh ra.
> - Thu baseline Compose nếu chạy được; lưu cả lỗi nếu chưa chạy được, không dùng kết quả mock làm bằng chứng runtime.
> - Ghi nhận source/patch, config và image để so sánh với Kubernetes.
>
> **Mốc 1 — Render và bootstrap**
>
> - Vendor/pin chart và dependency CNI; thêm override cho custom image, network và config.
> - Chạy Helm lint/render, kiểm tra schema, image, interface, subscriber và subnet.
> - Tạo minikube riêng; kiểm tra Multus, secondary interfaces, DNS, SCTP và image availability.
> - Dừng ở preflight nếu thiếu tài nguyên hoặc xung đột; không tự đổi topology.
>
> **Mốc 2 — Database và core**
>
> - Khởi động DB, nạp subscriber, rồi NRF/UDR/UDM/AUSF/AMF/SMF/UPF/DN.
> - Kiểm tra NF registration, PFCP association, route N4/N6.
> - Xác nhận BPF loader không có lỗi và XDP-SKB attach được; kiểm tra lại sau khi có session nếu chương trình được nạp theo session.
> - Startup/readiness probes kiểm tra dịch vụ; PFCP association là integration gate, tránh liveness restart loop do peer chưa sẵn sàng.
>
> **Mốc 3 — Radio và KPM**
>
> - Khởi động FlexRIC → gNB → PFCP capture → UE → xApp.
> - Xác nhận E2 setup, RFsim connection, registration và PDU session.
> - Xác nhận xApp ghi mẫu KPM với node/UE identity đúng.
>
> **Mốc 4 — Nghiệm thu end-to-end**
>
> - Chạy mặc định iperf2 **10 Mbit/s × 120 giây mỗi chiều**; kiểm tra dữ liệu thực nhận ở receiver và packet loss.
> - Capture phải có Create URR, ngưỡng/trigger thực, Usage Report và response chấp nhận từ SMF.
> - Đối chiếu byte UL/DL/total trong report; không yêu cầu bằng tuyệt đối iperf vì cách đếm lớp giao thức có thể khác.
> - Nếu lượng traffic chưa vượt ngưỡng thực, báo rõ và chạy lại với thời lượng đủ; không đánh dấu PASS khi thiếu report.
> - Restart UPF, tái thiết lập session UE và chạy lại traffic; kiểm tra không còn stale XDP/IPAM/route.
> - Chạy `up/down/up` và upgrade lại cùng values: subscriber không nhân đôi, config nhất quán, artifact còn nguyên.
>
> **Kiểm thử âm bắt buộc:** image thiếu, subnet trùng, mode XDP không hợp lệ, thiếu quyền BPF, SMF chưa sẵn sàng, subscriber sai và xApp không có mẫu. Mỗi lỗi phải dừng đúng bước, thu log và trả exit code thất bại.
>
> ## 5. Bàn giao và giới hạn
>
> Bàn giao gồm chart/values đã pin, Dockerfile cho thành phần research, patch XDP mode, CLI lab, kiểm thử và hướng dẫn dựng lại trên máy sạch. Cập nhật tài liệu migration với mapping từ script cũ sang Helm/Kubernetes.
>
> Chỉ tuyên bố migration hoàn tất khi có artifact end-to-end trên minikube chứng minh **SKB + traffic UL/DL + URR + KPM**. Giữ Compose và source 5gdeploy để đối chiếu; backend Kubernetes không phụ thuộc chúng.
>
> Thu hẹp quyền UPF, tùy chỉnh ngưỡng SMF, nhiều UPF/slice, tối ưu hiệu năng và Internet breakout thuộc giai đoạn sau.

<details><summary>13 previous messages</summary>

> Mình sẽ bắt đầu từ sửa baseline BPF và UPF XDP-SKB, rồi dựng chart/CLI và kiểm thử render trước khi tạo lab. Mọi thao tác cluster sẽ giới hạn ở context `oai-lab`; mình sẽ không sửa cluster Kubernetes đang chạy các workload khác.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `find .. -name AGENTS.md -print; ls deploy scripts/k8s 2>/dev/null; sed -n '1,220p' src/oai-upf/src/upf_app/app/upf_config_yaml.hpp; sed -n '1,210p' src/oai-upf/src/upf_app/app/upf_config_yaml.cpp; rg -n 'enable_bpf|enable_urr|to_upf_config' src/oai-upf/src/upf_app/app/upf_config_yaml.cpp src/oai-upf/src/upf_app/app/upf_config.hpp; head -100 src/oai-upf/src/upf_app/include/upf_network_config.h; head -70 src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp`
> - Ran `sed -n '330,405p' src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp; sed -n '660,710p' src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp; rg -n 'bpf_datapath|g_net_cfg' src/oai-upf/src/upf_app/control/Configuration.cpp; rg -n 'g_net_cfg' src/oai-upf/src/upf_app/include/upf_network_config.h; sudo -n true; df -BG .; docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | head -15`
> - Ran `mkdir -p deploy/k8s/vendor scripts/k8s tests/k8s; git clone --no-checkout https://gitlab.eurecom.fr/oai/orchestration/charts.git /tmp/oai-lab-charts-7925f93`
> - Ran `python3 - <<'PY'
> from pathlib import Path
> import shutil
> files=['src/upf_app/app/upf_config_yaml.hpp','src/upf_app/app/upf_config_yaml.cpp','src/upf_app/app/upf_config.hpp','src/upf_app/include/upf_network_config.h','src/upf_app/control/Configuration.cpp','src/upf_app/user/ProgramLifeCycle.hpp']
> base=Path('/tmp/oai-lab-upf-before');base.mkdir(exist_ok=True)
> for f in files:
>  p=base/f;p.parent.mkdir(parents=True,exist_ok=True)
>  if not p.exists():shutil.copyfile(Path('src/oai-upf')/f,p)
> p=Path('src/oai-upf/src/upf_app/app/upf_config_yaml.hpp');s=p.read_text().replace('option_config_value m_enable_bpf_datapath{};', 'option_config_value m_enable_bpf_datapath{};\n  std::string m_xdp_mode = "auto";');s=s.replace('bool get_option_enable_bpf_datapath() const;', 'bool get_option_enable_bpf_datapath() const;\n  const std::string& get_xdp_mode() const { return m_xdp_mode; }');p.write_text(s)
> p=Path('src/oai-upf/src/upf_app/app/upf_config_yaml.cpp');s=p.read_text().replace('#include <regex>','#include <regex>\n#include "XdpMode.hpp"');s=s.replace('  // Performance\n  if (node[UPF_ENABLE_BPF])', '  if (node["xdp_mode"]) {\n    m_xdp_mode = node["xdp_mode"].as<std::string>();\n    upf::ParseXdpMode(m_xdp_mode);  // Reject invalid modes before loading BPF.\n  }\n  // Performance\n  if (node[UPF_ENABLE_BPF])');s=s.replace('  std::string out;','  std::string out;\n  out.append(indent).append("XDP mode: ").append(m_xdp_mode).append("\\n");',1);s=s.replace('  cfg.enable_bpf_datapath =','  cfg.xdp_mode = upf_local->get_support_features().get_xdp_mode();\n  cfg.enable_bpf_datapath =');p.write_text(s)
> p=Path('src/oai-upf/src/upf_app/app/upf_config.hpp');s=p.read_text().replace('  bool enable_bpf_datapath;', '  bool enable_bpf_datapath;\n  std::string xdp_mode = "auto";');p.write_text(s)
> p=Path('src/oai-upf/src/upf_app/include/upf_network_config.h');s=p.read_text().replace('  bool bpf_datapath = false;', '  bool bpf_datapath = false;\n  std::string xdp_mode = "auto";');p.write_text(s)
> p=Path('src/oai-upf/src/upf_app/control/Configuration.cpp');s=p.read_text().replace('  upf::g_net_cfg.bpf_datapath', '  upf::g_net_cfg.xdp_mode = upf_cfg.xdp_mode;\n  upf::g_net_cfg.bpf_datapath',1);p.write_text(s)
> p=Path('src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp');s=p.read_text().replace('#include "logger.hpp"','#include "logger.hpp"\n#include "upf_network_config.h"\n#include "XdpMode.hpp"');start=s.index('    // Try attaching XDP program with smart fallback');end=s.index('    // Track linked interface',start)
> s=s[:start]+'''    const auto mode = upf::ParseXdpMode(upf::g_net_cfg.xdp_mode);
>     uint32_t mode_flags = upf::InitialXdpFlags(mode);
>     struct bpf_prog_info info {};
>     uint32_t info_len = sizeof(info);
>     if (bpf_obj_get_info_by_fd(prog_fd, &info, &info_len) != 0)
>       throw std::runtime_error("Cannot identify XDP program before attach");
>     int ret = bpf_xdp_attach(
>         if_index, prog_fd, xdp_flags_ | mode_flags, nullptr);
>     bool tried_native = false;
>     if (upf::ShouldFallbackToSkb(mode, ret)) {
>       mode_flags = XDP_FLAGS_SKB_MODE;
>       tried_native = true;
>       ret = bpf_xdp_attach(
>           if_index, prog_fd, xdp_flags_ | mode_flags, nullptr);
>     }
>     if (ret < 0) {
>       Logger::upf_app().error(
>           "[%s] XDP attach failed interface=%s requested_mode=%s error=%d",
>           name_.c_str(), interface, upf::g_net_cfg.xdp_mode.c_str(), ret);
>       throw std::runtime_error("XDP attach failed in requested mode");
>     }
>     const char* mode_str = mode_flags == XDP_FLAGS_SKB_MODE ? "skb" : "native";
>     interface_native_xdp_[std::string(interface)] = mode_flags == XDP_FLAGS_DRV_MODE;
>     xdp_attachments_[if_index] = {prog_fd, info.id, mode_flags};
>     Logger::upf_app().info(
>         "[%s] XDP attached interface=%s mode=%s program_id=%u",
>         name_.c_str(), interface, mode_str, info.id);
>
> '''+s[end:]
> start=s.index('    // Unlink XDP programs if in LINKED state');end=s.index('    // Destroy skeleton',start)
> s=s[:start]+'''    // Ownership is checked by ID and atomically enforced by old_prog_fd.
>     // Do not detach a replacement program installed by another instance.
>     for (const auto& entry : xdp_attachments_) {
>       uint32_t current_id = 0;
>       const auto& attachment = entry.second;
>       if (bpf_xdp_query_id(entry.first, attachment.mode, &current_id) != 0 ||
>           current_id != attachment.id) {
>         Logger::upf_app().warn(
>             "[%s] Skipping XDP detach on ifindex=%u: ownership changed",
>             name_.c_str(), entry.first);
>         continue;
>       }
>       struct bpf_xdp_attach_opts opts {};
>       opts.sz = sizeof(opts);
>       opts.old_prog_fd = attachment.fd;
>       const int ret = bpf_xdp_detach(entry.first, attachment.mode, &opts);
>       if (ret != 0)
>         Logger::upf_app().error("[%s] XDP detach failed ifindex=%u error=%d",
>                                 name_.c_str(), entry.first, ret);
>     }
>     xdp_attachments_.clear();
>     section_link_map_.clear();
>
> '''+s[end:];s=s.replace('  uint32_t xdp_flags_;','  struct XdpAttachment { int fd; uint32_t id; uint32_t mode; };\n  std::map<uint32_t, XdpAttachment> xdp_attachments_;\n  uint32_t xdp_flags_;');p.write_text(s)
> p=Path('src/oai-upf/src/upf_app/include/XdpMode.hpp');p.write_text('''// SPDX-License-Identifier: LicenseRef-CSSL-1.0
> #pragma once
> #include <cerrno>
> #include <linux/if_link.h>
> #include <stdexcept>
> #include <string>
> namespace upf {
> enum class XdpMode { Auto, Skb, Native };
> inline XdpMode ParseXdpMode(const std::string& mode) {
>   if (mode == "auto") return XdpMode::Auto;
>   if (mode == "skb") return XdpMode::Skb;
>   if (mode == "native") return XdpMode::Native;
>   throw std::invalid_argument("xdp_mode must be auto, skb or native");
> }
> inline unsigned InitialXdpFlags(XdpMode mode) {
>   return mode == XdpMode::Skb ? XDP_FLAGS_SKB_MODE : XDP_FLAGS_DRV_MODE;
> }
> inline bool ShouldFallbackToSkb(XdpMode mode, int result) {
>   return mode == XdpMode::Auto && result == -EOPNOTSUPP;
> }
> }
> ''')
> # Restore the generator's complete BPF branch rather than toggling YAML alone.
> p=Path('scripts/configure-core.sh');s=p.read_text();s=s.replace('"$SCRIPTS_ROOT/lib/generate-core-scenario.sh" "$CORE_STAGE" orantestbed \\', 'BPF_ARGS=()\nif [[ "$UPF_TO_USE" == "5gdeploy-oai" ]]; then\n    BPF_ARGS=(--oai-upf-bpf=false)\n    [[ "${OAI_UPF_DATAPATH:-}" != xdp-skb ]] || BPF_ARGS=(--oai-upf-bpf=true)\nfi\n"$SCRIPTS_ROOT/lib/generate-core-scenario.sh" "$CORE_STAGE" orantestbed \\');s=s.replace('    --cp=$CORE --up=$UPF --ran=none \\', '    --cp=$CORE --up=$UPF --ran=none "${BPF_ARGS[@]}" \\');p.write_text(s)
> PY`
> - Ran `git -C /tmp/oai-lab-charts-7925f93 archive 7925f939ea36a3c4c1df5525f3718ce8470f6b3f | tar -x -C deploy/k8s/vendor; ls deploy/k8s/vendor/oai-5g-core/oai-upf/templates; cat deploy/k8s/vendor/oai-5g-core/oai-upf/templates/deployment.yaml; cat deploy/k8s/vendor/oai-5g-core/oai-upf/templates/configmap.yaml | head -45; cat deploy/k8s/vendor/oai-5g-core/oai-upf/templates/_helpers.tpl | head -65; cat deploy/k8s/vendor/oai-5g-core/oai-upf/values.yaml | head -90`
>
> </details>
>
> Mình đã sửa đường cấu hình XDP từ YAML xuống loader, thêm chế độ SKB không fallback và bảo vệ teardown để không gỡ nhầm chương trình của instance khác. Chart OAI đã được tải đúng commit; mình sẽ giữ bản gốc và tạo lớp override riêng cho mạng bridge của minikube, image research và việc thu artifact.
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `rg -n 'get_xdp_mode' src/oai-upf/src/upf_app/app/upf_config_yaml.hpp; ls deploy/k8s/vendor/oai-5g-ran/oai-{gnb,nr-ue,flexric}/templates; head -35 compose/core/cp-cfg/config.yaml; cat compose/core/up-cfg/upf1.yaml; head -30 compose/core/cp-sql/oai_db.sql; head -35 configs/ue/ue1.conf | sed -E 's/(key|opc|imsi)[[:space:]]*=.*/\1 = REDACTED;/I'; ls src/oai-ran/docker; sed -n '45,65p' src/oai-upf/docker/Dockerfile.upf.ubuntu; du -sh deploy/k8s/vendor`
> - Ran `cat compose/core/cp-cfg/config.yaml; cat deploy/k8s/vendor/oai-5g-core/oai-nrf/templates/service.yaml; cat deploy/k8s/vendor/oai-5g-ran/oai-flexric/config.yaml 2>/dev/null | head -30; cat src/oai-ran/docker/Dockerfile.build.ubuntu | head -65; cat src/oai-ran/docker/Dockerfile.base.ubuntu | head -45; rg -n '^CREATE TABLE|^ALTER TABLE|^INSERT|^REPLACE' compose/core/cp-sql/oai_db.sql | head -35; rg -n 'INSERT|REPLACE' compose/core/cp-sql/*.sql | cut -c1-120 | head -20`
> - Ran `rg -n 'sqn_json|dnn_json_tpl' compose/core/cp-sql/oai_db.sql | head -4; sed -n '143,161p' compose/core/cp-sql/oai_db.sql; sed -n '297,316p' compose/core/cp-sql/oai_db.sql; tail -10 /tmp/oai-lab-upf-build.log; git ls-remote https://github.com/k8snetworkplumbingwg/multus-cni.git refs/tags/v4.2.2`
> - Ran ``cat > /tmp/create_oai_lab.py <<'PY'
> from pathlib import Path
> import yaml,json,re,shutil
> root=Path('deploy/k8s'); chart=root/'chart'; (chart/'templates').mkdir(parents=True,exist_ok=True);(chart/'files').mkdir(exist_ok=True);(root/'values').mkdir(exist_ok=True);(root/'images').mkdir(exist_ok=True)
> nfs=['nrf','udr','udm','ausf','amf','smf','upf','flexric','gnb','nr-ue']
> # Keep original charts with a small, explicit extension hook for the lab profile.
> deps=[]
> for nf in nfs:
>  family='oai-5g-ran' if nf in ['flexric','gnb','nr-ue'] else 'oai-5g-core'
>  p=root/'vendor'/family/('oai-'+nf)
>  for fn in ['deployment.yaml','configmap.yaml','nad.yaml']:
>   f=p/'templates'/fn
>   if not f.exists():continue
>   s=f.read_text()
>   if 'lab.rendered' in s:continue
>   if fn=='deployment.yaml': s='{{/* lab.rendered: explicit integration hook; original OAI template below */}}\n{{- if .Values.global.lab }}\n{{ include "lab.nf" . }}\n{{- else }}\n'+s+'\n{{- end }}\n'
>   else:s='{{/* lab.rendered */}}\n{{- if not .Values.global.lab }}\n'+s+'\n{{- end }}\n'
>   f.write_text(s)
>  meta=yaml.safe_load((p/'Chart.yaml').read_text())
>  deps.append({'name':'oai-'+nf,'version':meta['version'],'repository':'file://../vendor/'+family+'/oai-'+nf,'condition':'oai-'+nf+'.enabled'})
> (chart/'Chart.yaml').write_text(yaml.safe_dump({'apiVersion':'v2','name':'oai-lab','version':'0.1.0','type':'application','dependencies':deps},sort_keys=False))
> # values: one source of truth shared with dependencies through global.lab.
> lab={'profile':'oai-lab','namespace':'oai-lab','cpus':8,'memoryMiB':16384,'kubernetesVersion':'v1.33.13','minDiskGiB':25,'secretName':'oai-lab-credentials','plmn':{'mcc':'001','mnc':'01'},'tac':7,'slice':{'sst':1,'sd':'FFFFFF','dnn':'nist-dnn'},'ueSubnet':'10.1.0.0/16','xdpMode':'skb','usageReporting':True,'toolsImage':'oai-lab-tools:unbuilt','dbImage':'mariadb:10.6','artifactSize':'2Gi','dbSize':'2Gi','radio':{'band':78,'prbs':106,'numerology':1,'frequency':3619200000},'experiment':{'rate':'10M','duration':120,'periodMs':1000,'timeout':180},'networks':{},'workloads':{}}
> networks={'n2':('22',{'amf':'10','gnb':'20'}),'n3':('23',{'upf':'10','gnb':'20'}),'n4':('24',{'smf':'10','upf':'20'}),'n6':('26',{'dn':'10','upf':'20'}),'e2':('27',{'flexric':'10','gnb':'20','xapp':'30'})}
> for n,(octet,hosts) in networks.items():lab['networks'][n]={'subnet':f'172.30.{octet}.0/24','bridge':'oai-'+n,'addresses':{h:f'172.30.{octet}.{ip}' for h,ip in hosts.items()}}
> for nf in nfs:
>  custom=nf in ['upf','gnb','nr-ue','flexric']
>  lab['workloads'][nf]={'image':f'oai-lab-{nf}:unbuilt' if custom else f'oaisoftwarealliance/oai-{nf}:v2.2.0','requests':{'cpu':'2' if nf in ['gnb','nr-ue'] else '100m','memory':'2Gi' if nf in ['gnb','nr-ue'] else '256Mi'},'limits':{'cpu':'4' if nf in ['gnb','nr-ue'] else '2','memory':'4Gi' if nf in ['gnb','nr-ue'] else '1Gi'}}
> vals={'global':{'lab':lab,'clusterIpServiceIpAllocation':True,'waitForNRF':False},'seedEnabled':False,'xappEnabled':False}
> for nf in nfs:vals['oai-'+nf]={'enabled':False,'imagePullSecrets':[],'multus':{'enabled':False},'exposedPorts':{'sbi':80}}
> (chart/'values.yaml').write_text(yaml.safe_dump(vals,sort_keys=False));(root/'values/minikube.yaml').write_text(yaml.safe_dump(vals,sort_keys=False))
> # OAI NF configuration baseline: no subscriber secrets. Rebind to Kubernetes endpoints.
> c=yaml.safe_load(Path('compose/core/cp-cfg/config.yaml').read_text());u=yaml.safe_load(Path('compose/core/up-cfg/upf1.yaml').read_text())
> tokens={}
> def token(expr):
>  key='LABTOKEN'+str(len(tokens));tokens[key]=expr;return key
> T=lambda p:token('{{ '+p+' }}')
> mcc=T('.Values.global.lab.plmn.mcc | quote');mnc=T('.Values.global.lab.plmn.mnc | quote');sst=T('.Values.global.lab.slice.sst');sd=T('.Values.global.lab.slice.sd | quote');dnn=T('.Values.global.lab.slice.dnn | quote')
> slice_={'sst':sst,'sd':sd};c['snssais']=[slice_];c['dnns']=[{'dnn':dnn,'ipv4_subnet':T('.Values.global.lab.ueSubnet | quote'),'pdu_session_type':'IPV4'}]
> c['database'].update(host='oai-lab-db',user='oai',password='[REDACTED_SECRET]');c['database']['generate_random']=False
> c['http_version']=1
> for name,nf in c['nfs'].items():
>  nf['host']='oai-'+name;nf['sbi'].update(interface_name='eth0',port=80)
> c['nfs']['upf']=u['nfs']['upf'];c['nfs']['upf'].pop('n9',None);c['nfs']['upf']['host']='oai-upf';c['nfs']['upf']['sbi'].update(interface_name='eth0',port=80)
> c['amf']['plmn_support_list']=[{'mcc':mcc,'mnc':mnc,'tac':T('.Values.global.lab.tac'),'nssai':[slice_]}]
> c['amf']['served_guami_list'][0].update(mcc=mcc,mnc=mnc);c['amf']['support_features_options']['enable_simple_scenario']=True
> c['smf']['upfs']=[{'host':T('.Values.global.lab.networks.n4.addresses.upf | quote'),'config':{'enable_usage_reporting':T('.Values.global.lab.usageReporting')}}]
> c['smf']['local_subscription_infos']=[{'dnn':dnn,'single_nssai':slice_,'qos_profile':{'5qi':9}}]
> c['smf']['smf_info']['sNssaiSmfInfoList']=[{'sNssai':slice_,'dnnSmfInfoList':[{'dnn':dnn}]}]
> c['upf']={'remote_n6_gw':T('.Values.global.lab.networks.n6.addresses.dn | quote'),'smfs':[{'host':T('.Values.global.lab.networks.n4.addresses.smf | quote')}],'support_features':{'enable_bpf_datapath':True,'enable_urr':T('.Values.global.lab.usageReporting'),'enable_snat':False,'xdp_mode':T('.Values.global.lab.xdpMode | quote')},'upf_info':{'sNssaiUpfInfoList':[{'sNssai':slice_,'dnnUpfInfoList':[{'dnn':dnn}]}]}}
> s=yaml.safe_dump(c,sort_keys=False)
> for key,expr in tokens.items():s=s.replace(key,expr)
> (chart/'files/config.yaml.tpl').write_text(s)
> # gNB base is OAI config already patched locally; all site-specific fields templated.
> s=Path('configs/gnb/gnb.conf').read_text()
> replacements={'amf_ip_address':'({ ipv4 = "{{ .Values.global.lab.networks.n2.addresses.amf }}"; })','GNB_IPV4_ADDRESS_FOR_NG_AMF':'"{{ .Values.global.lab.networks.n2.addresses.gnb }}/24"','GNB_IPV4_ADDRESS_FOR_NGU':'"{{ .Values.global.lab.networks.n3.addresses.gnb }}/24"','tracking_area_code':'{{ .Values.global.lab.tac }}','near_ric_ip_addr':'"{{ .Values.global.lab.networks.e2.addresses.flexric }}"','sm_dir':'"/opt/oai/sm/"','plmn_list':'({ mcc = {{ .Values.global.lab.plmn.mcc }}; mnc = {{ .Values.global.lab.plmn.mnc }}; mnc_length = {{ len .Values.global.lab.plmn.mnc }}; snssaiList = ({ sst = {{ .Values.global.lab.slice.sst }};{{ if ne .Values.global.lab.slice.sd "FFFFFF" }} sd = 0x{{ .Values.global.lab.slice.sd }};{{ end }} }); })'}
> for key,val in replacements.items():s=re.sub(r'(?m)^(\s*)'+key+r'\s*=.*;',lambda m:m[1]+key+' = '+val+';',s)
> s='\n'.join(l for l in s.splitlines() if not ('#sm_dir' in l or '/home/' in l))+'\n';(chart/'files/gnb.conf.tpl').write_text(s)
> (chart/'files/ue.conf.tpl').write_text('''// SPDX-License-Identifier: LicenseRef-CSSL-1.0
> uicc0 = {
>  imsi = "__IMSI__";
>  key = "__KEY__";
>  opc = "__OPC__";
>  pdu_sessions = ({ dnn = "{{ .Values.global.lab.slice.dnn }}"; nssai_sst = {{ .Values.global.lab.slice.sst }}; nssai_sd = 0x{{ .Values.global.lab.slice.sd }}; });
> };
> @include "channelmod_rfsimu.conf"
> ''')
> shutil.copyfile('configs/gnb/channelmod_rfsimu.conf',chart/'files/channelmod_rfsimu.conf')
> # Extract schema only; never vendor IMSI/keys or sample INSERT rows.
> sql=Path('compose/core/cp-sql/oai_db.sql').read_text()
> ddl=re.findall(r'(?:CREATE TABLE|ALTER TABLE)\s+`[^`]+`.*?;',sql,re.S)
> (chart/'files/schema.sql').write_text('-- OAI FED v2.2.0 schema, DDL only; local composite subscription key.\n'+'\n'.join(ddl)+'\n')
> (root/'vendor/PROVENANCE.json').write_text(json.dumps({'oai_charts':{'url':'https://gitlab.eurecom.fr/oai/orchestration/charts.git','commit':'7925f939ea36a3c4c1df5525f3718ce8470f6b3f'},'configuration':'OAI v2.2.0 config/schema snapshot adapted to one slice; no runtime dependency on 5gdeploy'},indent=2)+'\n')
> PY
> python3 /tmp/create_oai_lab.py``
> - Ran `cat > deploy/k8s/chart/templates/_nf.tpl <<'EOF'
> {{- define "lab.nf" -}}
> {{- $lab := .Values.global.lab -}}
> {{- $nf := trimPrefix "oai-" .Chart.Name -}}
> {{- $w := index $lab.workloads $nf -}}
> apiVersion: apps/v1
> kind: Deployment
> metadata:
>   name: {{ .Chart.Name }}
>   labels: {oai-lab/component: {{ $nf | quote }}}
> spec:
>   replicas: 1
>   strategy: {type: Recreate}
>   selector:
>     matchLabels:
>       {{- include (printf "%s.selectorLabels" .Chart.Name) . | nindent 6 }}
>   template:
>     metadata:
>       labels:
>         oai-lab/component: {{ $nf | quote }}
>         {{- include (printf "%s.selectorLabels" .Chart.Name) . | nindent 8 }}
>       annotations:
>         oai-lab/config-checksum: {{ toJson $lab | sha256sum | quote }}
>         k8s.v1.cni.cncf.io/networks: {{ include "lab.attachments" (dict "lab" $lab "nf" $nf) | quote }}
>     spec:
>       automountServiceAccountToken: false
>       terminationGracePeriodSeconds: 30
>       initContainers:
>         - name: prepare
>           image: {{ $lab.toolsImage | quote }}
>           command: [python3, /opt/lab/runtime.py, prepare, {{ $nf | quote }}]
>           env:
>             - name: POD_IP
>               valueFrom: {fieldRef: {fieldPath: status.podIP}}
>             {{- if eq $nf "nr-ue" }}
>             {{- range $key := list "IMSI" "KEY" "OPC" }}
>             - name: {{ $key }}
>               valueFrom: {secretKeyRef: {name: {{ $lab.secretName }}, key: {{ $key }}}}
>             {{- end }}
>             {{- else if not (has $nf (list "gnb" "flexric")) }}
>             - name: DB_PASSWORD
>               valueFrom: {secretKeyRef: {name: {{ $lab.secretName }}, key: DB_PASSWORD}}
>             {{- end }}
>           securityContext:
>             capabilities: {add: [NET_ADMIN], drop: [ALL]}
>           volumeMounts:
>             - {name: config, mountPath: /input, readOnly: true}
>             - {name: runtime, mountPath: /config}
>       containers:
>         - name: {{ $nf }}
>           image: {{ $w.image | quote }}
>           imagePullPolicy: IfNotPresent
>           {{- if has $nf (list "gnb" "nr-ue" "flexric") }}
>           command: [/opt/lab/radio-entrypoint.sh, {{ $nf | quote }}]
>           {{- else }}
>           command: [{{ printf "/openair-%s/bin/oai_%s" $nf $nf | quote }}, -c, /config/config.yaml, -o]
>           {{- end }}
>           securityContext:
>             privileged: {{ eq $nf "upf" }}
>             capabilities:
>               drop: [ALL]
>               add: [NET_ADMIN, NET_RAW{{ if has $nf (list "gnb" "nr-ue") }}, SYS_NICE, IPC_LOCK{{ end }}]
>           resources:
>             requests: {{ toJson $w.requests }}
>             limits: {{ toJson $w.limits }}
>           startupProbe:
>             exec: {command: [sh, -c, {{ if has $nf (list "gnb" "nr-ue" "flexric") }}"kill -0 1"{{ else }}"grep -qi ':0050 ' /proc/net/tcp /proc/net/tcp6"{{ end }}]}
>             failureThreshold: 90
>             periodSeconds: 2
>           readinessProbe:
>             exec: {command: [sh, -c, {{ if has $nf (list "gnb" "nr-ue" "flexric") }}"kill -0 1"{{ else }}"grep -qi ':0050 ' /proc/net/tcp /proc/net/tcp6"{{ end }}]}
>             periodSeconds: 5
>           volumeMounts:
>             - {name: runtime, mountPath: /config, readOnly: true}
>             {{- if eq $nf "nr-ue" }}
>             - {name: tun, mountPath: /dev/net/tun}
>             {{- end }}
>         {{- if eq $nf "smf" }}
>         - name: capture
>           image: {{ $lab.toolsImage | quote }}
>           command: [python3, /opt/lab/runtime.py, capture]
>           securityContext: {capabilities: {add: [NET_RAW, NET_ADMIN], drop: [ALL]}}
>           resources: {requests: {cpu: 25m, memory: 64Mi}, limits: {cpu: 250m, memory: 256Mi}}
>           volumeMounts:
>             - {name: artifacts, mountPath: /artifacts}
>         {{- end }}
>       volumes:
>         - name: config
>           configMap: {name: oai-lab-config}
>         - name: runtime
>           emptyDir: {medium: Memory}
>         {{- if eq $nf "nr-ue" }}
>         - name: tun
>           hostPath: {path: /dev/net/tun, type: CharDevice}
>         {{- end }}
>         {{- if eq $nf "smf" }}
>         - name: artifacts
>           persistentVolumeClaim: {claimName: oai-lab-artifacts}
>         {{- end }}
> {{- end -}}
>
> {{- define "lab.attachments" -}}
> {{- $nets := list -}}
> {{- range $name, $net := .lab.networks -}}
> {{- if hasKey $net.addresses $.nf -}}
> {{- $nets = append $nets (dict "name" (printf "oai-%s-%s" $.nf $name) "interface" $name) -}}
> {{- end -}}
> {{- end -}}
> {{- toJson $nets -}}
> {{- end -}}
> EOF
> cat > deploy/k8s/chart/templates/config.yaml <<'EOF'
> apiVersion: v1
> kind: ConfigMap
> metadata:
>   name: oai-lab-config
> data:
>   lab.json: {{ toJson .Values.global.lab | quote }}
>   config.yaml: |
>     {{- tpl (.Files.Get "files/config.yaml.tpl") . | nindent 4 }}
>   gnb.conf: |
>     {{- tpl (.Files.Get "files/gnb.conf.tpl") . | nindent 4 }}
>   ue.conf: |
>     {{- tpl (.Files.Get "files/ue.conf.tpl") . | nindent 4 }}
>   channelmod_rfsimu.conf: |
>     {{- .Files.Get "files/channelmod_rfsimu.conf" | nindent 4 }}
>   schema.sql: |
>     {{- .Files.Get "files/schema.sql" | nindent 4 }}
> ---
> apiVersion: v1
> kind: Service
> metadata: {name: oai-gnb-rfsim}
> spec:
>   selector: {oai-lab/component: gnb}
>   ports: [{name: rfsim, port: 4043, targetPort: 4043, protocol: TCP}]
> EOF
> cat > deploy/k8s/chart/templates/networks.yaml <<'EOF'
> {{- range $name, $net := .Values.global.lab.networks }}
> {{- range $nf, $ip := $net.addresses }}
> ---
> apiVersion: k8s.cni.cncf.io/v1
> kind: NetworkAttachmentDefinition
> metadata:
>   name: oai-{{ $nf }}-{{ $name }}
> spec:
>   config: {{ toJson (dict "cniVersion" "0.3.1" "type" "bridge" "bridge" $net.bridge "isGateway" false "ipMasq" false "hairpinMode" true "ipam" (dict "type" "static" "addresses" (list (dict "address" (printf "%s/%s" $ip (last (splitList "/" $net.subnet))))))) | quote }}
> {{- end }}
> {{- end }}
> EOF
> cat > deploy/k8s/chart/templates/storage.yaml <<'EOF'
> {{- range $item := list (dict "name" "db" "size" .Values.global.lab.dbSize) (dict "name" "artifacts" "size" .Values.global.lab.artifactSize) }}
> ---
> apiVersion: v1
> kind: PersistentVolumeClaim
> metadata:
>   name: oai-lab-{{ $item.name }}
>   annotations: {helm.sh/resource-policy: keep}
> spec:
>   accessModes: [ReadWriteOnce]
>   resources:
>     requests: {storage: {{ $item.size }}}
> {{- end }}
> EOF
> cat > deploy/k8s/chart/templates/db.yaml <<'EOF'
> apiVersion: v1
> kind: Service
> metadata: {name: oai-lab-db}
> spec:
>   selector: {oai-lab/component: db}
>   ports: [{port: 3306}]
> ---
> apiVersion: apps/v1
> kind: StatefulSet
> metadata: {name: oai-lab-db}
> spec:
>   serviceName: oai-lab-db
>   replicas: 1
>   selector:
>     matchLabels: {oai-lab/component: db}
>   template:
>     metadata:
>       labels: {oai-lab/component: db}
>     spec:
>       automountServiceAccountToken: false
>       containers:
>         - name: db
>           image: {{ .Values.global.lab.dbImage | quote }}
>           env:
>             - {name: MARIADB_DATABASE, value: oai_db}
>             - {name: MARIADB_USER, value: oai}
>             - name: MARIADB_PASSWORD
>               valueFrom: {secretKeyRef: {name: {{ .Values.global.lab.secretName }}, key: DB_PASSWORD}}
>             - name: MARIADB_ROOT_PASSWORD
>               valueFrom: {secretKeyRef: {name: {{ .Values.global.lab.secretName }}, key: DB_ROOT_PASSWORD}}
>           resources: {requests: {cpu: 250m, memory: 256Mi}, limits: {cpu: 1, memory: 1Gi}}
>           startupProbe:
>             exec: {command: [healthcheck.sh, --connect, --innodb_initialized]}
>             failureThreshold: 60
>             periodSeconds: 3
>           readinessProbe:
>             exec: {command: [healthcheck.sh, --connect, --innodb_initialized]}
>           volumeMounts: [{name: data, mountPath: /var/lib/mysql}]
>       volumes:
>         - name: data
>           persistentVolumeClaim: {claimName: oai-lab-db}
> {{- if .Values.seedEnabled }}
> ---
> apiVersion: batch/v1
> kind: Job
> metadata: {name: oai-lab-subscriber}
> spec:
>   backoffLimit: 1
>   activeDeadlineSeconds: 180
>   template:
>     spec:
>       automountServiceAccountToken: false
>       restartPolicy: Never
>       containers:
>         - name: seed
>           image: {{ .Values.global.lab.toolsImage | quote }}
>           command: [python3, /opt/lab/runtime.py, seed]
>           envFrom:
>             - secretRef: {name: {{ .Values.global.lab.secretName }}}
>           volumeMounts: [{name: config, mountPath: /input, readOnly: true}]
>       volumes:
>         - name: config
>           configMap: {name: oai-lab-config}
> {{- end }}
> EOF
> cat > deploy/k8s/chart/templates/dn.yaml <<'EOF'
> apiVersion: apps/v1
> kind: Deployment
> metadata: {name: oai-lab-dn}
> spec:
>   replicas: 1
>   strategy: {type: Recreate}
>   selector:
>     matchLabels: {oai-lab/component: dn}
>   template:
>     metadata:
>       labels: {oai-lab/component: dn}
>       annotations:
>         k8s.v1.cni.cncf.io/networks: {{ include "lab.attachments" (dict "lab" .Values.global.lab "nf" "dn") | quote }}
>     spec:
>       automountServiceAccountToken: false
>       containers:
>         - name: dn
>           image: {{ .Values.global.lab.toolsImage | quote }}
>           command: [sh, -ec]
>           args:
>             - ip route replace {{ .Values.global.lab.ueSubnet }} via {{ .Values.global.lab.networks.n6.addresses.upf }} dev n6; exec sleep infinity
>           securityContext: {capabilities: {add: [NET_ADMIN, NET_RAW], drop: [ALL]}}
>           volumeMounts: [{name: artifacts, mountPath: /artifacts}]
>       volumes:
>         - name: artifacts
>           persistentVolumeClaim: {claimName: oai-lab-artifacts}
> EOF
> cat > deploy/k8s/chart/templates/xapp.yaml <<'EOF'
> {{- if .Values.xappEnabled }}
> apiVersion: apps/v1
> kind: Deployment
> metadata: {name: oai-lab-xapp}
> spec:
>   replicas: 1
>   strategy: {type: Recreate}
>   selector:
>     matchLabels: {oai-lab/component: xapp}
>   template:
>     metadata:
>       labels: {oai-lab/component: xapp}
>       annotations:
>         k8s.v1.cni.cncf.io/networks: {{ include "lab.attachments" (dict "lab" .Values.global.lab "nf" "xapp") | quote }}
>     spec:
>       automountServiceAccountToken: false
>       containers:
>         - name: xapp
>           image: {{ .Values.global.lab.workloads.flexric.image | quote }}
>           command: [/opt/lab/radio-entrypoint.sh, xapp]
>           env:
>             - {name: RIC_IP, value: {{ .Values.global.lab.networks.e2.addresses.flexric | quote }}}
>             - {name: SST, value: {{ .Values.global.lab.slice.sst | quote }}}
>             - {name: SD, value: {{ printf "0x%s" .Values.global.lab.slice.sd | quote }}}
>             - {name: KPM_PERIOD, value: {{ .Values.global.lab.experiment.periodMs | quote }}}
>           volumeMounts: [{name: artifacts, mountPath: /artifacts}]
>       volumes:
>         - name: artifacts
>           persistentVolumeClaim: {claimName: oai-lab-artifacts}
> {{- end }}
> EOF
> helm dependency update deploy/k8s/chart`
> - Ran `cat > deploy/k8s/images/runtime.py <<'PY'
> #!/usr/bin/env python3
> """In-pod configuration, subscriber bootstrap and PFCP capture. Never print secrets."""
> import json, os, pathlib, re, shutil, signal, subprocess, sys, time
> import yaml
>
> def lab():
>     return json.loads(pathlib.Path('/input/lab.json').read_text())
>
> def prepare(nf):
>     cfg = lab()
>     out = pathlib.Path('/config'); out.mkdir(exist_ok=True)
>     for p in pathlib.Path('/input').iterdir():
>         if p.is_file(): shutil.copyfile(p, out/p.name)
>     if nf == 'nr-ue':
>         s = (out/'ue.conf').read_text()
>         for key, pattern in [('IMSI',r'\d{15}'),('KEY',r'[0-9a-fA-F]{32}'),('OPC',r'[0-9a-fA-F]{32}')]:
>             value=os.environ[key]
>             if not re.fullmatch(pattern,value): raise ValueError('Invalid SIM field: '+key)
>             s=s.replace('__'+key+'__',value)
>         (out/'ue.conf').write_text(s)
>     elif nf == 'flexric':
>         (out/'flexric.conf').write_text('[NEAR-RIC]\nNEAR_RIC_IP = '+cfg['networks']['e2']['addresses']['flexric']+'\n[XAPP]\nDB_NAME = unused\nDB_DIR = /tmp/\n')
>     elif nf != 'gnb':
>         c=yaml.safe_load((out/'config.yaml').read_text())
>         c['database']['password']=os.environ['DB_PASSWORD']
>         c['nfs'][nf]['host']=os.environ['POD_IP']
>         (out/'config.yaml').write_text(yaml.safe_dump(c,sort_keys=False))
>     if nf == 'upf':
>         subprocess.run(['sysctl','-w','net.ipv4.ip_forward=1'],check=True)
>         subprocess.run(['ip','rule','add','from',cfg['ueSubnet'],'table','5000'],check=True)
>         subprocess.run(['ip','route','replace','default','via',cfg['networks']['n6']['addresses']['dn'],'dev','n6','table','5000'],check=True)
>     for p in out.iterdir():
>         if p.is_file():p.chmod(0o600)
>
> def seed():
>     import pymysql
>     cfg=lab()
>     conn=None
>     for _ in range(60):
>         try:
>             conn=pymysql.connect(host='oai-lab-db',user='root',password=[REDACTED_SECRET]'DB_ROOT_PASSWORD'],database='oai_db',autocommit=False)
>             break
>         except pymysql.OperationalError:time.sleep(2)
>     if conn is None:raise RuntimeError('Database did not become ready')
>     cur=conn.cursor()
>     cur.execute('SELECT GET_LOCK(%s,30)',('oai-lab-seed',))
>     if cur.fetchone()[0]!=1:raise RuntimeError('Cannot acquire subscriber lock')
>     try:
>         cur.execute('SHOW TABLES'); tables={r[0] for r in cur.fetchall()}
>         if not tables:
>             for statement in pathlib.Path('/input/schema.sql').read_text().split(';'):
>                 if statement.strip():cur.execute(statement)
>         elif not {'AuthenticationSubscription','SessionManagementSubscriptionData','AccessAndMobilitySubscriptionData'} <= tables:
>             raise RuntimeError('Incomplete database schema; manual recovery required')
>         imsi=os.environ['IMSI']; key=os.environ['KEY']; opc=os.environ['OPC']
>         if not re.fullmatch(r'\d{15}',imsi) or not all(re.fullmatch(r'[0-9a-fA-F]{32}',x) for x in (key,opc)):
>             raise ValueError('Invalid subscriber secret')
>         sqn=json.dumps({'sqn':'000000000020','sqnScheme':'NON_TIME_BASED','lastIndexes':{'ausf':0}})
>         cur.execute('''INSERT INTO AuthenticationSubscription
>           (ueid,authenticationMethod,encPermanentKey,protectionParameterId,sequenceNumber,authenticationManagementField,algorithmId,encOpcKey,supi)
>           VALUES (%s,'5G_AKA',%s,%s,%s,'8000','milenage',%s,%s)
>           ON DUPLICATE KEY UPDATE encPermanentKey=VALUES(encPermanentKey),encOpcKey=VALUES(encOpcKey),protectionParameterId=VALUES(protectionParameterId)''',(imsi,key,key,sqn,opc,imsi))
>         snssai={'sst':cfg['slice']['sst'],'sd':cfg['slice']['sd']}
>         dnn={cfg['slice']['dnn']:{'pduSessionTypes':{'defaultSessionType':'IPV4','allowedSessionTypes':['IPV4']},'sscModes':{'defaultSscMode':'SSC_MODE_1','allowedSscModes':['SSC_MODE_1']},'5gQosProfile':{'5qi':9,'priorityLevel':90,'arp':{'priorityLevel':8,'preemptCap':'NOT_PREEMPT','preemptVuln':'PREEMPTABLE'}},'sessionAmbr':{'downlink':'1000 Mbps','uplink':'1000 Mbps'}}}
>         plmn=cfg['plmn']['mcc']+cfg['plmn']['mnc']
>         cur.execute('''INSERT INTO SessionManagementSubscriptionData (ueid,servingPlmnid,singleNssai,dnnConfigurations) VALUES (%s,%s,%s,%s)
>           ON DUPLICATE KEY UPDATE dnnConfigurations=VALUES(dnnConfigurations)''',(imsi,plmn,json.dumps(snssai),json.dumps(dnn)))
>         cur.execute('''INSERT INTO AccessAndMobilitySubscriptionData (ueid,servingPlmnid,nssai) VALUES (%s,%s,%s)
>           ON DUPLICATE KEY UPDATE nssai=VALUES(nssai)''',(imsi,plmn,json.dumps({'defaultSingleNssais':[snssai]})))
>         conn.commit();print('Subscriber synchronized; authentication sequence preserved')
>     finally:
>         cur.execute('SELECT RELEASE_LOCK(%s)',('oai-lab-seed',));conn.close()
>
> def capture():
>     root=pathlib.Path('/artifacts'); root.mkdir(exist_ok=True)
>     request=root/'capture-request.json'; proc=None; active=None
>     def stop(*_):
>         nonlocal proc
>         if proc is not None:
>             if proc.poll() is None:proc.send_signal(signal.SIGINT)
>             proc.wait(timeout=15);proc=None
>     signal.signal(signal.SIGTERM,lambda *_:(stop(),sys.exit(0)))
>     while True:
>         if request.exists():
>             wanted=json.loads(request.read_text())['run_id']
>             if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',wanted):raise ValueError('Invalid run ID')
>             if wanted!=active:
>                 stop();active=wanted
>                 d=root/'runs'/wanted;d.mkdir(parents=True,exist_ok=True)
>                 proc=subprocess.Popen(['tcpdump','-U','-n','-i','n4','udp port 8805','-w',str(d/'pfcp.pcap')])
>                 time.sleep(1)
>                 if proc.poll() is not None:raise RuntimeError('PFCP capture failed')
>                 (d/'capture.ready').touch()
>         if proc and (root/'runs'/active/'capture.stop').exists():
>             stop();(root/'runs'/active/'capture.done').touch()
>         if proc and proc.poll() is not None:raise RuntimeError('PFCP capture exited unexpectedly')
>         time.sleep(.5)
>
> if __name__=='__main__':
>     try:
>         {'prepare':lambda:prepare(sys.argv[2]),'seed':seed,'capture':capture}[sys.argv[1]]()
>     except Exception as e:
>         # No exception repr from database APIs: it could include credentials/SQL.
>         print('Runtime operation failed: '+type(e).__name__,file=sys.stderr);sys.exit(1)
> PY
> cat > deploy/k8s/images/Dockerfile.tools <<'EOF'
> FROM ubuntu:24.04
> ENV DEBIAN_FRONTEND=noninteractive
> RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-yaml python3-pymysql iproute2 iptables iperf tcpdump tshark procps curl ca-certificates tar && rm -rf /var/lib/apt/lists/*
> COPY deploy/k8s/images/runtime.py /opt/lab/runtime.py
> CMD ["sleep", "infinity"]
> EOF
> cat > deploy/k8s/images/Dockerfile.radio <<'EOF'
> # Source build, sequential. No dependency on legacy launchers or 5gdeploy.
> FROM ubuntu:24.04 AS builder
> ENV DEBIAN_FRONTEND=noninteractive
> RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc-13 g++-13 cmake ninja-build make git sudo python3 python3-dev python3-pip pkg-config autoconf automake libtool bison flex swig libsctp-dev libpcre2-dev libssl-dev libconfig-dev libfftw3-dev libgmp-dev libyaml-cpp-dev libboost-all-dev libblas-dev liblapack-dev liblapacke-dev libjson-c-dev libcurl4-openssl-dev libczmq-dev libzmq3-dev libelf-dev libdw-dev zlib1g-dev xxd wget ca-certificates
> COPY src/flexric /source/flexric
> RUN rm -rf /source/flexric/build && cmake -S /source/flexric -B /source/flexric/build -DE2AP_VERSION=E2AP_V3 -DKPM_VERSION=KPM_V3_00 -DXAPP_DB=NONE_XAPP -DCMAKE_INSTALL_PREFIX=/opt/oai && cmake --build /source/flexric/build -j2 && cmake --install /source/flexric/build
> COPY src/oai-ran /source/ran
> RUN rm -rf /source/ran/cmake_targets/ran_build && cd /source/ran/cmake_targets && ./build_oai -I -w SIMU && ./build_oai --ninja --nrUE -w SIMU && ./build_oai --ninja --gNB -w SIMU --build-e2 --cmake-opt -DE2AP_VERSION=E2AP_V3 --cmake-opt -DKPM_VERSION=KPM_V3_00
> RUN mkdir -p /opt/oai/bin /opt/oai/sm /opt/oai/ran && cp /source/ran/cmake_targets/ran_build/build/nr-softmodem /source/ran/cmake_targets/ran_build/build/nr-uesoftmodem /opt/oai/bin/ && cp -a /source/ran/cmake_targets/ran_build/build/*.so /opt/oai/ran/ && cp /source/flexric/build/examples/ric/nearRT-RIC /source/flexric/build/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv /opt/oai/bin/ && cp -a /opt/oai/lib/flexric/*.so /opt/oai/sm/
> # Retain matching runtime libraries from this build environment. Optimization later.
> FROM builder AS radio
> RUN apt-get install -y --no-install-recommends iproute2 iperf procps python3-yaml && rm -rf /var/lib/apt/lists/* /source
> COPY deploy/k8s/images/radio-entrypoint.sh /opt/lab/radio-entrypoint.sh
> ENV LD_LIBRARY_PATH=/opt/oai/ran:/opt/oai/lib:/opt/oai/lib/flexric
> WORKDIR /opt/oai/ran
> ENTRYPOINT ["/opt/lab/radio-entrypoint.sh"]
> EOF
> cat > deploy/k8s/images/radio-entrypoint.sh <<'EOF'
> #!/usr/bin/env bash
> set -Eeuo pipefail
> case "${1:?component required}" in
>   gnb) exec /opt/oai/bin/nr-softmodem -O /config/gnb.conf --rfsim --rfsimulator.[0].serveraddr server --rfsimulator.[0].options chanmod --gNBs.[0].min_rxtxtime 6 ;;
>   nr-ue)
>     server=$(getent ahostsv4 oai-gnb-rfsim | awk 'NR==1 {print $1}')
>     test -n "$server"
>     read -r prbs mu band freq < <(python3 -c 'import json; r=json.load(open("/config/lab.json"))["radio"]; print(r["prbs"],r["numerology"],r["band"],r["frequency"])')
>     cd /config
>     exec /opt/oai/bin/nr-uesoftmodem -O /config/ue.conf --rfsim --rfsimulator.serveraddr "$server" --rfsimulator.options chanmod -r "$prbs" --numerology "$mu" --band "$band" -C "$freq" ;;
>   flexric) exec /opt/oai/bin/nearRT-RIC -c /config/flexric.conf -p /opt/oai/sm/ ;;
>   xapp)
>     printf '[NEAR-RIC]\nNEAR_RIC_IP = %s\n[XAPP]\nDB_NAME = unused\nDB_DIR = /tmp/\n' "$RIC_IP" >/tmp/flexric.conf
>     run_id=$(cat /artifacts/current-run)
>     [[ "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]
>     export OUTPUT_CSV_PATH="/artifacts/runs/$run_id/KPI_Metrics.csv"
>     exec /opt/oai/bin/xapp_kpm_moni_write_to_csv -c /tmp/flexric.conf -p /opt/oai/sm/ "${KPM_PERIOD:-1000}" ;;
>   *) exit 2 ;;
> esac
> EOF
> chmod +x deploy/k8s/images/radio-entrypoint.sh
> helm dependency update deploy/k8s/chart --skip-refresh > /tmp/oai-lab-helm-deps.log 2>&1
> helm lint deploy/k8s/chart -f deploy/k8s/values/minikube.yaml`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `git status --short; ls scripts/k8s; tail -20 /tmp/oai-lab-upf-build.log`
> - Ran `docker build -f src/oai-upf/docker/Dockerfile.upf.ubuntu --target oai-upf --build-arg GIT_COMMIT=00b7485-xdp-mode --tag oai-upf-research:skb-dev src/oai-upf > /tmp/oai-lab-upf-build.log 2>&1`
>
> </details>
>
> Phần chart và cấu hình lab đã được tạo; image UPF đang build để kiểm tra thay đổi XDP-SKB bằng compiler thật. Mình đang hoàn thiện CLI triển khai và các kiểm tra chặn lỗi trước khi khởi động UE, sau đó sẽ thử trên profile `oai-lab` riêng.
>
> <details><summary>Explored 6 files, a search, a list, ran 7 commands, searched the web</summary>
>
> <details><summary>Explored 6 files, a search, a list</summary>
>
> - Read `./deploy/k8s/chart/templates/_nf.tpl`
> - Read `./deploy/k8s/chart/templates/db.yaml`
> - Read `./deploy/k8s/images/radio-entrypoint.sh`
> - Read `./deploy/k8s/values/minikube.yaml`
> - Listed files
> - Read `./deploy/k8s/images/runtime.py`
> - Read `./src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp`
> - Searched for `argc|argv|SLICE|SST|SD` in `xapp_kpm_moni_write_to_csv.c`
>
> </details>
>
> - Ran `helm template oai-lab deploy/k8s/chart -f deploy/k8s/values/minikube.yaml --set oai-nrf.enabled=true,oai-udr.enabled=true,oai-udm.enabled=true,oai-ausf.enabled=true,oai-amf.enabled=true,oai-smf.enabled=true,oai-upf.enabled=true,oai-flexric.enabled=true,oai-gnb.enabled=true,oai-nr-ue.enabled=true,xappEnabled=true,seedEnabled=true > /tmp/oai-render.yaml
> rg -n 'kind:|name: oai-' /tmp/oai-render.yaml | tail -20
> rg -n 'UPF|usage|n3|n4|n6|host:|port:' deploy/k8s/chart/files/config.yaml.tpl | head -80
> cat deploy/k8s/images/Dockerfile.radio
> rg --files configs | head -40`
>
> - Ran `git ls-remote https://github.com/k8snetworkplumbingwg/multus-cni.git refs/tags/v4.2.2`
>
> - Ran `cat deploy/k8s/chart/files/config.yaml.tpl; cat deploy/k8s/chart/templates/xapp.yaml; cat deploy/k8s/chart/templates/dn.yaml; rg -n 'parse|case|getopt' src/flexric/src/util/alg_ds/alg/string_parser.c src/flexric/src/util/conf_file.c src/flexric/src/util/*args*; ls tests`
>
> - Ran `python3 - <<'PY'
> p='deploy/k8s/chart/files/config.yaml.tpl'
> s=open(p).read().replace('{{ .Values.global.lab.plmn.mnc | quote }}0','{{ .Values.global.lab.networks.n4.addresses.smf | quote }}').replace('{{ .Values.global.lab.plmn.mnc | quote }}1','{{ .Values.global.lab.usageReporting }}').replace('{{ .Values.global.lab.plmn.mnc | quote }}2','{{ .Values.global.lab.xdpMode | quote }}')
> open(p,'w').write(s)
> p='deploy/k8s/images/radio-entrypoint.sh';s=open(p).read().replace(' -c /tmp/flexric.conf -p /opt/oai/sm/ "${KPM_PERIOD:-1000}"',' "$OUTPUT_CSV_PATH" "${KPM_PERIOD:-1000}" -c /tmp/flexric.conf -p /opt/oai/sm/');open(p,'w').write(s)
> PY
> rg --files src/flexric | rg 'conf.*\.(c|h)$' | head
> ls manifests; rg -n 'CSV|pfcp\.' scripts/run-experiment.sh | tail -40
> ls /tmp/oai-lab-upf-before`
>
> - Ran `curl -fL --max-time 45 https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/v4.2.2/deployments/multus-daemonset-thick.yml -o /tmp/multus.yml`
>
> - Ran `cat /tmp/multus.yml | tail -115; sed -n '478,540p' scripts/run-experiment.sh; rg -n 'phases.csv|phase,' scripts/run-experiment.sh; tail -12 /tmp/oai-lab-upf-build.log; rg -n 'bpftool|iproute' src/oai-upf/docker/Dockerfile.upf.ubuntu; cat src/flexric/src/util/conf_file.c | head -100`
>
> - Ran `rg -n 'error:|FAILED:|fatal|Killed' /tmp/oai-lab-upf-build.log | tail -20; df -h .; rg -n 'getopt|strcmp\(argv|argc' src/flexric/src/util/conf_file.c | tail -20; cat deploy/k8s/chart/templates/config.yaml | head -45; ls tests/k8s`
>
> Searched the web for `https://minikube.sigs.k8s.io/docs/commands/start/`
>
> </details>
>
> Kiểm tra build phát hiện lỗi namespace trong parser XDP mode; mình đã sửa và build lại. Đồng thời mình đã sửa cấu hình xApp theo đúng cách binary hiện tại nhận đường dẫn CSV và chu kỳ KPM. Các bước nghiệm thu sẽ kiểm tra dữ liệu thực, không coi trạng thái pod `Running` là đủ.
>
> <details><summary>Explored 5 files, a search, ran 8 commands</summary>
>
> - Ran `cat > scripts/k8s/lab.sh <<'EOF'
> #!/usr/bin/env bash
> set -Eeuo pipefail
> ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
> exec python3 "$ROOT/scripts/k8s/lab.py" "$@"
> EOF
> chmod +x scripts/k8s/lab.sh
> cat > scripts/k8s/lab.py <<'PY'
> #!/usr/bin/env python3
> """Isolated oai-lab orchestration. No legacy backend imports or commands."""
> import argparse, base64, csv, datetime, hashlib, ipaddress, json, os, pathlib, re
> import secrets, shutil, socket, subprocess, sys, tempfile, time
> import yaml
> ROOT=pathlib.Path(__file__).resolve().parents[2]
> DEPLOY=ROOT/'deploy/k8s'; STATE=ROOT/'artifacts/k8s'; PROFILE='oai-lab'
> NFS=['nrf','udr','udm','ausf','amf','smf','upf','flexric','gnb','nr-ue']
> K=['kubectl','--context',PROFILE,'--namespace',PROFILE,'--request-timeout=30s']
> H=['helm','--kube-context',PROFILE,'--namespace',PROFILE]
> class GateError(RuntimeError):pass
>
> def run(args, *, data=None, capture=True, timeout=600, check=True):
>     p=subprocess.run([str(a) for a in args],input=data,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None,timeout=timeout)
>     if check and p.returncode:raise GateError('Command failed: '+str(args[0])+' '+str(args[1:3])+'\n'+(p.stderr or '')[-2000:])
>     return p.stdout or ''
>
> def write_json(path,value):
>     path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n')
>
> def validate(v, routes=()):
>     c=v['global']['lab']
>     if c['profile']!=PROFILE or c['namespace']!=PROFILE:raise GateError('Only profile/namespace oai-lab is permitted')
>     if c['xdpMode']!='skb':raise GateError('Kubernetes lab requires xdpMode=skb')
>     if not c['usageReporting']:raise GateError('Usage reporting must be enabled')
>     if c['radio']!={'band':78,'prbs':106,'numerology':1,'frequency':3619200000}:raise GateError('This initial gNB radio template supports only the pinned RFsim profile')
>     nets=[ipaddress.ip_network(c['ueSubnet'])]
>     for name,n in c['networks'].items():
>         if name not in ['n2','n3','n4','n6','e2']:raise GateError('Unexpected interface '+name)
>         subnet=ipaddress.ip_network(n['subnet']);nets.append(subnet)
>         if len(set(n['addresses'].values()))!=len(n['addresses']):raise GateError('Duplicate secondary IP')
>         for address in n['addresses'].values():
>             if ipaddress.ip_address(address) not in subnet or address in [str(subnet.network_address),str(subnet.broadcast_address)]:raise GateError('Invalid secondary IP')
>     for i,n in enumerate(nets):
>         if any(n.overlaps(o) for o in nets[i+1:]):raise GateError('Overlapping lab subnets')
>         for route in routes:
>             if n.version==route.version and n.overlaps(route):raise GateError('Subnet conflict: '+str(n)+' with '+str(route))
>     for nf in ['nrf','udr','udm','ausf','amf','smf']:
>         if c['workloads'][nf]['image']!='oaisoftwarealliance/oai-'+nf+':v2.2.0':raise GateError('CP image must remain pinned at v2.2.0')
>     return c
>
> def host_check(v):
>     for exe in ['docker','minikube','kubectl','helm','ip','tshark','g++']:
>         if not shutil.which(exe):raise GateError('Missing command: '+exe)
>     c=validate(v)
>     if os.cpu_count()<c['cpus']:raise GateError('Insufficient CPUs')
>     mem={l.split(':')[0]:int(l.split()[1]) for l in pathlib.Path('/proc/meminfo').read_text().splitlines()}
>     # An already running lab owns its reservation; do not require another 16 GiB.
>     running=run(['docker','ps','--filter','name=^/oai-lab$','--format','{{.Names}}']).strip()==PROFILE
>     required=2048 if running else c['memoryMiB']+1024
>     if mem['MemAvailable']<required*1024:raise GateError('Insufficient available RAM; need '+str(required)+' MiB')
>     if shutil.disk_usage(ROOT).free<c['minDiskGiB']*1024**3:raise GateError('Insufficient disk space; no cache will be deleted automatically')
>     routes=[]
>     for r in json.loads(run(['ip','-j','route','show','table','all'])):
>         dest=r.get('dst','default')
>         if dest!='default':routes.append(ipaddress.ip_network(dest,strict=False))
>     ids=run(['docker','network','ls','-q']).split()
>     if ids:
>         for net in json.loads(run(['docker','network','inspect',*ids])):
>             for block in net.get('IPAM',{}).get('Config',[]):
>                 if block.get('Subnet'):routes.append(ipaddress.ip_network(block['Subnet']))
>     # Reserve minikube's pod/service ranges even before bootstrap.
>     validate(v,[*routes,ipaddress.ip_network('10.244.0.0/16'),ipaddress.ip_network('10.96.0.0/12')])
>     try:
>         with socket.socket(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_SCTP):pass
>     except OSError as e:raise GateError('SCTP unavailable: '+str(e))
>     config=pathlib.Path('/boot/config-'+os.uname().release)
>     if config.exists() and 'CONFIG_BPF_SYSCALL=y' not in config.read_text():raise GateError('Kernel lacks BPF syscall')
>     return {'ramAvailableKiB':mem['MemAvailable'],'diskFreeBytes':shutil.disk_usage(ROOT).free,'kernel':os.uname().release,'sctp':True,'bpf':'load/attach gate required inside UPF'}
>
> def fingerprint(paths):
>     h=hashlib.sha256()
>     skip={'.git','build','ran_build','__pycache__','CMakeFiles','log','logs'}
>     for base in paths:
>         for here,dirs,files in os.walk(base):
>             dirs[:]=sorted(d for d in dirs if d not in skip)
>             for name in sorted(files):
>                 p=pathlib.Path(here)/name
>                 if p.is_symlink() or name.endswith(('.o','.a','.pyc')):continue
>                 h.update(str(p.relative_to(ROOT)).encode());h.update(p.read_bytes())
>     return h.hexdigest()
>
> class Lab:
>     def __init__(self,args):
>         self.args=args; self.values=yaml.safe_load(args.values.read_text());self.c=validate(self.values)
>         self.runid=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-k8s'
>         self.out=ROOT/'artifacts/experiments'/self.runid
>         self.enabled=[];self.seed=False;self.xapp=False
>     def render(self):
>         flags=[f'oai-{n}.enabled=true' for n in NFS]+['seedEnabled=true','xappEnabled=true']
>         rendered=run(['helm','template',PROFILE,DEPLOY/'chart','-f',self.args.values,'--set',','.join(flags)])
>         docs=list(yaml.safe_load_all(rendered))
>         cm=next(d for d in docs if d and d['kind']=='ConfigMap' and d['metadata']['name']=='oai-lab-config')
>         cfg=yaml.safe_load(cm['data']['config.yaml'])
>         assert cfg['upf']['support_features']['xdp_mode']=='skb'
>         assert len(cfg['smf']['upfs'])==1 and len(cfg['snssais'])==1
>         STATE.mkdir(parents=True,exist_ok=True);(STATE/'rendered.yaml').write_text(rendered)
>         run(['helm','lint',DEPLOY/'chart','-f',self.args.values,'--set',','.join(flags)],capture=False)
>     def check(self):
>         self.render();write_json(STATE/'preflight.json',host_check(self.values));print('Preflight passed. Actual BPF attachment remains a runtime gate.')
>     def build(self):
>         self.check();lock={};tag=fingerprint([ROOT/'src/oai-upf',ROOT/'src/oai-ran',ROOT/'src/flexric',DEPLOY/'images'])[:16]
>         jobs=[('tools',DEPLOY/'images/Dockerfile.tools',ROOT,None),('upf',ROOT/'src/oai-upf/docker/Dockerfile.upf.ubuntu',ROOT/'src/oai-upf','oai-upf'),('radio',DEPLOY/'images/Dockerfile.radio',ROOT,None)]
>         for name,dockerfile,context,target in jobs:
>             image='oai-lab-'+name+':'+tag
>             cmd=['docker','build','-f',dockerfile,'-t',image]
>             if target:cmd+=['--target',target,'--build-arg','GIT_COMMIT='+tag]
>             print('Building '+image,flush=True)
>             with (STATE/(name+'-build.log')).open('w') as log:
>                 p=subprocess.run([str(x) for x in cmd+[context]],stdout=log,stderr=subprocess.STDOUT)
>             if p.returncode:raise GateError('Image build failed: '+name+'; see artifacts/k8s/'+name+'-build.log')
>             info=json.loads(run(['docker','image','inspect',image]))[0]
>             lock[name]={'image':image,'id':info['Id'],'repoDigests':info.get('RepoDigests',[])}
>             write_json(STATE/'images.partial.json',lock)
>         overlay={'global':{'lab':{'toolsImage':lock['tools']['image'],'workloads':{n:{'image':lock['upf' if n=='upf' else 'radio']['image']} for n in ['upf','gnb','nr-ue','flexric']}}}}
>         (STATE/'images.yaml').write_text(yaml.safe_dump(overlay));write_json(STATE/'images.json',{'sourceHash':tag,'images':lock})
>     def k(self,*args,**kw):return run(K+list(args),**kw)
>     def exec(self,nf,*args,**kw):
>         deployment='oai-'+nf if nf in NFS else 'oai-lab-'+nf
>         return self.k('exec','deployment/'+deployment,'-c',nf,'--',*args,**kw)
>     def helm(self):
>         flags=[f'oai-{n}.enabled={str(n in self.enabled).lower()}' for n in NFS]+['seedEnabled='+str(self.seed).lower(),'xappEnabled='+str(self.xapp).lower()]
>         run(H+['upgrade','--install',PROFILE,DEPLOY/'chart','-f',self.args.values,'-f',STATE/'images.yaml','--set',','.join(flags),'--timeout','5m'],capture=False)
>     def ready(self,nf):
>         obj='statefulset/oai-lab-db' if nf=='db' else 'deployment/'+('oai-'+nf if nf in NFS else 'oai-lab-'+nf)
>         self.k('rollout','status',obj,'--timeout=180s',capture=False,timeout=200)
>     def wait(self,description,fn,timeout=180):
>         start=time.monotonic();last=''
>         while time.monotonic()-start<timeout:
>             try:
>                 val=fn()
>                 if val:return val
>             except (GateError,ValueError,KeyError) as e:last=str(e)
>             time.sleep(3)
>         raise GateError(description+' timed out. '+last[-500:])
>     def credentials(self):
>         # Reuse credentials when PVCs survive down/up. Never log secret data.
>         got=self.k('get','secret',self.c['secretName'],'--ignore-not-found','-o','name')
>         if got:return
>         raw=(ROOT/'configs/ue/ue1.conf').read_text();fields={}
>         for k,p in [('IMSI','imsi'),('KEY','key'),('OPC','opc')]:
>             m=re.search(r'\b'+p+r'\s*=\s*"([a-fA-F0-9]+)"',raw,re.I)
>             if not m:raise GateError('Cannot read UE1 '+k+'; create lab Secret explicitly')
>             fields[k]=m.group(1)
>         fields.update(DB_PASSWORD=secrets.token_hex(24),DB_ROOT_PASSWORD=secrets.token_hex(24))
>         self.k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':self.c['secretName'],'namespace':PROFILE},'type':'Opaque','stringData':fields}))
>     def up(self):
>         self.check()
>         if not (STATE/'images.yaml').exists():raise GateError('Run build successfully before up')
>         lock=json.loads((STATE/'images.json').read_text())
>         for item in lock['images'].values():
>             if json.loads(run(['docker','image','inspect',item['image']]))[0]['Id']!=item['id']:raise GateError('Image ID changed; rebuild')
>         run(['minikube','start','--profile',PROFILE,'--keep-context','--driver=docker','--container-runtime=containerd','--kubernetes-version='+self.c['kubernetesVersion'],'--cni=bridge','--cpus='+str(self.c['cpus']),'--memory='+str(self.c['memoryMiB']),'--interactive=false'],capture=False,timeout=900)
>         self.k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'Namespace','metadata':{'name':PROFILE,'labels':{'pod-security.kubernetes.io/enforce':'privileged'}}}))
>         run(['kubectl','--context',PROFILE,'--namespace','kube-system','apply','-f',DEPLOY/'vendor/multus.yaml'],capture=False)
>         run(['kubectl','--context',PROFILE,'--namespace','kube-system','rollout','status','daemonset/kube-multus-ds','--timeout=180s'],capture=False)
>         run(['minikube','--profile',PROFILE,'ssh','--','test -x /opt/cni/bin/bridge && test -x /opt/cni/bin/static && test -e /dev/net/tun'],capture=False)
>         for item in lock['images'].values():run(['minikube','--profile',PROFILE,'image','load',item['image']],capture=False,timeout=600)
>         self.credentials();self.helm();self.ready('db');self.ready('dn')
>         self.k('delete','job','oai-lab-subscriber','--ignore-not-found');self.seed=True;self.helm()
>         self.k('wait','--for=condition=complete','job/oai-lab-subscriber','--timeout=180s',capture=False)
>         for nf in NFS[:7]:
>             self.enabled.append(nf);self.helm();self.ready(nf)
>         self.wait('PFCP association',lambda:re.search(r'(?i)(association.*(success|accepted|established)|associated with)',self.k('logs','deployment/oai-upf','-c','upf','--tail=500')))
>         for nf in ['flexric','gnb']:
>             self.enabled.append(nf);self.helm();self.ready(nf)
>         self.start_session()
>     def start_session(self):
>         self.exec('dn','mkdir','-p','/artifacts/runs/'+self.runid)
>         self.exec('dn','python3','-c','import pathlib,json; p=pathlib.Path("/artifacts"); (p/"current-run").write_text('+repr(self.runid)+'); (p/"request.tmp").write_text(json.dumps({"run_id":'+repr(self.runid)+'})); (p/"request.tmp").replace(p/"capture-request.json")')
>         self.wait('PFCP capture ready',lambda:self.exec('dn','test','-f','/artifacts/runs/'+self.runid+'/capture.ready')== '')
>         self.enabled=NFS[:9];self.xapp=False;self.helm()
>         self.enabled=NFS[:];self.xapp=True;self.helm();self.ready('nr-ue');self.ready('xapp')
>         self.wait('UE registration/PDU interface',self.ue_ip)
>         self.wait('E2 setup',lambda:re.search(r'(?i)E2.*setup.*(response|success)',self.k('logs','deployment/oai-gnb','-c','gnb','--tail=500')))
>         self.xdp_gate()
>         self.wait('KPM samples',lambda:int(self.exec('dn','sh','-c','test -f /artifacts/runs/'+self.runid+'/KPI_Metrics.csv && wc -l < /artifacts/runs/'+self.runid+'/KPI_Metrics.csv'))>1)
>         self.out.mkdir(parents=True,exist_ok=True);self.metadata();(STATE/'current-run').write_text(self.runid)
>     def ue_ip(self):
>         for interface in json.loads(self.exec('nr-ue','ip','-j','address')):
>             for addr in interface.get('addr_info',[]):
>                 if addr['family']=='inet' and ipaddress.ip_address(addr['local']) in ipaddress.ip_network(self.c['ueSubnet']):return addr['local']
>         return None
>     def xdp_gate(self):
>         info=json.loads(self.exec('upf','/openair-upf/bin/bpftool','-j','net'))
>         records=info if isinstance(info,list) else [info]
>         xdp=[e for r in records for e in r.get('xdp',[])]
>         for interface in ['n3','n6']:
>             if not any(e.get('devname')==interface and e.get('mode')=='generic' and e.get('id',0)>0 for e in xdp):raise GateError('XDP-SKB not attached to '+interface)
>         self.out.mkdir(parents=True,exist_ok=True);write_json(self.out/'xdp.json',info)
>     def metadata(self):
>         write_json(self.out/'metadata.json',{'backend':'kubernetes','context':PROFILE,'xdpMode':'skb','valuesHash':hashlib.sha256(self.args.values.read_bytes()).hexdigest(),'chartHash':fingerprint([DEPLOY/'chart',DEPLOY/'vendor']),'images':json.loads((STATE/'images.json').read_text()),'chartProvenance':json.loads((DEPLOY/'vendor/PROVENANCE.json').read_text())})
>         (self.out/'pod-images.json').write_text(self.k('get','pods','-o','json'))
>     def collect(self):
>         self.out.mkdir(parents=True,exist_ok=True)
>         (self.out/'events.txt').write_text(self.k('get','events','--sort-by=.lastTimestamp'))
>         # Redact SIM and database secrets from application log output.
>         vals=[]
>         try:vals=[base64.b64decode(v).decode() for v in json.loads(self.k('get','secret',self.c['secretName'],'-o','json')).get('data',{}).values()]
>         except GateError:pass
>         pods=json.loads(self.k('get','pods','-o','json'))['items']
>         for pod in pods:
>             for cont in pod['spec']['containers']:
>                 log=self.k('logs',pod['metadata']['name'],'-c',cont['name'],'--tail=5000',check=False)
>                 for value in vals:log=log.replace(value,'[REDACTED]')
>                 (self.out/(pod['metadata']['name']+'-'+cont['name']+'.log')).write_text(log)
>         try:
>             self.exec('dn','touch','/artifacts/runs/'+self.runid+'/capture.stop')
>             self.wait('capture flush',lambda:self.exec('dn','test','-f','/artifacts/runs/'+self.runid+'/capture.done')=='',30)
>             with (self.out/'pod-artifacts.tar').open('wb') as f:
>                 subprocess.run(K+['exec','deployment/oai-lab-dn','-c','dn','--','tar','-C','/artifacts/runs/'+self.runid,'-cf','-','.'],stdout=f,check=True)
>             import tarfile
>             with tarfile.open(self.out/'pod-artifacts.tar') as t:t.extractall(self.out,filter='data')
>         except (GateError,subprocess.CalledProcessError):pass
>     def experiment(self):
>         self.enabled=NFS[:];self.seed=True;self.start_session()
>         duration=self.c['experiment']['duration'];rate=self.c['experiment']['rate'];ue=self.ue_ip();dn=self.c['networks']['n6']['addresses']['dn']
>         rows=[]
>         for direction,sender,receiver,dest,port in [('ul','nr-ue','dn',dn,5001),('dl','dn','nr-ue',ue,5002)]:
>             log='/tmp/oai-lab-iperf-'+direction+'.csv'
>             # Bound receiver lifetime. Parse the receiver report, never the client exit code alone.
>             self.exec(receiver,'sh','-c',f'timeout {duration+20} iperf -s -u -p {port} -y C > {log} 2>&1 < /dev/null &')
>             time.sleep(2);start=int(time.time()*1000)
>             client=self.exec(sender,'iperf','-c',dest,'-u','-b',str(rate),'-t',str(duration),'-p',str(port),'-y','C',timeout=duration+30)
>             time.sleep(3);server=self.exec(receiver,'cat',log)
>             (self.out/(direction+'-sender.csv')).write_text(client);(self.out/(direction+'-receiver.csv')).write_text(server)
>             samples=[r for r in csv.reader(server.splitlines()) if len(r)>=13 and r[8].isdigit() and int(r[8])>0]
>             if not samples:raise GateError(direction+' has no positive receiver traffic report')
>             row=max(samples,key=lambda r:int(r[8]));loss=float(row[12])
>             write_json(self.out/(direction+'-summary.json'),{'bytes':int(row[8]),'lostPercent':loss})
>             if loss>=100:raise GateError(direction+' packet loss is 100%')
>             rows.append([direction,direction,rate,duration,start,int(time.time()*1000),'ok'])
>         with (self.out/'phases.csv').open('w') as f:
>             w=csv.writer(f);w.writerow(['phase','direction','offered_rate','duration_seconds','start_unix_ms','end_unix_ms','status']);w.writerows(rows)
>         time.sleep(5);self.collect()
>         run([sys.executable,ROOT/'scripts/k8s/analyze.py',self.out],capture=False)
>     def status(self):
>         self.k('get','pods,svc,pvc,jobs','-o','wide',capture=False)
>     def down(self):
>         run(H+['uninstall',PROFILE,'--ignore-not-found','--wait','--timeout','180s'],capture=False)
>         print('Release removed. Cluster, Secret, database PVC and artifact PVC retained.')
>
> def main():
>     parser=argparse.ArgumentParser();parser.add_argument('command',choices=['check','build','up','status','experiment','down']);parser.add_argument('--values',type=pathlib.Path,default=DEPLOY/'values/minikube.yaml');args=parser.parse_args()
>     lab=None
>     try:
>         lab=Lab(args);getattr(lab,args.command)()
>     except (GateError,subprocess.TimeoutExpired,ValueError,OSError) as e:
>         print('FAIL: '+str(e),file=sys.stderr)
>         STATE.mkdir(parents=True,exist_ok=True);write_json(STATE/'last-failure.json',{'command':args.command,'error':str(e),'time':datetime.datetime.now(datetime.timezone.utc).isoformat()})
>         if lab and args.command in ['up','experiment']:
>             try:lab.collect()
>             except Exception:pass
>         return 1
>     return 0
> if __name__=='__main__':sys.exit(main())
> PY
> cat > .dockerignore <<'EOF'
> **/.git
> **/build
> **/ran_build
> **/CMakeFiles
> **/__pycache__
> **/*.o
> **/*.a
> artifacts
> src/5gdeploy
> src/oai-upf
> EOF
> python3 -m py_compile scripts/k8s/lab.py deploy/k8s/images/runtime.py
> scripts/k8s/lab.sh check`
>
> - Ran `free -m; tail -8 /tmp/oai-lab-upf-build.log; cat deploy/k8s/chart/files/gnb.conf.tpl | tail -50; cat src/oai-upf/src/upf_app/include/XdpMode.hpp; cat deploy/k8s/images/Dockerfile.tools; cat configs/ue/ue1.conf | sed -E 's/(imsi|key|opc) = .*/\1 = REDACTED/' | head -30; rg -n 'CREATE TABLE|PRIMARY KEY' deploy/k8s/chart/files/schema.sql`
>
> - Ran `python3 - <<'PY'
> p='src/oai-upf/src/upf_app/app/upf_config_yaml.cpp';s=open(p).read().replace('upf::ParseXdpMode','::upf::ParseXdpMode');open(p,'w').write(s)
> p='deploy/k8s/vendor/multus.yaml';s=open('/tmp/multus.yml').read().replace('snapshot-thick','v4.2.2-thick');open(p,'w').write(s)
> PY
> docker build -f src/oai-upf/docker/Dockerfile.upf.ubuntu --target oai-upf --build-arg GIT_COMMIT=00b7485-xdp-mode --tag oai-upf-research:skb-dev src/oai-upf > /tmp/oai-lab-upf-build.log 2>&1`
>
> - Ran `scripts/k8s/lab.sh check; rg -n 'phase,|fprintf\(.*csv|header|timestamp' src/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c | head -25; rg -n 'success|associated|Association' src/oai-upf/src/pfcp/pfcp_l4_stack.cpp src/oai-upf/src/upf_app/app/upf_app.cpp | head -20; cat deploy/k8s/chart/templates/storage.yaml; ls /tmp/oai-lab-upf-before/src/oai-upf/src/upf_app`
>
> - Ran `rg -n -i 'association.*(success|accepted|established)|associated with' src/oai-upf/src | head -15; rg -n -i 'e2.*setup' src/flexric/src/agent/e2_agent.c | tail -15; rg -n 'csv_header_buffer|ue_id|node_id|UE_ID' src/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c | tail -20; rg --files /tmp/oai-lab-upf-before | head; tail -4 /tmp/oai-lab-upf-build.log; rg -n 'SERVER|BIND|IP' src/flexric/flexric.conf configs/flexric/flexric.conf`
>
> - Ran `rg -n 'Logger|associated|ASSOC' src/oai-upf/src/upf_app/app/upf_pfcp_association.cpp | head -40; rg -n 'Association|association' src/oai-upf/src/upf_app/app/upf_n4.cpp | head -40; tail -6 /tmp/oai-lab-build-cli.log; tail -5 artifacts/k8s/tools-build.log; tshark -G fields 2>/dev/null | rg 'pfcp\.(cause|seqno|sequence|ie_type)|volume_threshold.tovol' | head -12; sed -n '1020,1080p' src/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c; cat deploy/k8s/vendor/PROVENANCE.json`
>
> <details><summary>Explored 5 files, a search</summary>
>
> - Read `./src/oai-upf/src/upf_app/app/upf_n4.cpp`
> - Read `./src/oai-upf/src/upf_app/app/upf_pfcp_association.cpp`
> - Searched for `xdp|attach` in `ProgramLifeCycle.hpp`
> - Read `./deploy/k8s/chart/files/ue.conf.tpl`
> - Read `./tests/test_oai_upf_profile.sh`
> - Read `./deploy/k8s/vendor/multus.yaml`
>
> </details>
>
> - Ran `cat > scripts/k8s/analyze.py <<'PY'
> #!/usr/bin/env python3
> """Offline acceptance gates for real receiver/KPM/PFCP artifacts; no mock PASS."""
> import csv, datetime, json, pathlib, subprocess, sys
>
> def fields(pcap,expression,names):
>     cmd=['tshark','-r',str(pcap),'-Y',expression,'-T','fields','-E','separator=|','-E','occurrence=f']
>     for name in names:cmd+=['-e',name]
>     p=subprocess.run(cmd,text=True,capture_output=True,check=True)
>     return [r.split('|') for r in p.stdout.splitlines() if r]
>
> def iso(value):
>     try:return datetime.datetime.fromtimestamp(float(value),datetime.timezone.utc).isoformat()
>     except ValueError:return value
>
> def table(path,header,rows):
>     with path.open('w') as f:
>         w=csv.writer(f);w.writerow(header.split(','));w.writerows(rows)
>
> def kpm_gate(path):
>     with path.open() as f:
>         rows=list(csv.DictReader(f))
>     if not rows:raise ValueError('No KPM samples')
>     # Keep the research CSV schema intact, including dynamic measurement columns.
>     node=next((k for k in rows[0] if k and k.startswith('E2 Node ID')),None)
>     ue=next((k for k in rows[0] if k and k.startswith('UE ID')),None)
>     if not node or not ue or not any(r.get(node) and r.get(ue) and r[ue] not in ('0','unknown') for r in rows):raise ValueError('KPM missing node/UE identity')
>     ids={r[node] for r in rows if r.get(node)}
>     if len(ids)!=1:raise ValueError('Expected one E2 node')
>     return {'samples':len(rows),'nodes':sorted(ids),'ueIds':sorted({r[ue] for r in rows if r.get(ue)})}
>
> def pfcp_gate(config,reports,transactions):
>     if not config:raise ValueError('Missing Create URR/volume threshold; inspect SMF configuration')
>     thresholds=[int(r[7]) for r in config if r[7]]
>     if not thresholds:raise ValueError('Missing actual URR threshold')
>     if not reports:raise ValueError('Missing Usage Report. Actual threshold(s): '+str(thresholds)+' bytes; increase duration beyond measured threshold and rerun; no PASS')
>     requests=[r for r in transactions if r[3]=='56']
>     accepted=[r for r in transactions if r[3]=='57' and r[5]=='1']
>     if not requests or any(not any(q[4]==r[4] and q[1]==r[2] and q[2]==r[1] and float(q[0])>=float(r[0]) for q in accepted) for r in requests):raise ValueError('Usage Report has no matching accepted SMF response')
>     ul=sum(int(r[9] or 0) for r in reports);dl=sum(int(r[10] or 0) for r in reports)
>     if ul<=0 or dl<=0:raise ValueError('Usage Reports do not cover both UL and DL')
>     for r in reports:
>         if r[8] and r[9] and r[10] and int(r[8])!=int(r[9])+int(r[10]):raise ValueError('Inconsistent total/UL/DL accounting in Usage Report')
>     return {'thresholdBytes':thresholds,'reportCount':len(reports),'ulBytes':ul,'dlBytes':dl,'acceptedResponses':len(accepted)}
>
> def analyze(out):
>     pcap=out/'pfcp.pcap'
>     msgs=fields(pcap,'pfcp',['frame.time_epoch','ip.src','ip.dst','pfcp.msg_type','pfcp.seid'])
>     table(out/'pfcp_messages.csv','frame_time_iso,frame_time_epoch_seconds,ip_src,ip_dst,pfcp_message_type,pfcp_seid',[[iso(r[0]),*r] for r in msgs])
>     cfg=fields(pcap,'pfcp.msg_type == 50 && pfcp.ie_type == 6 && pfcp.volume_threshold.tovol',['frame.time_epoch','pfcp.msg_type','pfcp.seid','pfcp.urr_id','pfcp.measurement_method_flags.volume','pfcp.reporting_triggers_flags.volth','pfcp.volume_threshold.tovol'])
>     cfg=[[iso(r[0]),*r] for r in cfg]
>     table(out/'pfcp_urr_config.csv','frame_time_iso,frame_time_epoch_seconds,pfcp_message_type,pfcp_seid,urr_id,measurement_method_volume,trigger_volume_threshold,volume_threshold_bytes',cfg)
>     reports=fields(pcap,'pfcp.msg_type == 56 && pfcp.volume_measurement.tovol',['frame.time_epoch','pfcp.time_of_first_packet','pfcp.time_of_last_packet','ip.src','ip.dst','pfcp.msg_type','pfcp.seid','pfcp.urr_id','pfcp.volume_measurement.tovol','pfcp.volume_measurement.ulvol','pfcp.volume_measurement.dlvol','pfcp.usage_report_trigger_flags.volth','pfcp.usage_report_trigger_flags.perio','pfcp.usage_report_trigger.term'])
>     table(out/'pfcp_urr.csv','frame_time_iso,frame_time_epoch_seconds,first_packet_time_iso,last_packet_time_iso,ip_src,ip_dst,pfcp_message_type,pfcp_seid,urr_id,total_volume_bytes,uplink_volume_bytes,downlink_volume_bytes,trigger_volume_threshold,trigger_periodic,trigger_termination',[[iso(r[0]),*r] for r in reports])
>     transactions=fields(pcap,'pfcp.msg_type == 56 || pfcp.msg_type == 57',['frame.time_epoch','ip.src','ip.dst','pfcp.msg_type','pfcp.seqno','pfcp.cause'])
>     table(out/'pfcp_report_responses.csv','epoch,src,dst,type,sequence,cause',transactions)
>     result={'status':'PASS','scope':'one experiment; restart and lifecycle acceptance still required','pfcp':pfcp_gate(cfg,reports,transactions),'kpm':kpm_gate(out/'KPI_Metrics.csv')}
>     if not fields(pcap,'pfcp.msg_type == 51 && pfcp.cause == 1',['pfcp.seqno']):raise ValueError('Missing accepted PFCP session establishment')
>     for direction in ['ul','dl']:
>         result[direction]=json.loads((out/(direction+'-summary.json')).read_text())
>         if result[direction]['bytes']<=0 or result[direction]['lostPercent']>=100:raise ValueError('No received '+direction+' traffic')
>     attach=json.loads((out/'xdp.json').read_text())
>     entries=[e for item in (attach if isinstance(attach,list) else [attach]) for e in item.get('xdp',[])]
>     for iface in ['n3','n6']:
>         if not any(e.get('devname')==iface and e.get('mode')=='generic' and e.get('id',0)>0 for e in entries):raise ValueError('Missing SKB evidence on '+iface)
>     return result
>
> if __name__=='__main__':
>     out=pathlib.Path(sys.argv[1]);status=0
>     try:result=analyze(out)
>     except (ValueError,OSError,subprocess.CalledProcessError) as e:result={'status':'FAIL','reason':str(e)};status=1
>     (out/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));sys.exit(status)
> PY
> python3 - <<'PY'
> p='deploy/k8s/chart/templates/_nf.tpl';s=open(p).read().replace('          securityContext:\n            capabilities: {add: [NET_ADMIN], drop: [ALL]}','          securityContext:\n            privileged: {{ eq $nf "upf" }}\n            capabilities: {add: [NET_ADMIN], drop: [ALL]}');open(p,'w').write(s)
> p='deploy/k8s/vendor/PROVENANCE.json';import json,hashlib
> c=json.load(open(p));c['multus']={'url':'https://github.com/k8snetworkplumbingwg/multus-cni','commit':'00adf22482945de41ff702258593aaf867a48e2d','tag':'v4.2.2','image':'ghcr.io/k8snetworkplumbingwg/multus-cni:v4.2.2-thick','sha256':hashlib.sha256(open('deploy/k8s/vendor/multus.yaml','rb').read()).hexdigest(),'patch':'snapshot-thick image replaced with v4.2.2-thick'};open(p,'w').write(json.dumps(c,indent=2)+'\n')
> PY
> helm dependency update --skip-refresh deploy/k8s/chart >/tmp/oai-deps.log
> cat /tmp/oai-lab-minikube.log | tail -12
> cat /tmp/oai-lab-build-cli.log | tail -8`
>
> - Ran `scripts/k8s/lab.sh check && minikube start --profile=oai-lab --keep-context --driver=docker --container-runtime=containerd --kubernetes-version=v1.33.13 --cni=bridge --cpus=8 --memory=16384 --interactive=false > /tmp/oai-lab-minikube.log 2>&1`
>
> </details>
>
> Image UPF đã build thành công với patch XDP mode. Profile `oai-lab` đang được tạo với Kubernetes `v1.33.13`; image tools đã build xong và image RAN/FlexRIC đang build tiếp. CLI đã có kiểm tra tài nguyên, subnet và lưu lỗi; bộ phân tích PFCP sẽ yêu cầu response chấp nhận từ SMF khớp với Usage Report.
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `tail -12 artifacts/k8s/radio-build.log; tail -12 /tmp/oai-lab-minikube.log; kubectl config current-context; sed -n '255,343p' src/oai-upf/src/upf_app/user/ProgramLifeCycle.hpp; rg -n 'gNB_ID|nssai|sd |mcc|mnc|TAC|tracking_area|address|IPV4' deploy/k8s/chart/files/gnb.conf.tpl | head -24; cat deploy/k8s/chart/files/ue.conf.tpl`
> - Ran `python3 - <<'PY'
> from pathlib import Path
> import difflib,subprocess,json
> base=Path('/tmp/oai-lab-upf-before'); parts=[]
> for p in sorted(base.rglob('*')):
>  if p.is_file():
>   rel=p.relative_to(base); new=Path('src/oai-upf')/rel
>   parts+=difflib.unified_diff(p.read_text().splitlines(True),new.read_text().splitlines(True),fromfile='a/'+str(rel),tofile='b/'+str(rel))
> p=Path('src/oai-upf/src/upf_app/include/XdpMode.hpp');parts+=difflib.unified_diff([],p.read_text().splitlines(True),fromfile='/dev/null',tofile='b/src/upf_app/include/XdpMode.hpp')
> Path('patches/oai-upf-xdp-mode.patch').write_text(''.join(parts))
> parts=[]
> for p in Path('deploy/k8s/vendor').rglob('*.yaml'):
>  rel=p.relative_to('deploy/k8s/vendor')
>  raw=subprocess.run(['git','-C','/tmp/oai-lab-charts-7925f93','show','7925f939ea36a3c4c1df5525f3718ce8470f6b3f:'+str(rel)],capture_output=True,text=True)
>  if raw.returncode==0 and raw.stdout!=p.read_text():parts+=difflib.unified_diff(raw.stdout.splitlines(True),p.read_text().splitlines(True),fromfile='a/'+str(rel),tofile='b/'+str(rel))
> Path('patches/oai-charts-7925f93-lab.patch').write_text(''.join(parts))
> schema={'$schema':'http://json-schema.org/draft-07/schema#','type':'object','required':['global'],'properties':{'global':{'type':'object','required':['lab'],'properties':{'lab':{'type':'object','required':['profile','namespace','xdpMode','networks','workloads'],'properties':{'profile':{'const':'oai-lab'},'namespace':{'const':'oai-lab'},'xdpMode':{'const':'skb'},'usageReporting':{'const':True},'cpus':{'type':'integer','minimum':8},'memoryMiB':{'type':'integer','minimum':16384},'networks':{'type':'object','required':['n2','n3','n4','n6','e2']}}}}}}}
> Path('deploy/k8s/chart/values.schema.json').write_text(json.dumps(schema,indent=2)+'\n')
> PY
> python3 - <<'PY'
> p='scripts/k8s/lab.py';s=open(p).read();s=s.replace("K=['kubectl','--context'","K=['minikube','--profile',PROFILE,'kubectl','--','--context'")
> s=s.replace("run(['kubectl','--context',PROFILE,'--namespace','kube-system',", "run(K[:]+['--namespace','kube-system',")
> s=s.replace("self.enabled.append(nf);self.helm();self.ready(nf)\n        self.wait('PFCP association',lambda:re.search(r'(?i)(association.*(success|accepted|established)|associated with)',self.k('logs','deployment/oai-upf','-c','upf','--tail=500')))","self.enabled.append(nf);self.helm();self.ready(nf)\n            if nf=='smf':self.capture_start()\n        self.wait('PFCP accepted association',lambda:self.k('exec','deployment/oai-smf','-c','capture','--','tshark','-r','/artifacts/runs/'+self.runid+'/pfcp.pcap','-Y','pfcp.msg_type == 6 && pfcp.cause == 1','-T','fields','-e','pfcp.seqno',check=False).strip())")
> s=s.replace("    def start_session(self):\n        self.exec", "    def capture_start(self):\n        self.exec")
> s=s.replace("        self.enabled=NFS[:9];self.xapp=False;self.helm()", "    def start_session(self):\n        self.capture_start()\n        self.enabled=NFS[:9];self.xapp=False;self.helm()\n        self.k('wait','--for=delete','pod','-l','oai-lab/component=nr-ue','--timeout=90s')\n        self.k('wait','--for=delete','pod','-l','oai-lab/component=xapp','--timeout=90s')")
> # Hash only source; final digest also stored by images lock.
> s=s.replace("lock=json.loads((STATE/'images.json').read_text())\n        for", "lock=json.loads((STATE/'images.json').read_text())\n        current=fingerprint([ROOT/'src/oai-upf',ROOT/'src/oai-ran',ROOT/'src/flexric',DEPLOY/'images'])[:16]\n        if current!=lock['sourceHash']:raise GateError('Source changed since build; rebuild images')\n        for")
> # Correct iperf2 CSV positions (interval=6, bytes=7, bps=8, loss%=12).
> s=s.replace("r[8].isdigit() and int(r[8])>0", "r[7].isdigit() and int(r[7])>0").replace("key=lambda r:int(r[8])", "key=lambda r:int(r[7])").replace("'bytes':int(row[8])", "'bytes':int(row[7])")
> open(p,'w').write(s)
> PY
> python3 -m py_compile scripts/k8s/lab.py scripts/k8s/analyze.py
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system apply -f deploy/k8s/vendor/multus.yaml > /tmp/oai-lab-multus.log 2>&1`
> - Ran `tail -7 /tmp/oai-lab-multus.log; tail -8 artifacts/k8s/radio-build.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system get pods; cat artifacts/k8s/images.partial.json`
> - Ran `rg -n 'assoc|Assoc|ASSOC' src/oai-upf/src/upf_app/upf_n4.cpp | head -40; rg --files src/oai-upf/src | rg 'n4.cpp|association.cpp'; rg -n 'csv_prepend_e2_node_id|csv_prepend_ue_id' src/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c; sed -n '245,285p' src/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c
> python3 - <<'PY'
> p='scripts/k8s/lab.py';s=open(p).read().replace("net.get('IPAM',{}).get('Config',[])","(net.get('IPAM',{}).get('Config') or [])");open(p,'w').write(s)
> PY
> scripts/k8s/lab.sh build > /tmp/oai-lab-build-cli.log 2>&1`
> - Ran `cat > tests/k8s/test_lab.py <<'PY'
> import copy, importlib.util, ipaddress, json, pathlib, subprocess, tempfile, unittest
> from unittest.mock import patch
> import yaml
> ROOT=pathlib.Path(__file__).resolve().parents[2]
> def module(name,path):
>     s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
> lab=module('lab',ROOT/'scripts/k8s/lab.py');analyze=module('analyze',ROOT/'scripts/k8s/analyze.py')
> class Tests(unittest.TestCase):
>     def setUp(self):self.v=yaml.safe_load((ROOT/'deploy/k8s/values/minikube.yaml').read_text())
>     def test_topology(self):lab.validate(self.v)
>     def test_overlapping_network(self):
>         self.v['global']['lab']['networks']['n3']=copy.deepcopy(self.v['global']['lab']['networks']['n2'])
>         with self.assertRaisesRegex(lab.GateError,'Overlapping'):lab.validate(self.v)
>     def test_host_overlap(self):
>         with self.assertRaisesRegex(lab.GateError,'conflict'):lab.validate(self.v,[ipaddress.ip_network('172.30.0.0/16')])
>     def test_invalid_mode(self):
>         self.v['global']['lab']['xdpMode']='magic'
>         with self.assertRaises(lab.GateError):lab.validate(self.v)
>     def test_wrong_context(self):
>         self.v['global']['lab']['profile']='kubernetes-admin@kubernetes'
>         with self.assertRaises(lab.GateError):lab.validate(self.v)
>     def test_missing_image_does_not_bootstrap(self):
>         args=type('Args',(),{'values':ROOT/'deploy/k8s/values/minikube.yaml'})()
>         with tempfile.TemporaryDirectory() as d,patch.object(lab,'STATE',pathlib.Path(d)),patch.object(lab.Lab,'check'),patch.object(lab,'run') as run:
>             with self.assertRaisesRegex(lab.GateError,'build'):lab.Lab(args).up()
>             run.assert_not_called()
>     def test_bpf_permission_failure_is_fatal(self):
>         args=type('Args',(),{'values':ROOT/'deploy/k8s/values/minikube.yaml'})()
>         with patch.object(lab.Lab,'exec',side_effect=lab.GateError('Operation not permitted')):
>             with self.assertRaises(lab.GateError):lab.Lab(args).xdp_gate()
>     def test_native_is_not_skb(self):
>         args=type('Args',(),{'values':ROOT/'deploy/k8s/values/minikube.yaml'})()
>         with patch.object(lab.Lab,'exec',return_value='[{"xdp":[{"devname":"n3","mode":"driver","id":4}]}]'):
>             with self.assertRaises(lab.GateError):lab.Lab(args).xdp_gate()
>     def test_smf_not_ready_stops(self):
>         args=type('Args',(),{'values':ROOT/'deploy/k8s/values/minikube.yaml'})()
>         with patch.object(lab.Lab,'k',side_effect=lab.GateError('rollout timeout')):
>             with self.assertRaises(lab.GateError):lab.Lab(args).ready('smf')
>     def test_xapp_no_samples(self):
>         with tempfile.TemporaryDirectory() as d:
>             p=pathlib.Path(d)/'kpm.csv';p.write_text('E2 Node ID,UE ID\n')
>             with self.assertRaisesRegex(ValueError,'No KPM'):analyze.kpm_gate(p)
>     def test_report_missing_or_rejected(self):
>         cfg=[['iso','1','50','12','1','1','1','1000']]
>         with self.assertRaisesRegex(ValueError,'threshold'):analyze.pfcp_gate(cfg,[],[])
>         report=[['1','','','a','b','56','1','1','200','100','100','','','']]
>         with self.assertRaisesRegex(ValueError,'accepted'):analyze.pfcp_gate(cfg,report,[['1','a','b','56','99',''],['2','b','a','57','99','64']])
>     def test_response_transaction_matching(self):
>         cfg=[['iso','1','50','12','1','1','1','1000']];report=[['1','','','a','b','56','1','1','200','100','100','','','']]
>         with self.assertRaises(ValueError):analyze.pfcp_gate(cfg,report,[['1','a','b','56','99',''],['2','b','a','57','98','1']])
>     def test_render_security_and_interfaces(self):
>         args=['helm','template','oai-lab',str(ROOT/'deploy/k8s/chart'),'-f',str(ROOT/'deploy/k8s/values/minikube.yaml'),'--set',','.join('oai-'+n+'.enabled=true' for n in lab.NFS)+',seedEnabled=true,xappEnabled=true']
>         docs=list(yaml.safe_load_all(subprocess.check_output(args,text=True)))
>         cm=next(d for d in docs if d and d['kind']=='ConfigMap' and d['metadata']['name']=='oai-lab-config')
>         c=yaml.safe_load(cm['data']['config.yaml']);self.assertEqual(c['upf']['support_features']['xdp_mode'],'skb');self.assertEqual(len(c['smf']['upfs']),1)
>         self.assertNotIn('DROP DATABASE',cm['data']['schema.sql']);self.assertNotIn('INSERT INTO',cm['data']['schema.sql'])
>         for d in docs:
>             if d and d['kind']=='Deployment':
>                 p=d['spec']['template']['spec'];self.assertFalse(p.get('hostNetwork',False));self.assertEqual(d['spec']['strategy']['type'],'Recreate')
>                 for cont in p.get('initContainers',[])+p['containers']:
>                     if cont.get('securityContext',{}).get('privileged'):self.assertEqual(d['metadata']['name'],'oai-upf')
>                 if d['metadata']['name']=='oai-upf':
>                     nets=json.loads(d['spec']['template']['metadata']['annotations']['k8s.v1.cni.cncf.io/networks']);self.assertEqual({n['interface'] for n in nets},{'n3','n4','n6'})
>             if d and d['kind']=='NetworkAttachmentDefinition':
>                 n=json.loads(d['spec']['config']);self.assertEqual(n['type'],'bridge');self.assertNotIn('gateway',n['ipam'])
> if __name__=='__main__':unittest.main()
> PY
> cat > tests/k8s/xdp_mode.cpp <<'CPP'
> #include "XdpMode.hpp"
> #include <cassert>
> int main() {
>   using namespace upf;
>   assert(InitialXdpFlags(ParseXdpMode("skb")) == XDP_FLAGS_SKB_MODE);
>   assert(InitialXdpFlags(ParseXdpMode("native")) == XDP_FLAGS_DRV_MODE);
>   assert(InitialXdpFlags(ParseXdpMode("auto")) == XDP_FLAGS_DRV_MODE);
>   assert(ShouldFallbackToSkb(XdpMode::Auto, -EOPNOTSUPP));
>   assert(!ShouldFallbackToSkb(XdpMode::Skb, -EOPNOTSUPP));
>   assert(!ShouldFallbackToSkb(XdpMode::Native, -EOPNOTSUPP));
>   assert(!ShouldFallbackToSkb(XdpMode::Auto, -EPERM));
>   bool rejected=false;
>   try { ParseXdpMode("magic"); } catch (const std::invalid_argument&) { rejected=true; }
>   assert(rejected);
> }
> CPP
> python3 -m unittest discover -s tests/k8s -v
>  g++ -std=c++17 -Isrc/oai-upf/src/upf_app/include tests/k8s/xdp_mode.cpp -o /tmp/oai-xdp-mode-test && /tmp/oai-xdp-mode-test`
> - Ran `rg -n 'bpf_xdp_attach|bpf_set_link_xdp|bpf_xdp_detach' src/oai-upf/src/upf_app --glob '!*.skel.h'; tail -6 artifacts/k8s/radio-build.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system get pods -l app=multus; minikube --profile oai-lab ssh -- 'test -x /opt/cni/bin/bridge && test -x /opt/cni/bin/static && test -e /dev/net/tun'; df -h .`
> - Ran `rg -n 'asn1c|BUILD|TEST|add_subdirectory|install' src/flexric/CMakeLists.txt | tail -40; cat src/flexric/examples/xApp/c/monitor/CMakeLists.txt | tail -100; cat src/flexric/src/sm/CMakeLists.txt | head -70; rg -n 'add_library|install' src/flexric/src/sm/*/CMakeLists.txt | head -40; tail -12 /tmp/oai-stage-core.log`
> - Ran `rg -n -i 'error:|failed|not found|could not' artifacts/k8s/radio-build.log | tail -15; tail -5 /tmp/oai-lab-build-cli.log; cat > /tmp/oai-stage-core.py <<'PY'
> import sys,json,yaml
> sys.path.insert(0,'scripts/k8s')
> from lab import *
> args=type('Args',(),{'values':DEPLOY/'values/minikube.yaml'})()
> l=Lab(args)
> partial=json.loads((STATE/'images.partial.json').read_text())
> overlay={'global':{'lab':{'toolsImage':partial['tools']['image'],'workloads':{'upf':{'image':partial['upf']['image']}}}}}
> (STATE/'images.yaml').write_text(yaml.safe_dump(overlay))
> for i in partial.values():run(['minikube','--profile',PROFILE,'image','load',i['image']],capture=False)
> l.k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'Namespace','metadata':{'name':PROFILE,'labels':{'pod-security.kubernetes.io/enforce':'privileged'}}}))
> l.credentials();l.helm();l.ready('db');l.ready('dn')
> l.k('delete','job','oai-lab-subscriber','--ignore-not-found');l.seed=True;l.helm()
> l.k('wait','--for=condition=complete','job/oai-lab-subscriber','--timeout=180s',capture=False)
> for nf in NFS[:7]:
>  l.enabled.append(nf);l.helm();l.ready(nf)
>  if nf=='smf':l.capture_start()
> (STATE/'bootstrap-run').write_text(l.runid)
> PY
> python3 /tmp/oai-stage-core.py > /tmp/oai-stage-core.log 2>&1`
>
> </details>
>
> System error
>
> You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Sep 27th, 2026 1:59 AM.
</details>

> ở chỗ dừng lại là đã làm đến mốc nào của plan rồi? tiếp tục hoàn thành mốc đó

<details><summary>17 previous messages</summary>

> Đang ở **Mốc 1 — Render và bootstrap**: Helm render/lint đã qua, cluster `oai-lab` và Multus đã chạy, image tools và UPF đã build thành công. Image RAN/FlexRIC còn lỗi build; Mốc 1 chưa hoàn tất. Mình sẽ xử lý nốt image này và kiểm tra mạng, DNS, SCTP cùng khả năng load image vào minikube trước khi chốt mốc.
>
> <details><summary>Explored 2 files, 2 searches, ran 9 commands</summary>
>
> - Ran `tail -25 /tmp/oai-stage-core.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods; df -h .; cat src/flexric/src/CMakeLists.txt | tail -45; rg -n 'install\(' src/flexric/src/{agent,ric,xApp}/CMakeLists.txt; rg -n 'install.*asn|ASN1|asn1c' src/oai-ran/cmake_targets/tools/build_helper | head -18`
>
> - Ran `minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab logs job/oai-lab-subscriber; head -8 deploy/k8s/chart/files/schema.sql; sed -n '84,100p' deploy/k8s/chart/files/schema.sql; rg -n 'KPM_MEAS_LIST' src/flexric/CMakeLists.txt; sed -n '480,500p' src/oai-ran/cmake_targets/tools/build_helper; rg -n 'cmake --install|install\(' src/flexric/examples/CMakeLists.txt src/flexric/src/xApp/CMakeLists.txt`
>
> <details><summary>Explored 3 files, 2 searches</summary>
>
> - Searched for `KPM_MEAS_LIST|fopen` in `metrics_factory.c`
> - Read `./src/flexric/CMakeLists.txt`
> - Searched for `LIBCONFIG|libconfig|cJSON` in `build_helper`
> - Read `./deploy/k8s/chart/files/schema.sql`
> - Read `./deploy/k8s/chart/files/schema.sql`
>
> </details>
>
> - Ran `sed -n '27,43p' src/oai-ran/cmake_targets/build_oai; sed -n '245,280p' src/oai-ran/cmake_targets/build_oai; tail -5 /tmp/oai-lab-build-cli.log; cat /tmp/oai-stage-core.log | tail -6; cat deploy/k8s/vendor/oai-5g-core/oai-upf/templates/configmap.yaml | head -8; rg -n 'cmake_targets/log|\.git' src/oai-ran/.dockerignore`
>
> - Ran `ps -eo pid,args | rg 'docker build -f.*/Dockerfile.radio'; tail -4 artifacts/k8s/radio-build.log; rg -n 'build-tool-opt' src/oai-ran/cmake_targets/build_oai`
>
> - Ran `rg -n 'jobs|nproc|NUM_CPU|ninja|make -j' src/oai-ran/cmake_targets/build_oai | head -24; rg -n 'KPM_MEAS_LIST' src/flexric/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c; cat > /tmp/oai-radio-fix.py <<'PY'
> p='deploy/k8s/images/Dockerfile.radio'
> s=open(p).read().replace('-DCMAKE_INSTALL_PREFIX=/opt/oai && cmake --build /source/flexric/build -j2','-DCMAKE_INSTALL_PREFIX=/opt/oai -DUNIT_TEST=FALSE && cmake --build /source/flexric/build -j2 --target nearRT-RIC xapp_kpm_moni_write_to_csv mac_sm rlc_sm pdcp_sm slice_sm tc_sm gtp_sm kpm_sm rc_sm')
> s=s.replace('&& rm -rf /var/lib/apt/lists/* /source','&& cp /source/flexric/build/28_552_kpm_meas.txt /tmp/kpm.txt && rm -rf /var/lib/apt/lists/* /source && mkdir -p /source/flexric/build && mv /tmp/kpm.txt /source/flexric/build/28_552_kpm_meas.txt')
> open(p,'w').write(s)
> p='deploy/k8s/chart/files/schema.sql';s=open(p).read().replace('DDL only; local','DDL only, local');open(p,'w').write(s)
> PY
> python3 /tmp/oai-radio-fix.py
> scripts/k8s/lab.sh build > /tmp/oai-lab-build-cli.log 2>&1`
>
> - Ran `sed -n '105,139p' src/oai-upf/docker/Dockerfile.upf.ubuntu; cat /tmp/oai-stage-core.log | tail -10; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get jobs; tail -6 artifacts/k8s/radio-build.log; rg -n 'minikube|Migration|Kubernetes' docs/KUBERNETES-MIGRATION.md | head -20`
>
> - Ran `kill -TERM 253822
> python3 - <<'PY'
> p='deploy/k8s/images/Dockerfile.radio';s=open(p).read().replace('./build_oai --ninja','./build_oai --build-tool-opt -j2 --ninja');open(p,'w').write(s)
> PY
> scripts/k8s/lab.sh build > /tmp/oai-lab-build-cli.log 2>&1`
>
> - Ran `cat > deploy/k8s/chart/files/bootstrap.py <<'PY'
> """Two-pod network checks: Multus interfaces, UDP on every network, SCTP and DNS."""
> import ipaddress,json,os,selectors,socket,subprocess,time
> cfg=json.load(open('/config/lab.json'))
> side=os.environ['SIDE'];offset=250 if side=='server' else 251
> address=lambda net,n: str(ipaddress.ip_network(net['subnet']).network_address+n)
> interfaces=json.loads(subprocess.check_output(['ip','-j','address'],text=True))
> for name,net in cfg['networks'].items():
>     own=next(i for i in interfaces if i['ifname']==name)
>     assert any(a.get('local')==address(net,offset) for a in own['addr_info']),name
> routes=json.loads(subprocess.check_output(['ip','-j','route'],text=True))
> assert all(r['dev']=='eth0' for r in routes if r.get('dst')=='default'),'secondary default route'
> assert socket.gethostbyname('kubernetes.default.svc.cluster.local')
> assert socket.gethostbyname('oai-lab-db')
> if side=='server':
>     sel=selectors.DefaultSelector()
>     for name,net in cfg['networks'].items():
>         sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind((address(net,offset),49000));sel.register(sock,selectors.EVENT_READ,name)
>     sctp=socket.socket(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_SCTP);sctp.bind((address(cfg['networks']['n2'],offset),49001));sctp.listen(1);sel.register(sctp,selectors.EVENT_READ,'sctp')
>     seen=set();deadline=time.monotonic()+120
>     while len(seen)<6 and time.monotonic()<deadline:
>         for key,_ in sel.select(2):
>             if key.data=='sctp':
>                 conn,_=key.fileobj.accept();assert conn.recv(32)==b'oai-lab';conn.sendall(b'ok');conn.close()
>             else:
>                 data,peer=key.fileobj.recvfrom(64);assert data==b'oai-lab';key.fileobj.sendto(b'ok',peer)
>             seen.add(key.data)
>     assert len(seen)==6,'secondary/SCTP peers timed out'
> else:
>     for name,net in cfg['networks'].items():
>         sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind((address(net,offset),0));sock.settimeout(2)
>         for attempt in range(30):
>             try:
>                 sock.sendto(b'oai-lab',(address(net,250),49000));assert sock.recv(32)==b'ok';break
>             except (socket.timeout,ConnectionRefusedError):time.sleep(1)
>         else:raise RuntimeError('UDP network failed: '+name)
>         sock.close()
>     with socket.socket(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_SCTP) as sock:
>         sock.settimeout(10);sock.connect((address(cfg['networks']['n2'],250),49001));sock.sendall(b'oai-lab');assert sock.recv(32)==b'ok'
> print(json.dumps({'status':'PASS','side':side,'interfaces':list(cfg['networks']),'dns':True,'sctp':True,'secondaryDefaultRoute':False}))
> PY
> cat > deploy/k8s/chart/templates/bootstrap.yaml <<'EOF'
> {{- if .Values.bootstrapTestEnabled }}
> apiVersion: v1
> kind: ConfigMap
> metadata: {name: oai-lab-bootstrap}
> data:
>   bootstrap.py: |
>     {{- .Files.Get "files/bootstrap.py" | nindent 4 }}
> {{- range $side := list "server" "client" }}
> {{- $attachments := list }}
> {{- range $name,$network := $.Values.global.lab.networks }}
> {{- $nad := printf "oai-bootstrap-%s-%s" $side $name }}
> {{- $attachments = append $attachments (dict "name" $nad "interface" $name) }}
> ---
> apiVersion: k8s.cni.cncf.io/v1
> kind: NetworkAttachmentDefinition
> metadata: {name: {{ $nad }}}
> spec:
>   config: {{ toJson (dict "cniVersion" "0.3.1" "type" "bridge" "bridge" $network.bridge "isGateway" false "ipam" (dict "type" "static" "addresses" (list (dict "address" (printf "%s.%s/%s" (regexReplaceAll "\\.[0-9]+/[0-9]+$" $network.subnet "") (ternary "250" "251" (eq $side "server")) (last (splitList "/" $network.subnet))))))) | quote }}
> {{- end }}
> ---
> apiVersion: batch/v1
> kind: Job
> metadata: {name: oai-lab-bootstrap-{{ $side }}}
> spec:
>   backoffLimit: 0
>   activeDeadlineSeconds: 180
>   template:
>     metadata:
>       annotations:
>         k8s.v1.cni.cncf.io/networks: {{ toJson $attachments | quote }}
>     spec:
>       automountServiceAccountToken: false
>       restartPolicy: Never
>       containers:
>         - name: probe
>           image: {{ $.Values.global.lab.toolsImage | quote }}
>           command: [python3, /probe/bootstrap.py]
>           env: [{name: SIDE, value: {{ $side }}}]
>           securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
>           resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 250m, memory: 128Mi}}
>           volumeMounts:
>             - {name: config, mountPath: /config, readOnly: true}
>             - {name: probe, mountPath: /probe, readOnly: true}
>       volumes:
>         - name: config
>           configMap: {name: oai-lab-config}
>         - name: probe
>           configMap: {name: oai-lab-bootstrap}
> {{- end }}
> {{- end }}
> EOF
> python3 - <<'PY'
> p='scripts/k8s/lab.py';s=open(p).read().replace('self.enabled=[];self.seed=False;self.xapp=False','self.enabled=[];self.seed=False;self.xapp=False;self.bootstrap=False')
> s=s.replace("'xappEnabled='+str(self.xapp).lower()]","'xappEnabled='+str(self.xapp).lower(),'bootstrapTestEnabled='+str(self.bootstrap).lower()]")
> s=s.replace("self.credentials();self.helm();self.ready('db');self.ready('dn')","self.credentials();self.helm();self.ready('db');self.ready('dn')\n        for side in ['server','client']:self.k('delete','job','oai-lab-bootstrap-'+side,'--ignore-not-found')\n        self.bootstrap=True;self.helm()\n        for side in ['server','client']:\n            self.k('wait','--for=condition=complete','job/oai-lab-bootstrap-'+side,'--timeout=180s',capture=False)\n            (STATE/('bootstrap-'+side+'.json')).write_text(self.k('logs','job/oai-lab-bootstrap-'+side))\n        write_json(STATE/'bootstrap.json',{'status':'PASS','scope':'milestone 1, not end-to-end acceptance','images':lock})\n        if self.args.stage=='bootstrap':return")
> s=s.replace("args=parser.parse_args()","parser.add_argument('--stage',choices=['bootstrap','core','full'],default='full');args=parser.parse_args()")
> s=s.replace("        for nf in ['flexric','gnb']:","        if self.args.stage=='core':return\n        for nf in ['flexric','gnb']:")
> # Limit addresses/subnets for initial probe template and reserved .250/251.
> s=s.replace("subnet=ipaddress.ip_network(n['subnet']);nets.append(subnet)","subnet=ipaddress.ip_network(n['subnet']);nets.append(subnet)\n        if subnet.version!=4 or subnet.prefixlen!=24:raise GateError('Initial secondary topology requires IPv4 /24 networks')\n        if any(ipaddress.ip_address(a) in [subnet.network_address+250,subnet.network_address+251] for a in n['addresses'].values()):raise GateError('Addresses .250/.251 reserved for bootstrap probes')")
> open(p,'w').write(s)
> PY
> helm template oai-lab deploy/k8s/chart --set bootstrapTestEnabled=true > /tmp/oai-bootstrap-render.yaml
> python3 - <<'PY'
> import yaml,json
> for d in yaml.safe_load_all(open('/tmp/oai-bootstrap-render.yaml')):
>  if d and d['kind']=='NetworkAttachmentDefinition':json.loads(d['spec']['config'])
> print('Bootstrap render valid')
> PY
> cat /tmp/oai-lab-build-cli.log | tail -4; tail -5 artifacts/k8s/radio-build.log`
>
> - Ran `rg -n 'error:|Error|FAILED|not found|No such|exit code' artifacts/k8s/radio-build.log | tail -18; tail -4 /tmp/oai-stage-core.log; ps -eo pid,args | rg '/tmp/oai-stage-core.py'`
>
> </details>
>
> Cluster và Multus đã sẵn sàng; context mặc định vẫn là `kubernetes-admin@kubernetes`, không bị đổi. Lỗi image radio nằm ở compiler ASN.1 mà FlexRIC cần nhưng Dockerfile chưa cài. Mình đang bổ sung compiler tại commit mà source OAI đang pin, rồi chạy kiểm tra liên pod cho cả 5 mạng phụ và SCTP.
>
> <details><summary>Explored 3 files, a search, 2 lists, ran 9 commands</summary>
>
> - Ran `cat tests/test_oai_upf_profile.sh | head -100; cat docs/KUBERNETES-MIGRATION.md | head -26; head -22 docs/BUILD-FROM-SCRATCH.md; rg -n 'generate|cap_add|BPF' scripts/configure-core.sh scripts/lib/oai-upf-profile.sh | tail -24; ls scripts/lib; du -sh deploy/k8s/*; tail -6 artifacts/k8s/radio-build.log`
>
> <details><summary>Explored 3 files, a search, 2 lists</summary>
>
> - Listed files in `core`
> - Listed files in `core`
> - Read `./scripts/lib/oai-upf-profile.sh`
> - Read `./scripts/configure-core.sh`
> - Read `./scripts/lib/generate-core-scenario.sh`
> - Searched for `BPF|cap_add|oai-upf-bpf` in `up.ts`
>
> </details>
>
> - Ran `ls src/5gdeploy/node_modules/.bin/tsx; rg -n 'NET_ADMIN|cap_add|services:' compose/core/compose.yml | head -16; tail -7 artifacts/k8s/radio-build.log; free -m; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab apply --dry-run=server -f /tmp/oai-bootstrap-render.yaml > /tmp/oai-server-validation.log 2>&1; tail -4 /tmp/oai-server-validation.log`
>
> - Ran `python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> a=type('A',(),{'values':DEPLOY/'values/minikube.yaml'})();l=Lab(a);l.bootstrap=True;l.helm()
> for side in ['server','client']:
>  l.k('wait','--for=condition=complete','job/oai-lab-bootstrap-'+side,'--timeout=180s',capture=False)
>  (STATE/('bootstrap-'+side+'.json')).write_text(l.k('logs','job/oai-lab-bootstrap-'+side))
> PY`
>
> - Ran `python3 - <<'PY'
> p='scripts/lib/oai-upf-profile.sh';s=open(p).read();mark='profile_apply() {'
> f='''profile_validate_compose_capabilities() {
>     local compose_file=$1
>     [[ "$OAI_UPF_DATAPATH" == "xdp-skb" ]] || return 0
>     # The generator must grant these when --oai-upf-bpf=true is passed.
>     local capability
>     for capability in NET_ADMIN BPF SYS_ADMIN SYS_RESOURCE; do
>         if ! CAPABILITY="$capability" yq eval -e '
>           [.services[] | select((.image // "") | test("(?i)oai.*upf|upf.*oai")) |
>             ((.cap_add // []) | contains([strenv(CAPABILITY)]))] |
>           length > 0 and all
>         ' "$compose_file" >/dev/null; then
>             echo "ERROR: Generated OAI UPF Compose lacks $capability; check --oai-upf-bpf=true." >&2
>             return 1
>         fi
>     done
> }
>
> '''
> s=s.replace(mark,f+mark).replace('    profile_patch_compose "$PROFILE_COMPOSE_DIR/compose.yml"','    profile_patch_compose "$PROFILE_COMPOSE_DIR/compose.yml"\n    profile_validate_compose_capabilities "$PROFILE_COMPOSE_DIR/compose.yml"')
> open(p,'w').write(s)
> PY
> bash tests/test_oai_upf_profile.sh
> mkdir -p artifacts/k8s/baseline
> python3 - <<'PY'
> import yaml,json,subprocess,pathlib,hashlib
> root=pathlib.Path('.')
> c=yaml.safe_load((root/'compose/core/compose.yml').read_text())
> report={'backend':'compose','runtimeAcceptance':'NOT_RUN','reason':'Legacy stack not active at migration baseline; no mock traffic substituted','upfServices':{n:{'image':x['image'],'capabilities':x.get('cap_add',[])} for n,x in c['services'].items() if 'upf' in x.get('image','')},'composeHash':hashlib.sha256((root/'compose/core/compose.yml').read_bytes()).hexdigest(),'containers':subprocess.check_output(['docker','ps','-a','--format','{{.Names}} {{.Status}}'],text=True).splitlines()}
> (root/'artifacts/k8s/baseline/compose.json').write_text(json.dumps(report,indent=2)+'\n')
> PY
> cat artifacts/k8s/bootstrap-client.json 2>/dev/null; tail -4 artifacts/k8s/radio-build.log`
>
> - Ran ````bash -c 'source scripts/lib/oai-upf-profile.sh; profile_validate_compose_capabilities compose/core/compose.yml'; python3 - <<'PY'
> import yaml
> c={'services':{'upf':{'image':'oai-upf:local','cap_add':['NET_ADMIN','BPF','SYS_ADMIN','SYS_RESOURCE']}}}
> open('/tmp/oai-caps.yml','w').write(yaml.safe_dump(c))
> PY
> bash -c 'source scripts/lib/oai-upf-profile.sh; profile_validate_compose_capabilities /tmp/oai-caps.yml'
> cat > docs/K8S-LAB.md <<'EOF'
> # OAI lab trên minikube
>
> Backend mới nằm trong `deploy/k8s` và `scripts/k8s`. Backend này không gọi 5gdeploy, pipework hoặc launcher NIST. Compose và source cũ vẫn được giữ để đối chiếu. Minikube dùng Docker driver để tạo node; workload bên trong node dùng containerd và Kubernetes.
>
> ## Phạm vi và trạng thái
>
> Một UE, một slice, một UPF; PLMN 00101, TAC 7, SST 1, SD FFFFFF, DNN nist-dnn, PDU 10.1.0.0/16. Không migrate SMO/ONAP/non-RT RIC. Chỉ UPF được privileged trong các workload ứng dụng; Multus là hạ tầng node và cần quyền riêng.
>
> Mốc 1 chỉ xác nhận build/render/bootstrap/mạng. **Không đồng nghĩa nghiệm thu migration:** Mốc 2–4 còn cần NF registration, PDU, XDP-SKB thật, traffic hai chiều, Usage Report được SMF chấp nhận và KPM. Xem `artifacts/k8s/milestones.json` để biết trạng thái được kiểm chứng gần nhất.
>
> ## Dựng trên máy sạch
>
> 1. Tái dựng source và patch theo [BUILD-FROM-SCRATCH.md](BUILD-FROM-SCRATCH.md). Sau patch URR `00b7485`, áp dụng thêm:
>
>    ```sh
>    cd src/oai-upf
>    git apply ../../patches/oai-upf-xdp-mode.patch
>    cd ../..
>    ```
>
>    Bỏ qua thao tác apply nếu đang dùng snapshot workspace đã patch. Không áp dụng hai lần.
>
> 2. Cài Docker Engine và quyền truy cập Docker, minikube, Helm 3, kubectl, Python 3 cùng PyYAML, tshark, iproute2 và g++. Máy cần ít nhất 8 CPU, 16 GiB cấp cho lab, RAM dư cho host/build và ít nhất 25 GiB đĩa còn trống tại preflight. Build lần đầu có thể cần nhiều hơn tùy cache.
>
> 3. Chạy từ root workspace:
>
>    ```sh
>    scripts/k8s/lab.sh check
>    scripts/k8s/lab.sh build
>    scripts/k8s/lab.sh up --stage bootstrap
>    scripts/k8s/lab.sh status
>    ```
>
>    Build tuần tự tools → UPF → radio. Radio image chứa gNB, UE, FlexRIC và xApp build từ source local; không thay bằng image `develop`. Compiler ASN.1 được pin commit `940dd5fa9f3917913fd487b13dfddfacd0ded06e`, cùng pin trong RAN build helper. Xem log tại `artifacts/k8s/*-build.log`.
>
> 4. Khi Mốc 1 đã qua, tiếp tục từng giai đoạn:
>
>    ```sh
>    scripts/k8s/lab.sh up --stage core
>    scripts/k8s/lab.sh up
>    scripts/k8s/lab.sh experiment
>    ```
>
>    Các giai đoạn này đang cần nghiệm thu runtime; lỗi trả exit code khác 0. Không coi pod Running hoặc kiểm thử giả lập là PASS end-to-end.
>
> 5. Dừng release, giữ dữ liệu:
>
>    ```sh
>    scripts/k8s/lab.sh down
>    ```
>
>    Giữ cluster, Secret, PVC database và artifact. Không xóa profile, namespace hoặc sửa cluster khác. Mọi lệnh kubectl dùng context `oai-lab`; CLI sử dụng kubectl tương ứng phiên bản minikube. `minikube start --keep-context` không đổi context mặc định của người dùng.
>
> ## Cấu hình và provenance
>
> - Values chính: `deploy/k8s/values/minikube.yaml`; image override sinh ra ở `artifacts/k8s/images.yaml`. `images.json` ghi hash source, image ID và digest registry nếu có. Image local không có RepoDigest thì ghi image ID, không tự tạo digest giả.
> - OAI charts vendored tại commit `7925f939ea36a3c4c1df5525f3718ce8470f6b3f`, dependency local trong umbrella chart. `vendor/PROVENANCE.json` ghi nguồn và phiên bản Multus. `Chart.lock` pin dependency.
> - `patches/oai-charts-7925f93-lab.patch` thêm nhánh opt-in `global.lab` cho deployment, bỏ ConfigMap/NAD mặc định trong nhánh lab. Service/selectors/chart metadata của OAI vẫn được dùng. Nhánh lab gọi helper deployment của umbrella, tạo bridge/static NAD và cấu hình tập trung.
> - `patches/oai-upf-xdp-mode.patch` độc lập patch URR. YAML thêm `upf.support_features.xdp_mode`: auto mặc định giữ đường Compose, skb bắt buộc SKB, native bắt buộc driver. Chỉ auto được fallback khi native trả EOPNOTSUPP. Teardown kiểm tra program ID và expected FD trước detach bằng đúng mode.
> - Config NF, gNB, UE, FlexRIC được template; các placeholder credential chỉ thay ở init container từ Secret. Values và ConfigMap không chứa khóa SIM. UE1 hiện có là nguồn credential mẫu lần tạo Secret đầu; Secret được tái sử dụng sau down/up.
> - Schema SQL là DDL snapshot OAI, không chứa subscriber có sẵn và không DROP DATABASE. Job seed dùng upsert cùng khóa duy nhất và giữ SQN khi chạy lại.
> - SMF vẫn v2.2.0. Không có tham số tùy chỉnh threshold URR mới; analyzer đọc threshold thực từ Create URR.
>
> ## Mapping từ script cũ
>
> | Trách nhiệm trước đây | Kubernetes |
> |---|---|
> | `configure-core.sh`, generator 5gdeploy | Helm values, ConfigMap và Secret |
> | `compose.sh`, `start-core.sh` | Helm release, Deployment/StatefulSet và rollout gates |
> | `bridge.sh`, pipework, IP host | Multus bridge/static NetworkAttachmentDefinition trong node |
> | subscriber SQL/script | MariaDB PVC và Job upsert |
> | `start-gnb.sh`, `start-ue.sh`, namespace/veth host | Pod gNB/UE, Service RFsim, TUN và NET_ADMIN của UE |
> | FlexRIC/xApp launcher | Deployment, E2 IP tĩnh và artifact PVC |
> | traffic/capture host | DN image iperf2, SMF capture sidecar, runner Kubernetes |
> | stop/cleanup host | Helm uninstall giới hạn release, giữ PVC |
>
> ## Kiểm chứng
>
> ```sh
> python3 -m unittest discover -s tests/k8s -v
> g++ -std=c++17 -Isrc/oai-upf/src/upf_app/include tests/k8s/xdp_mode.cpp -o /tmp/oai-xdp-mode-test
> /tmp/oai-xdp-mode-test
> bash tests/test_oai_upf_profile.sh
> ```
>
> Bootstrap tạo hai Job với IP .250/.251 trên mỗi mạng secondary; đây là IP dành riêng cho probe, không dùng cho NF. Probe xác nhận địa chỉ/interface, UDP liên pod trên cả 5 mạng, SCTP liên pod trên N2, DNS và không có default route secondary. Job không privileged. Kết quả nằm tại `artifacts/k8s/bootstrap-{server,client}.json`.
>
> `experiment` tạo capture trước session UE mới, lưu receiver CSV iperf2, giữ schema `KPI_Metrics.csv`, `pfcp_messages.csv`, `pfcp_urr_config.csv`, `pfcp_urr.csv`, `phases.csv`, bổ sung metadata/image/source/chart/XDP. Thiếu báo cáo URR hoặc KPM phải FAIL. Analyzer ghép Usage Report và response bằng sequence + cặp IP; yêu cầu cause accepted, volume UL/DL dương. Nếu traffic chưa đạt threshold, tăng `global.lab.experiment.duration` và chạy lại. Không chỉnh threshold metadata để giả lập hỗ trợ SMF.
>
> Restart UPF, tái tạo session, chạy lại experiment và vòng down/up/upgrade giữ subscriber/PVC là các bước nghiệm thu tiếp theo; một file acceptance PASS cho một lần đo chưa chứng minh toàn bộ lifecycle.
>
> Nguồn: [OAI charts](https://gitlab.eurecom.fr/oai/orchestration/charts/-/tree/7925f939ea36a3c4c1df5525f3718ce8470f6b3f), [Multus v4.2.2](https://github.com/k8snetworkplumbingwg/multus-cni/tree/v4.2.2), [minikube start](https://minikube.sigs.k8s.io/docs/commands/start/).
> EOF
> python3 - <<'PY'
> from pathlib import Path
> p=Path('docs/KUBERNETES-MIGRATION.md');s=p.read_text().replace('Kiểm tra 26/09/2026. Đây là thiết kế/lộ trình đề xuất, chưa có migration được triển khai.','Bản phân tích ban đầu ngày 26/09/2026 được giữ bên dưới để đối chiếu. Backend Kubernetes hiện đã được bổ sung; xem [K8S-LAB.md](K8S-LAB.md) cho cách dựng, patch và ranh giới nghiệm thu. Các nhận xét “chưa chạy” bên dưới mô tả thời điểm audit ban đầu, không phải trạng thái triển khai mới.');p.write_text(s)
> p=Path('docs/BUILD-FROM-SCRATCH.md');s=p.read_text();s+='\n## Backend Kubernetes mới\n\nSau các patch source ở trên, backend minikube dùng thêm `patches/oai-upf-xdp-mode.patch` và chart baseline OAI có patch `patches/oai-charts-7925f93-lab.patch`. Hướng dẫn, mapping script và trạng thái nghiệm thu nằm trong [K8S-LAB.md](K8S-LAB.md). Backend này không gọi 5gdeploy; vẫn giữ source/Compose legacy để đối chiếu.\n';p.write_text(s)
> PY````
>
> - Ran `bash -c 'source scripts/lib/oai-upf-profile.sh; OAI_UPF_DATAPATH=xdp-skb; profile_validate_compose_capabilities /tmp/oai-caps.yml'; bash -c 'source scripts/lib/oai-upf-profile.sh; OAI_UPF_DATAPATH=xdp-skb; profile_validate_compose_capabilities compose/core/compose.yml'; tail -5 artifacts/k8s/radio-build.log; df -h .; cat artifacts/k8s/bootstrap-server.json; cat /tmp/oai-lab-build-cli.log | tail -4`
>
> - Ran `python3 - <<'PY'
> p='scripts/lib/oai-upf-profile.sh';s=open(p).read().replace('length > 0 and all','(length > 0) and (all)');open(p,'w').write(s)
> PY
> bash -c 'source scripts/lib/oai-upf-profile.sh; OAI_UPF_DATAPATH=xdp-skb; profile_validate_compose_capabilities /tmp/oai-caps.yml'`
>
> - Ran `CAPABILITY=NET_ADMIN yq eval '[.services[] | select((.image // "") | test("(?i)oai.*upf|upf.*oai")) | ((.cap_add // []) | contains([strenv(CAPABILITY)]))] | all' /tmp/oai-caps.yml
> python3 - <<'PY'
> p='scripts/lib/oai-upf-profile.sh';s=open(p).read().replace('(length > 0) and (all)','all');open(p,'w').write(s)
> PY
> bash -c 'source scripts/lib/oai-upf-profile.sh; OAI_UPF_DATAPATH=xdp-skb; profile_validate_compose_capabilities /tmp/oai-caps.yml'
> bash -c 'source scripts/lib/oai-upf-profile.sh; OAI_UPF_DATAPATH=xdp-skb; profile_validate_compose_capabilities compose/core/compose.yml'`
>
> - Ran `rg -n 'CORE=|UPF=' scripts/configure-core.sh | head -20; tail -6 artifacts/k8s/radio-build.log; rg -n 'server|listen|127.0.0.1|e2addr' src/flexric/src/ric/near_ric.c | head -16; du -sh /tmp/oai-lab-charts-7925f93`
>
> </details>
>
> Kiểm tra mạng đã **PASS thực tế**: hai pod giao tiếp được trên N2/N3/N4/N6/E2, SCTP và DNS hoạt động, không có default route trên mạng phụ. FlexRIC đã vượt qua lỗi ASN.1; build đang sang phần RAN. Mốc 1 còn việc hoàn tất image radio và xác nhận toàn bộ image có trong runtime minikube.
>
> <details><summary>Ran 10 commands</summary>
>
> - Ran `python3 - <<'PY'
> p='scripts/lib/oai-upf-profile.sh';s=open(p).read().replace('    # The generator must grant these when --oai-upf-bpf=true is passed.','''    if ! yq eval -e '[.services[] | select((.image // "") | test("(?i)oai.*upf|upf.*oai"))] | length > 0' "$compose_file" >/dev/null; then
>         echo "ERROR: No OAI UPF service in generated Compose." >&2
>         return 1
>     fi
>     # The generator must grant these when --oai-upf-bpf=true is passed.''');open(p,'w').write(s)
> p='tests/test_oai_upf_profile.sh';s=open(p).read();s+='''
> # Negative: enabling BPF in YAML without generated capabilities must fail.
> if profile_validate_compose_capabilities "$COMPOSE" 2>/dev/null; then
>     echo "Expected missing BPF capabilities to fail" >&2
>     exit 1
> fi
> yq eval -i '.services.upf1.cap_add = ["NET_ADMIN", "BPF", "SYS_ADMIN", "SYS_RESOURCE"]' "$COMPOSE"
> profile_validate_compose_capabilities "$COMPOSE"
> echo "Compose BPF capability gates passed."
> ''';open(p,'w').write(s)
> PY
> bash tests/test_oai_upf_profile.sh
> mkdir -p /tmp/oai-compose-migration-baseline
> src/5gdeploy/node_modules/.bin/tsx src/5gdeploy/scenario/orantestbed/scenario.ts --gnbs=1 --phones=0 --vehicles=0 > /tmp/oai-compose-migration-baseline/netdef.json
> corepack pnpm --dir src/5gdeploy -s netdef-compose --netdef=/tmp/oai-compose-migration-baseline/netdef.json --out=/tmp/oai-compose-migration-baseline --cp=oai --up=oai --ran=none --oai-upf-bpf=true > /tmp/oai-compose-generator.log 2>&1`
> - Ran `rg -n 'flexric|E2AP_VERSION|KPM_VERSION|BUILD_E2' src/oai-ran/openair2/E2AP/CMakeLists.txt src/oai-ran/CMakeLists.txt | head -35; ls src/oai-ran/openair2/E2AP; tail -6 artifacts/k8s/radio-build.log; tail -8 /tmp/oai-compose-generator.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods`
> - Ran `ls src/5gdeploy/node_modules/.bin | head -15; cat src/5gdeploy/package.json | head -28; readlink src/oai-ran/openair2/E2AP/flexric; ls src/oai-ran/openair2/E2AP/flexric | head; rg -n 'git|Cloning|ERROR|fatal' artifacts/k8s/radio-build.log | tail -8`
> - Ran `src/5gdeploy/node_modules/.bin/tsx src/5gdeploy/netdef-compose/main.ts --netdef=/tmp/oai-compose-migration-baseline/netdef.json --out=/tmp/oai-compose-migration-baseline --cp=oai --up=oai --ran=none --oai-upf-bpf=true > /tmp/oai-compose-generator.log 2>&1
> bash -c 'source scripts/lib/oai-upf-profile.sh; OAI_UPF_DATAPATH=xdp-skb; profile_validate_compose_capabilities /tmp/oai-compose-migration-baseline/compose.yml'
> command -v black; command -v ruff; tail -6 artifacts/k8s/radio-build.log`
> - Ran `minikube image ls --help | head -28; minikube image pull --help | head -24; docker image ls --format '{{.Repository}}:{{.Tag}}' | rg 'oai-(smf|amf|nrf|ausf|udm|udr)|mariadb'; tail -5 artifacts/k8s/radio-build.log`
> - Ran `python3 - <<'PY'
> p='deploy/k8s/images/Dockerfile.radio';s=open(p).read();s=s.replace('COPY src/flexric /source/flexric','RUN git clone https://github.com/mouse07410/asn1c /tmp/asn1c && cd /tmp/asn1c && git checkout 940dd5fa9f3917913fd487b13dfddfacd0ded06e && autoreconf -iv && CFLAGS="-O2 -fno-strict-aliasing" ./configure --prefix=/opt/asn1c && make -j2 && make install && rm -rf /tmp/asn1c\nENV PATH=/opt/asn1c/bin:$PATH\nCOPY src/flexric /source/flexric')
> open(p,'w').write(s)
> PY
> scripts/k8s/lab.sh build > /tmp/oai-lab-build-cli.log 2>&1`
> - Ran `python3 - <<'PY'
> p='scripts/k8s/lab.py';s=open(p).read();old="        self.credentials();self.helm();self.ready('db');self.ready('dn')"
> new="""        for image in [self.c['dbImage']]+[self.c['workloads'][nf]['image'] for nf in NFS[:6]]:
>             local=subprocess.run(['docker','image','inspect',image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
>             run(['minikube','--profile',PROFILE,'image','load' if local else 'pull',image],capture=False,timeout=600)
>         runtime_images=json.loads(run(['minikube','--profile',PROFILE,'ssh','--','sudo crictl images -o json']))
>         write_json(STATE/'node-images.json',runtime_images)
>         actual={tag.removeprefix('docker.io/').removeprefix('library/') for item in runtime_images['images'] for tag in item.get('repoTags',[])}
>         expected=[i['image'] for i in lock['images'].values()]+[self.c['dbImage']]+[self.c['workloads'][nf]['image'] for nf in NFS[:6]]
>         if any(tag not in actual for tag in expected):raise GateError('Required image missing in node runtime')
>         self.credentials();self.helm();self.ready('db');self.ready('dn')"""
> assert old in s;s=s.replace(old,new)
> open(p,'w').write(s)
> PY
> python3 - <<'PY'
> import json,yaml,pathlib
> p=pathlib.Path('artifacts/k8s/baseline/compose.json');c=json.loads(p.read_text());generated=yaml.safe_load(open('/tmp/oai-compose-migration-baseline/compose.yml'));c['generatorWithBpfFlag']={n:x['cap_add'] for n,x in generated['services'].items() if 'upf' in x.get('image','')};c['generatorCapabilityCheck']='PASS';p.write_text(json.dumps(c,indent=2)+'\n')
> PY
> python3 -m unittest discover -s tests/k8s -v > artifacts/k8s/unit-tests.log 2>&1
> bash tests/test_oai_upf_profile.sh > artifacts/k8s/compose-profile-tests.log 2>&1
> scripts/k8s/lab.sh check > artifacts/k8s/check.log 2>&1
> tail -5 artifacts/k8s/check.log; tail -5 artifacts/k8s/radio-build.log`
> - Ran `rg -n 'error:|Error|ERROR|FAILED|not found|No such|exit code' artifacts/k8s/radio-build.log | tail -15; tail -5 /tmp/oai-lab-build-cli.log; sed -n '12,27p' src/oai-ran/cmake_targets/build_oai; ls -lh src/oai-ran/cmake_targets/ran_build/build/nr-* 2>/dev/null | head`
> - Ran `cat >> deploy/k8s/chart/templates/bootstrap.yaml <<'EOF'
> {{- if .Values.bootstrapTestEnabled }}
> ---
> apiVersion: batch/v1
> kind: Job
> metadata: {name: oai-lab-bootstrap-upf-bpf}
> spec:
>   backoffLimit: 0
>   activeDeadlineSeconds: 120
>   template:
>     spec:
>       automountServiceAccountToken: false
>       restartPolicy: Never
>       containers:
>         - name: upf-bpf-probe
>           image: {{ .Values.global.lab.workloads.upf.image | quote }}
>           command: [/openair-upf/bin/bpftool, -j, feature, probe, kernel]
>           securityContext: {privileged: true}
>           resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 500m, memory: 256Mi}}
> {{- end }}
> EOF
> python3 - <<'PY'
> p='scripts/k8s/lab.py';s=open(p).read().replace("for side in ['server','client']:self.k('delete'","for side in ['server','client','upf-bpf']:self.k('delete'")
> s=s.replace("        write_json(STATE/'bootstrap.json',{'status':'PASS'", "        self.k('wait','--for=condition=complete','job/oai-lab-bootstrap-upf-bpf','--timeout=120s',capture=False)\n        bpf=json.loads(self.k('logs','job/oai-lab-bootstrap-upf-bpf'))\n        write_json(STATE/'bootstrap-bpf.json',bpf)\n        if not bpf.get('program_types',{}).get('have_xdp_prog_type'):raise GateError('Kernel cannot load XDP programs from UPF privileged pod')\n        write_json(STATE/'bootstrap.json',{'status':'PASS'")
> open(p,'w').write(s)
> PY
> python3 -m py_compile scripts/k8s/lab.py
> python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());l.bootstrap=True;l.helm()
> l.k('wait','--for=condition=complete','job/oai-lab-bootstrap-upf-bpf','--timeout=120s',capture=False)
> result=json.loads(l.k('logs','job/oai-lab-bootstrap-upf-bpf'));write_json(STATE/'bootstrap-bpf.json',result)
> print('XDP load permitted:',result.get('program_types',{}).get('have_xdp_prog_type'))
> PY`
> - Ran `tail -7 artifacts/k8s/radio-build.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get jobs; python3 - <<'PY'
> import json,pathlib
> p=pathlib.Path('artifacts/k8s/bootstrap-bpf.json')
> if p.exists():
>  c=json.loads(p.read_text());print('BPF XDP program load:', c.get('program_types',{}).get('have_xdp_prog_type'))
> PY
> patch -d /tmp/oai-lab-upf-before -p1 --dry-run < patches/oai-upf-xdp-mode.patch
> python3 -m unittest discover -s tests/k8s -q`
>
> </details>
>
> Probe BPF trong pod UPF privileged cũng đã **PASS khả năng load chương trình XDP** trên node minikube. Đây là kiểm tra quyền/kernel của Mốc 1; attach SKB thật vào N3/N6 vẫn thuộc Mốc 2. Mình đã thêm lệnh `up --stage bootstrap` để dừng rõ tại Mốc 1 và lưu các kết quả kiểm tra vào `artifacts/k8s/`.
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `tail -8 artifacts/k8s/radio-build.log; df -h .; rg -n 'PRIVATE|all$' scripts/lib/oai-upf-profile.sh | tail -5; ls /tmp/oai-lab-charts-7925f93`
> - Ran `python3 - <<'PY'
> p='deploy/k8s/chart/templates/_nf.tpl';s=open(p).read().replace("grep -qi ':0050 ' /proc/net/tcp /proc/net/tcp6", "awk '$2 ~ /:0050$/ && $4 == \\\"0A\\\" {ok=1} END {exit !ok}' /proc/net/tcp /proc/net/tcp6");open(p,'w').write(s)
> PY
> python3 -m unittest discover -s tests/k8s -q
> mkdir -p /tmp/oai-chart-pristine
> git -C /tmp/oai-lab-charts-7925f93 archive 7925f939ea36a3c4c1df5525f3718ce8470f6b3f | tar -xf - -C /tmp/oai-chart-pristine
> git -C /tmp/oai-chart-pristine apply --check /home/ducsssanh/6G/O-RAN/DATN/Codebase/patches/oai-charts-7925f93-lab.patch
> rg -n 'proto|parse|ipam' deploy/k8s/chart/templates/networks.yaml
> cat artifacts/k8s/baseline/compose.json | head -18`
> - Ran `head -45 README.md; tail -5 artifacts/k8s/radio-build.log; df -h .; free -m`
> - Ran `python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})())
> image=json.loads((STATE/'images.partial.json').read_text())['upf']['image']
> # Use the already loaded equivalent UPF image for this permission-only check.
> image=yaml.safe_load((STATE/'images.yaml').read_text())['global']['lab']['workloads']['upf']['image']
> job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':'oai-lab-negative-bpf'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':45,'template':{'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'containers':[{'name':'probe','image':image,'command':['/openair-upf/bin/bpftool','-j','feature','probe','kernel'],'securityContext':{'privileged':False,'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}}}
> l.k('apply','-f','-',data=json.dumps(job));l.k('wait','--for=condition=failed','job/oai-lab-negative-bpf','--timeout=60s')
> pods=json.loads(l.k('get','pods','-l','job-name=oai-lab-negative-bpf','-o','json'))['items']
> code=pods[0]['status']['containerStatuses'][0]['state']['terminated']['exitCode']
> log=l.k('logs','job/oai-lab-negative-bpf');write_json(STATE/'negative-bpf.json',{'test':'BPF without privileges must fail','status':'PASS' if code!=0 else 'FAIL','observedExitCode':code,'log':log})
> l.k('delete','job','oai-lab-negative-bpf')
> print('Unprivileged BPF correctly rejected:',code!=0)
> PY`
> - Ran `tail -5 artifacts/k8s/radio-build.log; cat artifacts/k8s/negative-bpf.json 2>/dev/null; ls docs | head -12; ls deploy/k8s/chart/charts`
> - Ran ``command -v uv; head -35 docs/README.md; sed -n '1,35p' deploy/k8s/images/Dockerfile.radio; python3 - <<'PY'
> from pathlib import Path
> p=Path('docs/README.md');s=p.read_text();s+='\n## Backend Kubernetes\n\nXem [K8S-LAB.md](K8S-LAB.md) cho backend minikube mới, lệnh `up --stage bootstrap`, các patch XDP/chart và bằng chứng theo mốc. Backend Compose vẫn được giữ để đối chiếu.\n';p.write_text(s)
> p=Path('docs/K8S-LAB.md');s=p.read_text().replace('Python 3 cùng PyYAML','Python 3.12+ cùng PyYAML').replace('Job không privileged. Kết quả','Hai Job mạng không privileged. Job `bootstrap-upf-bpf` dùng image UPF privileged để probe khả năng load BPF/XDP; đây chưa phải attach datapath N3/N6. Kết quả');p.write_text(s)
> PY``
> - Ran `uvx --from black==25.1.0 black scripts/k8s/lab.py scripts/k8s/analyze.py tests/k8s/test_lab.py deploy/k8s/chart/files/bootstrap.py > /tmp/oai-format.log 2>&1`
> - Ran `python3 - <<'PY'
> p='deploy/k8s/chart/templates/bootstrap.yaml';s=open(p).read().replace('securityContext: {privileged: true}','securityContext: {privileged: true, capabilities: {drop: [ALL], add: [NET_ADMIN, NET_RAW]}}');open(p,'w').write(s)
> p='docs/README.md';s=open(p).read().replace('Tài liệu phân biệt phần đã đối chiếu source, phần chưa thử build sạch, và thiết kế Kubernetes chưa triển khai. Snapshot hiện tại không có Git root; các lệnh tạo repo/cluster trong tài liệu chưa được chạy tự động.','Tài liệu audit cũ được giữ để đối chiếu nguồn. Backend Kubernetes mới và bằng chứng triển khai theo mốc được mô tả riêng trong K8S-LAB.md; chưa được suy diễn bootstrap thành nghiệm thu toàn stack. Snapshot hiện tại không có Git root.');open(p,'w').write(s)
> PY
> cat /tmp/oai-format.log
> python3 -m unittest discover -s tests/k8s -q
> python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());l.k('delete','job','oai-lab-bootstrap-upf-bpf');l.bootstrap=True;l.helm()
> l.k('wait','--for=condition=complete','job/oai-lab-bootstrap-upf-bpf','--timeout=120s')
> c=json.loads(l.k('logs','job/oai-lab-bootstrap-upf-bpf'));write_json(STATE/'bootstrap-bpf.json',c);print('BPF with actual UPF securityContext:',c['program_types']['have_xdp_prog_type'])
> PY`
>
> </details>
>
> Các kiểm tra chặn lỗi đã qua, gồm trường hợp BPF thiếu quyền phải thất bại. Mình cũng đã kiểm chứng generator Compose thực sự sinh đủ capability khi truyền cờ BPF. Hiện RAN đang biên dịch các thư viện giao thức; trong lúc chờ, mình kiểm tra thêm quyền mở TUN của UE để tránh chốt bootstrap khi pod UE vẫn thiếu thiết bị cần thiết.
>
> <details><summary>Edited 2 files, ran 8 commands</summary>
>
> - Ran `cat >> deploy/k8s/chart/templates/bootstrap.yaml <<'EOF'
> {{- if .Values.bootstrapTestEnabled }}
> ---
> apiVersion: batch/v1
> kind: Job
> metadata: {name: oai-lab-bootstrap-ue-tun}
> spec:
>   backoffLimit: 0
>   activeDeadlineSeconds: 60
>   template:
>     spec:
>       automountServiceAccountToken: false
>       restartPolicy: Never
>       containers:
>         - name: ue-tun-probe
>           image: {{ .Values.global.lab.toolsImage | quote }}
>           command: [python3, -c]
>           args:
>             - 'import os,fcntl,struct,json; fd=os.open("/dev/net/tun",os.O_RDWR); fcntl.ioctl(fd,0x400454ca,struct.pack("16sH",b"oai-probe",0x1001)); os.close(fd); print(json.dumps({"status":"PASS","tun":True,"privileged":False}))'
>           securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL], add: [NET_ADMIN]}}
>           resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 250m, memory: 128Mi}}
>           volumeMounts: [{name: tun, mountPath: /dev/net/tun}]
>       volumes:
>         - name: tun
>           hostPath: {path: /dev/net/tun, type: CharDevice}
> {{- end }}
> EOF
> python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());l.bootstrap=True;l.helm()
> l.k('wait','--for=condition=complete','job/oai-lab-bootstrap-ue-tun','--timeout=60s')
> (STATE/'bootstrap-tun.json').write_text(l.k('logs','job/oai-lab-bootstrap-ue-tun'))
> PY`
> - Ran `tail -5 artifacts/k8s/radio-build.log; cat artifacts/k8s/bootstrap-tun.json 2>/dev/null; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get jobs; rg -n 'upf-bpf|bootstrap.json|stage ==|image load' scripts/k8s/lab.py | tail -18`
> - Wrote `./scripts/k8s/lab.py` (+9 -1)
> - Wrote `./deploy/k8s/chart/files/bootstrap.py` (+1 -0)
> - Ran `python3 -m unittest discover -s tests/k8s -q
> bash -n scripts/k8s/lab.sh deploy/k8s/images/radio-entrypoint.sh scripts/configure-core.sh scripts/lib/oai-upf-profile.sh
> helm template oai-lab deploy/k8s/chart -f deploy/k8s/values/minikube.yaml --set oai-nrf.enabled=true,oai-udr.enabled=true,oai-udm.enabled=true,oai-ausf.enabled=true,oai-amf.enabled=true,oai-smf.enabled=true,oai-upf.enabled=true,oai-flexric.enabled=true,oai-gnb.enabled=true,oai-nr-ue.enabled=true,seedEnabled=true,xappEnabled=true,bootstrapTestEnabled=true > artifacts/k8s/rendered-all.yaml
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab apply --dry-run=server -f artifacts/k8s/rendered-all.yaml > artifacts/k8s/server-validation.log 2>&1
> tail -4 artifacts/k8s/server-validation.log`
> - Ran ``tail -5 artifacts/k8s/radio-build.log; tail -5 artifacts/k8s/server-validation.log; df -h .; cat >> docs/LOCAL-PATCHES.md <<'EOF'
>
> ## Patch phát sinh khi thêm backend Kubernetes
>
> - `patches/oai-upf-xdp-mode.patch`: patch local mới, áp dụng sau URR `00b7485`; thêm YAML XDP mode và teardown có kiểm tra ownership. Không nằm trong source OAI baseline đã pin.
> - `patches/oai-charts-7925f93-lab.patch`: patch local mới trên chart OAI commit `7925f939ea36a3c4c1df5525f3718ce8470f6b3f`; thêm nhánh deployment/config/network cho umbrella lab. Các file `deploy/k8s/chart`, `deploy/k8s/images`, `scripts/k8s`, `tests/k8s` là implementation tích hợp mới, không phải file nguyên bản OAI.
> - `scripts/configure-core.sh` truyền cờ BPF cho generator; `scripts/lib/oai-upf-profile.sh` kiểm tra capability sinh ra. Các thay đổi này thuộc backend Compose để đối chiếu, không được backend Kubernetes gọi.
>
> Xem [K8S-LAB.md](K8S-LAB.md) cho provenance và bằng chứng theo mốc.
> EOF
> uvx --from black==25.1.0 black scripts/k8s/lab.py >/tmp/oai-format.log 2>&1``
> - Ran `mv artifacts/k8s/server-validation.log artifacts/k8s/server-validation-first-failure.log
> helm template oai-lab deploy/k8s/chart -f deploy/k8s/values/minikube.yaml -f artifacts/k8s/images.yaml --set oai-nrf.enabled=true,oai-udr.enabled=true,oai-udm.enabled=true,oai-ausf.enabled=true,oai-amf.enabled=true,oai-smf.enabled=true,oai-upf.enabled=true,oai-flexric.enabled=true,oai-gnb.enabled=true,oai-nr-ue.enabled=true,seedEnabled=true,xappEnabled=true,bootstrapTestEnabled=true > artifacts/k8s/rendered-all.yaml
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab apply --dry-run=server -f artifacts/k8s/rendered-all.yaml > artifacts/k8s/server-validation.log 2>&1`
> - Ran `sed -n '20,75p' src/oai-upf/src/upf_app/app/upf_config_yaml.cpp; rg -n 'xdp_mode|support_features' src/oai-upf/src/upf_app/app/upf_config_yaml.cpp | tail -15; tail -4 artifacts/k8s/radio-build.log; tail -2 artifacts/k8s/server-validation.log; cat /tmp/oai-format.log`
> - Ran `python3 - <<'PY'
> import yaml,pathlib,subprocess,json
> cm=next(d for d in yaml.safe_load_all(open('artifacts/k8s/rendered-all.yaml')) if d and d['kind']=='ConfigMap' and d['metadata']['name']=='oai-lab-config')
> c=yaml.safe_load(cm['data']['config.yaml']);c['upf']['support_features']['xdp_mode']='invalid-mode'
> p=pathlib.Path('/tmp/oai-invalid-xdp.yaml');p.write_text(yaml.safe_dump(c))
> image=json.load(open('artifacts/k8s/images.partial.json'))['upf']['image']
> r=subprocess.run(['docker','run','--rm','--network=none','--cap-drop=ALL','--mount','type=bind,src='+str(p)+',dst=/config.yaml,readonly','--entrypoint','/openair-upf/bin/oai_upf',image,'-c','/config.yaml','-o'],text=True,capture_output=True,timeout=30)
> log=r.stdout+r.stderr
> pathlib.Path('artifacts/k8s/invalid-xdp.log').write_text(log)
> result={'status':'PASS' if r.returncode!=0 and 'xdp_mode must be' in log else 'FAIL','exitCode':r.returncode,'test':'actual UPF binary rejects invalid YAML mode before BPF loading'}
> pathlib.Path('artifacts/k8s/invalid-xdp.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
> PY`
> - Wrote `./scripts/k8s/lab.py` (+5 -2)
> - Ran `python3 - <<'PY'
> import yaml,pathlib,subprocess,json
> v=yaml.safe_load(open('deploy/k8s/values/minikube.yaml'));v['global']['lab']['networks']['n3']=v['global']['lab']['networks']['n4'].copy()
> p=pathlib.Path('/tmp/oai-conflicting-networks.yaml');p.write_text(yaml.safe_dump(v))
> r=subprocess.run(['scripts/k8s/lab.sh','check','--values',str(p)],text=True,capture_output=True)
> result={'test':'CLI rejects overlapping networks before deployment','status':'PASS' if r.returncode!=0 and 'Overlapping' in r.stderr else 'FAIL','exitCode':r.returncode,'log':r.stderr}
> pathlib.Path('artifacts/k8s/negative-subnet.json').write_text(json.dumps(result,indent=2)+'\n');print(result['status'])
> PY
> python3 -m unittest discover -s tests/k8s -q
> tail -4 artifacts/k8s/radio-build.log`
>
> </details>
>
> UE đã tạo được TUN với `NET_ADMIN`, không cần privileged. Binary UPF cũng đã từ chối đúng cấu hình XDP mode sai; kiểm tra subnet trùng trả exit code lỗi trước triển khai. UE đã build xong, hiện đang build gNB với E2AP v3/KPM v3; sau đó mình sẽ chạy lại toàn bộ bootstrap bằng bộ image cuối cùng.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `tail -5 artifacts/k8s/radio-build.log; df -h .; rg -n 'def build|sourceHash|images.json' scripts/k8s/lab.py | head -12; ls -l deploy/k8s/images/radio-entrypoint.sh; git -C /tmp/oai-chart-pristine apply --check /home/ducsssanh/6G/O-RAN/DATN/Codebase/patches/oai-charts-7925f93-lab.patch`
> - Ran `rg -n 'include_dir|set_include' src/oai-ran/common/config; rg -n 'cd |softmodem' scripts/start-gnb.sh | tail -12; tail -3 artifacts/k8s/radio-build.log; rg -n 'Error|error:' artifacts/k8s/server-validation.log | head -3; sed -n '298,312p' scripts/k8s/lab.py`
> - Ran `sed -n '159,172p' deploy/k8s/chart/files/gnb.conf.tpl; cat deploy/k8s/chart/Chart.lock | head -25; sed -n '410,424p' scripts/k8s/lab.py; tail -4 artifacts/k8s/radio-build.log; df -h .`
> - Ran `python3 - <<'PY'
> p='deploy/k8s/images/Dockerfile.radio';s=open(p).read().replace('./build_oai -I -w SIMU && ./build_oai','./build_oai --ninja -I -w SIMU\nRUN cd /source/ran/cmake_targets && ./build_oai');open(p,'w').write(s)
> PY
> scripts/k8s/lab.sh build > /tmp/oai-lab-build-cli.log 2>&1`
> - Ran `cat >> deploy/k8s/chart/templates/bootstrap.yaml <<'EOF'
> {{- if .Values.bootstrapTestEnabled }}
> ---
> apiVersion: batch/v1
> kind: Job
> metadata: {name: oai-lab-bootstrap-radio}
> spec:
>   backoffLimit: 0
>   activeDeadlineSeconds: 60
>   template:
>     spec:
>       automountServiceAccountToken: false
>       restartPolicy: Never
>       containers:
>         - name: radio-probe
>           image: {{ .Values.global.lab.workloads.gnb.image | quote }}
>           command: [sh, -ec]
>           args:
>             - |
>               for binary in nr-softmodem nr-uesoftmodem nearRT-RIC xapp_kpm_moni_write_to_csv; do
>                 test -x "/opt/oai/bin/$binary"
>                 ldd "/opt/oai/bin/$binary" > /tmp/ldd.txt
>                 if grep -q 'not found' /tmp/ldd.txt; then cat /tmp/ldd.txt; exit 1; fi
>               done
>               test -r /opt/oai/sm/libkpm_sm.so
>               test -r /source/flexric/build/28_552_kpm_meas.txt
>               for library in /opt/oai/sm/*.so /opt/oai/ran/*.so; do
>                 ldd "$library" > /tmp/ldd.txt
>                 if grep -q 'not found' /tmp/ldd.txt; then cat /tmp/ldd.txt; exit 1; fi
>               done
>               echo '{"status":"PASS","binaries":4,"sharedLibraries":"resolved"}'
>           securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
>           resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 500m, memory: 256Mi}}
> {{- end }}
> EOF
> python3 - <<'PY'
> p='scripts/k8s/lab.py';s=open(p).read().replace('["server", "client", "upf-bpf", "ue-tun"]','["server", "client", "upf-bpf", "ue-tun", "radio"]');mark='        write_json(STATE / "bootstrap-tun.json", tun)';s=s.replace(mark,mark+'''
>         self.k("wait", "--for=condition=complete", "job/oai-lab-bootstrap-radio", "--timeout=60s", capture=False)
>         radio = json.loads(self.k("logs", "job/oai-lab-bootstrap-radio"))
>         if radio.get("status") != "PASS":
>             raise GateError("Radio image has unresolved binaries/libraries")
>         write_json(STATE / "bootstrap-radio.json", radio)
>         write_json(STATE / "source-provenance.json", {
>             "commits": {p.stem: p.read_text().strip() for p in (ROOT / "manifests").glob("*.commit")},
>             "patchSha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "patches").glob("*.patch")},
>             "chart": json.loads((DEPLOY / "vendor/PROVENANCE.json").read_text()),
>         })''');open(p,'w').write(s)
> PY
> uvx --from black==25.1.0 black scripts/k8s/lab.py >/tmp/oai-format.log 2>&1
> python3 -m unittest discover -s tests/k8s -q
> tail -4 artifacts/k8s/radio-build.log`
>
> </details>
>
> Cả ba image tools, UPF và radio đã build thành công từ source local. Mình đang chạy `up --stage bootstrap` bằng các tag cuối cùng: nạp image vào containerd, kiểm tra lại mạng/BPF/TUN và kiểm tra thư viện động của gNB, UE, FlexRIC, xApp. Bước này sẽ quyết định Mốc 1 có đủ điều kiện chốt hay chưa.
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `tail -12 artifacts/k8s/bootstrap-run.log; df -h .; minikube --profile oai-lab image ls --format json | head -c 450`
> - Ran ``python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})())
> secret=[REDACTED_SECRET]'get','secret',l.c['secretName'],'-o','json'))['data']
> vals={k:base64.b64decode(v).decode() for k,v in secret.items()}
> assert re.fullmatch(r'\d{15}',vals['IMSI']) and vals['IMSI'].startswith(l.c['plmn']['mcc']+l.c['plmn']['mnc'])
> assert all(re.fullmatch(r'[0-9a-fA-F]{32}',vals[k]) for k in ('KEY','OPC'))
> assert vals['DB_PASSWORD'] and vals['DB_ROOT_PASSWORD']
> write_json(STATE/'subscriber-secret-check.json',{'status':'PASS','plmnMatch':True,'simFieldFormats':True,'credentialsLogged':False,'authenticationRuntime':'NOT_TESTED'})
> print('Subscriber Secret format/PLMN verified; values withheld')
> PY
> python3 -m unittest discover -s tests/k8s -v > artifacts/k8s/unit-tests.log 2>&1
> bash tests/test_oai_upf_profile.sh > artifacts/k8s/compose-profile-tests.log 2>&1
> g++ -std=c++17 -Isrc/oai-upf/src/upf_app/include tests/k8s/xdp_mode.cpp -o /tmp/oai-xdp-mode-test && /tmp/oai-xdp-mode-test
> python3 - <<'PY'
> from pathlib import Path
> p=Path('docs/K8S-LAB.md');s=p.read_text().replace('Các giai đoạn này đang cần nghiệm thu runtime; lỗi trả exit code khác 0.','Các giai đoạn này đang cần nghiệm thu runtime; lỗi trả exit code khác 0. `up` tái đồng bộ release theo thứ tự và có thể tái tạo session, vì vậy không gọi trong lúc đang chạy experiment.');p.write_text(s)
> PY
> tail -8 artifacts/k8s/bootstrap-run.log; df -h .``
> - Ran `rg -n 'def host_check|required =|disk_usage|def build' scripts/k8s/lab.py | head -12; sed -n '123,145p' scripts/k8s/lab.py; sed -n '245,255p' scripts/k8s/lab.py; tail -8 artifacts/k8s/bootstrap-run.log; df -h .`
> - Ran `ps -eo pid,etime,args | rg 'minikube.*image|lab.py up' | head -10; minikube --profile oai-lab image ls | rg 'oai-lab-radio|oai-smf|mariadb'; tail -5 artifacts/k8s/bootstrap-run.log`
> - Ran `tail -12 artifacts/k8s/bootstrap-run.log; df -h .; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods; cat artifacts/k8s/images.json | head -24`
> - Ran `ps -eo pid,ppid,etime,pcpu,args | rg '416927|ctr.*import|docker.*save|gzip|gunzip|image load' | head -15; docker exec oai-lab ps -eo pid,etime,pcpu,args | rg 'ctr|import|tar|gzip' | head -12; minikube --profile oai-lab image ls | rg 'oai-lab-radio|oai-lab-tools:b7'`
>
> </details>
>
> API server đã chấp nhận toàn bộ manifest qua kiểm tra `dry-run`; không còn lỗi schema. Image radio khoảng 3,9 GB nên bước nạp vào minikube đang mất thêm thời gian. Các probe cuối sẽ chạy trên chính image này, thay vì chỉ dựa vào việc Docker build thành công.
>
> <details><summary>Edited a file, ran 6 commands</summary>
>
> - Ran `tail -10 artifacts/k8s/bootstrap-run.log; ps -eo etime,pcpu,args | rg '^ .*minikube --profile oai-lab image load' | head -3; df -h .`
> - Ran `sed -n '195,247p' scripts/k8s/lab.py; sed -n '604,630p' scripts/k8s/lab.py; tail -5 artifacts/k8s/bootstrap-run.log`
> - Wrote `./scripts/k8s/lab.py` (+4 -4)
> - Ran `uvx --from black==25.1.0 black scripts/k8s/lab.py >/tmp/oai-format.log 2>&1
> python3 -m unittest discover -s tests/k8s -q
> ps -eo etime,pcpu,args | rg 'minikube --profile oai-lab image load' | head -2; df -h .`
> - Ran `docker run --rm --network=none --cap-drop=ALL --entrypoint sh oai-lab-radio:b715742212936699 -ec 'for binary in nr-softmodem nr-uesoftmodem nearRT-RIC xapp_kpm_moni_write_to_csv; do test -x /opt/oai/bin/$binary; ldd /opt/oai/bin/$binary > /tmp/ldd.txt; if grep -q "not found" /tmp/ldd.txt; then cat /tmp/ldd.txt; exit 1; fi; done; for library in /opt/oai/sm/*.so /opt/oai/ran/*.so; do ldd "$library" > /tmp/ldd.txt; if grep -q "not found" /tmp/ldd.txt; then cat /tmp/ldd.txt; exit 1; fi; done; echo radio-shared-libraries-ok' > artifacts/k8s/radio-smoke-host.log 2>&1
> tail -3 artifacts/k8s/radio-smoke-host.log; tail -7 artifacts/k8s/bootstrap-run.log; df -h .`
> - Wrote `./scripts/k8s/lab.py` (+23 -3)
> - Ran `python3 - <<'PY'
> from pathlib import Path
> for name in ['deploy/k8s/values/minikube.yaml','deploy/k8s/chart/values.yaml']:
>  p=Path(name);s=p.read_text().replace('    minDiskGiB: 25','    minDiskGiB: 25\n    minRetainedDiskGiB: 5');p.write_text(s)
> p=Path('docs/K8S-LAB.md');s=p.read_text().replace('Build lần đầu có thể cần nhiều hơn tùy cache.','Build lần đầu có thể cần nhiều hơn tùy cache. Sau khi tất cả image đã có trong runtime của cluster giữ lại, preflight tái triển khai chỉ yêu cầu 5 GiB trống cho dữ liệu/log; một lần build mới vẫn yêu cầu 25 GiB. CLI kiểm tra image trong node để phân biệt hai trường hợp, không tự xóa cache.');p.write_text(s)
> PY
> uvx --from black==25.1.0 black scripts/k8s/lab.py >/tmp/oai-format.log 2>&1
> python3 -m unittest discover -s tests/k8s -q
> tail -7 artifacts/k8s/bootstrap-run.log; df -h .`
> - Ran `tail -5 /tmp/oai-lab-build-cli.log; docker image inspect oai-lab-radio:b715742212936699 --format '{{.Size}}'; df -h .; scripts/k8s/lab.sh up --stage bootstrap > artifacts/k8s/bootstrap-run.log 2>&1`
>
> </details>
>
> System error
>
> You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at Sep 27th, 2026 3:07 AM.
</details>

> ở chỗ dừng lại là đã làm đến mốc nào của plan rồi? tiếp tục hoàn thành mốc đó

<details><summary>2 previous messages</summary>

> Vẫn đang chốt **Mốc 1 — Render và bootstrap**. So với lần dừng trước, toàn bộ image đã build và nạp vào minikube; CLI đang triển khai lại các probe bằng bộ image cuối cùng. Mình tiếp tục đến khi các probe này hoàn tất và lưu báo cáo Mốc 1, chưa chuyển sang chạy toàn core ở Mốc 2.
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `tail -22 artifacts/k8s/bootstrap-run.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods,jobs; ls artifacts/k8s/bootstrap.json`
> - Ran `scripts/k8s/lab.sh check > artifacts/k8s/check.log 2>&1
> scripts/k8s/lab.sh status > artifacts/k8s/status.txt 2>&1
> python3 -m unittest discover -s tests/k8s -v > artifacts/k8s/unit-tests.log 2>&1
> bash tests/test_oai_upf_profile.sh > artifacts/k8s/compose-profile-tests.log 2>&1
> python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})())
> (STATE/'bootstrap-pods.json').write_text(l.k('get','pods','-o','json'))
> (STATE/'bootstrap-values.yaml').write_text(run(H+['get','values',PROFILE,'-o','yaml']))
> (STATE/'bootstrap-manifest.yaml').write_text(run(H+['get','manifest',PROFILE]))
> current=run(['kubectl','--context',PROFILE,'config','current-context']).strip()
> assert current=='kubernetes-admin@kubernetes'
> write_json(STATE/'context-isolation.json',{'labContext':PROFILE,'currentContext':current,'defaultContextPreserved':True})
> write_json(STATE/'milestones.json',{
>  'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
>  'milestone0':{'status':'PARTIAL','composeGeneratorCapabilities':'PASS','composeRuntimeBaseline':'NOT_RUN','evidence':'baseline/compose.json'},
>  'milestone1':{'status':'COMPLETE','bootstrap':'PASS','imageBuild':'PASS','helmLint':'PASS','apiServerDryRun':'PASS','secondaryNetworks':'PASS','dns':'PASS','sctp':'PASS','bpfLoadPermission':'PASS','unprivilegedUeTun':'PASS','radioLibraries':'PASS','unitTests':13,'evidence':['bootstrap.json','bootstrap-client.json','bootstrap-server.json','bootstrap-bpf.json','bootstrap-tun.json','bootstrap-radio.json','images.json','node-images.json','source-provenance.json']},
>  'milestone2':{'status':'NOT_ACCEPTED','note':'Database/DN infrastructure present; complete core and PFCP/SKB attachment not yet accepted'},
>  'milestone3':{'status':'NOT_RUN'},'milestone4':{'status':'NOT_RUN'},'migrationComplete':False})
> print('Milestone 1 COMPLETE. Default context preserved.')
> PY`
> - Ran `tail -6 artifacts/k8s/check.log; cat artifacts/k8s/bootstrap-radio.json; cat artifacts/k8s/milestones.json | head -18; cat artifacts/k8s/context-isolation.json
> helm --kube-context oai-lab --namespace oai-lab template oai-lab deploy/k8s/chart -f deploy/k8s/values/minikube.yaml -f artifacts/k8s/images.yaml --set oai-nrf.enabled=true,oai-udr.enabled=true,oai-udm.enabled=true,oai-ausf.enabled=true,oai-amf.enabled=true,oai-smf.enabled=true,oai-upf.enabled=true,oai-flexric.enabled=true,oai-gnb.enabled=true,oai-nr-ue.enabled=true,seedEnabled=true,xappEnabled=true,bootstrapTestEnabled=true > artifacts/k8s/rendered-all.yaml
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab apply --dry-run=server -f artifacts/k8s/rendered-all.yaml > artifacts/k8s/server-validation.log 2>&1`
> - Ran ``python3 - <<'PY'
> from pathlib import Path
> p=Path('docs/K8S-LAB.md');s=p.read_text();needle='## Phạm vi và trạng thái\n';s=s.replace(needle,needle+'\n**Mốc 1 đã hoàn tất ngày 26/09/2026.** Build image, Helm lint/render và server dry-run đã qua; cả 5 Job bootstrap (hai đầu mạng, BPF, TUN, radio libraries) đã Completed trên `oai-lab`. Bằng chứng: [milestones.json](../artifacts/k8s/milestones.json), [bootstrap.json](../artifacts/k8s/bootstrap.json), [image lock](../artifacts/k8s/images.json). Context mặc định vẫn là `kubernetes-admin@kubernetes`.\n\nMốc 0 đã sửa/kiểm chứng capability generator Compose, nhưng chưa có baseline traffic Compose. Mốc 2–4 chưa được nghiệm thu. Lần thử seed ban đầu phát hiện lỗi tách SQL comment; file schema đã được sửa, việc seed/authentication thực tế được kiểm chứng tiếp ở Mốc 2.\n')
> s=s.replace('Job `bootstrap-upf-bpf` dùng image UPF privileged','Job `bootstrap-radio` kiểm tra bốn binary và dependency thư viện; Job `bootstrap-ue-tun` thực sự tạo rồi đóng TUN với NET_ADMIN. Job `bootstrap-upf-bpf` dùng image UPF privileged')
> s+='\nCác kiểm thử nhánh lỗi thiếu image/SMF chưa ready/xApp không có mẫu trong `tests/k8s` là unit test, không thay thế nghiệm thu NF thật. Có bằng chứng runtime riêng cho BPF thiếu quyền, YAML XDP mode sai và CLI từ chối subnet trùng trong `artifacts/k8s/negative-bpf.json`, `invalid-xdp.json`, `negative-subnet.json`.\n'
> p.write_text(s)
> PY
> cat artifacts/k8s/preflight.json | head -12
> python3 - <<'PY'
> import json,pathlib
> root=pathlib.Path('artifacts/k8s')
> for name in ['bootstrap.json','bootstrap-client.json','bootstrap-server.json','bootstrap-tun.json','bootstrap-radio.json','negative-bpf.json','invalid-xdp.json','negative-subnet.json','source-provenance.json','node-images.json']:
>  p=root/name;d=json.loads(p.read_text());print(name,d.get('status','recorded'))
> PY
> ps -eo args | rg '^python3 .*/scripts/k8s/lab.py (build|up)'``
>
> </details>
</details>

Lần dừng trước đang ở **Mốc 1 — Render và bootstrap**. **Mốc này hiện đã hoàn tất.**

- Build thành công image tools, UPF, gNB/UE/FlexRIC/xApp; đã nạp vào minikube.
- Helm lint/render và kiểm tra manifest qua API server đều PASS.
- Cả **5 Job bootstrap PASS**: mạng phụ, DNS/SCTP, quyền load BPF, TUN không privileged và thư viện radio.
- Context mặc định vẫn là `kubernetes-admin@kubernetes`.

Đã lưu [báo cáo từng mốc](artifacts/k8s/milestones.json) và [hướng dẫn triển khai](docs/K8S-LAB.md).

**Mốc 2–4 chưa nghiệm thu**: chưa xác nhận attach SKB trên N3/N6, session UE, traffic UL/DL, URR và KPM. Baseline traffic Compose của Mốc 0 cũng còn thiếu.

> sao folder /artifact/k8s có nhiều file .json và .yaml trông lộn xộn quá. phần k8s đang được implement thế nào trong codebase? có cách nào chia folder lại phần này không

<details><summary>4 previous messages</summary>

> Mình sẽ kiểm tra cách CLI đang tạo artifact, rồi chia lại theo nhóm: trạng thái dùng để chạy lab, kết quả kiểm thử, log build và snapshot triển khai. Đồng thời mình sẽ giải thích rõ phần nào là cấu hình nguồn, phần nào chỉ là file sinh ra.
>
> <details><summary>Explored a search, 3 lists, ran 2 commands</summary>
>
> <details><summary>Explored a search, 3 lists</summary>
>
> - Listed files
> - Listed files in `k8s`
> - Searched for `STATE|artifacts/k8s` in `lab.py`
> - Listed files in `k8s`
>
> </details>
>
> - Ran `for p in /AGENTS.md /home/AGENTS.md /home/ducsssanh/AGENTS.md /home/ducsssanh/6G/AGENTS.md /home/ducsssanh/6G/O-RAN/AGENTS.md /home/ducsssanh/6G/O-RAN/DATN/AGENTS.md; do if [ -f "$p" ]; then cat "$p"; fi; done
> sed -n '1,55p' scripts/k8s/lab.py; sed -n '295,320p' scripts/k8s/lab.py; cat artifacts/k8s/milestones.json; sed -n '42,65p' tests/k8s/test_lab.py
> rg -n 'artifacts/k8s|bootstrap-server.json' docs scripts tests --glob '!*.pyc'`
>
> - Ran `cat > /tmp/reorganize-k8s-artifacts.py <<'PY'
> import ast,pathlib
> p=pathlib.Path('scripts/k8s/lab.py');s=p.read_text();tree=ast.parse(s);lines=s.splitlines(True);offsets=[0]
> for line in lines:offsets.append(offsets[-1]+len(line))
> edits=[]
> for node in ast.walk(tree):
>  if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Div) and isinstance(node.left,ast.Name) and node.left.id=='STATE':
>   edits.append((offsets[node.lineno-1]+node.col_offset,offsets[node.end_lineno-1]+node.end_col_offset,'artifact_path('+ast.get_source_segment(s,node.right)+')'))
> for start,end,replacement in sorted(edits,reverse=True):s=s[:start]+replacement+s[end:]
> helper='''
> # Stable CLI inputs are separate from generated evidence and diagnostic logs.
> ARTIFACT_GROUPS = {
>     "state": ("images.json", "images.yaml", "current-run"),
>     "build": ("images.partial.json", "source-provenance.json", "tools-build.log", "upf-build.log", "radio-build.log"),
>     "bootstrap": (
>         "bootstrap.json", "bootstrap-bpf.json", "bootstrap-client.json",
>         "bootstrap-server.json", "bootstrap-tun.json", "bootstrap-radio.json",
>         "bootstrap-manifest.yaml", "bootstrap-pods.json", "bootstrap-values.yaml",
>         "bootstrap-run.log", "node-images.json", "context-isolation.json",
>     ),
>     "checks": (
>         "check.log", "preflight.json", "rendered.yaml", "rendered-all.yaml",
>         "server-validation.log", "server-validation-first-failure.log",
>         "unit-tests.log", "compose-profile-tests.log", "invalid-xdp.json",
>         "invalid-xdp.log", "negative-bpf.json", "negative-subnet.json",
>         "radio-smoke-host.log", "subscriber-secret-check.json",
>     ),
>     "diagnostics": ("last-failure.json", "status.txt"),
> }
> ARTIFACT_LOCATIONS = {
>     name: pathlib.Path(group) / name
>     for group, names in ARTIFACT_GROUPS.items() for name in names
> }
>
>
> def artifact_path(name):
>     """Resolve an artifact without silently creating new files at the root."""
>     return STATE / ARTIFACT_LOCATIONS[name]
>
>
> def prepare_artifact_dirs():
>     for group in ARTIFACT_GROUPS:
>         (STATE / group).mkdir(parents=True, exist_ok=True)
>
> '''
> s=s.replace('class GateError(RuntimeError):',helper+'\nclass GateError(RuntimeError):')
> s=s.replace('    def __init__(self, args):\n','    def __init__(self, args):\n        prepare_artifact_dirs()\n')
> s=s.replace('; see artifacts/k8s/','; see artifacts/k8s/build/')
> p.write_text(s)
> PY
> python3 /tmp/reorganize-k8s-artifacts.py
> python3 - <<'PY'
> import sys,pathlib,hashlib,json
> sys.path.insert(0,'scripts/k8s');import lab
> files=[p for p in lab.STATE.iterdir() if p.is_file() and p.name not in ['milestones.json','README.md']]
> # Validate every destination before moving anything; never overwrite old evidence.
> for p in files:
>  dest=lab.artifact_path(p.name)
>  if dest.exists():raise RuntimeError('Destination exists: '+str(dest))
> before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
> lab.prepare_artifact_dirs()
> for p in files:p.rename(lab.artifact_path(p.name))
> assert all(hashlib.sha256(lab.artifact_path(n).read_bytes()).hexdigest()==h for n,h in before.items())
> p=lab.STATE/'milestones.json';c=json.loads(p.read_text())
> c['milestone1']['evidence']=[str(lab.ARTIFACT_LOCATIONS.get(n,n)) for n in c['milestone1']['evidence']]
> p.write_text(json.dumps(c,indent=2)+'\n')
> print('Moved and checksum-verified',len(files),'files; milestone evidence links updated.')
> PY
> uvx --from black==25.1.0 black scripts/k8s/lab.py >/tmp/k8s-artifact-format.log 2>&1
> rg -n 'STATE /|artifact_path' scripts/k8s/lab.py`
>
> </details>
>
> Nguyên nhân là CLI đang ghi chung cả file đầu vào cần giữ (`images.yaml`, image lock) lẫn log và bằng chứng kiểm thử vào một thư mục. Mình đã chuyển 35 file vào các nhóm riêng, kiểm tra checksum để bảo đảm nội dung không đổi, và sửa CLI để các lần chạy sau cũng ghi đúng chỗ.
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran ``cat > artifacts/k8s/README.md <<'EOF'
> # Artifact Kubernetes lab
>
> Bắt đầu từ [milestones.json](milestones.json) để xem tiến độ nghiệm thu.
> Đây là dữ liệu sinh ra khi build/kiểm tra/triển khai; cấu hình nguồn ở
> [deploy/k8s](../../deploy/k8s), hướng dẫn ở [K8S-LAB.md](../../docs/K8S-LAB.md).
>
> | Thư mục | Nội dung | CLI dùng lại? |
> |---|---|---|
> | `state/` | `images.json` khóa tag/ID/hash source; `images.yaml` override image cho Helm; `current-run` khi có thí nghiệm | Có, cần giữ để chạy `up` |
> | `build/` | Log build tools/UPF/radio, kết quả build dở và provenance source/patch/chart | Chủ yếu để đối chiếu; `images.partial.json` không phải lock hoàn chỉnh |
> | `bootstrap/` | Kết quả probe, snapshot manifest/pod/values/image trong node, log bootstrap và kiểm tra context | Bằng chứng Mốc 1 |
> | `checks/` | Preflight, manifest render, lint/test/validation và các kiểm thử âm | Bằng chứng kiểm tra |
> | `diagnostics/` | Lỗi gần nhất và snapshot status | Chẩn đoán; lỗi lịch sử không có nghĩa lab hiện vẫn lỗi |
> | `baseline/` | Đối chiếu Compose | Bằng chứng baseline |
>
> - JSON: dữ liệu máy đọc được (kết quả, image ID, trạng thái).
> - YAML: cấu hình Helm sinh ra hoặc snapshot manifest/values để đối chiếu.
> - LOG/TXT: đầu ra lệnh và log chẩn đoán.
>
> Muốn sửa topology/config: sửa `deploy/k8s/values/minikube.yaml` hoặc chart nguồn.
> `state/images.yaml` được `lab.sh build` sinh ra; không sửa snapshot trong `bootstrap/`
> hoặc manifest trong `checks/` để cấu hình deployment.
>
> Các file ở đây chủ yếu là snapshot gần nhất, một số giữ bằng chứng kiểm tra ban đầu.
> Kết quả thí nghiệm E2E được tách riêng theo run ID tại `artifacts/experiments/<run-id>/`.
> Việc chia lại thư mục không chạy lại workload hay thay đổi kết quả nghiệm thu.
> EOF
> python3 - <<'PY'
> import sys,pathlib
> sys.path.insert(0,'scripts/k8s');import lab
> p=pathlib.Path('docs/K8S-LAB.md');s=p.read_text()
> for name,relative in lab.ARTIFACT_LOCATIONS.items():
>  s=s.replace('artifacts/k8s/'+name,'artifacts/k8s/'+str(relative))
> s=s.replace('artifacts/k8s/*-build.log','artifacts/k8s/build/*-build.log').replace('artifacts/k8s/bootstrap-{server,client}.json','artifacts/k8s/bootstrap/bootstrap-{server,client}.json')
> s=s.replace('`invalid-xdp.json`, `negative-subnet.json`','`artifacts/k8s/checks/invalid-xdp.json`, `artifacts/k8s/checks/negative-subnet.json`')
> section='''## Cấu trúc implementation và artifact
>
> | Đường dẫn | Vai trò |
> |---|---|
> | `deploy/k8s/values/minikube.yaml` | Cấu hình lab người dùng chỉnh: topology, NF, PLMN/slice, tài nguyên |
> | `deploy/k8s/chart/` | Umbrella Helm chart: workload, Service, PVC, Secret references, Multus NAD, template config và probe |
> | `deploy/k8s/vendor/` | Chart OAI và manifest Multus đã pin; provenance nguồn |
> | `deploy/k8s/images/` | Dockerfile và runtime/entrypoint cho image tools và research |
> | `scripts/k8s/lab.sh`, `lab.py` | CLI điều phối preflight, build, Helm/kubectl, startup gates, thu artifact |
> | `scripts/k8s/analyze.py` | Phân tích traffic/PFCP/KPM và điều kiện nghiệm thu |
> | `tests/k8s/` | Unit test, kiểm tra render và XDP mode |
> | `patches/` | Patch UPF XDP mode, URR và patch chart OAI |
> | `artifacts/k8s/` | File sinh ra; xem [README artifact](../artifacts/k8s/README.md) |
>
> Luồng chính: **values + chart → Helm → workload Kubernetes**. CLI quản lý thứ tự
> và kiểm tra; runtime trong image chuẩn bị config từ ConfigMap/Secret. JSON/YAML
> trong artifact phục vụ chạy lại hoặc đối chiếu, không phải mỗi file là một thành
> phần triển khai độc lập.
>
> Artifact được chia thành `state/`, `build/`, `bootstrap/`, `checks/`, `diagnostics/`
> và `baseline/`; chỉ README và báo cáo `milestones.json` ở cấp đầu. CLI đọc image
> lock/override từ `state/`, ghi kết quả mới vào nhóm tương ứng. Kết quả thí nghiệm
> vẫn nằm tại `artifacts/experiments/<run-id>/`.
>
> '''
> s=s.replace('## Dựng trên máy sạch\n',section+'## Dựng trên máy sạch\n');p.write_text(s)
> PY
> python3 - <<'PY'
> p='tests/k8s/test_lab.py';s=open(p).read();marker='    def test_missing_image_does_not_bootstrap(self):'
> new='''    def test_artifact_paths_separate_state_and_evidence(self):
>         with tempfile.TemporaryDirectory() as d, patch.object(lab, "STATE", pathlib.Path(d)):
>             lab.prepare_artifact_dirs()
>             self.assertEqual(lab.artifact_path("images.json"), pathlib.Path(d) / "state/images.json")
>             self.assertEqual(lab.artifact_path("bootstrap-server.json"), pathlib.Path(d) / "bootstrap/bootstrap-server.json")
>             self.assertEqual(lab.artifact_path("radio-build.log"), pathlib.Path(d) / "build/radio-build.log")
>             with self.assertRaises(KeyError):
>                 lab.artifact_path("unclassified.json")
>
>     def test_helm_reads_overlay_from_state_directory(self):
>         args = type("Args", (), {"values": ROOT / "deploy/k8s/values/minikube.yaml"})()
>         with tempfile.TemporaryDirectory() as d, patch.object(lab, "STATE", pathlib.Path(d)), patch.object(lab, "run") as run:
>             lab.Lab(args).helm()
>             self.assertIn(pathlib.Path(d) / "state/images.yaml", run.call_args.args[0])
>             self.assertNotIn(pathlib.Path(d) / "images.yaml", run.call_args.args[0])
>
> '''
> assert marker in s;s=s.replace(marker,new+marker);open(p,'w').write(s)
> PY
> uvx --from black==25.1.0 black tests/k8s/test_lab.py >/tmp/k8s-artifact-format.log 2>&1
> python3 -m unittest discover -s tests/k8s -v
> scripts/k8s/lab.sh check > /tmp/k8s-artifact-layout-check.log 2>&1
> tail -6 /tmp/k8s-artifact-layout-check.log``
> - Ran `python3 - <<'PY'
> import json,pathlib
> root=pathlib.Path('artifacts/k8s');c=json.loads((root/'milestones.json').read_text())
> for name in c['milestone1']['evidence']:assert (root/name).is_file(),name
> assert {p.name for p in root.iterdir() if p.is_file()}=={'README.md','milestones.json'}
> print('Root tidy; all milestone evidence links resolve.')
> PY
> rg -n 'artifacts/k8s' docs/K8S-LAB.md scripts/k8s/lab.py
> ls artifacts/k8s`
>
> </details>
</details>

Đúng, trước đó CLI ghi chung **cấu hình sinh ra, log và bằng chứng kiểm thử**, nên thư mục bị lộn xộn. Mình đã chia lại và cập nhật CLI.

Phần implementation hiện nằm ở:

| Thư mục | Vai trò |
|---|---|
| `deploy/k8s/values/` | Cấu hình lab cần chỉnh |
| `deploy/k8s/chart/` | Helm quản lý workload, mạng, storage, config |
| `deploy/k8s/vendor/` | Chart OAI và Multus đã pin |
| `deploy/k8s/images/` | Dockerfile và entrypoint |
| `scripts/k8s/` | Điều phối triển khai, kiểm tra, thí nghiệm |
| `tests/k8s/` | Kiểm thử |

Artifact giờ được tổ chức thành:

```text
artifacts/k8s/
├── README.md
├── milestones.json   # Tiến độ nghiệm thu
├── state/            # Image lock và override CLI cần dùng
├── build/            # Log build, provenance
├── bootstrap/        # Kết quả probe, snapshot deployment
├── checks/           # Render, preflight, kiểm thử
├── diagnostics/      # Lỗi và status
└── baseline/         # Đối chiếu Compose
```

Muốn đổi cấu hình thì chỉnh `deploy/k8s/values/minikube.yaml`; các YAML snapshot trong artifact chỉ dùng đối chiếu.

Đã chuyển **35 file**, cập nhật đường dẫn và kiểm tra **15 tests + preflight PASS**. Chi tiết trong [README artifact](./artifacts/k8s/README.md).

> phần artifact lưu trữ cái gì

`artifacts/` lưu **đầu ra của quá trình build, triển khai và chạy thử**, để kiểm tra lỗi, đối chiếu và tái lập kết quả.

Trong `artifacts/k8s/`:

| Thư mục/file | Lưu gì |
|---|---|
| `state/` | Tag, ID, hash source của image và file override image mà CLI dùng khi deploy |
| `build/` | Log build, thông tin nguồn và patch |
| `bootstrap/` | Kết quả kiểm tra mạng, BPF, TUN; snapshot pod, manifest và values đã triển khai |
| `checks/` | Kết quả preflight, kiểm thử, manifest render và các lỗi cố tình thử |
| `diagnostics/` | Lỗi gần nhất và trạng thái lab tại lúc thu thập |
| `baseline/` | Kết quả đối chiếu với backend Compose |
| `milestones.json` | Mốc nào đã hoàn thành, mốc nào chưa |

Sau này, `artifacts/experiments/<run-id>/` sẽ chứa **traffic UL/DL, capture PFCP, CSV URR/KPM và kết quả nghiệm thu từng lần chạy**.

Cấu hình nguồn để chỉnh vẫn nằm trong `deploy/k8s/`. Riêng `artifacts/k8s/state/` cần giữ vì CLI đọc lại khi triển khai.

> implement mốc 2 cần làm những bước nào
>
> **Mốc 2 — Database và core**
>
> - Khởi động DB, nạp subscriber, rồi NRF/UDR/UDM/AUSF/AMF/SMF/UPF/DN.
> - Kiểm tra NF registration, PFCP association, route N4/N6.
> - Xác nhận BPF loader không có lỗi và XDP-SKB attach được; kiểm tra lại sau khi có session nếu chương trình được nạp theo session.
> - Startup/readiness probes kiểm tra dịch vụ; PFCP association là integration gate, tránh liveness restart loop do peer chưa sẵn sàng.

<details><summary>2 previous messages</summary>

> Mình sẽ đối chiếu phần `up --stage core` hiện có để chỉ rõ bước nào đã có code, bước nào cần bổ sung hoặc kiểm chứng ở Mốc 2.
>
> <details><summary>Explored 4 files, a search</summary>
>
> - Read `./scripts/k8s/lab.py`
> - Read `./deploy/k8s/chart/templates/db.yaml`
> - Read `./deploy/k8s/images/runtime.py`
> - Searched for `startupProbe|readinessProbe|livenessProbe|0050|kill -0` in `_nf.tpl`
> - Read `./artifacts/k8s/milestones.json`
>
> </details>
</details>

**Mốc 2 đã có code điều phối cơ bản, nhưng còn thiếu kiểm tra và nghiệm thu runtime.** Cần làm lần lượt 6 bước:

1. **Hoàn thiện database và subscriber**
   - Chạy lại Job seed sau lỗi SQL đã sửa ở Mốc 1.
   - Kiểm tra UE1 có đủ dữ liệu authentication và subscription đúng PLMN/slice/DNN.
   - Seed lần hai để xác nhận không nhân đôi subscriber, không reset SQN, không mất dữ liệu PVC.

2. **Khởi động core theo thứ tự**
   - DB/DN → NRF → UDR → UDM → AUSF → AMF → SMF → UPF.
   - Sửa các lỗi cấu hình, DNS, Secret hoặc interface phát hiện khi chạy thật.
   - CLI hiện đã có nhánh:
     ```bash
     scripts/k8s/lab.sh up --stage core
     ```

3. **Bổ sung kiểm tra NF registration**
   - Xác nhận các NF cần đăng ký đã xuất hiện đúng trong NRF, với endpoint SBI truy cập được.
   - Hiện CLI chủ yếu chờ rollout; **pod Ready chưa chứng minh NF registration thành công**.

4. **Kiểm tra N4/N6 và PFCP**
   - Xác nhận IP/interface và route SMF–UPF, UPF–DN; DN có route trả về `10.1.0.0/16`.
   - Capture PFCP trước khi UPF khởi động.
   - Kiểm tra Association Request/Response khớp nhau và response được chấp nhận. Code hiện mới tìm response accepted trong capture, cần kiểm tra chặt hơn.

5. **Kiểm chứng datapath XDP-SKB**
   - Kiểm tra cấu hình thực tế bật BPF/URR và `xdp_mode: skb`.
   - Thu log loader và thông tin program ID/mode trên N3/N6.
   - Nếu chương trình chỉ attach khi có session, ghi rõ **đang chờ kiểm chứng sau session ở Mốc 3**, không đánh dấu attach PASS trước.
   - Hiện nhánh `--stage core` trả về sau PFCP association, chưa kiểm tra XDP tại đây.

6. **Hoàn thiện probes và báo cáo nghiệm thu**
   - Probes kiểm tra dịch vụ cục bộ; hiện probe core chủ yếu kiểm tra TCP port 80 đang listen, cần xác nhận phù hợp từng NF.
   - PFCP association là bước kiểm tra tích hợp riêng, không dùng để gây vòng lặp liveness restart.
   - Khi lỗi: dừng đúng bước, thu log, trả exit code thất bại.
   - Lưu bằng chứng vào nhóm mới `artifacts/k8s/core/`, rồi cập nhật `milestones.json`.

Các file chính cần làm tiếp là [lab.py](./scripts/k8s/lab.py), [runtime.py](./deploy/k8s/images/runtime.py) và [template NF](./deploy/k8s/chart/templates/_nf.tpl). Mốc này chưa yêu cầu traffic UL/DL, URR hay KPM end-to-end.

> triển khai ngay mốc này theo từng bước, dừng lại và report lỗi ở bước đó luôn ngay khi gặp một lỗi cần quá nhiều token để giải quyết

<details><summary>16 previous messages</summary>

> Mình sẽ triển khai Mốc 2 theo từng bước, bắt đầu với database và subscriber. Lỗi nhỏ có nguyên nhân rõ sẽ được sửa tại chỗ; nếu gặp lỗi cần điều tra hoặc thay đổi lớn, mình sẽ dừng ở bước đó, lưu bằng chứng và báo phần còn vướng.
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `minikube status --profile=oai-lab; docker ps -a --filter name=oai-lab --format '{{.Names}} {{.Status}}'; docker inspect oai-lab --format '{{json .NetworkSettings.Networks}}'; ip -j route; free -m; df -h .`
> - Ran `sed -n '390,465p' scripts/k8s/lab.py; sed -n '615,648p' scripts/k8s/lab.py; sed -n '1,105p' deploy/k8s/chart/templates/_nf.tpl; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods,jobs; cat artifacts/k8s/state/images.yaml; rg --files -g AGENTS.md -g '!src/**' -g '!deploy/k8s/vendor/**'`
>
> </details>
>
> Cluster `oai-lab` hiện đang tắt, nên API báo `no route to host`; chưa phải lỗi database hay core. Mình sẽ khởi động lại profile đã có, giữ nguyên dữ liệu và image, rồi kiểm tra lại tài nguyên trước khi nạp subscriber.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `mkdir -p artifacts/k8s/core
> minikube start --profile=oai-lab --keep-context --driver=docker --container-runtime=containerd --kubernetes-version=v1.33.13 --cni=bridge --cpus=8 --memory=16384 --interactive=false > artifacts/k8s/core/resume.log 2>&1`
> - Ran `tail -12 artifacts/k8s/core/resume.log; sed -n '90,180p' deploy/k8s/chart/files/schema.sql; sed -n '1,65p' scripts/k8s/lab.py; rg -n 'xdp_gate|def collect' scripts/k8s/lab.py; rg -n 'http.*nrf|nnrf-nfm|REGISTERED' src/oai-upf/src/upf_app/app/* | head`
> - Ran `tail -6 artifacts/k8s/core/preflight.log; tail -15 artifacts/k8s/core/database-run.log; cat artifacts/k8s/core/subscriber.log 2>/dev/null; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get jobs`
> - Ran `minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods -o wide; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get events --sort-by=.lastTimestamp | tail -14; docker exec oai-lab df -h /`
> - Ran `minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system get pods; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get nodes -o json > artifacts/k8s/core/nodes.json
> minikube --profile oai-lab ssh -- 'sudo journalctl -u kubelet -n 35 --no-pager' > artifacts/k8s/core/kubelet.log
> python3 - <<'PY'
> import json
> c=json.load(open('artifacts/k8s/core/nodes.json'))
> for n in c['items']:
>  print([(x['type'],x['status'],x.get('message')) for x in n['status']['conditions']])
> PY
> tail -8 artifacts/k8s/core/kubelet.log`
>
> </details>
>
> API đã lên, nhưng DB/DN chưa khởi động được vì Multus sau khi resume đang timeout khi tạo mạng pod. Mình đang thử một lần khởi động lại riêng DaemonSet Multus trong `oai-lab`. Nếu không phục hồi được, mình sẽ dừng tại bước hạ tầng này thay vì tiếp tục điều tra sâu hoặc khởi động các NF.
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `tail -20 artifacts/k8s/core/multus-pod.txt; tail -5 artifacts/k8s/core/multus-restart.log; tail -8 artifacts/k8s/core/database-run.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system get pods -l app=multus; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods -l oai-lab/component=db`
> - Ran `minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system logs kube-multus-ds-cj4gd -c install-multus-binary > artifacts/k8s/core/multus-init.log
> cat artifacts/k8s/core/multus-init.log; ps -eo pid,args | rg '^ *[0-9]+ python3 /tmp/oai-core-database.py'`
> - Ran `python3 - <<'PY'
> from pathlib import Path
> import json,hashlib
> p=Path('deploy/k8s/vendor/multus.yaml');s=p.read_text();old='cp /usr/src/multus-cni/bin/multus-shim /host/opt/cni/bin/multus-shim && cp /usr/src/multus-cni/bin/passthru /host/opt/cni/bin/passthru';new='cp /usr/src/multus-cni/bin/multus-shim /host/opt/cni/bin/.multus-shim.tmp && mv -f /host/opt/cni/bin/.multus-shim.tmp /host/opt/cni/bin/multus-shim && cp /usr/src/multus-cni/bin/passthru /host/opt/cni/bin/.passthru.tmp && mv -f /host/opt/cni/bin/.passthru.tmp /host/opt/cni/bin/passthru';assert old in s;s=s.replace(old,new);p.write_text(s)
> p=Path('deploy/k8s/vendor/PROVENANCE.json');c=json.loads(p.read_text());c['multus']['sha256']=hashlib.sha256(Path('deploy/k8s/vendor/multus.yaml').read_bytes()).hexdigest();c['multus']['patch']='Pinned v4.2.2-thick image; install CNI binaries through same-directory temporary files and atomic rename to avoid ETXTBSY during restart';p.write_text(json.dumps(c,indent=2)+'\n')
> PY
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system apply -f deploy/k8s/vendor/multus.yaml > artifacts/k8s/core/multus-fix.log 2>&1
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system rollout status daemonset/kube-multus-ds --timeout=60s >> artifacts/k8s/core/multus-fix.log 2>&1`
> - Ran `minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system describe pod kube-multus-ds-h7kq7 > artifacts/k8s/core/multus-pod.txt
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system rollout restart daemonset/kube-multus-ds
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=kube-system rollout status daemonset/kube-multus-ds --timeout=60s > artifacts/k8s/core/multus-restart.log 2>&1`
>
> </details>
>
> Đã tìm được lỗi nhỏ, cụ thể: init container Multus dùng `cp` đè lên binary đang được kubelet sử dụng, nên báo `Text file busy`. Mình đã đổi sang ghi file tạm rồi rename nguyên tử và đang kiểm tra phục hồi. Chưa thay đổi database hay chạy các NF.
>
> <details><summary>Explored a file, ran 6 commands</summary>
>
> - Ran `scripts/k8s/lab.sh check > artifacts/k8s/core/preflight.log 2>&1
> minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods,jobs > artifacts/k8s/core/initial-status.txt
> cat > /tmp/oai-core-database.py <<'PY'
> import sys,json,pathlib,time
> sys.path.insert(0,'scripts/k8s');from lab import *
> out=STATE/'core'
> l=Lab(type('Args',(),{'values':DEPLOY/'values/minikube.yaml'})());l.bootstrap=True
> l.ready('db');l.ready('dn')
> l.k('delete','job','oai-lab-subscriber','--ignore-not-found');l.seed=True;l.helm()
> for attempt in range(60):
>  j=json.loads(l.k('get','job','oai-lab-subscriber','-o','json'))
>  if j['status'].get('succeeded'):break
>  if any(c['type']=='Failed' and c['status']=='True' for c in j['status'].get('conditions',[])):
>   (out/'subscriber.log').write_text(l.k('logs','job/oai-lab-subscriber',check=False))
>   raise GateError('Subscriber Job failed; stop at database step')
>  time.sleep(2)
> else:raise GateError('Subscriber Job timed out')
> (out/'subscriber.log').write_text(l.k('logs','job/oai-lab-subscriber'))
> write_json(out/'database-step.json',{'status':'SEED_COMPLETED','idempotence':'PENDING'})
> print('Subscriber seed completed')
> PY
> python3 /tmp/oai-core-database.py > artifacts/k8s/core/database-run.log 2>&1`
>
> - Ran `tail -8 artifacts/k8s/core/multus-fix.log; tail -15 artifacts/k8s/core/database-run.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods,jobs; cat artifacts/k8s/core/subscriber.log 2>/dev/null`
>
> - Ran `cat > /tmp/oai-db-verify.py <<'PY'
> import sys,shlex,json
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('Args',(),{'values':DEPLOY/'values/minikube.yaml'})());out=STATE/'core'
> def snapshot():
>  sql="""SELECT JSON_OBJECT('authCount',(SELECT COUNT(*) FROM AuthenticationSubscription),'authFieldsValid',(SELECT COUNT(*) FROM AuthenticationSubscription WHERE authenticationMethod='5G_AKA' AND CHAR_LENGTH(encPermanentKey)=32 AND CHAR_LENGTH(encOpcKey)=32),'sqnDigest',(SELECT SHA2(sequenceNumber,256) FROM AuthenticationSubscription LIMIT 1),'sessionCount',(SELECT COUNT(*) FROM SessionManagementSubscriptionData),'amCount',(SELECT COUNT(*) FROM AccessAndMobilitySubscriptionData),'session',(SELECT JSON_OBJECT('plmn',servingPlmnid,'slice',JSON_EXTRACT(singleNssai,'$'),'dnnNames',JSON_KEYS(dnnConfigurations)) FROM SessionManagementSubscriptionData LIMIT 1));"""
>  command='MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -uroot -N -B oai_db -e '+shlex.quote(sql)
>  return json.loads(l.k('exec','statefulset/oai-lab-db','-c','db','--','sh','-ec',command))
> a=snapshot();assert a['authCount']==a['authFieldsValid']==a['sessionCount']==a['amCount']==1,a
> assert a['session']['plmn']=='00101' and a['session']['slice']=={'sst':1,'sd':'FFFFFF'} and a['session']['dnnNames']==['nist-dnn']
> # Delete/recreate only the seed Job; database/PVC remain untouched.
> l.seed=True;l.bootstrap=True;l.k('delete','job','oai-lab-subscriber');l.helm();l.k('wait','--for=condition=complete','job/oai-lab-subscriber','--timeout=60s')
> b=snapshot();assert a==b,'Seed changed rows or SQN'
> write_json(out/'database-step.json',{'status':'PASS','subscriberCount':1,'plmn':'00101','slice':{'sst':1,'sd':'FFFFFF'},'dnn':'nist-dnn','seedRuns':2,'rowsUnchanged':True,'sqnPreserved':True,'authenticationRuntime':'NOT_TESTED'})
> print('DB/subscriber and repeated seed PASS')
> PY
> python3 /tmp/oai-db-verify.py > artifacts/k8s/core/database-verify.log 2>&1`
>
> <details><summary>Explored a file</summary>
>
> - Read `./artifacts/k8s/core/database-verify.log`
>
> </details>
>
> - Ran `python3 - <<'PY'
> p='/tmp/oai-db-verify.py';s=open(p).read().replace('mariadb -uroot -N -B','mariadb -uroot -N -B -r');open(p,'w').write(s)
> PY
> python3 /tmp/oai-db-verify.py > artifacts/k8s/core/database-verify.log 2>&1`
>
> - Ran `tail -6 artifacts/k8s/core/database-verify.log`
>
> - Ran `python3 - <<'PY'
> p='/tmp/oai-db-verify.py';s=open(p).read().replace("return json.loads(l.k('exec','statefulset/oai-lab-db','-c','db','--','sh','-ec',command))","result=json.loads(l.k('exec','statefulset/oai-lab-db','-c','db','--','sh','-ec',command))\n for k in ('authCount','authFieldsValid','sessionCount','amCount'):result[k]=int(result[k])\n if isinstance(result['session']['dnnNames'],str):result['session']['dnnNames']=json.loads(result['session']['dnnNames'])\n return result");open(p,'w').write(s)
> PY
> python3 /tmp/oai-db-verify.py > artifacts/k8s/core/database-verify.log 2>&1`
>
> </details>
>
> Bước database/subscriber đã **PASS**: UE1 có đúng PLMN/slice/DNN; nạp lại lần hai không tăng số bản ghi và giữ nguyên SQN. Multus cũng đã phục hồi sau bản sửa nhỏ. Mình đang chuyển sang khởi động lần lượt các NF, bắt đầu từ NRF.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `tail -10 artifacts/k8s/core/nfs-run.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods -l oai-lab/component=nrf; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab logs deployment/oai-nrf -c prepare --tail=12`
> - Ran `tail -16 artifacts/k8s/core/nfs-run.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods -l app.kubernetes.io/instance=oai-lab; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab exec deployment/oai-lab-dn -c dn -- curl -fsS --max-time 10 http://oai-nrf/nnrf-nfm/v1/nf-instances > artifacts/k8s/core/nrf-instances.json
> python3 - <<'PY'
> import json
> p='artifacts/k8s/core/nrf-instances.json';c=json.load(open(p));print(str(c)[:900])
> PY`
> - Ran `minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab exec deployment/oai-lab-dn -c dn -- curl -sS --max-time 10 http://oai-nrf/nnrf-nfm/v1/nf-instances; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab logs deployment/oai-smf -c capture --tail=15; tail -8 artifacts/k8s/core/nfs-run.log`
> - Ran `python3 - <<'PY'
> p='deploy/k8s/chart/templates/_nf.tpl';s=open(p).read().replace('securityContext: {capabilities: {add: [NET_RAW, NET_ADMIN], drop: [ALL]}}','securityContext: {capabilities: {add: [NET_RAW, NET_ADMIN, CHOWN, SETUID, SETGID], drop: [ALL]}}');open(p,'w').write(s)
> PY
> python3 - <<'PY'
> import sys,json
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());l.enabled=NFS[:6];l.seed=True;l.bootstrap=True;l.helm()
> for q in ['nnrf-nfm/v1/nf-instances?nf-type=SMF&limit=20','nnrf-disc/v1/nf-instances?target-nf-type=SMF&requester-nf-type=AMF']:
>  result=l.exec('dn','curl','-sS','--max-time','10','http://oai-nrf/'+q)
>  print(q,result[:1500])
> PY`
> - Ran `tail -12 artifacts/k8s/core/nfs-run.log; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods -l app.kubernetes.io/instance=oai-lab; minikube --profile oai-lab kubectl -- --context=oai-lab --namespace=oai-lab logs deployment/oai-smf -c capture --tail=6`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> <details><summary>Explored a file, ran 6 commands</summary>
>
> - Ran `cat artifacts/k8s/core/progress.json; tail -25 artifacts/k8s/core/nfs-run.log`
>
> <details><summary>Explored a file</summary>
>
> - Read `./scripts/k8s/lab.py`
>
> </details>
>
> - Ran `python3 - <<'PY'
> import sys,json,base64
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})())
> s=json.loads(l.k('get','secret','oai-lab-credentials','-o','json'))
> red=[base64.b64decode(x).decode() for x in s['data'].values()]
> for nf in ['upf','smf','nrf']:
>  t=l.k('logs','deployment/oai-'+nf,'-c',nf,'--tail=140')
>  for x in red:
>   if x:t=t.replace(x,'[REDACTED]')
>  (STATE/'core'/f'{nf}.log').write_text(t)
>  print(nf,t[-11000:])
> print(l.k('get','pods','-o','wide'))
> PY`
>
> - Ran `rg -n 'startupProbe|readinessProbe|tcpSocket|port:|capture' deploy/k8s/chart/templates/_nf.tpl; cat artifacts/k8s/milestones.json; tail -35 docs/K8S-LAB.md; rg -n 'Association|ASSOCIATION|error|warn' artifacts/k8s/core/smf.log`
>
> - Ran `python3 - <<'PY'
> import sys,json,base64
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})())
> s=json.loads(l.k('get','secret','oai-lab-credentials','-o','json'))
> t=l.k('logs','deployment/oai-upf','-c','upf')
> for x in s['data'].values():
>  v=base64.b64decode(x).decode()
>  if v:t=t.replace(v,'[REDACTED]')
> (STATE/'core/upf.log').write_text(t)
> print('\n'.join(x for x in t.splitlines() if any(y.lower() in x.lower() for y in ['error','warn','bpf','xdp','listen','http','server']))[:10000])
> print(l.k('get','events','--field-selector','involvedObject.name=oai-upf-8585b98cf-wf4jl','-o','json')[-5000:])
> PY`
>
> - Ran `sed -n '45,90p' deploy/k8s/chart/templates/_nf.tpl; rg -n 'probe|8805' deploy/k8s/chart/files/runtime.py; tail -12 artifacts/k8s/core/nfs-run.log; cat artifacts/k8s/core/capture-run; rg -n 'handle_receive|ASSOCIATION|error' artifacts/k8s/core/upf.log | head -25; rg --files -g AGENTS.md -g '*test*' tests/k8s`
>
> - Ran `tail -5 artifacts/k8s/core/database-verify.log; cat artifacts/k8s/core/database-step.json
> cat > /tmp/oai-core-nfs.py <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('Args',(),{'values':DEPLOY/'values/minikube.yaml'})());l.seed=True;l.bootstrap=True
> for nf in NFS[:7]:
>  write_json(STATE/'core/progress.json',{'step':'start-'+nf,'status':'RUNNING','ready':l.enabled[:]})
>  l.enabled.append(nf);l.helm();l.ready(nf)
>  write_json(STATE/'core/progress.json',{'step':'start-'+nf,'status':'PASS','ready':l.enabled[:]})
>  if nf=='smf':l.capture_start();(STATE/'core/capture-run').write_text(l.runid)
> PY
> python3 /tmp/oai-core-nfs.py > artifacts/k8s/core/nfs-run.log 2>&1`
>
> </details>
>
> UPF đã load BPF và attach XDP-SKB thật trên N3/N6. Tuy nhiên probe đang kiểm tra TCP/80 nên chưa báo Ready; mình sẽ sửa probe UPF sang socket PFCP UDP/8805. Đồng thời log cho thấy SMF gửi Association Request lặp lại; cần kiểm tra capture để xác định bước PFCP có qua được không.
>
> <details><summary>Explored 3 files, 3 searches, ran 3 commands</summary>
>
> <details><summary>Explored a file, 2 searches</summary>
>
> - Searched for `capture|pcap` in `runtime.py`
> - Searched for `ASSOCIATION SETUP REQUEST` in `oai-upf`
> - Read `./artifacts/k8s/README.md`
>
> </details>
>
> - Ran `python3 - <<'PY'
> from pathlib import Path
> p=Path('deploy/k8s/chart/templates/_nf.tpl');s=p.read_text();old='{{ else }}"awk \'$2 ~ /:0050$/';new='{{ else if eq $nf "upf" }}"awk \'$2 ~ /:2265$/ {ok=1} END {exit !ok}\' /proc/net/udp /proc/net/udp6"{{ else }}"awk \'$2 ~ /:0050$/'
> assert s.count(old)==2;s=s.replace(old,new);p.write_text(s)
> PY
> python3 - <<'PY'
> import sys
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());l.enabled=NFS[:7];l.seed=True;l.bootstrap=True;l.helm();l.ready('upf')
> PY`
>
> <details><summary>Explored 2 files, a search</summary>
>
> - Read `./src/oai-upf/src/upf_app/app/upf_n4.cpp`
> - Read `./scripts/k8s/lab.py`
> - Searched for `node_id|host:` in `config.yaml.tpl`
>
> </details>
>
> - Ran `python3 - <<'PY'
> import sys,json
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());rid=(STATE/'core/capture-run').read_text().strip()
> t=l.k('exec','deployment/oai-smf','-c','capture','--','tshark','-r','/artifacts/runs/'+rid+'/pfcp.pcap','-Y','pfcp','-T','fields','-e','ip.src','-e','ip.dst','-e','pfcp.msg_type','-e','pfcp.seqno','-e','pfcp.cause')
> (STATE/'core/pfcp.tsv').write_text(t);print(t[-2600:])
> print(l.exec('upf','bpftool','-j','net'))
> PY`
>
> - Ran `python3 - <<'PY'
> import sys,json,base64
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());sec=json.loads(l.k('get','secret','oai-lab-credentials','-o','json'))
> for nf in ['smf','upf']:
>  t=l.k('logs','deployment/oai-'+nf,'-c',nf)
>  for x in sec['data'].values():
>   v=base64.b64decode(x).decode()
>   if v:t=t.replace(v,'[REDACTED]')
>  (STATE/'core'/f'{nf}.log').write_text(t)
>  print(nf,'\n'.join(x for x in t.splitlines() if any(y in x.lower() for y in ['association','reject','error','discard','mismatch','unknown','heartbeat request']))[-5500:])
> print(l.exec('upf','sh','-c','command -v ip; ls /usr/sbin/*bpf* /usr/local/sbin/*bpf* /usr/lib/linux-tools/*/bpftool 2>/dev/null','',check=False))
> PY`
>
> </details>
>
> Mình dừng tại bước **PFCP association** theo yêu cầu: capture có phản hồi `Request accepted` từ UPF, nhưng SMF vẫn báo `Failed to receive PFCP Association Response` và retry. Chưa thể coi association thành công; tìm nguyên nhân cần điều tra sâu hơn luồng PFCP SMF–UPF. Mình sẽ lưu bằng chứng và cập nhật trạng thái dở dang; chưa khởi động gNB/UE.
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `python3 - <<'PY'
> import sys,json,subprocess
> sys.path.insert(0,'scripts/k8s');from lab import *
> l=Lab(type('A',(),{'values':DEPLOY/'values/minikube.yaml'})());d=STATE/'core';rid=(d/'capture-run').read_text().strip()
> for nf in ['upf','dn']:
>  t=l.exec(nf,'ip','-j','-details','link','show');(d/(nf+'-links.json')).write_text(t)
>  if nf=='upf':print('XDP',[(x['ifname'],x.get('xdp')) for x in json.loads(t) if x['ifname'] in ['n3','n6']])
> # Stop capture and copy the raw packet evidence without terminal output.
> l.exec('dn','touch','/artifacts/runs/'+rid+'/capture.stop')
> p=subprocess.run(K+['exec','deployment/oai-smf','-c','capture','--','cat','/artifacts/runs/'+rid+'/pfcp.pcap'],stdout=(d/'pfcp.pcap').open('wb'),stderr=subprocess.PIPE);p.check_returncode()
> (d/'status.txt').write_text(l.k('get','pods,svc,pvc,jobs','-o','wide'))
> print('context',run(['kubectl','config','current-context']).strip())
> PY
> python3 -m unittest discover -s tests/k8s -v > artifacts/k8s/core/unit-tests.log 2>&1`
> - Ran `cat deploy/k8s/vendor/PROVENANCE.json | head -45; head -35 docs/K8S-LAB.md; rg -n 'success|association|invalid|exception|decode' artifacts/k8s/core/smf.log | head -20; ls patches | tail`
> - Ran `sed -n '1,65p' tests/k8s/test_lab.py; head -20 patches/oai-charts-7925f93-lab.patch; rg -n 'def wait' scripts/k8s/lab.py; tail -4 artifacts/k8s/core/unit-tests.log; sed -n '252,266p' artifacts/k8s/core/smf.log`
> - Ran ``python3 - <<'PY'
> from pathlib import Path
> import json,datetime,difflib
> root=Path('.');d=root/'artifacts/k8s/core'
> m=json.loads((root/'artifacts/k8s/milestones.json').read_text());m['updatedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat();m['milestone2']={'status':'BLOCKED','stoppedAt':'PFCP association','databaseSeed':'PASS','subscriberReseedIdempotence':'PASS','corePodReadiness':'PASS','nfRegistration':'NOT_FULLY_VERIFIED','n4n6Routes':'NOT_FULLY_VERIFIED','xdpSkbAttach':'PASS','xdpProgramIds':{'n3':2336,'n6':2343},'pfcpAssociation':'FAIL','error':'SMF v2.2.0: handle_receive exception PFCP IE TLV 43 Bad Length 8; association remains pending despite UPF response cause=1','nextAction':'Investigate PFCP IE 43 encoding compatibility between patched UPF and SMF v2.2.0; do not accept packet cause=1 alone as association success','evidence':['core/database-step.json','core/status.txt','core/upf-links.json','core/smf.log','core/upf.log','core/pfcp.pcap'],'note':'Stopped at protocol incompatibility per user instruction; no gNB/UE started.'};(root/'artifacts/k8s/milestones.json').write_text(json.dumps(m,indent=2)+'\n');(d/'progress.json').write_text(json.dumps(m['milestone2'],indent=2)+'\n')
> p=root/'docs/K8S-LAB.md';s=p.read_text();pos=s.index('\nMột UE,');s=s[:pos]+'''\n**Mốc 2 ngày 27/09/2026: dừng ở PFCP association.** DB/Job seed đã chạy thật; seed lại không tăng số bản ghi và giữ SQN. DB, DN và NRF/UDR/UDM/AUSF/AMF/SMF/UPF đều Ready. XDP-SKB attach thật trên N3/N6 được xác nhận bằng `ip -j -details link` (mode 2, program ID 2336/2343 tại thời điểm chụp).
>
> SMF v2.2.0 báo `handle_receive exception PFCP IE TLV 43 Bad Length 8`, rồi retry association. Capture có response cause=1 từ UPF nhưng SMF không giải mã được, nên **không PASS PFCP**. Cần điều tra tương thích IE 43 trước khi chạy tiếp; gate hiện tại chỉ tìm response cause=1 trong pcap chưa đủ và phải được bổ sung kiểm tra trạng thái phía SMF khi xử lý blocker. Chưa nghiệm thu đầy đủ NF registration/route, chưa chạy radio/session/traffic/URR/KPM. Bằng chứng ở [core/](../artifacts/k8s/core/) và [milestones.json](../artifacts/k8s/milestones.json).
>
> Các sửa nhỏ trong lượt này: Multus cài binary bằng atomic rename để tránh `Text file busy` khi resume; capture sidecar thêm CHOWN/SETUID/SETGID cho tcpdump; probe UPF kiểm tra socket UDP/8805 thay TCP/80, không phụ thuộc peer PFCP. Đã giữ nguyên context mặc định và dữ liệu PVC; các pod core còn chạy để kiểm tra.\n'''+s[pos:];p.write_text(s)
> p=root/'artifacts/k8s/README.md';s=p.read_text().replace('| `checks/`','| `core/` | Seed/idempotence, log NF, capture PFCP và snapshot XDP; điểm dừng Mốc 2 | Bằng chứng runtime Mốc 2 |\n| `checks/`');p.write_text(s)
> p=root/'deploy/k8s/vendor/multus.yaml';s=p.read_text();old='cp /usr/src/multus-cni/bin/multus-shim /host/opt/cni/bin/.multus-shim.tmp && mv -f /host/opt/cni/bin/.multus-shim.tmp /host/opt/cni/bin/multus-shim && cp /usr/src/multus-cni/bin/passthru /host/opt/cni/bin/.passthru.tmp && mv -f /host/opt/cni/bin/.passthru.tmp /host/opt/cni/bin/passthru'
> if old in s:
>  before=s.replace(old,'cp /usr/src/multus-cni/bin/multus-shim /host/opt/cni/bin/multus-shim && cp /usr/src/multus-cni/bin/passthru /host/opt/cni/bin/passthru')
>  (root/'patches/multus-v4.2.2-atomic-install.patch').write_text(''.join(difflib.unified_diff(before.splitlines(True),s.splitlines(True),fromfile='a/deploy/k8s/vendor/multus.yaml',tofile='b/deploy/k8s/vendor/multus.yaml')))
> PY
> helm lint deploy/k8s/chart -f deploy/k8s/values/minikube.yaml -f artifacts/k8s/state/images.yaml > artifacts/k8s/core/helm-lint.log 2>&1``
>
> </details>
</details>

Đã triển khai Mốc 2 và **dừng tại lỗi PFCP**, đúng yêu cầu.

- **Đã qua:** DB và subscriber; seed lại không nhân bản, giữ SQN. DB, DN và toàn bộ core đều Ready.
- **Đã xác nhận:** UPF attach **XDP-SKB thật trên N3/N6**.
- **Đã sửa:** lỗi Multus khi resume, quyền tcpdump và probe UPF dùng UDP/8805.
- **Đang chặn:** SMF v2.2.0 báo `PFCP IE TLV 43 Bad Length 8`. UPF trả `accepted` nhưng SMF không giải mã được, nên association vẫn thất bại. Cần điều tra tương thích PFCP trước khi tiếp tục.
- Chưa chạy gNB/UE hoặc traffic. Core còn chạy để kiểm tra; context cluster cũ giữ nguyên.

Đã lưu log/pcap và cập nhật [trạng thái mốc](artifacts/k8s/milestones.json), [tài liệu](docs/K8S-LAB.md). Helm lint và 15 tests đều qua; **Mốc 2 chưa hoàn tất**.

> có log chỉ đích danh lỗi đó được lưu ở đâu không

Có. Log chỉ rõ lỗi nằm tại [artifacts/k8s/core/smf.log:260](./artifacts/k8s/core/smf.log:260):

```text
handle_receive exception PFCP IE TLV 43 Bad Length 8 Exception
/openair-smf/src/oai-cn5g-common-src/pfcp/3gpp_29.244.hpp:2588
```

Ngay trước đó SMF báo:

```text
Failed to receive PFCP Association Response, Retrying .....!!
```

Capture gói PFCP để đối chiếu bằng Wireshark: [pfcp.pcap](./artifacts/k8s/core/pfcp.pcap).

> ## Bước 1 — xác nhận IE 43 trong PCAP
>
> Đầu tiên đừng sửa code ngay. Dump packet ra để biết chính xác UPF đang gửi gì.
>
> Nếu pcap của mày nằm trong artifact:
> ```
> tshark -r <pfcp.pcap> \
>   -Y 'pfcp.msg_type == 6' \
>   -V
> ```
>
> `PFCP Association Setup Response` thường là message type 6.
>
> Hoặc:
> ```
> tshark -r <pfcp.pcap> -Y pfcp -V | less
> ```
>
> Tìm:
> ```
> UP Function Features
> ```
>
> hoặc:
> ```yaml
> IE Type: 43
> Length: 8
> ```
>
> Nếu muốn cực kỳ rõ:
> ```
> tshark -r <pfcp.pcap> \
>   -Y 'pfcp && ip.src==172.30.24.20' \
>   -x
> ```
>
> Mày cần xác nhận packet kiểu:
> ```yaml
> PFCP Association Setup Response
>     Node ID
>     Cause: Request accepted (1)
>     Recovery Time Stamp
>     UP Function Features
>         IE Type: 43
>         Length: 8
>         ...
> ```
>
> Nếu đúng như vậy thì **routing/network không phải root cause nữa**
>
> chạy thử cái này rồi báo cho tao kết quả

<details><summary>2 previous messages</summary>

> Mình sẽ dump response PFCP từ PCAP đã lưu để xác nhận IE 43, độ dài và bytes thực tế; chưa sửa code.
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `tshark -r artifacts/k8s/core/pfcp.pcap -Y 'pfcp.msg_type == 6' -V > artifacts/k8s/core/pfcp-association-response.verbose.txt
>  tshark -r artifacts/k8s/core/pfcp.pcap -Y 'pfcp && ip.src==172.30.24.20' -x > artifacts/k8s/core/pfcp-upf.hex.txt
>  tshark -r artifacts/k8s/core/pfcp.pcap -Y 'pfcp.msg_type == 6' -T fields -e frame.number -e ip.src -e ip.dst -e pfcp.seqno -e pfcp.cause | head -5
> rg -n -m 8 'UP Function Features|IE Type|IE Length|Length:|Cause:|Node ID|Recovery Time' artifacts/k8s/core/pfcp-association-response.verbose.txt`
> - Ran `sed -n '52,153p' artifacts/k8s/core/pfcp-association-response.verbose.txt; head -9 artifacts/k8s/core/pfcp-upf.hex.txt`
>
> </details>
</details>

Đã chạy dump PCAP, **đúng như dự đoán**. Packet số 2:

```text
172.30.24.20 → 172.30.24.10
PFCP Association Setup Response (6)
Sequence Number: 1859458
Node ID: 172.30.24.20
Cause: Request accepted (1)
Recovery Time Stamp
UP Function Features:
    IE Type: 43
    IE Length: 8
```

Bytes thực của IE:

```text
00 2b 00 08 10 00 00 00 00 00 00 00
│type│length│         payload
```

Payload bật **FTUP**, các bit còn lại bằng 0.

Đã lưu:

- [Dump chi tiết](artifacts/k8s/core/pfcp-association-response.verbose.txt:63)
- [Dump hex](artifacts/k8s/core/pfcp-upf.hex.txt)

**Kết luận:** kết hợp PCAP với log SMF `IE TLV 43 Bad Length 8`, lỗi đang chặn association nằm ở **giải mã IE 43 phía SMF**, không phải routing làm mất response. Chưa sửa code.

> check xem SMF đang expect length bao nhiêu và vì sao length=8 lại bị reject. sau đó đề xuất hướng fix

<details><summary>2 previous messages</summary>

> Mình sẽ đối chiếu parser PFCP của SMF v2.2.0 với phần encode IE 43 của UPF để xác định độ dài được chấp nhận và đề xuất cách sửa; chưa thay đổi code.
>
> <details><summary>Explored a file, 4 searches, 2 lists, ran 3 commands, searched the web</summary>
>
> <details><summary>Explored a file, 4 searches, 2 lists</summary>
>
> - Listed files in `src`
> - Searched for `3gpp_29.244.hpp$`
> - Searched for `up_function_features|Bad Length` in `3gpp_29.244.hpp`
> - Listed files in `src`
> - Read `./src/oai-upf/src/common-src/pfcp/3gpp_29.244.hpp`
> - Searched for `smf|common` in `BUILD-FROM-SCRATCH.md`
> - Searched for `up_function_features` in `upf_n4.cpp`
>
> </details>
>
> - Ran `python3 - <<'PY'
> import urllib.request,json
> u='https://api.github.com/repos/OPENAIRINTERFACE/openair-smf/contents/src/oai-cn5g-common-src?ref=v2.2.0'
> try:
>  d=json.load(urllib.request.urlopen(u));print(json.dumps(d,indent=2))
> except Exception as e:print(e)
> PY`
>
> Searched the web for `github openair smf v2.2.0 pfcp up_function_features_ie`
>
> - Ran `python3 - <<'PY'
> import urllib.request,json
> u='https://api.github.com/repos/openairinterface/oai-cn5g-smf/contents/src?ref=v2.2.0'
> d=json.load(urllib.request.urlopen(u));print([(x['name'],x['sha']) for x in d if 'common' in x['name']]);print(urllib.request.urlopen('https://raw.githubusercontent.com/openairinterface/oai-cn5g-smf/v2.2.0/.gitmodules').read().decode())
> PY`
>
> - Ran `python3 - <<'PY'
> import urllib.request,pathlib
> u='https://raw.githubusercontent.com/openairinterface/oai-cn5g-common-src/b5042f5f52cbb0dd61e9a1421b34a9fc030c685f/pfcp/3gpp_29.244.hpp'
> s=urllib.request.urlopen(u).read().decode();p=pathlib.Path('artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp');p.write_text(s)
> a=s.splitlines();print('\n'.join(f'{i+1}: {a[i]}' for i in range(2575,2610)))
> PY`
>
> </details>
</details>

**SMF v2.2.0 chấp nhận tối đa 6 byte cho IE 43; UPF hiện gửi 8 byte nên bị reject ngay.**

Đã đối chiếu source common của tag SMF `v2.2.0`, commit `b5042f5f…`. Parser có:

```cpp
if (tlv.get_length() > 6) {
  throw pfcp_tlv_bad_length_exception(
      tlv.type, tlv.get_length(), __FILE__, __LINE__);
}
```

Dòng throw **2588 khớp chính xác log runtime**. Bản source đối chiếu đã lưu tại [smf-v2.2.0-3gpp_29.244.hpp:2583](artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp:2583). [Source upstream](https://github.com/openairinterface/oai-cn5g-common-src/blob/b5042f5f52cbb0dd61e9a1421b34a9fc030c685f/pfcp/3gpp_29.244.hpp#L2583).

Trong khi đó, [encoder UPF](src/oai-upf/src/common-src/pfcp/3gpp_29.244.hpp:2620) hardcode `length=8` và ghi đủ tám byte, kể cả khi các byte cuối bằng zero. Đây là **không tương thích giữa hai phiên bản codec PFCP**.

Hướng fix đề xuất:

- **Ưu tiên cho lab hiện tại:** giữ SMF v2.2.0, thêm chế độ encode tương thích ở UPF, gửi **6 byte** khi hai byte cuối đều zero. Packet hiện tại đổi từ `10 00 00 00 00 00 00 00` thành `10 00 00 00 00 00`, vẫn giữ FTUP.
- Sửa đồng bộ **độ dài IE, số byte thực ghi và tính độ dài message**; không chỉ thay `set_length(8)`. Không âm thầm cắt nếu hai byte cuối chứa feature đang bật.
- **Hướng dài hạn:** sửa parser SMF để đọc phần hiểu được và bỏ qua phần mở rộng đúng độ dài; cần build image SMF riêng. Chỉ đổi giới hạn `6 → 8` là chưa đủ.

Không nên gửi 2 byte dù chỉ bật FTUP: parser SMF này đọc vô điều kiện bốn byte đầu, có thể đọc lấn sang IE tiếp theo.

Sau fix phải xác nhận SMF hết exception, association thành công và heartbeat hoạt động; riêng response `cause=1` chưa đủ. **Chưa sửa code.**

> research patch cho UPF của tao có theo hướng mô đun hóa dễ phân biệt như bên dưới đây mô tả không? tham khảo hướng fix này và test lại xem lỗi đã hết chưa.
>
> # Có một chi tiết rất quan trọng cho lab của mày
>
> OAI release `v2.2.0` là một bundle release cuối 2025, và OAI federation v2.2.0 là release đồng bộ của cả CN. [GitLab](https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed/-/tags?utm_source=chatgpt.com)
>
> Nếu mày lấy:
> ```ini
> SMF = official v2.2.0
> ```
>
> nhưng:
> ```markdown
> UPF = newer develop
>       + URR patch
>       + XDP patch
> ```
>
> thì mày đã vô tình tạo:
> ```
> stable SMF release
>        +
> newer/customized UPF
> ```
>
> Đây chính xác là loại setup dễ sinh lỗi kiểu này.
>
> Đối với paper của mày, tao sẽ setup theo mô hình:
> ```scss
>              OAI release baseline
>                      │
>          ┌───────────┴───────────┐
>          │                       │
>      OAI SMF                 OAI UPF
>  same compatible          same compatible
>  baseline                 baseline
>                                 │
>                                 │
>                        minimal research patches
>                          ├─ XDP mode
>                          ├─ eBPF logic
>                          └─ URR additions
> ```
>
> Tức là **đừng update cả UPF wholesale lên develop chỉ để lấy một feature**.
>
> Thay vào đó:
> ```
> known-compatible UPF
>         +
> cherry-pick/backport
> research changes
> ```
>
> sẽ reproducible hơn rất nhiều.
>
> ---
>
> ## Với case hiện tại, tao sẽ chọn hướng nào?
>
> Tao **không sửa**:
> ```
> if (tlv.get_length() > 6)
> ```
>
> thành:
> ```
> if (tlv.get_length() > 8)
> ```
>
> ngay.
>
> Vì cách đó chỉ làm parser không throw; chưa chứng minh code phía dưới có buffer/structure đủ cho 8 byte.
>
> Tao sẽ làm theo thứ tự:
>
> 1. Xác định commit/tag chính xác của UPF:
> ```css
> cd src/oai-upf
> git describe --tags --always
> git rev-parse HEAD
> git log -1 --oneline
> ```
>
> 2. Xem `UP Function Features` struct phía SMF:
> ```swift
> grep -Rni "struct.*up_function_features\|class.*up_function_features" \
>     src/oai-smf/src/oai-cn5g-common-src/
> ```
>
> 3. Xem decoder sau check `> 6`.
>
> Nếu decoder chỉ đọc:
> ```python-repl
> octet5
> octet6
> ...
> octet10
> ```
>
> thì fix an toàn có thể là:
> ```python
> if (tlv.get_length() < MINIMUM_REQUIRED_LENGTH) {
>     throw ...;
> }
>
> decode first min(length, 6) bytes;
> ignore trailing bytes;
> ```
>
> chứ **không nhất thiết cần SMF hiểu byte 7 và 8**, vì case hiện tại chúng đều `00`.
>
> Đó là cách tao thích nhất cho lab này:
> ```python
> UPF sends 8 bytes
>        ↓
> SMF recognizes first 6
>        ↓
> last 2 bytes unsupported
>        ↓
> ignore
>        ↓
> FTUP still decoded
>        ↓
> Association PASS
> ```
>
> Nó vừa backward/forward compatible hơn, vừa không ép mày phải implement các feature mới mà SMF không sử dụng.
>
> Quan trọng hơn nữa, FTUP mà UPF đang advertise là capability thực sự cần trong N4: TS 29.244 quy định UP function set FTUP để báo nó hỗ trợ UPF-side F-TEID allocation/release. [ETSI](https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/17.06.00_60/ts_129244v170600p.pdf?utm_source=chatgpt.com) Vì vậy **không nên workaround bằng cách tắt FTUP** chỉ để association chạy.

<details><summary>4 previous messages</summary>

> Mình sẽ kiểm tra provenance và cách tách patch UPF trước, rồi thử hướng sửa decoder SMF để giữ FTUP và bỏ qua các byte mở rộng. Mình sẽ giữ image gốc để rollback; nếu việc build hoặc debug phát sinh trở ngại lớn, mình sẽ dừng và báo rõ.
>
> <details><summary>Explored 2 files, ran 3 commands, searched the web</summary>
>
> - Ran `pwd; rg --files -g AGENTS.md -g '*manifest*' -g '*provenance*' -g '*smf*Docker*' | head -35; df -h .; rg -n '00b7485|develop|UPF|patch' docs/BUILD-FROM-SCRATCH.md | head -35; ls scripts/k8s; ls deploy/k8s/images`
>
> - Ran `docker image ls --format '{{.Repository}}:{{.Tag}} {{.Size}}' | rg 'smf|builder'; cat manifests/oai-upf.commit; cat patches/oai-upf-working-tree.patch | head -10; ls -l artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp; sed -n '2370,2400p' artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp`
>
> Searched the web for `https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed/-/tags`
>
> - Ran `python3 - <<'PY'
> import urllib.request,json
> for repo,ref in [('oai-cn5g-upf','v2.2.0'),('oai-cn5g-upf','9e93b6383803fd0eea2d18d9953670af17c0de64')]:
>  u=f'https://api.github.com/repos/openairinterface/{repo}/commits/{ref}'
>  d=json.load(urllib.request.urlopen(u));print(ref,d['sha'],d['commit']['committer']['date'],d['commit']['message'].splitlines()[0])
> PY
> rg -n '25|disk|for_build' scripts/k8s/lab.py | head -18`
>
> Searched the web for `'FTUP'`
>
> <details><summary>Explored 2 files</summary>
>
> - Read `./scripts/k8s/lab.py`
> - Read `./patches/oai-upf-00b7485-pfcp-urr-reporting.patch`
>
> </details>
>
> </details>
>
> UPF hiện có patch URR và XDP mode riêng, nhưng baseline là commit upstream tháng 8/2026, không phải UPF v2.2.0 tháng 12/2025. eBPF đã có sẵn trong baseline; chưa phải mô hình “cùng release + các backport tối thiểu”.
>
> Có một trở ngại cho test trên cluster: máy còn khoảng 18 GiB đĩa, dưới ngưỡng build 25 GiB của lab, và chưa có image builder SMF. Mình sẽ tạo patch decoder riêng và kiểm thử bằng payload PCAP trước; không hạ ngưỡng hoặc xóa cache để ép build.
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `mkdir -p tests/pfcp
> cat > /tmp/prepare-smf-patch.py <<'PY'
> from pathlib import Path
> import difflib
> p=Path('artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp');s=p.read_text();start=s.index('  void load_from(std::istream& is) {',s.index('class pfcp_up_function_features_ie'));end=s.index('\n  //--------',start)
> new='''  void load_from(std::istream& is) {
>     const auto length = tlv.get_length();
>     if (length < 2) {
>       throw pfcp_tlv_bad_length_exception(
>           tlv.type, length, __FILE__, __LINE__);
>     }
>     // This release understands six octets. Consume extensions without
>     // interpreting them, so the next IE remains aligned in the stream.
>     uint8_t* known[] = {&u1.b, &u2.b, &u3.b, &u4.b, &u5.b, &u6.b};
>     for (auto octet : known) *octet = 0;
>     for (unsigned i = 0; i < length; ++i) {
>       uint8_t octet = 0;
>       if (!is.read(reinterpret_cast<char*>(&octet), sizeof(octet))) {
>         throw pfcp_tlv_bad_length_exception(
>             tlv.type, length, __FILE__, __LINE__);
>       }
>       if (i < 6) *known[i] = octet;
>     }
>   }'''
> out=s[:start]+new+s[end:];Path('patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch').write_text(''.join(difflib.unified_diff(s.splitlines(True),out.splitlines(True),fromfile='a/pfcp/3gpp_29.244.hpp',tofile='b/pfcp/3gpp_29.244.hpp')))
> PY
> python3 /tmp/prepare-smf-patch.py
> cat > tests/pfcp/check_smf_features.py <<'PY'
> #!/usr/bin/env python3
> """Compile exact original/patched decoder methods; replay IE43 from a PCAP.
> Method-level harness, not a complete SMF binary/integration test.
> Usage: python3 tests/pfcp/check_smf_features.py BASELINE_HEADER PCAP
> """
> import pathlib, subprocess, sys, tempfile
> ROOT = pathlib.Path(__file__).resolve().parents[2]
> header, pcap = map(pathlib.Path, sys.argv[1:])
> def method(s):
>     start=s.index('  void load_from(std::istream& is) {',s.index('class pfcp_up_function_features_ie'))
>     return s[start:s.index('\n  //--------',start)]
> raw=subprocess.check_output(['tshark','-r',str(pcap),'-Y','pfcp.msg_type == 6','-T','fields','-e','udp.payload'],text=True)
> payloads=[]
> for line in raw.splitlines():
>     packet=bytes.fromhex(line.replace(':','')); pos=8
>     while pos < len(packet):
>         typ=int.from_bytes(packet[pos:pos+2],'big'); n=int.from_bytes(packet[pos+2:pos+4],'big')
>         value=packet[pos+4:pos+4+n]; assert len(value)==n
>         if typ==43: payloads.append(value)
>         pos+=4+n
> assert payloads and all(x==bytes.fromhex('1000000000000000') for x in payloads)
> with tempfile.TemporaryDirectory() as td:
>     d=pathlib.Path(td); (d/'pfcp').mkdir();(d/'pfcp/3gpp_29.244.hpp').write_bytes(header.read_bytes())
>     subprocess.run(['patch','-p1','-i',str(ROOT/'patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch')],cwd=d,check=True)
>     original=method(header.read_text()); patched=method((d/'pfcp/3gpp_29.244.hpp').read_text())
>     stub='''#include <sstream>
> #include <stdexcept>
> #include <cassert>
> #include <cstdint>
> struct pfcp_tlv_bad_length_exception : std::runtime_error {
>  pfcp_tlv_bad_length_exception(int,int,const char*,int):runtime_error("length"){} };
> struct Base { struct TLV { unsigned n; int type=43; unsigned get_length(){return n;} } tlv;
>  struct Octet { uint8_t b=255; } u1,u2,u3,u4,u5,u6;
> };
> '''
>     code=stub+'struct Original: Base {\n'+original+'\n};\nstruct Patched: Base {\n'+patched+'\n};\n'
>     data=''.join('\\x%02x'%x for x in payloads[0])
>     code+='''int main(){
>  Original old; old.tlv.n=8; std::istringstream a(std::string("'''+data+'''",8));
>  bool rejected=false; try { old.load_from(a); } catch(const pfcp_tlv_bad_length_exception&) {rejected=true;} assert(rejected);
>  for(unsigned n: {2,3,4,5,6,7,8,9,255}) {
>   Patched p; p.tlv.n=n; std::string body(n,'\\0'); body[0]=0x10;
>   if(n>6) body[6]=char(0xff);
>   std::istringstream in(body+"NEXT"); p.load_from(in);
>   assert(p.u1.b==0x10 && p.u2.b==0 && p.u6.b==0);
>   std::string next(4,'\\0'); in.read(&next[0],4); assert(next=="NEXT");
>  }
>  for(unsigned n: {0,1,2,6,8,9}) {
>   Patched p; p.tlv.n=n; std::istringstream in(std::string(n?n-1:0,'\\0'));
>   bool failed=false; try {p.load_from(in);} catch(const pfcp_tlv_bad_length_exception&){failed=true;} assert(failed);
>  }
> }
> '''
>     (d/'test.cpp').write_text(code)
>     subprocess.run(['g++','-std=c++17','-Wall','-Wextra',str(d/'test.cpp'),'-o',str(d/'test')],check=True)
>     subprocess.run([str(d/'test')],check=True)
> print(f'PASS: {len(payloads)} captured IE43 payloads identical; original rejects length=8; patched decoder preserves FTUP, consumes extensions, preserves next IE, rejects short/truncated payloads. Runtime SMF NOT TESTED.')
> PY
> python3 tests/pfcp/check_smf_features.py artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp artifacts/k8s/core/pfcp.pcap > artifacts/k8s/core/smf-decoder-test.log 2>&1
> cat artifacts/k8s/core/smf-decoder-test.log`
> - Ran `python3 - <<'PY' > artifacts/k8s/core/smf-build-preflight.log 2>&1
> import sys,yaml
> sys.path.insert(0,'scripts/k8s');from lab import *
> v=yaml.safe_load((DEPLOY/'values/minikube.yaml').read_text())
> try: host_check(v,for_build=True)
> except GateError as e:
>  write_json(STATE/'core/smf-build-preflight.json',{'status':'BLOCKED','error':str(e),'diskFreeGiB':round(shutil.disk_usage(ROOT).free/1024**3,2),'diskRequiredGiB':v['global']['lab']['minDiskGiB'],'imageBuilt':False,'runtimeRetested':False});print(e);sys.exit(1)
> PY
> cat artifacts/k8s/core/smf-build-preflight.json`
> - Ran ````cat > docs/SMF-PFCP-COMPATIBILITY.md <<'EOF'
> # PFCP IE 43 compatibility experiment (2026-09-27)
>
> ## Baseline and patch boundaries
>
> The workspace is a source snapshot without component Git metadata. UPF provenance is recorded in `manifests/oai-upf.commit`: fork commit `00b7485329b2c07d6cf74bbfae53b7f7acf5de4e`, with upstream parent `9e93b6383803fd0eea2d18d9953670af17c0de64` (2026-08-26). Upstream UPF v2.2.0 is `e025cdfb3a9c18a228f2efe36bd06b9de998554c` (2025-12-12). This is not a same-release baseline with SMF v2.2.0.
>
> - `patches/oai-upf-00b7485-pfcp-urr-reporting.patch`: 13 files, includes ring-buffer/PFCP report integration and kernel/userspace URR map/trigger corrections. These are one combined research patch, not independent eBPF and reporting layers.
> - `patches/oai-upf-xdp-mode.patch`: explicit XDP mode/attachment handling, separate from URR.
> - eBPF/XDP datapath already exists upstream; it is not all locally implemented research code.
> - Backporting onto UPF v2.2.0 has NOT been performed or validated. It needs a separate compatibility audit; do not describe the current tree as that architecture.
>
> ## Decoder patch
>
> `patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch` applies with `patch -p1` at the SMF common-source submodule root, pinned to `b5042f5f52cbb0dd61e9a1421b34a9fc030c685f` from SMF v2.2.0. It is an SMF compatibility patch, separate from UPF research patches. The baseline header snapshot is `artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp`.
>
> The decoder requires at least two octets, zeros six known feature octets, reads exactly the declared payload length, retains the first six octets and consumes extensions without interpreting them. A truncated stream throws. FTUP remains set; UPF encoding is unchanged. This patch does not merely raise the upper bound or claim support for unknown feature bits.
>
> Run method-level regression:
>
> ```sh
> python3 tests/pfcp/check_smf_features.py \
>   artifacts/k8s/core/smf-v2.2.0-3gpp_29.244.hpp \
>   artifacts/k8s/core/pfcp.pcap
> ```
>
> The test compiles the exact original and patched method bodies with minimal TLV/exception stubs. It checks the 20 captured IE43 payloads, reproduces the original length=8 rejection, and checks FTUP, lengths 2–9 and 255, nonzero unknown octets, next-IE alignment, and short/truncated payload rejection. It does NOT test the full PFCP message decoder or a deployed SMF.
>
> ## Stopping point
>
> Method regression PASS (`artifacts/k8s/core/smf-decoder-test.log`). Build preflight BLOCKED: 17.47 GiB free versus lab requirement 25 GiB (`smf-build-preflight.json`). No cache removed, no SMF image built/deployed, no runtime association PASS claimed. Original runtime image/UPF remain unchanged.
>
> After disk capacity is available: pin/checkout SMF and submodules; apply this patch; build a separately tagged image with source/patch hashes; introduce an explicit custom-SMF image override in the CLI validation/image lock (currently only official v2.2.0 is allowed); capture before restart; verify SMF association state and bidirectional heartbeat, not only response cause=1. Keep official image for rollback. M2 remains blocked until actual runtime evidence exists.
>
> Sources: [UPF parent](https://github.com/openairinterface/oai-cn5g-upf/commit/9e93b6383803fd0eea2d18d9953670af17c0de64), [UPF release](https://github.com/openairinterface/oai-cn5g-upf/commit/e025cdfb3a9c18a228f2efe36bd06b9de998554c), [SMF submodule pin](https://github.com/openairinterface/oai-cn5g-smf/tree/v2.2.0/src), [ETSI TS 29.244 §8.2.25](https://www.etsi.org/deliver/etsi_ts/129200_129299/129244/17.06.00_60/ts_129244v170600p.pdf).
> EOF
> python3 - <<'PY'
> from pathlib import Path
> import json
> p=Path('docs/K8S-LAB.md');s=p.read_text();s+='\nPhân tích baseline UPF và patch decoder SMF mới: [SMF-PFCP-COMPATIBILITY.md](SMF-PFCP-COMPATIBILITY.md). Test decoder đã PASS; build/runtime bị chặn bởi dung lượng đĩa, chưa thay image trên cluster.\n';p.write_text(s)
> p=Path('artifacts/k8s/milestones.json');v=json.loads(p.read_text());v['milestone2']['decoderPatchTest']='PASS_METHOD_LEVEL_ONLY';v['milestone2']['smfPatchedBuild']='BLOCKED_DISK';v['milestone2']['smfPatchedRuntime']='NOT_RUN';p.write_text(json.dumps(v,indent=2)+'\n')
> PY````
>
> </details>
</details>

**Patch đã tách một phần, nhưng baseline chưa theo mô hình mày mô tả:**

- UPF dựa trên upstream `9e93b638` tháng 8/2026, không cùng baseline v2.2.0 với SMF.
- Patch **URR reporting** và **XDP mode** riêng biệt. Patch URR vẫn gộp sửa kernel/userspace và báo cáo PFCP.
- eBPF datapath có sẵn từ upstream. Chưa backport research changes lên UPF v2.2.0.

Đã tạo [patch decoder SMF](patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch) theo hướng đề xuất: đọc tối đa sáu byte đã hiểu, tiêu thụ byte mở rộng, giữ FTUP và từ chối payload bị cắt ngắn.

**Kết quả test:** [PASS ở mức decoder](artifacts/k8s/core/smf-decoder-test.log). Payload lấy từ PCAP khiến decoder gốc reject; decoder đã sửa đọc được, giữ FTUP và không lệch IE kế tiếp.

**Chưa thể kết luận lỗi trên cluster đã hết:** build preflight bị chặn vì còn **17,47 GiB**, dưới ngưỡng **25 GiB**. Chưa build/deploy SMF mới, không xóa cache hoặc đổi image đang chạy.

Chi tiết baseline, patch và bước tiếp tục: [SMF-PFCP-COMPATIBILITY.md](docs/SMF-PFCP-COMPATIBILITY.md).

> xem xem có dọn được image hay file rác nào để tăng dụng lượng khả dụng của bộ nhớ ngay bây giờ mà không ảnh hưởng gì đến codebase đang chạy hiện tại. list ra thành các list để t checkout trước, tao cho mày xem kiểm tra hệ thống máy

<details><summary>6 previous messages</summary>

> Mình sẽ chỉ audit dung lượng, chưa xóa gì. Mình sẽ phân loại rõ: thứ đang được cluster `oai-lab` dùng, cache có thể tái tạo, image/container không liên quan, và file lớn trong codebase để mày checkout trước.
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `docker ps -a --no-trunc --format '{{json .}}'; docker volume ls --format '{{json .}}'; docker network ls --format '{{json .}}'`
> - Ran `df -hT / /var/lib/docker 2>/dev/null; du -xhd1 . 2>/dev/null | sort -h; du -xhd1 /var/lib/docker 2>/dev/null | sort -h | tail -20`
> - Ran `find . -xdev -type f -size +100M -printf '%s\t%p\n' 2>/dev/null | sort -nr | head -100; du -xhd2 src artifacts deploy patches 2>/dev/null | sort -h | tail -60`
> - Ran `minikube status -p oai-lab --output=json 2>/dev/null; minikube -p oai-lab kubectl -- --context=oai-lab --namespace=oai-lab get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .spec.initContainers[*]}{.image}{" "}{end}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}' 2>/dev/null; minikube -p oai-lab image ls 2>/dev/null`
> - Ran `du -xhd1 ~/.cache ~/.local/share/containers ~/.minikube 2>/dev/null | sort -h; find ~/.cache ~/.minikube -xdev -type f -size +100M -printf '%s\t%p\n' 2>/dev/null | sort -nr | head -60`
> - Ran `docker system df -v`
>
> </details>
>
> Kết quả sơ bộ có hai nguồn rất lớn mà không nằm trong codebase: cache IntelliSense C/C++ khoảng 40 GiB và Docker build cache khoảng 17,6 GiB. Cluster đang chạy giữ image riêng trong volume minikube; mình đang kiểm tra thêm file mở đã xóa, log hệ thống và phân biệt cache nào xóa được mà không làm mất khả năng rollback hiện tại.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `find ~/.minikube/cache -maxdepth 3 -type f -printf '%s\t%p\n' 2>/dev/null | sort -nr | head -40; du -xhd2 ~/.minikube/cache 2>/dev/null | sort -h | tail -30`
> - Ran `du -xhd3 src/oai-ran/cmake_targets src/flexric/build src/5gdeploy/node_modules 2>/dev/null | sort -h | tail -40; find artifacts -xdev -type f -printf '%s\t%p\n' | sort -nr | head -20`
> - Ran `docker buildx du 2>/dev/null | tail -25; docker images --filter dangling=true --format '{{.ID}}\t{{.Size}}\t{{.CreatedSince}}'; docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}' | sort`
> - Ran `journalctl --disk-usage 2>/dev/null; du -sh /var/cache/apt /var/lib/apt/lists /var/log 2>/dev/null; sudo -n true >/dev/null 2>&1 && lsof -nP +L1 2>/dev/null | awk 'NR==1 || $7>=10485760 {print}' | sort -k7nr | head -30 || lsof -nP +L1 2>/dev/null | awk 'NR==1 || $7>=10485760 {print}' | sort -k7nr | head -30`
> - Ran `du -xhd1 /home/ducsssanh 2>/dev/null | sort -h | tail -30; du -xhd1 /home/ducsssanh/.cache/vscode-cpptools 2>/dev/null | sort -h | tail -30`
>
> </details>
>
> Hiện filesystem đã có 28 GiB trống, vừa vượt ngưỡng preflight 25 GiB, nhưng biên an toàn còn ít cho một build SMF. Mình sẽ map các thư mục cache IntelliSense về workspace tương ứng và tính nhóm Docker image không dùng để danh sách không xóa nhầm cache/image của `oai-lab`.
>
> <details><summary>Ran 7 commands</summary>
>
> - Ran `for d in ~/.cache/vscode-cpptools/*; do [ -d "$d" ] || continue; p=$(find "$d" -maxdepth 1 -type f ! -name '*.db*' -printf '%f ' 2>/dev/null); printf '%s\t%s\t%s\n' "$(du -sh "$d" 2>/dev/null | cut -f1)" "$(basename "$d")" "$p"; done | sort -h; find ~/.cache/vscode-cpptools -maxdepth 2 -type f ! -name '*.db*' ! -name '*.ipch' -printf '%p\n' | head -100`
> - Ran `docker image inspect $(docker image ls -q) --format '{{.Id}}|{{join .RepoTags ","}}|{{.Size}}|{{json .ContainerConfig.Labels}}' 2>/dev/null | sort -u > /tmp/oai-image-audit.txt; awk -F'|' '$2 ~ /^5gdeploy.localhost/ {s+=$3} END {printf "5gdeploy nominal bytes: %.2f GiB\n",s/1073741824}' /tmp/oai-image-audit.txt; awk -F'|' '$2 ~ /^(grafana|prom\/|chartmuseum|ncabatoff|example.com|openapitools)/ {s+=$3;print} END {printf "other nominal bytes: %.2f GiB\n",s/1073741824}' /tmp/oai-image-audit.txt`
> - Ran `docker ps --format '{{.Image}}' | sort -u; docker inspect oai-lab --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{"\n"}}{{end}}'; minikube -p oai-lab ssh -- 'sudo crictl images 2>/dev/null | head -40; sudo du -sh /var/lib/containerd /var/lib/kubelet 2>/dev/null'`
> - Ran `du -sh ~/.cache/vscode-cpptools/ipch ~/.cache/vscode-cpptools/*/.browse.VC.db 2>/dev/null | sort -h | tail -30`
> - Ran `find ~/.minikube/cache/images/amd64 -maxdepth 1 -type f -printf '%s\t%f\n' 2>/dev/null | sort -nr; df -h /`
> - Ran `find /var/cache/apt/archives -maxdepth 1 -type f -printf '%s\t%f\n' 2>/dev/null | sort -nr | head -25; du -sh /var/cache/apt/archives 2>/dev/null`
> - Ran `docker system df --format '{{json .}}' 2>/dev/null || true; docker image ls --filter dangling=true -q | sort -u | wc -l`
>
> </details>
</details>

Mình đã kiểm tra read-only, chưa xóa gì. Hiện ổ đĩa còn **28 GiB trống**; cluster `oai-lab` vẫn chạy bình thường.

Các mục có thể dọn mà không ảnh hưởng workload Kubernetes đang chạy:

1. **APT package cache — 6,8 GiB**

   - Đường dẫn: `/var/cache/apt/archives`
   - Chỉ là các file `.deb` đã tải.
   - Xóa không ảnh hưởng package đã cài; lần sau cần cài lại sẽ tải lại.
   - Đây là lựa chọn an toàn nhất.

2. **Docker BuildKit cache — khoảng 11,9 GiB thực sự reclaimable**

   - Tổng cache hiện tại: 17,64 GiB.
   - Không xóa Docker image đã build và không ảnh hưởng container minikube đang chạy.
   - Build UPF/RAN/radio lần sau sẽ mất cache và chậm hơn.
   - Có thể dọn sau APT nếu cần thêm dung lượng build SMF.

3. **VS Code C/C++ IntelliSense cache — khoảng 40 GiB**

   - Đường dẫn: `~/.cache/vscode-cpptools`
   - Gồm khoảng 35 GiB database `.browse.VC.db` và 5,1 GiB precompiled headers.
   - Không chứa source code; VS Code sẽ index lại.
   - Nên đóng VS Code trước khi xóa vì `cpptools` hiện vẫn đang mở một file tạm khoảng 470 MiB.
   - Đây là nguồn rác lớn nhất trên máy.

4. **System journal — 2,4 GiB**

   - Có thể giới hạn journal về khoảng 500 MiB.
   - Không ảnh hưởng cluster, nhưng mất log hệ thống cũ nên ưu tiên thấp hơn.

5. **Build output trong codebase — khoảng 2,45 GiB**

   - `src/oai-ran/cmake_targets`: 1,6 GiB
   - `src/flexric/build`: 608 MiB
   - `src/5gdeploy/node_modules`: 241 MiB
   - Không ảnh hưởng pod hiện tại vì image đã nằm trong minikube.
   - Tuy nhiên sẽ phải build/cài dependency lại, nên không cần xóa lúc này.

Các mục dọn được nhưng có tác động đến khả năng rebuild/rollback:

- `~/.minikube/cache`: 3,3 GiB. Không ảnh hưởng cluster đang chạy, nhưng làm chậm việc dựng lại cluster. Trong đó có image radio/UPF/tools hiện hành nên mình đề nghị giữ.
- Docker image `5gdeploy.localhost/*`: khoảng 5–6 GiB. Không được Kubernetes hiện tại sử dụng, nhưng Compose backend cần chúng để rollback.
- `oransim:0.0.999`: 2,7 GiB và một container đã dừng. Không liên quan repo hiện tại, nhưng thuộc testbed khác nên cần xác nhận trước khi xóa.
- Docker đang báo tổng image reclaimable là 12,38 GiB, nhưng con số này bao gồm cả image OAI local cần cho rebuild/import; không nên chạy `docker image prune -a` hàng loạt.

Các mục phải giữ:

- Docker container/volume `oai-lab`; volume này khoảng **11,1 GiB**, chứa toàn bộ node minikube và containerd.
- Image hiện hành:
  - `oai-lab-radio:b715742212936699`
  - `oai-lab-tools:b715742212936699`
  - `oai-lab-upf:b715742212936699`
  - các image OAI core `v2.2.0`
  - `mariadb:10.6`
  - `gcr.io/k8s-minikube/kicbase:v0.0.50`
- `artifacts/` chỉ khoảng 2,9 MiB, không đáng xóa và đang chứa bằng chứng Mốc 1/2.

Phương án mình đề xuất để tiếp tục build SMF:

- Dọn APT cache: thu khoảng 6,8 GiB.
- Dọn Docker build cache: thu thêm khoảng 11,9 GiB.
- Giữ toàn bộ image và volume `oai-lab`.
- Chưa cần đụng tới codebase hay cache minikube.

Hai bước này dự kiến đưa dung lượng trống từ **28 GiB lên khoảng 46 GiB**, đủ an toàn hơn để build SMF.

> cho tao câu lệnh để xóa hết các phần này
>
> 1. **APT package cache — 6,8 GiB**
>    - Đường dẫn: `/var/cache/apt/archives`
>    - Chỉ là các file `.deb` đã tải.
>    - Xóa không ảnh hưởng package đã cài; lần sau cần cài lại sẽ tải lại.
>    - Đây là lựa chọn an toàn nhất.
> 2. **Docker BuildKit cache — khoảng 11,9 GiB thực sự reclaimable**
>    - Tổng cache hiện tại: 17,64 GiB.
>    - Không xóa Docker image đã build và không ảnh hưởng container minikube đang chạy.
>    - Build UPF/RAN/radio lần sau sẽ mất cache và chậm hơn.
>    - Có thể dọn sau APT nếu cần thêm dung lượng build SMF.
> 3. **VS Code C/C++ IntelliSense cache — khoảng 40 GiB**
>    - Đường dẫn: `~/.cache/vscode-cpptools`
>    - Gồm khoảng 35 GiB database `.browse.VC.db` và 5,1 GiB precompiled headers.
>    - Không chứa source code; VS Code sẽ index lại.
>    - Nên đóng VS Code trước khi xóa vì `cpptools` hiện vẫn đang mở một file tạm khoảng 470 MiB.
>    - Đây là nguồn rác lớn nhất trên máy.
> 4. **System journal — 2,4 GiB**
>    - Có thể giới hạn journal về khoảng 500 MiB.
>    - Không ảnh hưởng cluster, nhưng mất log hệ thống cũ nên ưu tiên thấp hơn.
> 5. **Build output trong codebase — khoảng 2,45 GiB**
>    - `src/oai-ran/cmake_targets`: 1,6 GiB
>    - `src/flexric/build`: 608 MiB
>    - `src/5gdeploy/node_modules`: 241 MiB
>    - Không ảnh hưởng pod hiện tại vì image đã nằm trong minikube.
>    - Tuy nhiên sẽ phải build/cài dependency lại, nên không cần xóa lúc này.

Chạy lần lượt:

```bash
# 1. Xóa APT package cache
sudo apt-get clean

# 2. Xóa toàn bộ Docker BuildKit cache, giữ nguyên image/container/volume
docker builder prune --all --force

# 3. Đóng VS Code trước, rồi xóa IntelliSense cache
rm -rf -- /home/ducsssanh/.cache/vscode-cpptools

# 4. Giữ system journal tối đa 500 MiB
sudo journalctl --vacuum-size=500M

# 5. Xóa build output, không xóa source/build script
rm -rf -- \
  /home/ducsssanh/6G/O-RAN/DATN/Codebase/src/oai-ran/cmake_targets/ran_build/build \
  /home/ducsssanh/6G/O-RAN/DATN/Codebase/src/flexric/build \
  /home/ducsssanh/6G/O-RAN/DATN/Codebase/src/5gdeploy/node_modules
```

Kiểm tra dung lượng sau khi xóa:

```bash
df -h /
docker system df
du -sh \
  /var/cache/apt/archives \
  /home/ducsssanh/.cache/vscode-cpptools \
  2>/dev/null
```

Không chạy `docker system prune -a` hoặc `docker volume prune`, vì có thể xóa image phục vụ rebuild và dữ liệu minikube.
