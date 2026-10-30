#!/usr/bin/env bash
###############################################################################
#  PatchMaster — Bare-Metal Uninstaller
#  Removes PatchMaster services and optionally all data.
#  Usage:  sudo ./uninstall-bare.sh [--purge]
###############################################################################
set -euo pipefail

INSTALL_DIR="/opt/patchmaster"
SVC_USER="patchmaster"
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
    echo "           Bare-Metal Uninstaller"
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
            echo "  --purge             Remove ALL data (database, user, monitoring if installed)"
            echo "  --install-dir DIR   Installation directory (default: /opt/patchmaster)"
            echo "  -h, --help          Show this help"
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
    warn "PURGE mode: This will remove ALL PatchMaster data and database!"
    echo ""
    read -r -p "Type 'yes' to confirm: " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        log "Aborted."
        exit 0
    fi
fi

###############################################################################
# Step 1: Stop services
###############################################################################
log "Stopping PatchMaster services..."

for SVC in patchmaster-backend; do
    if systemctl is-active "$SVC" &>/dev/null; then
        systemctl stop "$SVC"
        log "  Stopped $SVC"
    fi
done

###############################################################################
# Step 2: Disable and remove systemd units
###############################################################################
log "Removing systemd services..."

for SVC in patchmaster-backend; do
    if [[ -f "/etc/systemd/system/${SVC}.service" ]]; then
        systemctl disable "$SVC" &>/dev/null || true
        rm -f "/etc/systemd/system/${SVC}.service"
        log "  Removed ${SVC}.service"
    fi
done

systemctl daemon-reload

###############################################################################
# Step 3: Remove Nginx config
###############################################################################
log "Removing Nginx configuration..."

rm -f /etc/nginx/sites-enabled/patchmaster
rm -f /etc/nginx/sites-available/patchmaster
rm -f /etc/nginx/conf.d/patchmaster.conf
nginx -t &>/dev/null && systemctl reload nginx 2>/dev/null || true

log "  Nginx config removed"

###############################################################################
# Step 4: Purge database, monitoring, and user data (only with --purge)
###############################################################################
if [[ "$PURGE" == "true" ]]; then
    # Drop PostgreSQL database and user
    log "Removing database..."
    su - postgres -c "psql -c 'DROP DATABASE IF EXISTS patchmaster;'" 2>/dev/null || true
    su - postgres -c "psql -c 'DROP USER IF EXISTS patchmaster;'" 2>/dev/null || true
    log "  Database dropped"

    # Remove Prometheus (only if installed by PatchMaster)
    if [[ -f /etc/systemd/system/prometheus.service ]]; then
        log "Removing Prometheus..."
        systemctl stop prometheus 2>/dev/null || true
        systemctl disable prometheus 2>/dev/null || true
        rm -f /etc/systemd/system/prometheus.service
        rm -rf /var/lib/prometheus
        rm -rf /etc/prometheus
        rm -f /usr/local/bin/prometheus /usr/local/bin/promtool
        if id prometheus &>/dev/null; then
            userdel prometheus 2>/dev/null || true
        fi
        log "  Prometheus removed"
    fi

    # Remove Grafana PatchMaster config (only if provisioning files exist)
    if [[ -f /etc/grafana/provisioning/datasources/patchmaster.yml ]]; then
        log "Removing Grafana PatchMaster config..."
        rm -f /etc/grafana/provisioning/datasources/patchmaster.yml
        rm -f /etc/grafana/provisioning/dashboards/patchmaster.yml
        rm -f /var/lib/grafana/dashboards/patchmaster-overview.json
        log "  Grafana config removed (Grafana itself preserved)"
    fi

    # Remove service user
    if id "$SVC_USER" &>/dev/null; then
        userdel "$SVC_USER" 2>/dev/null || true
        log "  Removed user: $SVC_USER"
    fi

    # Remove install directory
    log "Removing $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
    log "  Directory removed"

    systemctl daemon-reload
fi

###############################################################################
# Summary
###############################################################################
echo ""
echo -e "${GREEN}PatchMaster has been uninstalled.${NC}"
echo ""
if [[ "$PURGE" == "false" ]]; then
    echo "  Application files kept at: $INSTALL_DIR"
    echo "  Database preserved in PostgreSQL."
    echo "  To fully remove everything: sudo $0 --purge"
fi
echo ""
