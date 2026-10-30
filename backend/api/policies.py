import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.agent_proxy import _agent_auth_headers as _agent_run_headers
from api.agent_proxy import _agent_url_for_host_id
from api.ops_queue import enqueue_operation
from api.dependency_resolver import (
    DependencyResolver,
    resolve_dependencies,
    PackageMetadata,
    parse_package_metadata,
    DependencyError,
    CircularDependencyError,
)
from auth import get_current_user, require_role
from database import async_session, get_db
from models.db_models import (
    AdminTaskExecution,
    AdminTaskTemplate,
    Host,
    Policy,
    PolicyExecution,
    PolicyRevision,
    User,
    UserRole,
)

logger = logging.getLogger("patchmaster.policies")

router = APIRouter(prefix="/api/policies", tags=["Policies"])

AGENT_PORT = 8080
_GLOBAL_AGENT_API_TOKEN = os.environ.get("AGENT_API_TOKEN", "").strip()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _agent_auth_headers(host=None) -> dict:
    token = (getattr(host, "agent_token", None) or "").strip() if host else ""
    if not token:
        token = _GLOBAL_AGENT_API_TOKEN
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _ensure_policy_schema(db: AsyncSession) -> None:
    stmts = [
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS active_revision_id INTEGER NULL;",
        "ALTER TABLE policies ADD COLUMN IF NOT EXISTS latest_revision_number INTEGER DEFAULT 0;",
        """
        CREATE TABLE IF NOT EXISTS policy_revisions (
            id SERIAL PRIMARY KEY,
            policy_id INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            yaml_content TEXT NOT NULL,
            status VARCHAR(24) DEFAULT 'draft',
            change_summary TEXT DEFAULT '',
            created_by VARCHAR(100) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS policy_executions (
            id SERIAL PRIMARY KEY,
            policy_id INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
            revision_id INTEGER NULL REFERENCES policy_revisions(id) ON DELETE SET NULL,
            execution_mode VARCHAR(24) DEFAULT 'apply',
            status VARCHAR(24) DEFAULT 'pending',
            requested_by VARCHAR(100) DEFAULT '',
            host_ids JSONB DEFAULT '[]'::jsonb,
            host_results JSONB DEFAULT '[]'::jsonb,
            guardrails JSONB DEFAULT '{}'::jsonb,
            summary JSONB DEFAULT '{}'::jsonb,
            queue_job_id VARCHAR(64) DEFAULT '',
            requested_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_task_templates (
            id SERIAL PRIMARY KEY,
            name VARCHAR(160) NOT NULL UNIQUE,
            task_key VARCHAR(80) NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            command_template TEXT DEFAULT '',
            default_timeout_seconds INTEGER DEFAULT 120,
            default_working_dir VARCHAR(255) DEFAULT '',
            allowed_roles JSONB DEFAULT '[]'::jsonb,
            is_enabled BOOLEAN DEFAULT TRUE,
            created_by VARCHAR(100) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_task_executions (
            id SERIAL PRIMARY KEY,
            template_id INTEGER NULL REFERENCES admin_task_templates(id) ON DELETE SET NULL,
            host_id INTEGER NULL REFERENCES hosts(id) ON DELETE SET NULL,
            task_key VARCHAR(80) NOT NULL DEFAULT '',
            execution_mode VARCHAR(24) DEFAULT 'queued',
            status VARCHAR(24) DEFAULT 'pending',
            requested_by VARCHAR(100) DEFAULT '',
            queue_job_id VARCHAR(64) DEFAULT '',
            parameters JSONB DEFAULT '{}'::jsonb,
            result_summary JSONB DEFAULT '{}'::jsonb,
            requested_at TIMESTAMP DEFAULT NOW(),
            completed_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_policy_revisions_policy ON policy_revisions(policy_id, revision_number);",
        "CREATE INDEX IF NOT EXISTS ix_policy_revisions_status ON policy_revisions(status);",
        "CREATE INDEX IF NOT EXISTS ix_policy_executions_policy ON policy_executions(policy_id, requested_at);",
        "CREATE INDEX IF NOT EXISTS ix_policy_executions_status ON policy_executions(status);",
        "CREATE INDEX IF NOT EXISTS ix_admin_task_templates_enabled ON admin_task_templates(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_admin_task_executions_status ON admin_task_executions(status);",
    ]
    for stmt in stmts:
        await db.execute(text(stmt))


_DEFAULT_ADMIN_TASKS = [
    {
        "task_key": "install_boot_relay_services",
        "name": "Install Boot Relay Services",
        "description": "Install or refresh the managed PXE relay services on a target host.",
        "command_template": (
            "set -euo pipefail\n"
            "TMP_DIR=$(mktemp -d)\n"
            'curl -fsSL {{bundle_url}} -o "$TMP_DIR/relay-bundle.tar.gz"\n'
            'tar -xzf "$TMP_DIR/relay-bundle.tar.gz" -C "$TMP_DIR"\n'
            'bash "$TMP_DIR/scripts/install-boot-host.sh"\n'
        ),
        "default_timeout_seconds": 240,
        "default_working_dir": "",
        "allowed_roles": ["admin", "operator"],
    },
    {
        "task_key": "sync_boot_relay_artifacts",
        "name": "Sync Boot Relay Artifacts",
        "description": "Re-apply the current PXE relay bundle to a host.",
        "command_template": (
            "set -euo pipefail\n"
            "TMP_DIR=$(mktemp -d)\n"
            'curl -fsSL {{bundle_url}} -o "$TMP_DIR/relay-bundle.tar.gz"\n'
            'tar -xzf "$TMP_DIR/relay-bundle.tar.gz" -C "$TMP_DIR"\n'
            'bash "$TMP_DIR/scripts/install-boot-host.sh"\n'
        ),
        "default_timeout_seconds": 240,
        "default_working_dir": "",
        "allowed_roles": ["admin", "operator"],
    },
    {
        "task_key": "validate_boot_relay",
        "name": "Validate Boot Relay",
        "description": "Validate dnsmasq, nginx, and core boot relay files on the target host.",
        "command_template": (
            "set -euo pipefail\n"
            "dnsmasq --test\n"
            "nginx -t\n"
            "test -f /etc/dnsmasq.d/patchmaster-network-boot.conf\n"
            "test -f /etc/nginx/sites-available/patchmaster-network-boot.conf\n"
        ),
        "default_timeout_seconds": 120,
        "default_working_dir": "",
        "allowed_roles": ["admin", "operator", "auditor"],
    },
    {
        "task_key": "refresh_package_metadata",
        "name": "Refresh Package Metadata",
        "description": "Refresh OS package metadata on a managed host.",
        "command_template": (
            "if command -v apt-get >/dev/null 2>&1; then apt-get update -qq; "
            "elif command -v dnf >/dev/null 2>&1; then dnf makecache -q; "
            "elif command -v yum >/dev/null 2>&1; then yum makecache -q; fi"
        ),
        "default_timeout_seconds": 180,
        "default_working_dir": "",
        "allowed_roles": ["admin", "operator"],
    },
    {
        "task_key": "run_host_prechecks",
        "name": "Run Host Prechecks",
        "description": "Collect quick pre-flight checks for disk, memory, and service state on a target host.",
        "command_template": (
            "set -e\n"
            "echo '[precheck] uname'; uname -a\n"
            "echo '[precheck] disk'; df -h /\n"
            "echo '[precheck] memory'; free -m || true\n"
            "echo '[precheck] system'; systemctl is-system-running || true\n"
        ),
        "default_timeout_seconds": 120,
        "default_working_dir": "",
        "allowed_roles": ["admin", "operator", "auditor"],
    },
]


async def _seed_admin_task_templates(db: AsyncSession) -> None:
    existing = (
        (
            await db.execute(
                select(AdminTaskTemplate).where(
                    AdminTaskTemplate.task_key.in_(
                        [row["task_key"] for row in _DEFAULT_ADMIN_TASKS]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    existing_keys = {row.task_key for row in existing}
    for row in _DEFAULT_ADMIN_TASKS:
        if row["task_key"] in existing_keys:
            continue
        db.add(AdminTaskTemplate(created_by="system", is_enabled=True, **row))
    await db.flush()


class PolicyBase(BaseModel):
    name: str
    description: Optional[str] = None
    yaml_content: str


class PolicyCreate(PolicyBase):
    change_summary: str = ""


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    yaml_content: Optional[str] = None
    change_summary: str = ""


class PolicyApplyRequest(BaseModel):
    host_ids: list[int] = Field(default_factory=list)
    guardrails: dict[str, Any] = Field(default_factory=dict)


class AdminTaskExecuteRequest(BaseModel):
    template_id: int
    host_id: int
    parameters: dict[str, Any] = Field(default_factory=dict)


class PolicyResponse(PolicyBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


def _policy_revision_public(revision: PolicyRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "policy_id": revision.policy_id,
        "revision_number": revision.revision_number,
        "name": revision.name,
        "description": revision.description or "",
        "yaml_content": revision.yaml_content,
        "status": revision.status,
        "change_summary": revision.change_summary or "",
        "created_by": revision.created_by or "",
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
    }


def _policy_execution_public(execution: PolicyExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "policy_id": execution.policy_id,
        "revision_id": execution.revision_id,
        "execution_mode": execution.execution_mode,
        "status": execution.status,
        "requested_by": execution.requested_by or "",
        "host_ids": list(execution.host_ids or []),
        "host_results": list(execution.host_results or []),
        "guardrails": dict(execution.guardrails or {}),
        "summary": dict(execution.summary or {}),
        "queue_job_id": execution.queue_job_id or "",
        "requested_at": execution.requested_at.isoformat()
        if execution.requested_at
        else None,
        "completed_at": execution.completed_at.isoformat()
        if execution.completed_at
        else None,
    }


def _policy_public(policy: Policy) -> dict[str, Any]:
    revisions = list(getattr(policy, "revisions", []) or [])
    active_revision = None
    for revision in revisions:
        if (
            revision.id == getattr(policy, "active_revision_id", None)
            or revision.status == "active"
        ):
            active_revision = revision
            break
    latest_revision = max(revisions, key=lambda row: row.revision_number, default=None)
    last_execution = max(
        list(getattr(policy, "executions", []) or []),
        key=lambda row: row.requested_at or datetime.min,
        default=None,
    )
    return {
        "id": policy.id,
        "name": policy.name,
        "description": policy.description or "",
        "yaml_content": active_revision.yaml_content
        if active_revision
        else policy.yaml_content,
        "created_by": policy.created_by or "",
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
        "active_revision_id": getattr(policy, "active_revision_id", None),
        "latest_revision_number": int(
            getattr(policy, "latest_revision_number", 0) or 0
        ),
        "revision_count": len(revisions),
        "active_revision": _policy_revision_public(active_revision)
        if active_revision
        else None,
        "latest_revision": _policy_revision_public(latest_revision)
        if latest_revision
        else None,
        "last_execution": _policy_execution_public(last_execution)
        if last_execution
        else None,
    }


def _admin_task_template_public(template: AdminTaskTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "task_key": template.task_key,
        "description": template.description or "",
        "default_timeout_seconds": int(template.default_timeout_seconds or 120),
        "default_working_dir": template.default_working_dir or "",
        "allowed_roles": list(template.allowed_roles or []),
        "is_enabled": bool(template.is_enabled),
        "created_by": template.created_by or "",
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


def _admin_task_execution_public(execution: AdminTaskExecution) -> dict[str, Any]:
    template = getattr(execution, "template", None)
    host = getattr(execution, "host", None)
    return {
        "id": execution.id,
        "template_id": execution.template_id,
        "task_key": execution.task_key,
        "execution_mode": execution.execution_mode,
        "status": execution.status,
        "requested_by": execution.requested_by or "",
        "queue_job_id": execution.queue_job_id or "",
        "parameters": dict(execution.parameters or {}),
        "result_summary": dict(execution.result_summary or {}),
        "requested_at": execution.requested_at.isoformat()
        if execution.requested_at
        else None,
        "completed_at": execution.completed_at.isoformat()
        if execution.completed_at
        else None,
        "template": _admin_task_template_public(template) if template else None,
        "host": {
            "id": host.id,
            "hostname": host.hostname,
            "ip": host.ip,
            "site": host.site or "",
            "os": host.os or "",
        }
        if host
        else None,
    }


async def _get_policy_with_relations(db: AsyncSession, policy_id: int) -> Policy | None:
    query = (
        select(Policy)
        .options(selectinload(Policy.revisions), selectinload(Policy.executions))
        .where(Policy.id == policy_id)
    )
    return (await db.execute(query)).scalar_one_or_none()


def _parse_yaml(yaml_content: str) -> None:
    try:
        yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}")


async def _get_revision(
    db: AsyncSession, policy: Policy, revision_id: int | None
) -> PolicyRevision | None:
    revisions = list(getattr(policy, "revisions", []) or [])
    if revision_id is None:
        for revision in revisions:
            if (
                revision.id == getattr(policy, "active_revision_id", None)
                or revision.status == "active"
            ):
                return revision
        return max(revisions, key=lambda row: row.revision_number, default=None)
    for revision in revisions:
        if revision.id == revision_id:
            return revision
    return await db.get(PolicyRevision, revision_id)


def _render_command_template(command_template: str, parameters: dict[str, Any]) -> str:
    command = str(command_template or "")
    for key, value in (parameters or {}).items():
        command = command.replace(f"{{{{{key}}}}}", str(value))
    if "{{" in command or "}}" in command:
        raise HTTPException(
            status_code=400,
            detail="Missing template parameters for admin task execution",
        )
    return command


async def _run_command_on_host(
    db: AsyncSession, host_id: int, command: str, timeout: int, working_dir: str = ""
) -> dict[str, Any]:
    host, url = await _agent_url_for_host_id(host_id, "/run", db)
    async with httpx.AsyncClient(timeout=float(timeout) + 10.0) as client:
        response = await client.post(
            url,
            json={"command": command, "timeout": timeout, "working_dir": working_dir},
            headers=_agent_run_headers(host),
        )
        payload = response.json()
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=payload.get("error")
            or payload.get("detail")
            or "Agent command failed",
        )
    payload.setdefault("host_id", host.id)
    payload.setdefault("host_ip", host.ip)
    return payload


async def apply_policy_on_host(host_ip: str, policy_content: str, host=None) -> dict:
    url = f"http://{host_ip}:{AGENT_PORT}/policy/apply"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url, json={"policy": policy_content}, headers=_agent_auth_headers(host)
            )
            if resp.status_code == 200:
                result = resp.json()
                logger.info("Policy applied on %s: %s", host_ip, result)
                return {"host": host_ip, "success": True, "result": result}
            logger.error(
                "Failed to apply policy on %s (HTTP %s): %s",
                host_ip,
                resp.status_code,
                resp.text,
            )
            return {
                "host": host_ip,
                "success": False,
                "error": resp.text,
                "status_code": resp.status_code,
            }
    except Exception as exc:
        logger.error("Connection error applying policy on %s: %s", host_ip, exc)
        return {"host": host_ip, "success": False, "error": str(exc)}


async def _write_policy_execution(
    db: AsyncSession,
    policy: Policy,
    revision: PolicyRevision | None,
    mode: str,
    host_ids: list[int],
    results: list[dict[str, Any]],
    requested_by: str,
    guardrails: dict[str, Any] | None,
) -> PolicyExecution | None:
    if not hasattr(db, "add"):
        return None
    summary = {
        "host_count": len(host_ids),
        "succeeded": len([row for row in results if row.get("success")]),
        "failed": len([row for row in results if not row.get("success")]),
    }
    execution = PolicyExecution(
        policy_id=policy.id,
        revision_id=revision.id if revision else None,
        execution_mode=mode,
        status="completed",
        requested_by=requested_by,
        host_ids=list(host_ids),
        host_results=list(results),
        guardrails=dict(guardrails or {}),
        summary=summary,
        requested_at=_utcnow(),
        completed_at=_utcnow(),
    )
    db.add(execution)
    await db.flush()
    return execution


async def apply_policy_to_hosts(
    policy_id: int,
    host_ids: list[int],
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    current_user: User,
    *,
    revision_id: int | None = None,
    mode: str = "apply",
    guardrails: dict[str, Any] | None = None,
):
    policy_result = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy = policy_result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    revision = None
    if revision_id is not None:
        try:
            policy_full = await _get_policy_with_relations(db, policy_id)
            if policy_full:
                policy = policy_full
                revision = await _get_revision(db, policy, revision_id)
        except Exception:
            revision = None
    policy_content = revision.yaml_content if revision else policy.yaml_content
    hosts_result = await db.execute(select(Host).where(Host.id.in_(host_ids)))
    hosts = hosts_result.scalars().all()
    if not hosts:
        raise HTTPException(status_code=404, detail="No valid hosts found")
    if mode == "dry_run":
        results = [
            {
                "host": host.ip,
                "success": True,
                "result": {
                    "would_apply": True,
                    "policy_revision_id": revision.id
                    if revision
                    else getattr(policy, "active_revision_id", None),
                    "guardrails": dict(guardrails or {}),
                },
            }
            for host in hosts
        ]
    else:
        tasks = [apply_policy_on_host(host.ip, policy_content, host) for host in hosts]
        results = list(await asyncio.gather(*tasks, return_exceptions=False))
    succeeded = [row for row in results if row.get("success")]
    failed = [row for row in results if not row.get("success")]
    execution = None
    if hasattr(db, "add"):
        execution = await _write_policy_execution(
            db,
            policy,
            revision,
            mode,
            host_ids,
            results,
            current_user.username,
            guardrails,
        )
        if hasattr(db, "commit"):
            await db.commit()
    return {
        "status": "completed",
        "execution_mode": mode,
        "host_count": len(hosts),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "results": results,
        "execution": _policy_execution_public(execution) if execution else None,
    }


async def _execute_admin_task_run(execution_id: int) -> dict[str, Any]:
    async with async_session() as db:
        query = (
            select(AdminTaskExecution)
            .options(
                selectinload(AdminTaskExecution.template),
                selectinload(AdminTaskExecution.host),
            )
            .where(AdminTaskExecution.id == execution_id)
        )
        execution = (await db.execute(query)).scalar_one_or_none()
        if not execution:
            raise HTTPException(
                status_code=404, detail="Admin task execution not found"
            )
        template = execution.template
        if not template:
            raise HTTPException(status_code=404, detail="Admin task template not found")
        command = _render_command_template(
            template.command_template, dict(execution.parameters or {})
        )
        execution.status = "running"
        await db.commit()
        result = await _run_command_on_host(
            db,
            execution.host_id,
            command,
            int(template.default_timeout_seconds or 120),
            template.default_working_dir or "",
        )
        execution.status = "success" if int(result.get("rc", 1)) == 0 else "failed"
        execution.completed_at = _utcnow()
        execution.result_summary = {
            "rc": int(result.get("rc", 1)),
            "output": str(result.get("output", "") or "")[:4000],
            "host_ip": result.get("host_ip"),
        }
        await db.commit()
        return _admin_task_execution_public(execution)


@router.post("/", response_model=PolicyResponse)
async def create_policy(
    policy: PolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _parse_yaml(policy.yaml_content)
    new_policy = Policy(
        name=policy.name,
        description=policy.description,
        yaml_content=policy.yaml_content,
        active_revision_id=None,
        latest_revision_number=1,
        created_by=current_user.username,
    )
    db.add(new_policy)
    await db.flush()
    revision = PolicyRevision(
        policy_id=new_policy.id,
        revision_number=1,
        name=policy.name,
        description=policy.description or "",
        yaml_content=policy.yaml_content,
        status="active",
        change_summary=policy.change_summary or "Initial policy revision",
        created_by=current_user.username,
    )
    db.add(revision)
    await db.flush()
    new_policy.active_revision_id = revision.id
    await db.commit()
    await db.refresh(new_policy)
    return new_policy


@router.get("/")
async def list_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Policy)
        .options(selectinload(Policy.revisions), selectinload(Policy.executions))
        .order_by(desc(Policy.created_at))
    )
    rows = (await db.execute(query)).scalars().all()
    return [_policy_public(row) for row in rows]


@router.put("/{policy_id}")
async def update_policy(
    policy_id: int,
    body: PolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    policy = await _get_policy_with_relations(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    active_revision = await _get_revision(db, policy, policy.active_revision_id)
    yaml_content = (
        body.yaml_content
        if body.yaml_content is not None
        else (active_revision.yaml_content if active_revision else policy.yaml_content)
    )
    _parse_yaml(yaml_content)
    if body.name is not None:
        policy.name = body.name
    if body.description is not None:
        policy.description = body.description
    next_revision = int(policy.latest_revision_number or 0) + 1
    revision = PolicyRevision(
        policy_id=policy.id,
        revision_number=next_revision,
        name=policy.name,
        description=policy.description or "",
        yaml_content=yaml_content,
        status="draft",
        change_summary=body.change_summary or "Draft revision update",
        created_by=current_user.username,
    )
    db.add(revision)
    policy.latest_revision_number = next_revision
    policy.updated_at = _utcnow()
    await db.commit()
    fresh = await _get_policy_with_relations(db, policy_id)
    return {
        "policy": _policy_public(fresh),
        "draft_revision": _policy_revision_public(revision),
    }


@router.delete("/{policy_id}")
async def delete_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    await db.delete(policy)
    await db.commit()
    return {"ok": True}


@router.get("/{policy_id}/revisions")
async def list_policy_revisions(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(PolicyRevision)
        .where(PolicyRevision.policy_id == policy_id)
        .order_by(PolicyRevision.revision_number.desc())
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_policy_revision_public(row) for row in rows]}


@router.get("/{policy_id}/executions")
async def list_policy_executions(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(PolicyExecution)
        .where(PolicyExecution.policy_id == policy_id)
        .order_by(PolicyExecution.requested_at.desc())
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_policy_execution_public(row) for row in rows]}


@router.post("/{policy_id}/revisions/{revision_id}/activate")
async def activate_policy_revision(
    policy_id: int,
    revision_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    policy = await _get_policy_with_relations(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    revision = await _get_revision(db, policy, revision_id)
    if not revision or revision.policy_id != policy.id:
        raise HTTPException(status_code=404, detail="Policy revision not found")
    for row in list(policy.revisions or []):
        row.status = "archived"
    revision.status = "active"
    policy.active_revision_id = revision.id
    policy.yaml_content = revision.yaml_content
    policy.name = revision.name
    policy.description = revision.description
    policy.updated_at = _utcnow()
    await db.commit()
    fresh = await _get_policy_with_relations(db, policy_id)
    return {
        "status": "ok",
        "policy": _policy_public(fresh),
        "active_revision": _policy_revision_public(revision),
    }


@router.post("/{policy_id}/revisions/{revision_id}/dry-run")
async def dry_run_policy_revision(
    policy_id: int,
    revision_id: int,
    body: PolicyApplyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    return await apply_policy_to_hosts(
        policy_id,
        body.host_ids,
        background_tasks,
        db,
        current_user,
        revision_id=revision_id,
        mode="dry_run",
        guardrails=body.guardrails,
    )


@router.post("/{policy_id}/revisions/{revision_id}/apply")
async def apply_policy_revision(
    policy_id: int,
    revision_id: int,
    body: PolicyApplyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await apply_policy_to_hosts(
        policy_id,
        body.host_ids,
        background_tasks,
        db,
        current_user,
        revision_id=revision_id,
        mode="apply",
        guardrails=body.guardrails,
    )


@router.post("/{policy_id}/rollback/{revision_id}")
async def rollback_policy_revision(
    policy_id: int,
    revision_id: int,
    body: PolicyApplyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    policy = await _get_policy_with_relations(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    revision = await _get_revision(db, policy, revision_id)
    if not revision or revision.policy_id != policy.id:
        raise HTTPException(status_code=404, detail="Policy revision not found")
    for row in list(policy.revisions or []):
        row.status = "archived"
    revision.status = "active"
    policy.active_revision_id = revision.id
    policy.yaml_content = revision.yaml_content
    policy.name = revision.name
    policy.description = revision.description
    await db.commit()
    return await apply_policy_to_hosts(
        policy_id,
        body.host_ids,
        background_tasks,
        db,
        current_user,
        revision_id=revision.id,
        mode="rollback",
        guardrails=body.guardrails,
    )


@router.post("/{policy_id}/apply")
async def apply_policy_route(
    policy_id: int,
    body: PolicyApplyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    policy = await _get_policy_with_relations(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return await apply_policy_to_hosts(
        policy_id,
        body.host_ids,
        background_tasks,
        db,
        current_user,
        revision_id=policy.active_revision_id,
        mode="apply",
        guardrails=body.guardrails,
    )


@router.get("/admin-tasks/templates")
async def list_admin_task_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _seed_admin_task_templates(db)
    await db.commit()
    rows = (
        (
            await db.execute(
                select(AdminTaskTemplate).order_by(AdminTaskTemplate.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_admin_task_template_public(row) for row in rows]}


@router.get("/admin-tasks/executions")
async def list_admin_task_executions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(AdminTaskExecution)
        .options(
            selectinload(AdminTaskExecution.template),
            selectinload(AdminTaskExecution.host),
        )
        .order_by(AdminTaskExecution.requested_at.desc())
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_admin_task_execution_public(row) for row in rows]}


@router.post("/admin-tasks/execute")
async def execute_admin_task(
    body: AdminTaskExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    await _seed_admin_task_templates(db)
    template = await db.get(AdminTaskTemplate, body.template_id)
    if not template or not template.is_enabled:
        raise HTTPException(status_code=404, detail="Admin task template not found")
    host = await db.get(Host, body.host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    allowed_roles = {str(role) for role in list(template.allowed_roles or [])}
    if allowed_roles and current_user.role.value not in allowed_roles:
        raise HTTPException(
            status_code=403, detail="Current role cannot execute this admin task"
        )
    execution = AdminTaskExecution(
        template_id=template.id,
        host_id=host.id,
        task_key=template.task_key,
        execution_mode="queued",
        status="pending",
        requested_by=current_user.username,
        parameters=dict(body.parameters or {}),
        result_summary={},
    )
    db.add(execution)
    await db.flush()

    async def runner():
        return await _execute_admin_task_run(execution.id)

    queue_job = await enqueue_operation(
        op_type=f"admin_task.{template.task_key}",
        payload={
            "template_id": template.id,
            "task_key": template.task_key,
            "host_id": host.id,
        },
        runner=runner,
        requested_by=current_user.username,
    )
    execution.queue_job_id = queue_job["id"]
    await db.commit()
    query = (
        select(AdminTaskExecution)
        .options(
            selectinload(AdminTaskExecution.template),
            selectinload(AdminTaskExecution.host),
        )
        .where(AdminTaskExecution.id == execution.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return {
        "status": "accepted",
        "execution": _admin_task_execution_public(fresh),
        "job": queue_job,
    }


# ─── Dependency Resolution Endpoints ───────────────────────────────────────


class ResolveDependenciesRequest(BaseModel):
    """Request model for resolving patch dependencies."""

    packages: list[dict[str, Any]]


@router.post("/resolve-dependencies")
async def resolve_policy_dependencies(
    body: ResolveDependenciesRequest,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Resolve dependencies between patches and return installation order.

    Provide a list of packages with their dependencies to get the correct
    installation order using topological sort.
    """
    try:
        # Parse package metadata
        packages_metadata = {}
        for pkg in body.packages:
            metadata = parse_package_metadata(pkg)
            packages_metadata[metadata.package_id] = metadata

        # Resolve dependencies
        package_ids = [pkg.get("id") for pkg in body.packages if pkg.get("id")]
        resolved_order = resolve_dependencies(package_ids, packages_metadata)

        return {
            "status": "success",
            "resolved_order": resolved_order,
            "packages_resolved": len(resolved_order),
        }
    except CircularDependencyError as e:
        raise HTTPException(
            status_code=400, detail=f"Circular dependency detected: {str(e)}"
        )
    except DependencyError as e:
        raise HTTPException(
            status_code=400, detail=f"Dependency resolution failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to resolve dependencies: {str(e)}"
        )
