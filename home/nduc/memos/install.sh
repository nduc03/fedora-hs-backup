#!/usr/bin/env bash

# This is Quadlet Service Installer Template, to use this template:
# 1. Copy this file into the service folder.
# 2. Rename it `mv install.sh.template install.sh` and make it executable `chmod +x install.sh`.
# 3. Customize this script as needed; recommended customization points are marked with '#*'.

set -e

#* =========================================
#* 1. CUSTOMIZABLE VARIABLES
#* =========================================

#* Set to false if this container can not run rootless
ROOTLESS=true

#* Set to false if you are directly using a .container or .quadlets file that don't have .template extension
USE_TEMPLATE=true

#* Set file extension to "container" for default installation,
#* or "quadlets" to specify multiple quadlets in one file (only podman v6 above)
FILE_TYPE="container"

#* Set to true if you want to use traefik service discovery
#* Automatically injects Traefik labels directly under [Container] section.
#* It utilizes $PRIVATE_DOMAIN (e.g., from ~/hs-info.env) for routing.
USE_TRAEFIK_LABELS=true

#* Set to true to route the service via PUBLIC_DOMAIN if you want to leverage the powaaahh 💪 of Let's Encrypt!
#* Note: This does NOT necessarily expose your service to the internet. It simply provides a valid SSL cert
#* so you don't have to manually install root certificates on every device across your LAN.
ENABLE_PUBLIC_DOMAIN=false

#* If your service has mount points, you can specify the directory names here
#* It will automatically create these directories in the service data directory and adjust permissions
#* example definition: MOUNT_DIR_NAMES=("data" "config" "logs")
MOUNT_DIR_NAMES=("data")

#* If you have extra files that need variable substitution (e.g., config files, networks),
#* list them here with full path from the script directory.
#* The script will process them with envsubst and output without the '.template' extension.
#* Should not include the main .container/.quadlet template file, as it's processed automatically.
#* Example: EXTRA_TEMPLATE_FILES=("etc/something/config.yml.template" "app-settings.conf.template")
EXTRA_TEMPLATE_FILES=()

#* Add more customizable variables here if needed, for example:
#* MY_CUSTOM_LOG="/path/to/custom.log"

#* Also define any $VARIABLES that you want to be automatically replaced in the template files.

#* =========================================
#* 2. CUSTOMIZABLE HOOKS (PRE/POST INSTALL)
#* =========================================
#* Các tham số khả dụng trong hàm:
#* $1: SCRIPT_DIR       - Đường dẫn thư mục chứa script này
#* $2: SCRIPT_DIR_NAME  - Tên thư mục cha chứa script này
#* $3: SERVICE_NAME     - Tên Service sau khi đã chuẩn hóa
#* $4: SERVICE_DATA_DIR - Thư mục lưu dữ liệu (~/container-data/$SERVICE_NAME)
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
#* 3. CONTAINER TEMPLATE VARIABLES
#* =========================================
#* Mọi biến được khai báo ở các file `ctv.env` trong thư mục này,
#* HOẶC từ file global `~/hs-info.env`, sẽ tự động được thay thế vào file template.
#*
#* TRONG FILE `.template`: Sử dụng cú pháp $VAR_NAME hoặc ${VAR_NAME}
#* Ví dụ: Environment=DB_PASSWORD=${DB_PASSWORD}
#* #* Các biến nội bộ có sẵn để gọi trong template:
#* $SERVICE_DIR, $SERVICE_DATA_DIR, $HOST_IPV4, $HOST_ULA_IPV6, và các biến ở trong ~/hs-info.env

# ==========================================
# 4. VARIABLE CALCULATION LOGIC
# ==========================================

# Determine the script's absolute directory
SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

# Thiết lập thư mục Debug
DEBUG_OUT_DIR="$SCRIPT_DIR/__dbg_template__"
DEBUG_MODE=false
for arg in "$@"; do
  if [[ "$arg" == "--dbg-templ" ]]; then
    DEBUG_MODE=true
    echo ">>> [DEBUG MODE] Enabled. Skipping installation steps."
    # Khởi tạo an toàn thư mục và file .gitignore ngay từ đầu
    mkdir -p "$DEBUG_OUT_DIR"
    echo "*" > "$DEBUG_OUT_DIR/.gitignore"
    break
  fi
done

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
#** recommended way is redefine it in pre_install hook
#!! directly change this is not recommended, as it may cause issues with future updates of the script
SERVICE_DATA_DIR="${SERVICE_DATA_DIR:-$HOME/container-data/$SERVICE_NAME}"

# get host's default ipv4 address
__default_iface=$(ip route | grep default | head -n1 | awk '{print $5}')
HOST_IPV4=$(ip -4 addr show "$__default_iface" | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)
HOST_ULA_IPV6=$(ip -6 addr show "$__default_iface" | grep -oP 'fd00[:0-9a-f]+' | head -n 1)
# Bổ sung fallback về ::1 nếu không có ULA IPv6
HOST_ULA_IPV6=${HOST_ULA_IPV6:-::1}

