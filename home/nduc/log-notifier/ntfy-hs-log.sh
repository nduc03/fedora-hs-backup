#!/bin/bash

# Kích hoạt chế độ thoát ngay lập tức nếu có lệnh lỗi
set -e

# --- TRAP BẢO MẬT ---
trap 'unset PGPASSWORD DB_PASS' EXIT INT TERM ERR

# Gán mật khẩu cho psql
export PGPASSWORD="$DB_PASS"
# --------------------

# Chuỗi lệnh psql dùng chung
PSQL_CMD="psql -h $DB_HOST -U $DB_USER -d $DB_NAME"

# 1. Lấy mốc thời gian SINCE
SINCE_TIME=$($PSQL_CMD -t -A -c "SELECT to_char(last_check_log + INTERVAL '1 second', 'YYYY-MM-DD HH24:MI:SS') FROM log_ntfy WHERE id = 1;")

# 2. Định nghĩa mốc thời gian UNTIL
UNTIL_TIME=$(date +"%Y-%m-%d %H:%M:%S")

# 3. Đọc log và lọc từ khóa "error"
# - journalctl vẫn lọc -p err trước để giảm tải lượng text phải xử lý.
# - grep -i "error" sẽ lọc tiếp để loại bỏ các false positive không chứa chữ error.
# - Dùng || true để đảm bảo nếu grep không tìm thấy chữ error nào (exit code 1), script vẫn không bị set -e ngắt ngang.
LOG_DATA=$(journalctl --user -p err --since "$SINCE_TIME" --until "$UNTIL_TIME" -q --no-pager | grep -i "error" || true)

# 4. Kiểm tra và gửi thông báo
if [ -n "$LOG_DATA" ]; then
    echo "$LOG_DATA" | curl --request POST \
      --url "$NTFY_URL" \
      --header "Authorization: $NTFY_AUTH" \
      --header "X-Title: hs Error Log" \
      --header "X-Priority: 2" \
      --data-binary @-
fi

# 5. Cập nhật lại thời gian vào DB
$PSQL_CMD -c "UPDATE log_ntfy SET last_check_log = '$UNTIL_TIME' WHERE id = 1;" > /dev/null