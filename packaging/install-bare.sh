#!/usr/bin/env bash
###############################################################################
#  PatchMaster by VYGROUP - Bare-Metal Installer
#  Installs PatchMaster directly on a Linux server (no Docker required).
#
#  Supports: Ubuntu 20.04+, Debian 11+, RHEL 8+/CentOS Stream 8+
#  Usage:    sudo ./install-bare.sh [--env /path/to/.env]
###############################################################################
set -euo pipefail

PM_VERSION="2.0.0"
INSTALL_DIR="/opt/patchmaster"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$SCRIPT_DIR/docker-compose.yml" ]]; then
    PROJECT_ROOT="$SCRIPT_DIR"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
PACKAGED_AUTHORITY_ENV="$PROJECT_ROOT/patchmaster-license-authority.env"
PACKAGED_PUBLIC_AUTHORITY_ENV="$PROJECT_ROOT/patchmaster-license-public.env"
INPUT_LICENSE_SIGN_KEY="${LICENSE_SIGN_KEY-}"
INPUT_LICENSE_VERIFY_PUBLIC_KEY="${LICENSE_VERIFY_PUBLIC_KEY-}"
INPUT_LICENSE_DECRYPT_PRIVATE_KEY="${LICENSE_DECRYPT_PRIVATE_KEY-}"
INPUT_LICENSE_ENCRYPT_PUBLIC_KEY="${LICENSE_ENCRYPT_PUBLIC_KEY-}"
ENV_FILE=""
DISTRO=""
PKG_MGR=""

# Unprivileged service user
SVC_USER="patchmaster"
SVC_GROUP="patchmaster"

# Install Prometheus + Grafana alongside PatchMaster by default.
INSTALL_MONITORING=true

# Optional: SSL certificate paths
SSL_CERT=""
SSL_KEY=""

# ?? Colors ??
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
run_with_progress() {
    local label="$1"
    shift
    local log_file
    log_file="$(mktemp)"
    ("$@" >"$log_file" 2>&1) &
    local cmd_pid=$!
    local started_at
    started_at="$(date +%s)"
    local last_line=""
    while kill -0 "$cmd_pid" 2>/dev/null; do
        sleep 5
        local now elapsed
        now="$(date +%s)"
        elapsed=$((now - started_at))
        last_line="$(tail -n 1 "$log_file" 2>/dev/null || true)"
        if [[ -n "$last_line" ]]; then
            log "  ${label} (elapsed ${elapsed}s) — ${last_line}"
        else
            log "  ${label} (elapsed ${elapsed}s)"
        fi
    done
    wait "$cmd_pid"
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        err "  ${label} failed (exit ${rc})"
        tail -n 40 "$log_file" >&2 || true
        rm -f "$log_file"
        return $rc
    fi
    rm -f "$log_file"
    return 0
}
banner() {
    echo -e "${BLUE}"
    cat <<'ART'
  ____       _       _   __  __
 |  _ \ __ _| |_ ___| | |  \/  | __ _ ___| |_ ___ _ __
 | |_) / _` | __/ __| |_| |\/| |/ _` / __| __/ _ \ '__|
 |  __/ (_| | || (__| '_| |  | | (_| \__ \ ||  __/ |
 |_|   \__,_|\__\___|_| |_|  |_|\__,_|___/\__\___|_|
ART
    echo -e "${NC}"
    echo "    PatchMaster by VYGROUP  v${PM_VERSION}"
    echo "        Bare-Metal Installer"
    echo
}

usage() {
    echo "Usage: sudo $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --env FILE           Path to environment config file"
    echo "  --install-dir DIR    Installation directory (default: /opt/patchmaster)"
    echo "  --with-monitoring    Install Prometheus + Grafana (default)"
    echo "  --without-monitoring Skip Prometheus + Grafana installation"
    echo "  --ssl-cert FILE      Path to SSL fullchain.pem (enables HTTPS)"
    echo "  --ssl-key FILE       Path to SSL privkey.pem   (requires --ssl-cert)"
    echo "  -h, --help           Show this help"
    exit 0
}

# Port helpers
port_in_use() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
    else
        return 1
    fi
}

choose_port() {
    local desired="$1"; shift
    local candidate="$desired"
    if port_in_use "$desired"; then
        warn "  Port $desired is in use; selecting a free port automatically..."
        for p in "$@"; do
            if ! port_in_use "$p"; then
                candidate="$p"
                break
            fi
        done
    fi
    echo "$candidate"
}

node_major_version() {
    if command -v node >/dev/null 2>&1; then
        node -v | tr -d 'v' | cut -d. -f1
    else
        echo 0
    fi
}

ensure_node_runtime() {
    local reason="$1"
    local node_major
    node_major="$(node_major_version)"

    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1 || [[ "$node_major" -lt 18 ]]; then
        log "  Installing Node.js (${reason})..."
        if [[ "$DISTRO" == "debian" ]]; then
            curl -fsSL https://deb.nodesource.com/setup_20.x | bash - || true
            apt-get install -y -qq nodejs > /dev/null 2>&1 || true
            if ! command -v npm >/dev/null 2>&1; then
                apt-get install -y -qq npm > /dev/null 2>&1 || true
            fi
        else
            curl -fsSL https://rpm.nodesource.com/setup_20.x | bash - || true
            $PKG_MGR install -y -q nodejs > /dev/null 2>&1 || true
            if ! command -v npm >/dev/null 2>&1; then
                $PKG_MGR install -y -q npm > /dev/null 2>&1 || true
            fi
        fi
    fi

    command -v node >/dev/null 2>&1 || {
        err "Node.js install failed (${reason}). Install Node.js 18+ and re-run."
        exit 1
    }
    command -v npm >/dev/null 2>&1 || {
        err "npm install failed (${reason}). Install npm and re-run."
        exit 1
    }

    npm install -g npm@latest > /dev/null 2>&1 || true
}

install_frontend_node_modules() {
    if [[ "${FRONTEND_NODE_MODULES_READY:-0}" == "1" ]]; then
        return 0
    fi

    if [[ -f package-lock.json ]]; then
        run_with_progress "npm ci" npm ci || {
            err "  npm ci failed while preparing frontend dependencies."
            exit 1
        }
    else
        run_with_progress "npm install" npm install || {
            err "  npm install failed while preparing frontend dependencies."
            exit 1
        }
    fi

    FRONTEND_NODE_MODULES_READY=1
}

# ?? Parse args ??
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)             ENV_FILE="$2"; shift 2 ;;
        --install-dir)     INSTALL_DIR="$2"; shift 2 ;;
        --with-monitoring)  INSTALL_MONITORING=true; shift ;;
        --without-monitoring) INSTALL_MONITORING=false; shift ;;
        --ssl-cert)        SSL_CERT="$2"; shift 2 ;;
        --ssl-key)         SSL_KEY="$2"; shift 2 ;;
        -h|--help)         usage ;;
        *)                 err "Unknown option: $1"; usage ;;
    esac
done

# Validate SSL arguments
if [[ -n "$SSL_CERT" && -z "$SSL_KEY" ]]; then
    err "--ssl-cert requires --ssl-key"; exit 1
fi
if [[ -n "$SSL_KEY" && -z "$SSL_CERT" ]]; then
    err "--ssl-key requires --ssl-cert"; exit 1
fi
if [[ -n "$SSL_CERT" ]]; then
    [[ -f "$SSL_CERT" ]] || { err "SSL cert not found: $SSL_CERT"; exit 1; }
    [[ -f "$SSL_KEY" ]]  || { err "SSL key not found: $SSL_KEY"; exit 1; }
fi

# ?? Root check ??
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo)."
    exit 1
fi

# ?? Upgrade & Rollback logic ??
IS_UPGRADE=false
BACKUP_DIR="/var/backups/patchmaster-$(date +%Y%m%d%H%M%S)"
REUSE_EXISTING_SSL=false

if [[ -d "$INSTALL_DIR/backend" ]]; then
    IS_UPGRADE=true
    log "Existing installation detected. Preparing for secure upgrade..."
fi

perform_backup() {
    log "Creating system backup at $BACKUP_DIR..."
    mkdir -p "$BACKUP_DIR"
    
    # 1. Backup DB
    if systemctl is-active --quiet postgresql; then
        log "  Backing up PostgreSQL database..."
        # Extract DB name from .env if possible
        DB_NAME="patchmaster"
        if [[ -f "$INSTALL_DIR/.env" ]]; then
             DB_NAME=$(grep POSTGRES_DB "$INSTALL_DIR/.env" | cut -d'=' -f2 || echo "patchmaster")
        fi
        su - postgres -c "pg_dump $DB_NAME" > "$BACKUP_DIR/db_backup.sql" || warn "DB backup failed!"
    fi

    # 2. Backup App Files
    log "  Backing up application files..."
    cp -rp "$INSTALL_DIR" "$BACKUP_DIR/files"
}

stop_existing_services() {
    log "Stopping existing PatchMaster services before upgrade sync..."
    systemctl stop patchmaster-backend 2>/dev/null || true
    systemctl stop nginx 2>/dev/null || true
    systemctl stop prometheus 2>/dev/null || true
    systemctl stop grafana-server 2>/dev/null || true
    systemctl reset-failed grafana-server 2>/dev/null || true
}

sync_install_dir() {
    local src="$1"
    local dst="$2"
    shift 2
    mkdir -p "$dst"
    rsync -a --delete "$@" "$src"/ "$dst"/
}

sync_install_file() {
    local src="$1"
    local dst="$2"
    if [[ -f "$src" ]]; then
        install -m 0644 "$src" "$dst"
    fi
}

load_existing_backend_default() {
    local key="$1"
    local file="$INSTALL_DIR/backend/.env"
    local current="${!key-}"
    local value=""
    if [[ -n "$current" || ! -f "$file" ]]; then
        return 0
    fi
    value="$(grep -E "^${key}=" "$file" | tail -n 1 | cut -d'=' -f2- || true)"
    if [[ -n "$value" ]]; then
        printf -v "$key" '%s' "$value"
    fi
}

rollback() {
    err "Update failed! Rolling back to previous version..."
    if [[ -d "$BACKUP_DIR/files" ]]; then
        # Stop services
        systemctl stop patchmaster-backend nginx prometheus grafana-server || true
        
        # Restore files
        rm -rf "$INSTALL_DIR"
        cp -rp "$BACKUP_DIR/files" "$INSTALL_DIR"
        
        # Restore DB
        if [[ -f "$BACKUP_DIR/db_backup.sql" ]]; then
            log "  Restoring database..."
            DB_NAME=$(grep POSTGRES_DB "$INSTALL_DIR/.env" | cut -d'=' -f2 || echo "patchmaster")
            su - postgres -c "psql $DB_NAME < $BACKUP_DIR/db_backup.sql" || warn "DB restore failed!"
        fi
        
        # Restart services
        systemctl daemon-reload
        systemctl start patchmaster-backend nginx || true
        systemctl start prometheus grafana-server || true
        log "Rollback complete. The previous version has been restored."
    else
        err "No backup found! Cannot rollback automatically."
    fi
    exit 1
}

