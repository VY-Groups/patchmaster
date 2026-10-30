#!/bin/bash
###############################################################################
# Package Verification Script
# Shows what's included in each package type
###############################################################################

VERSION="${1:-2.0.0}"

echo "═══════════════════════════════════════════════════════════"
echo "  Patch-SecOps Solution Package Verification"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Customer Package
if [[ -f "dist/patchmaster-${VERSION}.tar.gz" ]]; then
    echo "📦 CUSTOMER PACKAGE: dist/patchmaster-${VERSION}.tar.gz"
    echo "   Size: $(du -h dist/patchmaster-${VERSION}.tar.gz | cut -f1)"
    echo ""
    echo "   Contents:"
    echo "   ✓ Backend API (complete)"
    echo "   ✓ Frontend Web UI (complete)"
    echo "   ✓ Pre-built agent binaries:"
    tar -tzf "dist/patchmaster-${VERSION}.tar.gz" | grep 'backend/static/agent' | sed 's/^/     - /'
    echo "   ✓ Vendor portal (for license management)"
    echo "   ✓ Python wheels: $(tar -tzf dist/patchmaster-${VERSION}.tar.gz | grep '\.whl$' | wc -l) files"
    echo "   ✓ Documentation"
    echo "   ✓ Deployment scripts"
    echo ""
    echo "   Agent files (minimal):"
    tar -tzf "dist/patchmaster-${VERSION}.tar.gz" | grep '^./agent/' | sed 's/^/     - /'
    echo ""
else
    echo "❌ Customer package not found"
    echo ""
fi

# Vendor Package
if [[ -f "vendor/dist/patchmaster-vendor-${VERSION}.tar.gz" ]]; then
    echo "📦 VENDOR PACKAGE: vendor/dist/patchmaster-vendor-${VERSION}.tar.gz"
    echo "   Size: $(du -h vendor/dist/patchmaster-vendor-${VERSION}.tar.gz | cut -f1)"
    echo ""
    echo "   Contents (vendor portal only):"
    tar -tzf "vendor/dist/patchmaster-vendor-${VERSION}.tar.gz" | grep -v '/$' | sed 's/^/     - /'
    echo ""
else
    echo "❌ Vendor package not found"
    echo ""
fi

# Developer Kit
if [[ -f "dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz" ]]; then
    echo "📦 DEVELOPER KIT: dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz"
    echo "   Size: $(du -h dist/developer/patchmaster-developer-kit-${VERSION}.tar.gz | cut -f1)"
    echo ""
    echo "   ⚠️  INTERNAL USE ONLY - Contains complete source code"
    echo ""
else
    echo "ℹ️  Developer kit not built"
    echo ""
fi

echo "═══════════════════════════════════════════════════════════"
