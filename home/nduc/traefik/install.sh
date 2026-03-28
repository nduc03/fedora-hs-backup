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

#* Add more customizable variables here if needed, for example:
#* MY_CUSTOM_LOG="/path/to/custom.log"

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
#* $7: SUDO             - Biến chứa "sudo" nếu rootless = true, hoặc rỗng nếu false
#* $8: INSTALL_LOCATION - Đường dẫn thư mục cài đặt Quadlet
#* $9: SYSTEMCTL_CMD    - Lệnh systemctl đã được điều chỉnh cho root hoặc user

pre_install() {
  local SCRIPT_DIR="$1"
  local SCRIPT_DIR_NAME="$2"
  local SERVICE_NAME="$3"
  local SERVICE_DATA_DIR="$4"
  local HOST_IPV4="$5"
  local HOST_ULA_IPV6="$6"
  local SUDO="$7"
  local INSTALL_LOCATION="$8"
  local SYSTEMCTL_CMD="$9"

  echo ">>> Running pre-install hooks for: $SERVICE_NAME"

  rm -f "$SCRIPT_DIR/mycert/.gitignore" || true
  rm -f "$SCRIPT_DIR/secret/.gitignore" || true
  rm -f "$SCRIPT_DIR/secret/ctv.env" || true

  mv "$SCRIPT_DIR/mycert/"  "$SERVICE_DATA_DIR/mycert" || true
  mv "$SCRIPT_DIR/config/"  "$SERVICE_DATA_DIR/config" || true
  mv "$SCRIPT_DIR/secrets/" "$SERVICE_DATA_DIR/secret" || true
}

post_install() {
  local SCRIPT_DIR="$1"
  local SCRIPT_DIR_NAME="$2"
  local SERVICE_NAME="$3"
  local SERVICE_DATA_DIR="$4"
  local HOST_IPV4="$5"
  local HOST_ULA_IPV6="$6"
  local SUDO="$7"
  local INSTALL_LOCATION="$8"
  local SYSTEMCTL_CMD="$9"

  echo ">>> Running post-install hooks for: $SERVICE_NAME"

}

#* =========================================
#* 3. CUSTOMIZABLE TEMPLATE VARIABLES
#* =========================================
#* declare an associative array to hold custom template variables and their values
#* which are about to be injected into the template
declare -A CTV
#* --- VÍ DỤ CẤU HÌNH ---
#* Nếu trong file .template có thông tin như: "Environment=DB_PASSWORD=%pass%"
#* Hãy khai báo như bên dưới:
#* CTV["%pass%"]="mysecretpassword"
#* CTV["%app_port%"]="8080"
CTV["%domain%"]="hs.lan"
#* -----------------------------------------


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

#?? want to custom data directory?
#** recommended way is redefine in pre_install hook
#!! directly change this is not recommended, as it may cause issues with future updates of the script
SERVICE_DATA_DIR="$HOME/container-data/$SERVICE_NAME"

# get host's default ipv4 address
__default_iface=$(ip route | grep default | head -n1 | awk '{print $5}')
HOST_IPV4=$(ip -4 addr show "$__default_iface" | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)
HOST_ULA_IPV6=$(ip -6 addr show "$__default_iface" | grep -oP 'fd00[:0-9a-f]+' | head -n 1)
# Bổ sung fallback về ::1 nếu không có ULA IPv6
HOST_ULA_IPV6=${HOST_ULA_IPV6:-::1}

# define quadlet file paths
QUADLET_FILENAME="$SERVICE_NAME.$FILE_TYPE"
QUADLET_FILE_LOCATION="$SCRIPT_DIR/$QUADLET_FILENAME"

if [[ "$ROOTLESS" = "true" ]]; then
  INSTALL_LOCATION="$HOME/.config/containers/systemd/"
  SYSTEMCTL_CMD="systemctl --user"
  SUDO=""
else
  INSTALL_LOCATION="/etc/containers/systemd/"
  SYSTEMCTL_CMD="sudo systemctl"
  SUDO="sudo"
fi

