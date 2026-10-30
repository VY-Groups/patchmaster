#!/bin/bash
###############################################################################
# PatchMaster Agent - FreeBSD Package Builder (Portable Version)
# Creates .txz package for FreeBSD without requiring FreeBSD environment
###############################################################################

set -euo pipefail

VERSION="${1:-2.0.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/dist/freebsd-build"
PKG_NAME="patchmaster-agent"
PKG_FILE="${PKG_NAME}-${VERSION}.txz"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

log "Building FreeBSD package for PatchMaster Agent v${VERSION} (Portable Mode)"

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{usr/local/patch-agent,usr/local/etc/patch-agent,usr/local/etc/rc.d,usr/local/share/doc/patchmaster-agent}

# Copy agent files
log "Copying agent files..."
cp "$SCRIPT_DIR"/agent.py "$BUILD_DIR/usr/local/patch-agent/"
cp "$SCRIPT_DIR"/main.py "$BUILD_DIR/usr/local/patch-agent/"
cp "$SCRIPT_DIR"/requirements.txt "$BUILD_DIR/usr/local/patch-agent/"

# Create installation note
cat > "$BUILD_DIR/usr/local/share/doc/patchmaster-agent/INSTALL.txt" <<'EOF'
PatchMaster Agent for FreeBSD - Installation Instructions
==========================================================

This package contains the PatchMaster agent for FreeBSD systems.

INSTALLATION STEPS:
1. Install Python 3.8+ and pip:
   pkg install python3 py39-pip

2. Install Python dependencies:
   cd /usr/local/patch-agent
   pip install -r requirements.txt

3. Configure the agent:
   Edit /usr/local/etc/patch-agent/env and set:
   - CONTROLLER_URL=http://your-patchmaster-server:8000
   - AGENT_PORT=8080
   - METRICS_PORT=9100

4. Enable and start services:
   sysrc patch_agent_enable="YES"
   sysrc patch_agent_api_enable="YES"
   service patch_agent start
   service patch_agent_api start

5. Verify installation:
   service patch_agent status
   service patch_agent_api status

For more information, visit: https://github.com/VYGROUP/patchmaster
EOF

# Create run scripts
log "Creating run scripts..."
cat > "$BUILD_DIR/usr/local/patch-agent/run-heartbeat.sh" <<'EOF'
#!/bin/sh
. /usr/local/etc/patch-agent/env 2>/dev/null || true
exec /usr/local/bin/python3 /usr/local/patch-agent/main.py
EOF

cat > "$BUILD_DIR/usr/local/patch-agent/run-api.sh" <<'EOF'
#!/bin/sh
. /usr/local/etc/patch-agent/env 2>/dev/null || true
AGENT_PORT="${AGENT_PORT:-8080}"
METRICS_PORT="${METRICS_PORT:-9100}"
exec /usr/local/bin/python3 /usr/local/patch-agent/agent.py \
    --port "$AGENT_PORT" \
    --metrics-port "$METRICS_PORT"
EOF

