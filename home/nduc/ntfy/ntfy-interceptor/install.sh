cp ntfy-interceptor ~/ntfy/
cp ntfy-interceptor.service ~/.config/systemd/user/
chmod +x ~/ntfy/ntfy-interceptor
systemctl --user daemon-reload
systemctl --user enable ntfy-interceptor.service
systemctl --user restart ntfy-interceptor.service
echo "Ntfy Interceptor đã được cài đặt và khởi động thành công!"
systemctl status ntfy-interceptor.service