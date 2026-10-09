# Bộ cài Quadlet Python dùng chung

Bộ cài thay thế cách copy `install-v2.sh.template` vào từng service. Logic dùng chung nằm trong folder này; service chỉ giữ `install.toml`, template/config và các hook riêng. Python không tự đọc hay chạy `install.sh` cũ.

Folder này độc lập với `home/`. Các service hiện có chưa được chuyển đổi; việc phát triển và kiểm thử bộ cài không cài service thật.

## Yêu cầu và sử dụng

- Python **3.11+**, không cần `pip install`, Jinja2, `envsubst`, `curl` hoặc `jq` cho phần lõi.
- Cài thật trên Linux cần Podman có `quadlet install --reload-systemd=false`, systemd và các tiện ích Fedora như `ip`, `stat`, `cp`, `find`, `install`, `chown`. `ip` chỉ cần khi phải dò địa chỉ host.
- Bundle `.quadlets` cần Podman **5.8+**. Cài rootful và thao tác sửa quyền dùng `sudo`.
- Chạy bằng tài khoản thường cho cả rootless và rootful. Không gọi `sudo ./install.py`.

Đặt bộ cài tại một vị trí dùng chung, ví dụ `~/refactor-install-py/`, và đồng bộ cả `installer/` cùng `install.py` khi cập nhật. Trên Fedora, chuyển LF và cấp quyền entrypoint một lần:

```bash
cd ~/refactor-install-py
dos2unix install.py
chmod +x install.py
./install.py ten-service --dbg-templ
```

Mặc định lệnh trên tìm tại `~/ten-service`, tự chuyển working directory vào service trong thời gian chạy. Tên thư mục có khoảng trắng cần đặt trong dấu nháy. Tên service/Quadlet chuẩn hóa bằng cách đổi nhóm ký tự ngoài `A-Z`, `a-z`, `0-9`, `_`, `-` thành `-`, rồi bỏ `-` ở hai đầu.

Chỉ render các ví dụ, không cài đặt:

```bash
python3 install.py demo --services-root ./examples --dbg-templ
python3 install.py stack --services-root ./examples --dbg-templ
```

Trên Windows dùng `python` thay `python3`. `--services-root` tương đối được tính từ thư mục gọi lệnh; mặc định home không phụ thuộc CWD hoặc vị trí `install.py`.

`--dbg-templ` xuất template chính và phụ dưới `<service>/__dbg_template__/`, giữ cấu trúc thư mục. Nó không import hook, sửa quyền dữ liệu, cài Quadlet, gọi systemd hoặc AdGuard; trên Linux có thể gọi `ip` để dò địa chỉ. Với `use_template=false`, nó sao chép Quadlet gốc vào folder debug rồi kết thúc. Các file debug chứa giá trị sau render, được tạo riêng tư và có `.gitignore`.

Khi đã chuẩn bị service thật, lệnh không có `--dbg-templ` sẽ thực hiện cài đặt:

```bash
./install.py ten-service
./install.py ten-service --services-root /duong-dan/chua-services
```

## Cấu hình của một service

Ví dụ `~/ten-service/`:

```text
install.toml
ten-service.container.template
ctv.env                         # tùy chọn, không commit secrets
config/
hooks/pre_install.py             # tùy chọn
hooks/post_install.py            # tùy chọn
```

`install.toml` tối thiểu có thể rỗng khi dùng toàn bộ mặc định. Ví dụ đầy đủ:

```toml
rootless = true
use_template = true
file_type = "container"
use_traefik_labels = false
enable_public_domain = false
mount_dirs = ["data", "logs"]
config_dirs = ["config"]
extra_template_files = ["config/app.conf.template", "ten-service.env.template"]
# service_data_dir = "~/container-data/ten-service"
container_uid = 1000
container_gid = 1000
# systemd_units = ["ten-service.service"]

[variables]
IMAGE = "docker.io/library/nginx:alpine"
PRIVATE_DOMAIN = "hs.lan"
# HOST_IPV4 = "192.0.2.10"
# HOST_ULA_IPV6 = "fd00::10"

[hooks]
pre_install = ["hooks/pre_install.py:run"]
post_install = ["hooks/post_install.py:run"]
```

