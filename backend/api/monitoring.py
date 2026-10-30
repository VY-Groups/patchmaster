"""Monitoring API: service status, enforcement, install/start/stop."""
import os
import shutil
from datetime import datetime, timedelta

def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
import jwt
from jwt import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

import monitoring_manager as mm
from auth import ALGORITHM, SECRET_KEY, get_current_user, require_role
from database import get_db
from license import get_license_info
from models.db_models import AlertAction, AlertActionType, AlertTicket, AlertTicketStatus, Host, User, UserNotification, UserRole
from prometheus_targets import prometheus_config_text, sync_prometheus_agent_targets

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])
INSTALL_DIR = os.getenv("INSTALL_DIR", "/opt/patchmaster")
MONITORING_DIR = Path(os.getenv("PM_MONITORING_DIR", os.path.join(INSTALL_DIR, "monitoring")))
STATIC_MON_DIR = Path(os.getenv("PM_MONITORING_STATIC", os.path.join(INSTALL_DIR, "backend", "static", "monitoring")))
GRAFANA_PROV_DIR = MONITORING_DIR / "grafana" / "provisioning" / "datasources"
PROM_DS_FILE = GRAFANA_PROV_DIR / "patchmaster-prometheus.yml"
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "pm_token")
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "9090"))
GRAFANA_PORT = int(os.getenv("GRAFANA_PORT", "3001"))
PROMETHEUS_PROXY_PREFIX = "/api/monitoring/embed/prometheus/"
GRAFANA_PROXY_PREFIX = "/api/monitoring/embed/grafana/"
SUPPORTED_PROXY_SERVICES = {"prometheus", "grafana"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
STRIP_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-length",
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
}
SERVICE_HEALTH_PATHS = {
    "grafana": [
        f"{GRAFANA_PROXY_PREFIX}api/health",
        "/api/health",
    ],
    "prometheus": [
        f"{PROMETHEUS_PROXY_PREFIX}-/healthy",
        "/-/healthy",
    ],
}
LEGACY_SERVICE_PORTS = {
    "grafana": [3000],
    "prometheus": [],
}
CPU_ALERT_THRESHOLD = float(os.getenv("PM_ALERT_CPU_THRESHOLD", "80"))
MEMORY_ALERT_THRESHOLD = float(os.getenv("PM_ALERT_MEMORY_THRESHOLD", "80"))
DISK_IO_ALERT_THRESHOLD_BPS = float(os.getenv("PM_ALERT_DISK_IO_BPS_THRESHOLD", str(10 * 1024 * 1024)))


class AlertAckRequest(BaseModel):
    note: str = ""


class AlertTicketCreateRequest(BaseModel):
    alert_key: str
    alert_name: str
    instance: str = ""
    title: str = ""
    description: str = ""
    severity: str | None = None


class AlertActionRequest(BaseModel):
    alert_key: str
    alert_name: str
    instance: str = ""
    severity: str = "warning"
    note: str = ""


class AlertSnoozeActionRequest(AlertActionRequest):
    minutes: int = 30


def _alert_key(alert_name: str, instance: str) -> str:
    return f"{str(alert_name).strip()}::{str(instance).strip()}"


