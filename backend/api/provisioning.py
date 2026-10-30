import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import api.agent_proxy as agent_proxy
from api.ops_queue import enqueue_operation
from auth import get_current_user, require_role
from database import async_session, get_db
from license import get_license_info
from models.db_models import Host, ProvisioningRun, ProvisioningTemplate, User, UserRole

router = APIRouter(prefix="/api/provisioning", tags=["provisioning"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_provisioning_access() -> None:
    info = get_license_info()
    features = set(info.get("features") or [])
    if "backups" not in features and "snapshots" not in features:
        raise HTTPException(status_code=403, detail="Provisioning requires snapshot or backup features in the active license")


async def _ensure_provisioning_schema(db: AsyncSession) -> None:
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS provisioning_templates (
            id SERIAL PRIMARY KEY,
            name VARCHAR(160) NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            source_host_id INTEGER NULL REFERENCES hosts(id) ON DELETE SET NULL,
            source_snapshot_name VARCHAR(200) NOT NULL,
            snapshot_mode VARCHAR(24) DEFAULT 'full_system',
            os_family VARCHAR(40) DEFAULT '',
            platform_label VARCHAR(120) DEFAULT '',
            site_scope VARCHAR(120) DEFAULT '',
            hardware_profile JSONB DEFAULT '{}'::jsonb,
            labels JSONB DEFAULT '[]'::jsonb,
            archive_file_name VARCHAR(255) NOT NULL DEFAULT '',
            archive_checksum VARCHAR(128) NOT NULL DEFAULT '',
            archive_size_bytes INTEGER DEFAULT 0,
            is_enabled BOOLEAN DEFAULT TRUE,
            created_by VARCHAR(100) DEFAULT '',
            last_verified_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS provisioning_runs (
            id SERIAL PRIMARY KEY,
            template_id INTEGER NOT NULL REFERENCES provisioning_templates(id) ON DELETE CASCADE,
            initiated_by VARCHAR(100) DEFAULT '',
            mode VARCHAR(24) DEFAULT 'reimage',
            status VARCHAR(24) DEFAULT 'pending',
            allow_cross_site BOOLEAN DEFAULT FALSE,
            target_host_ids JSONB DEFAULT '[]'::jsonb,
            result_summary JSONB DEFAULT '{}'::jsonb,
            queue_job_id VARCHAR(64) DEFAULT '',
            started_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_provisioning_templates_enabled ON provisioning_templates(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_provisioning_templates_site_scope ON provisioning_templates(site_scope);",
        "CREATE INDEX IF NOT EXISTS ix_provisioning_runs_status ON provisioning_runs(status);",
        "CREATE INDEX IF NOT EXISTS ix_provisioning_runs_queue_job_id ON provisioning_runs(queue_job_id);",
    ]
    for stmt in stmts:
        await db.execute(text(stmt))


def _provisioning_storage_dir() -> Path:
    root = Path(os.getenv("PM_PROVISIONING_IMAGE_DIR") or (Path(__file__).resolve().parents[2] / "provisioning-images"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_snapshot_name(name: str) -> str:
    safe = str(name or "").strip()
    safe = safe.replace("..", "").replace("/", "").replace("\\", "")
    if not safe:
        raise HTTPException(status_code=400, detail="Snapshot name is required")
    return safe


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return slug[:80] or "provisioning-image"


def _normalize_labels(labels: list[str] | None) -> list[str]:
    normalized = []
    for raw in labels or []:
        value = str(raw or "").strip()
        if value and value not in normalized:
            normalized.append(value[:64])
    return normalized


def _deduce_os_family(os_name: str | None) -> str:
    value = str(os_name or "").strip().lower()
    if "win" in value:
        return "windows"
    if "freebsd" in value:
        return "freebsd"
    if value:
        return "linux"
    return "unknown"


def _template_archive_path(template: ProvisioningTemplate) -> Path:
    return _provisioning_storage_dir() / str(template.archive_file_name or "")


def _write_archive_file(blob: bytes, template_name: str) -> tuple[str, int, str]:
    digest = hashlib.sha256(blob).hexdigest()
    file_name = f"{_slugify(template_name)}-{uuid.uuid4().hex[:10]}.zip"
    path = _provisioning_storage_dir() / file_name
    path.write_bytes(blob)
    return file_name, len(blob), digest


async def _download_snapshot_archive(host: Host, snapshot_name: str, db: AsyncSession) -> bytes:
    safe_name = _safe_snapshot_name(snapshot_name)
    _host, url = await agent_proxy._agent_url_for_host_id(host.id, f"/snapshot/archive/{safe_name}", db)
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.get(url, follow_redirects=True, headers=agent_proxy._agent_auth_headers(_host))
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Could not export snapshot from source host: {response.text[:300]}")
    return response.content


async def _upload_archive_to_target(host: Host, archive_path: Path, restore_name: str, db: AsyncSession) -> dict:
    _host, url = await agent_proxy._agent_url_for_host_id(host.id, "/snapshot/restore_upload", db)
    with archive_path.open("rb") as handle:
        files = {"file": (archive_path.name, handle, "application/zip")}
        data = {"name": _slugify(restore_name)}
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, files=files, data=data, headers=agent_proxy._agent_auth_headers(_host))
    try:
        payload = response.json()
    except Exception:
        payload = {"detail": response.text[:1000]}
    if response.status_code >= 400:
        detail = payload.get("detail") or payload.get("error") or f"Target host returned status {response.status_code}"
        raise HTTPException(status_code=502, detail=str(detail))
    return payload


def _template_public(template: ProvisioningTemplate) -> dict:
    source_host = template.source_host
    archive_path = _template_archive_path(template)
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description or "",
        "source_snapshot_name": template.source_snapshot_name,
        "snapshot_mode": template.snapshot_mode or "full_system",
        "os_family": template.os_family or "unknown",
        "platform_label": template.platform_label or "",
        "site_scope": template.site_scope or "",
        "hardware_profile": dict(template.hardware_profile or {}),
        "labels": list(template.labels or []),
        "archive_file_name": template.archive_file_name,
        "archive_checksum": template.archive_checksum,
        "archive_size_bytes": int(template.archive_size_bytes or 0),
        "archive_present": archive_path.is_file(),
        "is_enabled": bool(template.is_enabled),
        "created_by": template.created_by or "",
        "last_verified_at": template.last_verified_at.isoformat() if template.last_verified_at else None,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "source_host": {
            "id": source_host.id,
            "hostname": source_host.hostname,
            "ip": source_host.ip,
            "os": source_host.os,
            "site": source_host.site or "",
        } if source_host else None,
    }


def _run_public(run: ProvisioningRun) -> dict:
    template = run.template
    summary = dict(run.result_summary or {})
    return {
        "id": run.id,
        "mode": run.mode or "reimage",
        "status": run.status,
        "allow_cross_site": bool(run.allow_cross_site),
        "target_host_ids": list(run.target_host_ids or []),
        "result_summary": summary,
        "queue_job_id": run.queue_job_id or "",
        "initiated_by": run.initiated_by or "",
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "template": {
            "id": template.id,
            "name": template.name,
            "os_family": template.os_family,
            "site_scope": template.site_scope or "",
        } if template else None,
    }


class ProvisioningTemplateCapture(BaseModel):
    name: str
    host_id: int
    snapshot_name: str
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    site_scope: str | None = None
    snapshot_mode: str = "full_system"


class ProvisioningTemplateUpdate(BaseModel):
    name: str
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    site_scope: str = ""
    is_enabled: bool = True


class ProvisioningRunCreate(BaseModel):
    template_id: int
    target_host_ids: list[int] = Field(default_factory=list)
    allow_cross_site: bool = False


async def _run_provisioning_rollout(run_id: int) -> dict:
    async with async_session() as session:
        query = (
            select(ProvisioningRun)
            .options(selectinload(ProvisioningRun.template))
            .where(ProvisioningRun.id == run_id)
        )
        run = (await session.execute(query)).scalar_one_or_none()
        if not run:
            return {"status": "missing_run", "run_id": run_id}

        template = run.template
        if not template:
            run.status = "failed"
            run.result_summary = {"error": "Provisioning template not found"}
            run.completed_at = _utcnow()
            await session.commit()
            return {"status": "failed", "reason": "missing_template"}

        archive_path = _template_archive_path(template)
        if not archive_path.is_file():
            run.status = "failed"
            run.result_summary = {"error": "Template archive file is missing from the server"}
            run.completed_at = _utcnow()
            await session.commit()
            return {"status": "failed", "reason": "missing_archive"}

        run.status = "running"
        run.started_at = _utcnow()
        await session.commit()

        results = []
        success_count = 0
        failed_count = 0
        normalized_target_ids = []
        for raw_host_id in run.target_host_ids or []:
            try:
                host_id = int(raw_host_id)
            except Exception:
                continue
            if host_id not in normalized_target_ids:
                normalized_target_ids.append(host_id)

        for host_id in normalized_target_ids:
            host = await session.get(Host, host_id)
            if not host:
                failed_count += 1
                results.append({"host_id": host_id, "status": "failed", "error": "Target host not found"})
                continue
            host_os_family = _deduce_os_family(host.os)
            if template.os_family and template.os_family != "unknown" and host_os_family != template.os_family:
                failed_count += 1
                results.append({
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "failed",
                    "error": f"OS family mismatch: template={template.os_family}, host={host_os_family}",
                })
                continue
            if template.site_scope and host.site and host.site != template.site_scope and not run.allow_cross_site:
                failed_count += 1
                results.append({
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "failed",
                    "error": f"Site mismatch: template is scoped to {template.site_scope}",
                })
                continue
            if not host.is_online:
                failed_count += 1
                results.append({
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "failed",
                    "error": "Target host is offline",
                })
                continue
            try:
                payload = await _upload_archive_to_target(host, archive_path, template.name, session)
                success_count += 1
                results.append({
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "success",
                    "response": payload,
                })
            except Exception as exc:
                failed_count += 1
                results.append({
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "failed",
                    "error": str(exc),
                })

        run.completed_at = _utcnow()
        run.updated_at = run.completed_at
        run.result_summary = {
            "total_targets": len(normalized_target_ids),
            "success_count": success_count,
            "failed_count": failed_count,
            "targets": results,
        }
        if failed_count == 0:
            run.status = "success"
        elif success_count == 0:
            run.status = "failed"
        else:
            run.status = "partial_success"
        await session.commit()
        return {
            "status": run.status,
            "run_id": run.id,
            "success_count": success_count,
            "failed_count": failed_count,
        }


@router.get("/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_provisioning_access()
    query = (
        select(ProvisioningTemplate)
        .options(selectinload(ProvisioningTemplate.source_host))
        .order_by(ProvisioningTemplate.name.asc())
    )
    if user.role not in {UserRole.admin, UserRole.operator}:
        query = query.where(ProvisioningTemplate.is_enabled == True)
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_template_public(row) for row in rows]}


@router.post("/templates/capture")
async def capture_template(
    body: ProvisioningTemplateCapture,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _ensure_provisioning_access()
    existing = await db.execute(select(ProvisioningTemplate).where(ProvisioningTemplate.name == body.name.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A provisioning template with this name already exists")

    host = await db.get(Host, body.host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Source host not found")

    archive_blob = await _download_snapshot_archive(host, body.snapshot_name, db)
    archive_file_name, archive_size_bytes, archive_checksum = _write_archive_file(archive_blob, body.name)

    template = ProvisioningTemplate(
        name=body.name.strip(),
        description=(body.description or "").strip(),
        source_host_id=host.id,
        source_snapshot_name=_safe_snapshot_name(body.snapshot_name),
        snapshot_mode=str(body.snapshot_mode or "full_system").strip().lower() or "full_system",
        os_family=_deduce_os_family(host.os),
        platform_label=" ".join(part for part in [host.os or "", host.os_version or ""] if part).strip(),
        site_scope=(body.site_scope.strip() if body.site_scope is not None else (host.site or "")),
        hardware_profile=dict(host.hardware_inventory or {}),
        labels=_normalize_labels(body.labels),
        archive_file_name=archive_file_name,
        archive_checksum=archive_checksum,
        archive_size_bytes=archive_size_bytes,
        is_enabled=True,
        created_by=user.username,
        last_verified_at=_utcnow(),
    )
    db.add(template)
    await db.flush()
    query = (
        select(ProvisioningTemplate)
        .options(selectinload(ProvisioningTemplate.source_host))
        .where(ProvisioningTemplate.id == template.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _template_public(fresh)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    body: ProvisioningTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _ensure_provisioning_access()
    template = await db.get(ProvisioningTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Provisioning template not found")
    if body.name.strip() != template.name:
        existing = await db.execute(
            select(ProvisioningTemplate).where(
                ProvisioningTemplate.name == body.name.strip(),
                ProvisioningTemplate.id != template_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Another provisioning template already uses this name")
    template.name = body.name.strip()
    template.description = (body.description or "").strip()
    template.labels = _normalize_labels(body.labels)
    template.site_scope = (body.site_scope or "").strip()
    template.is_enabled = bool(body.is_enabled)
    template.updated_at = _utcnow()
    await db.flush()
    query = (
        select(ProvisioningTemplate)
        .options(selectinload(ProvisioningTemplate.source_host))
        .where(ProvisioningTemplate.id == template.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _template_public(fresh)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _ensure_provisioning_access()
    template = await db.get(ProvisioningTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Provisioning template not found")
    archive_path = _template_archive_path(template)
    await db.delete(template)
    await db.flush()
    try:
        if archive_path.is_file():
            archive_path.unlink()
    except Exception:
        pass
    return {"status": "deleted", "id": template_id}


@router.get("/runs")
async def list_runs(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    _ensure_provisioning_access()
    query = (
        select(ProvisioningRun)
        .options(selectinload(ProvisioningRun.template))
        .order_by(desc(ProvisioningRun.created_at))
        .limit(max(1, min(limit, 500)))
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_run_public(row) for row in rows]}


@router.post("/runs")
async def create_run(
    body: ProvisioningRunCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _ensure_provisioning_access()
    template = await db.get(ProvisioningTemplate, body.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Provisioning template not found")
    if not template.is_enabled:
        raise HTTPException(status_code=409, detail="Provisioning template is disabled")

    target_host_ids = []
    for raw in body.target_host_ids:
        try:
            host_id = int(raw)
        except Exception:
            continue
        if host_id not in target_host_ids:
            target_host_ids.append(host_id)
    if not target_host_ids:
        raise HTTPException(status_code=400, detail="At least one target host is required")

    run = ProvisioningRun(
        template_id=template.id,
        initiated_by=user.username,
        mode="reimage",
        status="pending",
        allow_cross_site=body.allow_cross_site,
        target_host_ids=target_host_ids,
        result_summary={},
    )
    db.add(run)
    await db.flush()

    async def _runner():
        return await _run_provisioning_rollout(run.id)

    queue_job = await enqueue_operation(
        op_type="provisioning.rollout",
        payload={"run_id": run.id, "template_id": template.id, "target_host_ids": target_host_ids},
        runner=_runner,
        requested_by=user.username,
    )
    run.queue_job_id = str(queue_job.get("id", ""))
    await db.flush()
    query = (
        select(ProvisioningRun)
        .options(selectinload(ProvisioningRun.template))
        .where(ProvisioningRun.id == run.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return {"status": "accepted", "run": _run_public(fresh), "job": queue_job}
