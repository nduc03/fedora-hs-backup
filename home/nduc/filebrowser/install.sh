chmod +x filebrowser
sudo cp filebrowser.service /etc/systemd/system/
sudo chcon -t bin_t filebrowser
sudo systemctl daemon-reload
sudo systemctl enable --now filebrowser.service
