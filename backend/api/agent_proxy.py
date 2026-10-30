"""Backend proxy API — forwards commands from UI to agent machines."""

import httpx
import os
import re
import tempfile
import shutil
import logging
import asyncio
from datetime import datetime


def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


from urllib.parse import urlsplit
from fastapi import (
    APIRouter,
    HTTPException,
    UploadFile,
    File,
    Form,
    Depends,
    BackgroundTasks,
)
from fastapi.responses import StreamingResponse
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db, async_session
from auth import get_current_user, require_role
from license import get_license_info
from models.db_models import Host, PatchJob, JobStatus, PatchAction, User, UserRole

router = APIRouter(prefix="/api/agent", tags=["agent-proxy"])

AGENT_PORT = 8080
WINDOWS_AGENT_PORT = int(os.getenv("PM_WINDOWS_AGENT_PORT", "18080"))
# Linux agents always run on 8080 regardless of whether a Windows agent shares the IP.
# The env var allows override for non-standard deployments only.
LINUX_SAME_IP_AGENT_PORT = int(os.getenv("PM_LINUX_AGENT_PORT_SAME_IP", "8080"))
TIMEOUT = 30.0
logger = logging.getLogger("agent-proxy")
PM_WINDOWS_WBADMIN_TARGET = (
    os.getenv("PM_WINDOWS_WBADMIN_TARGET") or os.getenv("WBADMIN_BACKUP_TARGET") or ""
).strip()
PM_WINDOWS_WBADMIN_SMB_HOST = (os.getenv("PM_WINDOWS_WBADMIN_SMB_HOST") or "").strip()
PM_WINDOWS_WBADMIN_SHARE_NAME = (
    (os.getenv("PM_WINDOWS_WBADMIN_SHARE_NAME") or "patchmaster-wbadmin")
    .strip()
    .strip("\\/")
)
LOCAL_REPO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "packages"
)

# Agent API token — per-host, looked up from host.agent_token in the DB.
# Falls back to the global AGENT_API_TOKEN env var for hosts that haven't
# registered yet or for legacy deployments.
_GLOBAL_AGENT_API_TOKEN = os.environ.get("AGENT_API_TOKEN", "").strip()


def _agent_auth_headers(host: "Host | None" = None) -> dict:
    """Return Authorization header for a backend→agent call.

    Preference order:
      1. host.agent_token from DB (per-host, set at registration)
      2. AGENT_API_TOKEN env var (global override / legacy)
    """
    token = ""
    if host is not None:
        token = (getattr(host, "agent_token", None) or "").strip()
    if not token:
        token = _GLOBAL_AGENT_API_TOKEN
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


# IPv4 and IPv6 pattern - supports both formats
_IPV4_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_IPV6_PATTERN = re.compile(
    r"^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|^::1$|^(([0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4})?::([0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}$|^([0-9a-fA-F]{1,4}:){1,7}:$"
)


def _is_valid_ip(ip: str) -> bool:
    """Check if string is a valid IPv4 or IPv6 address."""
    return bool(_IPV4_PATTERN.match(ip) or _IPV6_PATTERN.match(ip))


async def _validate_host_ip(ip: str, db: AsyncSession):
    """Validate that the IP is a registered host to prevent SSRF."""
    if not _is_valid_ip(ip):
        raise HTTPException(400, f"Invalid IP format: {ip}")
    result = await db.execute(select(Host).where(Host.ip == ip))
    if not result.scalars().first():
        raise HTTPException(404, f"Host {ip} is not registered")


def _agent_url(ip: str, path: str) -> str:
    return f"http://{ip}:{AGENT_PORT}{path}"


def _agent_url_with_port(ip: str, port: int, path: str) -> str:
    return f"http://{ip}:{port}{path}"


def _windows_candidate_ports() -> list[int]:
    raw = (os.getenv("PM_WINDOWS_AGENT_PORTS") or "").strip()
    if raw:
        ports = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ports.append(int(part))
            except Exception:
                continue
        if ports:
            return list(dict.fromkeys(ports))
    return list(dict.fromkeys([WINDOWS_AGENT_PORT, 8080]))


async def _candidate_agent_urls(
    ip: str, path: str, db: AsyncSession | None = None
) -> list[str]:
    if not db:
        return [_agent_url(ip, path)]
    result = await db.execute(select(Host).where(Host.ip == ip))
    host = result.scalars().first()
    if not host:
        return [_agent_url(ip, path)]
    os_name = (host.os or "").lower()
    if "win" in os_name:
        return [_agent_url_with_port(ip, p, path) for p in _windows_candidate_ports()]
    port = await _resolve_host_agent_port(host, db)
    return [_agent_url_with_port(ip, port, path)]


async def _resolve_host_agent_port(host: Host, db: AsyncSession) -> int:
    os_name = (host.os or "").lower()
    if "win" in os_name:
        return WINDOWS_AGENT_PORT
    same_ip_hosts = (await db.scalars(select(Host).where(Host.ip == host.ip))).all()
    has_windows_peer = any("win" in ((h.os or "").lower()) for h in same_ip_hosts)
    if has_windows_peer:
        return LINUX_SAME_IP_AGENT_PORT
    return AGENT_PORT


async def _agent_url_for_host_id(
    host_id: int, path: str, db: AsyncSession
) -> tuple[Host, str]:
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(404, f"Host id {host_id} not found")
    port = await _resolve_host_agent_port(host, db)
    return host, _agent_url_with_port(host.ip, port, path)


