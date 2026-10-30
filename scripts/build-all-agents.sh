#!/bin/bash
###############################################################################
# Patch-SecOps Solution - Build All Agent Packages
# This script builds all platform agent packages with bundled dependencies
###############################################################################

set -euo pipefail

VERSION="${1:-2.0.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

log "Building all Patch-SecOps Solution agent packages v${VERSION}"
log "Project root: $PROJECT_ROOT"

# Step 1: Ensure vendor/wheels directory exists
log "Step 1: Checking vendor/wheels directory..."
if [[ ! -d "$PROJECT_ROOT/vendor/wheels" ]] || [[ -z "$(ls -A $PROJECT_ROOT/vendor/wheels 2>/dev/null)" ]]; then
    warn "vendor/wheels directory is empty or missing"
    log "Downloading Python dependencies..."
    
    mkdir -p "$PROJECT_ROOT/vendor/wheels"
    cd "$PROJECT_ROOT/vendor/wheels"
    
    # Download all dependencies
    if pip3 download --timeout 300 -r "$PROJECT_ROOT/agent/requirements.txt" --dest . 2>&1 | tee /tmp/pip-download.log; then
        success "Downloaded Python dependencies to vendor/wheels/"
    else
        error "Failed to download dependencies. Check /tmp/pip-download.log"
        exit 1
    fi
else
    success "vendor/wheels directory exists with $(ls -1 $PROJECT_ROOT/vendor/wheels | wc -l) wheel files"
fi

# Step 2: Build Linux agents (DEB, RPM, Arch, Alpine)
log "Step 2: Building Linux agent packages..."

cd "$PROJECT_ROOT/agent"

# Debian/Ubuntu
if [[ -f "build-deb.sh" ]]; then
    log "Building Debian package..."
    bash build-deb.sh "$VERSION" && success "Debian package built" || warn "Debian build failed"
else
    warn "build-deb.sh not found, skipping"
fi

# RHEL/RPM
if [[ -f "build-rpm.sh" ]]; then
    log "Building RPM package..."
    bash build-rpm.sh "$VERSION" && success "RPM package built" || warn "RPM build failed"
else
    warn "build-rpm.sh not found, skipping"
fi

# Arch Linux
if [[ -f "build-arch.sh" ]]; then
    log "Building Arch Linux package..."
    bash build-arch.sh "$VERSION" && success "Arch package built" || warn "Arch build failed"
else
    warn "build-arch.sh not found, skipping"
fi

# Alpine Linux
if [[ -f "build-apk.sh" ]]; then
    log "Building Alpine package..."
    bash build-apk.sh "$VERSION" && success "Alpine package built" || warn "Alpine build failed"
else
    warn "build-apk.sh not found, skipping"
fi

# Step 3: Build FreeBSD agent (bundled version)
log "Step 3: Building FreeBSD agent package (bundled)..."
if [[ -f "build-freebsd.sh" ]]; then
    bash build-freebsd.sh "$VERSION" && success "FreeBSD package built" || warn "FreeBSD build failed"
else
    warn "build-freebsd.sh not found, skipping"
fi

# Step 4: Build Windows agent
log "Step 4: Building Windows agent package..."
if [[ -f "build_agent_artifacts.py" ]]; then
    python3 build_agent_artifacts.py && success "Windows package built" || warn "Windows build failed"
else
    warn "build_agent_artifacts.py not found, skipping"
fi

# Step 5: Show summary
log "Step 5: Agent package summary..."
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Agent Package Build Summary"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if [[ -d "$PROJECT_ROOT/backend/static" ]]; then
    cd "$PROJECT_ROOT/backend/static"
    
    echo "Platform          | Package File              | Size"
    echo "------------------|---------------------------|----------"
    
    [[ -f "agent-latest.deb" ]] && printf "Debian/Ubuntu     | agent-latest.deb          | %s\n" "$(du -h agent-latest.deb | cut -f1)"
    [[ -f "agent-latest.rpm" ]] && printf "RHEL/RPM          | agent-latest.rpm          | %s\n" "$(du -h agent-latest.rpm | cut -f1)"
    [[ -f "agent-latest.pkg.tar.zst" ]] && printf "Arch Linux        | agent-latest.pkg.tar.zst  | %s\n" "$(du -h agent-latest.pkg.tar.zst | cut -f1)"
    [[ -f "agent-latest.apk" ]] && printf "Alpine Linux      | agent-latest.apk          | %s\n" "$(du -h agent-latest.apk | cut -f1)"
    [[ -f "agent-latest.txz" ]] && printf "FreeBSD           | agent-latest.txz          | %s\n" "$(du -h agent-latest.txz | cut -f1)"
    [[ -f "agent-windows.zip" ]] && printf "Windows           | agent-windows.zip         | %s\n" "$(du -h agent-windows.zip | cut -f1)"
    
    echo ""
    echo "All packages are located in: backend/static/"
    echo ""
else
    warn "backend/static directory not found"
fi

echo "═══════════════════════════════════════════════════════════════"
success "Agent package build complete!"
echo ""
log "Next steps:"
echo "  1. Test agents on target platforms"
echo "  2. Build Patch-SecOps Solution product package:"
echo "     bash packaging/build-package.sh --version $VERSION"
echo ""