async def _get_monitoring_proxy_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
) -> User:
    resolved_token = ""
    if authorization and authorization.lower().startswith("bearer "):
        resolved_token = authorization.split(" ", 1)[1].strip()
    if not resolved_token:
        resolved_token = (request.cookies.get(AUTH_COOKIE_NAME) or "").strip()
    if not resolved_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = jwt.decode(resolved_token, SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user



def _candidate_service_bases(service: str) -> list[str]:
    if service == "grafana":
        ports = [GRAFANA_PORT, *[port for port in LEGACY_SERVICE_PORTS["grafana"] if port != GRAFANA_PORT]]
    elif service == "prometheus":
        ports = [PROMETHEUS_PORT, *[port for port in LEGACY_SERVICE_PORTS["prometheus"] if port != PROMETHEUS_PORT]]
    else:
        raise HTTPException(status_code=404, detail=f"Unsupported monitoring service '{service}'")
    return [f"http://127.0.0.1:{port}" for port in ports]


def _proxy_service_config(service: str) -> tuple[list[str], str]:
    if service == "grafana":
        return _candidate_service_bases("grafana"), GRAFANA_PROXY_PREFIX
    if service == "prometheus":
        return _candidate_service_bases("prometheus"), PROMETHEUS_PROXY_PREFIX
    raise HTTPException(status_code=404, detail=f"Unsupported monitoring service '{service}'")


def _build_upstream_service_url(base: str, public_prefix: str, path: str, query: str = "") -> str:
    normalized_public = public_prefix.rstrip("/")
    normalized_path = path.lstrip("/")
    upstream_url = f"{base}{normalized_public}/"
    if normalized_path:
        upstream_url = f"{base}{normalized_public}/{normalized_path}"
    if query:
        upstream_url = f"{upstream_url}?{query}"
    return upstream_url


def _sanitize_upstream_query(query: str) -> str:
    if not query:
        return ""
    pairs = [(key, value) for key, value in parse_qsl(query, keep_blank_values=True) if key.lower() != "token"]
    return urlencode(pairs, doseq=True)


def _response_matches_service(service: str, response: httpx.Response) -> bool:
    if response.status_code >= 400:
        return False
    if service == "grafana":
        try:
            payload = response.json()
        except ValueError:
            return False
        return isinstance(payload, dict) and (
            "database" in payload or
            ("commit" in payload and "version" in payload)
        )
    if service == "prometheus":
        body = response.text.strip()
        return "Prometheus" in body and "Healthy" in body
    return False


async def _resolve_service_base(service: str) -> tuple[str | None, int | None]:
    health_paths = SERVICE_HEALTH_PATHS.get(service, ["/"])
    for base in _candidate_service_bases(service):
        for health_path in health_paths:
            try:
                async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(5.0, connect=1.5)) as client:
                    response = await client.get(f"{base}{health_path}")
                if _response_matches_service(service, response):
                    return base, int(base.rsplit(":", 1)[1])
            except httpx.HTTPError:
                continue
    return None, None


def _parse_prometheus_vector(results: list) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in (results or []):
        metric = row.get("metric") or {}
        instance = str(metric.get("instance") or "").strip()
        if not instance:
            continue
        raw_value = row.get("value") or [None, None]
        value_text = raw_value[1] if isinstance(raw_value, list) and len(raw_value) > 1 else None
        try:
            values[instance] = float(value_text)
        except Exception:
            continue
    return values


async def _prometheus_query_instant(base: str, public_prefix: str, expr: str) -> list:
    upstream_url = _build_upstream_service_url(base, public_prefix, "api/v1/query")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=2.5), follow_redirects=False) as client:
        response = await client.get(upstream_url, params={"query": expr})
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Prometheus query failed ({response.status_code})")
    payload = response.json()
    if payload.get("status") != "success":
        raise HTTPException(status_code=502, detail="Prometheus query returned non-success status")
    return payload.get("data", {}).get("result", []) or []


async def _prometheus_active_alerts(base: str, public_prefix: str) -> list[dict]:
    upstream_url = _build_upstream_service_url(base, public_prefix, "api/v1/alerts")
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=2.5), follow_redirects=False) as client:
        response = await client.get(upstream_url)
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Prometheus alerts endpoint failed ({response.status_code})")
    payload = response.json()
    if payload.get("status") != "success":
        raise HTTPException(status_code=502, detail="Prometheus alerts endpoint returned non-success status")
    return payload.get("data", {}).get("alerts", []) or []


async def _probe_service_http(service: str, base_status: dict) -> dict:
    current = dict(base_status or {})
    current.setdefault("installed", False)
    current.setdefault("running", False)

    base, port = await _resolve_service_base(service)
    if base and port:
        current["installed"] = True
        current["running"] = True
        current["reachable"] = True
        current["port"] = port
        return current

    current["running"] = False
    current["reachable"] = False
    return current


async def _probe_service_map(services: dict) -> dict:
    probed = {}
    for name, status in (services or {}).items():
        key = name.lower().replace(".service", "")
        if key.startswith("grafana"):
            service = "grafana"
        elif key.startswith("prometheus"):
            service = "prometheus"
        else:
            probed[name] = status
            continue
        probed[name] = await _probe_service_http(service, status)
    return probed


async def _close_proxy_stream(upstream_response: httpx.Response, client: httpx.AsyncClient) -> None:
    await upstream_response.aclose()
    await client.aclose()