Mặc định: rootless/template bật; `file_type="container"`; Traefik/public domain tắt; các danh sách rỗng; container UID/GID `1000:1000`; dữ liệu tại `~/container-data/<service_name>`; unit `<service_name>.service`. `service_data_dir` nhận đường dẫn tuyệt đối, `~/...`, hoặc tương đối bên trong service. UID/GID tài khoản host lấy từ hệ thống, không mặc định là 1000. Quadlet rootless cài tại `~/.config/containers/systemd`, hoặc `$XDG_CONFIG_HOME/containers/systemd` nếu environment của tiến trình đặt gốc XDG tuyệt đối; rootful tại `/etc/containers/systemd`.

Các đường dẫn mount/config/template/hook phải tương đối và không chứa `..` hay thoát khỏi gốc qua symlink. Tùy chọn không được hỗ trợ, sai kiểu, template/hook cần dùng bị thiếu hoặc bundle không hợp lệ đều làm dừng cài đặt. Nguồn `config_dirs` chưa tồn tại thì cảnh báo và bỏ qua copy, giống template Bash.

Nếu `use_template=false`, đầu vào là `<service_name>.container` hoặc `.quadlets`; bộ cài không thay biến, chèn label hay xử lý template phụ. Các `.network`/`.volume` phụ vẫn được cài nếu có.

## Biến môi trường và template

Thứ tự ghi đè:

1. Environment của tiến trình.
2. `~/hs-info.env` nếu tồn tại.
3. Các `ctv.env` bên trong service, theo thứ tự đường dẫn tương đối đã sắp xếp; bỏ qua `.git`, `__pycache__`, `__dbg_template__`.
4. `[variables]` trong `install.toml`.
5. Các biến nội bộ của context, bảo đảm đường dẫn phản ánh nơi bộ cài thực sự làm việc.

`.env` là dữ liệu literal: hỗ trợ `KEY=value`, `export KEY=value`, dòng comment và giá trị có dấu nháy đơn/kép. Bỏ dấu nháy bao ngoài nhưng giữ nguyên nội dung, kể cả `$VAR`, `${VAR}`, backslash, backtick và `$(command)`. Comment cuối giá trị không có nháy cần được ngăn bằng khoảng trắng; `#` bên trong giá trị có nháy hoặc `x#fragment` là dữ liệu. Không hỗ trợ multiline hoặc diễn giải escape như Bash. Dòng không phải phép gán báo lỗi kèm file/dòng, không in giá trị.

```dotenv
PUBLIC_DOMAIN=example.test
ADGUARD_USERNAME=admin
ADGUARD_PASSWORD='mat-khau-co-$-va-#'
```

Template hỗ trợ `$VAR` và `${VAR}`, phân biệt hoa/thường. Chỉ thay biến đã khai báo trong một lượt; không mở rộng tiếp giá trị được chèn. Không thực thi lệnh hoặc xử lý `${VAR:-default}`. Renderer không coi `$$` là escape: với `A=ok`, `$$A` thành `$ok`, tương tự `envsubst`; hash mật khẩu literal phổ biến được bảo toàn. Biến rỗng có khai báo được thay bằng chuỗi rỗng.

Biến chưa khai báo giữ nguyên; cảnh báo file/tên biến. Debug chỉ cảnh báo. Cài thật hỏi `(y/N)`; môi trường không tương tác tự dừng, trừ khi chọn `--allow-unresolved`. Dùng cờ này khi chủ động giữ biến runtime của systemd/container. Renderer không cảnh báo lại ký tự `$` nằm trong giá trị đã chèn.