def _default_windows_backup_target(host: Host) -> str:
    if PM_WINDOWS_WBADMIN_TARGET:
        return PM_WINDOWS_WBADMIN_TARGET
    smb_host = PM_WINDOWS_WBADMIN_SMB_HOST
    if not smb_host:
        return ""
    share = PM_WINDOWS_WBADMIN_SHARE_NAME or "patchmaster-wbadmin"
    return f"\\\\{smb_host}\\{share}"


def _enrich_snapshot_body_for_windows(host: Host, body: dict | None) -> dict:
    payload = dict(body or {})
    mode = str(payload.get("mode") or "").strip().lower()
    os_name = (host.os or "").lower()
    backup_target = payload.get("backup_target")
    if (
        mode == "full_system"
        and "win" in os_name
        and (not isinstance(backup_target, str) or not backup_target.strip())
    ):
        default_target = _default_windows_backup_target(host)
        if default_target:
            payload["backup_target"] = default_target
    return payload


async def _get(ip: str, path: str, db: AsyncSession, host: "Host | None" = None):
    await _validate_host_ip(ip, db)
    if host is None:
        result = await db.execute(select(Host).where(Host.ip == ip))
        host = result.scalars().first()
    urls = await _candidate_agent_urls(ip, path, db)
    last_error = None
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for url in urls:
            try:
                r = await c.get(url, headers=_agent_auth_headers(host))
                if r.status_code >= 400:
                    last_error = f"{url} status={r.status_code}"
                    continue
                return r.json()
            except Exception as e:
                last_error = str(e)
                continue
    raise HTTPException(
        502, f"Agent {ip} unreachable: {last_error or 'all candidate ports failed'}"
    )


async def _get_stream(ip: str, path: str, db: AsyncSession, host: "Host | None" = None):
    await _validate_host_ip(ip, db)
    if host is None:
        result = await db.execute(select(Host).where(Host.ip == ip))
        host = result.scalars().first()
    urls = await _candidate_agent_urls(ip, path, db)
    last_error = None
    async with httpx.AsyncClient(timeout=None) as c:
        for url in urls:
            try:
                r = await c.get(
                    url, follow_redirects=True, headers=_agent_auth_headers(host)
                )
                if r.status_code >= 400:
                    last_error = f"{url} status={r.status_code}"
                    continue
                headers = {}
                cd = r.headers.get("content-disposition")
                if cd:
                    headers["Content-Disposition"] = cd
                return StreamingResponse(
                    r.aiter_bytes(),
                    media_type=r.headers.get(
                        "content-type", "application/octet-stream"
                    ),
                    headers=headers,
                )
            except Exception as e:
                last_error = str(e)
                continue
    raise HTTPException(
        502, f"Agent {ip} unreachable: {last_error or 'all candidate ports failed'}"
    )


async def _post(
    ip: str,
    path: str,
    json_body: dict | None = None,
    db: AsyncSession = None,
    host: "Host | None" = None,
):
    if db:
        await _validate_host_ip(ip, db)
    if host is None and db is not None:
        result = await db.execute(select(Host).where(Host.ip == ip))
        host = result.scalars().first()
    urls = await _candidate_agent_urls(ip, path, db)
    last_error = None
    async with httpx.AsyncClient(timeout=120.0) as c:
        for url in urls:
            try:
                r = await c.post(
                    url, json=json_body or {}, headers=_agent_auth_headers(host)
                )
                if r.status_code >= 400:
                    last_error = f"{url} status={r.status_code}"
                    continue
                return r.json()
            except Exception as e:
                last_error = str(e)
                continue
    raise HTTPException(
        502, f"Agent {ip} unreachable: {last_error or 'all candidate ports failed'}"
    )


