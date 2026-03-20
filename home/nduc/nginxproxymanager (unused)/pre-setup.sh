#!/bin/bash

SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

# Clean and prepare overlay directory
rm -rf /tmp/overlay
mkdir -p /tmp/overlay
cp "$SCRIPT_DIR/nginx_ciphers.conf" /tmp/overlay/
cp "$SCRIPT_DIR/custom_openssl.cnf" /tmp/overlay/

chcon -R -t container_file_t /tmp/overlay
