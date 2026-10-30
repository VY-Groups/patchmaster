#!/bin/bash
###############################################################################
# Patch-SecOps Solution Unified Package Builder
# Single script to build all package types
###############################################################################

set -euo pipefail

VERSION="${1:-2.0.0}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_banner() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                            ║${NC}"
    echo -e "${CYAN}║         Patch-SecOps Solution Unified Package Builder v${VERSION}        ║${NC}"
    echo -e "${CYAN}║                                                            ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

show_menu() {
    echo -e "${CYAN}Select package type to build:${NC}"
    echo ""
    echo -e "  ${GREEN}1)${NC} Customer Package       ${YELLOW}(External - Ship to customers)${NC}"
    echo -e "     Output: dist/patchmaster-${VERSION}.tar.gz"
    echo -e "     Size: ~100-150 MB"
    echo ""
    echo -e "  ${GREEN}2)${NC} Vendor Package         ${YELLOW}(External - Ship to vendors/MSPs)${NC}"
    echo -e "     Output: vendor/dist/patchmaster-vendor-${VERSION}.tar.gz"
    echo -e "     Size: ~5-10 MB"
    echo ""
    echo -e "  ${GREEN}3)${NC} Developer Kit          ${RED}(Internal - NEVER ship externally)${NC}"
    echo -e "     Output: dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz"
    echo -e "     Size: ~200-300 MB"
    echo ""
    echo -e "  ${GREEN}4)${NC} Build All Packages     ${CYAN}(Customer + Vendor + Developer)${NC}"
    echo ""
    echo -e "  ${GREEN}5)${NC} Build External Only    ${CYAN}(Customer + Vendor)${NC}"
    echo ""
    echo -e "  ${GREEN}0)${NC} Exit"
    echo ""
}

build_customer_package() {
    log "Building Customer Package..."
    echo ""
    bash packaging/build-package.sh --output dist --version "$VERSION"
}

build_vendor_package() {
    log "Building Vendor Package..."
    echo ""
    
    # Vendor package includes ONLY:
    # - Vendor portal application (Flask app)
    # - Templates and static files
    # - Deployment files (Docker, nginx)
    # - Installation/management scripts
    # This is for MSPs/vendors who manage licenses
    
    local DIST_DIR="vendor/dist"
    local PACKAGE_NAME="patchmaster-vendor-${VERSION}.tar.gz"
    local PACKAGE_PATH="${DIST_DIR}/${PACKAGE_NAME}"
    local TEMP_DIR="vendor-pkg-$(date +%s)"
    
    mkdir -p "$DIST_DIR"
    mkdir -p "$TEMP_DIR"
    
    log "[1/5] Copying vendor portal application..."
    cp vendor/app.py "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/generate-license.py "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/requirements.txt "$TEMP_DIR/"
    
    log "[2/5] Copying templates and static files..."
    cp -r vendor/templates "$TEMP_DIR/" 2>/dev/null || true
    [[ -d "vendor/static" ]] && cp -r vendor/static "$TEMP_DIR/" || mkdir -p "$TEMP_DIR/static"
    
    log "[3/4] Copying deployment files..."
    cp vendor/Dockerfile "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/docker-compose.yml "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/nginx.conf "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/.env.example "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/Makefile "$TEMP_DIR/" 2>/dev/null || true
    
    log "[4/4] Copying installation scripts..."
    cp vendor/install-vendor.sh "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/uninstall-vendor.sh "$TEMP_DIR/" 2>/dev/null || true
    cp vendor/update-vendor.sh "$TEMP_DIR/" 2>/dev/null || true
    cp .license-authority.env "$TEMP_DIR/patchmaster-license-authority.env" 2>/dev/null || true
    cp vendor/README.md "$TEMP_DIR/" 2>/dev/null || true
    
    # Create empty certs directory
    mkdir -p "$TEMP_DIR/certs"
    
    log "Creating tarball..."
    tar -czf "$PACKAGE_PATH" \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.log' \
        --exclude='.DS_Store' \
        -C "$TEMP_DIR" .
    
    rm -rf "$TEMP_DIR"
    
    if [[ -f "$PACKAGE_PATH" ]]; then
        local size=$(du -h "$PACKAGE_PATH" | cut -f1)
        success "Vendor package created: $PACKAGE_PATH ($size)"
        return 0
    else
        error "Vendor package build failed"
        return 1
    fi
}

