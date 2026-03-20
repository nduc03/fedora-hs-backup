#!/bin/bash

DEST="remote:backup_folder"

SOURCE_DATA="$HOME/container-data"
DB_USER="postgres"
BACKUP_TEMP=$(mktemp -d -t "postgres_backup-XXXXXXXX")

# Tạo thư mục tạm nếu chưa có
mkdir -p "$BACKUP_TEMP"

echo "--- Bắt đầu tiến trình Backup: $(date) ---"

# 1. Chạy pg_dump
# Lưu ý: Nên dùng file .pgpass để không phải nhập pass thủ công
echo "1. Đang dump database..."
DB_BACKUP_FILE="$BACKUP_TEMP/postgres18-backup-$(date +%F).sql"
pg_dumpall -U "$DB_USER" > "$DB_BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "Dump DB thành công."
else
    echo "Dump DB lỗi."
    exit 1
fi

# 2. Rclone sync container-data
echo "2. Đang sync dữ liệu container..."
rclone sync "$SOURCE_DATA" "$DEST/container-data" --progress -L -v

# 3. Rclone copy bản dump DB vào cùng chỗ đó
echo "3. Đang upload bản dump DB..."
rclone copy "$DB_BACKUP_FILE" "$DEST/postgres-dump/"

echo "--- Hoàn tất Backup: $(date) ---"

# Dọn dẹp file tạm
rm "$DB_BACKUP_FILE"