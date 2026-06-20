#!/bin/bash

DEST="gdrive:backup-hs"
SOURCE_DATA="$HOME/container-data"
DB_HOST="192.168.1.220"
DB_PORT="5432"
DB_USER="postgres"
BACKUP_TEMP=$(mktemp -d -t "hs_backup-XXXXXXXX")
trap "rm -rf $BACKUP_TEMP" EXIT

PG_VERSION=$(psql -V | awk '{print $3}' | cut -d. -f1)

[ -z "$PG_VERSION" ] && PG_VERSION="postgres"

mkdir -p "$BACKUP_TEMP"

echo "--- Bắt đầu tiến trình Backup: $(date) ---"
echo "Phát hiện Postgres Version: $PG_VERSION"

# 1. Chạy pg_dump
echo "1. Đang dump database..."
DB_BACKUP_FILE="$BACKUP_TEMP/postgres${PG_VERSION}-backup-$(date +%F).sql"
pg_dumpall -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" > "$DB_BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "Dump DB thành công."
else
    echo "Dump DB lỗi."
    rm -rf "$BACKUP_TEMP"
    exit 1
fi

# 2. Rclone sync container-data
echo "2. Đang nén thư mục container-data..."
CONTAINER_ZIP_FILE="$BACKUP_TEMP/container-data-$(date +%F).tar.gz"
podman unshare tar -czf "$CONTAINER_ZIP_FILE" -C "$(dirname "$SOURCE_DATA")" "$(basename "$SOURCE_DATA")"
if [ $? -eq 0 ]; then
    echo "Nén container-data thành công. Đang upload lên Google Drive..."
    # Đổi từ rclone sync sang rclone copy vì giờ là file đơn lẻ
    rclone copy "$CONTAINER_ZIP_FILE" "$DEST/container-data-zip/" --progress
else
    echo "Nén container-data thất bại."
    rm -rf "$BACKUP_TEMP"
    exit 1
fi

# 3. Rclone copy bản dump DB vào Google Drive
echo "3. Đang upload bản dump DB..."
rclone copy "$DB_BACKUP_FILE" "$DEST/postgres-dump/"

echo "--- Hoàn tất Backup: $(date) ---"

# Dọn dẹp thư mục tạm
rm -rf "$BACKUP_TEMP"
