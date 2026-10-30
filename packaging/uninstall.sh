#!/usr/bin/env bash
###############################################################################
#  PatchMaster Uninstaller
#  Removes PatchMaster stack and optionally all data.
#  Usage:  sudo ./uninstall.sh [--purge]
###############################################################################
set -euo pipefail

INSTALL_DIR="/opt/patchmaster"
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
    echo "       PatchMaster by VYGROUP  v${PM_VERSION}"
    echo "              Uninstaller"
    echo
}

PURGE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)        PURGE=true; shift ;;
        --install-dir)  INSTALL_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: sudo $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --purge           Remove all data (database, volumes, images)"
            echo "  --install-dir DIR Installation directory (default: /opt/patchmaster)"
            echo "  -h, --help        Show this help"
            exit 0
            ;;
        *)  err "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo)."
    exit 1
fi

banner

if [[ "$PURGE" == "true" ]]; then
    warn "PURGE mode: This will remove ALL data including the database!"
    echo ""
    read -r -p "Are you sure? Type 'yes' to confirm: " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        log "Aborted."
        exit 0
    fi
fi

###############################################################################
# Step 1: Stop services
###############################################################################
log "Stopping services..."

if [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    cd "$INSTALL_DIR"
    if [[ "$PURGE" == "true" ]]; then
        docker compose down -v --remove-orphans 2>/dev/null || true
    else
        docker compose down --remove-orphans 2>/dev/null || true
    fi
    log "  Docker services stopped."
else
    warn "  No docker-compose.yml found at $INSTALL_DIR"
fi

###############################################################################
# Step 2: Remove systemd service
###############################################################################
log "Removing systemd service..."

if [[ -f /etc/systemd/system/patchmaster.service ]]; then
    systemctl disable patchmaster.service &>/dev/null || true
    systemctl stop patchmaster.service &>/dev/null || true
    rm -f /etc/systemd/system/patchmaster.service
    systemctl daemon-reload
    log "  Removed patchmaster.service"
else
    log "  No systemd service found (skipped)"
fi

###############################################################################
# Step 3: Remove Docker images (purge only)
###############################################################################
if [[ "$PURGE" == "true" ]]; then
    log "Removing Docker images..."
    PROJECT_NAME=$(basename "$INSTALL_DIR")
    docker images --format '{{.Repository}}:{{.Tag}}' | grep -i "${PROJECT_NAME}" | while read -r IMG; do
        docker rmi "$IMG" 2>/dev/null && log "  Removed image: $IMG"
    done || true
fi

###############################################################################
# Step 4: Remove install directory
###############################################################################
if [[ "$PURGE" == "true" ]]; then
    log "Removing install directory..."
    rm -rf "$INSTALL_DIR"
    log "  Removed $INSTALL_DIR"
else
    log "Keeping install directory (use --purge to remove): $INSTALL_DIR"
fi

###############################################################################
# Summary
###############################################################################
echo ""
echo -e "${GREEN}PatchMaster has been uninstalled.${NC}"
echo ""
if [[ "$PURGE" == "false" ]]; then
    echo "  Files preserved at: $INSTALL_DIR"
    echo "  To fully remove: sudo $0 --purge"
fi
echo ""