# Trap errors during upgrade to trigger rollback
if [[ "$IS_UPGRADE" == "true" ]]; then
    perform_backup
    trap rollback ERR
fi

banner

# Determine total steps based on options
if [[ "$INSTALL_MONITORING" == "true" ]]; then
    TOTAL_STEPS=8
else
    TOTAL_STEPS=7
fi

###############################################################################
# Helper: Detect distro
###############################################################################
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        case "$ID" in
            ubuntu|debian|linuxmint|pop) DISTRO="debian"; PKG_MGR="apt" ;;
            rhel|centos|rocky|alma|fedora|ol) DISTRO="rhel"; PKG_MGR="dnf" ;;
            *)
                if command -v apt-get &>/dev/null; then
                    DISTRO="debian"; PKG_MGR="apt"
                elif command -v dnf &>/dev/null; then
                    DISTRO="rhel"; PKG_MGR="dnf"
                elif command -v yum &>/dev/null; then
                    DISTRO="rhel"; PKG_MGR="yum"
                else
                    err "Unsupported distribution: $ID"
                    exit 1
                fi
                ;;
        esac
    else
        err "Cannot detect distribution (missing /etc/os-release)."
        exit 1
    fi
    log "  Detected: $ID ($DISTRO family), package manager: $PKG_MGR"
}

###############################################################################
# Step 1: Check prerequisites & detect OS
###############################################################################
log "Step 1/${TOTAL_STEPS}: Detecting operating system..."
detect_distro

# Check Python version
PY_VER=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
log "  Python version: $PY_VER"

# Simple numeric comparison without bc (which might not be installed)
# Extract major and minor
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 8 ]]; then
    err "PatchMaster requires Python 3.8 or higher. Found: $PY_VER"
    exit 1
fi

###############################################################################
# Step 2: Install system packages
###############################################################################
log "Step 2/${TOTAL_STEPS}: Installing system packages..."

if [[ "$DISTRO" == "debian" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    export NEEDRESTART_MODE=a

    # Clean up old NodeSource entries (prevents apt update failures from stale URLs)
    rm -f /etc/apt/sources.list.d/nodesource.list /etc/apt/sources.list.d/nodesource*.list 2>/dev/null || true

    # Clean up old PostgreSQL repo entries (prevents apt update warnings/errors from stale URLs and legacy keys)
    rm -f /etc/apt/sources.list.d/pgdg.list /etc/apt/sources.list.d/pgdg*.list /etc/apt/sources.list.d/postgresql*.list 2>/dev/null || true
    rm -f /etc/apt/keyrings/pgdg.gpg 2>/dev/null || true
    if [[ -f /etc/apt/sources.list ]]; then
        sed -i '/apt\.postgresql\.org\/pub\/repos\/apt/d' /etc/apt/sources.list 2>/dev/null || true
    fi
    if command -v gpg >/dev/null 2>&1 && [[ -f /etc/apt/trusted.gpg ]]; then
        gpg --batch --yes --no-default-keyring --keyring /etc/apt/trusted.gpg --delete-key ACCC4CF8 >/dev/null 2>&1 || true
    fi
    
    # Robust apt update with retry logic and mirror sync handling
    log "  Updating package lists..."
    apt_update_with_retry() {
        local max_attempts=3
        local attempt=1
        
        while [ $attempt -le $max_attempts ]; do
            log "  Attempt $attempt/$max_attempts..."
            
            # Clean apt cache to avoid stale data
            apt-get clean 2>/dev/null || true
            rm -rf /var/lib/apt/lists/* 2>/dev/null || true
            
            # Try update with retries and timeouts
            if apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update 2>&1 | grep -v "File has unexpected size"; then
                log "  Package lists updated successfully"
                return 0
            fi
            
            if [ $attempt -lt $max_attempts ]; then
                warn "  apt update had issues, waiting 10 seconds for mirror sync..."
                sleep 10
            fi
            
            attempt=$((attempt + 1))
        done
        
        warn "  apt update had issues but continuing with cached packages..."
        return 0
    }
    
    apt_update_with_retry
    apt-get install -y -qq gnupg2 wget lsb-release ca-certificates 2>/dev/null || true

    # Configure PostgreSQL repository (PGDG) if reachable; otherwise fall back to distro packages
    log "  Configuring PostgreSQL repository..."
    CODENAME="$(lsb_release -cs 2>/dev/null || echo jammy)"
    PGDG_LIST="/etc/apt/sources.list.d/pgdg.list"
    PGDG_KEYRING="/etc/apt/keyrings/pgdg.gpg"
    mkdir -p /etc/apt/keyrings

    # Skip PGDG setup entirely if PostgreSQL 17 is already installed
    _pg17_installed() {
        command -v psql >/dev/null 2>&1 && psql --version 2>/dev/null | grep -q " 17\."
    }

    fetch_pgdg_key() {
        local tmp_asc="/tmp/pgdg-key-$$.asc"
        local ok=1
        local key_urls=(
            "https://www.postgresql.org/media/keys/ACCC4CF8.asc"
            "https://apt.postgresql.org/pub/repos/apt/ACCC4CF8.asc"
        )
        rm -f "$tmp_asc" "$PGDG_KEYRING" 2>/dev/null || true
        for key_url in "${key_urls[@]}"; do
            if curl --connect-timeout 5 --max-time 20 --retry 2 --retry-delay 1 -fsSL "$key_url" -o "$tmp_asc"; then
                if grep -q "BEGIN PGP PUBLIC KEY BLOCK" "$tmp_asc"; then
                    if gpg --dearmor -o "$PGDG_KEYRING" "$tmp_asc" >/dev/null 2>&1; then
                        ok=0
                        break
                    fi
                fi
            fi
        done
        rm -f "$tmp_asc" 2>/dev/null || true
        return $ok
    }

    if _pg17_installed; then
        log "  PostgreSQL 17 already installed — skipping PGDG repository setup"
    elif [[ "${SKIP_PGDG:-0}" == "1" ]]; then
        warn "  SKIP_PGDG=1 set; using distro PostgreSQL packages"
        rm -f "$PGDG_LIST" "$PGDG_KEYRING" 2>/dev/null || true
    else
        if curl --connect-timeout 5 --max-time 12 -fsSI "https://apt.postgresql.org/pub/repos/apt/dists/${CODENAME}-pgdg/InRelease" >/dev/null 2>&1; then
            if fetch_pgdg_key; then
                echo "deb [signed-by=${PGDG_KEYRING}] https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" > "$PGDG_LIST"
                apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=10 -o Acquire::https::Timeout=10 update -qq 2>/dev/null || {
                    warn "  PGDG apt update failed; falling back to distro PostgreSQL packages"
                    rm -f "$PGDG_LIST" "$PGDG_KEYRING" 2>/dev/null || true
                    apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=10 -o Acquire::https::Timeout=10 update -qq 2>/dev/null || true
                }
            else
                warn "  PGDG key download failed; using distro PostgreSQL packages"
                rm -f "$PGDG_LIST" "$PGDG_KEYRING" 2>/dev/null || true
            fi
        else
            warn "  PGDG repo not reachable for ${CODENAME}; using distro PostgreSQL packages"
            rm -f "$PGDG_LIST" 2>/dev/null || true
        fi
    fi

    log "  Installing base packages (python3, nginx, curl, gcc, etc.)..."
    apt-get install -y -qq \
        python3 python3-venv python3-pip python3-dev \
        nginx curl gcc make rsync zip unzip openssl samba \
        > /dev/null 2>&1
    log "  Base packages installed"

    log "  Installing PostgreSQL..."
    # Prefer PostgreSQL 17 if available, otherwise install distro default
    if apt-cache show postgresql-17 >/dev/null 2>&1; then
        apt-get install -y -qq postgresql-17 postgresql-contrib-17 libpq-dev > /dev/null 2>&1 || true
    fi
    if ! command -v psql >/dev/null 2>&1; then
        apt-get install -y -qq postgresql postgresql-contrib libpq-dev > /dev/null 2>&1
    fi
    log "  PostgreSQL installed"

    if [[ -f "$PROJECT_ROOT/frontend/dist/index.html" ]]; then
        if [[ "${SKIP_FRONTEND_E2E:-0}" == "1" ]]; then
            log "  Skipping Node.js install because pre-built frontend is present and SKIP_FRONTEND_E2E=1"
        else
            ensure_node_runtime "required for Testing Center browser smoke"
        fi
    else
        ensure_node_runtime "required to build the frontend and enable browser smoke"
    fi

elif [[ "$DISTRO" == "rhel" ]]; then
    $PKG_MGR install -y -q \
        python3 python3-devel python3-pip \
        postgresql-server postgresql-contrib libpq-devel \
        nginx curl gcc make rsync zip unzip openssl samba \
        > /dev/null 2>&1

    if [[ -f "$PROJECT_ROOT/frontend/dist/index.html" ]]; then
        if [[ "${SKIP_FRONTEND_E2E:-0}" == "1" ]]; then
            log "  Skipping Node.js install because pre-built frontend is present and SKIP_FRONTEND_E2E=1"
        else
            ensure_node_runtime "required for Testing Center browser smoke"
        fi
    else
        ensure_node_runtime "required to build the frontend and enable browser smoke"
    fi

    # Initialize PostgreSQL on RHEL if needed
    if [[ ! -f /var/lib/pgsql/data/PG_VERSION ]]; then
        postgresql-setup --initdb 2>/dev/null || /usr/bin/postgresql-setup initdb 2>/dev/null || true
    fi
fi

log "  Python $(python3 --version | awk '{print $2}')"
log "  Node $(node --version)"
log "  PostgreSQL $(psql --version | awk '{print $3}')"
log "  Nginx $(nginx -v 2>&1 | awk -F/ '{print $2}')"

if [[ "$IS_UPGRADE" == "true" ]]; then
    stop_existing_services
fi

###############################################################################
# Step 3: Create service user & install directory
###############################################################################
log "Step 3/${TOTAL_STEPS}: Setting up user and directories..."

# Create system user if not exists
if ! id "$SVC_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$SVC_USER"
    log "  Created system user: $SVC_USER"
fi

# Create directories
mkdir -p "$INSTALL_DIR"/{backend,frontend,agent,monitoring,scripts,certs,logs}

# Copy application files

if [[ -f "$PROJECT_ROOT/docker-compose.yml" ]]; then
    sync_install_dir "$PROJECT_ROOT/backend" "$INSTALL_DIR/backend" --exclude 'venv/' --exclude '.env'
    sync_install_dir "$PROJECT_ROOT/frontend" "$INSTALL_DIR/frontend" --exclude 'node_modules/' --exclude '.playwright-browsers/'
    sync_install_dir "$PROJECT_ROOT/agent" "$INSTALL_DIR/agent"
    if [[ -d "$PROJECT_ROOT/monitoring" ]]; then
        sync_install_dir "$PROJECT_ROOT/monitoring" "$INSTALL_DIR/monitoring"
    fi
    if [[ -d "$PROJECT_ROOT/scripts" ]]; then
        sync_install_dir "$PROJECT_ROOT/scripts" "$INSTALL_DIR/scripts"
    fi
    if [[ -d "$PROJECT_ROOT/packaging" ]]; then
        sync_install_dir "$PROJECT_ROOT/packaging" "$INSTALL_DIR/packaging"
    fi
    # Copy docs (including monitoring integration guide)
    mkdir -p "$INSTALL_DIR/docs"
    if [[ -d "$PROJECT_ROOT/docs" ]]; then
        sync_install_dir "$PROJECT_ROOT/docs" "$INSTALL_DIR/docs"
    fi
    sync_install_file "$PROJECT_ROOT/README.md" "$INSTALL_DIR/README.md"
    sync_install_file "$PROJECT_ROOT/LICENSE" "$INSTALL_DIR/LICENSE"
else
    err "Cannot find PatchMaster source files at $PROJECT_ROOT"
    exit 1
fi

# Ensure monitoring-ctl.sh is executable and secured (root-owned; backend calls it via sudo)
if [[ -f "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" ]]; then
    chmod 755 "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh"
    chown root:root "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh"

    # Allow PatchMaster service user to run monitoring controller without password
    cat > /etc/sudoers.d/patchmaster-monitoring <<SUDOERS
${SVC_USER} ALL=(root) NOPASSWD: ${INSTALL_DIR}/backend/scripts/monitoring-ctl.sh *
SUDOERS
    chmod 440 /etc/sudoers.d/patchmaster-monitoring
    chown root:root /etc/sudoers.d/patchmaster-monitoring
fi

# Setup CLI tools
if [[ -f "$INSTALL_DIR/backend/scripts/pm-backup-cli.py" ]]; then
    chmod 755 "$INSTALL_DIR/backend/scripts/pm-backup-cli.py"
    ln -sf "$INSTALL_DIR/backend/scripts/pm-backup-cli.py" /usr/local/bin/patchmaster-backup
    log "  Installed CLI: patchmaster-backup"
fi

# Fix Windows line endings on all text files
find "$INSTALL_DIR" -type f \( -name "*.py" -o -name "*.txt" -o -name "*.yml" \
    -o -name "*.yaml" -o -name "*.json" -o -name "*.js" -o -name "*.css" \
    -o -name "*.html" -o -name "*.conf" -o -name "*.sh" -o -name "*.md" \
    -o -name "*.env*" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true

# Validate agent artifacts and build local .deb if the packaged one is a mock placeholder.
# (Some build environments can't produce a real .deb and ship "Mock DEB Content".)
AGENT_DEB="$INSTALL_DIR/backend/static/agent-latest.deb"
if [[ -f "$AGENT_DEB" ]]; then
    if ! dpkg-deb -I "$AGENT_DEB" >/dev/null 2>&1; then
        log "  agent-latest.deb is invalid (likely a placeholder). Building locally..."
        if command -v dpkg-deb >/dev/null 2>&1; then
            bash "$INSTALL_DIR/agent/build-deb.sh" "$AGENT_DEB" || warn "  Failed to build agent-latest.deb locally."
        else
            warn "  dpkg-deb not found; cannot build agent-latest.deb locally."
        fi
    fi
fi

# Normalize static artifact permissions (avoid 777/misleading executable bits)
if [[ -d "$INSTALL_DIR/backend/static" ]]; then
    chmod 755 "$INSTALL_DIR/backend/static/install-agent.sh" 2>/dev/null || true
    chmod 644 "$INSTALL_DIR/backend/static/install-agent.ps1" 2>/dev/null || true
    chmod 644 "$INSTALL_DIR/backend/static/agent-latest.deb" 2>/dev/null || true
    chmod 644 "$INSTALL_DIR/backend/static/agent-latest.rpm" 2>/dev/null || true
    chmod 644 "$INSTALL_DIR/backend/static/agent-windows.zip" 2>/dev/null || true
fi

log "  Installed to: $INSTALL_DIR"

###############################################################################
# Step 4: Load environment configuration
###############################################################################
log "Step 4/${TOTAL_STEPS}: Configuring environment..."

# Determine .env source
if [[ -n "$ENV_FILE" ]]; then
    if [[ -f "$ENV_FILE" ]]; then
        cp "$ENV_FILE" "$INSTALL_DIR/.env"
        log "  Using custom env: $ENV_FILE"
    else
        err "  Custom env file not found: $ENV_FILE"
        err "  Pass a valid --env path or omit --env to use the packaged template."
        exit 1
    fi
elif [[ -f "$INSTALL_DIR/.env" ]]; then
    log "  Using existing .env"
elif [[ -f "$INSTALL_DIR/packaging/env.example" ]]; then
    cp "$INSTALL_DIR/packaging/env.example" "$INSTALL_DIR/.env"
    log "  Created .env from template"
fi

# Source env
if [[ -f "$INSTALL_DIR/.env" ]]; then
    sed -i 's/\r$//' "$INSTALL_DIR/.env"
    set -a
    # shellcheck disable=SC1091
    source "$INSTALL_DIR/.env"
    set +a
fi

is_placeholder_secret() {
    local value="${1:-}"
    [[ -z "$value" ]] && return 0
    case "$value" in
        changeme*|CHANGE-ME*|change-me*|replace-me*|REPLACE-ME*|PatchMaster-License-SignKey-2026-Secure)
            return 0
            ;;
    esac
    return 1
}

SHARED_AUTHORITY_ENV="${PATCHMASTER_SHARED_AUTHORITY_ENV:-/var/lib/patchmaster/shared-license.env}"

read_env_value() {
    local file="$1"
    local key="$2"
    [[ -f "$file" ]] || return 0
    awk -F= -v wanted="$key" '
        /^[[:space:]]*#/ { next }
        $1 ~ ("^[[:space:]]*" wanted "[[:space:]]*$") {
            value = substr($0, index($0, "=") + 1)
            sub(/[[:space:]]*#.*/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            result = value
        }
        END { print result }
    ' "$file" 2>/dev/null
}

upsert_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp
    tmp=$(mktemp)
    mkdir -p "$(dirname "$file")"
    if [[ -f "$file" ]]; then
        awk -v wanted="$key" -v replacement="$value" '
            BEGIN { updated = 0 }
            /^[[:space:]]*#/ { print; next }
            $0 ~ ("^[[:space:]]*" wanted "=") {
                if (!updated) {
                    print wanted "=" replacement
                    updated = 1
                }
                next
            }
            { print }
            END {
                if (!updated) {
                    print wanted "=" replacement
                }
            }
        ' "$file" > "$tmp"
    else
        printf '%s=%s\n' "$key" "$value" > "$tmp"
    fi
    mv "$tmp" "$file"
    chmod 600 "$file" 2>/dev/null || true
}

