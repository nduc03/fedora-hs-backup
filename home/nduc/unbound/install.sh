SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
cp "$SCRIPT_DIR"/unbound.container ~/.config/containers/systemd/unbound.container
systemctl --user daemon-reload
systemctl --user restart unbound.service
