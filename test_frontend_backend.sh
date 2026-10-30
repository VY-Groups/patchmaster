#!/bin/bash
# Test frontend-backend integration
# Run this on the Patch-SecOps Solution server after installation

set -e

echo "=== Patch-SecOps Solution Frontend-Backend Integration Test ==="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

BACKEND_PORT=8000
FRONTEND_PORT=3000
NGINX_PORT=80

echo -e "${BLUE}[1. Backend API Tests]${NC}"

# Test backend health
echo "Testing backend health endpoint..."
if curl -s -f http://127.0.0.1:${BACKEND_PORT}/api/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://127.0.0.1:${BACKEND_PORT}/api/health)
    echo -e "${GREEN}✓${NC} Backend health: $HEALTH"
else
    echo -e "${RED}✗${NC} Backend health check failed"
    exit 1
fi

# Test backend CORS headers
echo "Testing CORS headers..."
CORS_HEADERS=$(curl -s -I http://127.0.0.1:${BACKEND_PORT}/api/health | grep -i "access-control")
if [ -n "$CORS_HEADERS" ]; then
    echo -e "${GREEN}✓${NC} CORS headers present"
    echo "$CORS_HEADERS"
else
    echo -e "${YELLOW}!${NC} No CORS headers (may be OK if behind nginx)"
fi

# Test backend endpoints
echo ""
echo "Testing backend endpoints..."
ENDPOINTS=(
    "/api/health"
    "/api/license/info"
    "/api/auth/me"
)

for endpoint in "${ENDPOINTS[@]}"; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${BACKEND_PORT}${endpoint})
    if [ "$STATUS" = "200" ] || [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
        echo -e "${GREEN}✓${NC} ${endpoint} - Status: ${STATUS}"
    else
        echo -e "${RED}✗${NC} ${endpoint} - Status: ${STATUS}"
    fi
done

echo ""
echo -e "${BLUE}[2. nginx Proxy Tests]${NC}"

# Test nginx is running
if systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓${NC} nginx service is running"
else
    echo -e "${RED}✗${NC} nginx service is not running"
    exit 1
fi

# Test nginx proxy to backend
echo "Testing nginx proxy to backend..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${FRONTEND_PORT}/api/health)
if [ "$STATUS" = "200" ]; then
    echo -e "${GREEN}✓${NC} nginx proxy working - Status: ${STATUS}"
else
    echo -e "${RED}✗${NC} nginx proxy failed - Status: ${STATUS}"
    echo "Check nginx config: /etc/nginx/sites-available/patchmaster"
fi

# Test WebSocket proxy
echo "Testing WebSocket endpoint via nginx..."
WS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${FRONTEND_PORT}/api/notifications/ws)
if [ "$WS_STATUS" = "426" ] || [ "$WS_STATUS" = "101" ]; then
    echo -e "${GREEN}✓${NC} WebSocket endpoint accessible - Status: ${WS_STATUS}"
else
    echo -e "${YELLOW}!${NC} WebSocket endpoint - Status: ${WS_STATUS} (426 or 101 expected)"
fi

echo ""
echo -e "${BLUE}[3. Frontend Tests]${NC}"

# Test frontend files exist
if [ -f /opt/patchmaster/frontend/dist/index.html ]; then
    echo -e "${GREEN}✓${NC} Frontend files exist"
else
    echo -e "${RED}✗${NC} Frontend files missing"
    exit 1
fi

