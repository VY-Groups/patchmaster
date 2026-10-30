#!/bin/bash
###############################################################################
# Patch-SecOps Solution - Complete Release Builder
# Builds all agents, frontend, and creates the final product package
###############################################################################

set -euo pipefail

VERSION="${1:-2.0.0}"
SKIP_FRONTEND="${2:-no}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
section() { echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"; echo -e "${CYAN}║${NC} $1"; echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"; }

section "Patch-SecOps Solution Complete Release Builder v${VERSION}"

START_TIME=$(date +%s)

# Step 1: Build frontend
if [[ "$SKIP_FRONTEND" == "no" ]]; then
    section "Step 1: Building Frontend"
    log "Building React frontend..."
    cd "$PROJECT_ROOT/frontend"
    
    if npm run build; then
        success "Frontend built successfully"
    else
        error "Frontend build failed"
        exit 1
    fi
else
    section "Step 1: Skipping Frontend Build"
    warn "Using existing frontend/dist"
fi

# Step 2: Build all agent packages
section "Step 2: Building All Agent Packages"
log "Running build-all-agents.sh..."

if bash "$SCRIPT_DIR/build-all-agents.sh" "$VERSION"; then
    success "All agent packages built"
else
    error "Agent build failed"
    exit 1
fi

# Step 3: Build product package
section "Step 3: Building Product Package"
log "Creating Patch-SecOps Solution product tarball..."

cd "$PROJECT_ROOT"

if bash packaging/build-package.sh --version "$VERSION" --skip-frontend-build; then
    success "Product package created"
else
    error "Product package build failed"
    exit 1
fi

# Step 4: Summary
section "Build Summary"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Patch-SecOps Solution v${VERSION} - Build Complete!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Build time: ${MINUTES}m ${SECONDS}s"
echo ""

# Show product package
if [[ -f "$PROJECT_ROOT/dist/patchmaster-${VERSION}.tar.gz" ]]; then
    PACKAGE_SIZE=$(du -h "$PROJECT_ROOT/dist/patchmaster-${VERSION}.tar.gz" | cut -f1)
    PACKAGE_SHA256=$(cat "$PROJECT_ROOT/dist/patchmaster-${VERSION}.tar.gz.sha256" 2>/dev/null | cut -d' ' -f1)
    
    echo "Product Package:"
    echo "  File: dist/patchmaster-${VERSION}.tar.gz"
    echo "  Size: $PACKAGE_SIZE"
    echo "  SHA256: $PACKAGE_SHA256"
    echo ""
fi

# Show agent packages
echo "Agent Packages (backend/static/):"
echo ""
cd "$PROJECT_ROOT/backend/static"

printf "  %-20s %-30s %s\n" "Platform" "File" "Size"
printf "  %-20s %-30s %s\n" "--------------------" "------------------------------" "----------"

[[ -f "agent-latest.deb" ]] && printf "  %-20s %-30s %s\n" "Debian/Ubuntu" "agent-latest.deb" "$(du -h agent-latest.deb | cut -f1)"
[[ -f "agent-latest.rpm" ]] && printf "  %-20s %-30s %s\n" "RHEL/RPM" "agent-latest.rpm" "$(du -h agent-latest.rpm | cut -f1)"
[[ -f "agent-latest.pkg.tar.zst" ]] && printf "  %-20s %-30s %s\n" "Arch Linux" "agent-latest.pkg.tar.zst" "$(du -h agent-latest.pkg.tar.zst | cut -f1)"
[[ -f "agent-latest.apk" ]] && printf "  %-20s %-30s %s\n" "Alpine Linux" "agent-latest.apk" "$(du -h agent-latest.apk | cut -f1)"
[[ -f "agent-latest.txz" ]] && printf "  %-20s %-30s %s\n" "FreeBSD" "agent-latest.txz" "$(du -h agent-latest.txz | cut -f1)"
[[ -f "agent-windows.zip" ]] && printf "  %-20s %-30s %s\n" "Windows" "agent-windows.zip" "$(du -h agent-windows.zip | cut -f1)"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

success "Release build complete!"

echo ""
log "Deployment instructions:"
echo "  1. Upload product package to server:"
echo "     scp dist/patchmaster-${VERSION}.tar.gz user@server:/path/"
echo ""
echo "  2. Extract and install:"
echo "     tar -xzf patchmaster-${VERSION}.tar.gz"
echo "     cd patchmaster"
echo "     bash install.sh"
echo ""
echo "  3. Agents are available at:"
echo "     http://your-server:8000/static/agent-latest.{deb,rpm,apk,txz}"
echo ""