chmod +x "$BUILD_DIR/usr/local/patch-agent"/*.sh

# Create rc.d service files (FreeBSD uses rc.d, not systemd)
log "Creating rc.d service files..."
cat > "$BUILD_DIR/usr/local/etc/rc.d/patch_agent" <<'EOF'
#!/bin/sh
# PROVIDE: patch_agent
# REQUIRE: NETWORKING
# KEYWORD: shutdown

. /etc/rc.subr

name="patch_agent"
rcvar="patch_agent_enable"
command="/usr/local/patch-agent/run-heartbeat.sh"
pidfile="/var/run/${name}.pid"
command_interpreter="/bin/sh"

load_rc_config $name
: ${patch_agent_enable:="NO"}

run_rc_command "$1"
EOF

cat > "$BUILD_DIR/usr/local/etc/rc.d/patch_agent_api" <<'EOF'
#!/bin/sh
# PROVIDE: patch_agent_api
# REQUIRE: NETWORKING
# KEYWORD: shutdown

. /etc/rc.subr

name="patch_agent_api"
rcvar="patch_agent_api_enable"
command="/usr/local/patch-agent/run-api.sh"
pidfile="/var/run/${name}.pid"
command_interpreter="/bin/sh"

load_rc_config $name
: ${patch_agent_api_enable:="NO"}

run_rc_command "$1"
EOF

chmod +x "$BUILD_DIR/usr/local/etc/rc.d"/*

# Create default config
cat > "$BUILD_DIR/usr/local/etc/patch-agent/env" <<'EOF'
CONTROLLER_URL=http://localhost:8000
AGENT_PORT=8080
METRICS_PORT=9100
EOF

# Create pkg manifest (+MANIFEST)
log "Creating package manifest..."
cat > "$BUILD_DIR/+MANIFEST" <<EOF
name: $PKG_NAME
version: $VERSION
origin: sysutils/patchmaster-agent
comment: PatchMaster Agent - Universal patch management agent
www: https://github.com/VYGROUP/patchmaster
maintainer: support@VYGROUP.com
prefix: /usr/local
desc: <<EOD
PatchMaster Agent provides universal patch management capabilities for FreeBSD systems.
It communicates with the PatchMaster backend to manage system updates, security patches,
and package installations.

This package requires Python 3.8+ and pip to be installed separately.
After installation, run: pip install -r /usr/local/patch-agent/requirements.txt
EOD
deps: {
  python3: {origin: lang/python3, version: "3.8"}
}
EOF

# Create post-install script (+POST_INSTALL)
cat > "$BUILD_DIR/+POST_INSTALL" <<'EOF'
#!/bin/sh
echo "=========================================="
echo "PatchMaster Agent Installation"
echo "=========================================="
echo ""
echo "IMPORTANT: Complete the installation by running:"
echo ""
echo "  1. Install Python dependencies:"
echo "     cd /usr/local/patch-agent"
echo "     pip install -r requirements.txt"
echo ""
echo "  2. Configure the agent:"
echo "     Edit /usr/local/etc/patch-agent/env"
echo "     Set CONTROLLER_URL to your PatchMaster server"
echo ""
echo "  3. Enable and start services:"
echo "     sysrc patch_agent_enable=YES"
echo "     sysrc patch_agent_api_enable=YES"
echo "     service patch_agent start"
echo "     service patch_agent_api start"
echo ""
echo "For detailed instructions, see:"
echo "/usr/local/share/doc/patchmaster-agent/INSTALL.txt"
echo ""
EOF

chmod +x "$BUILD_DIR/+POST_INSTALL"

# Create pre-deinstall script (+PRE_DEINSTALL)
cat > "$BUILD_DIR/+PRE_DEINSTALL" <<'EOF'
#!/bin/sh
service patch_agent stop 2>/dev/null || true
service patch_agent_api stop 2>/dev/null || true
sysrc -x patch_agent_enable 2>/dev/null || true
sysrc -x patch_agent_api_enable 2>/dev/null || true
EOF

chmod +x "$BUILD_DIR/+PRE_DEINSTALL"

# Create package using tar (FreeBSD .txz is just a tar.xz archive)
log "Creating package archive..."
cd "$BUILD_DIR"

# Check if xz is available
if ! command -v xz &> /dev/null; then
    warn "xz not found, installing..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y xz-utils
    elif command -v yum &> /dev/null; then
        sudo yum install -y xz
    fi
fi

# Create the .txz package (tar + xz compression)
tar -cJf "$SCRIPT_DIR/dist/$PKG_FILE" +MANIFEST +POST_INSTALL +PRE_DEINSTALL usr

success "Package created: $SCRIPT_DIR/dist/$PKG_FILE"

# Get package size
PKG_SIZE=$(du -h "$SCRIPT_DIR/dist/$PKG_FILE" | cut -f1)
log "Package size: $PKG_SIZE"

# Create symlink
cd "$SCRIPT_DIR/dist"
ln -sf "$PKG_FILE" "agent-latest.txz"
success "Symlink created: agent-latest.txz"

# Copy to backend/static
if [[ -d "$PROJECT_ROOT/backend/static" ]]; then
    cp "$SCRIPT_DIR/dist/$PKG_FILE" "$PROJECT_ROOT/backend/static/agent-latest.txz"
    success "Copied to backend/static/"
fi

log "FreeBSD package build complete!"
log ""
log "Installation on FreeBSD:"
log "  sudo pkg add $PKG_FILE"
log ""
log "Note: This package requires manual Python dependency installation."
log "See /usr/local/share/doc/patchmaster-agent/INSTALL.txt after installation."