def _forward_request_headers(request: Request, public_prefix: str) -> dict:
    headers = {}
    for header, value in request.headers.items():
        lowered = header.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered in {"host", "content-length", "authorization"}:
            continue
        headers[header] = value
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    headers["X-Forwarded-Prefix"] = public_prefix.rstrip("/")
    return headers



def _rewrite_location(location: str, upstream_base: str, public_prefix: str) -> str:
    if not location:
        return location
    normalized_public = public_prefix.rstrip("/")
    upstream_parts = urlsplit(upstream_base)
    location_parts = urlsplit(location)

    def _join_public(path: str, query: str = "", fragment: str = "") -> str:
        rewritten = path
        if query:
            rewritten = f"{rewritten}?{query}"
        if fragment:
            rewritten = f"{rewritten}#{fragment}"
        return rewritten

    if location_parts.scheme and location_parts.netloc:
        if location_parts.path.startswith(normalized_public):
            return _join_public(location_parts.path, location_parts.query, location_parts.fragment)
        if (
            location_parts.scheme == upstream_parts.scheme and
            location_parts.netloc == upstream_parts.netloc
        ):
            suffix = location_parts.path.lstrip("/")
            rewritten_path = f"{normalized_public}/{suffix}" if suffix else f"{normalized_public}/"
            return _join_public(rewritten_path, location_parts.query, location_parts.fragment)
        return location

    if location.startswith(normalized_public):
        return location
    if location.startswith("/"):
        return f"{normalized_public}{location}"
    return f"{normalized_public}/{location.lstrip('/')}"



def _sanitize_response_headers(headers: httpx.Headers, upstream_base: str, public_prefix: str) -> dict:
    sanitized = {}
    for header, value in headers.items():
        lowered = header.lower()
        if lowered in STRIP_RESPONSE_HEADERS:
            continue
        if lowered == "location":
            sanitized[header] = _rewrite_location(value, upstream_base, public_prefix)
            continue
        sanitized[header] = value
    return sanitized


@router.get("/status")
async def monitoring_status(user: User = Depends(get_current_user)):
    """Get monitoring service status plus license feature check."""
    info = get_license_info()
    features = info.get("features", [])
    has_monitoring = "monitoring" in features
    tier = info.get("tier", "")
    tier_label = info.get("tier_label", "")

    services = mm.get_status()

    return {
        "licensed": has_monitoring,
        "tier": tier,
        "tier_label": tier_label,
        "min_tier": "standard",
        "services": services,
    }


@router.post("/enforce")
async def enforce_monitoring(user=Depends(require_role(UserRole.admin))):
    """Enforce monitoring services based on the current license."""
    info = get_license_info(force_refresh=True)
    features = info.get("features", [])
    result = mm.enforce_license(features)
    has_monitoring = "monitoring" in features
    return {
        "licensed": has_monitoring,
        "tier": info.get("tier", ""),
        "action": "started" if has_monitoring else "stopped",
        "services": result,
    }


@router.post("/install")
async def install_monitoring(user=Depends(require_role(UserRole.admin))):
    """Install all monitoring services (requires standard+ license)."""
    info = get_license_info()
    if "monitoring" not in info.get("features", []):
        raise HTTPException(
            403,
            "Monitoring requires Standard tier or above. Upgrade your license.",
        )
    result = mm.install_services("all")
    return {"action": "install", "result": result}


@router.post("/start")
async def start_monitoring(user=Depends(require_role(UserRole.admin))):
    """Start all monitoring services (requires standard+ license)."""
    info = get_license_info()
    if "monitoring" not in info.get("features", []):
        raise HTTPException(
            403,
            "Monitoring requires Standard tier or above. Upgrade your license.",
        )
    result = mm.start_services("all")
    return {"action": "start", "result": result}


@router.post("/stop")
async def stop_monitoring(user=Depends(require_role(UserRole.admin))):
    """Stop all monitoring services."""
    result = mm.stop_services("all")
    return {"action": "stop", "result": result}