# define quadlet file paths
QUADLET_FILENAME="$SERVICE_NAME.$FILE_TYPE"

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
trap "rm -rf $TMP_DIR" EXIT

# Đổi đường dẫn file xuất ra nếu bật cờ DEBUG
if [[ "$DEBUG_MODE" == "true" ]]; then
  QUADLET_FILE_LOCATION="$DEBUG_OUT_DIR/$QUADLET_FILENAME"
else
  QUADLET_FILE_LOCATION="$TMP_DIR/$QUADLET_FILENAME"
fi

BACKUP_DIR="$TMP_DIR/backup"

HOOK_ARGS=("$SCRIPT_DIR" "$SCRIPT_DIR_NAME" "$SERVICE_NAME"
      "$SERVICE_DATA_DIR" "$HOST_IPV4" "$HOST_ULA_IPV6"
      "$SUDO" "$INSTALL_LOCATION" "$SYSTEMCTL_CMD")

# ==========================================
# 5. EXECUTION & TEMPLATE PROCESSING
# ==========================================
make_mount_dir() {
    echo ">>> Creating mount directories and adjusting permissions if necessary..."

    for DIR_NAME in "$@"; do
        local TARGET="$SERVICE_DATA_DIR/$DIR_NAME"
        echo "--- Đang xử lý mount point: $TARGET ---"

        # 1. Tạo thư mục nếu chưa tồn tại
        if [ ! -d "$TARGET" ]; then
            echo ">> Thư mục chưa tồn tại, đang tạo: mkdir -p $TARGET"
            mkdir -p "$TARGET"
        fi

        if [ "$ROOTLESS" = "false" ]; then
            echo ">> Chế độ Rootfull (ROOTLESS=false): Bỏ qua bước sửa quyền sở hữu."
            echo ""
            continue
        fi

        # 2. Lấy thông tin UID
        local HOST_UID=$(stat -c "%u" "$TARGET")
        local UNSHARE_UID=$(podman unshare stat -c "%u" "$TARGET")

        echo "   UID hiện tại (Host): $HOST_UID | (Unshare): $UNSHARE_UID"

        # 3. Logic xử lý quyền
        if [ "$UNSHARE_UID" = "1000" ]; then
            echo ">> Mount point đã thuộc quyền quản lý của Podman. Bỏ qua."

        elif [ "$HOST_UID" = "1000" ]; then
            echo ">> Mount point đang là UID 1000. Đang chạy podman unshare chown..."
            podman unshare chown -R 1000:1000 "$TARGET"
            echo ">> Xong!"

        else
            echo ">> Mount point đang thuộc UID khác ($HOST_UID). Đang dùng sudo để reset về 1000..."
            sudo chown -R 1000:1000 "$TARGET"
            echo ">> Tiếp tục chuyển sang Podman unshare..."
            podman unshare chown -R 1000:1000 "$TARGET"
            echo ">> Hoàn tất!"
        fi
        echo ""
    done
}

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

  # Ensure primary template exists
  if [[ ! -f "$SCRIPT_DIR/$TEMPLATE_FILENAME" ]]; then
    echo "Error: $TEMPLATE_FILENAME not found in $SCRIPT_DIR."
    exit 1
  fi

  echo ">>> Processing templates and safely injecting variables..."

  # Tạo Subshell để nạp và xử lý biến môi trường an toàn
  (
    export SERVICE_DIR="$SCRIPT_DIR"
    export SERVICE_DATA_DIR="$SERVICE_DATA_DIR"
    export HOST_IPV4="$HOST_IPV4"
    export HOST_ULA_IPV6="[$HOST_ULA_IPV6]"

    # 1. Nạp Global Env nếu có
    if [[ -f "$HOME/hs-info.env" ]]; then
      echo "    -> Sourcing global variables from: ~/hs-info.env"
      set -a
      source "$HOME/hs-info.env"
      set +a
    fi

    # 2. Nạp Local ctv.env
    while IFS= read -r env_file; do
      echo "    -> Sourcing variables from: $(basename "$env_file")"
      set -a
      source "$env_file"
      set +a
    done < <(find "$SCRIPT_DIR" -name "ctv.env")

# 3. Setup Traefik Labels
    if [[ "$USE_TRAEFIK_LABELS" == "true" ]]; then
      LAN_DOMAIN="${PRIVATE_DOMAIN:-hs.lan}"
      LE_DOMAIN="${PUBLIC_DOMAIN}"

      # Khởi tạo nhãn mặc định cho mạng LAN
      TRAEFIK_LABELS=$(cat << EOF
Network=traefik.network
Label=traefik.enable=true
Label=traefik.http.routers.$SERVICE_NAME.rule=Host(\`$SERVICE_NAME.$LAN_DOMAIN\`)
Label=traefik.http.routers.$SERVICE_NAME.entrypoints=websecure
Label=traefik.http.routers.$SERVICE_NAME.tls=true
EOF
)

      # Kiểm tra nếu cờ ENABLE_PUBLIC_DOMAIN bật VÀ biến LE_DOMAIN có giá trị thì nối thêm cấu hình
      if [[ "$ENABLE_PUBLIC_DOMAIN" == "true" && -n "$LE_DOMAIN" ]]; then
        TRAEFIK_LABELS=$(cat << EOF
$TRAEFIK_LABELS
Label=traefik.http.routers.$SERVICE_NAME-le.rule=Host(\`$SERVICE_NAME.$LE_DOMAIN\`)
Label=traefik.http.routers.$SERVICE_NAME-le.entrypoints=websecure
Label=traefik.http.routers.$SERVICE_NAME-le.tls.certresolver=leresolver
EOF
)
      fi
    fi

    # Lấy danh sách các biến CÓ THỰC để envsubst không xóa nhầm các biến systemd native
    VARS_TO_REPLACE=$(compgen -e | awk '{print "${"$1"}"}' | tr '\n' ' ')

    # 4. Render file template chính
    envsubst "$VARS_TO_REPLACE" < "$SCRIPT_DIR/$TEMPLATE_FILENAME" > "$QUADLET_FILE_LOCATION"

    # 5. Render các file template phụ (EXTRA_TEMPLATE_FILES)
    if [[ ${#EXTRA_TEMPLATE_FILES[@]} -gt 0 ]]; then
      for ext_tpl in "${EXTRA_TEMPLATE_FILES[@]}"; do
        if [[ -f "$SCRIPT_DIR/$ext_tpl" ]]; then
          echo "    -> Injecting variables into extra template: $ext_tpl"
          out_file="${ext_tpl%.template}" # Xóa đuôi .template cho file đầu ra

          # Đổi đường dẫn target nếu đang bật chế độ debug
          if [[ "$DEBUG_MODE" == "true" ]]; then
            target_file="$DEBUG_OUT_DIR/$out_file"
          else
            target_file="$SCRIPT_DIR/$out_file"
          fi

          mkdir -p "$(dirname "$target_file")"

          envsubst "$VARS_TO_REPLACE" < "$SCRIPT_DIR/$ext_tpl" > "$target_file"
        else
          echo "    -> [WARNING] Extra template file not found: $ext_tpl"
        fi
      done
    fi

    # 6. Auto-inject Traefik Labels (nếu bật)
    if [[ "$USE_TRAEFIK_LABELS" == "true" ]]; then
      echo "    -> Auto-injecting Traefik labels under [Container] section..."
      awk -v labels="$TRAEFIK_LABELS" '
      /^\[Container\]/ {
          print $0
          print labels
          next
      }
      { print }
      ' "$QUADLET_FILE_LOCATION" > "${QUADLET_FILE_LOCATION}.tmp" && mv "${QUADLET_FILE_LOCATION}.tmp" "$QUADLET_FILE_LOCATION"
    fi
  )

  # Validate if ANY of the resulting files have unreplaced placeholders
  echo ">>> Validating unreplaced placeholders..."
  FILES_TO_CHECK=("$QUADLET_FILE_LOCATION")
  for ext_tpl in "${EXTRA_TEMPLATE_FILES[@]}"; do
    out_file="${ext_tpl%.template}"
    if [[ "$DEBUG_MODE" == "true" ]]; then
      test_path="$DEBUG_OUT_DIR/$out_file"
    else
      test_path="$SCRIPT_DIR/$out_file"
    fi
    if [[ -f "$test_path" ]]; then
      FILES_TO_CHECK+=("$test_path")
    fi
  done

  # Tìm kiếm các placeholder còn sót lại trong tất cả các file đã xử lý,
  # và loại bỏ các string hash mật khẩu phổ biến để giảm false positive
  remaining_placeholders=$(cat "${FILES_TO_CHECK[@]}" 2>/dev/null | \
      sed -E 's/\$(1|2[abxy]|apr1|argon2[a-z]+|5|6)\$[a-zA-Z0-9./$=+,-]+//g' | \
      grep -oP '\$\{[a-zA-Z_][a-zA-Z0-9_]*\}|\$[a-zA-Z_][a-zA-Z0-9_]*' | \
      sort -u | xargs)

  if [[ -n "$remaining_placeholders" ]]; then
      echo ""
      echo "[WARNING] The following variables were NOT replaced in the output files:"
      echo "    $remaining_placeholders"
      echo ""
      echo "    Note: Remaining placeholders check may have false positives if your templates include string that have character \`$\` such as password hashes."
      echo "    You can ignore this warning and enter 'n' if you are sure all variables were replaced correctly."
      read -p "Do you want to keep these variables as-is and continue? (y/N) " -n 1 -r
      echo ""
      if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation aborted."
        exit 1
      fi
  fi
fi

# Ngừng script sớm nếu đang bật chế độ debug
if [[ "$DEBUG_MODE" == "true" ]]; then
  echo ""
  echo ">>> [DEBUG MODE] All templates generated successfully in: $DEBUG_OUT_DIR"
  echo ">>> [DEBUG MODE] Exiting script safely..."
  exit 0
fi

# ensure install location exists
$SUDO mkdir -p "$INSTALL_LOCATION"

# ensure service data directory exists
mkdir -p "$SERVICE_DATA_DIR"

make_mount_dir "${MOUNT_DIR_NAMES[@]}"

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