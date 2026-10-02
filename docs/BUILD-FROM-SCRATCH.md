# Xây dựng Codebase OAI/FlexRIC từ nguồn

Ngày đối chiếu ban đầu: 26/09/2026; cập nhật runtime Kubernetes: 30/09/2026. Tài liệu tái dựng từ source, manifests, patch, script legacy và các checkout Git cũ còn trên máy. Không có lịch sử Git ở root Codebase, nên đây là quy trình tái dựng có kiểm chứng phần source, không phải bản ghi đầy đủ mọi lệnh đã chạy trong quá khứ. Một run đã xác nhận UL/DL, PFCP URR, A1-EI và KPM tới chính xApp; session epoch khi SEID được tái sử dụng vẫn chưa triển khai.

## 1. Thành phần và nguồn gốc

Không phải mọi service đều được clone từ OpenAirInterface. AMF/NRF/AUSF/UDM/UDR dùng image phát hành; RAN và UPF có source OAI research. Source SMF v2.2.0 được pin riêng để build một patch tương thích PFCP tối thiểu. FlexRIC đến từ Mosaic5G; 5gdeploy và lớp automation kế thừa NIST.

| Thư mục | Repository | Commit đã ghi nhận |
|---|---|---|
| `src/oai-ran` | `https://gitlab.eurecom.fr/oai/openairinterface5g.git` | `26efcc498931b8f6979c39f9f44400f3c965fdc4` |
| `src/flexric` | `https://gitlab.eurecom.fr/mosaic5g/flexric.git` | `ef6d722f22191eea74089966983da1f5ec1fedd4` |
| `src/5gdeploy` | `https://github.com/usnistgov/5gdeploy.git` | `c842a50ee2794f5795a7cea65947287662225572` |
| `src/oai-upf` | upstream `https://github.com/OPENAIRINTERFACE/oai-cn5g-upf.git`; fork `https://github.com/ducsssanh/oai-cn5g-upf.git` | fork `00b7485329b2c07d6cf74bbfae53b7f7acf5de4e` |
| `src/oai-smf` | `https://github.com/OPENAIRINTERFACE/oai-cn5g-smf.git` | tag v2.2.0 / `d18906656ca85b823cc68877e3c545353150c018`; common source `b5042f5f52cbb0dd61e9a1421b34a9fc030c685f` |
| Automation nền | upstream `https://github.com/USNISTGOV/O-RAN-Testbed-Automation.git`; fork `https://github.com/ducsssanh/O-RAN-Testbed-Automation.git` | checkout cũ trên máy `c1dd6ea68b7b236e7ff8e90994fba9138f28b457` |

UPF fork có một commit riêng `00b7485` trên parent upstream `9e93b6383803fd0eea2d18d9953670af17c0de64`: `feat(upf): emit PFCP usage reports from eBPF URR events`.

Compose vẫn dùng image `oaisoftwarealliance/oai-{amf,smf,nrf,ausf,udm,udr}:v2.2.0`. Kubernetes dùng các image release tương tự, riêng SMF được override bằng image v2.2.0 có patch decoder IE 43; patch này không thêm tùy chỉnh threshold URR. Database dùng MariaDB. `src/urr-producer` và `src/a1-ei-adapter` hiện là thư mục rỗng, không phải service đã implementation.

## 2. Từ testbed cũ sang một Codebase

Nguồn cũ ở `O-RAN-Testbed-Automation` có cấu trúc chia theo vai trò:

| Vị trí cũ | Vị trí mới |
|---|---|
| `OpenAirInterface_Testbed/User_Equipment/openairinterface5g` | `src/oai-ran`, dùng chung cho UE và gNB |
| `OpenAirInterface_Testbed/RAN_Intelligent_Controllers/Flexible-RIC/flexric` | `src/flexric` |
| `5G_Core_Network/OAI_UPF_Research` | `src/oai-upf` |
| `5G_Core_Network/Additional_Cores_5GDeploy/5gdeploy` | `src/5gdeploy` |
| Các script cài/chạy từng vai trò | bản gốc ở `scripts/legacy/{core,flexric,gnb,ue}`; bản Compose đã port ở `scripts/legacy/compose` |
| Patch cài đặt RAN/FlexRIC | `patches/ran`, `patches/flexric` |

`scripts/legacy/compose/env.sh` gom đường dẫn; source file này không khởi động service. `configs/` chứa đầu vào; `compose/core` là đầu ra sinh tự động; `artifacts/` chứa log/kết quả. RAN vẫn chứa FlexRIC nhúng tại `openair2/E2AP/flexric` cho E2 agent, khác với FlexRIC standalone phục vụ RIC/xApp.