@router.post("/bootstrap")
async def bootstrap_monitoring(user=Depends(require_role(UserRole.admin))):
    """Drop default Prometheus/Grafana configs and install+start services."""
    info = get_license_info()
    if "monitoring" not in info.get("features", []):
        raise HTTPException(403, "Monitoring requires Standard tier or above.")

    MONITORING_DIR.mkdir(parents=True, exist_ok=True)
    prom_path = MONITORING_DIR / "prometheus.yml"
    dash_dir = MONITORING_DIR / "dashboards"
    dash_dir.mkdir(exist_ok=True)
    GRAFANA_PROV_DIR.mkdir(parents=True, exist_ok=True)

    if STATIC_MON_DIR.is_dir():
        for item in STATIC_MON_DIR.rglob("*"):
            if item.is_file():
                rel = item.relative_to(STATIC_MON_DIR)
                dest = MONITORING_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(item, dest)
    else:
        if not prom_path.exists():
            prom_path.write_text(prometheus_config_text(), encoding="utf-8")
        dash_file = dash_dir / "patchmaster-overview.json"
        if not dash_file.exists():
            dash_file.write_text(
                '{"dashboard":{"title":"Patch-SecOps Solution Overview","panels":[]}, "overwrite": true}',
                encoding="utf-8",
            )

    import logging as _logging
    _log = _logging.getLogger("patchmaster.monitoring")
    warnings = []

    target_sync_ok = False
    try:
        from database import async_session

        async with async_session() as session:
            await sync_prometheus_agent_targets(session)
        target_sync_ok = True
    except Exception as _exc:
        _log.warning("Prometheus target sync failed during bootstrap: %s", _exc)
        warnings.append(f"target_sync: {_exc}")

    datasource_ok = False
    try:
        import yaml

        ds = {
            "apiVersion": 1,
            "datasources": [
                {
                    "uid": "patchmaster-prometheus",
                    "name": "Patch-SecOps Solution Prometheus",
                    "type": "prometheus",
                    "access": "proxy",
                    "url": f"http://localhost:{PROMETHEUS_PORT}{PROMETHEUS_PROXY_PREFIX.rstrip('/')}",
                    "isDefault": True,
                    "editable": True,
                }
            ],
        }
        PROM_DS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROM_DS_FILE.write_text(yaml.safe_dump(ds, sort_keys=False))
        datasource_ok = True
    except Exception as _exc:
        _log.warning("Grafana datasource provisioning failed during bootstrap: %s", _exc)
        warnings.append(f"datasource_provision: {_exc}")

    install_result = mm.install_services("all")
    start_result = mm.start_services("all")
    reload_ok = False
    try:
        mm.restart_service("prometheus")
        mm.restart_service("grafana")
        mm.reload_dashboards()
        reload_ok = True
    except Exception as _exc:
        _log.warning("Service reload failed during bootstrap: %s", _exc)
        warnings.append(f"service_reload: {_exc}")

    status = mm.get_status()
    return {
        "installed": install_result,
        "started": start_result,
        "status": status,
        "target_sync_ok": target_sync_ok,
        "datasource_ok": datasource_ok,
        "reload_ok": reload_ok,
        "warnings": warnings,
    }


@router.get("/health")
async def monitoring_health(user: User = Depends(get_current_user)):
    """Lightweight health endpoint the UI can poll after bootstrap."""
    status = await _probe_service_map(mm.get_status())
    return {"services": status}


