#!/usr/bin/env bash
# This is Quadlet Container Service Installer Template, to use this template:
# 1. Copy this file into your container project folder.
# 2. Rename it to 'install.sh' and make it executable: 'chmod +x install.sh'.
# 3. Customize this script as needed; recommended customization points are marked with '#*'.

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
USE_TEMPLATE=true  #* set to true if using a .container.template file
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
  # replace %service_dir% and %host_ipv4% placeholder
  sed "s|%service_dir%|$SCRIPT_DIR|g; s|%host_ipv4%|$HOST_IPV4|g" "$SCRIPT_DIR/$TEMPLATE_FILE" \
    > "$SCRIPT_DIR/$TARGET_FILE"

  #* process more %variables% or more files here if needed
  #* please note that you should modify the target file created in the previous step, not the template file
  # example: sed -i "s|%variables%|$variables|" "$SCRIPT_DIR/$TARGET_FILE"
  #* ...
fi

#* Custom pre installation setup here if needed
mkdir -p "$SCRIPT_DIR/config"
#* ...

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

#* Uncomment if you have .network and/or .volume files to install
# echo ">>> Copying $SERVICE_NAME.network to $SYSTEMD_DIR"
# $SUDO cp "$SCRIPT_DIR/$SERVICE_NAME.network" "$SYSTEMD_DIR/$SERVICE_NAME.network"
# echo ">>> Copying $SERVICE_NAME.volume to $SYSTEMD_DIR"
# $SUDO cp "$SCRIPT_DIR/$SERVICE_NAME.volume" "$SYSTEMD_DIR/$SERVICE_NAME.volume"

echo ">>> Reloading systemd daemon to recognize new Quadlet"
$SYSTEMCTL_CMD daemon-reload

echo ">>> Starting $SERVICE_NAME container..."
$SYSTEMCTL_CMD start $SERVICE_NAME

echo ">>> Done!"
echo
echo "To check status:"
echo "  $SYSTEMCTL_CMD status $SERVICE_NAME"

#* Custom post installation setup here if needed

#* ...