# If an older install exists, preserve important runtime settings from the
# generated backend env when they are absent from the root .env.
for key in JWT_SECRET LICENSE_VERIFY_PUBLIC_KEY LICENSE_DECRYPT_PRIVATE_KEY LICENSE_ENCRYPT_PUBLIC_KEY \
           PM_ADMIN_USER PM_ADMIN_PASSWORD PM_SMOKE_USER PM_SMOKE_PASSWORD \
           PLAYWRIGHT_REAL_BASE_URL PLAYWRIGHT_REAL_USER PLAYWRIGHT_REAL_PASSWORD PLAYWRIGHT_BROWSERS_PATH \
           PM_MONITORING_PUBLIC_BASE_URL GRAFANA_PORT PROMETHEUS_PORT TOKEN_EXPIRE_MINUTES \
           PM_WINDOWS_WBADMIN_SMB_AUTO PM_WINDOWS_WBADMIN_SMB_HOST PM_WINDOWS_WBADMIN_SHARE_NAME \
           PM_WINDOWS_WBADMIN_SHARE_PATH PM_WINDOWS_WBADMIN_SMB_USER PM_WINDOWS_WBADMIN_SMB_PASSWORD \
           PM_WINDOWS_WBADMIN_TARGET; do
    load_existing_backend_default "$key"
done

PACKAGED_LICENSE_SIGN_KEY="$(read_env_value "$PACKAGED_AUTHORITY_ENV" "LICENSE_SIGN_KEY")"
PACKAGED_LICENSE_VERIFY_PUBLIC_KEY="$(read_env_value "$PACKAGED_PUBLIC_AUTHORITY_ENV" "LICENSE_VERIFY_PUBLIC_KEY")"
PACKAGED_LICENSE_DECRYPT_PRIVATE_KEY="$(read_env_value "$PACKAGED_PUBLIC_AUTHORITY_ENV" "LICENSE_DECRYPT_PRIVATE_KEY")"
PACKAGED_LICENSE_ENCRYPT_PUBLIC_KEY="$(read_env_value "$PACKAGED_PUBLIC_AUTHORITY_ENV" "LICENSE_ENCRYPT_PUBLIC_KEY")"
PACKAGED_PRIVATE_BUNDLE_PUBLIC_KEY="$(read_env_value "$PACKAGED_AUTHORITY_ENV" "LICENSE_VERIFY_PUBLIC_KEY")"
PACKAGED_PRIVATE_BUNDLE_DECRYPT_KEY="$(read_env_value "$PACKAGED_AUTHORITY_ENV" "LICENSE_DECRYPT_PRIVATE_KEY")"
PACKAGED_PRIVATE_BUNDLE_ENCRYPT_KEY="$(read_env_value "$PACKAGED_AUTHORITY_ENV" "LICENSE_ENCRYPT_PUBLIC_KEY")"
SHARED_LICENSE_SIGN_KEY="$(read_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_SIGN_KEY")"
SHARED_LICENSE_VERIFY_PUBLIC_KEY="$(read_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_VERIFY_PUBLIC_KEY")"
SHARED_LICENSE_DECRYPT_PRIVATE_KEY="$(read_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_DECRYPT_PRIVATE_KEY")"
SHARED_LICENSE_ENCRYPT_PUBLIC_KEY="$(read_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_ENCRYPT_PUBLIC_KEY")"
EXISTING_BACKEND_LICENSE_SIGN_KEY="$(read_env_value "$INSTALL_DIR/backend/.env" "LICENSE_SIGN_KEY")"
EXISTING_BACKEND_LICENSE_VERIFY_PUBLIC_KEY="$(read_env_value "$INSTALL_DIR/backend/.env" "LICENSE_VERIFY_PUBLIC_KEY")"
EXISTING_BACKEND_LICENSE_DECRYPT_PRIVATE_KEY="$(read_env_value "$INSTALL_DIR/backend/.env" "LICENSE_DECRYPT_PRIVATE_KEY")"
EXISTING_BACKEND_LICENSE_ENCRYPT_PUBLIC_KEY="$(read_env_value "$INSTALL_DIR/backend/.env" "LICENSE_ENCRYPT_PUBLIC_KEY")"
if [[ -n "${INPUT_LICENSE_VERIFY_PUBLIC_KEY:-}" ]]; then
    LICENSE_VERIFY_PUBLIC_KEY="$INPUT_LICENSE_VERIFY_PUBLIC_KEY"
    log "  Using explicit LICENSE_VERIFY_PUBLIC_KEY from the environment"
