#!/usr/bin/env bash
set -e

# Determine the script's absolute directory
SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

# get script directory name which will be used as service name
SCRIPT_DIR_NAME="$(basename "$SCRIPT_DIR")"

# sanitize service name (example: My Service (v1.0)! -> My-Service-v1-0)
SERVICE_NAME=$(printf '%s\n' "$SCRIPT_DIR_NAME" | awk '{
    g=$0;
    # replace non-alnum/_/- with hyphen
    g=gensub(/[^[:alnum:]_-]+/, "-", "g", g);
    # remove leading hyphen
    g=gensub(/^-+/, "", "g", g);
    # remove trailing hyphen
    g=gensub(/-+$/, "", "g", g);
    print g
}')

# get host's default ipv4 address
__default_iface=$(ip route | grep default | head -n1 | awk '{print $5}')
HOST_IPV4=$(ip -4 addr show "$__default_iface" | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)

TEMPLATE_FILE="$SERVICE_NAME.container.template"
TARGET_FILE="$SERVICE_NAME.container"
ROOTLESS=true #* set to true if this container can run rootless
USE_TEMPLATE=false  #* set to true if using a .container.template file

INSTALL="cp"

echo ">>> Preparing $SERVICE_NAME Quadlet installation..."
echo "Script directory detected: $SCRIPT_DIR"

# template processing
if [[ "$USE_TEMPLATE" = "true" ]]; then
  # Ensure template exists
  if [[ ! -f "$SCRIPT_DIR/$TEMPLATE_FILE" ]]; then
    echo "Error: $TEMPLATE_FILE not found in $SCRIPT_DIR."
    exit 1
  fi
  INSTALL="mv"
  # replace %script_dir% and %host_ipv4% placeholder
  sed "s|%script_dir%|$SCRIPT_DIR|g; s|%host_ipv4%|$HOST_IPV4|g" "$SCRIPT_DIR/$TEMPLATE_FILE" \
    > "$SCRIPT_DIR/$TARGET_FILE"
fi

# Setup quadlet systemd
if [[ "$ROOTLESS" = "true" ]]; then
  SYSTEMCTL_CMD="systemctl --user"
  SYSTEMD_DIR="$HOME/.config/containers/systemd/"
  SUDO=""
else
  SYSTEMCTL_CMD="sudo systemctl"
  SYSTEMD_DIR="/etc/containers/systemd/"
  SUDO="sudo"
fi
echo ">>> Installing $TARGET_FILE to $SYSTEMD_DIR"
$SUDO mkdir -p "$SYSTEMD_DIR"
# $TO expands to nothing, just for readability
$SUDO $INSTALL "$SCRIPT_DIR/$TARGET_FILE" $TO "$SYSTEMD_DIR/$TARGET_FILE"

echo ">>> Reloading systemd daemon to recognize new Quadlet"
$SYSTEMCTL_CMD daemon-reload

echo ">>> Starting $SERVICE_NAME container..."
$SYSTEMCTL_CMD start $SERVICE_NAME

echo ">>> Done!"
echo
echo "To check status:"
echo "  $SYSTEMCTL_CMD status $SERVICE_NAME"
