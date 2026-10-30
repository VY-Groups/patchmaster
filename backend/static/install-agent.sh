#!/bin/bash
###############################################################################
#  PatchMaster by VYGROUP — Universal Agent Installer (Air-Gapped Friendly)
#  This script is served by the Master node and installs the agent locally.
###############################################################################

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${BLUE}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

# Config passed via env or detected
MASTER_URL="${MASTER_URL:-http://localhost:8000}"
AGENT_PORT="${AGENT_PORT:-8080}"
METRICS_PORT="${METRICS_PORT:-9100}"
PATCHMASTER_SITE="${PATCHMASTER_SITE:-${PATCHMASTER_LOCATION:-}}"
DOWNLOAD_BASE=""

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
    echo "       PatchMaster by VYGROUP"
    echo "           Agent Installer"
    echo
}

detect_distro() {
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        ID=$ID
    elif [[ -f /etc/debian_version ]]; then
        ID="debian"
    elif [[ -f /etc/redhat-release ]]; then
        ID="rhel"
    else
        ID="unknown"
    fi
    echo "$ID"
}

normalize_urls() {
    local raw_url scheme host port
    raw_url="${MASTER_URL//\`/}"
    raw_url="${raw_url//\"/}"
    raw_url="${raw_url//\'/}"
    raw_url="${raw_url// /}"
    raw_url="${raw_url%/}"
    if [[ "$raw_url" =~ ^(https?)://([^/:]+)(:([0-9]+))?$ ]]; then
        scheme="${BASH_REMATCH[1]}"
        host="${BASH_REMATCH[2]}"
        port="${BASH_REMATCH[4]:-}"
        case "$port" in
            "")
                if [[ "$scheme" == "https" ]]; then
                    MASTER_URL="${scheme}://${host}"
                    DOWNLOAD_BASE="${scheme}://${host}"
                else
                    warn "MASTER_URL did not include a port; defaulting controller to ${scheme}://${host}:8000 and downloads to ${scheme}://${host}:3000"
                    MASTER_URL="${scheme}://${host}:8000"
                    DOWNLOAD_BASE="${scheme}://${host}:3000"
                fi
                ;;
            "3000")
                warn "MASTER_URL points to the frontend port; using ${scheme}://${host}:8000 for agent registration."
                MASTER_URL="${scheme}://${host}:8000"
                DOWNLOAD_BASE="${scheme}://${host}:3000"
                ;;
            "8000")
                MASTER_URL="${scheme}://${host}:8000"
                DOWNLOAD_BASE="${scheme}://${host}:3000"
                ;;
            *)
                MASTER_URL="$raw_url"
                DOWNLOAD_BASE="$raw_url"
                ;;
        esac
    else
        MASTER_URL="$raw_url"
        DOWNLOAD_BASE="$raw_url"
    fi
}

ensure_runtime_ready() {
    local py="/opt/patch-agent/venv/bin/python3"
    if [[ ! -x "$py" ]]; then
        return
    fi
    if "$py" - <<'PY' >/dev/null 2>&1
import flask, prometheus_client, psutil, requests, yaml
PY
    then
        return
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        warn "python3 not available for runtime repair."
        return
    fi
    rm -rf /opt/patch-agent/venv 2>/dev/null || true
    python3 -m venv /opt/patch-agent/venv || return
    /opt/patch-agent/venv/bin/python3 -m ensurepip --upgrade >/dev/null 2>&1 || true
    /opt/patch-agent/venv/bin/python3 -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
    /opt/patch-agent/venv/bin/python3 -m pip install -r /opt/patch-agent/requirements.txt >/dev/null 2>&1 || true
}

install_linux() {
    DISTRO=$(detect_distro)
    log "Detected OS: $DISTRO"

    normalize_urls

    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
            log "Installing for Debian/Ubuntu family..."
            # Try to get .deb from master
            log "Fetching agent package from ${DOWNLOAD_BASE}/download/agent-latest.deb"
            curl -fSL "${DOWNLOAD_BASE}/download/agent-latest.deb" -o /tmp/patch-agent.deb || curl -fSL "$MASTER_URL/static/agent-latest.deb" -o /tmp/patch-agent.deb || {
                err "Failed to download agent package from Master node. Is it air-gapped ready?"
                exit 1
            }
            if ! dpkg-deb -I /tmp/patch-agent.deb >/dev/null 2>&1; then
                err "Downloaded file is not a valid .deb (most likely a 404 HTML response)."
                err "Check these URLs in a browser:"
                err "  ${DOWNLOAD_BASE}/download/agent-latest.deb"
                err "  ${MASTER_URL}/static/agent-latest.deb"
                exit 1
            fi
            dpkg -i /tmp/patch-agent.deb || apt-get install -f -y
            ensure_runtime_ready
            ;;
        rhel|centos|rocky|alma|fedora|ol)
            log "Installing for RedHat family..."
            log "Fetching agent package from ${DOWNLOAD_BASE}/download/agent-latest.rpm"
            curl -fSL "${DOWNLOAD_BASE}/download/agent-latest.rpm" -o /tmp/patch-agent.rpm || curl -fSL "$MASTER_URL/static/agent-latest.rpm" -o /tmp/patch-agent.rpm || {
                err "Failed to download agent package from Master node."
                exit 1
            }
            rpm -Uvh /tmp/patch-agent.rpm || dnf localinstall -y /tmp/patch-agent.rpm
            ensure_runtime_ready
            ;;
        *)
            err "Unsupported Linux distribution: $DISTRO"
            exit 1
            ;;
    esac

    # Configure Agent
    log "Configuring agent..."
    mkdir -p /etc/patch-agent
    cat > /etc/patch-agent/config.yaml <<EOF