elif [[ -n "$PACKAGED_LICENSE_VERIFY_PUBLIC_KEY" ]]; then
    LICENSE_VERIFY_PUBLIC_KEY="$PACKAGED_LICENSE_VERIFY_PUBLIC_KEY"
    log "  Reusing packaged LICENSE_VERIFY_PUBLIC_KEY from $PACKAGED_PUBLIC_AUTHORITY_ENV"
elif [[ -n "$PACKAGED_PRIVATE_BUNDLE_PUBLIC_KEY" ]]; then
    LICENSE_VERIFY_PUBLIC_KEY="$PACKAGED_PRIVATE_BUNDLE_PUBLIC_KEY"
    log "  Reusing packaged LICENSE_VERIFY_PUBLIC_KEY from $PACKAGED_AUTHORITY_ENV"
elif [[ -n "$SHARED_LICENSE_VERIFY_PUBLIC_KEY" ]]; then
    LICENSE_VERIFY_PUBLIC_KEY="$SHARED_LICENSE_VERIFY_PUBLIC_KEY"
    log "  Reusing shared LICENSE_VERIFY_PUBLIC_KEY from $SHARED_AUTHORITY_ENV"
elif [[ -n "$EXISTING_BACKEND_LICENSE_VERIFY_PUBLIC_KEY" ]]; then
    LICENSE_VERIFY_PUBLIC_KEY="$EXISTING_BACKEND_LICENSE_VERIFY_PUBLIC_KEY"
    log "  Reusing existing backend LICENSE_VERIFY_PUBLIC_KEY from $INSTALL_DIR/backend/.env"
fi

if [[ -n "${INPUT_LICENSE_DECRYPT_PRIVATE_KEY:-}" ]]; then
    LICENSE_DECRYPT_PRIVATE_KEY="$INPUT_LICENSE_DECRYPT_PRIVATE_KEY"
    log "  Using explicit LICENSE_DECRYPT_PRIVATE_KEY from the environment"
elif [[ -n "$PACKAGED_LICENSE_DECRYPT_PRIVATE_KEY" ]]; then
    LICENSE_DECRYPT_PRIVATE_KEY="$PACKAGED_LICENSE_DECRYPT_PRIVATE_KEY"
    log "  Reusing packaged LICENSE_DECRYPT_PRIVATE_KEY from $PACKAGED_PUBLIC_AUTHORITY_ENV"
elif [[ -n "$PACKAGED_PRIVATE_BUNDLE_DECRYPT_KEY" ]]; then
    LICENSE_DECRYPT_PRIVATE_KEY="$PACKAGED_PRIVATE_BUNDLE_DECRYPT_KEY"
    log "  Reusing packaged LICENSE_DECRYPT_PRIVATE_KEY from $PACKAGED_AUTHORITY_ENV"
elif [[ -n "$SHARED_LICENSE_DECRYPT_PRIVATE_KEY" ]]; then
    LICENSE_DECRYPT_PRIVATE_KEY="$SHARED_LICENSE_DECRYPT_PRIVATE_KEY"
    log "  Reusing shared LICENSE_DECRYPT_PRIVATE_KEY from $SHARED_AUTHORITY_ENV"
elif [[ -n "$EXISTING_BACKEND_LICENSE_DECRYPT_PRIVATE_KEY" ]]; then
    LICENSE_DECRYPT_PRIVATE_KEY="$EXISTING_BACKEND_LICENSE_DECRYPT_PRIVATE_KEY"
    log "  Reusing existing backend LICENSE_DECRYPT_PRIVATE_KEY from $INSTALL_DIR/backend/.env"
fi

if [[ -n "${INPUT_LICENSE_ENCRYPT_PUBLIC_KEY:-}" ]]; then
    LICENSE_ENCRYPT_PUBLIC_KEY="$INPUT_LICENSE_ENCRYPT_PUBLIC_KEY"
    log "  Using explicit LICENSE_ENCRYPT_PUBLIC_KEY from the environment"
elif [[ -n "$PACKAGED_LICENSE_ENCRYPT_PUBLIC_KEY" ]]; then
    LICENSE_ENCRYPT_PUBLIC_KEY="$PACKAGED_LICENSE_ENCRYPT_PUBLIC_KEY"
    log "  Reusing packaged LICENSE_ENCRYPT_PUBLIC_KEY from $PACKAGED_PUBLIC_AUTHORITY_ENV"
elif [[ -n "$PACKAGED_PRIVATE_BUNDLE_ENCRYPT_KEY" ]]; then
    LICENSE_ENCRYPT_PUBLIC_KEY="$PACKAGED_PRIVATE_BUNDLE_ENCRYPT_KEY"
    log "  Reusing packaged LICENSE_ENCRYPT_PUBLIC_KEY from $PACKAGED_AUTHORITY_ENV"
elif [[ -n "$SHARED_LICENSE_ENCRYPT_PUBLIC_KEY" ]]; then
    LICENSE_ENCRYPT_PUBLIC_KEY="$SHARED_LICENSE_ENCRYPT_PUBLIC_KEY"
    log "  Reusing shared LICENSE_ENCRYPT_PUBLIC_KEY from $SHARED_AUTHORITY_ENV"
elif [[ -n "$EXISTING_BACKEND_LICENSE_ENCRYPT_PUBLIC_KEY" ]]; then
    LICENSE_ENCRYPT_PUBLIC_KEY="$EXISTING_BACKEND_LICENSE_ENCRYPT_PUBLIC_KEY"
    log "  Reusing existing backend LICENSE_ENCRYPT_PUBLIC_KEY from $INSTALL_DIR/backend/.env"
fi

LICENSE_VERIFY_PUBLIC_KEY="${LICENSE_VERIFY_PUBLIC_KEY:-}"
LICENSE_DECRYPT_PRIVATE_KEY="${LICENSE_DECRYPT_PRIVATE_KEY:-}"
LICENSE_ENCRYPT_PUBLIC_KEY="${LICENSE_ENCRYPT_PUBLIC_KEY:-}"

if [[ -n "${INPUT_LICENSE_SIGN_KEY:-}" ]] && ! is_placeholder_secret "$INPUT_LICENSE_SIGN_KEY"; then
    LICENSE_SIGN_KEY="$INPUT_LICENSE_SIGN_KEY"
    log "  Using explicit LICENSE_SIGN_KEY from the environment"
elif [[ -n "$PACKAGED_LICENSE_SIGN_KEY" ]] && ! is_placeholder_secret "$PACKAGED_LICENSE_SIGN_KEY" && is_placeholder_secret "${LICENSE_SIGN_KEY:-}"; then
    LICENSE_SIGN_KEY="$PACKAGED_LICENSE_SIGN_KEY"
    log "  Reusing packaged LICENSE_SIGN_KEY from $PACKAGED_AUTHORITY_ENV"
elif [[ -n "$SHARED_LICENSE_SIGN_KEY" ]] && ! is_placeholder_secret "$SHARED_LICENSE_SIGN_KEY" && is_placeholder_secret "${LICENSE_SIGN_KEY:-}"; then
    LICENSE_SIGN_KEY="$SHARED_LICENSE_SIGN_KEY"
    log "  Reusing shared LICENSE_SIGN_KEY from $SHARED_AUTHORITY_ENV"
elif [[ -n "$EXISTING_BACKEND_LICENSE_SIGN_KEY" ]] && ! is_placeholder_secret "$EXISTING_BACKEND_LICENSE_SIGN_KEY" && is_placeholder_secret "${LICENSE_SIGN_KEY:-}"; then
    LICENSE_SIGN_KEY="$EXISTING_BACKEND_LICENSE_SIGN_KEY"
    log "  Reusing existing backend LICENSE_SIGN_KEY from $INSTALL_DIR/backend/.env"
fi

if is_placeholder_secret "${JWT_SECRET:-}"; then
    warn "  JWT_SECRET is unset or using the template placeholder; generating a runtime secret."
    unset JWT_SECRET
fi
if [[ -n "${LICENSE_VERIFY_PUBLIC_KEY:-}" ]] && is_placeholder_secret "${LICENSE_SIGN_KEY:-}"; then
    unset LICENSE_SIGN_KEY
fi
if [[ -z "${LICENSE_VERIFY_PUBLIC_KEY:-}" ]] && is_placeholder_secret "${LICENSE_SIGN_KEY:-}"; then
    warn "  LICENSE_SIGN_KEY is unset or using the template placeholder; generating a signing key."
    warn "  Use the same LICENSE_SIGN_KEY value in your vendor portal/CLI when generating license keys."
    unset LICENSE_SIGN_KEY
fi
if is_placeholder_secret "${PM_SECRET_KEY:-}"; then
    warn "  PM_SECRET_KEY is unset or using the template placeholder; generating a Fernet key."
    unset PM_SECRET_KEY
fi

# Auto-detect server IP
if [[ -z "${SERVER_IP:-}" ]]; then
    SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [[ -z "$SERVER_IP" ]] && SERVER_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
    [[ -z "$SERVER_IP" ]] && SERVER_IP="127.0.0.1"
    log "  Auto-detected server IP: $SERVER_IP"
fi

# Set defaults
FRONTEND_PORT=$(choose_port "${FRONTEND_PORT:-3000}" 3001 3080 8080 8888)
BACKEND_PORT=$(choose_port "${BACKEND_PORT:-8000}" 8001 18000 19000)
POSTGRES_USER="${POSTGRES_USER:-patchmaster}"
# Generate secure password if not provided
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(python3 -c 'import secrets; print("PgPm!7" + secrets.token_hex(8))')}"
POSTGRES_DB="${POSTGRES_DB:-patchmaster}"
JWT_SECRET="${JWT_SECRET:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
# Generate LICENSE_SIGN_KEY only for legacy shared-secret installs that do not
# have a public verification key.
if [[ -z "${LICENSE_VERIFY_PUBLIC_KEY:-}" ]]; then
    LICENSE_SIGN_KEY="${LICENSE_SIGN_KEY:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"
else
    LICENSE_SIGN_KEY="${LICENSE_SIGN_KEY:-}"
