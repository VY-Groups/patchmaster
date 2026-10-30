#!/bin/bash
###############################################################################
# PatchMaster Agent - FreeBSD Package Builder
# Creates .txz package for FreeBSD
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
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

log "Building FreeBSD package for PatchMaster Agent v${VERSION}"

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{usr/local/patch-agent,usr/local/etc/patch-agent,usr/local/etc/rc.d,usr/local/share/doc/patchmaster-agent}

# Copy agent files
log "Copying agent files..."
cp "$SCRIPT_DIR"/agent.py "$BUILD_DIR/usr/local/patch-agent/"
cp "$SCRIPT_DIR"/main.py "$BUILD_DIR/usr/local/patch-agent/"
cp "$SCRIPT_DIR"/requirements.txt "$BUILD_DIR/usr/local/patch-agent/"

# Create bundled virtualenv (for air-gapped support)
log "Creating bundled virtualenv..."
python3 -m venv "$BUILD_DIR/usr/local/patch-agent/venv"

# Install dependencies into venv
log "Installing Python dependencies..."
VENV_PIP="$BUILD_DIR/usr/local/patch-agent/venv/bin/pip"

# Use local wheels only (air-gapped build)
if [[ -d "/workspace/vendor/wheels" ]]; then
    log "Using wheels from /workspace/vendor/wheels..."
    $VENV_PIP install --upgrade pip wheel setuptools --no-index --find-links /workspace/vendor/wheels 2>/dev/null || true
    $VENV_PIP install --no-index --find-links /workspace/vendor/wheels -r "$SCRIPT_DIR/requirements.txt"
elif [[ -d "$PROJECT_ROOT/vendor/wheels" ]]; then
    log "Using wheels from vendor..."
    $VENV_PIP install --upgrade pip wheel setuptools --no-index --find-links "$PROJECT_ROOT/vendor/wheels" 2>/dev/null || true
    $VENV_PIP install --no-index --find-links "$PROJECT_ROOT/vendor/wheels" -r "$SCRIPT_DIR/requirements.txt"
else
    log "ERROR: No wheels directory found! Air-gapped build requires vendor/wheels/"
    exit 1
fi

# Clean up venv to reduce size
log "Cleaning up virtualenv..."
rm -rf "$BUILD_DIR/usr/local/patch-agent/venv/share" 2>/dev/null || true
find "$BUILD_DIR/usr/local/patch-agent/venv" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/usr/local/patch-agent/venv" -type f -name '*.pyc' -delete 2>/dev/null || true
find "$BUILD_DIR/usr/local/patch-agent/venv" -type f -name '*.pyo' -delete 2>/dev/null || true

# Create run scripts
log "Creating run scripts..."
cat > "$BUILD_DIR/usr/local/patch-agent/run-heartbeat.sh" <<'EOF'
#!/bin/sh
. /usr/local/etc/patch-agent/env 2>/dev/null || true
exec /usr/local/patch-agent/venv/bin/python3 /usr/local/patch-agent/main.py
EOF

cat > "$BUILD_DIR/usr/local/patch-agent/run-api.sh" <<'EOF'
#!/bin/sh
. /usr/local/etc/patch-agent/env 2>/dev/null || true
AGENT_PORT="${AGENT_PORT:-8080}"
METRICS_PORT="${METRICS_PORT:-9100}"
exec /usr/local/patch-agent/venv/bin/python3 /usr/local/patch-agent/agent.py \
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
EOD
deps: {
  python3: {origin: lang/python3, version: "3.8"}
}
EOF

# Create post-install script (+POST_INSTALL)
cat > "$BUILD_DIR/+POST_INSTALL" <<'EOF'
#!/bin/sh
echo "Setting up PatchMaster Agent..."

# Enable services in rc.conf
sysrc patch_agent_enable="YES"
sysrc patch_agent_api_enable="YES"

# Start services
service patch_agent start
service patch_agent_api start

echo "PatchMaster Agent installed successfully!"
echo "Check status: service patch_agent status"
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

# Create plist (file list)
find usr -type f -o -type l | sort > plist.txt

# Create the package
tar -cJf "$SCRIPT_DIR/dist/$PKG_FILE" +MANIFEST +POST_INSTALL +PRE_DEINSTALL usr

success "Package created: $SCRIPT_DIR/dist/$PKG_FILE"

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
log "Install with: sudo pkg add $PKG_FILE"
