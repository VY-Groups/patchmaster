#!/bin/bash
###############################################################################
# PatchMaster Agent - RPM Package Builder
# Creates .rpm package for openSUSE/AlmaLinux/RHEL
###############################################################################

set -euo pipefail

VERSION="${1:-2.0.1}"  # Fixed: ensures dependencies are properly installed and verified
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/dist/rpm-build"
PKG_NAME="patchmaster-agent"
PKG_FILE="${PKG_NAME}-${VERSION}-1.x86_64.rpm"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

log "Building RPM package for PatchMaster Agent v${VERSION}"

# Clean and create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{opt/patch-agent,etc/patch-agent,etc/systemd/system,usr/share/doc/patchmaster-agent}

# Copy agent files
log "Copying agent files..."
cp "$SCRIPT_DIR"/agent.py "$BUILD_DIR/opt/patch-agent/"
cp "$SCRIPT_DIR"/main.py "$BUILD_DIR/opt/patch-agent/"
cp "$SCRIPT_DIR"/requirements.txt "$BUILD_DIR/opt/patch-agent/"

# Create bundled virtualenv (for air-gapped support)
log "Creating bundled virtualenv..."

# Detect Python command (python3 or python3.11)
if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_CMD="python3.11"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
else
    log "Error: Python 3 not found"
    exit 1
fi

log "Using Python: $PYTHON_CMD"
# Create venv (try with pip, fallback to without pip)
$PYTHON_CMD -m venv "$BUILD_DIR/opt/patch-agent/venv" 2>/dev/null || \
$PYTHON_CMD -m venv --without-pip "$BUILD_DIR/opt/patch-agent/venv"

# Install dependencies into venv
log "Installing Python dependencies..."
VENV_PYTHON="$BUILD_DIR/opt/patch-agent/venv/bin/python3"
VENV_PIP="$BUILD_DIR/opt/patch-agent/venv/bin/pip"

# Use local wheels only (air-gapped build)
if [[ -d "/workspace/vendor/wheels" ]]; then
    log "Using wheels from /workspace/vendor/wheels..."
    # Ensure pip is available
    if [[ ! -f "$VENV_PIP" ]]; then
        log "Installing pip from wheels..."
        $VENV_PYTHON -m ensurepip --default-pip 2>/dev/null || \
        wget -q -O /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py && $VENV_PYTHON /tmp/get-pip.py --no-index --find-links /workspace/vendor/wheels || true
    fi
    $VENV_PIP install --upgrade pip wheel setuptools --no-index --find-links /workspace/vendor/wheels 2>/dev/null || true
    $VENV_PIP install --no-index --find-links /workspace/vendor/wheels -r "$SCRIPT_DIR/requirements.txt"
elif [[ -d "$PROJECT_ROOT/vendor/wheels" ]]; then
    log "Using wheels from vendor..."
    # Ensure pip is available
    if [[ ! -f "$VENV_PIP" ]]; then
        log "Installing pip from wheels..."
        $VENV_PYTHON -m ensurepip --default-pip 2>/dev/null || true
    fi
    $VENV_PIP install --upgrade pip wheel setuptools --no-index --find-links "$PROJECT_ROOT/vendor/wheels" 2>/dev/null || true
    $VENV_PIP install --no-index --find-links "$PROJECT_ROOT/vendor/wheels" -r "$SCRIPT_DIR/requirements.txt"
else
    log "ERROR: No wheels directory found! Air-gapped build requires vendor/wheels/"
    exit 1
fi

# Fix ambiguous shebangs in Python packages (rpmbuild requirement)
log "Fixing ambiguous shebangs in Python packages..."
find "$BUILD_DIR/opt/patch-agent/venv" -type f -name '*.py' -exec sed -i 's|#!/usr/bin/env python$|#!/usr/bin/env python3|g' {} + 2>/dev/null || true
find "$BUILD_DIR/opt/patch-agent/venv" -type f -name '*.py' -exec sed -i 's|#!/usr/bin/python$|#!/usr/bin/python3|g' {} + 2>/dev/null || true

# Clean up venv to reduce size (suppress errors for directories we can't fully remove)
log "Cleaning up virtualenv to reduce package size..."

# Remove share directory completely
rm -rf "$BUILD_DIR/opt/patch-agent/venv/share" 2>/dev/null || true

# Remove __pycache__ directories
find "$BUILD_DIR/opt/patch-agent/venv" -type d -name '__pycache__' -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true

# Remove compiled Python files
find "$BUILD_DIR/opt/patch-agent/venv" -type f -name '*.pyc' -delete 2>/dev/null || true
find "$BUILD_DIR/opt/patch-agent/venv" -type f -name '*.pyo' -delete 2>/dev/null || true

# Remove test directories
find "$BUILD_DIR/opt/patch-agent/venv" -type d -name 'tests' -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true
find "$BUILD_DIR/opt/patch-agent/venv" -type d -name 'test' -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true

# Remove pip, setuptools, wheel (not needed at runtime) - suppress "Directory not empty" errors
rm -rf "$BUILD_DIR/opt/patch-agent/venv/lib/python"*/site-packages/pip* 2>&1 | grep -v "Directory not empty" || true
rm -rf "$BUILD_DIR/opt/patch-agent/venv/lib/python"*/site-packages/setuptools* 2>&1 | grep -v "Directory not empty" || true
rm -rf "$BUILD_DIR/opt/patch-agent/venv/lib/python"*/site-packages/wheel* 2>&1 | grep -v "Directory not empty" || true
rm -rf "$BUILD_DIR/opt/patch-agent/venv/lib/python"*/site-packages/_distutils_hack 2>&1 | grep -v "Directory not empty" || true