fi
# Generate PM_SECRET_KEY (Fernet-compatible) if not already set
PM_SECRET_KEY="${PM_SECRET_KEY:-$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')}"
PM_ADMIN_USER="${PM_ADMIN_USER:-admin}"
PM_ADMIN_PASSWORD="${PM_ADMIN_PASSWORD:-$(python3 -c "import secrets; print('PmA!7' + secrets.token_hex(4))")}"
PM_SMOKE_USER="${PM_SMOKE_USER:-qa-smoke}"
PM_SMOKE_PASSWORD="${PM_SMOKE_PASSWORD:-$(python3 -c "import secrets; print('PmS!7' + secrets.token_hex(4))")}"
PLAYWRIGHT_REAL_BASE_URL="${PLAYWRIGHT_REAL_BASE_URL:-http://${SERVER_IP}:${FRONTEND_PORT}}"
PLAYWRIGHT_REAL_USER="${PLAYWRIGHT_REAL_USER:-${PM_SMOKE_USER}}"
PLAYWRIGHT_REAL_PASSWORD="${PLAYWRIGHT_REAL_PASSWORD:-${PM_SMOKE_PASSWORD}}"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-${INSTALL_DIR}/frontend/.playwright-browsers}"
SKIP_FRONTEND_E2E="${SKIP_FRONTEND_E2E:-0}"

# Persist generated secrets back into the root env file, replacing any
# template placeholders instead of silently leaving them in place.
upsert_env_value "$INSTALL_DIR/.env" "JWT_SECRET" "$JWT_SECRET"
upsert_env_value "$INSTALL_DIR/.env" "LICENSE_SIGN_KEY" "$LICENSE_SIGN_KEY"
upsert_env_value "$INSTALL_DIR/.env" "LICENSE_DECRYPT_PRIVATE_KEY" "$LICENSE_DECRYPT_PRIVATE_KEY"
upsert_env_value "$INSTALL_DIR/.env" "LICENSE_ENCRYPT_PUBLIC_KEY" "$LICENSE_ENCRYPT_PUBLIC_KEY"
upsert_env_value "$INSTALL_DIR/.env" "PM_SECRET_KEY" "$PM_SECRET_KEY"
if [[ -n "${LICENSE_SIGN_KEY:-}" ]]; then
    upsert_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_SIGN_KEY" "$LICENSE_SIGN_KEY"
fi
if [[ -n "${LICENSE_VERIFY_PUBLIC_KEY:-}" ]]; then
    upsert_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_VERIFY_PUBLIC_KEY" "$LICENSE_VERIFY_PUBLIC_KEY"
    upsert_env_value "$INSTALL_DIR/.env" "LICENSE_VERIFY_PUBLIC_KEY" "$LICENSE_VERIFY_PUBLIC_KEY"
fi
if [[ -n "${LICENSE_DECRYPT_PRIVATE_KEY:-}" ]]; then
    upsert_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_DECRYPT_PRIVATE_KEY" "$LICENSE_DECRYPT_PRIVATE_KEY"
    upsert_env_value "$INSTALL_DIR/.env" "LICENSE_DECRYPT_PRIVATE_KEY" "$LICENSE_DECRYPT_PRIVATE_KEY"
fi
if [[ -n "${LICENSE_ENCRYPT_PUBLIC_KEY:-}" ]]; then
    upsert_env_value "$SHARED_AUTHORITY_ENV" "LICENSE_ENCRYPT_PUBLIC_KEY" "$LICENSE_ENCRYPT_PUBLIC_KEY"
    upsert_env_value "$INSTALL_DIR/.env" "LICENSE_ENCRYPT_PUBLIC_KEY" "$LICENSE_ENCRYPT_PUBLIC_KEY"
fi

JWT_SECRET="$(read_env_value "$INSTALL_DIR/.env" "JWT_SECRET")"
LICENSE_SIGN_KEY="$(read_env_value "$INSTALL_DIR/.env" "LICENSE_SIGN_KEY")"
LICENSE_VERIFY_PUBLIC_KEY="$(read_env_value "$INSTALL_DIR/.env" "LICENSE_VERIFY_PUBLIC_KEY")"
LICENSE_DECRYPT_PRIVATE_KEY="$(read_env_value "$INSTALL_DIR/.env" "LICENSE_DECRYPT_PRIVATE_KEY")"
LICENSE_ENCRYPT_PUBLIC_KEY="$(read_env_value "$INSTALL_DIR/.env" "LICENSE_ENCRYPT_PUBLIC_KEY")"
PM_SECRET_KEY="$(read_env_value "$INSTALL_DIR/.env" "PM_SECRET_KEY")"

# Monitoring defaults
GRAFANA_PORT="${GRAFANA_PORT:-3001}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
PM_PROMETHEUS_PROXY_PREFIX="${PM_PROMETHEUS_PROXY_PREFIX:-/api/monitoring/embed/prometheus/}"
PM_GRAFANA_PROXY_PREFIX="${PM_GRAFANA_PROXY_PREFIX:-/api/monitoring/embed/grafana/}"
GF_ADMIN_USER="${GF_ADMIN_USER:-admin}"
# Generate secure Grafana password if not provided
GF_ADMIN_PASSWORD="${GF_ADMIN_PASSWORD:-$(python3 -c 'import secrets; print("GfA!7" + secrets.token_hex(8))')}"
PROMETHEUS_RETENTION="${PROMETHEUS_RETENTION:-30d}"
PM_MONITORING_PUBLIC_BASE_URL="${PM_MONITORING_PUBLIC_BASE_URL:-http://${SERVER_IP}:${BACKEND_PORT}}"
PM_WINDOWS_WBADMIN_SMB_AUTO="${PM_WINDOWS_WBADMIN_SMB_AUTO:-1}"
PM_WINDOWS_WBADMIN_SMB_HOST="${PM_WINDOWS_WBADMIN_SMB_HOST:-${SERVER_IP}}"
PM_WINDOWS_WBADMIN_SHARE_NAME="${PM_WINDOWS_WBADMIN_SHARE_NAME:-patchmaster-wbadmin}"
PM_WINDOWS_WBADMIN_SHARE_PATH="${PM_WINDOWS_WBADMIN_SHARE_PATH:-/srv/${PM_WINDOWS_WBADMIN_SHARE_NAME}}"
PM_WINDOWS_WBADMIN_SMB_USER="${PM_WINDOWS_WBADMIN_SMB_USER:-patchmasterwb}"
PM_WINDOWS_WBADMIN_SMB_PASSWORD="${PM_WINDOWS_WBADMIN_SMB_PASSWORD:-$(python3 -c "import secrets; print('PmWb!7' + secrets.token_hex(4))")}"
PM_WINDOWS_WBADMIN_TARGET="${PM_WINDOWS_WBADMIN_TARGET:-\\\\${PM_WINDOWS_WBADMIN_SMB_HOST}\\${PM_WINDOWS_WBADMIN_SHARE_NAME}}"

DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"

log "  Backend port: $BACKEND_PORT, Frontend port: $FRONTEND_PORT"
if [[ "$INSTALL_MONITORING" == "true" ]]; then
    log "  Monitoring: Prometheus :$PROMETHEUS_PORT, Grafana :$GRAFANA_PORT"
fi

configure_windows_backup_share() {
    if [[ "${PM_WINDOWS_WBADMIN_SMB_AUTO:-1}" != "1" ]]; then
        log "  Windows SMB backup share auto-setup disabled (PM_WINDOWS_WBADMIN_SMB_AUTO=${PM_WINDOWS_WBADMIN_SMB_AUTO})."
        return 0
    fi

    local share_name="$PM_WINDOWS_WBADMIN_SHARE_NAME"
    local share_path="$PM_WINDOWS_WBADMIN_SHARE_PATH"
    local smb_user="$PM_WINDOWS_WBADMIN_SMB_USER"
    local smb_pass="$PM_WINDOWS_WBADMIN_SMB_PASSWORD"

    if ! command -v smbpasswd >/dev/null 2>&1; then
        warn "  smbpasswd not available; skipping SMB share setup."
        return 0
    fi

    mkdir -p "$share_path"
    if ! id -u "$smb_user" >/dev/null 2>&1; then
        useradd -M -s /usr/sbin/nologin "$smb_user" 2>/dev/null || useradd -M -s /sbin/nologin "$smb_user" 2>/dev/null || true
    fi
    chown -R "${smb_user}:${smb_user}" "$share_path" 2>/dev/null || true
    chmod 0770 "$share_path" 2>/dev/null || true

    printf '%s\n%s\n' "$smb_pass" "$smb_pass" | smbpasswd -a -s "$smb_user" >/dev/null 2>&1 || true
    smbpasswd -e "$smb_user" >/dev/null 2>&1 || true

    if [[ -f /etc/samba/smb.conf ]]; then
        if ! grep -q "^\[$share_name\]" /etc/samba/smb.conf 2>/dev/null; then
            cat >> /etc/samba/smb.conf <<EOF

[$share_name]
   path = $share_path
   browseable = yes
   writable = yes
   create mask = 0660
   directory mask = 0770
   valid users = $smb_user
EOF
        fi
    fi

    if systemctl list-unit-files | grep -q "^smbd.service"; then
        systemctl enable smbd nmbd >/dev/null 2>&1 || true
        systemctl restart smbd nmbd >/dev/null 2>&1 || true
    elif systemctl list-unit-files | grep -q "^smb.service"; then
        systemctl enable smb nmb >/dev/null 2>&1 || true
        systemctl restart smb nmb >/dev/null 2>&1 || true
    fi

    PM_WINDOWS_WBADMIN_TARGET="\\\\${PM_WINDOWS_WBADMIN_SMB_HOST}\\${share_name}"
    log "  Windows wbadmin target: ${PM_WINDOWS_WBADMIN_TARGET}"
}

###############################################################################
# Step 5: Setup PostgreSQL
###############################################################################
log "Step 5/${TOTAL_STEPS}: Configuring PostgreSQL..."

configure_windows_backup_share

# Start PostgreSQL
systemctl enable postgresql
systemctl start postgresql

# Wait for PostgreSQL to be ready
TRIES=0
until su - postgres -c "pg_isready" &>/dev/null || [[ $TRIES -ge 15 ]]; do
    sleep 1
    TRIES=$((TRIES + 1))
done

# Create database user and database (ignore errors if they already exist)
su - postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}';\"" 2>/dev/null || true
su - postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\"" 2>/dev/null || true
su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_USER};\"" 2>/dev/null || true