Codebase hiện tại là **snapshot được gom chung**, chưa phải monorepo Git: không có `.git` ở root hoặc bốn cây source chính. Không nên mô tả là đã merge lịch sử Git các repo. `manifests/*.commit`, `*.status`, `*.submodules` và patch là thông tin truy xuất nguồn.

## 3. Tái dựng nguồn trong thư mục mới

Các lệnh dưới chạy trong Bash. Giữ Codebase hiện tại làm bộ tài nguyên local: các patch, script port, config và test này không tự xuất hiện khi clone OAI. Quy trình không ghi đè workspace đang dùng.

```bash
set -euo pipefail
ASSET_ROOT=/home/ducsssanh/6G/O-RAN/DATN/Codebase
REBUILD_ROOT="$HOME/oai-codebase-rebuild"
test ! -e "$REBUILD_ROOT"
mkdir -p "$REBUILD_ROOT/src"
cp -a "$ASSET_ROOT"/{scripts,patches,configs,manifests,tests,docs} "$REBUILD_ROOT/"
mkdir -p "$REBUILD_ROOT/compose" "$REBUILD_ROOT/artifacts"
cd "$REBUILD_ROOT"

git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git src/oai-ran
git -C src/oai-ran checkout --detach 26efcc498931b8f6979c39f9f44400f3c965fdc4
git -C src/oai-ran submodule update --init --recursive

git clone https://gitlab.eurecom.fr/mosaic5g/flexric.git src/flexric
git -C src/flexric checkout --detach ef6d722f22191eea74089966983da1f5ec1fedd4
git -C src/flexric submodule update --init --recursive

git clone https://github.com/usnistgov/5gdeploy.git src/5gdeploy
git -C src/5gdeploy checkout --detach c842a50ee2794f5795a7cea65947287662225572

git clone https://github.com/ducsssanh/oai-cn5g-upf.git src/oai-upf
git -C src/oai-upf checkout --detach 00b7485329b2c07d6cf74bbfae53b7f7acf5de4e
git -C src/oai-upf submodule update --init --recursive

git clone https://github.com/OPENAIRINTERFACE/oai-cn5g-smf.git src/oai-smf
git -C src/oai-smf checkout --detach d18906656ca85b823cc68877e3c545353150c018
git -C src/oai-smf submodule update --init --recursive
test "$(git -C src/oai-smf/src/oai-cn5g-common-src rev-parse HEAD)" = \
  b5042f5f52cbb0dd61e9a1421b34a9fc030c685f
```

Không dùng `--depth=1` rồi giả định commit lịch sử luôn có sẵn. Nếu một remote không phục vụ SHA nữa, cần Git bundle/mirror từ checkout cũ; chưa thử truy cập lại tất cả remote bằng clone đầy đủ trong audit này.

Nếu muốn UPF xuất phát trực tiếp từ upstream: clone upstream, checkout parent `9e93b6383803fd0eea2d18d9953670af17c0de64`, rồi `git am "$REBUILD_ROOT/patches/oai-upf-00b7485-pfcp-urr-reporting.patch"` và init submodule. Chọn một cách; không áp patch này lần nữa trên `00b7485`. `git am` tạo commit tương đương nội dung, SHA có thể khác vì committer metadata.

Submodule UPF phải khớp:

| Path | Commit |
|---|---|
| `build/common-build` | `7b20f7ff8a29855fbfa35c0b913e12968db31337` |
| `ci-scripts/common` | `8471dc86e029641b938818e1c74f7e4f0369dd88` |
| `src/common-src` | `ef4ddb0ee95ad00c4696f549e7486ba202eff825` |

FlexRIC nhúng RAN dùng `ef6d722f...`. Dấu `-` trong manifest submodule cũ chỉ trạng thái chưa initialized lúc ghi nhận; không phải một phần SHA.

## 4. Áp delta local đúng một lần

Để khôi phục **đủ** thay đổi source, dùng patch tổng hợp; patch nhỏ do build helper dùng không chứa mọi thay đổi như PDCP volume và default E2AP/KPM ở RAN.