build_developer_kit() {
    warn "⚠️  Building Developer Kit (INTERNAL USE ONLY)"
    warn "⚠️  This package contains source code and must NEVER be distributed externally"
    echo ""
    
    local DIST_DIR="dist/developer"
    local PACKAGE_NAME="patchmaster-developer-kit-${VERSION}.tar.gz"
    local PACKAGE_PATH="${DIST_DIR}/${PACKAGE_NAME}"
    local TEMP_DIR="devkit-pkg-$(date +%s)"
    
    mkdir -p "$DIST_DIR"
    mkdir -p "$TEMP_DIR"
    
    log "[1/6] Copying complete source code..."
    
    # Copy agent
    [[ -d "agent" ]] && cp -r agent "$TEMP_DIR/" 2>/dev/null || true
    
    # Copy backend
    [[ -d "backend" ]] && cp -r backend "$TEMP_DIR/" 2>/dev/null || true
    
    # Copy frontend
    [[ -d "frontend" ]] && cp -r frontend "$TEMP_DIR/" 2>/dev/null || true
    
    # Copy vendor but exclude python-testdeps (has permission issues)
    log "    Copying vendor (excluding python-testdeps)..."
    mkdir -p "$TEMP_DIR/vendor"
    [[ -f "vendor/app.py" ]] && cp vendor/app.py "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -f "vendor/generate-license.py" ]] && cp vendor/generate-license.py "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -f "vendor/requirements.txt" ]] && cp vendor/requirements.txt "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -f "vendor/Makefile" ]] && cp vendor/Makefile "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -f "vendor/Dockerfile" ]] && cp vendor/Dockerfile "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -f "vendor/docker-compose.yml" ]] && cp vendor/docker-compose.yml "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -d "vendor/templates" ]] && cp -r vendor/templates "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -d "vendor/static" ]] && cp -r vendor/static "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -d "vendor/wheels" ]] && cp -r vendor/wheels "$TEMP_DIR/vendor/" 2>/dev/null || true
    [[ -d "dist" ]] && cp -r dist "$TEMP_DIR/vendor/" 2>/dev/null || true
    
    # Copy scripts
    [[ -d "scripts" ]] && cp -r scripts "$TEMP_DIR/" 2>/dev/null || true
    
    log "[2/6] Copying documentation..."
    cp -r docs "$TEMP_DIR/"
    
    log "[3/6] Copying build scripts..."
    cp build-packages.sh "$TEMP_DIR/"
    cp rebuild-all.ps1 "$TEMP_DIR/" 2>/dev/null || true
    cp pull-images.ps1 "$TEMP_DIR/" 2>/dev/null || true
    
    log "[4/6] Copying deployment files..."
    cp docker-compose*.yml "$TEMP_DIR/" 2>/dev/null || true
    cp Makefile "$TEMP_DIR/" 2>/dev/null || true
    cp auto-setup.* "$TEMP_DIR/" 2>/dev/null || true
    cp .gitignore "$TEMP_DIR/" 2>/dev/null || true
    
    log "[5/6] Cleaning temp files from copy..."
    find "$TEMP_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$TEMP_DIR" -name '*.pyc' -delete 2>/dev/null || true
    find "$TEMP_DIR" -name '.pytest_cache' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$TEMP_DIR" -name 'node_modules' -type d -exec rm -rf {} + 2>/dev/null || true
    
    log "[6/6] Creating tarball..."
    tar -czf "$PACKAGE_PATH" \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache' \
        --exclude='node_modules' \
        --exclude='.venv' \
        --exclude='*.log' \
        --exclude='python-testdeps' \
        --exclude='.git' \
        -C "$TEMP_DIR" .
    
    rm -rf "$TEMP_DIR"
    
    if [[ -f "$PACKAGE_PATH" ]]; then
        local size=$(du -h "$PACKAGE_PATH" | cut -f1)
        success "Developer kit created: $PACKAGE_PATH ($size)"
        warn "⚠️  Remember: NEVER distribute this package externally"
        return 0
    else
        error "Developer kit build failed"
        return 1
    fi
}

