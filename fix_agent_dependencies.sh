#!/bin/bash
# Fix Patch-SecOps Solution Agent missing Python dependencies
# Run this on the AGENT machine (Ubuntu) to fix ModuleNotFoundError issues
#
# This script fixes:
#   - ModuleNotFoundError: No module named 'yaml' (PyYAML)
#   - ModuleNotFoundError: No module named 'requests'
#
# Usage: sudo bash fix_agent_dependencies.sh

set -e

echo "=== Patch-SecOps Solution Agent Dependency Fix ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "[ERROR] Please run as root (sudo)"
    exit 1
fi

AGENT_DIR="/opt/patch-agent"
VENV_DIR="${AGENT_DIR}/venv"
REQUIREMENTS_FILE="${AGENT_DIR}/requirements.txt"

echo "[1/6] Stopping agent services..."
systemctl stop patch-agent 2>/dev/null || true
systemctl stop patch-agent-heartbeat 2>/dev/null || true
echo "  ✓ Services stopped"

echo ""
echo "[2/6] Checking installation..."

if [ ! -d "$VENV_DIR" ]; then
    echo "[ERROR] Virtualenv not found at $VENV_DIR"
    echo "The agent may not be installed correctly."
    exit 1
fi

if [ ! -f "${VENV_DIR}/bin/python3" ]; then
    echo "[ERROR] Python3 not found in virtualenv"
    exit 1
fi

echo "  ✓ Virtualenv found: $VENV_DIR"
echo "  ✓ Python version: $("${VENV_DIR}/bin/python3" --version 2>&1)"

echo ""
echo "[3/6] Checking current package status..."

# List of required packages and their import names
declare -A PACKAGES=(
    ["PyYAML"]="yaml"
    ["requests"]="requests"
    ["flask"]="flask"
    ["psutil"]="psutil"
    ["prometheus-client"]="prometheus_client"
)

MISSING_PACKAGES=()

for pkg in "${!PACKAGES[@]}"; do
    import_name="${PACKAGES[$pkg]}"
    if "${VENV_DIR}/bin/python3" -c "import $import_name" 2>/dev/null; then
        echo "  ✓ $pkg (import $import_name)"
    else
        echo "  ✗ $pkg MISSING (import $import_name)"
        MISSING_PACKAGES+=("$pkg")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -eq 0 ]; then
    echo ""
    echo "All required packages are installed!"
    echo "Starting services..."
    systemctl start patch-agent 2>/dev/null || true
    systemctl start patch-agent-heartbeat 2>/dev/null || true
    echo "Done!"
    exit 0
fi

echo ""
echo "  Missing packages: ${MISSING_PACKAGES[*]}"

echo ""
echo "[4/6] Installing missing dependencies..."

# Upgrade pip first
echo "  Upgrading pip..."
"${VENV_DIR}/bin/python3" -m pip install --upgrade pip --quiet 2>/dev/null || {
    echo "  Warning: Could not upgrade pip, continuing..."
}

# Check if requirements.txt exists in agent directory
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "  Installing from requirements.txt..."
    "${VENV_DIR}/bin/pip3" install -r "$REQUIREMENTS_FILE" --quiet 2>/dev/null && {
        echo "  ✓ All dependencies installed from requirements.txt"
    } || {
        echo "  Warning: requirements.txt install had issues, trying individual packages..."
    }
else
    echo "  requirements.txt not found at $REQUIREMENTS_FILE"
    echo "  Installing individual missing packages..."
fi

# Install missing packages individually as fallback
for pkg in "${MISSING_PACKAGES[@]}"; do
    echo "  Installing $pkg..."
    "${VENV_DIR}/bin/pip3" install "$pkg" --quiet 2>/dev/null && {
        echo "    ✓ $pkg installed"
    } || {
        echo "    ✗ Failed to install $pkg"
    }
done

echo ""
echo "[5/6] Verifying installation..."

ALL_OK=true
for pkg in "${!PACKAGES[@]}"; do
    import_name="${PACKAGES[$pkg]}"
    if "${VENV_DIR}/bin/python3" -c "import $import_name" 2>/dev/null; then
        echo "  ✓ $pkg"
    else
        echo "  ✗ $pkg STILL MISSING"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo "[ERROR] Some packages are still missing!"
    echo ""
    echo "Possible solutions:"
    echo "1. Check internet connectivity on the agent machine"
    echo "2. If offline, download wheels on another machine and use:"
    echo "   ${VENV_DIR}/bin/pip3 install --no-index --find-links=/path/to/wheels -r $REQUIREMENTS_FILE"
    echo "3. Rebuild the agent package for your Python version"
    echo ""
    echo "Python version: $(python3 --version)"
    echo "Venv Python: $( "${VENV_DIR}/bin/python3" --version 2>&1 )"
    
    # Still try to start services
    echo ""
    echo "Attempting to start services anyway..."
else
    echo ""
    echo "  ✓ All dependencies verified!"
fi

echo ""
echo "[6/6] Starting agent services..."
systemctl daemon-reload
systemctl start patch-agent
systemctl start patch-agent-heartbeat

sleep 3

echo ""
echo "=== Service Status ==="
echo ""
echo "patch-agent service:"
systemctl status patch-agent --no-pager -l 2>/dev/null | head -10 || echo "  Service not found or not running"
echo ""
echo "patch-agent-heartbeat service:"
systemctl status patch-agent-heartbeat --no-pager -l 2>/dev/null | head -10 || echo "  Service not found or not running"

echo ""
echo "=== Recent Logs ==="
echo ""
echo "Last 5 agent log lines:"
journalctl -u patch-agent -n 5 --no-pager 2>/dev/null || echo "  No logs available"
echo ""
echo "Last 5 heartbeat log lines:"
journalctl -u patch-agent-heartbeat -n 5 --no-pager 2>/dev/null || echo "  No logs available"

echo ""
if [ "$ALL_OK" = true ]; then
    echo "=== Fix Complete ==="
    echo "The agent dependencies are now installed."
else
    echo "=== Fix Incomplete ==="
    echo "Some dependencies could not be installed. Please check the errors above."
fi