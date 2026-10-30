# Patch-SecOps Solution Build Process

## Overview
This document explains how to build Patch-SecOps Solution from source, including all agent packages and the final product tarball.

**Last Updated**: April 12, 2026  
**Version**: 2.0.0

> **Verification note (2026-10-25)** — the core product-package path was
> re-verified end-to-end in a clean `node:22` container: `npm ci` in
> `frontend/`, then `bash packaging/build-package.sh` → exit 0, producing
> `dist/patchmaster-2.0.17.tar.gz` (12 MB) + `.sha256` + `BUILD-MANIFEST.txt`.
> Current product version is **2.0.17**; examples below still show `2.0.6`
> from the April release cycle — pass `--version` (or the `VERSION` env var)
> to build a specific version. That build is now a blocking CI job
> (`package-build` in `.github/workflows/ci.yml`). The multi-platform agent
> build scripts (`scripts/build-all-agents.sh` etc.) were NOT re-verified in
> this cycle.

---

## Quick Start

### Build Everything (Recommended)
```bash
# Build all agents + frontend + product package
bash scripts/build-complete-release.sh 2.0.6

# Skip frontend rebuild (faster for agent-only changes)
bash scripts/build-complete-release.sh 2.0.6 skip
```

### Build Only Agents
```bash
# Build all platform agent packages
bash scripts/build-all-agents.sh 2.0.6
```

### Build Individual Components
```bash
# Frontend only
cd frontend && npm run build

# Specific agent
bash agent/build-freebsd.sh 2.0.6

# Product package only
bash packaging/build-package.sh --version 2.0.6
```

---

## Build Scripts

### 1. `scripts/build-complete-release.sh`
**Purpose**: Complete release builder - builds everything

**What it does**:
1. ✅ Builds React frontend (`frontend/dist/`)
2. ✅ Downloads Python dependencies to `vendor/wheels/`
3. ✅ Builds all agent packages (DEB, RPM, Arch, Alpine, FreeBSD, Windows)
4. ✅ Creates product tarball (`dist/patchmaster-VERSION.tar.gz`)
5. ✅ Generates SHA256 checksums
6. ✅ Shows build summary

**Usage**:
```bash
# Full build
bash scripts/build-complete-release.sh 2.0.6

# Skip frontend (use existing build)
bash scripts/build-complete-release.sh 2.0.6 skip
```

**Output**:
- `dist/patchmaster-2.0.6.tar.gz` - Product package (~119 MB)
- `dist/patchmaster-2.0.6.tar.gz.sha256` - Checksum file
- `backend/static/agent-latest.*` - All agent packages

### 2. `scripts/build-all-agents.sh`
**Purpose**: Build all platform agent packages

**What it does**:
1. ✅ Checks/creates `vendor/wheels/` directory
2. ✅ Downloads Python dependencies if missing
3. ✅ Builds Debian package (`.deb`)
4. ✅ Builds RPM package (`.rpm`)
5. ✅ Builds Arch package (`.pkg.tar.zst`)
6. ✅ Builds Alpine package (`.apk`)
7. ✅ Builds FreeBSD package (`.txz`) - **bundled version**
8. ✅ Builds Windows package (`.zip`)
9. ✅ Copies all to `backend/static/`

**Usage**:
```bash
bash scripts/build-all-agents.sh 2.0.6
```

**Output**:
- `backend/static/agent-latest.deb` (3.0 MB)
- `backend/static/agent-latest.rpm` (1.3 MB)
- `backend/static/agent-latest.pkg.tar.zst` (3.1 MB)
- `backend/static/agent-latest.apk` (4.5 MB)
- `backend/static/agent-latest.txz` (2.5 MB) - **Bundled!**
- `backend/static/agent-windows.zip` (48 MB)

---

## FreeBSD Agent: Two Versions

### Bundled Version (Default - 2.5 MB)
**Script**: `agent/build-freebsd.sh`  
**Size**: 2.5 MB  
**Type**: Self-contained with Python virtual environment