@router.get("/alerts/active")
async def monitoring_active_alerts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    info = get_license_info()
    if "monitoring" not in info.get("features", []):
        raise HTTPException(status_code=403, detail="Monitoring requires a licensed tier with monitoring enabled")

    base, _ = await _resolve_service_base("prometheus")
    if not base:
        raise HTTPException(status_code=503, detail="Prometheus service is not reachable")
    _, public_prefix = _proxy_service_config("prometheus")

    alerts_payload = await _prometheus_active_alerts(base, public_prefix)
    cpu_map = _parse_prometheus_vector(await _prometheus_query_instant(base, public_prefix, "max by(instance) (system_cpu_usage_percent{job=\"patchmaster-agents\"})"))
    mem_map = _parse_prometheus_vector(await _prometheus_query_instant(base, public_prefix, "max by(instance) (system_memory_usage_percent{job=\"patchmaster-agents\"})"))
    io_map = _parse_prometheus_vector(
        await _prometheus_query_instant(
            base,
            public_prefix,
            "max by(instance) (system_disk_read_bytes_per_sec{job=\"patchmaster-agents\"} + system_disk_write_bytes_per_sec{job=\"patchmaster-agents\"})",
        )
    )
    up_map = _parse_prometheus_vector(await _prometheus_query_instant(base, public_prefix, "max by(instance) (up{job=\"patchmaster-agents\"})"))
    offline_total_rows = await _prometheus_query_instant(base, public_prefix, "(patchmaster_hosts_total - patchmaster_hosts_online)")
    offline_total = 0.0
    if offline_total_rows:
        raw_value = offline_total_rows[0].get("value") or [None, "0"]
        try:
            offline_total = float(raw_value[1] if isinstance(raw_value, list) and len(raw_value) > 1 else 0)
        except Exception:
            offline_total = 0.0

    instances = sorted(set(cpu_map.keys()) | set(mem_map.keys()) | set(io_map.keys()) | set(up_map.keys()))
    host_matrix = []
    for instance in instances:
        cpu = float(cpu_map.get(instance, 0.0))
        mem = float(mem_map.get(instance, 0.0))
        io_bps = float(io_map.get(instance, 0.0))
        online = float(up_map.get(instance, 0.0)) >= 1.0
        host_matrix.append(
            {
                "instance": instance,
                "cpu_percent": round(cpu, 2),
                "memory_percent": round(mem, 2),
                "disk_io_bps": round(io_bps, 2),
                "online": online,
                "cpu_alert": cpu >= CPU_ALERT_THRESHOLD,
                "memory_alert": mem >= MEMORY_ALERT_THRESHOLD,
                "disk_io_alert": io_bps >= DISK_IO_ALERT_THRESHOLD_BPS,
                "offline_alert": not online,
            }
        )

    active_alerts = []
    critical = 0
    warning = 0
    action_map: dict[str, AlertAction] = {}
    notified_keys: set[str] = set()
    ticket_count_by_key: dict[str, int] = {}
    alert_keys = []
    for raw in alerts_payload:
        labels = raw.get("labels") or {}
        alert_keys.append(_alert_key(labels.get("alertname", ""), labels.get("instance", "")))
    if alert_keys:
        action_rows = (
            await db.execute(
                select(AlertAction)
                .where(AlertAction.alert_key.in_(alert_keys))
                .order_by(desc(AlertAction.created_at))
            )
        ).scalars().all()
        for row in action_rows:
            if row.alert_key not in action_map:
                action_map[row.alert_key] = row
            if row.action_type == AlertActionType.notify:
                notified_keys.add(row.alert_key)
        ticket_rows = (
            await db.execute(
                select(AlertTicket).where(AlertTicket.alert_key.in_(alert_keys))
            )
        ).scalars().all()
        for ticket in ticket_rows:
            ticket_count_by_key[ticket.alert_key] = ticket_count_by_key.get(ticket.alert_key, 0) + 1
    for alert in alerts_payload:
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        severity = str(labels.get("severity", "")).lower()
        name = labels.get("alertname", "")
        instance = labels.get("instance", "")
        akey = _alert_key(name, instance)
        last_action = action_map.get(akey)
        snoozed_until = last_action.snooze_until if last_action and last_action.snooze_until else None
        snooze_active = bool(snoozed_until and snoozed_until > _utcnow() and last_action and last_action.action_type == AlertActionType.snooze)
        snooze_remaining_seconds = int(max((snoozed_until - _utcnow()).total_seconds(), 0)) if snoozed_until else 0
        acknowledged = bool(last_action and last_action.action_type in {AlertActionType.acknowledge, AlertActionType.snooze})
        if severity == "critical":
            critical += 1
        elif severity == "warning":
            warning += 1
        active_alerts.append(
            {
                "key": akey,
                "name": name,
                "state": alert.get("state", ""),
                "severity": severity or "unknown",
                "instance": instance,
                "summary": annotations.get("summary", ""),
                "description": annotations.get("description", ""),
                "starts_at": alert.get("activeAt", ""),
                "acknowledged": acknowledged,
                "snooze_active": snooze_active,
                "snooze_remaining_seconds": snooze_remaining_seconds,
                "last_action_type": last_action.action_type.value if last_action and hasattr(last_action.action_type, "value") else (str(last_action.action_type) if last_action else ""),
                "last_action_note": last_action.note if last_action else "",
                "last_action_at": (last_action.created_at.isoformat() + "Z") if last_action and last_action.created_at else "",
                "snoozed_until": (snoozed_until.isoformat() + "Z") if snoozed_until else None,
                "ticket_count": int(ticket_count_by_key.get(akey, 0)),
                "labels": labels,
            }
        )
        if severity == "critical" and akey not in notified_keys:
            db.add(
                UserNotification(
                    user_id=None,
                    type="alert",
                    title=f"Critical alert: {name}",
                    message=annotations.get("summary", "") or annotations.get("description", "") or f"Critical alert on {instance or 'cluster'}",
                    link="/alerts-center",
                    is_read=False,
                )
            )
            db.add(
                AlertAction(
                    alert_key=akey,
                    alert_name=name,
                    instance=instance,
                    severity="critical",
                    action_type=AlertActionType.notify,
                    note="auto_notification_created",
                    created_by="system",
                )
            )
            notified_keys.add(akey)
    await db.commit()

    return {
        "active_alerts": active_alerts,
        "host_matrix": host_matrix,
        "thresholds": {
            "cpu_percent": CPU_ALERT_THRESHOLD,
            "memory_percent": MEMORY_ALERT_THRESHOLD,
            "disk_io_bps": DISK_IO_ALERT_THRESHOLD_BPS,
        },
        "summary": {
            "active_alerts_total": len(active_alerts),
            "critical_alerts": critical,
            "warning_alerts": warning,
            "hosts_in_matrix": len(host_matrix),
            "high_cpu_hosts": sum(1 for row in host_matrix if row["cpu_alert"]),
            "high_memory_hosts": sum(1 for row in host_matrix if row["memory_alert"]),
            "high_disk_io_hosts": sum(1 for row in host_matrix if row["disk_io_alert"]),
            "offline_hosts": max(int(round(offline_total)), sum(1 for row in host_matrix if row["offline_alert"])),
            "last_refreshed_at": _utcnow().isoformat() + "Z",
        },
    }


