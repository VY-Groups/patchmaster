#!/bin/bash
# Patch-SecOps Solution 2.0.1 Deployment Script
# Deploy to Ubuntu server at 172.24.1.254
set -e

SERVER="172.24.1.254"
PACKAGE="dist/patchmaster-2.0.1.tar.gz"

echo "=== Patch-SecOps Solution 2.0.1 Deployment ==="
echo ""
echo "This will deploy to: $SERVER"
echo "Package: $PACKAGE"
echo ""

# Check if package exists
if [[ ! -f "$PACKAGE" ]]; then
    echo "ERROR: Package not found: $PACKAGE"
    echo "Run: cd packaging && bash build-package.sh"
    exit 1
fi

echo "Step 1: Copy package to server..."
scp "$PACKAGE" "root@${SERVER}:/tmp/"

echo ""
echo "Step 2: Extract and install on server..."
ssh "root@${SERVER}" bash <<'REMOTE'
set -e
cd /tmp
tar -xzf patchmaster-2.0.1.tar.gz
cd /tmp
bash packaging/install-bare.sh
REMOTE

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Access Patch-SecOps Solution at: http://${SERVER}:3000"
echo "2. Deploy agent to agent machine:"
echo "   curl -fsSL -o agent-latest.deb http://${SERVER}:3000/download/agent-latest.deb"
echo "   sudo dpkg -i agent-latest.deb"
echo "   echo 'CONTROLLER_URL=http://${SERVER}:8000' | sudo tee /etc/patch-agent/env"
echo "   sudo systemctl restart patch-agent patch-agent-heartbeat"
echo ""