# Ensure local password auth works (scram instead of peer)
PG_HBA=$(su - postgres -c "psql -t -c 'SHOW hba_file;'" | tr -d ' ')
if [[ -f "$PG_HBA" ]]; then
    # Add a line for the patchmaster user before the default local entries
    if grep -qE "^local\\s+${POSTGRES_DB}\\s+${POSTGRES_USER}\\s+" "$PG_HBA"; then
        sed -i -E "s/^local\\s+${POSTGRES_DB}\\s+${POSTGRES_USER}\\s+\\S+/local   ${POSTGRES_DB}   ${POSTGRES_USER}                                scram-sha-256/" "$PG_HBA" || true
    else
        sed -i "/^local.*all.*all/i local   ${POSTGRES_DB}   ${POSTGRES_USER}                                scram-sha-256" "$PG_HBA"
    fi

    if grep -qE "^host\\s+${POSTGRES_DB}\\s+${POSTGRES_USER}\\s+127\\.0\\.0\\.1/32\\s+" "$PG_HBA"; then
        sed -i -E "s/^host\\s+${POSTGRES_DB}\\s+${POSTGRES_USER}\\s+127\\.0\\.0\\.1\\/32\\s+\\S+/host    ${POSTGRES_DB}   ${POSTGRES_USER}   127.0.0.1\\/32   scram-sha-256/" "$PG_HBA" || true
    else
        echo "host    ${POSTGRES_DB}   ${POSTGRES_USER}   127.0.0.1/32   scram-sha-256" >> "$PG_HBA"
    fi

    if grep -qE "^host\\s+${POSTGRES_DB}\\s+${POSTGRES_USER}\\s+::1/128\\s+" "$PG_HBA"; then
        sed -i -E "s/^host\\s+${POSTGRES_DB}\\s+${POSTGRES_USER}\\s+::1\\/128\\s+\\S+/host    ${POSTGRES_DB}   ${POSTGRES_USER}   ::1\\/128        scram-sha-256/" "$PG_HBA" || true
    else
        echo "host    ${POSTGRES_DB}   ${POSTGRES_USER}   ::1/128        scram-sha-256" >> "$PG_HBA"
    fi

    systemctl reload postgresql
fi

log "  PostgreSQL ready ? database: $POSTGRES_DB, user: $POSTGRES_USER"

###############################################################################
# Step 6: Setup Backend (Python + FastAPI)
###############################################################################
log "Step 6/${TOTAL_STEPS}: Setting up backend..."

cd "$INSTALL_DIR/backend"

# Create Python virtual environment
python3 -m venv "$INSTALL_DIR/backend/venv"
BACKEND_PIP="$INSTALL_DIR/backend/venv/bin/pip"
BACKEND_WHEELHOUSE="$INSTALL_DIR/vendor/wheels"
BACKEND_PIP_ARGS=(--disable-pip-version-check)
if [[ -d "$BACKEND_WHEELHOUSE" ]]; then
    BACKEND_PIP_ARGS+=(--find-links "$BACKEND_WHEELHOUSE")
fi

# Keep backend installs resilient on hosts with intermittent DNS/network access.
# If a bundled pip wheel exists, upgrade from it; otherwise keep the venv's pip.
if [[ -d "$BACKEND_WHEELHOUSE" ]] && compgen -G "$BACKEND_WHEELHOUSE/pip-*.whl" > /dev/null; then
    if ! "$BACKEND_PIP" install "${BACKEND_PIP_ARGS[@]}" --upgrade "$BACKEND_WHEELHOUSE"/pip-*.whl; then
        warn "  Bundled pip upgrade failed; continuing with the existing pip version."
    fi
else
    log "  Bundled pip wheel not found; keeping the existing pip version"
fi

"$BACKEND_PIP" install "${BACKEND_PIP_ARGS[@]}" -r requirements.txt

log "  Python venv created, dependencies installed"

# Write backend environment file (needed for init_db and for systemd service)
cat > "$INSTALL_DIR/backend/.env" <<BENV
DATABASE_URL=${DATABASE_URL}
JWT_SECRET=${JWT_SECRET}
TOKEN_EXPIRE_MINUTES=${TOKEN_EXPIRE_MINUTES:-480}
LICENSE_FILE=${INSTALL_DIR}/license.key
LICENSE_SIGN_KEY=${LICENSE_SIGN_KEY}
LICENSE_VERIFY_PUBLIC_KEY=${LICENSE_VERIFY_PUBLIC_KEY}
LICENSE_DECRYPT_PRIVATE_KEY=${LICENSE_DECRYPT_PRIVATE_KEY}
LICENSE_ENCRYPT_PUBLIC_KEY=${LICENSE_ENCRYPT_PUBLIC_KEY}
PM_SECRET_KEY=${PM_SECRET_KEY}
INSTALL_DIR=${INSTALL_DIR}
PM_ADMIN_USER=${PM_ADMIN_USER}
PM_ADMIN_PASSWORD=${PM_ADMIN_PASSWORD}
PM_SMOKE_USER=${PM_SMOKE_USER}
PM_SMOKE_PASSWORD=${PM_SMOKE_PASSWORD}
PLAYWRIGHT_REAL_BASE_URL=${PLAYWRIGHT_REAL_BASE_URL}
PLAYWRIGHT_REAL_USER=${PLAYWRIGHT_REAL_USER}
PLAYWRIGHT_REAL_PASSWORD=${PLAYWRIGHT_REAL_PASSWORD}
PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH}
PM_MONITORING_PUBLIC_BASE_URL=${PM_MONITORING_PUBLIC_BASE_URL}
PM_WINDOWS_WBADMIN_SMB_HOST=${PM_WINDOWS_WBADMIN_SMB_HOST}
PM_WINDOWS_WBADMIN_SHARE_NAME=${PM_WINDOWS_WBADMIN_SHARE_NAME}
PM_WINDOWS_WBADMIN_TARGET=${PM_WINDOWS_WBADMIN_TARGET}
BENV