**Includes**:
- ✅ Agent Python scripts
- ✅ Python virtual environment
- ✅ All Python dependencies (Flask, requests, psutil, etc.)
- ✅ FreeBSD rc.d service files
- ✅ Configuration templates

**Installation**:
```bash
# One command - no manual setup!
sudo pkg add patchmaster-agent-2.0.6.txz
service patch_agent status
```

**Use when**:
- ✅ Production deployment
- ✅ Air-gapped environment
- ✅ Consistent with other platforms
- ✅ No manual dependency installation

### Portable Version (Alternative - 31 KB)
**Script**: `agent/build-freebsd-portable.sh`  
**Size**: 31 KB  
**Type**: Scripts only, requires manual Python setup

**Includes**:
- ✅ Agent Python scripts
- ✅ FreeBSD rc.d service files
- ✅ Configuration templates
- ❌ No Python dependencies

**Installation**:
```bash
# Install package
sudo pkg add patchmaster-agent-2.0.6-portable.txz

# Manual setup required
sudo pkg install python3 py39-pip
cd /usr/local/patch-agent
sudo pip install -r requirements.txt

# Enable services
sudo sysrc patch_agent_enable="YES"
sudo service patch_agent start
```

**Use when**:
- ✅ Development/testing
- ✅ Minimal footprint required
- ✅ Python already installed
- ✅ Faster iteration

---

## Prerequisites

### System Requirements
- **OS**: Linux (Ubuntu 20.04+, WSL2, or native Linux)
- **Python**: 3.8 or higher
- **Node.js**: 16.x or higher
- **npm**: 8.x or higher
- **Disk Space**: 2 GB free

### Required Tools
```bash
# Ubuntu/Debian
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    nodejs npm \
    tar gzip xz-utils \
    build-essential

# Install Python packages
pip3 install --upgrade pip wheel setuptools
```

---

## Build Process Details

### Step 1: Prepare Vendor Wheels
The `vendor/wheels/` directory contains all Python dependencies as wheel files for air-gapped builds.

**Create vendor/wheels**:
```bash
mkdir -p vendor/wheels
cd vendor/wheels
pip3 download -r ../../agent/requirements.txt --dest .
```

**Contents** (17 wheel files, 2.3 MB):
- flask-3.1.3-py3-none-any.whl
- prometheus_client-0.25.0-py3-none-any.whl
- psutil-7.2.2-cp36-abi3-manylinux2010_x86_64.whl
- requests-2.33.1-py3-none-any.whl
- pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.whl
- + 12 more dependencies

### Step 2: Build Frontend
```bash
cd frontend
npm install
npm run build
```

**Output**: `frontend/dist/` (React production build)

### Step 3: Build Agent Packages

Each platform has its own build script:

| Platform | Script | Output | Size |
|----------|--------|--------|------|
| Debian/Ubuntu | `agent/build-deb.sh` | `.deb` | 3.0 MB |
| RHEL/RPM | `agent/build-rpm.sh` | `.rpm` | 1.3 MB |
| Arch Linux | `agent/build-arch.sh` | `.pkg.tar.zst` | 3.1 MB |
| Alpine Linux | `agent/build-apk.sh` | `.apk` | 4.5 MB |
| FreeBSD | `agent/build-freebsd.sh` | `.txz` | 2.5 MB |
| Windows | `agent/build_agent_artifacts.py` | `.zip` | 48 MB |

**All scripts**:
1. Create build directory
2. Copy agent files
3. Create Python virtual environment
4. Install dependencies from `vendor/wheels/`
5. Create service files
6. Package everything
7. Copy to `backend/static/`

### Step 4: Build Product Package
```bash
bash packaging/build-package.sh --version 2.0.6
```

**What it includes**:
- ✅ Backend Python application
- ✅ Frontend React build
- ✅ All agent packages
- ✅ Database migrations
- ✅ Static files
- ✅ Documentation
- ✅ Installation scripts