build_all() {
    log "Building ALL packages..."
    echo ""
    
    local failed=0
    
    build_customer_package || ((failed++))
    echo ""
    
    build_vendor_package || ((failed++))
    echo ""
    
    build_developer_kit || ((failed++))
    echo ""
    
    if [[ $failed -eq 0 ]]; then
        success "All packages built successfully!"
        show_summary
        return 0
    else
        error "$failed package(s) failed to build"
        return 1
    fi
}

build_external_only() {
    log "Building EXTERNAL packages only (Customer + Vendor)..."
    echo ""
    
    local failed=0
    
    build_customer_package || ((failed++))
    echo ""
    
    build_vendor_package || ((failed++))
    echo ""
    
    if [[ $failed -eq 0 ]]; then
        success "External packages built successfully!"
        show_external_summary
        return 0
    else
        error "$failed package(s) failed to build"
        return 1
    fi
}

show_summary() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                    BUILD SUMMARY                           ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✅ External Packages (Safe to distribute):${NC}"
    
    if [[ -f "dist/patchmaster-${VERSION}.tar.gz" ]]; then
        local size=$(du -h "dist/patchmaster-${VERSION}.tar.gz" | cut -f1)
        echo -e "   📦 Customer: dist/patchmaster-${VERSION}.tar.gz (${size})"
    fi
    
    if [[ -f "vendor/dist/patchmaster-vendor-${VERSION}.tar.gz" ]]; then
        local size=$(du -h "vendor/dist/patchmaster-vendor-${VERSION}.tar.gz" | cut -f1)
        echo -e "   📦 Vendor:   vendor/dist/patchmaster-vendor-${VERSION}.tar.gz (${size})"
    fi
    
    echo ""
    echo -e "${RED}❌ Internal Package (NEVER distribute):${NC}"
    
    if [[ -f "dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz" ]]; then
        local size=$(du -h "dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz" | cut -f1)
        echo -e "   📦 Developer: dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz (${size})"
    fi
    
    echo ""
}

show_external_summary() {
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║              EXTERNAL PACKAGES SUMMARY                     ║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✅ Ready to distribute:${NC}"
    
    if [[ -f "dist/patchmaster-${VERSION}.tar.gz" ]]; then
        local size=$(du -h "dist/patchmaster-${VERSION}.tar.gz" | cut -f1)
        echo -e "   📦 Customer: dist/patchmaster-${VERSION}.tar.gz (${size})"
    fi
    
    if [[ -f "vendor/dist/patchmaster-vendor-${VERSION}.tar.gz" ]]; then
        local size=$(du -h "vendor/dist/patchmaster-vendor-${VERSION}.tar.gz" | cut -f1)
        echo -e "   📦 Vendor:   vendor/dist/patchmaster-vendor-${VERSION}.tar.gz (${size})"
    fi
    
    echo ""
}

# Main script
show_banner

# Check if version is provided as argument
if [[ $# -eq 0 ]]; then
    log "No version specified, using default: ${VERSION}"
    echo ""
fi

# Interactive mode
while true; do
    show_menu
    read -p "Enter your choice [0-5]: " choice
    echo ""
    
    case $choice in
        1)
            build_customer_package
            echo ""
            read -p "Press Enter to continue..."
            ;;
        2)
            build_vendor_package
            echo ""
            read -p "Press Enter to continue..."
            ;;
        3)
            warn "⚠️  You are about to build the Developer Kit"
            warn "⚠️  This package contains source code and internal documentation"
            read -p "Are you sure? (yes/no): " confirm
            if [[ "$confirm" == "yes" ]]; then
                build_developer_kit
            else
                warn "Developer kit build cancelled"
            fi
            echo ""
            read -p "Press Enter to continue..."
            ;;
        4)
            build_all
            echo ""
            read -p "Press Enter to continue..."
            ;;
        5)
            build_external_only
            echo ""
            read -p "Press Enter to continue..."
            ;;
        0)
            log "Exiting..."
            exit 0
            ;;
        *)
            error "Invalid choice. Please select 0-5."
            sleep 2
            ;;
    esac
    
    clear
    show_banner
done