Các biến nội bộ: `SERVICE_DIR`, `SCRIPT_DIR`, `SCRIPT_DIR_NAME`, `SERVICE_NAME`, `SERVICE_DATA_DIR`, `INSTALL_LOCATION`, `HOST_IPV4`, `HOST_ULA_IPV6`, `SUDO`, `SYSTEMCTL_CMD`. Hai biến địa chỉ có thể đặt bằng env hoặc `[variables]`; nếu thiếu thì dò interface có IPv4 default route trên Linux. ULA hỗ trợ cả `fc00::/7`, fallback `::1`. Trong context IPv6 là địa chỉ raw; trong mapping template `HOST_ULA_IPV6` có ngoặc vuông để giữ cách dùng hiện tại.

Template chính render vào staging; template phụ chỉ xuất sang service sau khi kiểm tra và xác nhận biến. File phụ `.env` được tạo mode 600; file phụ khác mode 644. Bộ cài không chuyển `%service_dir%` hay các placeholder legacy; hãy đổi thủ công sang cú pháp `$...` khi chuyển từng service.

## Module và hook

`install.py` chỉ là entrypoint. Package `installer` chia theo nhiệm vụ: `config`, `environment`, `context`, `templates`, `filesystem`, `quadlet`, `systemd`, `traefik`, `adguard`, `hooks`, `commands`; `cli` điều phối pipeline.

Mỗi hook là callable nhận đúng một `InstallContext`. Có thể cấu hình nhiều module/callable cho mỗi giai đoạn; chạy theo thứ tự khai báo. Hook có thể import helper chung từ `installer` hoặc helper riêng từ gốc service.

```python
from installer.context import InstallContext


def run(context: InstallContext) -> None:
    context.log(f">>> Chuẩn bị {context.service_name}")
    context.runner.run(["restorecon", "-R", str(context.service_data_dir)])
    # privileged=True chỉ cho thao tác cần sudo.
```

Context cung cấp cấu hình, đường dẫn, tên service, địa chỉ host raw, mapping biến, `systemctl_argv`, `systemd_units`, `log` và runner. Runner dùng argv, không `shell=True`, đặt `cwd` tại service; `privileged=True` thêm `sudo`; `check=False` trả về mã lỗi cho caller tự xử lý.

Hook chạy sau render, nên thay `context.variables` trong `pre_install` không render lại template. Biến template và đường dẫn dữ liệu nên đặt trong TOML/env trước khi chạy. Hook cần dùng `context.systemctl_argv` cùng `privileged=not context.config.rootless` khi tự gọi systemd. Debug không import cả module hook, tránh cả side effect ở cấp module.

## Quadlet, systemd, Traefik và DNS

Pipeline cài thật: kiểm tra Linux/user/config → nạp biến/render/kiểm tra đầu vào → kiểm tra capability Podman và các điều kiện cài đặt → xuất template phụ → tạo mount/copy config/sửa quyền → `pre_install` → snapshot/cài Quadlet → cập nhật systemd → `post_install` → DNS AdGuard.

`config_dirs` được copy đè vào dữ liệu bằng cách merge, không xóa các file cũ không có trong nguồn. Giữ cách cấp mode của Bash: thư mục 755, file 644. Chế độ rootless đưa quyền config về tài khoản host để copy, rồi chuyển sang UID/GID trong namespace Podman; mount có ownership đúng thì bỏ qua `chown`. Rootful dùng quyền cao cho thao tác filesystem và không gọi `podman unshare`.

Quadlet chính là `<service_name>.container[.template]` hoặc `.quadlets[.template]`. File `<service_name>.network` và `.volume` phụ được cài nếu có; nếu render chúng từ template phụ, dùng bản staged. Bundle cần khai báo `systemd_units` và mỗi phần có `# FileName=<stem>` cùng một section tài nguyên, ngăn bằng dòng `---`. Podman tự thêm đuôi loại tài nguyên vào stem; không thêm `.container` vào `FileName`.

```toml
file_type = "quadlets"
systemd_units = ["stack.service", "stack-worker.service"]
```

Ví dụ hoàn chỉnh nằm trong `examples/stack/`. Parser nhận Container, Network, Volume, Pod, Image, Build, Kube và Artifact; Podman trên host vẫn phải hỗ trợ loại tài nguyên đó. Unit cần quản lý là unit khai báo trong TOML; bộ cài không đoán tên các unit sinh từ Pod/Kube/`ServiceName=`.