master_url: "$MASTER_URL"
agent_port: $AGENT_PORT
metrics_port: $METRICS_PORT
os_type: "$DISTRO"
EOF

    if [[ ! -f /etc/patch-agent/env ]]; then
        {
            echo "CONTROLLER_URL=${MASTER_URL%/}"
            echo "AGENT_PORT=${AGENT_PORT}"
            echo "METRICS_PORT=${METRICS_PORT}"
            [[ -n "${PATCHMASTER_SITE}" ]] && echo "PATCHMASTER_SITE=${PATCHMASTER_SITE}"
        } > /etc/patch-agent/env
    else
        if grep -q "^CONTROLLER_URL=" /etc/patch-agent/env 2>/dev/null; then
            sed -i "s|^CONTROLLER_URL=.*|CONTROLLER_URL=${MASTER_URL%/}|" /etc/patch-agent/env 2>/dev/null || true
        else
            echo "CONTROLLER_URL=${MASTER_URL%/}" >> /etc/patch-agent/env
        fi
        if grep -q "^AGENT_PORT=" /etc/patch-agent/env 2>/dev/null; then
            sed -i "s/^AGENT_PORT=.*/AGENT_PORT=${AGENT_PORT}/" /etc/patch-agent/env 2>/dev/null || true
        else
            echo "AGENT_PORT=${AGENT_PORT}" >> /etc/patch-agent/env
        fi
        if grep -q "^METRICS_PORT=" /etc/patch-agent/env 2>/dev/null; then
            sed -i "s/^METRICS_PORT=.*/METRICS_PORT=${METRICS_PORT}/" /etc/patch-agent/env 2>/dev/null || true
        else
            echo "METRICS_PORT=${METRICS_PORT}" >> /etc/patch-agent/env
        fi
        if [[ -n "${PATCHMASTER_SITE}" ]]; then
            if grep -q "^PATCHMASTER_SITE=" /etc/patch-agent/env 2>/dev/null; then
                sed -i "s/^PATCHMASTER_SITE=.*/PATCHMASTER_SITE=${PATCHMASTER_SITE}/" /etc/patch-agent/env 2>/dev/null || true
            else
                echo "PATCHMASTER_SITE=${PATCHMASTER_SITE}" >> /etc/patch-agent/env
            fi
        fi
    fi

    if ! command -v systemctl >/dev/null 2>&1; then
        warn "Systemd not available. Start manually: /opt/patch-agent/run-heartbeat.sh and /opt/patch-agent/run-api.sh"
        return
    fi

    local has_patch_service=0
    local has_heartbeat_service=0
    local has_api_service=0
    systemctl list-unit-files 2>/dev/null | grep -q '^patch-agent\.service' && has_patch_service=1 || true
    systemctl list-unit-files 2>/dev/null | grep -q '^patch-agent-heartbeat\.service' && has_heartbeat_service=1 || true
    systemctl list-unit-files 2>/dev/null | grep -q '^patch-agent-api\.service' && has_api_service=1 || true

    if [[ $has_patch_service -eq 0 && $has_heartbeat_service -eq 0 && $has_api_service -eq 0 && -x /opt/patch-agent/run-heartbeat.sh && -x /opt/patch-agent/run-api.sh ]]; then
        cat > /etc/systemd/system/patch-agent.service <<EOF
[Unit]
Description=PatchMaster Agent - Heartbeat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
EnvironmentFile=/etc/patch-agent/env
ExecStart=/opt/patch-agent/run-heartbeat.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
        cat > /etc/systemd/system/patch-agent-api.service <<EOF
[Unit]
Description=PatchMaster Agent - API Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
EnvironmentFile=/etc/patch-agent/env
ExecStart=/opt/patch-agent/run-api.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        has_patch_service=1
        has_api_service=1
    fi

    systemctl daemon-reload 2>/dev/null || true
    [[ $has_patch_service -eq 1 ]] && systemctl enable patch-agent.service 2>/dev/null || true
    [[ $has_heartbeat_service -eq 1 ]] && systemctl enable patch-agent-heartbeat.service 2>/dev/null || true
    [[ $has_api_service -eq 1 ]] && systemctl enable patch-agent-api.service 2>/dev/null || true
    [[ $has_patch_service -eq 1 ]] && systemctl restart patch-agent.service 2>/dev/null || true
    [[ $has_heartbeat_service -eq 1 ]] && systemctl restart patch-agent-heartbeat.service 2>/dev/null || true
    [[ $has_api_service -eq 1 ]] && systemctl restart patch-agent-api.service 2>/dev/null || true

    if systemctl is-active --quiet patch-agent.service 2>/dev/null || systemctl is-active --quiet patch-agent-heartbeat.service 2>/dev/null; then
        if systemctl is-active --quiet patch-agent-api.service 2>/dev/null || systemctl is-active --quiet patch-agent.service 2>/dev/null; then
            log "${GREEN}Agent installed and started successfully!${NC}"
            return
        fi
    fi
    warn "Systemd service not active. Check: systemctl status patch-agent patch-agent-heartbeat patch-agent-api"
}

if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    err "This script is for Linux. For Windows, use the installer EXE or install-agent.cmd."
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
   err "This script must be run as root (sudo)"
   exit 1
fi

banner
install_linux
