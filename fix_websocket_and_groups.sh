#!/bin/bash
# Fix WebSocket connections and Groups & Tags page issues
# Run this on the Patch-SecOps Solution server (172.24.1.254)

set -e

echo "=== Patch-SecOps Solution WebSocket & Groups Fix ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}[ERROR]${NC} Please run as root (sudo)"
    exit 1
fi

INSTALL_DIR="/opt/patchmaster"
BACKEND_PORT=8000

echo -e "${YELLOW}[1/6]${NC} Backing up nginx configuration..."
if [ -f /etc/nginx/sites-available/patchmaster ]; then
    cp /etc/nginx/sites-available/patchmaster /etc/nginx/sites-available/patchmaster.backup.$(date +%Y%m%d_%H%M%S)
    echo -e "${GREEN}✓${NC} Backup created"
else
    echo -e "${RED}✗${NC} nginx config not found at /etc/nginx/sites-available/patchmaster"
    exit 1
fi

echo ""
echo -e "${YELLOW}[2/6]${NC} Checking for WebSocket proxy headers in nginx..."

# Check if WebSocket headers are already present
if grep -q "proxy_set_header Upgrade" /etc/nginx/sites-available/patchmaster; then
    echo -e "${GREEN}✓${NC} WebSocket headers already present"
else
    echo -e "${YELLOW}!${NC} Adding WebSocket support to nginx configuration..."
    
    # Add WebSocket headers to nginx config
    # This is a safe sed operation that adds the headers after proxy_set_header X-Forwarded-Proto
    sed -i '/proxy_set_header X-Forwarded-Proto/a\        \n        # WebSocket support\n        proxy_http_version 1.1;\n        proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection "upgrade";' /etc/nginx/sites-available/patchmaster
    
    # Also update timeouts
    sed -i 's/proxy_read_timeout 300s;/proxy_read_timeout 300s;\n        proxy_send_timeout 300s;/' /etc/nginx/sites-available/patchmaster
    
    echo -e "${GREEN}✓${NC} WebSocket headers added"
fi

echo ""
echo -e "${YELLOW}[3/6]${NC} Testing nginx configuration..."
if nginx -t 2>&1 | grep -q "successful"; then
    echo -e "${GREEN}✓${NC} nginx configuration is valid"
else
    echo -e "${RED}✗${NC} nginx configuration test failed"
    echo "Restoring backup..."
    cp /etc/nginx/sites-available/patchmaster.backup.* /etc/nginx/sites-available/patchmaster 2>/dev/null || true
    exit 1
fi

echo ""
echo -e "${YELLOW}[4/6]${NC} Reloading nginx..."
systemctl reload nginx
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} nginx reloaded successfully"
else
    echo -e "${RED}✗${NC} Failed to reload nginx"
    exit 1
fi

echo ""
echo -e "${YELLOW}[5/6]${NC} Checking backend service..."
if systemctl is-active --quiet patchmaster-backend; then
    echo -e "${GREEN}✓${NC} Backend service is running"
    
    # Check if backend is responding
    if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Backend API is responding"
    else
        echo -e "${YELLOW}!${NC} Backend API not responding, restarting..."
        systemctl restart patchmaster-backend
        sleep 3
        
        if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/health > /dev/null 2>&1; then
            echo -e "${GREEN}✓${NC} Backend API is now responding"
        else
            echo -e "${RED}✗${NC} Backend API still not responding"
            echo "Check logs: journalctl -u patchmaster-backend -n 50"
        fi
    fi
else
    echo -e "${RED}✗${NC} Backend service is not running"
    echo "Starting backend service..."
    systemctl start patchmaster-backend
    sleep 3
    
    if systemctl is-active --quiet patchmaster-backend; then
        echo -e "${GREEN}✓${NC} Backend service started"
    else
        echo -e "${RED}✗${NC} Failed to start backend service"
        echo "Check logs: journalctl -u patchmaster-backend -n 50"
        exit 1
    fi
fi

echo ""
echo -e "${YELLOW}[6/6]${NC} Verifying fixes..."

# Test WebSocket endpoint
echo "Testing WebSocket endpoint availability..."
if curl -s -I http://127.0.0.1:${BACKEND_PORT}/api/notifications/ws 2>&1 | grep -q "426\|101"; then
    echo -e "${GREEN}✓${NC} WebSocket endpoint is accessible (426/101 expected for non-WS request)"
else
    echo -e "${YELLOW}!${NC} WebSocket endpoint response unclear (may still work)"
fi

# Test Groups API
echo "Testing Groups API..."
if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/groups/ > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Groups API is responding"
else
    echo -e "${RED}✗${NC} Groups API not responding"
fi

# Check registered agents
echo "Checking registered agents..."
AGENT_COUNT=$(curl -s http://127.0.0.1:${BACKEND_PORT}/api/hosts/ 2>/dev/null | grep -o '"id"' | wc -l)
if [ "$AGENT_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Found $AGENT_COUNT registered host(s)"
else
    echo -e "${YELLOW}!${NC} No hosts registered yet"
fi

echo ""
echo -e "${GREEN}=== Fix Complete ===${NC}"
echo ""
echo "Summary of changes:"
echo "  • Added WebSocket proxy headers to nginx"
echo "  • Increased proxy timeouts for long-lived connections"
echo "  • Verified backend service is running"
echo "  • Tested API endpoints"
echo ""
echo "Next steps:"
echo "  1. Clear your browser cache (Ctrl+Shift+Delete)"
echo "  2. Reload the Patch-SecOps Solution web interface"
echo "  3. Navigate to Groups & Tags page"
echo "  4. Check browser console (F12) for any remaining errors"
echo ""
echo "If agents are not showing:"
echo "  • Verify agent service is running: systemctl status patch-agent"
echo "  • Check agent logs: journalctl -u patch-agent -n 50"
echo "  • Verify CONTROLLER_URL in /etc/patch-agent/env"
echo "  • Test connectivity: curl http://172.24.1.254:8000/api/health"
echo ""
echo "Troubleshooting:"
echo "  • Backend logs: journalctl -u patchmaster-backend -f"
echo "  • nginx logs: tail -f /var/log/nginx/error.log"
echo "  • nginx config: cat /etc/nginx/sites-available/patchmaster"
echo ""