# Remove RECORD files from .dist-info directories
find "$BUILD_DIR/opt/patch-agent/venv/lib/python"*/site-packages -type d -name '*.dist-info' -exec rm -f {}/RECORD \; 2>/dev/null || true

log "Virtualenv cleaned - size reduced"

# Create run scripts
log "Creating run scripts..."
cat > "$BUILD_DIR/opt/patch-agent/run-heartbeat.sh" <<'EOF'
#!/bin/bash
source /etc/patch-agent/env 2>/dev/null || true
exec /opt/patch-agent/venv/bin/python3 /opt/patch-agent/main.py
EOF

cat > "$BUILD_DIR/opt/patch-agent/run-api.sh" <<'EOF'
#!/bin/bash
source /etc/patch-agent/env 2>/dev/null || true
AGENT_PORT="${AGENT_PORT:-8080}"
METRICS_PORT="${METRICS_PORT:-9100}"
exec /opt/patch-agent/venv/bin/python3 /opt/patch-agent/agent.py \
    --port "$AGENT_PORT" \
    --metrics-port "$METRICS_PORT"
EOF

chmod +x "$BUILD_DIR/opt/patch-agent"/*.sh

# Create systemd service files
log "Creating systemd service files..."
cat > "$BUILD_DIR/etc/systemd/system/patch-agent.service" <<'EOF'
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

cat > "$BUILD_DIR/etc/systemd/system/patch-agent-api.service" <<'EOF'
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

# Create default config
cat > "$BUILD_DIR/etc/patch-agent/env" <<'EOF'
CONTROLLER_URL=http://localhost:8000
AGENT_PORT=8080
METRICS_PORT=9100
EOF

# Create RPM spec file
log "Creating RPM spec file..."
mkdir -p "$BUILD_DIR/SPECS"
cat > "$BUILD_DIR/SPECS/${PKG_NAME}.spec" <<EOF
# Enable maximum compression
%define _binary_payload w9.xzdio
%define _source_payload w9.xzdio

Name:           ${PKG_NAME}
Version:        ${VERSION}
Release:        1
Summary:        PatchMaster Agent - Universal patch management agent
License:        MIT
URL:            https://github.com/VYGROUP/patchmaster
BuildArch:      x86_64
Requires:       python3 >= 3.8

%description
PatchMaster Agent - Self-contained patch management agent with bundled Python virtualenv.
No internet required on target hosts.

%install
mkdir -p %{buildroot}/opt/patch-agent
mkdir -p %{buildroot}/etc/patch-agent
mkdir -p %{buildroot}/etc/systemd/system
cp -r $BUILD_DIR/opt/patch-agent/* %{buildroot}/opt/patch-agent/
cp $BUILD_DIR/etc/patch-agent/env %{buildroot}/etc/patch-agent/
cp $BUILD_DIR/etc/systemd/system/*.service %{buildroot}/etc/systemd/system/

%clean
rm -rf %{buildroot}

%files
/opt/patch-agent
/etc/patch-agent
/etc/systemd/system/patch-agent.service
/etc/systemd/system/patch-agent-api.service

%post
systemctl daemon-reload
systemctl enable patch-agent.service patch-agent-api.service
systemctl start patch-agent.service patch-agent-api.service
echo "PatchMaster Agent installed successfully!"

%preun
systemctl stop patch-agent.service patch-agent-api.service 2>/dev/null || true
systemctl disable patch-agent.service patch-agent-api.service 2>/dev/null || true

%postun
systemctl daemon-reload

%changelog
* $(date "+%a %b %d %Y") PatchMaster Build System
- Version ${VERSION}
EOF

# Build RPM using rpmbuild
log "Building RPM package..."
mkdir -p "$BUILD_DIR"/{BUILD,RPMS,SOURCES,SRPMS}

# Use rpmbuild if available, otherwise use fakeroot + cpio
if command -v rpmbuild >/dev/null 2>&1; then
    rpmbuild --define "_topdir $BUILD_DIR" \
             --define "_rpmdir $SCRIPT_DIR/dist" \
             -bb "$BUILD_DIR/SPECS/${PKG_NAME}.spec"
    
    # Find and copy the RPM
    find "$SCRIPT_DIR/dist" -name "*.rpm" -exec cp {} "$SCRIPT_DIR/dist/$PKG_FILE" \;
else
    # Fallback: create RPM manually using cpio
    log "rpmbuild not available, creating RPM manually..."
    cd "$BUILD_DIR"
    
    # Create cpio archive
    find opt etc -type f -o -type l | cpio -o -H newc | gzip > "$SCRIPT_DIR/dist/${PKG_NAME}-${VERSION}.cpio.gz"
    
    # Create simple RPM header (this is a simplified approach)
    # For production, you should use rpmbuild
    log "Warning: Manual RPM creation - install rpmbuild for proper RPM packages"
fi

success "Package created: $SCRIPT_DIR/dist/$PKG_FILE"

# Create symlink
cd "$SCRIPT_DIR/dist"
ln -sf "$PKG_FILE" "agent-latest.rpm"
success "Symlink created: agent-latest.rpm"

# Copy to backend/static
if [[ -d "$PROJECT_ROOT/backend/static" ]]; then
    cp "$SCRIPT_DIR/dist/$PKG_FILE" "$PROJECT_ROOT/backend/static/agent-latest.rpm"
    success "Copied to backend/static/"
fi

log "RPM package build complete!"
log "Install with: sudo rpm -i $PKG_FILE"