**Output**: `dist/patchmaster-2.0.6.tar.gz` (~119 MB)

---

## Package Versions Explained

You may see multiple package versions in `dist/`:

| Package | FreeBSD Agent | Size | Status |
|---------|--------------|------|--------|
| `patchmaster-2.0.0.tar.gz` | Portable (31 KB) | 114 MB | ❌ Old |
| `patchmaster-2.0.6.tar.gz` | Bundled (2.5 MB) | 119 MB | ✅ Current |

**Why the difference?**
- **2.0.0**: Built with `build-freebsd-portable.sh` (31 KB agent)
- **2.0.6**: Built with `build-freebsd.sh` (2.5 MB bundled agent)

**Which to use?**
- ✅ **Use 2.0.6** - Bundled agent, consistent with other platforms
- ❌ **Avoid 2.0.0** - Portable agent, requires manual setup

**Clean up old versions**:
```bash
cd dist
rm -f patchmaster-2.0.0.tar.gz*
ls -lh  # Should only show 2.0.6
```

---

## Troubleshooting

### Issue: "vendor/wheels directory is empty"
**Solution**:
```bash
mkdir -p vendor/wheels
cd vendor/wheels
pip3 download --timeout 300 -r ../../agent/requirements.txt --dest .
```

### Issue: "Frontend build failed"
**Solution**:
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

### Issue: "FreeBSD build failed - no wheels"
**Solution**:
```bash
# Ensure vendor/wheels exists
ls -la vendor/wheels/

# If empty, download dependencies
bash scripts/build-all-agents.sh 2.0.6
```

### Issue: "Multiple package versions in dist/"
**Solution**:
```bash
# Keep only the latest
cd dist
ls -lt patchmaster-*.tar.gz | tail -n +2 | awk '{print $9}' | xargs rm -f
```

---

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Build Patch-SecOps Solution Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '16'
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Build Release
        run: |
          VERSION=${GITHUB_REF#refs/tags/v}
          bash scripts/build-complete-release.sh $VERSION
      
      - name: Upload Artifacts
        uses: actions/upload-artifact@v3
        with:
          name: patchmaster-release
          path: dist/patchmaster-*.tar.gz*
```

---

## Best Practices

### 1. Version Numbering
Use semantic versioning: `MAJOR.MINOR.PATCH`
- **MAJOR**: Breaking changes
- **MINOR**: New features
- **PATCH**: Bug fixes

### 2. Clean Builds
```bash
# Clean everything before building
rm -rf frontend/dist
rm -rf agent/dist
rm -rf dist/patchmaster-*.tar.gz
rm -rf backend/static/agent-*

# Then build
bash scripts/build-complete-release.sh 2.0.6
```

### 3. Verify Builds
```bash
# Check package contents
tar -tzf dist/patchmaster-2.0.6.tar.gz | head -20

# Verify FreeBSD agent is bundled
tar -tzf backend/static/agent-latest.txz | grep venv

# Check sizes
ls -lh backend/static/agent-*
```

### 4. Test Before Release
```bash
# Extract and test
tar -xzf dist/patchmaster-2.0.6.tar.gz
cd patchmaster
bash install.sh

# Verify agents
curl http://localhost:8000/static/agent-latest.txz -I
```

---

## Summary

**To build a complete Patch-SecOps Solution release**:

```bash
# One command builds everything
bash scripts/build-complete-release.sh 2.0.6
```

**Output**:
- ✅ Product package: `dist/patchmaster-2.0.6.tar.gz` (119 MB)
- ✅ All agent packages in `backend/static/`
- ✅ FreeBSD agent is bundled (2.5 MB) with Python dependencies
- ✅ Ready for production deployment

**No manual steps required!**

---

**Document Version**: 1.0  
**Generated**: April 12, 2026  
**Build Scripts**: v2.0.0
