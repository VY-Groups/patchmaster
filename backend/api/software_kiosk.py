from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_user, require_role
from database import get_db
from models.db_models import Host, SoftwareCatalogItem, SoftwareKioskRequest, User, UserRole
import api.agent_proxy as agent_proxy

router = APIRouter(prefix="/api/software-kiosk", tags=["software-kiosk"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _ensure_kiosk_schema(db: AsyncSession) -> None:
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS software_catalog_items (
            id SERIAL PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            package_name VARCHAR(200) NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            supported_platforms JSONB DEFAULT '[]'::jsonb,
            allowed_actions JSONB DEFAULT '[]'::jsonb,
            default_execution_mode VARCHAR(20) DEFAULT 'immediate',
            is_enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS software_kiosk_requests (
            id SERIAL PRIMARY KEY,
            catalog_item_id INTEGER NOT NULL REFERENCES software_catalog_items(id) ON DELETE CASCADE,
            host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
            requested_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            approved_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            requested_action VARCHAR(20) NOT NULL DEFAULT 'install',
            execution_mode VARCHAR(20) NOT NULL DEFAULT 'immediate',
            note TEXT DEFAULT '',
            status VARCHAR(24) NOT NULL DEFAULT 'submitted',
            status_message TEXT DEFAULT '',
            fulfilled_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_software_catalog_enabled ON software_catalog_items(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_software_kiosk_status ON software_kiosk_requests(status);",
    ]
    for stmt in stmts:
        await db.execute(text(stmt))


def _normalize_actions(actions: list[str] | None) -> list[str]:
    normalized = []
    for action in actions or []:
        value = str(action or "").strip().lower()
        if value in {"install", "remove"} and value not in normalized:
            normalized.append(value)
    return normalized or ["install"]


def _normalize_platforms(platforms: list[str] | None) -> list[str]:
    normalized = []
    for platform_name in platforms or []:
        value = str(platform_name or "").strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_execution_mode(value: str | None) -> str:
    mode = str(value or "immediate").strip().lower()
    return mode if mode in {"immediate", "shutdown"} else "immediate"


def _catalog_public(item: SoftwareCatalogItem) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "package_name": item.package_name,
        "description": item.description or "",
        "supported_platforms": list(item.supported_platforms or []),
        "allowed_actions": list(item.allowed_actions or []),
        "default_execution_mode": item.default_execution_mode or "immediate",
        "is_enabled": bool(item.is_enabled),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _request_public(req: SoftwareKioskRequest) -> dict:
    catalog = req.catalog_item
    host = req.host
    requested_by = req.requested_by
    approved_by = req.approved_by
    return {
        "id": req.id,
        "status": req.status,
        "status_message": req.status_message or "",
        "requested_action": req.requested_action,
        "execution_mode": req.execution_mode,
        "note": req.note or "",
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "fulfilled_at": req.fulfilled_at.isoformat() if req.fulfilled_at else None,
        "catalog_item": _catalog_public(catalog) if catalog else None,
        "host": {
            "id": host.id,
            "hostname": host.hostname,
            "ip": host.ip,
            "os": host.os,
            "site": host.site or "",
        } if host else None,
        "requested_by": {
            "id": requested_by.id,
            "username": requested_by.username,
            "role": requested_by.role.value if hasattr(requested_by.role, "value") else str(requested_by.role),
        } if requested_by else None,
        "approved_by": {
            "id": approved_by.id,
            "username": approved_by.username,
        } if approved_by else None,
    }


async def _dispatch_request_to_agent(req: SoftwareKioskRequest, db: AsyncSession, approved_by: User) -> tuple[bool, dict]:
    host = req.host
    catalog = req.catalog_item
    if not host or not catalog:
        return False, {"error": "Request is missing host or catalog item"}
    payload = {
        "action": req.requested_action,
        "packages": [catalog.package_name],
        "requested_by": approved_by.username,
        "reason": req.note or f"Kiosk request #{req.id}",
    }
    if req.execution_mode == "shutdown":
        path = "/software/queue"
    else:
        path = "/software/manage"
    _, url = await agent_proxy._agent_url_for_host_id(req.host_id, path, db)
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=agent_proxy._agent_auth_headers(host))
    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    return response.status_code < 400, data


class CatalogItemUpsert(BaseModel):
    name: str
    package_name: str
    description: str = ""
    supported_platforms: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=lambda: ["install"])
    default_execution_mode: str = "immediate"
    is_enabled: bool = True


class KioskRequestCreate(BaseModel):
    catalog_item_id: int
    host_id: int
    requested_action: str = "install"
    execution_mode: str | None = None
    note: str = ""


@router.get("/catalog")
async def list_catalog(
    include_disabled: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(SoftwareCatalogItem).order_by(SoftwareCatalogItem.name.asc())
    is_operator = (user.role in {UserRole.admin, UserRole.operator})
    if not include_disabled or not is_operator:
        query = query.where(SoftwareCatalogItem.is_enabled == True)
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_catalog_public(item) for item in rows]}


@router.post("/catalog")
async def create_catalog_item(
    body: CatalogItemUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    normalized_package = body.package_name.strip()
    existing = await db.execute(select(SoftwareCatalogItem).where(SoftwareCatalogItem.package_name == normalized_package))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Catalog item with this package already exists")
    item = SoftwareCatalogItem(
        name=body.name.strip(),
        package_name=normalized_package,
        description=body.description.strip(),
        supported_platforms=_normalize_platforms(body.supported_platforms),
        allowed_actions=_normalize_actions(body.allowed_actions),
        default_execution_mode=_normalize_execution_mode(body.default_execution_mode),
        is_enabled=body.is_enabled,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return _catalog_public(item)


@router.put("/catalog/{item_id}")
async def update_catalog_item(
    item_id: int,
    body: CatalogItemUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    item = await db.get(SoftwareCatalogItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    normalized_package = body.package_name.strip()
    existing = await db.execute(
        select(SoftwareCatalogItem).where(
            SoftwareCatalogItem.package_name == normalized_package,
            SoftwareCatalogItem.id != item_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Another catalog item already uses this package name")
    item.name = body.name.strip()
    item.package_name = normalized_package
    item.description = body.description.strip()
    item.supported_platforms = _normalize_platforms(body.supported_platforms)
    item.allowed_actions = _normalize_actions(body.allowed_actions)
    item.default_execution_mode = _normalize_execution_mode(body.default_execution_mode)
    item.is_enabled = body.is_enabled
    item.updated_at = _utcnow()
    await db.flush()
    return _catalog_public(item)


@router.delete("/catalog/{item_id}")
async def delete_catalog_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    item = await db.get(SoftwareCatalogItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    await db.delete(item)
    await db.flush()
    return {"status": "deleted", "id": item_id}


@router.get("/requests")
async def list_requests(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        select(SoftwareKioskRequest)
        .options(
            selectinload(SoftwareKioskRequest.catalog_item),
            selectinload(SoftwareKioskRequest.host),
            selectinload(SoftwareKioskRequest.requested_by),
            selectinload(SoftwareKioskRequest.approved_by),
        )
        .order_by(desc(SoftwareKioskRequest.created_at))
    )
    if user.role not in {UserRole.admin, UserRole.operator}:
        query = query.where(SoftwareKioskRequest.requested_by_id == user.id)
    if status:
        query = query.where(SoftwareKioskRequest.status == status.strip().lower())
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_request_public(req) for req in rows]}


@router.post("/requests")
async def submit_request(
    body: KioskRequestCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = await db.get(SoftwareCatalogItem, body.catalog_item_id)
    if not item or not item.is_enabled:
        raise HTTPException(status_code=404, detail="Catalog item is not available")
    host = await db.get(Host, body.host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Target host not found")
    requested_action = str(body.requested_action or "install").strip().lower()
    if requested_action not in set(_normalize_actions(item.allowed_actions)):
        raise HTTPException(status_code=400, detail="Requested action is not allowed for this catalog item")
    req = SoftwareKioskRequest(
        catalog_item_id=item.id,
        host_id=host.id,
        requested_by_id=user.id,
        requested_action=requested_action,
        execution_mode=_normalize_execution_mode(body.execution_mode or item.default_execution_mode),
        note=(body.note or "").strip()[:500],
        status="submitted",
        status_message="Awaiting approval",
    )
    db.add(req)
    await db.flush()
    query = (
        select(SoftwareKioskRequest)
        .options(
            selectinload(SoftwareKioskRequest.catalog_item),
            selectinload(SoftwareKioskRequest.host),
            selectinload(SoftwareKioskRequest.requested_by),
            selectinload(SoftwareKioskRequest.approved_by),
        )
        .where(SoftwareKioskRequest.id == req.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _request_public(fresh)


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    query = (
        select(SoftwareKioskRequest)
        .options(
            selectinload(SoftwareKioskRequest.catalog_item),
            selectinload(SoftwareKioskRequest.host),
            selectinload(SoftwareKioskRequest.requested_by),
            selectinload(SoftwareKioskRequest.approved_by),
        )
        .where(SoftwareKioskRequest.id == request_id)
    )
    req = (await db.execute(query)).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Kiosk request not found")
    if req.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted requests can be approved")
    success, payload = await _dispatch_request_to_agent(req, db, user)
    req.approved_by_id = user.id
    req.fulfilled_at = _utcnow()
    req.updated_at = _utcnow()
    if success:
        req.status = "queued" if req.execution_mode == "shutdown" else "started"
        req.status_message = payload.get("status") or ("Queued for next controlled shutdown" if req.execution_mode == "shutdown" else "Agent accepted request")
    else:
        req.status = "failed"
        req.status_message = payload.get("error") or payload.get("detail") or "Agent call failed"
    await db.flush()
    return _request_public(req)


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    query = (
        select(SoftwareKioskRequest)
        .options(
            selectinload(SoftwareKioskRequest.catalog_item),
            selectinload(SoftwareKioskRequest.host),
            selectinload(SoftwareKioskRequest.requested_by),
            selectinload(SoftwareKioskRequest.approved_by),
        )
        .where(SoftwareKioskRequest.id == request_id)
    )
    req = (await db.execute(query)).scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Kiosk request not found")
    if req.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted requests can be rejected")
    req.approved_by_id = user.id
    req.status = "rejected"
    req.status_message = "Rejected by operator"
    req.fulfilled_at = _utcnow()
    req.updated_at = _utcnow()
    await db.flush()
    return _request_public(req)