```bash
git -C src/oai-ran apply --check --exclude=openair2/E2AP/flexric \
  "$REBUILD_ROOT/patches/oai-ran-working-tree.patch"
git -C src/oai-ran apply --exclude=openair2/E2AP/flexric \
  "$REBUILD_ROOT/patches/oai-ran-working-tree.patch"
git -C src/flexric apply "$REBUILD_ROOT/patches/flexric-working-tree.patch"
git -C src/flexric apply "$REBUILD_ROOT/patches/flexric-k8s-runtime.patch"
git -C src/5gdeploy apply "$REBUILD_ROOT/patches/5gdeploy-working-tree.patch"

# Working-tree diff không chứa bốn file mới này.
for f in metrics_factory.c metrics_factory.h \
  monitor/xapp_kpm_moni_write_to_csv.c \
  monitor/xapp_kpm_moni_write_to_influxdb.c; do
  cp "$REBUILD_ROOT/patches/flexric/examples/xApp/c/$f" \
     "$REBUILD_ROOT/src/flexric/examples/xApp/c/$f"
done

# Receiver URR chỉ áp cho FlexRIC standalone của Near-RT RIC.
git -C src/flexric apply "$REBUILD_ROOT/patches/flexric-xapp-urr-receiver.patch"

# Khôi phục FlexRIC nhúng như snapshot hiện tại.
git -C src/oai-ran/openair2/E2AP/flexric apply \
  "$REBUILD_ROOT/patches/flexric-working-tree.patch"
for f in metrics_factory.c metrics_factory.h \
  monitor/xapp_kpm_moni_write_to_csv.c \
  monitor/xapp_kpm_moni_write_to_influxdb.c; do
  cp "$ASSET_ROOT/src/oai-ran/openair2/E2AP/flexric/examples/xApp/c/$f" \
     "$REBUILD_ROOT/src/oai-ran/openair2/E2AP/flexric/examples/xApp/c/$f"
done

# Scenario local cũng không nằm trong aggregate diff.
cp -a "$ASSET_ROOT/src/5gdeploy/scenario/orantestbed" \
      "$REBUILD_ROOT/src/5gdeploy/scenario/"

# Patch SMF v2.2.0 chỉ ở common PFCP decoder; không update SMF wholesale.
git -C src/oai-smf/src/oai-cn5g-common-src apply --check \
  "$REBUILD_ROOT/patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch"
git -C src/oai-smf/src/oai-cn5g-common-src apply \
  "$REBUILD_ROOT/patches/oai-smf-v2.2.0-pfcp-up-features-extension.patch"
```

Loại `openair2/E2AP/flexric` khỏi patch RAN vì entry đó chỉ ghi `-dirty`, không chứa nội dung patch submodule. Các file tracked của FlexRIC nhúng và standalone hiện giống nhau, nhưng file mới CSV của hai bản khác nhau; build RAN không dùng target xApp CSV. Helper `flexric-agent` hiện chỉ chuẩn bị độ dài đường dẫn agent, không tự khôi phục toàn bộ patch của snapshot nhúng.

Các file `*.previous*` là bản sao tham chiếu, không cần để build. Nếu yêu cầu bản lưu trữ byte-for-byte cả backup và artifact thì phải copy snapshot đầy đủ; quy trình này tập trung vào source/config/build.

## 5. Từng nhóm patch khác nguyên bản ở đâu?

Danh mục mọi file patch và file đích: [LOCAL-PATCHES.md](LOCAL-PATCHES.md). Giải thích trước/sau cho từng patch: [PATCH-DETAILS.md](PATCH-DETAILS.md). So nội dung với testbed cũ: [PATCH-PROVENANCE.md](PATCH-PROVENANCE.md).

Các thay đổi có ý nghĩa chức năng:

- **UPF:** baseline đã có eBPF/XDP, PDR/FAR/QER/URR và native→SKB fallback. Commit riêng nối URR ring buffer với PFCP report; đồng bộ map key/layout và trigger, sửa phép tính thời gian, chuyển gửi qua task N4. Hỗ trợ một URR/session. Không nên viết “tự implementation toàn bộ eBPF UPF”.
- **SMF:** giữ source/tag v2.2.0; patch decoder đọc sáu octet feature đã biết và tiêu thụ extension theo length. Nó giữ FTUP, không quảng cáo support mới và không thay ngưỡng URR.
- **RAN:** E2AP v3/KPM v3, sửa gNB/DU ID, PDCP SDU volume UL/DL real thay integer để giữ mẫu <1 Mb, mở SST lên 0..255, sửa OpenSSL/C++/distro build.
- **FlexRIC:** callback mang node ID xuyên handler/dispatcher/API; `NONE_XAPP` bỏ DB; dùng metrics factory/label, lọc SST/SD, CSV/InfluxDB; tăng giới hạn đường dẫn config. CSV standalone có chuyển PDCP Mb sang byte và timestamp phục vụ đối chiếu URR.
- **5gdeploy:** dải IP, gNB ID, TAC và retry/fallback tải OAI FED; thêm scenario local nằm ngoài diff tracked.
- **Automation mới:** không thuộc upstream OAI. Port logic NIST vào layout chung, thêm profile UPF, launch nền/sudo, traffic iperf2, PFCP capture và runner KPM/URR. Test dùng mock nên không chứng minh network thật.