# make a temporary directory for temporary target file or backup old quadlets file
TMP_DIR=$(mktemp -d -t "$SERVICE_NAME-XXXXXXXX")
trap "rm -rf $TMP_DIR; unset SEARCH_KEY REPLACE_VAL" EXIT
QUADLET_FILE_LOCATION="$TMP_DIR/$QUADLET_FILENAME"

BACKUP_DIR="$TMP_DIR/backup"

TRAEFIK_LABELS=$(cat << EOF
Label=host.subdomain=$SERVICE_NAME
Label=traefik.http.routers.$SERVICE_NAME.entrypoints=websecure
Label=traefik.http.routers.$SERVICE_NAME.service=api@internal
Label=traefik.http.routers.$SERVICE_NAME.tls=true
Label=traefik.http.services.$SERVICE_NAME.loadbalancer.server.url=http://host.container.internal:$HTTP_PORT
EOF
)

HOOK_ARGS=("$SCRIPT_DIR" "$SCRIPT_DIR_NAME" "$SERVICE_NAME"
      "$SERVICE_DATA_DIR" "$HOST_IPV4" "$HOST_ULA_IPV6"
      "$SUDO" "$INSTALL_LOCATION" "$SYSTEMCTL_CMD")

# ==========================================
# 5. AUTOMATIC TEMPLATE VARIABLES
# ==========================================

echo ">>> Auto-detecting ctv.env files for template injection..."

