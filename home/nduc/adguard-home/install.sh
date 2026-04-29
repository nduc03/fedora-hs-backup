#!/usr/bin/env bash
# This is Quadlet Container Service Installer Template, to use this template:
# 1. Copy this file into your container project folder.
# 2. Rename it to 'install.sh' and make it executable: 'chmod +x install.sh'.
# 3. Customize this script as needed; recommended customization points are marked with '#*'.

set -e

#* ==========================================
#* CUSTOMIZABLE VARIABLES
#* ==========================================

#* Set to false if this container can not run rootless
ROOTLESS=true

#* Set to false if you are directly using a .container or .quadlets file that don't have .template extension
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

SERVICE_DATA_DIR="$HOME/container-data/$SERVICE_NAME"

# get host's default ipv4 address
__default_iface=$(ip route | grep default | head -n1 | awk '{print $5}')
HOST_IPV4=$(ip -4 addr show "$__default_iface" | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)
HOST_ULA_IPV6=$(ip -6 addr show | grep -oP 'fd00[:0-9a-f]+' | head -n 1)

# define quadlet file paths
QUADLET_FILENAME="$SERVICE_NAME.$FILE_TYPE"
QUADLET_FILE_LOCATION="$SCRIPT_DIR/$QUADLET_FILENAME"

echo ">>> Preparing $SERVICE_NAME Quadlet installation..."
echo "Script directory detected: $SCRIPT_DIR"

# template processing
if [[ "$USE_TEMPLATE" = "true" ]]; then
  TEMPLATE_FILENAME="$QUADLET_FILENAME.template"

  # Ensure template exists
  if [[ ! -f "$SCRIPT_DIR/$TEMPLATE_FILENAME" ]]; then
    echo "Error: $TEMPLATE_FILENAME not found in $SCRIPT_DIR."
    exit 1
  fi

  # make a temporary directory for temporary target file
  TMP_DIR=$(mktemp -d -t "$SERVICE_NAME-XXXXXXXX")
  trap "rm -rf $TMP_DIR" EXIT
  QUADLET_FILE_LOCATION="$TMP_DIR/$QUADLET_FILENAME"

  # replace %service_dir% and %host_ipv4% placeholder
  sed -e "s|%service_dir%|$SCRIPT_DIR|g" \
    -e "s|%host_ipv4%|$HOST_IPV4|g" \
    -e "s|%host_ula_ipv6%|\[$HOST_ULA_IPV6\]|g" \
    -e "s|%service_data_dir%|$SERVICE_DATA_DIR|g" \
    "$SCRIPT_DIR/$TEMPLATE_FILENAME" > "$QUADLET_FILE_LOCATION"


  #* process more %variables% or more files here if needed
  #! please note that you should modify the target file created in the previous step, not the template file
  # example: sed -i "s|%variables%|$variables|" "$QUADLET_FILE_LOCATION"
  # Detect if this is first-time setup
  CONF_DIR="$SCRIPT_DIR/conf"
  WORK_DIR="$SCRIPT_DIR/work"
  if [[ ! -d "$CONF_DIR" || ! -d "$WORK_DIR" || ! -f "$CONF_DIR/AdGuardHome.yaml" ]]; then
    echo ">>> First-time installation detected — enabling setup port 3000..."
    EXTRA_PUBLISH="PublishPort=$HOST_IPV4:3000:3000/tcp"
  else
    echo ">>> Existing configuration found — skipping setup port 3000."
    EXTRA_PUBLISH=""
  fi
  sed -i "s|%EXTRA_PORT_PLACEHOLDER%|$EXTRA_PUBLISH|" "$QUADLET_FILE_LOCATION"
  #* ...
fi

#* Custom pre installation setup here if needed

#* ...

# Setup quadlet systemd
if [[ "$ROOTLESS" = "true" ]]; then
  if [[ "$EUID" -eq 0 ]]; then
    echo "Error: You are running as root but ROOTLESS is set to true."
    echo "Please run this script without 'sudo'."
    exit 1
  fi
  SYSTEMCTL_CMD="systemctl --user"
  SUDO=""
else
  SYSTEMCTL_CMD="sudo systemctl"
  SUDO="sudo"
fi
echo ">>> Installing $QUADLET_FILENAME"
$SUDO podman quadlet install --replace "$QUADLET_FILE_LOCATION"

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
if [[ -n "$EXTRA_PUBLISH" ]]; then
  echo
  echo "AdGuardHome setup UI is available at: http://$HOST_IPV4:3000"
  echo "After completing setup, re-run ./install.sh and restart the service to lock it down."
  echo "To restart the service:"
  echo "  $SYSTEMCTL_CMD restart $SERVICE_NAME"
else
  echo
  echo "AdGuardHome is running with setup port closed."
  echo "If you haven't restarted the service:"
  echo "  $SYSTEMCTL_CMD restart $SERVICE_NAME"
fi
#* ...