24 patch nhỏ khớp nguyên blob với fork NIST testbed ở SHA đã nêu. Điều này chứng minh được kế thừa ở mức nội dung, không tự xác nhận tác giả hay đã upstream vào NIST chính thức. Những patch UHD/WLS dưới source OAI vốn có trong baseline không phải delta của testbed.

## 6. Đóng gói thành một Git monorepo

Nếu cần một repo chứa toàn bộ source có thể đọc trực tiếp, dùng vendoring. Làm ở thư mục mới sau bước khôi phục source, trước khi build để không mang cache/binary sang. Giữ cây clone ở `REBUILD_ROOT` để tra lịch sử; export source đã patch vào repo mới, bỏ metadata Git lồng nhau.

```bash
MONOREPO_ROOT="$HOME/oai-codebase-monorepo"
test ! -e "$MONOREPO_ROOT"
mkdir -p "$MONOREPO_ROOT"
rsync -a --exclude='.git' --exclude='.gitmodules' \
  --exclude='/artifacts/' --exclude='/compose/' \
  "$REBUILD_ROOT/" "$MONOREPO_ROOT/"
cd "$MONOREPO_ROOT"
git init
cat > .gitignore <<'EOF'
/artifacts/
/compose/
/src/flexric/build/
/src/oai-ran/cmake_targets/ran_build/
/src/oai-ran/cmake_targets/log/
/src/oai-upf/build/upf/build/
**/node_modules/
**/__pycache__/
EOF
git add .
git status --short
git commit -m 'Vendor pinned OAI, FlexRIC and 5gdeploy with testbed integration'
```

Không dùng quy tắc bỏ toàn bộ `**/build/`: UPF có source build helper và `common-build` cần giữ. Giữ license/copyright; ghi URL/SHA và submodule SHA trong manifests. Snapshot không còn `.git` ở từng component, nên build UPF sẽ ghi label `commit:snapshot`; bổ sung checksum manifest nếu cần định danh mạnh hơn.

Phương án khác là umbrella repo + submodule trỏ fork đã commit patch. Dễ cập nhật upstream hơn nhưng cần duy trì các fork và pin commit mới của cả FlexRIC nhúng; chỉ `git add src/` khi đang chứa `.git` lồng nhau không tạo monorepo vendored hoàn chỉnh. Đây là lựa chọn tổ chức repo, không phải thay đổi đã thực hiện trong audit.

## 7. Dependency, image và build từ máy sạch

Chuẩn bị Docker/Compose, Git, rsync, Node/Corepack, Mike Farah yq v4, GCC/G++ phù hợp (testbed yêu cầu >=13), CMake/Ninja/Make, SWIG >=4.1 và dependency RAN/FlexRIC. Runtime: iperf2, iproute2/iptables, chrony, dumpcap/tshark/capinfos, ripgrep, Python3, util-linux. `build-ran.sh --install-deps` gọi OAI `build_oai -I`; `build-flexric.sh --install-deps` chỉ cài nhóm gói cơ bản, không tự nâng toàn bộ compiler.

Tại root mới, tránh biến môi trường trỏ checkout cũ:

```bash
export CODEBASE_ROOT="$PWD"
unset RAN_SRC UPF_SRC FLEXRIC_SRC DEPLOY_SRC CONFIG_ROOT CORE_OPTIONS
unset CORE_COMPOSE_DIR PATCH_ROOT FLEXRIC_PREFIX LOG_ROOT ARTIFACT_ROOT EXPERIMENT_ROOT

(cd src/5gdeploy && corepack pnpm install --frozen-lockfile)
(cd src/5gdeploy && bash types/build-schema.sh)
(cd src/5gdeploy && bash oai/download.sh v2.2.0)
(cd src/5gdeploy && bash docker/build.sh bridge)
(cd src/5gdeploy && bash docker/build.sh dn)

bash scripts/legacy/compose/build-upf.sh
bash scripts/legacy/compose/build-flexric.sh --install-deps
RADIO_TYPE=SIMU bash scripts/legacy/compose/build-ran.sh --install-deps

bash scripts/legacy/compose/configure-core.sh
bash scripts/legacy/compose/configure-flexric.sh
RADIO_TYPE=SIMU bash scripts/legacy/compose/configure-gnb.sh
RADIO_TYPE=SIMU bash scripts/legacy/compose/configure-ue.sh 1
docker compose -f compose/core/compose.yml config --quiet
```

