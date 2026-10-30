#!/bin/bash
# Patch-SecOps Solution Automated Setup Script for Linux/Mac
# Handles all setup, dependencies, and common issues automatically

set -e

# Configuration
PYTHON_MIN_VERSION="3.10"
NODE_MIN_VERSION="18"
PROJECT_ROOT="$(pwd)"
LOG_FILE="setup-$(date +%Y%m%d-%H%M%S).log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error_log() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

warn_log() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

info_log() {
    echo -e "${CYAN}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Compare versions
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

# Check Python
check_python() {
    log "Checking Python installation..."
    
    PYTHON_CMD=""
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        PYTHON_CMD="python"
    else
        error_log "Python not found. Please install Python $PYTHON_MIN_VERSION+"
        return 1
    fi
    
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+\.\d+')
    info_log "Found Python $PYTHON_VERSION"
    
    if version_ge "$PYTHON_VERSION" "$PYTHON_MIN_VERSION"; then
        log "✓ Python version OK"
        export PYTHON_CMD
        return 0
    else
        error_log "Python $PYTHON_MIN_VERSION+ required, found $PYTHON_VERSION"
        return 1
    fi
}

# Check Node.js
check_node() {
    log "Checking Node.js installation..."
    
    if ! command_exists node; then
        warn_log "Node.js not found. Please install Node.js $NODE_MIN_VERSION+ from https://nodejs.org/"
        return 1
    fi
    
    NODE_VERSION=$(node --version 2>&1 | sed 's/v//')
    info_log "Found Node.js $NODE_VERSION"
    
    if version_ge "$NODE_VERSION" "$NODE_MIN_VERSION"; then
        log "✓ Node.js version OK"
        return 0
    else
        warn_log "Node.js $NODE_MIN_VERSION+ recommended, found $NODE_VERSION"
        return 0
    fi
}

# Setup Python virtual environment
setup_python_venv() {
    local dir=$1
    local venv_name=${2:-.venv}
    
    log "Setting up Python virtual environment in $dir..."
    
    cd "$PROJECT_ROOT/$dir"
    
    if [ -d "$venv_name" ]; then
        warn_log "Virtual environment already exists, skipping creation"
    else
        $PYTHON_CMD -m venv "$venv_name"
        log "✓ Virtual environment created"
    fi
    
    # Activate venv
    source "$venv_name/bin/activate"
    
    # Upgrade pip
    python -m pip install --upgrade pip setuptools wheel >> "$PROJECT_ROOT/$LOG_FILE" 2>&1
    
    log "✓ Virtual environment ready"
    cd "$PROJECT_ROOT"
}

# Install Python dependencies
install_python_deps() {
    local dir=$1
    local venv_name=${2:-.venv}
    
    log "Installing Python dependencies for $dir..."
    
    cd "$PROJECT_ROOT/$dir"
    source "$venv_name/bin/activate"
    
    # Check if we have local wheels
    if [ -d "$PROJECT_ROOT/vendor/wheels" ]; then
        info_log "Using local wheel files (offline mode)"
        if pip install --no-index --find-links="$PROJECT_ROOT/vendor/wheels" -r requirements.txt >> "$PROJECT_ROOT/$LOG_FILE" 2>&1; then
            log "✓ Installed from local wheels"
        else
            warn_log "Failed with local wheels, trying online installation..."
            pip install -r requirements.txt >> "$PROJECT_ROOT/$LOG_FILE" 2>&1
        fi
    else
        info_log "Installing from PyPI (online mode)"
        pip install -r requirements.txt >> "$PROJECT_ROOT/$LOG_FILE" 2>&1
    fi
    
    log "✓ Python dependencies installed for $dir"
    cd "$PROJECT_ROOT"
}

# Setup Backend
setup_backend() {
    log "=== Setting up Backend ==="
    
    setup_python_venv "backend" || return 1
    install_python_deps "backend" || return 1
    
    # Create .env if not exists
    if [ ! -f "backend/.env" ]; then
        log "Creating backend/.env from template..."
        SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
        LICENSE_KEY=$(openssl rand -hex 32 2>/dev/null || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
        
        cat > backend/.env << EOF
# Database
DATABASE_URL=postgresql://patchmaster:patchmaster@localhost:5432/patchmaster

# Security
PM_SECRET_KEY=$SECRET_KEY
LICENSE_SIGN_KEY=$LICENSE_KEY

# Redis (optional)
REDIS_URL=redis://localhost:6379

# CORS (adjust for your domain)
CORS_ORIGINS=["http://localhost:5173","http://localhost"]
EOF
        log "✓ Created backend/.env (please review and update)"
    fi
    
    log "✓ Backend setup complete"
}

# Setup Frontend
setup_frontend() {
    log "=== Setting up Frontend ==="
    
    cd "$PROJECT_ROOT/frontend"
    
    # Check if node_modules exists
    if [ -d "node_modules" ]; then
        info_log "node_modules already exists, skipping npm install"
    else
        log "Installing Node.js dependencies..."
        # Install all dependencies including Playwright
        npm install >> "$PROJECT_ROOT/$LOG_FILE" 2>&1
        
        # Install Playwright browsers completely
        log "Installing Playwright browsers for Testing Center..."
        npx playwright install chromium >> "$PROJECT_ROOT/$LOG_FILE" 2>&1
        log "✓ Playwright browsers installed successfully"
    fi
    
    # Create .env if not exists
    if [ ! -f ".env" ]; then
        log "Creating frontend/.env from template..."
        cat > .env << EOF
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
EOF
        log "✓ Created frontend/.env"
    fi
    
    cd "$PROJECT_ROOT"
    log "✓ Frontend setup complete"
}

# Setup Agent
setup_agent() {
    log "=== Setting up Agent ==="
    
    setup_python_venv "agent" || return 1
    install_python_deps "agent" || return 1
    
    log "✓ Agent setup complete"
}

# Setup Vendor
setup_vendor() {
    log "=== Setting up Vendor Portal ==="
    
    setup_python_venv "vendor" || return 1
    install_python_deps "vendor" || return 1
    
    # Create .env if not exists
    if [ ! -f "vendor/.env" ]; then
        log "Creating vendor/.env from template..."
        SIGN_KEY=$(openssl rand -hex 32 2>/dev/null || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
        ENCRYPT_KEY=$(openssl rand -hex 32 2>/dev/null || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
        FLASK_KEY=$(openssl rand -hex 32 2>/dev/null || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
        
        cat > vendor/.env << EOF
# Database
DATABASE_URL=postgresql://vendor:vendor@localhost:5432/vendor

# License Keys
LICENSE_SIGN_KEY=$SIGN_KEY
LICENSE_ENCRYPT_KEY=$ENCRYPT_KEY

# Flask
FLASK_SECRET_KEY=$FLASK_KEY
EOF
        log "✓ Created vendor/.env (please review and update)"
    fi
    
    log "✓ Vendor portal setup complete"
}

# Create startup scripts
create_startup_scripts() {
    log "=== Creating Startup Scripts ==="
    
    # Backend startup script
    cat > start-backend.sh << 'EOF'
#!/bin/bash
cd backend
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
EOF
    chmod +x start-backend.sh
    log "✓ Created start-backend.sh"
    
    # Frontend startup script
    cat > start-frontend.sh << 'EOF'
#!/bin/bash
cd frontend
npm run dev
EOF
    chmod +x start-frontend.sh
    log "✓ Created start-frontend.sh"
    
    # Vendor startup script
    cat > start-vendor.sh << 'EOF'
#!/bin/bash
cd vendor
source .venv/bin/activate
python app.py
EOF
    chmod +x start-vendor.sh
    log "✓ Created start-vendor.sh"
    
    # Start all script
    cat > start-all.sh << 'EOF'
#!/bin/bash
echo "Starting Patch-SecOps Solution services..."
echo ""
echo "Starting backend..."
./start-backend.sh &
BACKEND_PID=$!

echo "Starting frontend..."
./start-frontend.sh &
FRONTEND_PID=$!

echo ""
echo "Services started!"
echo "Backend PID: $BACKEND_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Access the application:"
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait
EOF
    chmod +x start-all.sh
    log "✓ Created start-all.sh"
}

# Print summary
show_summary() {
    echo ""
    echo -e "${GREEN}==========================================${NC}"
    echo -e "${GREEN}  Patch-SecOps Solution Setup Complete!${NC}"
    echo -e "${GREEN}==========================================${NC}"
    echo ""
    echo -e "${GREEN}✓ Backend setup complete${NC}"
    echo -e "${GREEN}✓ Frontend setup complete${NC}"
    echo -e "${GREEN}✓ Agent setup complete${NC}"
    echo -e "${GREEN}✓ Vendor portal setup complete${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo ""
    echo -e "${NC}1. Review and update configuration files:${NC}"
    echo -e "   ${CYAN}backend/.env${NC}"
    echo -e "   ${CYAN}frontend/.env${NC}"
    echo -e "   ${CYAN}vendor/.env${NC}"
    echo ""
    echo -e "${NC}2. Start services:${NC}"
    echo -e "   ${CYAN}./start-all.sh${NC}         # Start all services"
    echo -e "   ${CYAN}./start-backend.sh${NC}     # Start backend only"
    echo -e "   ${CYAN}./start-frontend.sh${NC}    # Start frontend only"
    echo -e "   ${CYAN}./start-vendor.sh${NC}      # Start vendor portal only"
    echo ""
    echo -e "${NC}3. Access the application:${NC}"
    echo -e "   ${CYAN}Frontend:  http://localhost:5173${NC}"
    echo -e "   ${CYAN}Backend:   http://localhost:8000${NC}"
    echo -e "   ${CYAN}API Docs:  http://localhost:8000/docs${NC}"
    echo -e "   ${CYAN}Vendor:    http://localhost:5001${NC}"
    echo ""
    echo -e "${NC}4. Or use Docker:${NC}"
    echo -e "   ${CYAN}docker-compose up -d${NC}"
    echo ""
    echo -e "${YELLOW}Setup log saved to: $LOG_FILE${NC}"
    echo ""
}

# Main function
main() {
    echo ""
    echo -e "${CYAN}==========================================${NC}"
    echo -e "${CYAN}  Patch-SecOps Solution Automated Setup${NC}"
    echo -e "${CYAN}==========================================${NC}"
    echo ""
    
    log "Starting automated setup..."
    log "Project root: $PROJECT_ROOT"
    
    # Check prerequisites
    check_python || exit 1
    check_node || warn_log "Node.js check failed, but continuing..."
    
    # Setup components
    setup_backend || { error_log "Backend setup failed"; exit 1; }
    setup_frontend || { error_log "Frontend setup failed"; exit 1; }
    setup_agent || warn_log "Agent setup failed, but continuing..."
    setup_vendor || warn_log "Vendor setup failed, but continuing..."
    
    # Create helper scripts
    create_startup_scripts
    
    # Print summary
    show_summary
    
    log "Setup completed successfully!"
}

# Run main function
main
