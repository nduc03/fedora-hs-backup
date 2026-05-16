SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
cp "$SCRIPT_DIR"/unbound.container ~/.config/containers/systemd/unbound.container
mkdir -p ~/container-data/unbound/conf
source "$SCRIPT_DIR"/redis_pass.env
envsubst < "$SCRIPT_DIR"/unbound-build/unbound.conf > ~/container-data/unbound/conf/unbound.conf
systemctl --user daemon-reload
systemctl --user restart unbound.service
