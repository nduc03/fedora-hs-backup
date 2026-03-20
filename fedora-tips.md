# Fedora Tips & Tricks

Tổng hợp các thủ thuật hữu ích khi homelab hệ thống Fedora Linux thông qua kinh nghiệm đau thương của bản thân.

---

## 1. Quản lý SELinux File Context

Thay đổi ngữ cảnh bảo mật (security context) cho file.
```bash
# 1. Thêm định nghĩa context mới cho file (ví dụ ở đây gán type là bin_t)
sudo semanage fcontext -a -t bin_t "/usr/local/bin/myscript.sh"

# 2. Áp dụng (restore) context đã định nghĩa lên file
sudo restorecon -v /usr/local/bin/myscript.sh
```

---

## 2. Port Forwarding với Firewalld

Chuyển hướng lưu lượng từ cổng đặc quyền (Privileged Ports - dưới 1024) sang cổng thường (Unprivileged Ports - trên 1024).

**Use Case:** Rất hữu dụng khi chạy **Rootless Containers** cho các mục đích cần Privileged Ports như 80, 443, 53, và nhiều cổng khác. Container không có quyền root có thể bind vào cổng cao (ví dụ: 8000), mà người dùng vẫn có thể truy cập qua cổng chuẩn (80). Điều này giúp một vài dịch vụ như DNS, reverse proxy, vân vân, chạy hoàn toàn rootless và tăng bảo mật.

**Lưu ý:** Cách này hoạt động được với traffic từ bên ngoài vào, nhưng traffic từ bản thân server sẽ không được port forwarding.

```bash
# Chuyển hướng traffic từ Port 80 (TCP) sang Port 8000
sudo firewall-cmd --permanent --add-forward-port=port=80:proto=tcp:toport=8000

# Reload lại tường lửa để áp dụng thay đổi
sudo firewall-cmd --reload
```

hoặc muốn check rule trước khi add:
```bash
RULE="port=80:proto=tcp:toport=8000"

if ! sudo firewall-cmd --permanent --list-forward-ports | grep -q "$RULE"; then
    sudo firewall-cmd --permanent --add-forward-port=$RULE
    sudo firewall-cmd --reload
    echo "Rule added."
else
    echo "Rule already exists."
fi
```

## 3. Những đau khổ khi chuyển sang rootless podman nên nhớ

- nên bật `loginctl enable-linger $USER` để giữ container bật khi logout
- khác với rootful, ở rootless muốn trỏ ra host, ta không thể dùng LAN IP, cách đáng tin cậy duy nhất (đã được documented) để có IP trỏ ra host là `host.containers.internal` đc định nghĩa trong `/etc/hosts` của chính container, nên lên kế hoạch đối phó trước vấn đề này, ví dụ như app không đọc `/etc/hosts` có thể lỗi, thao thác cần biết trước IP host cũng không khả dụng. Nếu app ko đọc `/etc/hosts` có thể tra cứu vài trick trên google nhưng hầu hết là undocumented, nên lưu ý về tính ổn định.
- nên dùng `net.ipv4.ip_unprivileged_port_start=0` lưu vào `/etc/sysctl.d/*.conf` để bỏ bớt rào cản privileged ports cho rootless. Nếu điều kiện cho phép thì cách này ngon hơn là port forwarding ở phần 2:
    ```
    # ví dụ fedora có file 99-sysctl.conf được tạo sẵn thì ta append vào
    echo "net.ipv4.ip_unprivileged_port_start=0" | sudo tee -a /etc/sysctl.d/99-sysctl.conf
    ```

## 4. useful tips
- không lưu last access time của file: thêm noatime cho mọi phân vùng ở /etc/fstab để giảm bớt metadata write không cần thiết, tăng chút ít tuổi thọ ssd