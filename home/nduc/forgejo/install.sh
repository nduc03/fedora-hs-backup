#!/usr/bin/env bash

# This is Quadlet Container Service Installer Template, to use this template:
# 1. Copy this file into the container project folder.
# 2. Rename it `mv install.sh.template install.sh` and make it executable `chmod +x install.sh`.
# 3. Customize this script as needed; recommended customization points are marked with '#*'.

set -e

#* ==========================================
#* 1. CUSTOMIZABLE VARIABLES
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

#* ==========================================
#* 2. CUSTOMIZABLE HOOKS (PRE/POST INSTALL)
#* ==========================================
#* Các tham số khả dụng trong hàm:
#* $1: SCRIPT_DIR       - Đường dẫn thư mục chứa script này
#* $2: SCRIPT_DIR_NAME  - Tên thư mục cha chứa script này
#* $3: SERVICE_NAME     - Tên Service sau khi đã chuẩn hóa
#* $4: SERVICE_DATA_DIR - Thư mục lưu dữ liệu (~/container-data/...)
#* $5: HOST_IPV4        - Địa chỉ IPv4 của máy chủ
#* $6: HOST_ULA_IPV6    - Địa chỉ IPv6 nội bộ (ULA) của máy chủ

pre_install() {
  local SCRIPT_DIR="$1"
  local SCRIPT_DIR_NAME="$2"
  local SERVICE_NAME="$3"
  local SERVICE_DATA_DIR="$4"
  local HOST_IPV4="$5"
  local HOST_ULA_IPV6="$6"

  echo ">>> Running pre-install hooks for: $SERVICE_NAME"

  echo "setup forgejo volumes"
  mkdir -p $SERVICE_DATA_DIR/forgejo
  mkdir -p $SERVICE_DATA_DIR/conf
  mkdir -p $SERVICE_DATA_DIR/data
}

post_install() {
  :
}

#* ==========================================
#* 3. CUSTOMIZABLE TEMPLATE VARIABLES
#* ==========================================
#* an associative array to hold custom template variables and their values
#* which are about to be injected into the template
declare -A CTV
#* --- VÍ DỤ CẤU HÌNH ---
#* Nếu trong file .template có thông tin như: "Environment=DB_PASSWORD=%pass%"
#* Hãy khai báo như bên dưới:
#* CTV["%pass%"]="mysecretpassword"
#* ----------------------

# ==========================================
# 4. VARIABLE CALCULATION LOGIC
# ==========================================

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
HOST_ULA_IPV6=$(ip -6 addr show "$__default_iface" | grep -oP 'fd00[:0-9a-f]+' | head -n 1)

# define quadlet file paths
QUADLET_FILENAME="$SERVICE_NAME.$FILE_TYPE"
QUADLET_FILE_LOCATION="$SCRIPT_DIR/$QUADLET_FILENAME"

ARGS=("$SCRIPT_DIR" "$SCRIPT_DIR_NAME" "$SERVICE_NAME" "$SERVICE_DATA_DIR" "$HOST_IPV4" "$HOST_ULA_IPV6")

echo ">>> Preparing $SERVICE_NAME Quadlet installation..."
echo "Script directory detected: $SCRIPT_DIR"

# ==========================================
# 5. EXECUTION
# ==========================================

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
  echo ">>> Injecting variables into template..."
  sed -e "s|%service_dir%|$SCRIPT_DIR|g" \
    -e "s|%host_ipv4%|$HOST_IPV4|g" \
    -e "s|%host_ula_ipv6%|\[$HOST_ULA_IPV6\]|g" \
    -e "s|%service_data_dir%|$SERVICE_DATA_DIR|g" \
    "$SCRIPT_DIR/$TEMPLATE_FILENAME" > "$QUADLET_FILE_LOCATION"


  echo ">>> Injecting custom variables into template..."
  for key in "${!CTV[@]}"; do
    value="${CTV[$key]}"
    echo "Injecting %$key% with value: $value"
    sed -i "s|$key|$value|g" "$QUADLET_FILE_LOCATION"
  done

fi

pre_install "${ARGS[@]}"

# Setup quadlet systemd
if [[ "$ROOTLESS" = "true" ]]; then
  if [[ "$EUID" -eq 0 ]]; then
    echo "Error: You are running as root but ROOTLESS is set to true."
    echo "Please run this script without 'sudo'."
    exit 1
  fi
  INSTALL_LOCATION="$HOME/.config/systemd/user"
  SYSTEMCTL_CMD="systemctl --user"
  SUDO=""
else
  INSTALL_LOCATION="/etc/systemd/system"
  SYSTEMCTL_CMD="sudo systemctl"
  SUDO="sudo"
fi
echo ">>> Installing $QUADLET_FILENAME"

# due to `podman quadlet install` bug, we still need to remove the old file before installing the new one
$SUDO rm -f "$INSTALL_LOCATION/$SERVICE_NAME.container"
$SUDO podman quadlet install --replace "$QUADLET_FILE_LOCATION"

if [[ -f "$SCRIPT_DIR/$SERVICE_NAME.network" ]]; then
    echo ">>> Found network file. Installing $SERVICE_NAME.network"
    $SUDO rm -f "$INSTALL_LOCATION/$SERVICE_NAME.network"
    $SUDO podman quadlet install --replace "$SCRIPT_DIR/$SERVICE_NAME.network"
fi
if [[ -f "$SCRIPT_DIR/$SERVICE_NAME.volume" ]]; then
    echo ">>> Found volume file. Installing $SERVICE_NAME.volume"
    $SUDO rm -f "$INSTALL_LOCATION/$SERVICE_NAME.volume"
    $SUDO podman quadlet install --replace "$SCRIPT_DIR/$SERVICE_NAME.volume"
fi

echo ">>> Reloading systemd daemon to recognize new Quadlet"
$SYSTEMCTL_CMD daemon-reload

echo ">>> Starting $SERVICE_NAME container..."
$SYSTEMCTL_CMD start $SERVICE_NAME

post_install "${ARGS[@]}"

echo ">>> Done!"
echo
echo "To check status:"
echo "  $SYSTEMCTL_CMD status $SERVICE_NAME"
