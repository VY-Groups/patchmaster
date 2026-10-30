"""
Patch-SecOps Solution — Monitoring Service Manager
Manages Prometheus and Grafana lifecycle based on license tier.
Calls monitoring-ctl.sh (via sudo) for privileged operations.
"""
import json
import logging
import os
import subprocess
from typing import Dict, Optional

logger = logging.getLogger("patchmaster.monitoring")

INSTALL_DIR = os.getenv("INSTALL_DIR", "/opt/patchmaster")
MONITORING_CTL = os.path.join(INSTALL_DIR, "backend", "scripts", "monitoring-ctl.sh")

SERVICES = {
    "prometheus": {"name": "Prometheus", "port": 9090},
    "grafana":    {"name": "Grafana",    "port": int(os.getenv("GRAFANA_PORT", "3001"))},
}


def _run_ctl(action: str, arg: str = "", timeout: int = 300) -> dict:
    """Run monitoring-ctl.sh with given action, return parsed result."""
    cmd = ["sudo", MONITORING_CTL, action]
    if arg:
        cmd.append(arg)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        stdout = result.stdout.strip()
        # Try to parse as JSON
        try:
            return {"ok": result.returncode == 0, "data": json.loads(stdout)}
        except json.JSONDecodeError:
            return {"ok": result.returncode == 0, "raw": stdout, "stderr": result.stderr.strip()}
    except FileNotFoundError:
        logger.error("monitoring-ctl.sh not found at %s", MONITORING_CTL)
        return {"ok": False, "error": f"monitoring-ctl.sh not found at {MONITORING_CTL}"}
    except subprocess.TimeoutExpired:
        logger.error("monitoring-ctl.sh timed out (action=%s)", action)
        return {"ok": False, "error": "Command timed out"}
    except Exception as e:
        logger.error("monitoring-ctl.sh failed: %s", e)
        return {"ok": False, "error": str(e)}


def get_status() -> dict:
    """Get JSON status of all monitoring services."""
    result = _run_ctl("status")
    if result.get("ok") and "data" in result:
        return result["data"]
    # Return unknown state if script failed
    return {
        k: {"installed": False, "running": False, "port": v["port"], "error": result.get("error", "unknown")}
        for k, v in SERVICES.items()
    }


def start_services(service: str = "all") -> dict:
    """Start monitoring service(s)."""
    return _run_ctl("start", service)


def stop_services(service: str = "all") -> dict:
    """Stop monitoring service(s)."""
    return _run_ctl("stop", service)


def install_services(service: str = "all") -> dict:
    """Install monitoring service(s)."""
    return _run_ctl("install", service)

def reload_dashboards() -> dict:
    """Force Grafana to reload provisioned dashboards."""
    return _run_ctl("reload-dashboards")


def restart_service(service: str) -> dict:
    """Restart a single monitoring service."""
    return _run_ctl("restart", service)


def enforce_license(features: list) -> dict:
    """Enforce monitoring state based on license features.
    If 'monitoring' in features: install (if needed) + start.
    Otherwise: stop all monitoring services.
    """
    has_monitoring = "1" if "monitoring" in features else "0"
    logger.info("Enforcing monitoring: has_feature=%s", has_monitoring)
    result = _run_ctl("enforce", has_monitoring, timeout=600)
    if result.get("ok") and "data" in result:
        return result["data"]
    return result