# Verify backend can import (catches missing deps / missing models early)
log "  Verifying backend imports..."
cd "$INSTALL_DIR/backend"
(
    set -a
    # shellcheck disable=SC1091
    source "$INSTALL_DIR/backend/.env"
    set +a
    "$INSTALL_DIR/backend/venv/bin/python" -c "
import sys
print('Python version:', sys.version, file=sys.stderr)
print('Python executable:', sys.executable, file=sys.stderr)
print('Python path:', sys.path, file=sys.stderr)

# Test database import step by step
try:
    import database
    print('database module loaded', file=sys.stderr)
    print('__getattr__ defined:', hasattr(database, '__getattr__'), file=sys.stderr)
    print('async_session in dir:', 'async_session' in dir(database), file=sys.stderr)
    
    # Try to get async_session
    result = getattr(database, 'async_session')
    print('async_session type:', type(result).__name__, file=sys.stderr)
except Exception as e:
    print('Failed to import database:', e, file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Now try the full main import
import main
print('main module loaded successfully', file=sys.stderr)
"
) || {
    err "Backend import check failed."
    exit 1
}

# Explicitly initialize database tables
log "  Initializing database schema..."
cd "$INSTALL_DIR/backend"
(
    set -a
    # shellcheck disable=SC1091
    source "$INSTALL_DIR/backend/.env"
    set +a
    "$INSTALL_DIR/backend/venv/bin/python" -c "import asyncio; from database import init_db; asyncio.run(init_db())"
) || {
    warn "  Database initialization failed. Ensure PostgreSQL is running and credentials are correct."
}

# Create systemd service for backend
# Ensure logs directory exists with correct permissions before service starts
mkdir -p "${INSTALL_DIR}/logs"
chown "${SVC_USER}:${SVC_GROUP}" "${INSTALL_DIR}/logs"

cat > /etc/systemd/system/patchmaster-backend.service <<UNIT
[Unit]
Description=PatchMaster Backend API
After=network.target postgresql.service
Requires=postgresql.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=exec
User=${SVC_USER}
Group=${SVC_GROUP}
WorkingDirectory=${INSTALL_DIR}/backend
EnvironmentFile=${INSTALL_DIR}/backend/.env
ExecStartPre=${INSTALL_DIR}/backend/venv/bin/python -c "import main"
ExecStart=${INSTALL_DIR}/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${BACKEND_PORT} --workers 2
Restart=on-failure
RestartSec=5s
SuccessExitStatus=143
# Stream logs to journald; logrotate handles backend.log separately via tee-service below
StandardOutput=append:${INSTALL_DIR}/logs/backend.log
StandardError=append:${INSTALL_DIR}/logs/backend.log


[Install]
WantedBy=multi-user.target
UNIT

log "  Created patchmaster-backend.service"
log "  Frontend E2E Smoke configured for ${PLAYWRIGHT_REAL_BASE_URL} (user: ${PLAYWRIGHT_REAL_USER})"

# Logrotate for backend
cat > /etc/logrotate.d/patchmaster-backend <<LOGROT
${INSTALL_DIR}/logs/backend.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROT

# Logrotate for Linux agent (if present on this host)
cat > /etc/logrotate.d/patchmaster-agent <<'LOGROT'
/var/log/patch-agent/agent.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROT

###############################################################################
# Step 7: Build & serve Frontend (React ? Nginx)
###############################################################################
log "Step 7/${TOTAL_STEPS}: Setting up frontend & starting services..."

cd "$INSTALL_DIR/frontend"
FRONTEND_NODE_MODULES_READY=0

# Use pre-built frontend if available, otherwise build from source
if [[ -f "$INSTALL_DIR/frontend/dist/index.html" ]]; then
    log "  Using pre-built frontend"
else
    log "  Building frontend from source (requires Node.js & ~2GB RAM)..."
    install_frontend_node_modules
    run_with_progress "npm run build" env REACT_APP_API_URL="" npm run build
    if [[ ! -f "$INSTALL_DIR/frontend/dist/index.html" ]]; then
        err "  Frontend build failed. If low on RAM, pre-build on another machine."
        err "  See INSTALL.md for instructions."
        exit 1
    fi
    log "  React app built from source"
fi

if [[ "${SKIP_FRONTEND_E2E:-0}" == "1" ]]; then
    log "  Skipping frontend E2E tooling because SKIP_FRONTEND_E2E=1"
else
    log "  Installing frontend E2E tooling (optional - for Testing Center)..."
    
    # Try to install browsers but don't fail if it doesn't work
    if command -v npm >/dev/null 2>&1; then
        install_frontend_node_modules || {
            warn "  npm install failed, skipping browser installation"
            warn "  Testing Center will not be available but core features will work"
            SKIP_FRONTEND_E2E=1
        }
        
        if [[ "${SKIP_FRONTEND_E2E:-0}" != "1" ]]; then
            mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
            
            # Try to install browsers with timeout and error handling
            log "  Downloading Playwright browsers (this may take a few minutes)..."
            if timeout 600 env PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" npx playwright install --with-deps chromium 2>&1 | grep -v "Failed to fetch\|unexpected size" || true; then
                if [ -d "$PLAYWRIGHT_BROWSERS_PATH/chromium"* ] 2>/dev/null; then
                    chown -R "$SVC_USER:$SVC_GROUP" "$INSTALL_DIR/frontend/node_modules" "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
                    log "  Frontend E2E tooling ready"
                else
                    warn "  Browser installation incomplete - Testing Center may not work"
                    warn "  This is OK - all core PatchMaster features will work normally"
                fi
            else
                warn "  Browser installation failed (apt mirror sync issue or timeout)"
                warn "  This is OK - all core PatchMaster features will work normally"
                warn "  Testing Center can be set up later with: npx playwright install --with-deps chromium"
            fi
        fi
    else
        warn "  npm not available, skipping browser installation"
        warn "  Testing Center will not be available but core features will work"
    fi
fi

# Configure Nginx ? with SSL if certs provided
SSL_ENABLED=false
if [[ -z "$SSL_CERT" && -z "$SSL_KEY" && -f "$INSTALL_DIR/certs/fullchain.pem" && -f "$INSTALL_DIR/certs/privkey.pem" ]]; then
    REUSE_EXISTING_SSL=true
    SSL_ENABLED=true
    log "  Reusing existing SSL certificates from $INSTALL_DIR/certs/"
elif [[ -n "$SSL_CERT" ]]; then
    cp "$SSL_CERT" "$INSTALL_DIR/certs/fullchain.pem"
    cp "$SSL_KEY"  "$INSTALL_DIR/certs/privkey.pem"
    chmod 600 "$INSTALL_DIR/certs/privkey.pem"
    chmod 644 "$INSTALL_DIR/certs/fullchain.pem"
    chown "$SVC_USER:$SVC_GROUP" "$INSTALL_DIR/certs/"*.pem
    SSL_ENABLED=true
    log "  SSL certificates installed to $INSTALL_DIR/certs/"
fi

write_nginx_config() {
    if [[ "$SSL_ENABLED" == "true" ]]; then
        SSL_PORT="${FRONTEND_SSL_PORT:-443}"
        cat > /etc/nginx/sites-available/patchmaster <<NGINX
# HTTP ? HTTPS redirect
server {
    listen ${FRONTEND_PORT};
    server_name _;
    return 301 https://\$host\$request_uri;
}

# HTTPS server
server {
    listen ${SSL_PORT} ssl http2;
    server_name _;

    ssl_certificate     ${INSTALL_DIR}/certs/fullchain.pem;
    ssl_certificate_key ${INSTALL_DIR}/certs/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self' https:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:; font-src 'self' https: data:; connect-src 'self' https: http: ws: wss:;" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    root ${INSTALL_DIR}/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_connect_timeout 30s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /download/ {
        alias ${INSTALL_DIR}/backend/static/;
        try_files \$uri =404;
    }

    location /static/ {
        alias ${INSTALL_DIR}/backend/static/;
        try_files \$uri =404;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX
    else
        cat > /etc/nginx/sites-available/patchmaster <<NGINX
server {
    listen ${FRONTEND_PORT};
    server_name _;

    root ${INSTALL_DIR}/frontend/dist;
    index index.html;

    # Proxy API requests to FastAPI backend
    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        
        proxy_connect_timeout 30s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    # Serve agent .deb downloads from backend static
    location /download/ {
        alias ${INSTALL_DIR}/backend/static/;
        try_files \$uri =404;
    }

    location /static/ {
        alias ${INSTALL_DIR}/backend/static/;
        try_files \$uri =404;
    }

    # React SPA ? serve index.html for all other routes
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self' https:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:; font-src 'self' https: data:; connect-src 'self' https: http: ws: wss:;" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
}
NGINX
    fi

    # Enable the site
    if [[ -d /etc/nginx/sites-enabled ]]; then
        ln -sf /etc/nginx/sites-available/patchmaster /etc/nginx/sites-enabled/patchmaster
        # Remove default if it conflicts with our port
        if [[ "$FRONTEND_PORT" == "80" ]] && [[ -f /etc/nginx/sites-enabled/default ]]; then
            rm -f /etc/nginx/sites-enabled/default
        fi
    elif [[ -d /etc/nginx/conf.d ]]; then
        # RHEL-style: use conf.d
        cp /etc/nginx/sites-available/patchmaster /etc/nginx/conf.d/patchmaster.conf
    fi
}

write_nginx_config

# Test nginx config
nginx -t 2>/dev/null
systemctl enable nginx
if ! systemctl restart nginx; then
    warn "  Nginx failed to start on port $FRONTEND_PORT; retrying another port..."
    FRONTEND_PORT=$(choose_port 3001 3080 8080 8888 8880)
    write_nginx_config
    nginx -t 2>/dev/null
    if ! systemctl restart nginx; then
        err "Nginx could not start even after changing port. Check conflicts with: ss -tlnp | grep :${FRONTEND_PORT}"
        exit 1
    fi
fi

log "  Nginx configured on port $FRONTEND_PORT"
if [[ "$SSL_ENABLED" == "true" ]]; then
    log "  HTTPS enabled on port ${SSL_PORT} (HTTP?HTTPS redirect active)"
fi

###############################################################################
# Step 8 (optional): Install Prometheus + Grafana  (--with-monitoring)
###############################################################################
if [[ "$INSTALL_MONITORING" == "true" ]]; then
    log "Step 8/${TOTAL_STEPS}: Installing Prometheus & Grafana..."

    # ?? Prometheus ??????????????????????????????????????????????????????
    if ! command -v prometheus &>/dev/null; then
        log "  Installing Prometheus..."
        if [[ "$DISTRO" == "debian" ]]; then
            apt-get update -qq
            apt-get install -y -qq prometheus > /dev/null 2>&1 || {
                warn "  Prometheus package not available. Skipping Prometheus install."
            }
        elif [[ "$DISTRO" == "rhel" ]]; then
            $PKG_MGR install -y -q prometheus > /dev/null 2>&1 || {
                warn "  Prometheus package not available. Skipping Prometheus install."
            }
        fi
    else
        log "  Prometheus already installed: $(prometheus --version 2>&1 | head -1)"
    fi

    PROM_BIN="$(command -v prometheus 2>/dev/null || true)"

    # Create prometheus user if needed
    if [[ -n "$PROM_BIN" ]] && ! id prometheus &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin prometheus
    fi

    # Prometheus directories
    if [[ -n "$PROM_BIN" ]]; then
        mkdir -p /etc/prometheus /var/lib/prometheus
        chown prometheus:prometheus /var/lib/prometheus
    fi

    # Write Prometheus config pointing at PatchMaster /metrics
    if [[ -n "$PROM_BIN" ]]; then
        cat > /etc/prometheus/prometheus.yml <<PROMCFG
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'patchmaster'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['localhost:${BACKEND_PORT}']
        labels:
          instance: 'patchmaster-server'

  - job_name: 'patchmaster-agents'
    metrics_path: '/metrics'
    file_sd_configs:
      - files:
          - ${INSTALL_DIR}/monitoring/prometheus/agents/*.json
        refresh_interval: 60s

rule_files:
  - /etc/prometheus/alerts.yml
PROMCFG
        mkdir -p /etc/prometheus/agents
        mkdir -p "${INSTALL_DIR}/monitoring/prometheus/agents"
        chmod 755 "${INSTALL_DIR}/monitoring" "${INSTALL_DIR}/monitoring/prometheus" "${INSTALL_DIR}/monitoring/prometheus/agents" 2>/dev/null || true
        chown -R prometheus:prometheus /etc/prometheus

        if [[ -f "$INSTALL_DIR/monitoring/prometheus/alerts.yml" ]]; then
            cp "$INSTALL_DIR/monitoring/prometheus/alerts.yml" /etc/prometheus/alerts.yml
        else
            cat > /etc/prometheus/alerts.yml <<'ALERTS'
groups: []
ALERTS
        fi
        chown prometheus:prometheus /etc/prometheus/alerts.yml
    fi

    # Prometheus systemd service
    if [[ -n "$PROM_BIN" ]]; then
        cat > /etc/systemd/system/prometheus.service <<PROMSVC
[Unit]
Description=Prometheus Monitoring
After=network.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=${PROM_BIN} \\
    --config.file=/etc/prometheus/prometheus.yml \\
    --storage.tsdb.path=/var/lib/prometheus \\
    --storage.tsdb.retention.time=${PROMETHEUS_RETENTION} \\
    --web.listen-address=0.0.0.0:${PROMETHEUS_PORT} \\
    --web.enable-lifecycle
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
PROMSVC

    # Reload & start Prometheus
        systemctl daemon-reload
        systemctl enable prometheus
        systemctl restart prometheus
    fi
    
    # ?? Grafana ?????????????????????????????????????????????????????????
    if ! command -v grafana-server &>/dev/null; then
        log "  Installing Grafana..."
        if [[ "$DISTRO" == "debian" ]]; then
            curl -fsSL https://packages.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
            echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://packages.grafana.com/oss/deb stable main" > /etc/apt/sources.list.d/grafana.list
            apt-get update -qq && apt-get install -y -qq grafana > /dev/null 2>&1
        elif [[ "$DISTRO" == "rhel" ]]; then
            cat > /etc/yum.repos.d/grafana.repo <<GREPO
[grafana]
name=grafana
baseurl=https://packages.grafana.com/oss/rpm
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://packages.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
GREPO
            $PKG_MGR install -y -q grafana > /dev/null 2>&1
        fi
    fi
    
    # Configure Grafana
    log "  Configuring Grafana..."
    # Enable provisioning
    mkdir -p /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards
    
    # Datasource
    cat > /etc/grafana/provisioning/datasources/prometheus.yml <<GDS
apiVersion: 1
datasources:
  - uid: patchmaster-prometheus
    name: PatchMaster Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:${PROMETHEUS_PORT}${PM_PROMETHEUS_PROXY_PREFIX%/}
    isDefault: true
GDS

    # Dashboards provider
    cat > /etc/grafana/provisioning/dashboards/patchmaster.yml <<GDB
apiVersion: 1
providers:
  - name: 'PatchMaster'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    options:
      path: ${INSTALL_DIR}/monitoring/grafana/dashboards
GDB

    # Start Grafana once before the final proxy/provisioning pass. Some Grafana
    # builds report a failed unit on graceful SIGTERM during restart, so the
    # final monitoring-ctl pass does the safer reset-failed + start sequence.
    systemctl enable grafana-server
    systemctl start grafana-server || true

    if [[ -x "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" ]]; then
        log "  Finalizing monitoring proxy configuration..."
        INSTALL_DIR="$INSTALL_DIR" "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" install all >/dev/null 2>&1 || \
            warn "  Monitoring proxy finalization failed; use 'Repair Embed Access' after login if Grafana or Prometheus does not open inside PatchMaster."
        INSTALL_DIR="$INSTALL_DIR" "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" restart prometheus >/dev/null 2>&1 || true
        INSTALL_DIR="$INSTALL_DIR" "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" restart grafana >/dev/null 2>&1 || true
        sleep 2
        curl -fsS "http://127.0.0.1:${PROMETHEUS_PORT}${PM_PROMETHEUS_PROXY_PREFIX}-/healthy" >/dev/null 2>&1 || \
            warn "  Prometheus did not answer on 127.0.0.1:${PROMETHEUS_PORT}${PM_PROMETHEUS_PROXY_PREFIX}; review 'journalctl -u prometheus -n 50 --no-pager'."
        curl -fsS "http://127.0.0.1:${GRAFANA_PORT}${PM_GRAFANA_PROXY_PREFIX}api/health" >/dev/null 2>&1 || \
            warn "  Grafana did not answer on 127.0.0.1:${GRAFANA_PORT}${PM_GRAFANA_PROXY_PREFIX}; review 'journalctl -u grafana-server -n 50 --no-pager'."
    fi
fi

###############################################################################
# Start services & verify
###############################################################################
log "  Starting services..."

# Set ownership

# Set ownership for all files and directories
chown -R "$SVC_USER:$SVC_GROUP" "$INSTALL_DIR"

# Re-secure monitoring controller after recursive chown
if [[ -f "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" ]]; then
    chown root:root "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" || true
    chmod 755 "$INSTALL_DIR/backend/scripts/monitoring-ctl.sh" || true
fi

# Copy license.key from package if present
if [[ -f "$PROJECT_ROOT/license.key" ]]; then
    log "  Installing bundled license key..."
    cp "$PROJECT_ROOT/license.key" "$INSTALL_DIR/license.key"
    chown $SVC_USER:$SVC_GROUP "$INSTALL_DIR/license.key"
    chmod 644 "$INSTALL_DIR/license.key"
elif [[ -f "$INSTALL_DIR/license.key" ]]; then
    # Ensure existing license.key has correct permissions
    chown $SVC_USER:$SVC_GROUP "$INSTALL_DIR/license.key"
    chmod 644 "$INSTALL_DIR/license.key"
fi

# Logs dir needs write access
chmod 755 "$INSTALL_DIR/logs"

# Reload systemd
systemctl daemon-reload

# Start backend
systemctl enable patchmaster-backend
systemctl start patchmaster-backend

log "  patchmaster-backend started"

# Wait for backend to be ready
log "  Waiting for backend..."
TRIES=0
until curl -sf "http://127.0.0.1:${BACKEND_PORT}/api/health" &>/dev/null || [[ $TRIES -ge 90 ]]; do
    sleep 2
    TRIES=$((TRIES + 1))
done

if [[ $TRIES -ge 90 ]]; then
    warn "  Backend not responding yet ? check: journalctl -u patchmaster-backend"
    systemctl status patchmaster-backend --no-pager | tail -n 25 || true
    journalctl -u patchmaster-backend -n 80 --no-pager || true
    if [[ -f "${INSTALL_DIR}/logs/backend.log" ]]; then
        tail -n 80 "${INSTALL_DIR}/logs/backend.log" || true
    fi
    if [[ "$IS_UPGRADE" == "true" ]]; then rollback; fi
else
    log "  Backend API: healthy"
fi

# ?? Final Success Check ??
if [[ "$IS_UPGRADE" == "true" ]]; then
    log "Upgrade successful! Removing trap."
    trap - ERR
    # Move backup to a permanent location or remove if not needed
    mv "$BACKUP_DIR" "$BACKUP_DIR-SUCCESS"
    log "Backup preserved at: $BACKUP_DIR-SUCCESS"
fi

###############################################################################
# Generate ready-to-use Prometheus scrape config for existing setups
###############################################################################
mkdir -p "$INSTALL_DIR/monitoring/integration-configs"

cat > "$INSTALL_DIR/monitoring/integration-configs/prometheus-scrape-job.yml" <<SCRAPE
# ?? Add this to your existing prometheus.yml under scrape_configs: ??
# Then reload Prometheus: kill -HUP \$(pidof prometheus)

  - job_name: 'patchmaster'
    metrics_path: '/metrics'
    scrape_interval: 30s
    static_configs:
      - targets: ['${SERVER_IP}:${BACKEND_PORT}']
        labels:
          instance: 'patchmaster-server'
SCRAPE

chown -R "$SVC_USER:$SVC_GROUP" "$INSTALL_DIR/monitoring/integration-configs"
log "  Generated monitoring integration configs in $INSTALL_DIR/monitoring/integration-configs/"

###############################################################################
# Summary
###############################################################################
echo ""
echo -e "${BLUE}==============================================================${NC}"
if [[ "$IS_UPGRADE" == "true" ]]; then
echo -e "${GREEN}  PatchMaster v${PM_VERSION} upgraded successfully! (bare-metal)${NC}"
else
echo -e "${GREEN}  PatchMaster v${PM_VERSION} installed successfully! (bare-metal)${NC}"
fi
echo -e "${BLUE}==============================================================${NC}"
echo ""
echo "  Install directory:  $INSTALL_DIR"
echo ""
echo "  Service URLs:"
if [[ "$SSL_ENABLED" == "true" ]]; then
echo "    Web UI:      https://${SERVER_IP}:${SSL_PORT}  (HTTP :${FRONTEND_PORT} ? HTTPS redirect)"
echo "    Backend API: http://${SERVER_IP}:${BACKEND_PORT}/docs"
else
echo "    Web UI:      http://${SERVER_IP}:${FRONTEND_PORT}"
echo "    Backend API: http://${SERVER_IP}:${BACKEND_PORT}/docs"
fi
if [[ "$INSTALL_MONITORING" == "true" ]]; then
echo "    Grafana embed:    http://${SERVER_IP}:${BACKEND_PORT}${PM_GRAFANA_PROXY_PREFIX}"
echo "    Prometheus embed: http://${SERVER_IP}:${BACKEND_PORT}${PM_PROMETHEUS_PROXY_PREFIX}"
echo "    Internal Grafana: http://127.0.0.1:${GRAFANA_PORT}"
echo "    Internal Prom:    http://127.0.0.1:${PROMETHEUS_PORT}"
fi
echo ""
echo "  First-time setup:"
if [[ "$SSL_ENABLED" == "true" ]]; then
echo "    1. Open https://${SERVER_IP}:${SSL_PORT}"
else
echo "    1. Open http://${SERVER_IP}:${FRONTEND_PORT}"
fi
echo "    2. Login with:"
echo "       Admin user:      ${PM_ADMIN_USER}"
echo "       Admin password:  ${PM_ADMIN_PASSWORD}"
echo "       QA smoke user:   ${PM_SMOKE_USER}"
echo "       QA smoke pass:   ${PM_SMOKE_PASSWORD}"
echo "    3. Activate your license: Settings ? License"
echo "       Or place license.key file in ${INSTALL_DIR}/license.key"
echo "    4. Go to DevOps ? QA Testing or Testing Center ? Frontend E2E Smoke"
echo "       Authenticated smoke is pre-wired to ${PLAYWRIGHT_REAL_BASE_URL}"
echo "    5. Go to 'Onboarding' to install agents on hosts"
echo ""
echo "  Agent install (Linux):"
if [[ "$SSL_ENABLED" == "true" ]]; then
echo "    curl -sS https://${SERVER_IP}:${SSL_PORT}/download/install-agent.sh | sudo MASTER_URL=http://${SERVER_IP}:${BACKEND_PORT} bash"
else
echo "    curl -sS http://${SERVER_IP}:${FRONTEND_PORT}/download/install-agent.sh | sudo MASTER_URL=http://${SERVER_IP}:${BACKEND_PORT} bash"
fi
echo ""
echo "  Agent install (Windows EXE Installer):"
if [[ "$SSL_ENABLED" == "true" ]]; then
echo "    Download: https://${SERVER_IP}:${SSL_PORT}/download/patchmaster-agent-installer.exe"
echo "    Run:      PatchMaster-Agent-Installer.exe --master-url http://${SERVER_IP}:${BACKEND_PORT}"
else
echo "    Download: http://${SERVER_IP}:${FRONTEND_PORT}/download/patchmaster-agent-installer.exe"
echo "    Run:      PatchMaster-Agent-Installer.exe --master-url http://${SERVER_IP}:${BACKEND_PORT}"
fi
if [[ "${PM_WINDOWS_WBADMIN_SMB_AUTO:-1}" == "1" ]]; then
echo ""
echo "  Windows full-system backup (auto-configured):"
echo "    wbadmin target: ${PM_WINDOWS_WBADMIN_TARGET}"
echo "    SMB user:       ${PM_WINDOWS_WBADMIN_SMB_USER}"
echo "    SMB password:   ${PM_WINDOWS_WBADMIN_SMB_PASSWORD}"
fi
echo ""
echo "  Monitoring Integration:"
if [[ "$INSTALL_MONITORING" == "true" ]]; then
echo "    Prometheus + Grafana installed and configured automatically."
echo "    Grafana embed:    http://${SERVER_IP}:${BACKEND_PORT}${PM_GRAFANA_PROXY_PREFIX}"
echo "    Prometheus embed: http://${SERVER_IP}:${BACKEND_PORT}${PM_PROMETHEUS_PROXY_PREFIX}"
echo "    Internal Grafana: http://127.0.0.1:${GRAFANA_PORT}"
echo "    Internal Prom:    http://127.0.0.1:${PROMETHEUS_PORT}"
else
echo ""
echo "    Already have Prometheus/Grafana? Connect them to PatchMaster:"
echo ""
echo "    ?? Prometheus ??"
echo "      Add this scrape job to your prometheus.yml:"
echo "        - job_name: 'patchmaster'"
echo "          metrics_path: '/metrics'"
echo "          static_configs:"
echo "            - targets: ['${SERVER_IP}:${BACKEND_PORT}']"
echo "      Ready-to-copy config: $INSTALL_DIR/monitoring/integration-configs/prometheus-scrape-job.yml"
echo ""
echo "    ?? Grafana ??"
echo "      Import dashboard: $INSTALL_DIR/monitoring/grafana/dashboards/patchmaster-overview.json"
echo "      (Grafana ? Dashboards ? Import ? Upload JSON)"
echo ""
echo "    (Optional) Prometheus scrape job example saved to monitoring/integration-configs/"
echo ""
echo "    Full guide: $INSTALL_DIR/docs/MONITORING-INTEGRATION.md"
echo "    Or re-run with --with-monitoring to install Prometheus + Grafana here."
fi
echo ""
echo "  Management:"
echo "    systemctl {start|stop|restart} patchmaster-backend"
echo "    systemctl {start|stop|restart} nginx"
if [[ "$INSTALL_MONITORING" == "true" ]]; then
echo "    systemctl {start|stop|restart} prometheus"
echo "    systemctl {start|stop|restart} grafana-server"
fi
echo ""
echo "  Logs:"
echo "    tail -f $INSTALL_DIR/logs/backend.log"
echo "    journalctl -u patchmaster-backend -f"
echo "    journalctl -u nginx -f"
echo ""
if [[ "$SSL_ENABLED" == "true" ]]; then
    echo "  SSL certificates:"
    echo "    Cert: $INSTALL_DIR/certs/fullchain.pem"
    echo "    Key:  $INSTALL_DIR/certs/privkey.pem"
    echo "    To renew: replace the files and run: systemctl restart nginx"
    echo ""
else
    echo "  Enable HTTPS later:"
    echo "    Re-run: sudo $0 --ssl-cert /path/to/fullchain.pem --ssl-key /path/to/privkey.pem"
    echo ""
fi
if [[ "$JWT_SECRET" == "change-me-to-a-secure-random-string" ]]; then
    echo -e "  ${YELLOW}WARNING: Change JWT_SECRET in $INSTALL_DIR/backend/.env for production!${NC}"
    echo ""
fi