@router.post("/alerts/ack")
async def ack_alert(
    body: AlertActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    action = AlertAction(
        alert_key=body.alert_key.strip(),
        alert_name=body.alert_name.strip(),
        instance=body.instance.strip(),
        severity=(body.severity or "warning").strip().lower(),
        action_type=AlertActionType.acknowledge,
        note=body.note.strip(),
        created_by=getattr(user, "username", "system"),
    )
    db.add(action)
    await db.commit()
    return {"status": "ok", "action_id": action.id}


@router.post("/alerts/snooze")
async def snooze_alert(
    body: AlertSnoozeActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    minutes = max(int(body.minutes or 30), 1)
    action = AlertAction(
        alert_key=body.alert_key.strip(),
        alert_name=body.alert_name.strip(),
        instance=body.instance.strip(),
        severity=(body.severity or "warning").strip().lower(),
        action_type=AlertActionType.snooze,
        note=body.note.strip(),
        snooze_until=_utcnow() + timedelta(minutes=minutes),
        created_by=getattr(user, "username", "system"),
    )
    db.add(action)
    await db.commit()
    return {"status": "ok", "action_id": action.id, "snooze_until": action.snooze_until.isoformat() + "Z"}


@router.post("/alerts/unsnooze")
async def unsnooze_alert(
    body: AlertActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    action = AlertAction(
        alert_key=body.alert_key.strip(),
        alert_name=body.alert_name.strip(),
        instance=body.instance.strip(),
        severity=(body.severity or "warning").strip().lower(),
        action_type=AlertActionType.unsnooze,
        note=body.note.strip(),
        created_by=getattr(user, "username", "system"),
    )
    db.add(action)
    await db.commit()
    return {"status": "ok", "action_id": action.id}


@router.post("/alerts/tickets")
async def create_alert_ticket(
    body: AlertTicketCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    title = body.title.strip() or f"[{(body.severity or 'warning').upper()}] {body.alert_name.strip()} @ {body.instance.strip() or 'global'}"
    ticket = AlertTicket(
        alert_key=body.alert_key.strip(),
        alert_name=body.alert_name.strip(),
        instance=body.instance.strip(),
        severity=(body.severity or "warning").strip().lower(),
        title=title,
        description=body.description.strip(),
        status=AlertTicketStatus.open,
        created_by=getattr(user, "username", "system"),
    )
    db.add(ticket)
    await db.flush()
    action = AlertAction(
        alert_key=ticket.alert_key,
        alert_name=ticket.alert_name,
        instance=ticket.instance,
        severity=ticket.severity,
        action_type=AlertActionType.ticket_create,
        note=f"ticket_id={ticket.id}",
        ticket_id=ticket.id,
        created_by=getattr(user, "username", "system"),
    )
    db.add(action)
    await db.commit()
    return {
        "status": "ok",
        "ticket": {
            "id": ticket.id,
            "title": ticket.title,
            "severity": ticket.severity,
            "status": ticket.status.value if hasattr(ticket.status, "value") else str(ticket.status),
            "created_at": ticket.created_at.isoformat() + "Z" if ticket.created_at else None,
        },
    }


@router.get("/alerts/tickets")
async def list_alert_tickets(
    limit: int = Query(100, ge=1, le=500),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    stmt = select(AlertTicket).order_by(desc(AlertTicket.created_at)).limit(limit)
    if status:
        wanted = status.strip().lower()
        if wanted in {"open", "closed"}:
            stmt = stmt.where(AlertTicket.status == AlertTicketStatus(wanted))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": row.id,
            "alert_key": row.alert_key,
            "alert_name": row.alert_name,
            "instance": row.instance,
            "severity": row.severity,
            "title": row.title,
            "description": row.description,
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "external_ref": row.external_ref,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
            "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        }
        for row in rows
    ]


@router.post("/alerts/tickets/{ticket_id}/close")
async def close_alert_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    ticket = await db.get(AlertTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Alert ticket not found")
    ticket.status = AlertTicketStatus.closed
    ticket.updated_at = _utcnow()
    db.add(ticket)
    await db.commit()
    return {"status": "ok", "ticket_id": ticket.id, "ticket_status": "closed"}


@router.post("/alerts/tickets/{ticket_id}/reopen")
async def reopen_alert_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    ticket = await db.get(AlertTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Alert ticket not found")
    ticket.status = AlertTicketStatus.open
    ticket.updated_at = _utcnow()
    db.add(ticket)
    await db.commit()
    return {"status": "ok", "ticket_id": ticket.id, "ticket_status": "open"}


@router.api_route("/embed/{service}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@router.api_route("/embed/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def monitoring_embed_proxy(
    service: str,
    request: Request,
    path: str = "",
    user: User = Depends(_get_monitoring_proxy_user),
):
    service_key = service.lower().strip()
    if service_key not in SUPPORTED_PROXY_SERVICES:
        raise HTTPException(status_code=404, detail=f"Unsupported monitoring service '{service}'")

    info = get_license_info()
    if "monitoring" not in info.get("features", []):
        raise HTTPException(status_code=403, detail="Monitoring requires a licensed tier with monitoring enabled")

    request_body = None if request.method in {"GET", "HEAD"} else await request.body()
    upstream_bases, public_prefix = _proxy_service_config(service_key)
    normalized_path = path.lstrip("/")

    resolved_base, _ = await _resolve_service_base(service_key)
    if resolved_base:
        upstream_bases = [resolved_base]

    last_exc: Exception | None = None
    upstream_response = None
    upstream_base = upstream_bases[0]
    headers = _forward_request_headers(request, public_prefix)
    client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(60.0, connect=2.5))
    for candidate_base in upstream_bases:
        upstream_base = candidate_base
        upstream_url = _build_upstream_service_url(
            candidate_base,
            public_prefix,
            normalized_path,
            _sanitize_upstream_query(request.url.query),
        )
        try:
            upstream_request = client.build_request(
                request.method,
                upstream_url,
                headers=headers,
                content=request_body,
            )
            upstream_response = await client.send(upstream_request, stream=True)
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            continue

    if upstream_response is None:
        await client.aclose()
        raise HTTPException(
            status_code=502,
            detail=f"{service_key.title()} is unavailable. Confirm the monitoring stack is running.",
        ) from last_exc

    response_headers = _sanitize_response_headers(upstream_response.headers, upstream_base, public_prefix)
    if request.method == "HEAD":
        await _close_proxy_stream(upstream_response, client)
        return Response(status_code=upstream_response.status_code, headers=response_headers)

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        background=BackgroundTask(_close_proxy_stream, upstream_response, client),
    )
