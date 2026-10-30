#!/bin/bash
###############################################################################
# PatchMaster Agent - Alpine Linux Package Builder
# Creates .apk package for Alpine Linux
###############################################################################

set -euo pipefail

VERSION="${1:-2.0.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/dist/alpine-build"
PKG_NAME="patchmaster-agent"
PKG_FILE="${PKG_NAME}-${VERSION}-r0.apk"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

# Set UTF-8 locale to handle Unicode characters
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

log "Building Alpine Linux package for PatchMaster Agent v${VERSION}"

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{opt/patch-agent,etc/patch-agent,etc/init.d,usr/share/doc/patchmaster-agent}

# Copy agent files
log "Copying agent files..."
cp "$SCRIPT_DIR"/agent.py "$BUILD_DIR/opt/patch-agent/"
cp "$SCRIPT_DIR"/main.py "$BUILD_DIR/opt/patch-agent/"
cp "$SCRIPT_DIR"/requirements.txt "$BUILD_DIR/opt/patch-agent/"

# Create bundled virtualenv (for air-gapped support)
log "Creating bundled virtualenv..."
python3 -m venv "$BUILD_DIR/opt/patch-agent/venv"

# Install dependencies into venv
log "Installing Python dependencies..."
VENV_PIP="$BUILD_DIR/opt/patch-agent/venv/bin/pip"

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
rm -rf "$BUILD_DIR/opt/patch-agent/venv/share" 2>/dev/null || true
find "$BUILD_DIR/opt/patch-agent/venv" -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR/opt/patch-agent/venv" -name '*.pyc' -delete 2>/dev/null || true

# Create run scripts
log "Creating run scripts..."
cat > "$BUILD_DIR/opt/patch-agent/run-heartbeat.sh" <<'EOF'
#!/bin/sh
. /etc/patch-agent/env 2>/dev/null || true
exec /opt/patch-agent/venv/bin/python3 /opt/patch-agent/main.py
EOF

cat > "$BUILD_DIR/opt/patch-agent/run-api.sh" <<'EOF'
#!/bin/sh
. /etc/patch-agent/env 2>/dev/null || true
AGENT_PORT="${AGENT_PORT:-8080}"
METRICS_PORT="${METRICS_PORT:-9100}"
exec /opt/patch-agent/venv/bin/python3 /opt/patch-agent/agent.py \
    --port "$AGENT_PORT" \
    --metrics-port "$METRICS_PORT"
EOF

chmod +x "$BUILD_DIR/opt/patch-agent"/*.sh

# Create OpenRC init scripts (Alpine uses OpenRC, not systemd)
log "Creating OpenRC init scripts..."
cat > "$BUILD_DIR/etc/init.d/patch-agent" <<'EOF'
#!/sbin/openrc-run

name="PatchMaster Agent - Heartbeat"
description="PatchMaster Agent Heartbeat Service"
command="/opt/patch-agent/run-heartbeat.sh"
command_background=true
pidfile="/run/patch-agent.pid"

depend() {
    need net
    after firewall
}

start_pre() {
    checkpath --directory --mode 0755 /var/log/patch-agent
    checkpath --directory --mode 0755 /var/lib/patch-agent
}
EOF

cat > "$BUILD_DIR/etc/init.d/patch-agent-api" <<'EOF'
#!/sbin/openrc-run

name="PatchMaster Agent - API Server"
description="PatchMaster Agent API Service"
command="/opt/patch-agent/run-api.sh"
command_background=true
pidfile="/run/patch-agent-api.pid"

depend() {
    need net
    after firewall
}

start_pre() {
    checkpath --directory --mode 0755 /var/log/patch-agent
    checkpath --directory --mode 0755 /var/lib/patch-agent
}
EOF

chmod +x "$BUILD_DIR/etc/init.d"/*

# Create default config
cat > "$BUILD_DIR/etc/patch-agent/env" <<'EOF'
CONTROLLER_URL=http://localhost:8000
AGENT_PORT=8080
METRICS_PORT=9100
EOF

# Create .PKGINFO for apk
log "Creating package metadata..."
cat > "$BUILD_DIR/.PKGINFO" <<EOF
pkgname = $PKG_NAME
pkgver = $VERSION-r0
pkgdesc = PatchMaster Agent - Universal patch management agent
url = https://github.com/VYGROUP/patchmaster
builddate = $(date +%s)
packager = PatchMaster Build System
size = $(du -sb "$BUILD_DIR" | cut -f1)
arch = x86_64
license = MIT
depend = python3
depend = py3-pip
EOF

# Create post-install script
cat > "$BUILD_DIR/.post-install" <<'EOF'
#!/bin/sh
echo "Setting up PatchMaster Agent..."

# Virtualenv is already bundled, just enable services
rc-update add patch-agent default
rc-update add patch-agent-api default
rc-service patch-agent start
rc-service patch-agent-api start

echo "PatchMaster Agent installed successfully!"
echo "Check status: rc-service patch-agent status"
EOF

chmod +x "$BUILD_DIR/.post-install"

# Create pre-deinstall script
cat > "$BUILD_DIR/.pre-deinstall" <<'EOF'
#!/bin/sh
rc-service patch-agent stop 2>/dev/null || true
rc-service patch-agent-api stop 2>/dev/null || true
rc-update del patch-agent default 2>/dev/null || true
rc-update del patch-agent-api default 2>/dev/null || true
EOF

chmod +x "$BUILD_DIR/.pre-deinstall"

# Create package using tar and gzip (Alpine apk format)
log "Creating package archive..."
cd "$BUILD_DIR"

# Create control.tar.gz
tar -czf control.tar.gz .PKGINFO .post-install .pre-deinstall

# Create data.tar.gz
tar -czf data.tar.gz opt etc

# Combine into .apk (which is just a tar.gz with specific structure)
tar -czf "$SCRIPT_DIR/dist/$PKG_FILE" control.tar.gz data.tar.gz

success "Package created: $SCRIPT_DIR/dist/$PKG_FILE"

# Create symlink
cd "$SCRIPT_DIR/dist"
ln -sf "$PKG_FILE" "agent-latest.apk"
success "Symlink created: agent-latest.apk"

# Copy to backend/static
if [[ -d "$PROJECT_ROOT/backend/static" ]]; then
    cp "$SCRIPT_DIR/dist/$PKG_FILE" "$PROJECT_ROOT/backend/static/agent-latest.apk"
    success "Copied to backend/static/"
fi

log "Alpine Linux package build complete!"
log "Install with: apk add --allow-untrusted $PKG_FILE"
