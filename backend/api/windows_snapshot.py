"""
Windows Snapshot Management API for Patch-SecOps Solution.

Provides Windows-specific snapshot operations via VSS (Volume Shadow Copy Service).
Supports creating, listing, rolling back, and deleting snapshots.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from database import get_db
from models.db_models import Host, User, UserRole


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/windows-snapshot", tags=["windows-snapshot"])


def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


class SnapshotMode(str, Enum):
    """Windows snapshot modes."""

    APPLICATION_CONSISTENT = "application_consistent"
    CRASH_CONSISTENT = "crash_consistent"
    FULL_SYSTEM = "full_system"


class SnapshotCreateRequest(BaseModel):
    """Request to create a Windows snapshot."""

    name: Optional[str] = None
    mode: SnapshotMode = SnapshotMode.APPLICATION_CONSISTENT
    description: Optional[str] = None
    backup_target: Optional[str] = None  # SMB target for full system backup


class SnapshotListResponse(BaseModel):
    """Response for snapshot list."""

    snapshots: list[dict[str, Any]]
    total: int


class SnapshotPrecheckResponse(BaseModel):
    """Response for snapshot precheck."""

    can_create: bool
    requirements_met: list[str]
    requirements_missing: list[str]
    warnings: list[str]


class SnapshotRollbackRequest(BaseModel):
    """Request to rollback to a snapshot."""

    snapshot_name: str
    force: bool = False
    keep_snapshot: bool = True


@router.get("/by-host/{host_id}/list", response_model=SnapshotListResponse)
async def list_windows_snapshots(
    host_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """List all snapshots for a Windows host."""
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    if not _is_windows_host(host):
        raise HTTPException(status_code=400, detail="Host is not Windows")

    # Proxy to agent
    from api.agent_proxy import _agent_url_for_host_id

    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/list", db)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            return {
                "snapshots": data.get("snapshots", []),
                "total": data.get("total", 0),
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/create")
async def create_windows_snapshot(
    host_id: int,
    body: SnapshotCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Create a Windows snapshot for a host."""
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    if not _is_windows_host(host):
        raise HTTPException(status_code=400, detail="Host is not Windows")

    # Build payload for agent
    payload = {
        "mode": body.mode.value,
    }
    if body.name:
        payload["name"] = body.name
    if body.description:
        payload["description"] = body.description
    if body.backup_target:
        payload["backup_target"] = body.backup_target

    from api.agent_proxy import _enrich_snapshot_body_for_windows

    enriched_payload = _enrich_snapshot_body_for_windows(host, payload)

    from api.agent_proxy import _agent_url_for_host_id

    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/create", db)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=enriched_payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/precheck", response_model=SnapshotPrecheckResponse)
async def precheck_windows_snapshot(
    host_id: int,
    body: SnapshotCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Precheck if snapshot can be created for a Windows host."""
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    if not _is_windows_host(host):
        raise HTTPException(status_code=400, detail="Host is not Windows")

    # Build payload
    payload = {"mode": body.mode.value}
    if body.backup_target:
        payload["backup_target"] = body.backup_target

    from api.agent_proxy import _agent_url_for_host_id

    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/precheck", db)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            return {
                "can_create": data.get("can_create", True),
                "requirements_met": data.get("requirements_met", []),
                "requirements_missing": data.get("requirements_missing", []),
                "warnings": data.get("warnings", []),
            }
    except Exception as e:
        return {
            "can_create": False,
            "requirements_met": [],
            "requirements_missing": ["Unable to contact agent"],
            "warnings": [str(e)],
        }


@router.post("/by-host/{host_id}/rollback")
async def rollback_windows_snapshot(
    host_id: int,
    body: SnapshotRollbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Rollback a Windows host to a previous snapshot."""
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    if not _is_windows_host(host):
        raise HTTPException(status_code=400, detail="Host is not Windows")

    from api.agent_proxy import _agent_url_for_host_id

    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/rollback", db)
    try:
        import httpx

        payload = {
            "name": body.snapshot_name,
            "force": body.force,
            "keep_snapshot": body.keep_snapshot,
        }
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@router.post("/by-host/{host_id}/delete")
async def delete_windows_snapshot(
    host_id: int,
    snapshot_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete a Windows snapshot."""
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    if not _is_windows_host(host):
        raise HTTPException(status_code=400, detail="Host is not Windows")

    from api.agent_proxy import _agent_url_for_host_id

    _host, url = await _agent_url_for_host_id(host_id, "/snapshot/delete", db)
    try:
        import httpx

        payload = {"name": snapshot_name}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


@router.get("/by-host/{host_id}/archive/{name}")
async def download_windows_snapshot_archive(
    host_id: int,
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Download a Windows snapshot archive."""
    from fastapi.responses import StreamingResponse

    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    if not _is_windows_host(host):
        raise HTTPException(status_code=400, detail="Host is not Windows")

    from api.agent_proxy import _agent_url_for_host_id

    _host, url = await _agent_url_for_host_id(host_id, f"/snapshot/archive/{name}", db)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            r = await client.get(url, follow_redirects=True)
            r.raise_for_status()

            headers = {}
            cd = r.headers.get("content-disposition")
            if cd:
                headers["Content-Disposition"] = cd

            return StreamingResponse(
                r.aiter_bytes(),
                media_type=r.headers.get("content-type", "application/zip"),
                headers=headers,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent unreachable: {e}")


def _is_windows_host(host: Host) -> bool:
    """Check if host is Windows."""
    os_name = (host.os or "").lower()
    return "win" in os_name or "windows" in os_name


# Additional helper endpoints
@router.get("/modes")
async def list_snapshot_modes():
    """List available Windows snapshot modes."""
    return {
        "modes": [
            {
                "name": SnapshotMode.APPLICATION_CONSISTENT.value,
                "description": "Application consistent - uses VSS to ensure data integrity",
            },
            {
                "name": SnapshotMode.CRASH_CONSISTENT.value,
                "description": "Crash consistent - simple snapshot without application coordination",
            },
            {
                "name": SnapshotMode.FULL_SYSTEM.value,
                "description": "Full system backup - complete disk image including system state",
            },
        ]
    }


@router.get("/requirements")
async def windows_snapshot_requirements():
    """Get requirements for Windows snapshots."""
    return {
        "requirements": [
            "Windows host with VSS (Volume Shadow Copy Service) enabled",
            "Sufficient disk space for snapshots",
            "Administrator access to Windows host",
            "For full system mode: SMB share for backup storage",
        ],
        "supported_os": [
            "Windows Server 2012 R2 and later",
            "Windows 10/11 Enterprise",
        ],
    }
