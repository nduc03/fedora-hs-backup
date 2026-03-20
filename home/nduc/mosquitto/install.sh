#!/usr/bin/env bash
# This is Quadlet Container Service Installer Template, to use this template:
# 1. Copy this file into your container project folder.
# 2. Rename it to 'install.sh' and make it executable: 'chmod +x install.sh'.
# 3. Customize this script as needed; recommended customization points are marked with '#*'.

set -e

#* ==========================================
#* CUSTOMIZABLE VARIABLES
#* ==========================================

#* Set to true if this container can run rootless
ROOTLESS=true

#* Set to true if using a .container.template or .quadlets.template file
USE_TEMPLATE=true

#* Set file extension to "container" for default installation,
#* or "quadlets" to specify multiple quadlets in one file (only podman v6 above)
FILE_TYPE="container"

#* ==========================================
#* END OF CUSTOMIZABLE VARIABLES
#* ==========================================

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

# define important paths
TMP_DIR=$(mktemp -d -t "$SERVICE_NAME-XXXXXXXX")
TEMPLATE_FILE="$SERVICE_NAME.$FILE_TYPE.template"
TARGET_FILE="$SERVICE_NAME.$FILE_TYPE"
TARGET_LOCATION="$TMP_DIR/$TARGET_FILE"

echo ">>> Preparing $SERVICE_NAME Quadlet installation..."
echo "Script directory detected: $SCRIPT_DIR"

# template processing
if [[ "$USE_TEMPLATE" = "true" ]]; then
  # Ensure template exists
  if [[ ! -f "$SCRIPT_DIR/$TEMPLATE_FILE" ]]; then
    echo "Error: $TEMPLATE_FILE not found in $SCRIPT_DIR."
    exit 1
  fi
  # replace %service_dir% and %host_ipv4% placeholder
  sed "s|%service_dir%|$SCRIPT_DIR|g; s|%host_ipv4%|$HOST_IPV4|g" "$SCRIPT_DIR/$TEMPLATE_FILE" \
    > "$TARGET_LOCATION"

  #* process more %variables% or more files here if needed
  #! please note that you should modify the target file created in the previous step, not the template file
  # example: sed -i "s|%variables%|$variables|" "$TARGET_LOCATION"
  #* ...
fi

#* Custom pre installation setup here if needed
mkdir -p "$SCRIPT_DIR/config"
mkdir -p "$SCRIPT_DIR/data"
read -s -p "Create password for MQTT user 'hs': " HS_PASSWORD
echo
read -s -p "Confirm password for MQTT user 'hs': " HS_PASSWORD_CONFIRM
echo
if [[ "$HS_PASSWORD" != "$HS_PASSWORD_CONFIRM" ]]; then
  echo "Error: Passwords do not match."
  exit 1
fi
read -s -p "Create password for MQTT user 'esp32': " ESP32_PASSWORD
echo
read -s -p "Confirm password for MQTT user 'esp32': " ESP32_PASSWORD_CONFIRM
echo
if [[ "$ESP32_PASSWORD" != "$ESP32_PASSWORD_CONFIRM" ]]; then
  echo "Error: Passwords do not match."
  exit 1
fi
podman run --rm eclipse-mosquitto:openssl sh -c \
"mosquitto_passwd -b -c /tmp/pw hs $HS_PASSWORD && mosquitto_passwd -b /tmp/pw esp32 $ESP32_PASSWORD && cat /tmp/pw" 2>/dev/null | \
sudo tee ./config/pwfile
#* ...

# Setup quadlet systemd
if [[ "$ROOTLESS" = "true" ]]; then
  SYSTEMCTL_CMD="systemctl --user"
else
  SYSTEMCTL_CMD="sudo systemctl"
  SUDO="sudo"
fi
echo ">>> Installing $TARGET_FILE"
$SUDO podman quadlet install --replace "$TARGET_LOCATION"
rm -rf "$TMP_DIR" # clean up temporary directory if using template mode, do nothing if not using template

#* Uncomment if you have .network and/or .volume files to install
# echo ">>> Installing $SERVICE_NAME.network"
# $SUDO podman quadlet install "$SCRIPT_DIR/$SERVICE_NAME.network"
# echo ">>> Installing $SERVICE_NAME.volume"
# $SUDO podman quadlet install "$SCRIPT_DIR/$SERVICE_NAME.volume"

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