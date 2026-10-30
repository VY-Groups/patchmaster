#!/bin/bash
# Diagnose agent registration and visibility issues
# Run this on the Patch-SecOps Solution server

set -e

echo "=== Patch-SecOps Solution Agent Diagnostics ==="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

BACKEND_PORT=8000
DB_NAME="patchmaster"
DB_USER="patchmaster"

echo -e "${BLUE}[System Information]${NC}"
echo "Hostname: $(hostname)"
echo "IP Address: $(hostname -I | awk '{print $1}')"
echo "Date/Time: $(date)"
echo ""

echo -e "${BLUE}[1. Backend Service Status]${NC}"
if systemctl is-active --quiet patchmaster-backend; then
    echo -e "${GREEN}✓${NC} Backend service is running"
    
    # Check if API is responding
    if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Backend API is responding"
        HEALTH=$(curl -s http://127.0.0.1:${BACKEND_PORT}/api/health)
        echo "  Response: $HEALTH"
    else
        echo -e "${RED}✗${NC} Backend API is not responding"
    fi
else
    echo -e "${RED}✗${NC} Backend service is not running"
    echo "Start with: sudo systemctl start patchmaster-backend"
fi
echo ""

echo -e "${BLUE}[2. Database Connection]${NC}"
if command -v psql &> /dev/null; then
    # Test database connection
    if sudo -u postgres psql -d ${DB_NAME} -c "SELECT 1;" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Database connection successful"
        
        # Count hosts
        HOST_COUNT=$(sudo -u postgres psql -d ${DB_NAME} -t -c "SELECT COUNT(*) FROM hosts;" 2>/dev/null | tr -d ' ')
        echo "  Total hosts in database: ${HOST_COUNT}"
        
        # Count online hosts
        ONLINE_COUNT=$(sudo -u postgres psql -d ${DB_NAME} -t -c "SELECT COUNT(*) FROM hosts WHERE is_online = true;" 2>/dev/null | tr -d ' ')
        echo "  Online hosts: ${ONLINE_COUNT}"
        
        # Show recent registrations
        echo ""
        echo "  Recent host registrations:"
        sudo -u postgres psql -d ${DB_NAME} -c "SELECT id, hostname, ip, os, is_online, last_heartbeat FROM hosts ORDER BY created_at DESC LIMIT 5;" 2>/dev/null || echo "  (Unable to query)"
        
    else
        echo -e "${RED}✗${NC} Cannot connect to database"
    fi
else
    echo -e "${YELLOW}!${NC} psql not found, skipping database checks"
fi
echo ""

echo -e "${BLUE}[3. API Endpoints Test]${NC}"

# Test registration endpoint
echo "Testing /api/register endpoint..."
if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/register > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Registration endpoint accessible"
else
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${BACKEND_PORT}/api/register)
    if [ "$STATUS" = "405" ] || [ "$STATUS" = "422" ]; then
        echo -e "${GREEN}✓${NC} Registration endpoint accessible (POST required, got $STATUS)"
    else
        echo -e "${RED}✗${NC} Registration endpoint returned: $STATUS"
    fi
fi

# Test hosts endpoint
echo "Testing /api/hosts endpoint..."
HOSTS_RESPONSE=$(curl -s http://127.0.0.1:${BACKEND_PORT}/api/hosts/ 2>/dev/null)
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Hosts endpoint accessible"
    HOST_COUNT=$(echo "$HOSTS_RESPONSE" | grep -o '"id"' | wc -l)
    echo "  Hosts returned by API: $HOST_COUNT"
else
    echo -e "${RED}✗${NC} Hosts endpoint not accessible"
fi

# Test groups endpoint
echo "Testing /api/groups endpoint..."
if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/groups/ > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Groups endpoint accessible"
else
    echo -e "${RED}✗${NC} Groups endpoint not accessible"
fi

# Test WebSocket endpoint
echo "Testing /api/notifications/ws endpoint..."
WS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${BACKEND_PORT}/api/notifications/ws)
if [ "$WS_STATUS" = "426" ] || [ "$WS_STATUS" = "101" ]; then
    echo -e "${GREEN}✓${NC} WebSocket endpoint accessible (status: $WS_STATUS)"