@router.post("/{host_ip}/system/reboot")
async def reboot_host(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    return await _post(host_ip, "/system/reboot", {})


@router.post("/{host_ip}/system/shutdown")
async def shutdown_host(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    return await _post(host_ip, "/system/shutdown", {})


@router.post("/{host_ip}/software/manage")
async def software_manage(
    host_ip: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    return await _post(host_ip, "/software/manage", body)


@router.get("/{host_ip}/software/queue")
async def software_queue(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _validate_host_ip(host_ip, db)
    return await _get(host_ip, "/software/queue", db)


@router.post("/{host_ip}/software/queue")
async def queue_software_for_shutdown(
    host_ip: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    return await _post(host_ip, "/software/queue", body, db)


# --- Package info ---
@router.get("/{host_ip}/packages/installed")
async def proxy_installed(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/packages/installed", db)


@router.get("/{host_ip}/packages/upgradable")
async def proxy_upgradable(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/packages/upgradable", db)


@router.post("/{host_ip}/packages/refresh")
async def proxy_refresh(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/packages/refresh", db=db)


# --- Snapshots ---
@router.get("/{host_ip}/snapshot/list")
async def proxy_snap_list(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/snapshot/list", db)


@router.post("/{host_ip}/snapshot/create")
async def proxy_snap_create(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    result = await db.execute(select(Host).where(Host.ip == host_ip))
    host = result.scalars().first()
    payload = (
        _enrich_snapshot_body_for_windows(host, body) if host else dict(body or {})
    )
    return await _post(host_ip, "/snapshot/create", payload, db)


@router.post("/{host_ip}/snapshot/precheck")
async def proxy_snap_precheck(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    result = await db.execute(select(Host).where(Host.ip == host_ip))
    host = result.scalars().first()
    payload = (
        _enrich_snapshot_body_for_windows(host, body) if host else dict(body or {})
    )
    return await _post(host_ip, "/snapshot/precheck", payload, db)


@router.post("/{host_ip}/snapshot/rollback")
async def proxy_snap_rollback(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/snapshot/rollback", body, db)


@router.post("/{host_ip}/snapshot/delete")
async def proxy_snap_delete(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/snapshot/delete", body, db)


@router.get("/{host_ip}/snapshot/archive/{name}")
async def proxy_snap_archive(
    host_ip: str,
    name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    safe_name = name.replace("..", "").replace("/", "")
    return await _get_stream(host_ip, f"/snapshot/archive/{safe_name}", db)


@router.post("/{host_ip}/snapshot/restore-url")
async def proxy_snap_restore_url(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/snapshot/restore_url", body, db)


@router.post("/{host_ip}/snapshot/restore-upload")
async def proxy_snap_restore_upload(
    host_ip: str,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _validate_host_ip(host_ip, db)
    try:
        upload_host_result = await db.execute(select(Host).where(Host.ip == host_ip))
        upload_host = upload_host_result.scalar_one_or_none()
        urls = await _candidate_agent_urls(host_ip, "/snapshot/restore_upload", db)
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            files = {
                "file": (
                    file.filename,
                    await file.read(),
                    file.content_type or "application/zip",
                )
            }
            data = {}
            if name:
                data["name"] = name
            last_error = ""
            for url in urls:
                r = await c.post(
                    url,
                    files=files,
                    data=data,
                    headers=_agent_auth_headers(upload_host),
                )
                if r.status_code < 400:
                    return r.json()
                last_error = f"{url} status={r.status_code}"
            raise HTTPException(
                502,
                f"Agent {host_ip} unreachable: {last_error or 'all candidate ports failed'}",
            )
    except Exception as e:
        raise HTTPException(502, f"Agent {host_ip} unreachable: {e}")


@router.post("/{host_ip}/cleanup")
async def proxy_cleanup(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/cleanup", body, db)


@router.get("/by-host/{host_id}/snapshot/list")
async def proxy_snap_list_by_host(
    host_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/list", db)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(url, headers=_agent_auth_headers(_host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/snapshot/create")
async def proxy_snap_create_by_host(
    host_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    host, url = await _agent_url_for_host_id(host_id, "/snapshot/create", db)
    payload = _enrich_snapshot_body_for_windows(host, body)
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=payload, headers=_agent_auth_headers(host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/snapshot/precheck")
async def proxy_snap_precheck_by_host(
    host_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    host, url = await _agent_url_for_host_id(host_id, "/snapshot/precheck", db)
    payload = _enrich_snapshot_body_for_windows(host, body)
    try:
        async with httpx.AsyncClient(timeout=45.0) as c:
            r = await c.post(url, json=payload, headers=_agent_auth_headers(host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/snapshot/rollback")
async def proxy_snap_rollback_by_host(
    host_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/rollback", db)
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=body or {}, headers=_agent_auth_headers(_host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/snapshot/delete")
async def proxy_snap_delete_by_host(
    host_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/delete", db)
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=body or {}, headers=_agent_auth_headers(_host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.get("/by-host/{host_id}/snapshot/archive/{name}")
async def proxy_snap_archive_by_host(
    host_id: int,
    name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _host, base_url = await _agent_url_for_host_id(host_id, "/snapshot/archive/", db)
    safe_name = name.replace("..", "").replace("/", "")
    try:
        async with httpx.AsyncClient(timeout=None) as c:
            r = await c.get(
                f"{base_url}{safe_name}",
                follow_redirects=True,
                headers=_agent_auth_headers(_host),
            )
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
            headers = {}
            cd = r.headers.get("content-disposition")
            if cd:
                headers["Content-Disposition"] = cd
            return StreamingResponse(
                r.aiter_bytes(),
                media_type=r.headers.get("content-type", "application/octet-stream"),
                headers=headers,
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/snapshot/restore-url")
async def proxy_snap_restore_url_by_host(
    host_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/restore_url", db)
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=body or {}, headers=_agent_auth_headers(_host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/snapshot/restore-upload")
async def proxy_snap_restore_upload_by_host(
    host_id: int,
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/restore_upload", db)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            files = {
                "file": (
                    file.filename,
                    await file.read(),
                    file.content_type or "application/zip",
                )
            }
            data = {}
            if name:
                data["name"] = name
            r = await c.post(
                url, files=files, data=data, headers=_agent_auth_headers(_host)
            )
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/cleanup")
async def proxy_cleanup_by_host(
    host_id: int,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _host, url = await _agent_url_for_host_id(host_id, "/cleanup", db)
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(url, json=body or {}, headers=_agent_auth_headers(_host))
            return r.json()
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/clone-snapshot")
async def proxy_clone_snapshot(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    source_ip = body.get("source_ip")
    target_ip = body.get("target_ip")
    name = body.get("name")
    if not (source_ip and target_ip and name):
        raise HTTPException(400, "source_ip, target_ip, name required")
    await _validate_host_ip(source_ip, db)
    await _validate_host_ip(target_ip, db)
    # Download archive from source to temp file, then upload to target
    import tempfile, os

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    try:
        src_result = await db.execute(select(Host).where(Host.ip == source_ip))
        src_host = src_result.scalar_one_or_none()
        dst_result = await db.execute(select(Host).where(Host.ip == target_ip))
        dst_host = dst_result.scalar_one_or_none()
        async with httpx.AsyncClient(timeout=None) as c:
            src_urls = await _candidate_agent_urls(
                source_ip, f"/snapshot/archive/{name}", db
            )
            resp = None
            for src_url in src_urls:
                check = await c.get(src_url, headers=_agent_auth_headers(src_host))
                if check.status_code < 400:
                    resp = check
                    break
            if resp is None:
                raise HTTPException(
                    502, f"Source host {source_ip} unreachable on candidate ports"
                )
            if resp.status_code >= 400:
                raise HTTPException(
                    resp.status_code, f"Source archive failed: {resp.text}"
                )
            with open(tmp_path, "wb") as f:
                f.write(resp.content)
            files = {"file": (f"{name}.zip", open(tmp_path, "rb"), "application/zip")}
            data = {"name": name}
            dest_urls = await _candidate_agent_urls(
                target_ip, "/snapshot/restore_upload", db
            )
            last_error = ""
            for dest_url in dest_urls:
                resp2 = await c.post(
                    dest_url,
                    files=files,
                    data=data,
                    headers=_agent_auth_headers(dst_host),
                )
                if resp2.status_code < 400:
                    return resp2.json()
                last_error = f"{dest_url} status={resp2.status_code}"
            raise HTTPException(
                502,
                f"Target host {target_ip} restore upload failed: {last_error or 'all candidate ports failed'}",
            )
    finally:
        try:
            os.remove(tmp_path)
        except OSError as e:
            # File may have already been deleted or is in use
            pass


# --- Patch execution ---
@router.post("/{host_ip}/patch/execute")
async def proxy_patch(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _ensure_patch_license(host_ip, db)
    return await _post(host_ip, "/patch/execute", body, db)


# --- Offline ---
@router.get("/{host_ip}/offline/list")
async def proxy_offline_list(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/offline/list", db)


@router.post("/{host_ip}/offline/install")
async def proxy_offline_install(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/offline/install", body, db)


@router.post("/{host_ip}/offline/clear")
async def proxy_offline_clear(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/offline/clear", db=db)


# --- Status / history ---
@router.get("/{host_ip}/health")
async def proxy_health(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/health", db)


@router.get("/{host_ip}/ping")
async def proxy_ping(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lightweight reachability + latency check."""
    import time

    try:
        await _validate_host_ip(host_ip, db)
        result = await db.execute(select(Host).where(Host.ip == host_ip))
        ping_host = result.scalars().first()
        urls = await _candidate_agent_urls(host_ip, "/health", db)
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            last_error = ""
            for url in urls:
                start = time.perf_counter()
                try:
                    r = await c.get(url, headers=_agent_auth_headers(ping_host))
                    if r.status_code >= 400:
                        last_error = f"{url} status={r.status_code}"
                        continue
                    latency = int((time.perf_counter() - start) * 1000)
                    data = r.json()
                    return {
                        "online": True,
                        "latency_ms": latency,
                        "state": data.get("state"),
                        "reboot_required": data.get("reboot_required"),
                        "raw": data,
                    }
                except Exception as inner:
                    last_error = str(inner)
                    continue
            return {
                "online": False,
                "error": last_error or "all candidate ports failed",
            }
    except Exception as e:
        return {"online": False, "error": str(e)}


@router.get("/{host_ip}/status")
async def proxy_status(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/status", db)


@router.get("/{host_ip}/history")
async def proxy_history(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/history", db)


@router.get("/{host_ip}/job/history")
async def proxy_job_history(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get(host_ip, "/job/history", db)


# --- WSUS / Windows Update (Windows agents only) ---
@router.get("/{host_ip}/wsus/updates")
async def proxy_wsus_updates(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _ensure_patch_license(host_ip, db)
    return await _get(host_ip, "/wsus/updates", db)


@router.post("/{host_ip}/wsus/install")
async def proxy_wsus_install(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _ensure_patch_license(host_ip, db)
    return await _post(host_ip, "/wsus/install", db=db)


@router.post("/{host_ip}/wsus/download")
async def proxy_wsus_download(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _ensure_patch_license(host_ip, db)
    return await _post(host_ip, "/wsus/download", body, db=db)


@router.post("/{host_ip}/wsus/install-selected")
async def proxy_wsus_install_selected(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    await _ensure_patch_license(host_ip, db)
    return await _post(host_ip, "/wsus/install", body, db=db)


@router.get("/{host_ip}/wsus/status")
async def proxy_wsus_status(
    host_ip: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _ensure_patch_license(host_ip, db)
    return await _get(host_ip, "/wsus/status", db)


# --- Server-side package download + push ---
@router.post("/{host_ip}/packages/uris")
async def proxy_uris(
    host_ip: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _post(host_ip, "/packages/uris", body, db)


@router.post("/{host_ip}/patch/server-patch")
async def server_patch(
    host_ip: str,
    body: dict = {},
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """
    Initiates a server-side patch job. Returns a Job ID immediately.
    The actual work (download, push, install) happens in the background.
    """
    # Verify host
    result = await db.execute(select(Host).where(Host.ip == host_ip))
    host = result.scalars().first()
    if not host:
        raise HTTPException(404, "Host not found")
    await _ensure_patch_license(host_ip, db)

    # Create Job Record
    job = PatchJob(
        host_id=host.id,
        action=PatchAction.server_patch,
        status=JobStatus.running,
        packages=body.get("packages", []),
        hold_packages=body.get("hold", []),
        dry_run=body.get("dry_run", False),
        auto_snapshot=body.get("auto_snapshot", True),
        auto_rollback=body.get("auto_rollback", True),
        initiated_by=user.username,
        started_at=_utcnow(),
        output="Job queued. Starting server-side patch workflow...",
    )
    db.add(job)
    await db.flush()
    await db.commit()
    await db.refresh(job)

    # Start Background Task
    if background_tasks is not None:
        background_tasks.add_task(_server_patch_worker, job.id, host_ip, body)
    else:
        asyncio.create_task(_server_patch_worker(job.id, host_ip, body))

    return {"status": "started", "job_id": job.id}


async def _server_patch_worker(job_id: int, host_ip: str, body: dict):
    async with async_session() as db:
        job = await db.get(PatchJob, job_id)
        if not job:
            return

        if job.status != JobStatus.running:
            job.status = JobStatus.running
        if not job.started_at:
            job.started_at = _utcnow()
        await db.commit()

        log = ["Starting server-side patch workflow..."]

        def update_log(msg):
            log.append(f"[{_utcnow().strftime('%H:%M:%S')}] {msg}")
            job.output = "\n".join(log)

        try:
            packages = body.get("packages", [])
            hold = [str(x).strip() for x in (body.get("hold") or []) if str(x).strip()]
            dry_run = body.get("dry_run", False)
            auto_snapshot = bool(body.get("auto_snapshot", True))
            auto_rollback = bool(body.get("auto_rollback", True))
            update_policy = str(body.get("update_policy") or "latest").strip().lower()
            download_only = bool(body.get("download_only", False))
            save_to_repo = bool(body.get("save_to_repo", True))
            security_only = bool(body.get("security_only", False))
            exclude_kernel = bool(body.get("exclude_kernel", False))
            auto_reboot = bool(body.get("auto_reboot", False))
            pre_patch_script = str(body.get("pre_patch_script") or "").strip() or None
            post_patch_script = str(body.get("post_patch_script") or "").strip() or None
            extra_flags = [
                str(f)
                for f in (body.get("extra_flags") or [])
                if isinstance(f, str) and str(f).strip().startswith("-")
            ]

            def _version_numbers(v: str):
                if not isinstance(v, str):
                    return []
                cleaned = v.split(":")[-1]
                return [int(x) for x in re.findall(r"\d+", cleaned)]

            def _allow_by_policy(current_version: str, available_version: str) -> bool:
                if update_policy != "n_minus_1":
                    return True
                cur_nums = _version_numbers(current_version)
                new_nums = _version_numbers(available_version)
                if not cur_nums or not new_nums:
                    return True
                cur_major = cur_nums[0]
                new_major = new_nums[0]
                if new_major != cur_major:
                    return False
                cur_minor = cur_nums[1] if len(cur_nums) > 1 else 0
                new_minor = new_nums[1] if len(new_nums) > 1 else 0
                return (new_minor - cur_minor) <= 1

            # 1. Get URIs
            update_log("Requesting package URIs from agent...")
            await db.commit()  # Save progress

            requested_packages = list(packages or [])
            if hold and requested_packages:
                hold_set = set(hold)
                before_hold = len(requested_packages)
                requested_packages = [
                    p for p in requested_packages if p not in hold_set
                ]
                update_log(
                    f"Hold list excluded {before_hold - len(requested_packages)} package(s): {', '.join(hold)}"
                )
            if update_policy == "n_minus_1":
                update_log("Applying N-1 policy filter against available updates...")
                upg = await _get(host_ip, "/packages/upgradable", db)
                upgradable = upg.get("packages", []) if isinstance(upg, dict) else []
                filtered = [
                    p.get("name")
                    for p in upgradable
                    if _allow_by_policy(
                        str(p.get("current_version") or ""),
                        str(p.get("available_version") or ""),
                    )
                ]
                if requested_packages:
                    req_set = set(requested_packages)
                    filtered = [p for p in filtered if p in req_set]
                skipped = max(
                    (len(requested_packages) if requested_packages else len(upgradable))
                    - len(filtered),
                    0,
                )
                requested_packages = filtered
                if hold and requested_packages:
                    hold_set = set(hold)
                    before_hold = len(requested_packages)
                    requested_packages = [
                        p for p in requested_packages if p not in hold_set
                    ]
                    update_log(
                        f"Hold list removed {before_hold - len(requested_packages)} package(s) after policy filter."
                    )
                update_log(
                    f"N-1 policy retained {len(requested_packages)} package(s), skipped {skipped}."
                )

            uris_data = await _post(
                host_ip, "/packages/uris", {"packages": requested_packages}, db=db
            )
            uris = uris_data.get("uris", [])

            if not uris:
                if not requested_packages:
                    update_log("No packages to download.")
                    job.status = JobStatus.success
                    job.completed_at = _utcnow()
                    await db.commit()
                    return
                # URIs unavailable (e.g. apt cache not populated) — fall back to direct agent patch
                update_log(
                    f"Package URI resolution returned no results for {len(requested_packages)} package(s). "
                    "Falling back to direct agent-side patch execution..."
                )
                patch_result = await _post(
                    host_ip,
                    "/patch/execute",
                    {
                        "packages": requested_packages,
                        "hold": hold,
                        "dry_run": dry_run,
                        "auto_snapshot": auto_snapshot,
                        "auto_rollback": auto_rollback,
                        "security_only": security_only,
                        "exclude_kernel": exclude_kernel,
                        "auto_reboot": auto_reboot,
                        "pre_patch_script": pre_patch_script,
                        "post_patch_script": post_patch_script,
                        "extra_flags": extra_flags,
                    },
                    db=db,
                )
                update_log(f"Agent patch started: {patch_result}")
                job.status = JobStatus.success
                job.result = {
                    "success": True,
                    "fallback": "direct_agent_patch",
                    "agent_response": patch_result,
                }
                job.completed_at = _utcnow()
                await db.commit()
                return

            if dry_run:
                total_expected = 0
                known_sizes = 0
                for uri in uris:
                    try:
                        sz = int(str(uri.get("size") or "0").strip())
                    except Exception:
                        sz = 0
                    if sz > 0:
                        total_expected += sz
                        known_sizes += 1
                update_log(
                    f"Dry-run completed. {len(uris)} package(s) would be downloaded"
                    + (
                        f" (~{(total_expected / (1024 * 1024)):.2f} MB known)"
                        if known_sizes > 0
                        else ""
                    )
                    + ". No files were downloaded or installed."
                )
                job.status = JobStatus.success
                job.result = {
                    "success": True,
                    "dry_run": True,
                    "planned_packages": len(uris),
                    "known_size_bytes": total_expected,
                    "known_size_count": known_sizes,
                    "policy": update_policy,
                    "download_only": bool(download_only),
                    "save_to_repo": bool(save_to_repo),
                }
                job.completed_at = _utcnow()
                await db.commit()
                return

            # 2. Download
            update_log(f"Downloading {len(uris)} packages on server...")
            await db.commit()

            tmp_dir = tempfile.mkdtemp(prefix="pm-patch-")
            downloaded = []

            async with httpx.AsyncClient(
                timeout=180.0, follow_redirects=True
            ) as client:
                total_uris = len(uris)
                for idx, uri in enumerate(uris, start=1):
                    raw_name = str(uri.get("filename") or "").strip()
                    if not raw_name:
                        raw_name = os.path.basename(
                            urlsplit(str(uri.get("url") or "")).path
                        )
                    fname = os.path.basename(raw_name) or f"package-{idx}"
                    path = os.path.join(tmp_dir, fname)
                    expected_size = (
                        int(uri.get("size") or 0)
                        if str(uri.get("size", "")).isdigit()
                        else 0
                    )
                    update_log(
                        f"Downloading {fname} ({idx}/{total_uris})"
                        + (
                            f", expected {(expected_size / (1024 * 1024)):.2f} MB"
                            if expected_size > 0
                            else ""
                        )
                    )
                    await db.commit()
                    try:
                        started_ts = _utcnow()
                        bytes_written = 0
                        async with client.stream("GET", uri["url"]) as r:
                            if r.status_code != 200:
                                update_log(
                                    f"Failed to download {fname}: {r.status_code}"
                                )
                                await db.commit()
                                continue
                            with open(path, "wb") as f:
                                last_log_ts = _utcnow()
                                async for chunk in r.aiter_bytes():
                                    if not chunk:
                                        continue
                                    f.write(chunk)
                                    bytes_written += len(chunk)
                                    now = _utcnow()
                                    if (now - last_log_ts).total_seconds() >= 1.0:
                                        elapsed = max(
                                            (now - started_ts).total_seconds(), 0.001
                                        )
                                        speed_bps = bytes_written / elapsed
                                        eta_sec = (
                                            (
                                                (expected_size - bytes_written)
                                                / speed_bps
                                            )
                                            if (
                                                expected_size > bytes_written
                                                and speed_bps > 0
                                            )
                                            else 0
                                        )
                                        update_log(
                                            f"Downloading {fname}: {(bytes_written / (1024 * 1024)):.2f} MB"
                                            + (
                                                f" / {(expected_size / (1024 * 1024)):.2f} MB"
                                                if expected_size > 0
                                                else ""
                                            )
                                            + f", speed {(speed_bps / (1024 * 1024)):.2f} MB/s"
                                            + (
                                                f", ETA {int(eta_sec)}s"
                                                if eta_sec > 0
                                                else ""
                                            )
                                        )
                                        await db.commit()
                                        last_log_ts = now
                        elapsed = max((_utcnow() - started_ts).total_seconds(), 0.001)
                        avg_speed_bps = bytes_written / elapsed
                        downloaded.append(path)
                        update_log(
                            f"Downloaded {fname} ({idx}/{total_uris}) - {(bytes_written / (1024 * 1024)):.2f} MB at avg {(avg_speed_bps / (1024 * 1024)):.2f} MB/s"
                        )
                        await db.commit()
                    except Exception as e:
                        update_log(f"Error downloading {fname}: {e}")
                        await db.commit()

            if not downloaded:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise Exception("No packages downloaded successfully")

            # 3. Save to master repository (optional)
            saved_to_repo = []
            if save_to_repo:
                os.makedirs(LOCAL_REPO_DIR, exist_ok=True)
                for fpath in downloaded:
                    dst = os.path.join(LOCAL_REPO_DIR, os.path.basename(fpath))
                    try:
                        shutil.copy2(fpath, dst)
                        saved_to_repo.append(os.path.basename(dst))
                    except Exception as copy_err:
                        update_log(
                            f"Failed to store {os.path.basename(fpath)} in master repo: {copy_err}"
                        )
                if saved_to_repo:
                    update_log(
                        f"Saved {len(saved_to_repo)} package(s) into master repository."
                    )
                    await db.commit()

            if download_only:
                update_log(
                    "Download-only mode enabled. Skipping push/install on agent."
                )
                job.status = JobStatus.success
                job.result = {
                    "success": True,
                    "download_only": True,
                    "downloaded_count": len(downloaded),
                    "saved_to_master_repo": saved_to_repo,
                    "policy": update_policy,
                }
                job.completed_at = _utcnow()
                await db.commit()
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return

            # 4. Push all packages to agent (no artificial limits)
            update_log(f"Pushing {len(downloaded)} packages to agent...")
            await db.commit()

            agent_urls = await _candidate_agent_urls(host_ip, "/offline/upload", db)
            try:
                push_host_result = await db.execute(
                    select(Host).where(Host.ip == host_ip)
                )
                push_host = push_host_result.scalar_one_or_none()

                # Upload all packages in a single batch - no artificial limits
                # The agent and network can handle any size
                update_log(f"Uploading {len(downloaded)} packages...")
                await db.commit()

                async with httpx.AsyncClient(
                    timeout=None
                ) as client:  # No timeout - let it complete
                    pushed = False
                    last_error = None

                    for agent_url in agent_urls:
                        try:
                            # Open file handles fresh for each attempt
                            files_to_send = []
                            file_handles = []
                            for fpath in downloaded:
                                fh = open(fpath, "rb")
                                file_handles.append(fh)
                                files_to_send.append(
                                    (
                                        "file",
                                        (
                                            os.path.basename(fpath),
                                            fh,
                                            "application/octet-stream",
                                        ),
                                    )
                                )

                            try:
                                resp = await client.post(
                                    agent_url,
                                    files=files_to_send,
                                    headers=_agent_auth_headers(push_host),
                                )
                                if resp.status_code < 400:
                                    pushed = True
                                    update_log(
                                        f"All {len(downloaded)} packages uploaded successfully"
                                    )
                                    await db.commit()
                                    break
                                else:
                                    last_error = f"{agent_url} returned status {resp.status_code}: {resp.text[:200]}"
                                    update_log(f"Upload failed: {last_error}")
                                    await db.commit()
                            finally:
                                # Close file handles after each attempt
                                for fh in file_handles:
                                    fh.close()

                        except Exception as upload_err:
                            last_error = f"{agent_url} error: {str(upload_err)}"
                            update_log(f"Upload failed: {last_error}")
                            await db.commit()
                            continue

                    if not pushed:
                        raise Exception(
                            f"Upload failed on all candidate ports. Last error: {last_error}"
                        )

                update_log(f"All {len(downloaded)} packages uploaded successfully")
                await db.commit()

            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            # 5. Install
            update_log("Triggering agent install (async)...")
            await db.commit()

            install_body = {
                "files": [os.path.basename(p) for p in downloaded],
                "auto_snapshot": auto_snapshot,
                "auto_rollback": auto_rollback,
                "auto_reboot": auto_reboot,
                "post_patch_script": post_patch_script,
            }
            # This returns {"status": "started", "job": "offline_install"}
            inst_resp = await _post(host_ip, "/offline/install", install_body, db=db)

            if inst_resp.get("status") != "started":
                update_log(f"Agent failed to start offline install: {inst_resp}")
                job.status = JobStatus.failed
            else:
                update_log("Agent started installation. Polling for completion...")
                await db.commit()

                # Poll agent until done
                last_seen_state = ""
                last_seen_progress = None
                for _ in range(180):
                    await asyncio.sleep(2)
                    try:
                        status_resp = await _get(host_ip, "/job/status", db)
                    except Exception as poll_err:
                        update_log(f"Waiting for agent job status... ({poll_err})")
                        await db.commit()
                        continue
                    state = str(status_resp.get("state") or "").strip().lower()
                    current_job = (
                        str(status_resp.get("current_job") or "").strip().lower()
                    )
                    progress = status_resp.get("progress")
                    if state != last_seen_state or progress != last_seen_progress:
                        progress_text = (
                            f", progress {progress}%"
                            if isinstance(progress, (int, float))
                            else ""
                        )
                        cj_text = f", job {current_job}" if current_job else ""
                        update_log(
                            f"Agent status: {state or 'unknown'}{progress_text}{cj_text}"
                        )
                        await db.commit()
                        last_seen_state = state
                        last_seen_progress = progress
                    if (
                        current_job
                        and current_job != "offline_install"
                        and state in ["running", "success", "failed"]
                    ):
                        continue
                    if state in ["success", "failed"]:
                        job.result = status_resp.get("last_result")
                        if state == "success":
                            update_log("Agent reported success!")
                            job.status = JobStatus.success
                        else:
                            update_log(
                                f"Agent reported failure: {status_resp.get('last_result')}"
                            )
                            job.status = JobStatus.failed
                        break
                else:
                    update_log("Timed out waiting for agent installation status.")
                    job.status = JobStatus.failed

        except Exception as e:
            update_log(f"Server-side error: {str(e)}")
            job.status = JobStatus.failed

        job.completed_at = _utcnow()
        await db.commit()


async def _ensure_patch_license(host_ip: str, db: AsyncSession):
    """Enforce license-based OS patching availability."""
    result = await db.execute(select(Host).where(Host.ip == host_ip))
    host = result.scalars().first()
    if not host:
        return
    os_name = (host.os or "").lower()
    license_info = get_license_info()
    features = set(license_info.get("features") or [])
    if "windows" in os_name:
        if "windows_patching" not in features:
            raise HTTPException(
                403, "Windows patching not permitted by current license tier."
            )
    else:
        if "linux_patching" not in features:
            raise HTTPException(
                403, "Linux/Unix patching not permitted by current license tier."
            )


# --- Live Command Runner ---
# SECURITY: Uses strict ALLOWLIST (not a blocklist) of safe read-only command prefixes.
# Set LIVE_CMD_ENABLED=false to globally disable this feature.
import re as _re

LIVE_CMD_ENABLED = os.getenv("LIVE_CMD_ENABLED", "true").lower() == "true"

# Only commands starting with one of these prefixes are permitted.
# All other commands are blocked by default.
_ALLOWED_CMD_PREFIXES = {
    # System info / monitoring
    "df",
    "du",
    "free",
    "top",
    "uptime",
    "date",
    "uname",
    "hostname",
    "whoami",
    "id",
    # Process / network
    "ps",
    "netstat",
    "ss",
    "ip addr",
    "ip route",
    "ip link",
    "ping",
    # File inspection (read-only)
    "ls",
    "cat",
    "tail",
    "head",
    "grep",
    "find",
    "awk",
    "sed",
    # Journaling / logs
    "journalctl",
    "dmesg",
    # Service status (status only)
    "systemctl status",
    "systemctl is-active",
    "systemctl is-enabled",
    "systemctl list-units",
    # Hardware
    "lsblk",
    "lspci",
    "lsusb",
    "lscpu",
    "lsmem",
    # Package info (read-only list/query)
    "apt list",
    "apt-cache",
    "dpkg -l",
    "dpkg --list",
    "dpkg -s",
    "dnf list",
    "yum list",
    "rpm -q",
    "rpm -qa",
    "rpm -qi",
    "pacman -Q",
    "pacman -Si",
    "pkg info",
    "pkg list",
    "apk info",
    "apk list",
    "zypper info",
    "zypper se",
    # Windows
    "winget list",
    "winget show",
    "get-service",
    "get-process",
    "get-computerinfo",
    "dir",
    "type",
    "ipconfig",
    "netstat",
    # Disk usage
    "lsof",
}

from pydantic import BaseModel as _BaseModel


def _audit_command(user, host_ip: str, cmd: str):
    """Write live-command execution to audit log (fire-and-forget, non-blocking)."""
    import asyncio

    async def _write():
        try:
            async with async_session() as _db:
                from api.audit import log_action

                await log_action(
                    _db,
                    user,
                    "live_command",
                    target_type="host",
                    target_id=host_ip,
                    details={"command": cmd},
                )
        except Exception:
            pass

    try:
        asyncio.create_task(_write())
    except RuntimeError:
        pass  # Outside async context (tests)


class RunCommandRequest(_BaseModel):
    command: str
    timeout: int = 30
    working_dir: str = ""


def _is_command_allowed(cmd: str) -> bool:
    """Check command against strict allowlist. Returns True if allowed."""
    cmd_lower = cmd.strip().lower()
    for prefix in _ALLOWED_CMD_PREFIXES:
        if (
            cmd_lower == prefix
            or cmd_lower.startswith(prefix + " ")
            or cmd_lower.startswith(prefix + "\t")
        ):
            return True
    return False


@router.post("/{host_ip}/run")
async def run_command(
    host_ip: str,
    body: RunCommandRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Execute a pre-approved read-only command on a registered host via its agent.
    Admin/operator only. Command must match the strict allowlist.
    """
    if not LIVE_CMD_ENABLED:
        raise HTTPException(403, "Live command execution is disabled on this server.")
    if user.role not in (UserRole.admin, UserRole.operator):
        raise HTTPException(403, "Only admin/operator can run commands")

    cmd = body.command.strip()
    if not cmd:
        raise HTTPException(400, "Command cannot be empty")
    if not _is_command_allowed(cmd):
        raise HTTPException(
            400,
            f"Command not permitted. Only pre-approved read-only commands are allowed. "
            f"Contact your administrator to add new commands to the allowlist.",
        )
    if body.timeout < 1 or body.timeout > 300:
        raise HTTPException(400, "Timeout must be 1–300 seconds")

    _audit_command(user, host_ip, cmd)
    await _validate_host_ip(host_ip, db)
    try:
        run_host_result = await db.execute(select(Host).where(Host.ip == host_ip))
        run_host = run_host_result.scalar_one_or_none()
        urls = await _candidate_agent_urls(host_ip, "/run", db)
        async with httpx.AsyncClient(timeout=body.timeout + 5.0) as client:
            last_error = ""
            for url in urls:
                r = await client.post(
                    url,
                    json={
                        "command": cmd,
                        "timeout": body.timeout,
                        "working_dir": body.working_dir,
                    },
                    headers=_agent_auth_headers(run_host),
                )
                if r.status_code < 400:
                    return r.json()
                last_error = f"{url} status={r.status_code}"
            raise HTTPException(
                502, f"Agent unreachable: {last_error or 'all candidate ports failed'}"
            )
    except httpx.TimeoutException:
        raise HTTPException(504, "Command timed out")
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/run")
async def run_command_by_host_id(
    host_id: int,
    body: RunCommandRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    if not LIVE_CMD_ENABLED:
        raise HTTPException(403, "Live command execution is disabled on this server.")
    if user.role not in (UserRole.admin, UserRole.operator):
        raise HTTPException(403, "Only admin/operator can run commands")
    cmd = body.command.strip()
    if not cmd:
        raise HTTPException(400, "Command cannot be empty")
    if not _is_command_allowed(cmd):
        raise HTTPException(
            400,
            "Command not permitted. Only pre-approved read-only commands are allowed.",
        )
    if body.timeout < 1 or body.timeout > 300:
        raise HTTPException(400, "Timeout must be 1–300 seconds")
    host, url = await _agent_url_for_host_id(host_id, "/run", db)
    _audit_command(user, host.ip, cmd)
    try:
        async with httpx.AsyncClient(timeout=body.timeout + 5.0) as client:
            r = await client.post(
                url,
                json={
                    "command": cmd,
                    "timeout": body.timeout,
                    "working_dir": body.working_dir,
                },
                headers=_agent_auth_headers(host),
            )
            payload = r.json()
            if isinstance(payload, dict):
                payload.setdefault("host_ip", host.ip)
                payload.setdefault("host_id", host.id)
            return payload
    except httpx.TimeoutException:
        raise HTTPException(504, "Command timed out")
    except Exception as e:
        raise HTTPException(502, f"Agent unreachable: {e}")