Chỉ snapshot/xóa/thay definition thuộc các nguồn cài của lần chạy này. Bỏ qua nguồn có nội dung giống snapshot để giữ nguyên metadata và tránh cảnh báo `NeedDaemonReload`. Với nguồn thay đổi, giữ workaround xóa definition cũ trước `podman quadlet install --replace`, nhưng luôn có backup; truyền `--reload-systemd=false` để tự quyết định reload. Nội dung thay đổi thì daemon-reload một lần và restart các unit đã chọn. Không đổi thì chỉ start unit đang dừng, không reload/restart. Không tự xóa member cũ đã bỏ khỏi bundle; hãy xử lý việc gỡ unit riêng khi chuyển đổi service.

Lỗi trong bước cài Quadlet khôi phục nội dung/mode các definition cũ và xóa definition mới của lần chạy. Nếu khôi phục thất bại, giữ backup ở thư mục recovery riêng trong temp và in đường dẫn. Rollback này không bao gồm dữ liệu, template phụ, hook, trạng thái runtime hay metadata ứng dụng của Podman. Lỗi systemd/post-hook/DNS dừng tại bước lỗi và không tự rollback các bước đã thành công.

Traefik tự chèn network và label LAN ngay dưới `[Container]`, dùng `PRIVATE_DOMAIN` hoặc fallback `hs.lan`. Bật `enable_public_domain` thêm router public với `leresolver`. Trong bundle, label tự động chỉ áp dụng cho container chính có `FileName=<service_name>`; container khác tự định nghĩa routing để không trùng router.

`enable_public_domain` cũng bật đăng ký AdGuard, cần `PUBLIC_DOMAIN`, `ADGUARD_USERNAME`, `ADGUARD_PASSWORD`. API dùng HTTPS `https://dns.<PUBLIC_DOMAIN>/control`, Basic Auth và timeout 30 giây; giữ xác minh TLS mặc định. Đọc `/rewrite/list`, chỉ POST `/rewrite/add` cho cặp domain/địa chỉ chưa có, bao gồm IPv4 và ULA thực sự; không dùng `::1`, link-local hoặc IPv6 global làm rewrite ULA. Credentials chỉ gửi trong header, không ghi vào log lỗi HTTP.

Nếu image container sau render là `adguard/adguardhome` (có thể có registry,
tag hoặc digest), bộ cài bỏ qua kiểm tra credential và mọi API DNS để bootstrap
AdGuard Home. Bundle chứa container này cũng bỏ qua DNS. Cờ public domain và
label Traefik vẫn giữ nguyên; service dùng image khác vẫn đăng ký DNS như trên.

## Kiểm thử

Từ folder bộ cài:

```bash
python3 -m unittest discover -s tests -v
```

Test dùng thư mục tạm, mock subprocess/HTTP và filesystem simulation; không chạy Podman, systemd, sudo hay AdGuard thật. Có kiểm thử CLI debug với cả hai service mẫu, xác nhận hook không được import và không xuất template phụ ra ngoài folder debug. Việc test qua trên Windows không xác nhận hành vi runtime của Fedora/Podman đã triển khai.

Đã kiểm chứng thêm service `share` (PsiTransfer) chạy rootless thật trên instance
WSL 2 Fedora 44 riêng, với cấu hình giả và không dùng Traefik: HTTP từ Windows/WSL,
cài lại không restart, và tự khởi động sau khi mở lại instance. Xem
[hướng dẫn dựng lab](wsl-lab/README.md) và [kết quả/log](wsl-lab/RESULTS.md).

Tài liệu tham chiếu: [Python tomllib](https://docs.python.org/3/library/tomllib.html), [Podman Quadlet install](https://docs.podman.io/en/latest/markdown/podman-quadlet-install.1.html), [parser bundle của Podman](https://github.com/containers/podman/blob/main/pkg/domain/infra/abi/quadlet.go).