# Tìm tất cả các file ctv.env và duyệt qua từng file một
while IFS= read -r __ctv_env_path; do
  if [[ -f "$__ctv_env_path" ]]; then
    echo ">>> Found ctv.env at: $__ctv_env_path"
    echo ">>> Sourcing environment variables from this file..."
    source "$__ctv_env_path"

    echo ">>> Auto-mapping variables from $(basename "$__ctv_env_path") to CTV array..."
    # Đọc từng dòng trong file ctv.env để tự động map
    while IFS= read -r line || [[ -n "$line" ]]; do
      # Bỏ qua các dòng trống hoặc dòng comment (#)
      if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
        continue
      fi

      # 1. Tách Key và Value trực tiếp từ chuỗi (không dùng awk để tránh rườm rà)
      line_clean="${line#export }"     # Loại bỏ chữ 'export ' nếu có
      var_name="${line_clean%%=*}"     # Lấy tên biến (trước dấu = đầu tiên)
      raw_value="${line_clean#*=}"     # Lấy giá trị gốc (sau dấu = đầu tiên)

      # 2. Xóa dấu nháy đơn hoặc nháy kép bao quanh giá trị (nếu user có bọc)
      if [[ "$raw_value" =~ ^\".*\"$ ]] || [[ "$raw_value" =~ ^\'.*\'$ ]]; then
        raw_value="${raw_value:1:-1}"
      fi

      # Kiểm tra xem tên biến có hợp lệ theo chuẩn Bash không (tránh lỗi indirection)
      if [[ "$var_name" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
        # 1. Chuyển tên biến thành chữ thường: ${var_name,,}
        # 2. Bọc trong dấu %: placeholder
        placeholder="%${var_name,,}%"

        # Cảnh báo nếu biến đã được map trước đó từ một file ctv.env khác và yêu cầu xác nhận
        if [[ -v CTV["$placeholder"] ]]; then
          echo ""
          echo "    [WARNING] Variable '$var_name' is defined multiple times!"
          echo "              This causes confusion in predicting which value is ultimately selected."
          echo "              It can lead to instability, where different installations"
          echo "              might produce unpredictable or unintended results."
          echo "              Please consolidate your variables to avoid unexpected behaviors."

          read -p "    Do you want to overwrite the value of $var_name and continue? (y/N) " -n 1 -r
          echo ""

          if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "    [ABORT] Installation aborted by user due to variable conflict."
            exit 1
          fi
        else
          echo ">>> Found a valid variable $var_name."
        fi

        # 3. gán giá trị thực tế của biến vào mảng CTV với key là placeholder
        CTV["$placeholder"]="$raw_value"

        echo "    [Auto-mapped] $var_name -> $placeholder"
      else
        echo "    [Warning] Skipping invalid variable name '$var_name' in ctv.env"
      fi
    done < "$__ctv_env_path"
  fi
done < <(find "$SCRIPT_DIR" -name "ctv.env")

# ==========================================
# 6. EXECUTION
# ==========================================
echo ">>> Validating execution environment..."

if [[ "$EUID" -eq 0 ]]; then
  echo ""
  echo "[ERROR] Root privileges detected."
  echo "        Please run this script as a standard user (or without 'sudo')."
  echo "        Note: The script will automatically request 'sudo' access when necessary. " \
       "Therefore, running this script with 'sudo' is not supported."
  echo ""
  exit 1
fi

echo ">>> Preparing $SERVICE_NAME Quadlet installation..."
echo "Script directory detected: $SCRIPT_DIR"

mkdir -p "$BACKUP_DIR"

# template processing
if [[ "$USE_TEMPLATE" = "true" ]]; then
  TEMPLATE_FILENAME="$QUADLET_FILENAME.template"

  # Ensure template exists
  if [[ ! -f "$SCRIPT_DIR/$TEMPLATE_FILENAME" ]]; then
    echo "Error: $TEMPLATE_FILENAME not found in $SCRIPT_DIR."
    exit 1
  fi

  # replace predefined placeholder
  echo ">>> Injecting variables into template..."
  sed -e "s|%service_dir%|$SCRIPT_DIR|g" \
    -e "s|%host_ipv4%|$HOST_IPV4|g" \
    -e "s|%host_ula_ipv6%|\[$HOST_ULA_IPV6\]|g" \
    -e "s|%service_data_dir%|$SERVICE_DATA_DIR|g" \
    "$SCRIPT_DIR/$TEMPLATE_FILENAME" > "$QUADLET_FILE_LOCATION"

 # Inject TRAEFIK_LABELS if USE_TRAEFIK_LABELS is true
  if [[ "$USE_TRAEFIK_LABELS" == "true" ]]; then
    export SEARCH_KEY="==%traefik_labels%=="
    export REPLACE_VAL="$TRAEFIK_LABELS"

    echo ">>> Processing TRAEFIK_LABELS injection..."
    awk '
    BEGIN { search = ENVIRON["SEARCH_KEY"]; replace = ENVIRON["REPLACE_VAL"]; len = length(search) }
    {
        while ( (idx = index($0, search)) > 0 ) {
            $0 = substr($0, 1, idx - 1) replace substr($0, idx + len)
        }
        # Nếu người dùng không dùng Traefik (replace == ""), bỏ qua việc in dòng trống để file config sạch hơn
        if ($0 ~ /^[[:space:]]*$/ && replace == "") next;
        print
    }' "$QUADLET_FILE_LOCATION" > "${QUADLET_FILE_LOCATION}.tmp" && mv "${QUADLET_FILE_LOCATION}.tmp" "$QUADLET_FILE_LOCATION"
  fi


  echo ">>> Injecting custom variables into template..."
  for key in "${!CTV[@]}"; do
    value="${CTV[$key]}"
    echo "Injecting $key"

    # awk is a safer choice than sed for arbitrary replacement values, as it can handle special characters
    export SEARCH_KEY="$key"
    export REPLACE_VAL="$value"

    awk '
    BEGIN { search = ENVIRON["SEARCH_KEY"]; replace = ENVIRON["REPLACE_VAL"]; len = length(search) }
    {
        while ( (idx = index($0, search)) > 0 ) {
            $0 = substr($0, 1, idx - 1) replace substr($0, idx + len)
        }
        print
    }' "$QUADLET_FILE_LOCATION" > "${QUADLET_FILE_LOCATION}.tmp" && mv "${QUADLET_FILE_LOCATION}.tmp" "$QUADLET_FILE_LOCATION"
  done

fi

# validate if the resulting file has any unreplaced placeholders
echo ">>> Validating unreplaced placeholders..."
remaining_placeholders=$(grep -oP '%[a-zA-Z0-9_]+%' "$QUADLET_FILE_LOCATION" | sort -u | xargs)

if [[ -n "$remaining_placeholders" ]]; then
    echo ""
    echo "[WARNING] The following placeholders were not replaced:"
    echo "    $remaining_placeholders"
    read -p "Do you want to keep these placeholders unreplaced? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Installation aborted."
      exit 1
    fi
fi

# ensure install location exists
$SUDO mkdir -p "$INSTALL_LOCATION"

# ensure service data directory exists
mkdir -p "$SERVICE_DATA_DIR"

pre_install "${HOOK_ARGS[@]}"

# Setup quadlet systemd

echo ">>> Backing up current Quadlet definitions..."
for ext in container network volume; do
  if [[ -f "$INSTALL_LOCATION/$SERVICE_NAME.$ext" ]]; then
    cp "$INSTALL_LOCATION/$SERVICE_NAME.$ext" "$BACKUP_DIR/"
  fi
done

echo ">>> Installing $QUADLET_FILENAME"

# due to `podman quadlet install` bug, we still need to remove the old file before installing the new one
$SUDO rm -f "$INSTALL_LOCATION/$SERVICE_NAME.container"
$SUDO podman quadlet install --replace "$QUADLET_FILE_LOCATION" > /dev/null

if [[ -f "$SCRIPT_DIR/$SERVICE_NAME.network" ]]; then
    echo ">>> Found network file. Installing $SERVICE_NAME.network"
    $SUDO rm -f "$INSTALL_LOCATION/$SERVICE_NAME.network"
    $SUDO podman quadlet install --replace "$SCRIPT_DIR/$SERVICE_NAME.network" > /dev/null
fi
if [[ -f "$SCRIPT_DIR/$SERVICE_NAME.volume" ]]; then
    echo ">>> Found volume file. Installing $SERVICE_NAME.volume"
    $SUDO rm -f "$INSTALL_LOCATION/$SERVICE_NAME.volume"
    $SUDO podman quadlet install --replace "$SCRIPT_DIR/$SERVICE_NAME.volume" > /dev/null
fi

echo ">>> Checking for configuration changes..."
SERVICE_CHANGED=false

# Kiểm tra tất cả các extension có thể được Podman sinh ra
for ext in container network volume; do
  CURRENT_FILE="$INSTALL_LOCATION/$SERVICE_NAME.$ext"
  BACKUP_FILE="$BACKUP_DIR/$SERVICE_NAME.$ext"

  # Nếu file mới tồn tại
  if [[ -f "$CURRENT_FILE" ]]; then
    # Nếu file backup không có (file mới hoàn toàn), HOẶC nội dung khác nhau
    if [[ ! -f "$BACKUP_FILE" ]] || ! $SUDO cmp -s "$CURRENT_FILE" "$BACKUP_FILE"; then
      echo "    -> [CHANGED/NEW] $SERVICE_NAME.$ext"
      SERVICE_CHANGED=true
    fi
  # Nếu file mới không có, nhưng file backup lại có (cấu hình bị xóa khỏi .quadlet)
  elif [[ -f "$BACKUP_FILE" ]]; then
    echo "    -> [REMOVED] $SERVICE_NAME.$ext"
    SERVICE_CHANGED=true
  fi
done

# quyết định restart dựa trên cấu hình có thay đổi hay không
if [[ "$SERVICE_CHANGED" == "true" ]]; then
  echo ">>> Changes applied. Reloading systemd daemon..."
  $SYSTEMCTL_CMD daemon-reload

  echo ">>> Restarting $SERVICE_NAME container..."
  $SYSTEMCTL_CMD restart "$SERVICE_NAME"
else
  echo ">>> No configuration changes detected. Skipping daemon-reload."

  if ! $SYSTEMCTL_CMD is-active --quiet "$SERVICE_NAME"; then
    echo ">>> Service is currently down. Starting $SERVICE_NAME..."
    $SYSTEMCTL_CMD start "$SERVICE_NAME"
  else
    echo ">>> Service is already running."
  fi
fi

post_install "${HOOK_ARGS[@]}"

echo ">>> Done!"
echo
echo "To check status:"
echo "  $SYSTEMCTL_CMD status $SERVICE_NAME"
