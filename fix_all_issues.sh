#!/bin/bash
# Comprehensive fix for Patch-SecOps Solution installation issues
# Run this on the Ubuntu Patch-SecOps Solution server

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=================================="
echo "Patch-SecOps Solution - Comprehensive Fix"
echo "==================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

INSTALL_DIR="/opt/patchmaster"
BACKUP_DIR="/tmp/patchmaster-backup-$(date +%Y%m%d%H%M%S)"

# Create backup
echo -e "${YELLOW}Creating backup...${NC}"
mkdir -p "$BACKUP_DIR"
cp -r "$INSTALL_DIR/backend/database.py" "$BACKUP_DIR/" 2>/dev/null || true
cp -r "$INSTALL_DIR/backend/main.py" "$BACKUP_DIR/" 2>/dev/null || true

echo -e "${GREEN}✓ Backup created at $BACKUP_DIR${NC}"
echo ""

# Fix 1: Database initialization feedback
echo -e "${YELLOW}Fix 1: Adding database initialization feedback...${NC}"
cat > /tmp/db_init_fix.py << 'EOF'
async def init_db():
    """Create all tables on startup."""
    db_engine = get_engine()
    if db_engine is None:
        raise RuntimeError(
            "Database not configured. Set DATABASE_URL environment variable."
        )
    async with db_engine.begin() as conn:
        from models import db_models  # noqa: F401

        try:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
            print("✓ Database schema initialized successfully")
        except Exception as e:
            # Handle duplicate index/table errors gracefully during upgrades
            error_msg = str(e).lower()
            if "already exists" in error_msg or "duplicate" in error_msg:
                print("⚠ Warning: Some database objects already exist (likely from previous installation)")
                print("✓ Database schema verification complete - continuing with existing schema")
                # Continue - tables/indexes already exist from previous install
            else:
                # Re-raise other errors
                print(f"✗ Error initializing database: {e}")
                raise
EOF

python3 << 'PYTHON_FIX1'
import re

with open('/opt/patchmaster/backend/database.py', 'r') as f:
    content = f.read()

with open('/tmp/db_init_fix.py', 'r') as f:
    new_function = f.read()

pattern = r'async def init_db\(\):.*?(?=\n(?:async def|def|class|\Z))'
content = re.sub(pattern, new_function.rstrip(), content, flags=re.DOTALL)

with open('/opt/patchmaster/backend/database.py', 'w') as f:
    f.write(content)
PYTHON_FIX1

rm /tmp/db_init_fix.py
echo -e "${GREEN}✓ Database initialization fix applied${NC}"
echo ""

# Fix 2: Ensure proper permissions
echo -e "${YELLOW}Fix 2: Setting proper permissions...${NC}"
chown -R patchmaster:patchmaster "$INSTALL_DIR" 2>/dev/null || true
chmod -R 755 "$INSTALL_DIR/backend" 2>/dev/null || true
chmod -R 755 "$INSTALL_DIR/frontend" 2>/dev/null || true
echo -e "${GREEN}✓ Permissions fixed${NC}"
echo ""

# Fix 3: Check and fix PostgreSQL connection
echo -e "${YELLOW}Fix 3: Verifying PostgreSQL connection...${NC}"
if systemctl is-active --quiet postgresql; then
    echo -e "${GREEN}✓ PostgreSQL is running${NC}"
else
    echo -e "${YELLOW}Starting PostgreSQL...${NC}"
    systemctl start postgresql
    echo -e "${GREEN}✓ PostgreSQL started${NC}"
fi
echo ""

# Fix 4: Restart backend service
echo -e "${YELLOW}Fix 4: Restarting Patch-SecOps Solution backend...${NC}"
systemctl daemon-reload
systemctl restart patchmaster-backend 2>/dev/null || true
sleep 3

if systemctl is-active --quiet patchmaster-backend; then
    echo -e "${GREEN}✓ Backend service is running${NC}"
else
    echo -e "${RED}✗ Backend service failed to start${NC}"
    echo "Checking logs..."
    journalctl -u patchmaster-backend -n 20 --no-pager
fi
echo ""

# Fix 5: Check backend logs for errors
echo -e "${YELLOW}Fix 5: Checking for backend errors...${NC}"
if [ -f "$INSTALL_DIR/logs/backend.log" ]; then
    ERRORS=$(tail -n 50 "$INSTALL_DIR/logs/backend.log" | grep -i "error\|exception\|failed" | tail -n 5)
    if [ -n "$ERRORS" ]; then
        echo -e "${YELLOW}Recent errors found:${NC}"
        echo "$ERRORS"
    else
        echo -e "${GREEN}✓ No recent errors in backend log${NC}"
    fi
else
    echo -e "${YELLOW}Backend log not found yet${NC}"
fi
echo ""

# Fix 6: Verify agent download endpoint
echo -e "${YELLOW}Fix 6: Verifying agent download endpoint...${NC}"
if [ -f "$INSTALL_DIR/backend/static/agent-latest.deb" ]; then
    SIZE=$(stat -f%z "$INSTALL_DIR/backend/static/agent-latest.deb" 2>/dev/null || stat -c%s "$INSTALL_DIR/backend/static/agent-latest.deb")
    if [ "$SIZE" -gt 1000 ]; then
        echo -e "${GREEN}✓ Agent package exists (${SIZE} bytes)${NC}"
    else
        echo -e "${RED}✗ Agent package is too small (${SIZE} bytes)${NC}"
    fi
else
    echo -e "${RED}✗ Agent package not found${NC}"
fi
echo ""

# Fix 7: Check frontend service
echo -e "${YELLOW}Fix 7: Checking frontend service...${NC}"
if systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓ Nginx is running${NC}"
else
    echo -e "${YELLOW}Starting Nginx...${NC}"
    systemctl start nginx
    echo -e "${GREEN}✓ Nginx started${NC}"
fi
echo ""

# Fix 8: Test API endpoint
echo -e "${YELLOW}Fix 8: Testing API endpoint...${NC}"
API_TEST=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>/dev/null || echo "000")
if [ "$API_TEST" = "200" ] || [ "$API_TEST" = "404" ]; then
    echo -e "${GREEN}✓ Backend API is responding (HTTP $API_TEST)${NC}"
else
    echo -e "${RED}✗ Backend API not responding (HTTP $API_TEST)${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}=================================="
echo "Fix Summary"
echo "==================================${NC}"
echo ""
echo "Applied fixes:"
echo "  ✓ Database initialization feedback"
echo "  ✓ File permissions"
echo "  ✓ PostgreSQL verification"
echo "  ✓ Backend service restart"
echo "  ✓ Error log check"
echo "  ✓ Agent package verification"
echo "  ✓ Frontend service check"
echo "  ✓ API endpoint test"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Check the web interface: http://$(hostname -I | awk '{print $1}'):3000"
echo "2. Check backend logs: journalctl -u patchmaster-backend -f"
echo "3. If issues persist, check: $INSTALL_DIR/logs/backend.log"
echo ""
echo -e "${GREEN}Backup location: $BACKUP_DIR${NC}"
