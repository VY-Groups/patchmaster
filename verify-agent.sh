#!/bin/bash
# Verify Patch-SecOps Solution Agent Installation
# Run this on the agent machine after installation

echo "=== Patch-SecOps Solution Agent Verification ==="
echo ""

# Check if agent is installed
if [[ ! -d /opt/patch-agent ]]; then
    echo "❌ Agent not installed at /opt/patch-agent"
    exit 1
fi
echo "✅ Agent directory exists"

# Check virtualenv
if [[ ! -f /opt/patch-agent/venv/bin/python3 ]]; then
    echo "❌ Python virtualenv not found"
    exit 1
fi
echo "✅ Python virtualenv exists"

# Check Python dependencies
echo ""
echo "Checking Python dependencies..."
MISSING=""
for pkg in yaml requests flask psutil prometheus_client; do
    if /opt/patch-agent/venv/bin/python3 -c "import $pkg" 2>/dev/null; then
        echo "  ✅ $pkg"
    else
        echo "  ❌ $pkg - MISSING"
        MISSING="$MISSING $pkg"
    fi
done

if [[ -n "$MISSING" ]]; then
    echo ""
    echo "❌ Missing dependencies:$MISSING"
    echo "Fix: sudo /opt/patch-agent/venv/bin/pip install$MISSING"
    exit 1
fi

# Check configuration
echo ""
if [[ -f /etc/patch-agent/env ]]; then
    echo "✅ Configuration file exists"
    echo "   $(cat /etc/patch-agent/env)"
else
    echo "⚠️  Configuration file missing"
    echo "   Create: echo 'CONTROLLER_URL=http://172.24.1.254:8000' | sudo tee /etc/patch-agent/env"
fi

# Check services
echo ""
echo "Checking services..."
for svc in patch-agent patch-agent-heartbeat; do
    if systemctl is-active --quiet $svc; then
        echo "  ✅ $svc is running"
    else
        echo "  ❌ $svc is NOT running"
        echo "     Status: $(systemctl is-active $svc)"
        echo "     Start: sudo systemctl start $svc"
    fi
done

# Check recent logs
echo ""
echo "Recent agent logs (last 5 lines):"
journalctl -u patch-agent -n 5 --no-pager 2>/dev/null || echo "  (no logs available)"

echo ""
echo "Recent heartbeat logs (last 5 lines):"
journalctl -u patch-agent-heartbeat -n 5 --no-pager 2>/dev/null || echo "  (no logs available)"

echo ""
echo "=== Verification Complete ==="
