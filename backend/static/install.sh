#!/bin/bash
# PatchMaster Agent Installer (Offline / Air-Gapped)
# Usage: curl -sS http://<master-ip>:3000/download/install.sh | sudo bash -s -- <master-ip>
#
# The .deb package is fully self-contained with a bundled Python virtualenv.
# No internet access required on the target host.
set -euo pipefail

MASTER_IP="${1:-}"
if [ -z "$MASTER_IP" ]; then
  echo "ERROR: Master IP required."
  echo "Usage: curl -sS http://<master-ip>/download/install.sh | sudo bash -s -- <master-ip>"
  exit 1
fi

MASTER_URL="http://${MASTER_IP}:8000"
DEB_URL="http://${MASTER_IP}/static/agent-latest.deb"
TMP_DEB="/tmp/patch-agent.deb"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

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
echo "     Agent Installer (Offline/Air-Gapped)"
echo "  Master: ${MASTER_IP}"
echo

# Check root
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: This script must be run as root (use sudo)."
  exit 1
fi

# Check OS
if ! command -v dpkg >/dev/null 2>&1; then
  echo "ERROR: This installer requires a Debian/Ubuntu system (dpkg not found)."
  exit 1
fi

# Download agent .deb
echo "[1/4] Downloading agent package..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL -o "$TMP_DEB" "$DEB_URL"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP_DEB" "$DEB_URL"
else
  echo "ERROR: Neither curl nor wget found."
  exit 1
fi
echo "      Downloaded to ${TMP_DEB}"

# Install .deb (self-contained — all Python deps bundled in virtualenv)
echo "[2/4] Installing agent package..."
dpkg -i "$TMP_DEB"
echo "      Package installed (all dependencies bundled)."

# Configure master URL
echo "[3/4] Configuring agent to report to ${MASTER_IP}..."
mkdir -p /etc/patch-agent
cat > /etc/patch-agent/env <<EOF
CONTROLLER_URL=http://${MASTER_IP}:8000
EOF

# Create and start systemd services using bundled venv
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

echo "[4/4] Starting agent services..."
systemctl daemon-reload
systemctl enable --now patch-agent.service
systemctl enable --now patch-agent-api.service
sleep 3

if systemctl is-active --quiet patch-agent && systemctl is-active --quiet patch-agent-api; then
  echo ""
  echo -e "${GREEN}Agent installed and running!${NC}"
  echo "  Heartbeat service: active"
  echo "  API service (port 8080): active"
  echo "  Host will appear in PatchMaster dashboard within 60 seconds."
  echo ""
else
  echo ""
  echo "WARNING: One or more services may not have started."
  echo "  Check: sudo systemctl status patch-agent"
  echo "  Check: sudo systemctl status patch-agent-api"
  echo "  Logs:  sudo journalctl -u patch-agent -n 20"
fi

# Cleanup
rm -f "$TMP_DEB"
