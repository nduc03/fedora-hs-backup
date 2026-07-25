# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a backup/documentation repository for a Fedora-based homelab server. It contains:
- Configuration backups for multiple Podman-based services (Traefik, Unbound, Mosquitto, Home Assistant, etc.)
- Installation scripts for services following a Quadlet templating pattern
- System administration tips and tricks specific to Fedora Linux
- Backup and deployment tooling

**Architecture Pattern:** Services run as rootless Podman containers managed via systemd Quadlet files. Configuration lives in `home/nduc/<service>/` directories. Each service has:
- `install.sh` - customized from `install-v2.sh.template` for Quadlet setup
- `*.container` or `*.quadlet` files - service definitions
- Service-specific config directories (config/, data/, logs/)

## Common Commands

### Service Management
```bash
# Sync a service folder to the remote server (with dos2unix conversion)
# Define sync-service function from snippets.md, then run in service folder:
sync-service

# View service logs on the server
sudo journalctl -u <service-name>.service -f

# Restart a service
sudo systemctl restart <service-name>.service

# Check service status
sudo systemctl status <service-name>.service
```

### Backup Operations
```bash
# Run full homelab backup (PostgreSQL dump + container data to Google Drive)
~/backup-hs/backup.sh

# The backup script:
# 1. Dumps all PostgreSQL databases to a temp directory
# 2. Archives ~/container-data folder
# 3. Syncs to Google Drive using rclone
```

### Installation/Deployment
```bash
# Inside a service folder, customize install.sh.template and make it executable:
chmod +x install.sh

# Run installation (creates Quadlet files, systemd services, mounts directories)
./install.sh
```

## Architecture & Key Patterns

### Quadlet Service Installation
Each service follows a template-based installation system using Fedora's Quadlet (systemd unit generator for Podman). The pattern:

1. Copy `install-v2.sh.template` from parent directory or use existing `install.sh`
2. Customize variables at top of script (marked with `#*`):
   - `ROOTLESS=true/false` - whether container runs without root
   - `USE_TRAEFIK_LABELS=true/false` - enable automatic Traefik discovery
   - `MOUNT_DIR_NAMES` - directories to create in `~/container-data/<service-name>/`
3. Run `./install.sh` to:
   - Process `.container` or `.quadlet` template files
   - Create systemd service files
   - Set up data directories with correct permissions
   - Enable and start the service

### Key File Locations
- **Service configs:** `home/nduc/<service-name>/` - contains install scripts, container definitions, and service-specific configs
- **Installation templates:** `home/nduc/install.sh.template`, `home/nduc/install-v2.sh.template`
- **Container data:** On server at `~/container-data/<service-name>/` (mounted in containers)
- **Systemd services:** On server at `~/.config/systemd/user/` (for rootless) or `/etc/systemd/system/` (for root)
- **Server info:** `home/nduc/hs-info.env` - environment variables like `PRIVATE_DOMAIN`, `PUBLIC_DOMAIN`, `HOST_IPV4`, `HOST_ULA_IPV6`

### Traefik Integration
Services can be auto-discovered by Traefik reverse proxy:
- Set `USE_TRAEFIK_LABELS=true` in `install.sh` to inject labels automatically
- Or manually specify labels in `.container` template with `==%traefik_labels%==` placeholder
- Uses `$PRIVATE_DOMAIN` from `hs-info.env` for internal routing

### Rootless Podman Notes
- Use `loginctl enable-linger $USER` on server to keep services running after logout
- To reference the host from within containers: use `host.containers.internal` (defined in container `/etc/hosts`)
- For privileged ports (< 1024): either use port forwarding via firewall-cmd or set `net.ipv4.ip_unprivileged_port_start=0` in `/etc/sysctl.d/`

## Important Notes

### SELinux Management (Fedora)
When setting up custom scripts or changing file contexts:
```bash
# Add context definition for a file or directory
sudo semanage fcontext -a -t <type> "/path/to/file(/.*)?"

# Apply the context
sudo restorecon -Rv /path/to/file
```

### Deployment Pattern
Services are deployed via rsync with specific file permissions:
- Executable scripts (`.sh`): chmod 755
- Env files (`.env`): chmod 600
- Regular configs: chmod 644
- Directories: chmod 755
- DOS line endings are converted before sync (dos2unix)

### Database Backups
The backup script (`backup.sh`):
- Connects to PostgreSQL on `DB_HOST:DB_PORT` using credentials from environment
- Uses `pg_dumpall` to dump all databases
- Requires `psql` client installed locally
- Checks PostgreSQL version and adapts dump accordingly

### Service Language
Some documentation and comments are in Vietnamese. This is intentional and reflects the original author's context.
