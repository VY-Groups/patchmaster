"""Helpers for Prometheus scrape target config managed by Patch-SecOps Solution."""
import json
import os
from pathlib import Path

from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models.db_models import Host

INSTALL_DIR = os.getenv("INSTALL_DIR", "/opt/patchmaster")
MONITORING_DIR = Path(os.getenv("PM_MONITORING_DIR", os.path.join(INSTALL_DIR, "monitoring")))
PROM_AGENT_SD_DIR = MONITORING_DIR / "prometheus" / "agents"
PROM_AGENT_SD_FILE = PROM_AGENT_SD_DIR / "patchmaster-agents.json"
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
AGENT_METRICS_PORT = int(os.getenv("AGENT_METRICS_PORT", "9100"))
WINDOWS_AGENT_PORT = int(os.getenv("PM_WINDOWS_AGENT_PORT", "18080"))


ALERTS_YML_PATH = os.getenv(
    "PM_PROMETHEUS_ALERTS_PATH",
    str(MONITORING_DIR / "prometheus" / "alerts.yml"),
)


def prometheus_config_text(backend_port: int = BACKEND_PORT) -> str:
    return f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - '{ALERTS_YML_PATH}'

scrape_configs:
  - job_name: 'patchmaster-backend'
    metrics_path: /metrics
    static_configs:
      - targets: ['localhost:{backend_port}']
        labels:
          instance: 'patchmaster-server'

  - job_name: 'patchmaster-agents'
    metrics_path: /metrics
    file_sd_configs:
      - files:
          - '{PROM_AGENT_SD_DIR.as_posix()}/*.json'
        refresh_interval: 60s

  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
"""


async def sync_prometheus_agent_targets(db: AsyncSession | None = None) -> list[str]:
    own_session = None
    if db is None:
        own_session = async_session()
        db = await own_session.__aenter__()

    try:
        result = await db.execute(
            select(Host.ip, Host.os, Host.os_version, Host.kernel, Host.hostname).where(
                Host.ip.is_not(None),
                Host.ip != "",
                or_(
                    Host.is_online == True,
                    Host.agent_id != "",
                    Host.agent_version != "",
                ),
            )
        )
        rows = []
        for row in result.all():
            values = tuple(row)
            if len(values) >= 5:
                ip, os_name, os_version, kernel, hostname = values[:5]
            elif len(values) >= 2:
                ip, os_name = values[:2]
                os_version = ""
                kernel = ""
                hostname = ""
            else:
                continue
            if ip and not str(ip).startswith("127."):
                rows.append(
                    (
                        str(ip),
                        str(os_name or ""),
                        str(os_version or ""),
                        str(kernel or ""),
                        str(hostname or ""),
                    )
                )
        ip_to_os: dict[str, list[str]] = defaultdict(list)
        for ip, os_name, os_version, kernel, hostname in rows:
            ip_to_os[ip].append(" ".join(part for part in (os_name, os_version, kernel, hostname) if part))

        target_entries: dict[str, dict] = {}

        def _os_label(value: str) -> str:
            lowered = (value or "").lower()
            if any(token in lowered for token in ("windows", "win32", "win64", "microsoft")):
                return "windows"
            if any(x in lowered for x in ("linux", "ubuntu", "debian", "centos", "rhel", "fedora", "rocky", "alma", "arch")):
                return "linux"
            if lowered:
                return "other"
            return "unknown"

        def _set_target(target: str, host_ip: str, host_os: str):
            target_entries[target] = {
                "targets": [target],
                "labels": {
                    "component": "agent",
                    "host_ip": host_ip,
                    "host_os": host_os,
                    "host_kind": host_os,
                },
            }

        for ip, os_list in ip_to_os.items():
            if len(os_list) <= 1:
                _set_target(f"{ip}:{AGENT_METRICS_PORT}", ip, _os_label(os_list[0] if os_list else ""))
                continue

            # Multiple agents on the same IP (e.g. Windows + WSL).
            # Both share port 9100 for metrics, so we can only emit one scrape
            # target per IP. Prefer the Windows label when Windows is present —
            # Grafana dashboards branch on host_os=windows for WSUS panels, and
            # a missed Windows label is harder to diagnose than a missed Linux one.
            # Known limitation: the Linux agent on this IP will not get its own
            # Prometheus target. Separate IPs (or a dedicated metrics port per OS)
            # are required to scrape both agents independently.
            windows_os = [name for name in os_list if "win" in (name or "").lower()]
            linux_os = [name for name in os_list if "win" not in (name or "").lower()]

            if windows_os:
                _set_target(f"{ip}:{AGENT_METRICS_PORT}", ip, "windows")
            elif linux_os:
                _set_target(f"{ip}:{AGENT_METRICS_PORT}", ip, _os_label(linux_os[0]))

        targets = sorted(target_entries.keys())
        payload = [target_entries[t] for t in targets]

        PROM_AGENT_SD_DIR.mkdir(parents=True, exist_ok=True)
        PROM_AGENT_SD_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(PROM_AGENT_SD_DIR, 0o755)
            os.chmod(PROM_AGENT_SD_FILE, 0o644)
        except OSError:
            pass
        return targets
    finally:
        if own_session is not None:
            await own_session.__aexit__(None, None, None)
