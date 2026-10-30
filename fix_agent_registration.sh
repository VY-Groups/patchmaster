#!/bin/bash
# Fix agent registration issues
# Run this on the AGENT machine (not the Patch-SecOps Solution server)

set -e

echo "=== Patch-SecOps Solution Agent Registration Fix ==="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}[ERROR]${NC} Please run as root (sudo)"
    exit 1
fi

# Get controller URL from user if not set
if [ -f /etc/patch-agent/env ]; then
    source /etc/patch-agent/env
fi

if [ -z "$CONTROLLER_URL" ]; then
    echo -e "${YELLOW}[!]${NC} CONTROLLER_URL not set"
    read -p "Enter Patch-SecOps Solution server IP or hostname: " CONTROLLER_IP
    CONTROLLER_URL="http://${CONTROLLER_IP}:8000"
    echo "CONTROLLER_URL=${CONTROLLER_URL}" > /etc/patch-agent/env
    echo -e "${GREEN}✓${NC} CONTROLLER_URL set to: ${CONTROLLER_URL}"
else
    echo -e "${GREEN}✓${NC} CONTROLLER_URL: ${CONTROLLER_URL}"
fi

echo ""
echo -e "${YELLOW}[1/6]${NC} Testing connectivity to Patch-SecOps Solution server..."

# Extract host and port from CONTROLLER_URL
CONTROLLER_HOST=$(echo $CONTROLLER_URL | sed -e 's|^[^/]*//||' -e 's|:.*||')
CONTROLLER_PORT=$(echo $CONTROLLER_URL | sed -e 's|^[^:]*:||' -e 's|/.*||')

# Test connectivity
if curl -s -f --connect-timeout 5 ${CONTROLLER_URL}/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Successfully connected to Patch-SecOps Solution server"
    HEALTH=$(curl -s ${CONTROLLER_URL}/api/health)
    echo "  Server response: $HEALTH"
else
    echo -e "${RED}✗${NC} Cannot connect to Patch-SecOps Solution server at ${CONTROLLER_URL}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Verify server IP/hostname is correct"
    echo "  2. Check if server is running: ssh ${CONTROLLER_HOST} 'systemctl status patchmaster-backend'"
    echo "  3. Check firewall: sudo ufw status"
    echo "  4. Test port: telnet ${CONTROLLER_HOST} ${CONTROLLER_PORT}"
    echo "  5. Ping server: ping ${CONTROLLER_HOST}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[2/6]${NC} Checking agent installation..."

if [ -d /opt/patch-agent ]; then
    echo -e "${GREEN}✓${NC} Agent installed at /opt/patch-agent"
    
    # Check agent version
    if [ -f /opt/patch-agent/agent.py ]; then
        AGENT_VERSION=$(grep -oP "AGENT_VERSION\s*=\s*['\"]\\K[^'\"]*" /opt/patch-agent/agent.py 2>/dev/null || echo "unknown")
        echo "  Agent version: ${AGENT_VERSION}"
    fi
else
    echo -e "${RED}✗${NC} Agent not installed at /opt/patch-agent"
    echo "Install agent first from: ${CONTROLLER_URL}/download/agent-latest.deb"
    exit 1
fi

echo ""
echo -e "${YELLOW}[3/6]${NC} Configuring agent services..."

# Ensure config directory exists
mkdir -p /etc/patch-agent

# Write configuration
echo "CONTROLLER_URL=${CONTROLLER_URL}" > /etc/patch-agent/env
echo -e "${GREEN}✓${NC} Configuration written to /etc/patch-agent/env"

# Set proper permissions
chmod 644 /etc/patch-agent/env
chown root:root /etc/patch-agent/env

echo ""
echo -e "${YELLOW}[4/6]${NC} Stopping existing agent services..."

# Stop services if running
systemctl stop patch-agent 2>/dev/null || true
systemctl stop patch-agent-heartbeat 2>/dev/null || true
echo -e "${GREEN}✓${NC} Services stopped"

# Wait a moment for services to fully stop
sleep 2

echo ""
echo -e "${YELLOW}[5/6]${NC} Starting agent services..."

# Enable and start services
systemctl enable patch-agent patch-agent-heartbeat
systemctl start patch-agent
systemctl start patch-agent-heartbeat

# Wait for services to start
sleep 3

# Check service status
if systemctl is-active --quiet patch-agent; then
    echo -e "${GREEN}✓${NC} patch-agent service is running"
else
    echo -e "${RED}✗${NC} patch-agent service failed to start"
    echo "Check logs: journalctl -u patch-agent -n 50"
    exit 1
fi

if systemctl is-active --quiet patch-agent-heartbeat; then
    echo -e "${GREEN}✓${NC} patch-agent-heartbeat service is running"
else
    echo -e "${RED}✗${NC} patch-agent-heartbeat service failed to start"
    echo "Check logs: journalctl -u patch-agent-heartbeat -n 50"
    exit 1
fi

echo ""
echo -e "${YELLOW}[6/6]${NC} Verifying registration..."

# Wait for initial registration
echo "Waiting for agent to register (10 seconds)..."
sleep 10

# Check logs for registration success
if journalctl -u patch-agent -n 50 --no-pager 2>/dev/null | grep -q "Registration successful\|Registered successfully\|agent_token"; then
    echo -e "${GREEN}✓${NC} Agent registration appears successful"
else
    echo -e "${YELLOW}!${NC} Cannot confirm registration from logs"
    echo "Check logs manually: journalctl -u patch-agent -n 50"
fi

# Check heartbeat
if journalctl -u patch-agent-heartbeat -n 20 --no-pager 2>/dev/null | grep -q "Heartbeat sent\|status.*ok"; then
    echo -e "${GREEN}✓${NC} Heartbeat is working"
else
    echo -e "${YELLOW}!${NC} Cannot confirm heartbeat from logs"
    echo "Check logs manually: journalctl -u patch-agent-heartbeat -n 20"
fi

echo ""
echo -e "${GREEN}=== Agent Registration Complete ===${NC}"
echo ""
echo "Agent Information:"
echo "  Hostname: $(hostname)"
echo "  IP Address: $(hostname -I | awk '{print $1}')"
echo "  Controller: ${CONTROLLER_URL}"
echo ""
echo "Service Status:"
systemctl status patch-agent --no-pager -l | head -5
echo ""
systemctl status patch-agent-heartbeat --no-pager -l | head -5
echo ""
echo "Next Steps:"
echo "  1. Check Patch-SecOps Solution UI - this host should appear in Hosts page"
echo "  2. If not visible, check server logs: ssh ${CONTROLLER_HOST} 'journalctl -u patchmaster-backend -f'"
echo "  3. Run diagnostics on server: ssh ${CONTROLLER_HOST} 'sudo bash diagnose_agent_issues.sh'"
echo ""
echo "Troubleshooting Commands:"
echo "  • View agent logs: journalctl -u patch-agent -f"
echo "  • View heartbeat logs: journalctl -u patch-agent-heartbeat -f"
echo "  • Restart agent: sudo systemctl restart patch-agent patch-agent-heartbeat"
echo "  • Test connectivity: curl ${CONTROLLER_URL}/api/health"
echo "  • Check config: cat /etc/patch-agent/env"
echo ""