Hai image `5gdeploy.localhost/bridge` và `5gdeploy.localhost/dn` cần build trên máy sạch; chúng không đến từ Docker Hub. `oai/download.sh` tải cấu hình FED/NWDAF, không clone source tất cả NF. Không cần chạy `src/5gdeploy/install.sh` toàn bộ chỉ để dùng OAI: script đó còn build nhiều backend ngoài phạm vi.

Tag image và gói apt không được khóa toàn bộ bằng digest/version; do đó đây chưa phải build hermetic/bit-for-bit. Sau build, ghi Docker image ID/digest, compiler, kernel, dependency lockfile, Compose và config vào artifact thí nghiệm.

## 8. Thiếu sót cần xử lý trước xác nhận eBPF runtime

**Phát hiện mới:** `configure-core.sh` chưa truyền `--oai-upf-bpf=true` cho generator. Profile hậu xử lý bật `enable_bpf_datapath` và đổi image, nhưng không thêm capability. Compose hiện cấp UPF `NET_ADMIN` và `/dev/net/tun`, trong khi `src/5gdeploy/oai/up.ts` ở nhánh BPF thêm `BPF`, `SYS_ADMIN`, `SYS_RESOURCE`. Đây là sự không nhất quán cụ thể; chưa chạy để đo lỗi runtime.

Hướng sửa đề xuất: khi profile là `xdp-skb`, truyền `--oai-upf-bpf=true` trong lời gọi `generate-core-scenario.sh`; khi `simple-switch` thì false. Để generator thiết lập cả config và capability, rồi giữ profile cho image/URR. Thêm kiểm tra Compose sinh ra và sau đó chạy thật để xác nhận kernel/capability/seccomp đủ cho loader. Audit này chỉ ghi nhận, chưa sửa script runtime.

Hai giới hạn khác: profile `xdp-skb` chưa ép mode SKB; threshold URR trong options chỉ được lưu metadata/kiểm tra, chưa cấu hình SMF. Native XDP thành công vẫn có thể kiểm chứng datapath; ngưỡng thực phải đọc từ Create URR.

Hướng dẫn chạy/thu chứng cứ sau khi xử lý cấu hình: [RUN-EBPF-UPF.md](RUN-EBPF-UPF.md). Không coi container Up hoặc image build sẵn là bằng chứng UE↔DN hoạt động.

## 9. Kết quả kiểm chứng tài liệu

- Dùng `git archive` các commit từ checkout cũ vào thư mục tạm; áp aggregate patch RAN/FlexRIC/5gdeploy. Đối chiếu byte của mọi file blob tracked trong repo chính với source hiện tại: không thấy khác biệt ở cả bốn repo. UPF so trực tiếp với `00b7485`.
- Không tính submodule là blob của repo cha; đã đối chiếu riêng các file tracked FlexRIC nhúng với standalone, không khác; CSV mới khác như đã nêu. UPF submodule SHA lấy từ manifest, không tuyên bố audit byte toàn bộ submodule.
- Patch nhỏ có thể trùng aggregate; untracked/additional files và scenario phải copy riêng. Không lấy kết quả “patch apply thành công” làm bằng chứng đã tái dựng đủ mọi file.
- Quy trình clone qua Internet và build sạch chưa được thực thi trong audit; không thay đổi deployment đang có.

## Backend Kubernetes mới

Sau các patch source ở trên, backend minikube dùng thêm `patches/oai-upf-xdp-mode.patch`, patch SMF IE 43 và chart baseline OAI có patch `patches/oai-charts-7925f93-lab.patch`. `scripts/k8s/lab.sh build` build tuần tự tools/UPF/radio/SMF, khóa image ID và tạo Helm overlay. Hướng dẫn, mapping script và trạng thái nghiệm thu nằm trong [K8S-LAB.md](K8S-LAB.md). Backend này không gọi 5gdeploy; vẫn giữ source/Compose legacy để đối chiếu.
