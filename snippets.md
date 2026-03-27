đồng bộ service từ project backup-script lên fedora server
```bash
sync-service() {
    local folder
    folder=$(basename "$PWD")

    local target_user="user"
    local target_host="192.168.x.y"
    local remote_path="~/${folder}"

    echo "Syncing current folder '$folder' to ${target_user}@${target_host}:${remote_path}"
    echo "Additional rsync args: $@"

    echo "dos2unix trước khi rsync"
    find . -type f -exec dos2unix {} \;

    rsync -av --no-times --no-owner --no-group \
        --chmod=D755,F644 \
        --exclude='*.sh' \
        -e "ssh" \
        ./ "${target_user}@${target_host}:${remote_path}/" \
        "$@"

    rsync -av --no-times --no-owner --no-group \
        --chmod=755 \
        -e "ssh" \
        ./*.sh "${target_user}@${target_host}:${remote_path}/" \
        "$@"
}
```