else
    echo -e "${YELLOW}!${NC} WebSocket endpoint returned: $WS_STATUS (426 or 101 expected)"
fi
echo ""

echo -e "${BLUE}[4. nginx Configuration]${NC}"
if [ -f /etc/nginx/sites-available/patchmaster ]; then
    echo -e "${GREEN}✓${NC} nginx config exists"
    
    # Check for WebSocket headers
    if grep -q "proxy_set_header Upgrade" /etc/nginx/sites-available/patchmaster; then
        echo -e "${GREEN}✓${NC} WebSocket headers present in nginx config"
    else
        echo -e "${RED}✗${NC} WebSocket headers MISSING in nginx config"
        echo "  Run: sudo bash fix_websocket_and_groups.sh"
    fi
    
    # Test nginx config
    if nginx -t 2>&1 | grep -q "successful"; then
        echo -e "${GREEN}✓${NC} nginx configuration is valid"
    else
        echo -e "${RED}✗${NC} nginx configuration has errors"
    fi
    
    # Check if nginx is running
    if systemctl is-active --quiet nginx; then
        echo -e "${GREEN}✓${NC} nginx service is running"
    else
        echo -e "${RED}✗${NC} nginx service is not running"
    fi
else
    echo -e "${RED}✗${NC} nginx config not found"
fi
echo ""

echo -e "${BLUE}[5. Network Connectivity]${NC}"
# Check if port 8000 is listening
if netstat -tuln 2>/dev/null | grep -q ":${BACKEND_PORT}"; then
    echo -e "${GREEN}✓${NC} Backend port ${BACKEND_PORT} is listening"
else
    if ss -tuln 2>/dev/null | grep -q ":${BACKEND_PORT}"; then
        echo -e "${GREEN}✓${NC} Backend port ${BACKEND_PORT} is listening"
    else
        echo -e "${RED}✗${NC} Backend port ${BACKEND_PORT} is NOT listening"
    fi
fi

# Check if port 3000 is listening (frontend)
if netstat -tuln 2>/dev/null | grep -q ":3000"; then
    echo -e "${GREEN}✓${NC} Frontend port 3000 is listening"
else
    if ss -tuln 2>/dev/null | grep -q ":3000"; then
        echo -e "${GREEN}✓${NC} Frontend port 3000 is listening"
    else
        echo -e "${YELLOW}!${NC} Frontend port 3000 is NOT listening (nginx may be serving on port 80/443)"
    fi
fi
echo ""

echo -e "${BLUE}[6. Recent Backend Logs]${NC}"
echo "Last 10 lines from backend service:"
journalctl -u patchmaster-backend -n 10 --no-pager 2>/dev/null || echo "Unable to read logs"
echo ""

echo -e "${BLUE}[7. Agent Connectivity Test]${NC}"
echo "Testing if agents can reach this server..."
echo "From agent machine, run:"
echo "  curl http://$(hostname -I | awk '{print $1}'):8000/api/health"
echo ""

echo -e "${GREEN}=== Diagnostics Complete ===${NC}"
echo ""
echo "Common Issues & Solutions:"
echo ""
echo "1. Agents not showing in UI:"
echo "   • Check agent service: systemctl status patch-agent"
echo "   • Verify CONTROLLER_URL: cat /etc/patch-agent/env"
echo "   • Test connectivity from agent: curl http://172.24.1.254:8000/api/health"
echo "   • Check agent logs: journalctl -u patch-agent -n 50"
echo ""
echo "2. WebSocket connection failed:"
echo "   • Run: sudo bash fix_websocket_and_groups.sh"
echo "   • Clear browser cache and reload"
echo ""
echo "3. Groups & Tags page not working:"
echo "   • Check browser console (F12) for JavaScript errors"
echo "   • Verify backend logs: journalctl -u patchmaster-backend -f"
echo "   • Test API: curl http://127.0.0.1:8000/api/groups/"
echo ""
echo "4. Database connection issues:"
echo "   • Check PostgreSQL: systemctl status postgresql"
echo "   • Verify DATABASE_URL in /opt/patchmaster/backend/.env"
echo "   • Test connection: sudo -u postgres psql -d patchmaster -c 'SELECT 1;'"
echo ""
