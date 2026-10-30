#!/usr/bin/env bash
# Patch-SecOps Solution Advanced Uninstaller
# Safely stops and removes backend/frontend/monitoring bits.
# Usage:
#   sudo bash scripts/uninstall_patchmaster.sh            # prompt before destructive steps
#   sudo bash scripts/uninstall_patchmaster.sh --force    # no prompts
#   sudo bash scripts/uninstall_patchmaster.sh --keep-data  # keep logs/db/data

set -euo pipefail

PM_VERSION="2.0.0"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

banner() {
    echo -e "${BLUE}"
    cat <<'ART'
  ____       _       _       _       __  __
 |  _ \ __ _| |_ ___| |__   | |\/|  / _|/ _|
 | |_) / _` | __/ __| '_ \  | |  | | |_| |_
 |  __/ (_| | || (__| | | | | |  | |  _|  _|
 |_|   \__,_|\__\___|_| |_| |_|  |_|_| |_|
ART
    echo -e "${NC}"
    echo "       Patch-SecOps Solution by VYGROUP  v${PM_VERSION}"
    echo "           Advanced Uninstaller"
    echo
}

FORCE=false
KEEP_DATA=false
PURGE_ALL=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=true ;;
    --keep-data) KEEP_DATA=true ;;
    --purge-all) PURGE_ALL=true; KEEP_DATA=false ;;
    *) err "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo)."
    exit 1
fi

banner

confirm() {
  $FORCE && return 0
  read -r -p "$1 [y/N] " ans
  [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]
}

svc_stop_disable() {
  local svc="$1"
  if systemctl list-unit-files | grep -q "^${svc}.service"; then
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    echo "Stopped & disabled $svc"
  fi
}

file_remove() {
  local path="$1"
  [[ -e "$path" ]] || return 0
  rm -f "$path"
  echo "Removed $path"
}

dir_remove() {
  local path="$1"
  [[ -d "$path" ]] || return 0
  rm -rf "$path"
  echo "Removed $path"
}

log "Stopping Patch-SecOps Solution services..."
svc_stop_disable patchmaster-backend
svc_stop_disable patchmaster-frontend
svc_stop_disable patchmaster-monitoring
svc_stop_disable grafana-server
svc_stop_disable prometheus
svc_stop_disable postgresql
svc_stop_disable patch-agent
svc_stop_disable patch-agent-heartbeat

# Remove systemd unit files if present
for unit in /etc/systemd/system/patchmaster-backend.service \
            /etc/systemd/system/patchmaster-frontend.service \
            /etc/systemd/system/patchmaster-monitoring.service \
            /etc/systemd/system/patch-agent.service \
            /etc/systemd/system/patch-agent-heartbeat.service; do
  file_remove "$unit"
done
systemctl daemon-reload || true

# Remove nginx site if present
for conf in /etc/nginx/sites-enabled/patchmaster.conf /etc/nginx/sites-available/patchmaster.conf; do
  file_remove "$conf"
done

# Directories to remove
BACKEND_DIRS=(
  /opt/patchmaster
  /opt/patchmaster/backend
  /opt/patchmaster/frontend
  /opt/patchmaster/monitoring
  /opt/patchmaster/grafana
  /opt/patchmaster/prometheus
  /opt/patch-agent
)
DATA_DIRS=(
  /var/log/patchmaster
  /var/lib/patchmaster
  /var/lib/grafana
  /var/lib/prometheus
  /etc/prometheus
  /etc/grafana
  /etc/patchmaster
  /etc/patch-agent
  /var/log/patch-agent
  /var/lib/patch-agent
  /opt/patchmaster-product
)

if confirm "Remove application code under /opt/patchmaster (backend/frontend/monitoring)?"; then
  for d in "${BACKEND_DIRS[@]}"; do dir_remove "$d"; done
fi

if ! $KEEP_DATA && confirm "Remove data/logs (Prometheus/Grafana/patchmaster logs and libs)?"; then
  for d in "${DATA_DIRS[@]}"; do dir_remove "$d"; done
else
  echo "Keeping data directories."
fi

if $PURGE_ALL; then
  if confirm "Purge local PostgreSQL Patch-SecOps Solution databases/users if present?"; then
    if command -v sudo >/dev/null 2>&1; then
      sudo -u postgres psql -v ON_ERROR_STOP=0 -c "DROP DATABASE IF EXISTS patchmaster;" 2>/dev/null || true
      sudo -u postgres psql -v ON_ERROR_STOP=0 -c "DROP USER IF EXISTS patchmaster;" 2>/dev/null || true
      sudo -u postgres psql -v ON_ERROR_STOP=0 -c "DROP DATABASE IF EXISTS patchmaster_test;" 2>/dev/null || true
    fi
  fi
  if command -v docker >/dev/null 2>&1; then
    if confirm "Remove Docker containers/volumes/networks matching patchmaster?"; then
      docker ps -a --format '{{.ID}} {{.Names}}' | awk '/patchmaster/{print $1}' | xargs -r docker rm -f >/dev/null 2>&1 || true
      docker volume ls --format '{{.Name}}' | awk '/patchmaster/{print $1}' | xargs -r docker volume rm >/dev/null 2>&1 || true
      docker network ls --format '{{.Name}}' | awk '/patchmaster/{print $1}' | xargs -r docker network rm >/dev/null 2>&1 || true
      docker image ls --format '{{.Repository}}:{{.Tag}}' | awk '/patchmaster/{print $1}' | xargs -r docker rmi -f >/dev/null 2>&1 || true
    fi
  fi
fi

log "Uninstall complete."
log "Restart nginx if you removed its site: sudo systemctl restart nginx"
log "If you plan to reinstall, ensure systemd units are gone and ports 8000/80/9090 are free."