# Test frontend is served by nginx
echo "Testing frontend is served..."
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${FRONTEND_PORT}/)
if [ "$STATUS" = "200" ]; then
    echo -e "${GREEN}✓${NC} Frontend served by nginx - Status: ${STATUS}"
    
    # Check if index.html contains expected content
    CONTENT=$(curl -s http://127.0.0.1:${FRONTEND_PORT}/)
    if echo "$CONTENT" | grep -q "Patch-SecOps Solution"; then
        echo -e "${GREEN}✓${NC} Frontend content looks correct"
    else
        echo -e "${YELLOW}!${NC} Frontend content may be incorrect"
    fi
else
    echo -e "${RED}✗${NC} Frontend not accessible - Status: ${STATUS}"
fi

echo ""
echo -e "${BLUE}[4. API Integration Tests]${NC}"

# Test API calls through nginx (as frontend would)
echo "Testing API calls through nginx proxy..."

# Test health through proxy
HEALTH_PROXY=$(curl -s http://127.0.0.1:${FRONTEND_PORT}/api/health)
if echo "$HEALTH_PROXY" | grep -q "healthy"; then
    echo -e "${GREEN}✓${NC} API health through proxy: $HEALTH_PROXY"
else
    echo -e "${RED}✗${NC} API health through proxy failed"
fi

# Test license info through proxy
LICENSE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:${FRONTEND_PORT}/api/license/info)
if [ "$LICENSE_STATUS" = "200" ]; then
    echo -e "${GREEN}✓${NC} License API through proxy - Status: ${LICENSE_STATUS}"
else
    echo -e "${YELLOW}!${NC} License API through proxy - Status: ${LICENSE_STATUS}"
fi

echo ""
echo -e "${BLUE}[5. Browser Compatibility Tests]${NC}"

# Check if frontend JavaScript is valid
echo "Checking frontend JavaScript..."
if [ -f /opt/patchmaster/frontend/dist/assets/index-*.js ]; then
    JS_FILE=$(ls /opt/patchmaster/frontend/dist/assets/index-*.js | head -1)
    JS_SIZE=$(du -h "$JS_FILE" | cut -f1)
    echo -e "${GREEN}✓${NC} Frontend JavaScript exists (${JS_SIZE})"
    
    # Check for common issues
    if grep -q "API.*http" "$JS_FILE"; then
        echo -e "${GREEN}✓${NC} API configuration found in JavaScript"
    else
        echo -e "${YELLOW}!${NC} API configuration may be missing"
    fi
else
    echo -e "${RED}✗${NC} Frontend JavaScript not found"
fi

echo ""
echo -e "${BLUE}[6. Configuration Tests]${NC}"

# Check nginx configuration
echo "Checking nginx configuration..."
if nginx -t 2>&1 | grep -q "successful"; then
    echo -e "${GREEN}✓${NC} nginx configuration is valid"
else
    echo -e "${RED}✗${NC} nginx configuration has errors"
    nginx -t
fi

# Check for WebSocket headers in nginx config
if grep -q "proxy_set_header Upgrade" /etc/nginx/sites-available/patchmaster; then
    echo -e "${GREEN}✓${NC} WebSocket headers configured in nginx"
else
    echo -e "${RED}✗${NC} WebSocket headers missing in nginx"
    echo "Run: sudo bash fix_websocket_and_groups.sh"
fi

# Check backend environment
if [ -f /opt/patchmaster/backend/.env ]; then
    echo -e "${GREEN}✓${NC} Backend environment file exists"
    
    # Check DATABASE_URL
    if grep -q "DATABASE_URL" /opt/patchmaster/backend/.env; then
        echo -e "${GREEN}✓${NC} DATABASE_URL configured"
    else
        echo -e "${RED}✗${NC} DATABASE_URL missing"
    fi
else
    echo -e "${RED}✗${NC} Backend environment file missing"
fi

echo ""
echo -e "${BLUE}[7. Network Tests]${NC}"

# Check ports are listening
echo "Checking listening ports..."
for port in ${BACKEND_PORT} ${FRONTEND_PORT} 5432; do
    if netstat -tuln 2>/dev/null | grep -q ":${port}" || ss -tuln 2>/dev/null | grep -q ":${port}"; then
        echo -e "${GREEN}✓${NC} Port ${port} is listening"
    else
        echo -e "${RED}✗${NC} Port ${port} is NOT listening"
    fi
done

echo ""
echo -e "${GREEN}=== Integration Test Complete ===${NC}"
echo ""

# Summary
echo "Summary:"
echo "  • Backend API: http://127.0.0.1:${BACKEND_PORT}"
echo "  • Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "  • nginx proxy: /api/ → backend:${BACKEND_PORT}"
echo ""

# Test from browser
echo "To test from browser:"
echo "  1. Open: http://YOUR_SERVER_IP:${FRONTEND_PORT}"
echo "  2. Open browser console (F12)"
echo "  3. Check for errors"
echo "  4. Try to login"
echo ""

# Common issues
echo "Common Issues:"
echo "  • 'Failed to fetch' - Check nginx proxy configuration"
echo "  • 'CORS error' - Check CORS headers in backend"
echo "  • 'WebSocket failed' - Run fix_websocket_and_groups.sh"
echo "  • '401 Unauthorized' - Normal for /api/auth/me without login"
echo "  • 'Cannot connect to backend' - Check backend service"
echo ""
