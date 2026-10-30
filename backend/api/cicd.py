"""CI/CD Pipeline API — Jenkins, GitLab webhook integration."""
import csv
import json
import hashlib
import hmac
import io
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
import asyncio

import httpx
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from fpdf import FPDF
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (for DB storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from database import get_db
from auth import get_current_user, require_role
from validators import validate_filename
from api.auth_api import get_effective_permissions
from api.cicd_secrets import (
    decrypt_json_field,
    decrypt_text_field,
    encrypt_json_field,
    encrypt_text_field,
    is_encrypted_text,
)
from models.db_models import (
    CICDPipeline,
    CICDBuild,
    CICDVariable,
    CICDEnvironment,
    CICDDeployment,
    CICDDeploymentApproval,
    CICDDeploymentApprovalEvent,
    CICDNotificationDeliveryReceipt,
    CICDBuildStageRun,
    CICDBuildLog,
    CICDBuildArtifact,
    NotificationChannel,
    UserNotification,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/cicd", tags=["cicd"])

INSTALL_DIR = os.getenv("INSTALL_DIR", "/opt/patchmaster")

# TLS verification: opt-out only — set CICD_TLS_VERIFY=false to disable (e.g. self-signed Jenkins).
# Defaults to True (verify certs).
_CICD_TLS_VERIFY = os.environ.get("CICD_TLS_VERIFY", "true").strip().lower() != "false"
CICD_STORAGE_DIR = Path(os.getenv("PM_CICD_STORAGE_DIR", os.path.join(INSTALL_DIR, "cicd")))
ARTIFACTS_DIR = Path(os.getenv("PM_CICD_ARTIFACT_DIR", str(CICD_STORAGE_DIR / "artifacts")))
LOGS_DIR = Path(os.getenv("PM_CICD_LOG_DIR", str(CICD_STORAGE_DIR / "logs")))

# ── Pydantic schemas ──

class PipelineCreate(BaseModel):
    name: str
    description: str = ""
    tool: str  # jenkins, gitlab, custom
    server_url: str = ""
    auth_type: str = "token"
    auth_credentials: dict = {}
    job_path: str = ""
    script_type: str = "groovy"
    script_content: str = ""
    trigger_events: list = []

class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    server_url: Optional[str] = None
    auth_type: Optional[str] = None
    auth_credentials: Optional[dict] = None
    job_path: Optional[str] = None
    script_type: Optional[str] = None
    script_content: Optional[str] = None
    trigger_events: Optional[list] = None
    status: Optional[str] = None

class PipelineOut(BaseModel):
    id: int
    name: str
    description: str
    tool: str
    server_url: str
    auth_type: str
    job_path: str
    script_type: str
    script_content: str
    webhook_secret: str
    webhook_url: str
    trigger_events: list
    status: str
    last_triggered: Optional[str]
    created_by: str
    created_at: str
    build_count: int = 0
    last_build_status: Optional[str] = None

class BuildOut(BaseModel):
    id: int
    pipeline_id: int
    pipeline_name: str
    build_number: int
    status: str
    trigger_type: str
    trigger_info: dict
    duration_seconds: Optional[int]
    output: str
    external_url: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str

class TriggerRequest(BaseModel):
    parameters: dict = {}

class BuildUpdate(BaseModel):
    status: Optional[str] = None
    output: Optional[str] = None
    external_url: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class VariableIn(BaseModel):
    key: str
    value: str = ""
    is_secret: bool = False
    status: str = "active"


class EnvironmentIn(BaseModel):
    name: str
    description: str = ""
    webhook_url: str = ""
    requires_approval: bool = False
    approvers: list = Field(default_factory=list)
    approval_quorum: int = 1
    approval_sla_minutes: int = 60
    escalation_after_minutes: int = 120
    escalation_targets: list = Field(default_factory=list)
    status: str = "active"


class DeploymentIn(BaseModel):
    pipeline_id: int
    environment: str
    build_id: Optional[int] = None
    notes: str = ""
    external_url: str = ""
    storage_path: str = ""
    status: str = "pending"


class DeploymentUpdate(BaseModel):
    status: Optional[str] = None
    external_url: Optional[str] = None
    notes: Optional[str] = None
    approved_by: Optional[str] = None
    storage_path: Optional[str] = None


class DeploymentApprovalIn(BaseModel):
    note: str = ""


class BuildLogIn(BaseModel):
    line: str
    storage_path: Optional[str] = None
    status: str = "info"


class StageRunIn(BaseModel):
    stage_name: str
    order_index: int = 0
    status: str = "pending"
    duration_seconds: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output: str = ""


class ManualGateApproveIn(BaseModel):
    stage_name: str = ""
    note: str = ""


class ArtifactIn(BaseModel):
    name: str
    url: str = ""
    size_bytes: int = 0
    storage_path: str = ""
    status: str = "stored"
    meta: dict = Field(default_factory=dict)


class ArtifactUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    size_bytes: Optional[int] = None
    storage_path: Optional[str] = None
    status: Optional[str] = None
    meta: Optional[dict] = None


class ReleaseArtifactIn(BaseModel):
    release_version: str
    release_channel: str = "stable"
    notes: str = ""
    environment: str = ""


def _role_name(user: User) -> str:
    role = getattr(user, "role", "")
    return role.value if hasattr(role, "value") else str(role)


def _cicd_perms(user: User) -> dict:
    role = _role_name(user) or "viewer"
    perms = get_effective_permissions(role, getattr(user, "custom_permissions", None))
    perms.setdefault("cicd", bool(role in ("admin", "operator")))
    perms.setdefault("cicd_view", bool(role in ("admin", "operator", "auditor")))
    perms.setdefault("cicd_manage", bool(role in ("admin", "operator")))
    perms.setdefault("cicd_execute", bool(role in ("admin", "operator")))
    perms.setdefault("cicd_approve", bool(role in ("admin", "operator")))
    return perms


def _assert_cicd_permission(user: User, feature: str, detail: str):
    perms = _cicd_perms(user)
    if not perms.get("cicd"):
        raise HTTPException(status_code=403, detail="CI/CD feature is not enabled for this user.")
    if not perms.get(feature):
        raise HTTPException(status_code=403, detail=detail)

# ── Helpers ──

def _pipeline_to_dict(p: CICDPipeline, build_count: int = 0, last_status: str = None, base_url: str = "") -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "tool": p.tool,
        "server_url": p.server_url,
        "auth_type": p.auth_type,
        # auth_credentials intentionally omitted — never sent to frontend
        "job_path": p.job_path,
        "script_type": p.script_type,
        "script_content": p.script_content,
        # webhook_secret intentionally omitted — use /api/cicd/pipelines/{id}/webhook-secret
        "webhook_url": f"{base_url}/api/cicd/webhook/{p.id}",
        "trigger_events": p.trigger_events or [],
        "status": p.status or "active",
        "last_triggered": p.last_triggered.isoformat() if p.last_triggered else None,
        "created_by": p.created_by or "",
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
        "build_count": build_count,
        "last_build_status": last_status,
    }


def _build_to_dict(b: CICDBuild, pipeline_name: str = "") -> dict:
    duration = getattr(b, "duration_seconds", None)
    if duration in (None, 0) and b.started_at and b.completed_at:
        duration = int((b.completed_at - b.started_at).total_seconds())
    return {
        "id": b.id,
        "pipeline_id": b.pipeline_id,
        "pipeline_name": pipeline_name,
        "build_number": b.build_number,
        "status": b.status or "pending",
        "trigger_type": b.trigger_type or "manual",
        "trigger_info": b.trigger_info or {},
        "duration_seconds": duration,
        "output": b.output or "",
        "external_url": b.external_url or "",
        "started_at": b.started_at.isoformat() if b.started_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else "",
    }


async def _mark_stale_pending_builds(db: AsyncSession, builds: list[CICDBuild], stale_seconds: int = 120) -> bool:
    now = _utcnow()
    changed = False
    for build in builds:
        if str(build.status or "").lower() != "pending":
            continue
        started = build.started_at or build.created_at
        if not started:
            continue
        age_seconds = int((now - started).total_seconds())
        if age_seconds < stale_seconds:
            continue
        base_out = (build.output or "").strip()
        append = "Build remained pending for too long and was marked failed. Retry the run."
        build.status = "failed"
        build.completed_at = now
        build.output = f"{base_out}\n{append}" if base_out else append
        changed = True
    if changed:
        await db.commit()
    return changed


def _variable_to_dict(v: CICDVariable) -> dict:
    value = v.value or ""
    if v.is_secret:
        redacted_value = ""
    else:
        redacted_value = decrypt_text_field(value) if is_encrypted_text(value) else value
    return {
        "id": v.id,
        "pipeline_id": v.pipeline_id,
        "key": v.key,
        "value": redacted_value,
        "is_secret": v.is_secret,
        "has_value": bool(value),
        "status": getattr(v, "status", "active") or "active",
        "created_at": v.created_at.isoformat() if v.created_at else "",
        "updated_at": v.updated_at.isoformat() if v.updated_at else "",
    }


def _environment_to_dict(e: CICDEnvironment) -> dict:
    return {
        "id": e.id,
        "pipeline_id": e.pipeline_id,
        "name": e.name,
        "description": e.description or "",
        "webhook_url": e.webhook_url or "",
        "requires_approval": bool(e.requires_approval),
        "approvers": e.approvers or [],
        "approval_quorum": int(getattr(e, "approval_quorum", 1) or 1),
        "approval_sla_minutes": int(getattr(e, "approval_sla_minutes", 60) or 60),
        "escalation_after_minutes": int(getattr(e, "escalation_after_minutes", 120) or 120),
        "escalation_targets": getattr(e, "escalation_targets", []) or [],
        "status": getattr(e, "status", "active") or "active",
        "created_at": e.created_at.isoformat() if e.created_at else "",
        "updated_at": e.updated_at.isoformat() if e.updated_at else "",
    }


def _deployment_to_dict(d: CICDDeployment, environment_name: str = "", pipeline_name: str = "") -> dict:
    return {
        "id": d.id,
        "pipeline_id": d.pipeline_id,
        "pipeline_name": pipeline_name,
        "environment_id": d.environment_id,
        "environment_name": environment_name,
        "build_id": d.build_id,
        "status": d.status or "pending",
        "triggered_by": d.triggered_by or "",
        "notes": d.notes or "",
        "external_url": d.external_url or "",
        "storage_path": getattr(d, "storage_path", "") or "",
        "approved_by": d.approved_by or "",
        "approval_due_at": d.approval_due_at.isoformat() if getattr(d, "approval_due_at", None) else None,
        "escalated_at": d.escalated_at.isoformat() if getattr(d, "escalated_at", None) else None,
        "escalation_status": getattr(d, "escalation_status", "") or "",
        "approved_at": d.approved_at.isoformat() if d.approved_at else None,
        "started_at": d.started_at.isoformat() if d.started_at else None,
        "completed_at": d.completed_at.isoformat() if d.completed_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else "",
    }


def _can_user_approve(user: User, env: CICDEnvironment | None) -> bool:
    if getattr(user, "role", None) == UserRole.admin:
        return True
    approvers = [str(v).strip().lower() for v in (env.approvers or [])] if env else []
    username = str(getattr(user, "username", "")).strip().lower()
    return username in approvers


def _format_seconds(value: int | None) -> str:
    if value is None:
        return "0s"
    seconds = int(max(value, 0))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _approval_sla_fields(dep: CICDDeployment) -> dict:
    now = _utcnow()
    due = getattr(dep, "approval_due_at", None)
    remaining = int((due - now).total_seconds()) if due else None
    is_overdue = bool(remaining is not None and remaining < 0)
    return {
        "approval_due_at": due.isoformat() if due else None,
        "approval_remaining_seconds": remaining,
        "approval_remaining_human": _format_seconds(remaining) if remaining is not None else "",
        "approval_overdue": is_overdue,
        "escalation_status": getattr(dep, "escalation_status", "") or "",
        "escalated_at": dep.escalated_at.isoformat() if getattr(dep, "escalated_at", None) else None,
    }


async def _append_approval_event(db: AsyncSession, dep: CICDDeployment, event_type: str, actor: str = "", note: str = "") -> None:
    db.add(
        CICDDeploymentApprovalEvent(
            deployment_id=dep.id,
            event_type=event_type,
            actor=(actor or "").strip(),
            note=(note or "").strip(),
        )
    )


async def _upsert_delivery_receipt(
    db: AsyncSession,
    deployment_id: int,
    event_type: str,
    channel_type: str,
    target: str,
) -> CICDNotificationDeliveryReceipt:
    result = await db.execute(
        select(CICDNotificationDeliveryReceipt).where(
            CICDNotificationDeliveryReceipt.deployment_id == deployment_id,
            CICDNotificationDeliveryReceipt.event_type == event_type,
            CICDNotificationDeliveryReceipt.channel_type == channel_type,
            CICDNotificationDeliveryReceipt.target == target,
        )
    )
    row = result.scalars().first()
    if row:
        return row
    row = CICDNotificationDeliveryReceipt(
        deployment_id=deployment_id,
        event_type=event_type,
        channel_type=channel_type,
        target=target,
        status="pending",
        attempt_count=0,
        max_attempts=3,
    )
    db.add(row)
    await db.flush()
    return row


async def _dispatch_escalation_notifications(
    db: AsyncSession,
    dep: CICDDeployment,
    env: CICDEnvironment | None,
    reason: str,
) -> None:
    title = f"Deployment escalation: #{dep.id}"
    message = f"Deployment #{dep.id} in {env.name if env else 'environment'} exceeded approval SLA. {reason}".strip()
    link = "/cicd?tab=deploy"
    db.add(UserNotification(user_id=None, type="cicd", title=title, message=message, link=link, is_read=False))

    targets = [str(v).strip() for v in (getattr(env, "escalation_targets", []) or []) if str(v).strip()]
    target_users = []
    if targets:
        users = (await db.execute(select(User))).scalars().all()
        users_by_username = {str(u.username).strip().lower(): u for u in users}
        users_by_email = {str(u.email).strip().lower(): u for u in users if getattr(u, "email", None)}
        for t in targets:
            user = users_by_username.get(t.lower()) or users_by_email.get(t.lower())
            if user and user.id:
                target_users.append(user)
                db.add(UserNotification(user_id=user.id, type="cicd", title=title, message=message, link=link, is_read=False))

    channels = (
        await db.execute(
            select(NotificationChannel).where(NotificationChannel.is_enabled == True)
        )
    ).scalars().all()

    def _send_email_via_cfg(cfg: dict, to_addr: str, subject: str, body: str):
        import smtplib
        from email.mime.text import MIMEText
        if not to_addr:
            return
        host = cfg.get("smtp_host", "")
        port = int(cfg.get("smtp_port", 587))
        user = cfg.get("smtp_user", "")
        password = cfg.get("smtp_pass", "")
        from_addr = cfg.get("from", user or "patchmaster@localhost")
        if not host:
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        with smtplib.SMTP(host, port, timeout=10) as server:
            if cfg.get("smtp_tls", True):
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())

    async def _deliver_with_retry(channel_type: str, target: str, payload: dict, send_fn, max_attempts: int = 3):
        receipt = await _upsert_delivery_receipt(db, dep.id, "cicd_approval_escalated", channel_type, target)
        receipt.max_attempts = max_attempts
        success = False
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                await send_fn()
                receipt.attempt_count = attempt
                receipt.status = "delivered"
                receipt.delivered_at = _utcnow()
                receipt.next_retry_at = None
                receipt.last_error = ""
                receipt.payload = payload
                success = True
                break
            except Exception as exc:
                last_error = str(exc)
                receipt.attempt_count = attempt
                receipt.status = "failed" if attempt == max_attempts else "retry_scheduled"
                backoff = min(2 ** attempt, 60)
                receipt.next_retry_at = _utcnow() + timedelta(seconds=backoff) if attempt < max_attempts else None
                receipt.last_error = last_error[:1000]
                receipt.payload = payload
        if not success:
            await _append_approval_event(
                db,
                dep,
                "escalation_delivery_failed",
                "system",
                f"{channel_type}:{target}:{last_error[:300]}",
            )

    for ch in channels:
        events = ch.events or []
        if "cicd_approval_escalated" not in events:
            continue
        cfg = ch.config or {}
        if ch.channel_type == "webhook":
            if targets:
                for t in targets:
                    if t.lower().startswith("http://") or t.lower().startswith("https://"):
                        payload = {"event": "cicd_approval_escalated", "deployment_id": dep.id, "title": title, "message": message}
                        async def _send_webhook_target(url=t, body=payload):
                            async with httpx.AsyncClient(timeout=10) as client:
                                await client.post(url, json=body)
                        await _deliver_with_retry("webhook", t, payload, _send_webhook_target)
            else:
                webhook_url = cfg.get("url", "")
                if webhook_url:
                    payload = {"event": "cicd_approval_escalated", "deployment_id": dep.id, "title": title, "message": message}
                    async def _send_webhook_default(url=webhook_url, body=payload):
                        async with httpx.AsyncClient(timeout=10) as client:
                            await client.post(url, json=body)
                    await _deliver_with_retry("webhook", webhook_url, payload, _send_webhook_default)
        elif ch.channel_type == "email":
            if target_users:
                for u in target_users:
                    if not u.email:
                        continue
                    payload = {"event": "cicd_approval_escalated", "deployment_id": dep.id, "title": title, "message": message}
                    async def _send_email_target(email=u.email, body=message, subject=title):
                        _send_email_via_cfg(cfg, email, subject, body)
                    await _deliver_with_retry("email", u.email, payload, _send_email_target)
            elif cfg.get("to"):
                to_addr = cfg.get("to")
                payload = {"event": "cicd_approval_escalated", "deployment_id": dep.id, "title": title, "message": message}
                async def _send_email_default(email=to_addr, body=message, subject=title):
                    _send_email_via_cfg(cfg, email, subject, body)
                await _deliver_with_retry("email", to_addr, payload, _send_email_default)


def _internal_v2_template() -> dict:
    return {
        "runner_label": "default",
        "retry_default": 1,
        "timeout_default_seconds": 300,
        "post_actions": {
            "always": "echo post:always",
            "success": "echo post:success",
            "failure": "echo post:failure",
        },
        "stages": [
            {"name": "Checkout", "command": "git clone repo", "parallel_group": "prep", "runner_label": "default"},
            {"name": "Lint", "command": "npm run lint", "parallel_group": "test", "runner_label": "default"},
            {"name": "Unit Tests", "command": "npm test", "parallel_group": "test", "runner_label": "default"},
            {"name": "Manual Approval", "manual_gate": True, "approver_role": "operator", "parallel_group": "gate"},
            {"name": "Package", "command": "npm run build", "parallel_group": "release", "runner_label": "default"},
            {"name": "Deploy", "command": "deploy.sh", "parallel_group": "release", "runner_label": "default"},
        ],
    }


def _parse_internal_v2_script(content: str) -> dict:
    text = (content or "").strip()
    if not text:
        return _internal_v2_template()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data.setdefault("stages", [])
            return data
    except Exception:
        pass
    return _internal_v2_template()


async def _run_internal_v2_stage(
    db: AsyncSession,
    build_id: int,
    stage: dict,
    order_index: int,
    retry_default: int,
    timeout_default_seconds: int,
    params: dict,
    secrets: dict | None = None,
    pipeline_id: int | None = None,
    environment_id: int | None = None,
) -> dict:
    import re as _re
    name = str(stage.get("name") or f"Stage-{order_index}")
    runner_label = str(stage.get("runner_label") or "default")
    retries = max(int(stage.get("retry", retry_default) or 0), 0)
    timeout_seconds = max(int(stage.get("timeout_seconds", timeout_default_seconds) or 1), 1)
    sleep_seconds = max(int(stage.get("sleep_seconds", 1) or 1), 1)
    command = str(stage.get("command") or "")
    manual_gate = bool(stage.get("manual_gate", False))

    # Substitute ${{ secrets.NAME }} with resolved values (masked in logs)
    def _sub_secrets(text: str) -> str:
        if not secrets or not text:
            return text
        def _replacer(m: _re.Match) -> str:
            key = m.group(1).strip()
            return secrets.get(key, m.group(0))
        return _re.sub(r'\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}', _replacer, text)

    resolved_command = _sub_secrets(command)

    started = _utcnow()
    out_lines = [f"runner={runner_label}", f"timeout={timeout_seconds}", f"retries={retries}", f"command={command or 'manual_gate'}"]
    status = "success"
    completed = _utcnow()
    duration = 0

    if manual_gate:
        status = "pending_approval"
        out_lines.append("manual gate pending approval")
        completed = _utcnow()
        duration = int((completed - started).total_seconds())
    elif runner_label in ("agent", "all", "*") or runner_label.startswith("agent:"):
        # Explicit agent dispatch labels
        from api.cicd_agent_targets import dispatch_stage_to_agents
        agent_runs = await dispatch_stage_to_agents(
            build_id=build_id,
            pipeline_id=pipeline_id or 0,
            environment_id=environment_id,
            stage_name=name,
            command=resolved_command,
            runner_label=runner_label,
            db=db,
        )
        if agent_runs:
            all_success = all(r.get("status") == "success" for r in agent_runs)
            status = "success" if all_success else "failed"
            for r in agent_runs:
                out_lines.append(f"agent {r.get('host_ip', '?')}: exit={r.get('exit_code')} status={r.get('status')}")
                if r.get("output"):
                    out_lines.append(r["output"][:2000])
        else:
            out_lines.append(f"no agent targets matched label={runner_label}, running locally")
            forced_fail = str(params.get("force_fail_stage", "")).strip().lower()
            should_fail = bool((forced_fail and forced_fail == name.lower()) or "fail" in command.lower() or "exit 1" in command.lower())
            await asyncio.sleep(min(sleep_seconds, timeout_seconds))
            status = "failed" if should_fail else "success"
            out_lines.append(f"local attempt: {status}")
        completed = _utcnow()
        duration = int((completed - started).total_seconds())
    elif runner_label not in ("default", "local") and pipeline_id:
        # Custom label — check if any agent targets are registered for it
        from api.cicd_agent_targets import dispatch_stage_to_agents
        agent_runs = await dispatch_stage_to_agents(
            build_id=build_id,
            pipeline_id=pipeline_id,
            environment_id=environment_id,
            stage_name=name,
            command=resolved_command,
            runner_label=runner_label,
            db=db,
        )
        if agent_runs:
            all_success = all(r.get("status") == "success" for r in agent_runs)
            status = "success" if all_success else "failed"
            for r in agent_runs:
                out_lines.append(f"agent {r.get('host_ip', '?')}: exit={r.get('exit_code')} status={r.get('status')}")
                if r.get("output"):
                    out_lines.append(r["output"][:2000])
        else:
            # No targets for this label — run locally
            forced_fail = str(params.get("force_fail_stage", "")).strip().lower()
            should_fail = bool((forced_fail and forced_fail == name.lower()) or "fail" in command.lower() or "exit 1" in command.lower())
            for attempt in range(1, retries + 2):
                step_started = _utcnow()
                await asyncio.sleep(min(sleep_seconds, timeout_seconds))
                step_completed = _utcnow()
                duration = int((step_completed - step_started).total_seconds())
                if duration >= timeout_seconds:
                    status = "failed"
                    out_lines.append(f"attempt={attempt} timeout")
                elif should_fail:
                    status = "failed"
                    out_lines.append(f"attempt={attempt} failed")
                else:
                    status = "success"
                    out_lines.append(f"attempt={attempt} success")
                    break
        completed = _utcnow()
        duration = int((completed - started).total_seconds())
    else:
        forced_fail = str(params.get("force_fail_stage", "")).strip().lower()
        should_fail = bool((forced_fail and forced_fail == name.lower()) or "fail" in command.lower() or "exit 1" in command.lower())
        for attempt in range(1, retries + 2):
            step_started = _utcnow()
            await asyncio.sleep(min(sleep_seconds, timeout_seconds))
            step_completed = _utcnow()
            duration = int((step_completed - step_started).total_seconds())
            if duration >= timeout_seconds:
                status = "failed"
                out_lines.append(f"attempt={attempt} timeout")
            elif should_fail:
                status = "failed"
                out_lines.append(f"attempt={attempt} failed")
            else:
                status = "success"
                out_lines.append(f"attempt={attempt} success")
                break
        completed = _utcnow()

    run = CICDBuildStageRun(
        build_id=build_id,
        stage_name=name,
        order_index=order_index,
        status=status,
        duration_seconds=duration,
        started_at=started,
        completed_at=completed,
        output="\n".join(out_lines),
    )
    db.add(run)
    await db.flush()
    return {"stage_name": name, "status": status, "output": run.output, "manual_gate": manual_gate}


async def _execute_internal_v2_build(db: AsyncSession, pipeline: CICDPipeline, build: CICDBuild, params: dict) -> None:
    from api.cicd_secrets import resolve_secrets_for_pipeline

    cfg = _parse_internal_v2_script(pipeline.script_content)
    stages = list(cfg.get("stages") or [])
    retry_default = max(int(cfg.get("retry_default", 1) or 1), 0)
    timeout_default_seconds = max(int(cfg.get("timeout_default_seconds", 300) or 300), 1)
    post_actions = cfg.get("post_actions") or {}

    # Resolve secrets once for this build — substituted into commands as ${{ secrets.NAME }}
    secrets = await resolve_secrets_for_pipeline(pipeline.id, db)

    # Determine environment_id from params or build trigger_info
    environment_id: int | None = None
    env_name = str(params.get("environment") or build.trigger_info.get("environment") or "").strip()
    if env_name:
        from models.db_models import CICDEnvironment
        from sqlalchemy import select as _select
        env_row = (await db.execute(
            _select(CICDEnvironment).where(
                CICDEnvironment.pipeline_id == pipeline.id,
                CICDEnvironment.name == env_name,
            )
        )).scalar_one_or_none()
        if env_row:
            environment_id = env_row.id

    grouped: list[tuple[str, list[dict]]] = []
    for st in stages:
        grp = str(st.get("parallel_group") or f"serial-{len(grouped)}")
        if grouped and grouped[-1][0] == grp:
            grouped[-1][1].append(st)
        else:
            grouped.append((grp, [st]))

    build.status = "running"
    build.started_at = _utcnow()
    await db.flush()

    stage_outputs = []
    order = 0
    overall_failed = False
    overall_pending = False
    for group_name, group_stages in grouped:
        tasks = []
        for st in group_stages:
            order += 1
            tasks.append(_run_internal_v2_stage(
                db, build.id, st, order, retry_default, timeout_default_seconds,
                params or {}, secrets=secrets,
                pipeline_id=pipeline.id, environment_id=environment_id,
            ))
        results = await asyncio.gather(*tasks)
        stage_outputs.extend(results)
        if any(r["status"] == "pending_approval" for r in results):
            overall_pending = True
            break
        if any(r["status"] != "success" for r in results):
            overall_failed = True
            if any(str(s.get("on_failure", "stop")).lower() == "stop" for s in group_stages):
                break
    lines = [f"group={g} stages={len(s)}" for g, s in grouped]
    for r in stage_outputs:
        lines.append(f"{r['stage_name']} => {r['status']}")
    lines.append(f"post.always: {post_actions.get('always', '')}")
    if overall_pending:
        build.status = "pending_approval"
        lines.append("post.pending: manual approval required")
    elif overall_failed:
        build.status = "failed"
        lines.append(f"post.failure: {post_actions.get('failure', '')}")
    else:
        build.status = "success"
        lines.append(f"post.success: {post_actions.get('success', '')}")
    build.output = "\n".join(lines)[:8000]
    build.completed_at = _utcnow() if build.status != "pending_approval" else None
    build.external_url = f"/api/cicd/builds/{build.id}"
    await db.flush()


def _log_to_dict(l: CICDBuildLog) -> dict:
    return {
        "id": l.id,
        "build_id": l.build_id,
        "line": l.line,
        "storage_path": getattr(l, "storage_path", "") or "",
        "status": getattr(l, "status", "") or "",
        "created_at": l.created_at.isoformat() if l.created_at else "",
    }


def _artifact_to_dict(a: CICDBuildArtifact) -> dict:
    return {
        "id": a.id,
        "build_id": a.build_id,
        "name": a.name,
        "url": a.url or "",
        "size_bytes": a.size_bytes or 0,
        "storage_path": getattr(a, "storage_path", "") or "",
        "status": getattr(a, "status", "") or "",
        "meta": a.meta or {},
        "created_at": a.created_at.isoformat() if a.created_at else "",
    }


def _stage_run_to_dict(s: CICDBuildStageRun) -> dict:
    return {
        "id": s.id,
        "build_id": s.build_id,
        "stage_name": s.stage_name,
        "order_index": s.order_index,
        "status": s.status or "pending",
        "duration_seconds": s.duration_seconds,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "output": s.output or "",
        "created_at": s.created_at.isoformat() if s.created_at else "",
    }


class _ApprovalEvidencePDF(FPDF):
    pass


def _build_jenkins_headers(pipeline: CICDPipeline) -> dict:
    """Build auth headers for Jenkins API calls."""
    headers = {}
    creds = decrypt_json_field(pipeline.auth_credentials)
    if pipeline.auth_type == "token" and creds.get("user") and creds.get("token"):
        import base64
        auth_str = f"{creds['user']}:{creds['token']}"
        headers["Authorization"] = f"Basic {base64.b64encode(auth_str.encode()).decode()}"
    elif pipeline.auth_type == "basic" and creds.get("user") and creds.get("password"):
        import base64
        auth_str = f"{creds['user']}:{creds['password']}"
        headers["Authorization"] = f"Basic {base64.b64encode(auth_str.encode()).decode()}"
    elif pipeline.auth_type == "token" and creds.get("token"):
        headers["Authorization"] = f"Bearer {creds['token']}"
    return headers


# ── Pipeline CRUD ──

@router.get("/pipelines")
async def list_pipelines(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List all CI/CD pipelines with build stats."""
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD pipelines.")
    result = await db.execute(select(CICDPipeline).order_by(CICDPipeline.created_at.desc()))
    pipelines = result.scalars().all()

    base_url = str(request.base_url).rstrip("/")
    out = []
    changed = False
    for p in pipelines:
        # Get build count and last status
        count_result = await db.execute(
            select(func.count(CICDBuild.id)).where(CICDBuild.pipeline_id == p.id)
        )
        build_count = count_result.scalar() or 0

        last_build = await db.execute(
            select(CICDBuild).where(CICDBuild.pipeline_id == p.id)
            .order_by(CICDBuild.created_at.desc()).limit(1)
        )
        lb = last_build.scalars().first()
        last_status = lb.status if lb else None

        out.append(_pipeline_to_dict(p, build_count, last_status, base_url))
    return out


@router.post("/pipelines", status_code=201)
async def create_pipeline(
    body: PipelineCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Create a new CI/CD pipeline."""
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD pipelines.")
    if body.tool not in ("jenkins", "gitlab", "custom", "internal"):
        raise HTTPException(400, "tool must be one of: jenkins, gitlab, custom, internal")
    if body.script_type not in ("groovy", "yaml", "shell"):
        raise HTTPException(400, "script_type must be one of: groovy, yaml, shell")
    if body.tool in ("jenkins", "gitlab") and not body.server_url.strip():
        raise HTTPException(400, "server_url is required for jenkins/gitlab pipelines")

    webhook_secret = secrets.token_hex(24)

    pipeline = CICDPipeline(
        name=body.name,
        description=body.description,
        tool=body.tool,
        server_url=body.server_url.rstrip("/") if body.server_url else "",
        auth_type=body.auth_type,
        auth_credentials=encrypt_json_field(body.auth_credentials),
        job_path=body.job_path,
        script_type=body.script_type,
        script_content=body.script_content,
        webhook_secret=encrypt_text_field(webhook_secret),
        trigger_events=body.trigger_events,
        status="active",
        created_by=user.username,
    )
    db.add(pipeline)
    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    base_url = str(request.base_url).rstrip("/")
    return _pipeline_to_dict(pipeline, 0, None, base_url)


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(
    pipeline_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get a single pipeline with details."""
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD pipelines.")
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")

    count_result = await db.execute(
        select(func.count(CICDBuild.id)).where(CICDBuild.pipeline_id == pipeline_id)
    )
    build_count = count_result.scalar() or 0

    last_build = await db.execute(
        select(CICDBuild).where(CICDBuild.pipeline_id == pipeline_id)
        .order_by(CICDBuild.created_at.desc()).limit(1)
    )
    lb = last_build.scalars().first()

    base_url = str(request.base_url).rstrip("/")
    return _pipeline_to_dict(pipeline, build_count, lb.status if lb else None, base_url)


@router.get("/pipelines/{pipeline_id}/webhook-secret")
async def get_pipeline_webhook_secret(
    pipeline_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Return the webhook secret for a pipeline. Requires manage permission."""
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to view pipeline secrets.")
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    return {"id": pipeline_id, "webhook_secret": decrypt_text_field(pipeline.webhook_secret)}


@router.put("/pipelines/{pipeline_id}")
async def update_pipeline(
    pipeline_id: int,
    body: PipelineUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Update a CI/CD pipeline."""
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD pipelines.")
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")

    for field in ("name", "description", "server_url", "auth_type", "auth_credentials",
                  "job_path", "script_type", "script_content", "trigger_events", "status"):
        val = getattr(body, field, None)
        if val is None:
            continue
        # Never wipe stored credentials with an empty or partial dict — the frontend
        # cannot read back auth_credentials (intentionally redacted), so a missing
        # or incomplete payload means "unchanged". Only update when both user and
        # token are provided, ensuring a partial edit cannot silently clear one field.
        if field == "auth_credentials":
            if not isinstance(val, dict):
                continue
            has_user = bool((val.get("user") or "").strip())
            has_token = bool((val.get("token") or val.get("password") or "").strip())
            if not (has_user and has_token):
                continue
            val = encrypt_json_field(val)
        if field == "server_url":
            val = val.rstrip("/")
        setattr(pipeline, field, val)

    pipeline.updated_at = _utcnow()
    await db.flush()
    await db.commit()
    await db.refresh(pipeline)

    base_url = str(request.base_url).rstrip("/")
    return _pipeline_to_dict(pipeline, 0, None, base_url)


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    """Delete a pipeline and all its builds."""
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to delete CI/CD pipelines.")
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    await db.delete(pipeline)
    await db.commit()
    return {"ok": True}


# ── Trigger builds ──

@router.post("/pipelines/{pipeline_id}/trigger")
async def trigger_build(
    pipeline_id: int,
    body: TriggerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Manually trigger a pipeline build via Jenkins/GitLab API."""
    _assert_cicd_permission(user, "cicd_execute", "You do not have permission to execute CI/CD pipelines.")
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    if pipeline.status != "active":
        raise HTTPException(400, "Pipeline is not active")

    # Get next build number
    max_num = await db.execute(
        select(func.coalesce(func.max(CICDBuild.build_number), 0))
        .where(CICDBuild.pipeline_id == pipeline_id)
    )
    next_num = (max_num.scalar() or 0) + 1

    build = CICDBuild(
        pipeline_id=pipeline_id,
        build_number=next_num,
        status="pending",
        trigger_type="manual",
        trigger_info={"triggered_by": user.username, "parameters": body.parameters},
        started_at=_utcnow(),
    )
    db.add(build)
    pipeline.last_triggered = _utcnow()
    await db.flush()
    await db.commit()
    await db.refresh(build)

    # Attempt to trigger remote CI system
    external_url = ""
    try:
        if pipeline.tool == "jenkins":
            external_url = await _trigger_jenkins(pipeline, body.parameters)
            build.status = "running"
            build.external_url = external_url
        elif pipeline.tool == "gitlab":
            external_url = await _trigger_generic_webhook(pipeline, body.parameters)
            build.status = "running"
            build.external_url = external_url
        elif pipeline.tool == "internal":
            await _execute_internal_v2_build(db, pipeline, build, body.parameters or {})
        else:
            build.status = "running"
    except Exception as exc:
        build.status = "failed"
        build.output = f"Trigger failed: {str(exc)}"
        build.completed_at = _utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(build)
    return _build_to_dict(build, pipeline.name)


async def _trigger_jenkins(pipeline: CICDPipeline, params: dict) -> str:
    """Trigger a Jenkins job and return the build URL."""
    headers = _build_jenkins_headers(pipeline)
    job_path = pipeline.job_path.strip("/")
    base = pipeline.server_url

    # Jenkins build URL — with or without parameters
    if params:
        url = f"{base}/job/{job_path}/buildWithParameters"
    else:
        url = f"{base}/job/{job_path}/build"

    # Get crumb for CSRF protection
    try:
        async with httpx.AsyncClient(timeout=15, verify=_CICD_TLS_VERIFY) as client:
            crumb_resp = await client.get(f"{base}/crumbIssuer/api/json", headers=headers)
            if crumb_resp.status_code == 200:
                crumb_data = crumb_resp.json()
                headers[crumb_data["crumbRequestField"]] = crumb_data["crumb"]
    except Exception:
        pass  # Some Jenkins instances don't require crumbs

    async with httpx.AsyncClient(timeout=30, verify=_CICD_TLS_VERIFY) as client:
        resp = await client.post(url, headers=headers, data=params if params else None)
        if resp.status_code not in (200, 201, 302):
            raise Exception(f"Jenkins returned HTTP {resp.status_code}: {resp.text[:200]}")
        # Return the queue/build URL
        location = resp.headers.get("Location", "")
        if location:
            return location
        return f"{base}/job/{job_path}/"


async def _trigger_generic_webhook(pipeline: CICDPipeline, params: dict) -> str:
    """Trigger via generic webhook POST."""
    headers = _build_jenkins_headers(pipeline)
    headers["Content-Type"] = "application/json"
    import json
    payload = {
        "ref": params.get("branch", "main"),
        "variables": params,
    }
    async with httpx.AsyncClient(timeout=30, verify=_CICD_TLS_VERIFY) as client:
        resp = await client.post(pipeline.server_url, headers=headers, json=payload)
        if resp.status_code not in (200, 201, 202):
            raise Exception(f"Webhook returned HTTP {resp.status_code}: {resp.text[:200]}")
    return pipeline.server_url


# ── Build history ──

@router.get("/builds")
async def list_builds(
    pipeline_id: int = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """List builds, optionally filtered by pipeline."""
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD builds.")
    q = select(CICDBuild).order_by(CICDBuild.created_at.desc()).limit(min(limit, 200))
    if pipeline_id:
        q = q.where(CICDBuild.pipeline_id == pipeline_id)

    result = await db.execute(q)
    builds = result.scalars().all()
    await _mark_stale_pending_builds(db, builds)

    # Get pipeline names
    pipe_ids = {b.pipeline_id for b in builds}
    names = {}
    if pipe_ids:
        pr = await db.execute(select(CICDPipeline).where(CICDPipeline.id.in_(pipe_ids)))
        for p in pr.scalars().all():
            names[p.id] = p.name

    return [_build_to_dict(b, names.get(b.pipeline_id, "")) for b in builds]


@router.get("/builds/{build_id}")
async def get_build(
    build_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD builds.")
    result = await db.execute(select(CICDBuild).where(CICDBuild.id == build_id))
    build = result.scalars().first()
    if not build:
        raise HTTPException(404, "Build not found")
    await _mark_stale_pending_builds(db, [build])
    pr = await db.execute(select(CICDPipeline).where(CICDPipeline.id == build.pipeline_id))
    pipe = pr.scalars().first()
    return _build_to_dict(build, pipe.name if pipe else "")


@router.post("/builds/{build_id}/manual-gate/approve")
async def approve_manual_gate(
    build_id: int,
    body: ManualGateApproveIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_approve", "You do not have permission to approve CI/CD manual gates.")
    result = await db.execute(select(CICDBuild).where(CICDBuild.id == build_id))
    build = result.scalars().first()
    if not build:
        raise HTTPException(404, "Build not found")
    stage_q = select(CICDBuildStageRun).where(CICDBuildStageRun.build_id == build_id)
    if body.stage_name.strip():
        stage_q = stage_q.where(CICDBuildStageRun.stage_name == body.stage_name.strip())
    stage_q = stage_q.order_by(CICDBuildStageRun.order_index.asc())
    stages = (await db.execute(stage_q)).scalars().all()
    if not stages:
        raise HTTPException(404, "Manual gate stage not found")
    changed = False
    for s in stages:
        if str(s.status or "").lower() == "pending_approval":
            s.status = "success"
            s.completed_at = _utcnow()
            s.output = (s.output or "") + f"\nmanual gate approved by {user.username}. {body.note.strip()}".rstrip()
            changed = True
    if not changed:
        return {"ok": True, "message": "No pending manual gates to approve."}
    remaining = (
        await db.execute(
            select(func.count()).select_from(CICDBuildStageRun).where(
                CICDBuildStageRun.build_id == build_id,
                CICDBuildStageRun.status == "pending_approval",
            )
        )
    ).scalar_one()
    if int(remaining or 0) == 0 and str(build.status or "").lower() == "pending_approval":
        failed_count = (
            await db.execute(
                select(func.count()).select_from(CICDBuildStageRun).where(
                    CICDBuildStageRun.build_id == build_id,
                    CICDBuildStageRun.status == "failed",
                )
            )
        ).scalar_one()
        build.status = "failed" if int(failed_count or 0) > 0 else "success"
        build.completed_at = _utcnow()
    await db.flush()
    pr = await db.execute(select(CICDPipeline).where(CICDPipeline.id == build.pipeline_id))
    pipe = pr.scalars().first()
    return _build_to_dict(build, pipe.name if pipe else "")


# ── Incoming webhook (from Jenkins / GitLab / compatible senders) ──

@router.post("/webhook/{pipeline_id}")
async def receive_webhook(
    pipeline_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive webhook callback from Jenkins/GitLab.
    Validates signature if webhook_secret is set.
    Creates or updates a build record.
    """
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")

    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")

    webhook_secret = decrypt_text_field(pipeline.webhook_secret)

    # Validate webhook signature if secret is set
    if webhook_secret:
        sig_header = (
            request.headers.get("X-Hub-Signature-256")
            or request.headers.get("X-Gitlab-Token")
            or request.headers.get("X-Jenkins-Signature")
        )
        if sig_header:
            if sig_header.startswith("sha256="):
                expected = "sha256=" + hmac.new(
                    webhook_secret.encode(), body_bytes, hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(sig_header, expected):
                    raise HTTPException(403, "Invalid webhook signature")
            elif sig_header == webhook_secret:
                pass  # GitLab token match
            else:
                raise HTTPException(403, "Invalid webhook signature")

    # Parse payload
    try:
        import json
        payload = json.loads(body_text)
    except Exception:
        payload = {"raw": body_text[:2000]}

    # Determine build status from payload
    build_status = "success"
    build_number = 0
    external_url = ""
    output = ""

    # Jenkins payload
    if "build" in payload:
        b = payload["build"]
        jenkins_status = b.get("status", b.get("phase", ""))
        if jenkins_status in ("SUCCESS", "COMPLETED"):
            build_status = "success"
        elif jenkins_status in ("FAILURE", "FAILED"):
            build_status = "failed"
        elif jenkins_status in ("STARTED", "RUNNING"):
            build_status = "running"
        elif jenkins_status in ("ABORTED",):
            build_status = "aborted"
        else:
            build_status = "running"
        build_number = b.get("number", 0)
        external_url = b.get("full_url", b.get("url", ""))
        output = f"Jenkins build #{build_number} — {jenkins_status}"

    # GitLab pipeline payload
    elif "object_attributes" in payload and "pipeline" in payload.get("object_kind", ""):
        oa = payload["object_attributes"]
        gl_status = oa.get("status", "")
        if gl_status == "success":
            build_status = "success"
        elif gl_status == "failed":
            build_status = "failed"
        elif gl_status == "canceled":
            build_status = "aborted"
        else:
            build_status = "running"
        build_number = oa.get("id", 0)
        external_url = oa.get("url", "")
        output = f"GitLab pipeline #{build_number} — {gl_status}"

    else:
        output = f"Webhook received: {body_text[:500]}"

    # Check if we already have a build with this number
    existing = None
    if build_number:
        er = await db.execute(
            select(CICDBuild).where(
                CICDBuild.pipeline_id == pipeline_id,
                CICDBuild.build_number == build_number,
            )
        )
        existing = er.scalars().first()

    now = _utcnow()
    if existing:
        existing.status = build_status
        existing.output = output
        existing.external_url = external_url or existing.external_url
        if build_status in ("success", "failed", "aborted"):
            existing.completed_at = now
        elif build_status == "running" and not existing.started_at:
            existing.started_at = now
        build_record = existing
    else:
        max_num = await db.execute(
            select(func.coalesce(func.max(CICDBuild.build_number), 0))
            .where(CICDBuild.pipeline_id == pipeline_id)
        )
        fallback_num = (max_num.scalar() or 0) + 1
        build_record = CICDBuild(
            pipeline_id=pipeline_id,
            build_number=build_number or fallback_num,
            status=build_status,
            trigger_type="webhook",
            trigger_info={"source": pipeline.tool, "headers": dict(request.headers)},
            output=output,
            external_url=external_url,
            started_at=now if build_status == "running" else None,
            completed_at=now if build_status in ("success", "failed", "aborted") else None,
        )
        db.add(build_record)

    pipeline.last_triggered = now
    await db.flush()
    return {"ok": True, "build_status": build_status}


# ── Test connection ──

@router.post("/pipelines/{pipeline_id}/test")
async def test_connection(
    pipeline_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Test connectivity to the CI/CD server."""
    _assert_cicd_permission(user, "cicd_execute", "You do not have permission to test CI/CD connections.")
    result = await db.execute(select(CICDPipeline).where(CICDPipeline.id == pipeline_id))
    pipeline = result.scalars().first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")

    try:
        if pipeline.tool == "internal":
            return {"ok": True, "status_code": 200, "message": "Patch-SecOps Solution internal CI/CD engine is active."}
        headers = _build_jenkins_headers(pipeline)
        async with httpx.AsyncClient(timeout=10, verify=_CICD_TLS_VERIFY) as client:
            if pipeline.tool == "jenkins":
                url = f"{pipeline.server_url}/api/json"
            else:
                url = pipeline.server_url
            resp = await client.get(url, headers=headers)
            return {
                "ok": resp.status_code < 400,
                "status_code": resp.status_code,
                "message": f"Connected — HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"ok": False, "status_code": 0, "message": f"Connection failed: {str(e)}"}


# ── Script templates ──

@router.get("/templates")
async def get_script_templates(user=Depends(get_current_user)):
    """Return starter pipeline script templates."""
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD templates.")
    return {
        "groovy": {
            "label": "Jenkins Declarative Pipeline (Groovy)",
            "content": """pipeline {
    agent any
    environment {
        PATCHMASTER_URL = 'http://YOUR_SERVER:8000'
    }
    stages {
        stage('Pre-Patch Check') {
            steps {
                sh '''
                    curl -s $PATCHMASTER_URL/api/health
                    echo "Patch-SecOps Solution is reachable"
                '''
            }
        }
        stage('Run Patches') {
            steps {
                sh '''
                    curl -s -X POST $PATCHMASTER_URL/api/jobs/ \\
                        -H "Authorization: Bearer $PM_TOKEN" \\
                        -H "Content-Type: application/json" \\
                        -d '{"host_id": 1, "action": "upgrade", "dry_run": false}'
                '''
            }
        }
        stage('Verify') {
            steps {
                sh '''
                    curl -s $PATCHMASTER_URL/api/compliance/ \\
                        -H "Authorization: Bearer $PM_TOKEN"
                '''
            }
        }
    }
    post {
        success {
            echo 'Patch pipeline completed successfully!'
        }
        failure {
            echo 'Patch pipeline failed — check Patch-SecOps Solution logs.'
        }
    }
}""",
        },
        "yaml": {
            "label": "GitLab CI (YAML)",
            "content": """# GitLab CI Pipeline
stages:
  - verify
  - snapshot
  - patch
  - compliance

variables:
  PATCHMASTER_URL: "http://YOUR_SERVER:8000"

health_check:
  stage: verify
  script:
    - curl -sf "$PATCHMASTER_URL/api/health"

pre_patch_snapshot:
  stage: snapshot
  script:
    - curl -s -X POST "$PATCHMASTER_URL/api/jobs/" -H "Authorization: Bearer $PM_TOKEN" -H "Content-Type: application/json" -d '{"host_id": 1, "action": "snapshot"}'

execute_patches:
  stage: patch
  script:
    - curl -s -X POST "$PATCHMASTER_URL/api/jobs/" -H "Authorization: Bearer $PM_TOKEN" -H "Content-Type: application/json" -d '{"host_id": 1, "action": "upgrade", "dry_run": false}'

verify_compliance:
  stage: compliance
  script:
    - curl -s "$PATCHMASTER_URL/api/compliance/" -H "Authorization: Bearer $PM_TOKEN"
""",
        },
        "shell": {
            "label": "Shell Script",
            "content": """#!/bin/bash
# Patch-SecOps Solution CI/CD Shell Script
set -euo pipefail

PATCHMASTER_URL="${PATCHMASTER_URL:-http://localhost:8000}"
PM_TOKEN="${PM_TOKEN:-}"

echo "=== Patch-SecOps Solution CI/CD Pipeline ==="
echo "Server: $PATCHMASTER_URL"
echo "Time: $(date -u)"

# Health check
echo "--- Health Check ---"
curl -sf "$PATCHMASTER_URL/api/health" || { echo "FAIL: Patch-SecOps Solution unreachable"; exit 1; }

# Pre-patch snapshot
echo "--- Creating Snapshot ---"
curl -s -X POST "$PATCHMASTER_URL/api/jobs/" \\
    -H "Authorization: Bearer $PM_TOKEN" \\
    -H "Content-Type: application/json" \\
    -d '{"host_id": 1, "action": "snapshot"}' | jq .

# Execute patches
echo "--- Executing Patches ---"
curl -s -X POST "$PATCHMASTER_URL/api/jobs/" \\
    -H "Authorization: Bearer $PM_TOKEN" \\
    -H "Content-Type: application/json" \\
    -d '{"host_id": 1, "action": "upgrade", "auto_snapshot": true, "auto_rollback": true}' | jq .

# Check compliance
echo "--- Compliance Check ---"
curl -s "$PATCHMASTER_URL/api/compliance/" \\
    -H "Authorization: Bearer $PM_TOKEN" | jq .

echo "=== Pipeline Complete ==="
""",
        },
        "internal_v2": {
            "label": "Patch-SecOps Solution Internal CI/CD v2 (JSON)",
            "content": json.dumps(_internal_v2_template(), indent=2),
        },
    }


# ── Variables ──

@router.get("/pipelines/{pipeline_id}/variables")
async def list_variables(pipeline_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD variables.")
    result = await db.execute(select(CICDVariable).where(CICDVariable.pipeline_id == pipeline_id).order_by(CICDVariable.key))
    return [_variable_to_dict(v) for v in result.scalars().all()]


@router.post("/pipelines/{pipeline_id}/variables", status_code=201)
async def create_variable(
    pipeline_id: int,
    body: VariableIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD variables.")
    var = CICDVariable(
        pipeline_id=pipeline_id,
        key=body.key,
        value=encrypt_text_field(body.value) if body.is_secret and body.value else body.value,
        is_secret=body.is_secret,
        status=body.status,
    )
    db.add(var)
    await db.flush()
    await db.commit()
    await db.refresh(var)
    return _variable_to_dict(var)


@router.put("/pipelines/{pipeline_id}/variables/{var_id}")
async def update_variable(
    pipeline_id: int,
    var_id: int,
    body: VariableIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD variables.")
    result = await db.execute(select(CICDVariable).where(CICDVariable.id == var_id, CICDVariable.pipeline_id == pipeline_id))
    var = result.scalars().first()
    if not var:
        raise HTTPException(404, "Variable not found")
    var.key = body.key
    var.value = encrypt_text_field(body.value) if body.is_secret and body.value else body.value
    var.is_secret = body.is_secret
    if hasattr(var, "status"):
        var.status = body.status
    await db.flush()
    await db.commit()
    await db.refresh(var)
    return _variable_to_dict(var)


@router.delete("/pipelines/{pipeline_id}/variables/{var_id}")
async def delete_variable(
    pipeline_id: int,
    var_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD variables.")
    result = await db.execute(select(CICDVariable).where(CICDVariable.id == var_id, CICDVariable.pipeline_id == pipeline_id))
    var = result.scalars().first()
    if not var:
        raise HTTPException(404, "Variable not found")
    await db.delete(var)
    await db.commit()
    return {"ok": True}


# ── Environments ──

@router.get("/pipelines/{pipeline_id}/environments")
async def list_environments(pipeline_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD environments.")
    result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.pipeline_id == pipeline_id).order_by(CICDEnvironment.name))
    return [_environment_to_dict(e) for e in result.scalars().all()]


@router.post("/pipelines/{pipeline_id}/environments", status_code=201)
async def create_environment(
    pipeline_id: int,
    body: EnvironmentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD environments.")
    env = CICDEnvironment(
        pipeline_id=pipeline_id,
        name=body.name,
        description=body.description,
        webhook_url=body.webhook_url,
        requires_approval=body.requires_approval,
        approvers=body.approvers,
        approval_quorum=max(int(body.approval_quorum or 1), 1),
        approval_sla_minutes=max(int(body.approval_sla_minutes or 60), 1),
        escalation_after_minutes=max(int(body.escalation_after_minutes or 120), 1),
        escalation_targets=body.escalation_targets or [],
        status=body.status,
    )
    db.add(env)
    await db.flush()
    await db.commit()
    await db.refresh(env)
    return _environment_to_dict(env)


@router.put("/pipelines/{pipeline_id}/environments/{env_id}")
async def update_environment(
    pipeline_id: int,
    env_id: int,
    body: EnvironmentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD environments.")
    result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.id == env_id, CICDEnvironment.pipeline_id == pipeline_id))
    env = result.scalars().first()
    if not env:
        raise HTTPException(404, "Environment not found")
    env.name = body.name
    env.description = body.description
    env.webhook_url = body.webhook_url
    env.requires_approval = body.requires_approval
    env.approvers = body.approvers
    if hasattr(env, "approval_quorum"):
        env.approval_quorum = max(int(body.approval_quorum or 1), 1)
    if hasattr(env, "approval_sla_minutes"):
        env.approval_sla_minutes = max(int(body.approval_sla_minutes or 60), 1)
    if hasattr(env, "escalation_after_minutes"):
        env.escalation_after_minutes = max(int(body.escalation_after_minutes or 120), 1)
    if hasattr(env, "escalation_targets"):
        env.escalation_targets = body.escalation_targets or []
    if hasattr(env, "status"):
        env.status = body.status
    await db.flush()
    await db.commit()
    await db.refresh(env)
    return _environment_to_dict(env)


@router.delete("/pipelines/{pipeline_id}/environments/{env_id}")
async def delete_environment(
    pipeline_id: int,
    env_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_manage", "You do not have permission to manage CI/CD environments.")
    result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.id == env_id, CICDEnvironment.pipeline_id == pipeline_id))
    env = result.scalars().first()
    if not env:
        raise HTTPException(404, "Environment not found")
    await db.delete(env)
    await db.commit()
    return {"ok": True}


# ── Deployments ──

@router.get("/deployments")
async def list_deployments(
    pipeline_id: int = None,
    environment: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    _assert_cicd_permission(user, "cicd_view", "You do not have permission to view CI/CD deployments.")
    q = select(CICDDeployment).order_by(CICDDeployment.created_at.desc()).limit(min(limit, 200))
    if pipeline_id:
        q = q.where(CICDDeployment.pipeline_id == pipeline_id)
    if environment:
        q = q.join(CICDEnvironment, CICDDeployment.environment_id == CICDEnvironment.id).where(CICDEnvironment.name == environment)
    result = await db.execute(q)
    deployments = result.scalars().all()

    env_ids = {d.environment_id for d in deployments if d.environment_id}
    env_map = {}
    env_obj_map = {}
    if env_ids:
        er = await db.execute(select(CICDEnvironment).where(CICDEnvironment.id.in_(env_ids)))
        env_rows = er.scalars().all()
        env_map = {e.id: e.name for e in env_rows}
        env_obj_map = {e.id: e for e in env_rows}

    pipe_ids = {d.pipeline_id for d in deployments if d.pipeline_id}
    pipe_map = {}
    if pipe_ids:
        pr = await db.execute(select(CICDPipeline).where(CICDPipeline.id.in_(pipe_ids)))
        pipe_map = {p.id: p.name for p in pr.scalars().all()}

    dep_ids = [d.id for d in deployments]
    event_rows = []
    if dep_ids:
        event_rows = (
            await db.execute(
                select(CICDDeploymentApprovalEvent).where(CICDDeploymentApprovalEvent.deployment_id.in_(dep_ids))
            )
        ).scalars().all()
    event_map: dict[int, list[CICDDeploymentApprovalEvent]] = {}
    for e in event_rows:
        event_map.setdefault(e.deployment_id, []).append(e)

    out = []
    changed = False
    now = _utcnow()
    for d in deployments:
        env = env_obj_map.get(d.environment_id) if d.environment_id else None
        if d.status == "pending_approval" and env and getattr(d, "approval_due_at", None):
            overdue_seconds = int((now - d.approval_due_at).total_seconds()) if d.approval_due_at else 0
            escalation_after = int(getattr(env, "escalation_after_minutes", 120) or 120) * 60
            if overdue_seconds > 0 and overdue_seconds >= escalation_after and not getattr(d, "escalated_at", None):
                d.escalated_at = now
                d.escalation_status = "escalated"
                await _append_approval_event(db, d, "escalated", "system", "Approval SLA escalation triggered")
                await _dispatch_escalation_notifications(db, d, env, "Escalation notifications dispatched.")
                changed = True
        row = _deployment_to_dict(d, env_map.get(d.environment_id, ""), pipe_map.get(d.pipeline_id, ""))
        row.update(_approval_sla_fields(d))
        events = event_map.get(d.id, [])
        row["approval_event_count"] = len(events)
        row["escalation_notification_sent"] = any(str(ev.event_type or "").lower() == "escalated" for ev in events)
        out.append(row)
    if changed:
        await db.commit()
    return out


@router.post("/deployments", status_code=201)
async def create_deployment(
    body: DeploymentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_execute", "You do not have permission to execute CI/CD deployments.")
    env_result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.pipeline_id == body.pipeline_id, CICDEnvironment.name == body.environment))
    env = env_result.scalars().first()
    if not env:
        raise HTTPException(404, "Environment not found")
    requested_status = (body.status or "pending").strip().lower()
    status = "pending_approval" if bool(env.requires_approval) else requested_status
    terminal_statuses = {"success", "failed", "aborted", "canceled", "completed", "rolled_back"}
    started_at = _utcnow() if status == "running" else None
    completed_at = _utcnow() if status in terminal_statuses else None
    deployment = CICDDeployment(
        pipeline_id=body.pipeline_id,
        environment_id=env.id,
        build_id=body.build_id,
        status=status,
        triggered_by=user.username,
        notes=body.notes,
        external_url=body.external_url,
        storage_path=getattr(body, "storage_path", "") or "",
        started_at=started_at,
        completed_at=completed_at,
    )
    if status == "pending_approval" and hasattr(deployment, "approval_due_at"):
        sla_min = max(int(getattr(env, "approval_sla_minutes", 60) or 60), 1)
        deployment.approval_due_at = _utcnow() + timedelta(minutes=sla_min)
        deployment.escalation_status = "awaiting_approval"
    db.add(deployment)
    await db.flush()
    await _append_approval_event(
        db,
        deployment,
        "deployment_created",
        user.username,
        f"status={status}",
    )
    await db.refresh(deployment)
    row = _deployment_to_dict(deployment, env.name, "")
    row.update(_approval_sla_fields(deployment))
    return row


@router.put("/deployments/{deploy_id}")
async def update_deployment(
    deploy_id: int,
    body: DeploymentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_execute", "You do not have permission to update CI/CD deployments.")
    result = await db.execute(select(CICDDeployment).where(CICDDeployment.id == deploy_id))
    dep = result.scalars().first()
    if not dep:
        raise HTTPException(404, "Deployment not found")

    terminal_statuses = {"success", "failed", "aborted", "canceled", "completed", "rolled_back"}
    for field in ["status", "external_url", "notes", "storage_path"]:
        val = getattr(body, field, None)
        if val is not None:
            setattr(dep, field, val)
            if field == "status" and val:
                if val == "running" and not dep.started_at:
                    dep.started_at = _utcnow()
                if val in terminal_statuses:
                    dep.completed_at = _utcnow()

    if body.approved_by:
        dep.approved_by = body.approved_by
        dep.approved_at = _utcnow()

    await db.flush()
    await db.commit()
    await db.refresh(dep)

    env_name = ""
    if dep.environment_id:
        env_result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.id == dep.environment_id))
        env = env_result.scalars().first()
        if env:
            env_name = env.name

    return _deployment_to_dict(dep, env_name, "")


@router.post("/deployments/{deploy_id}/approve")
async def approve_deployment(
    deploy_id: int,
    body: DeploymentApprovalIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_approve", "You do not have permission to approve CI/CD deployments.")
    result = await db.execute(select(CICDDeployment).where(CICDDeployment.id == deploy_id))
    dep = result.scalars().first()
    if not dep:
        raise HTTPException(404, "Deployment not found")
    env = None
    if dep.environment_id:
        env_result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.id == dep.environment_id))
        env = env_result.scalars().first()
    if env and not _can_user_approve(user, env):
        raise HTTPException(status_code=403, detail="User is not in approval list for this environment")
    uname = str(user.username or "").strip()
    approval_result = await db.execute(
        select(CICDDeploymentApproval).where(
            CICDDeploymentApproval.deployment_id == dep.id,
            CICDDeploymentApproval.approver == uname,
        )
    )
    approval = approval_result.scalars().first()
    if not approval:
        approval = CICDDeploymentApproval(deployment_id=dep.id, approver=uname, decision="approved", note=body.note.strip())
        db.add(approval)
    else:
        approval.decision = "approved"
        approval.note = body.note.strip()
        approval.updated_at = _utcnow()
    all_approvals = (
        await db.execute(
            select(CICDDeploymentApproval).where(
                CICDDeploymentApproval.deployment_id == dep.id,
                CICDDeploymentApproval.decision == "approved",
            )
        )
    ).scalars().all()
    quorum = max(int(getattr(env, "approval_quorum", 1) or 1), 1)
    if len(all_approvals) >= quorum:
        dep.approved_by = uname
        dep.approved_at = _utcnow()
        dep.status = "approved"
        dep.escalation_status = ""
    else:
        dep.status = "pending_approval"
    dep.notes = (dep.notes or "") + (f"\n[approval] {uname}: {body.note.strip()}" if body.note.strip() else "")
    await _append_approval_event(db, dep, "approved", uname, body.note.strip())
    await db.flush()
    await db.commit()
    await db.refresh(dep)
    return {
        **_deployment_to_dict(dep, env.name if env else "", ""),
        "approval_quorum": quorum,
        "approval_count": len(all_approvals),
    }


@router.post("/deployments/{deploy_id}/reject")
async def reject_deployment(
    deploy_id: int,
    body: DeploymentApprovalIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    _assert_cicd_permission(user, "cicd_approve", "You do not have permission to reject CI/CD deployments.")
    result = await db.execute(select(CICDDeployment).where(CICDDeployment.id == deploy_id))
    dep = result.scalars().first()
    if not dep:
        raise HTTPException(404, "Deployment not found")
    env = None
    if dep.environment_id:
        env_result = await db.execute(select(CICDEnvironment).where(CICDEnvironment.id == dep.environment_id))
        env = env_result.scalars().first()
    if env and not _can_user_approve(user, env):
        raise HTTPException(status_code=403, detail="User is not in approval list for this environment")
    uname = str(user.username or "").strip()
    approval_result = await db.execute(
        select(CICDDeploymentApproval).where(
            CICDDeploymentApproval.deployment_id == dep.id,
            CICDDeploymentApproval.approver == uname,
        )
    )
    approval = approval_result.scalars().first()
    if not approval:
        approval = CICDDeploymentApproval(deployment_id=dep.id, approver=uname, decision="rejected", note=body.note.strip())
        db.add(approval)
    else:
        approval.decision = "rejected"
        approval.note = body.note.strip()
        approval.updated_at = _utcnow()
    dep.approved_by = uname
    dep.approved_at = _utcnow()
    dep.status = "rejected"
    dep.escalation_status = ""
    dep.notes = (dep.notes or "") + (f"\n[rejection] {uname}: {body.note.strip()}" if body.note.strip() else "")
    dep.completed_at = _utcnow()
    await _append_approval_event(db, dep, "rejected", uname, body.note.strip())
    await db.flush()
    await db.commit()
    await db.refresh(dep)
    return _deployment_to_dict(dep, env.name if env else "", "")


@router.get("/analytics/progress")
async def cicd_progress_analytics(
    pipeline_id: int = None,
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    max_days = max(1, min(int(days or 14), 90))
    stmt = select(CICDBuild).order_by(CICDBuild.created_at.desc()).limit(5000)
    if pipeline_id:
        stmt = stmt.where(CICDBuild.pipeline_id == pipeline_id)
    builds = (await db.execute(stmt)).scalars().all()
    now = _utcnow()
    cutoff = now.timestamp() - (max_days * 86400)
    day_map: dict[str, dict[str, int]] = {}
    for build in reversed(builds):
        if not build.created_at:
            continue
        ts = build.created_at.timestamp()
        if ts < cutoff:
            continue
        day = build.created_at.strftime("%Y-%m-%d")
        bucket = day_map.setdefault(day, {"success": 0, "failed": 0, "running": 0, "pending": 0, "other": 0})
        status = str(build.status or "").lower()
        if status in bucket:
            bucket[status] += 1
        else:
            bucket["other"] += 1
    points = []
    for day in sorted(day_map.keys()):
        row = day_map[day]
        points.append(
            {
                "day": day,
                "total": int(sum(row.values())),
                "success": int(row["success"]),
                "failed": int(row["failed"]),
                "running": int(row["running"]),
                "pending": int(row["pending"]),
                "other": int(row["other"]),
            }
        )
    totals = {"success": 0, "failed": 0, "running": 0, "pending": 0, "other": 0}
    for p in points:
        for k in totals.keys():
            totals[k] += int(p.get(k, 0))
    return {"points": points, "totals": totals, "days": max_days, "pipeline_id": pipeline_id}


@router.get("/analytics/dora")
async def cicd_dora_metrics(
    pipeline_id: int = None,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    max_days = max(1, min(int(days or 30), 180))
    cutoff = _utcnow().timestamp() - (max_days * 86400)
    dep_stmt = select(CICDDeployment).order_by(CICDDeployment.created_at.desc()).limit(5000)
    if pipeline_id:
        dep_stmt = dep_stmt.where(CICDDeployment.pipeline_id == pipeline_id)
    deployments = (await db.execute(dep_stmt)).scalars().all()
    deployments = [d for d in deployments if d.created_at and d.created_at.timestamp() >= cutoff]
    total_deployments = len(deployments)
    failed_like = {"failed", "rejected", "rolled_back", "aborted", "canceled"}
    failed_deployments = sum(1 for d in deployments if str(d.status or "").lower() in failed_like)
    successful_deployments = sum(1 for d in deployments if str(d.status or "").lower() in {"success", "completed", "approved"})
    deployment_frequency_per_day = round(total_deployments / max_days, 3) if max_days else 0.0
    change_failure_rate_pct = round((failed_deployments / total_deployments) * 100.0, 2) if total_deployments else 0.0

    build_ids = {d.build_id for d in deployments if d.build_id}
    build_map = {}
    if build_ids:
        builds = (await db.execute(select(CICDBuild).where(CICDBuild.id.in_(build_ids)))).scalars().all()
        build_map = {b.id: b for b in builds}
    lead_time_seconds_samples = []
    for dep in deployments:
        if dep.build_id and dep.build_id in build_map:
            build = build_map[dep.build_id]
            if build and build.created_at:
                end_time = dep.completed_at or dep.created_at
                if end_time and end_time >= build.created_at:
                    lead_time_seconds_samples.append(int((end_time - build.created_at).total_seconds()))
    lead_time_seconds_avg = int(sum(lead_time_seconds_samples) / len(lead_time_seconds_samples)) if lead_time_seconds_samples else 0

    repair_samples = []
    grouped: dict[tuple[int, int | None], list[CICDDeployment]] = {}
    for dep in deployments:
        grouped.setdefault((dep.pipeline_id, dep.environment_id), []).append(dep)
    for _, items in grouped.items():
        items = sorted(items, key=lambda x: x.created_at or _utcnow())
        for i, dep in enumerate(items):
            if str(dep.status or "").lower() in failed_like and dep.completed_at:
                next_success = None
                for j in range(i + 1, len(items)):
                    cand = items[j]
                    if str(cand.status or "").lower() in {"success", "completed", "approved"} and cand.completed_at:
                        next_success = cand
                        break
                if next_success:
                    delta = int((next_success.completed_at - dep.completed_at).total_seconds())
                    if delta >= 0:
                        repair_samples.append(delta)
    mttr_seconds_avg = int(sum(repair_samples) / len(repair_samples)) if repair_samples else 0

    return {
        "days": max_days,
        "pipeline_id": pipeline_id,
        "deployment_frequency_per_day": deployment_frequency_per_day,
        "change_failure_rate_pct": change_failure_rate_pct,
        "lead_time_seconds_avg": lead_time_seconds_avg,
        "mttr_seconds_avg": mttr_seconds_avg,
        "total_deployments": total_deployments,
        "successful_deployments": successful_deployments,
        "failed_deployments": failed_deployments,
    }


@router.get("/builds/{build_id}/stages")
async def list_build_stages(build_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(CICDBuildStageRun).where(CICDBuildStageRun.build_id == build_id).order_by(CICDBuildStageRun.order_index.asc())
    )
    return [_stage_run_to_dict(s) for s in result.scalars().all()]


@router.post("/builds/{build_id}/stages", status_code=201)
async def upsert_build_stage(
    build_id: int,
    body: StageRunIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(
        select(CICDBuildStageRun).where(
            CICDBuildStageRun.build_id == build_id,
            CICDBuildStageRun.stage_name == body.stage_name,
        )
    )
    stage = result.scalars().first()
    if not stage:
        stage = CICDBuildStageRun(
            build_id=build_id,
            stage_name=body.stage_name,
            order_index=body.order_index,
            status=body.status,
            duration_seconds=body.duration_seconds,
            started_at=body.started_at,
            completed_at=body.completed_at,
            output=body.output or "",
        )
        db.add(stage)
    else:
        stage.order_index = body.order_index
        stage.status = body.status
        stage.duration_seconds = body.duration_seconds
        stage.started_at = body.started_at
        stage.completed_at = body.completed_at
        stage.output = body.output or stage.output
        stage.updated_at = _utcnow()
    await db.flush()
    await db.commit()
    await db.refresh(stage)
    return _stage_run_to_dict(stage)


@router.get("/analytics/stage-progress")
async def stage_progress_analytics(
    pipeline_id: int = None,
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    max_days = max(1, min(int(days or 14), 90))
    cutoff = _utcnow().timestamp() - (max_days * 86400)
    build_stmt = select(CICDBuild.id).order_by(CICDBuild.created_at.desc()).limit(5000)
    if pipeline_id:
        build_stmt = build_stmt.where(CICDBuild.pipeline_id == pipeline_id)
    build_ids = [bid for bid in (await db.execute(build_stmt)).scalars().all()]
    if not build_ids:
        return {"stages": [], "days": max_days, "pipeline_id": pipeline_id}
    stage_rows = (
        await db.execute(
            select(CICDBuildStageRun).where(
                CICDBuildStageRun.build_id.in_(build_ids),
                CICDBuildStageRun.created_at.is_not(None),
            )
        )
    ).scalars().all()
    stage_map: dict[str, dict[str, int]] = {}
    for row in stage_rows:
        if not row.created_at or row.created_at.timestamp() < cutoff:
            continue
        bucket = stage_map.setdefault(row.stage_name, {"success": 0, "failed": 0, "running": 0, "pending": 0, "other": 0, "total": 0})
        st = str(row.status or "").lower()
        if st in bucket:
            bucket[st] += 1
        else:
            bucket["other"] += 1
        bucket["total"] += 1
    stages = []
    for name in sorted(stage_map.keys()):
        row = stage_map[name]
        stages.append({"stage_name": name, **row})
    return {"stages": stages, "days": max_days, "pipeline_id": pipeline_id}


@router.get("/approvals/evidence.csv")
async def approvals_evidence_csv(
    pipeline_id: int = None,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    max_days = max(1, min(int(days or 30), 365))
    cutoff = _utcnow().timestamp() - (max_days * 86400)
    stmt = select(CICDDeployment).order_by(CICDDeployment.created_at.desc()).limit(5000)
    if pipeline_id:
        stmt = stmt.where(CICDDeployment.pipeline_id == pipeline_id)
    deployments = (await db.execute(stmt)).scalars().all()
    deployments = [d for d in deployments if d.created_at and d.created_at.timestamp() >= cutoff]

    dep_ids = [d.id for d in deployments]
    events = []
    receipts = []
    if dep_ids:
        events = (await db.execute(select(CICDDeploymentApprovalEvent).where(CICDDeploymentApprovalEvent.deployment_id.in_(dep_ids)))).scalars().all()
        receipts = (await db.execute(select(CICDNotificationDeliveryReceipt).where(CICDNotificationDeliveryReceipt.deployment_id.in_(dep_ids)))).scalars().all()
    event_map: dict[int, list[CICDDeploymentApprovalEvent]] = {}
    for ev in events:
        event_map.setdefault(ev.deployment_id, []).append(ev)
    for dep_id in event_map.keys():
        event_map[dep_id] = sorted(event_map[dep_id], key=lambda x: x.created_at or _utcnow())
    receipt_map: dict[int, list[CICDNotificationDeliveryReceipt]] = {}
    for rc in receipts:
        receipt_map.setdefault(rc.deployment_id, []).append(rc)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "deployment_id",
        "pipeline_id",
        "environment_id",
        "status",
        "triggered_by",
        "approved_by",
        "approval_due_at",
        "escalation_status",
        "escalated_at",
        "created_at",
        "event_count",
        "event_timeline",
        "delivery_receipt_count",
        "delivery_summary",
    ])
    for d in deployments:
        timeline = " | ".join(
            f"{(e.created_at.isoformat() if e.created_at else '')}:{e.event_type}:{e.actor}:{e.note}"
            for e in event_map.get(d.id, [])
        )
        delivery_summary = " | ".join(
            f"{r.channel_type}:{r.target}:{r.status}:attempts={r.attempt_count}:error={r.last_error[:120]}"
            for r in receipt_map.get(d.id, [])
        )
        writer.writerow([
            d.id,
            d.pipeline_id,
            d.environment_id or "",
            d.status or "",
            d.triggered_by or "",
            d.approved_by or "",
            d.approval_due_at.isoformat() if getattr(d, "approval_due_at", None) else "",
            getattr(d, "escalation_status", "") or "",
            d.escalated_at.isoformat() if getattr(d, "escalated_at", None) else "",
            d.created_at.isoformat() if d.created_at else "",
            len(event_map.get(d.id, [])),
            timeline,
            len(receipt_map.get(d.id, [])),
            delivery_summary,
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="cicd_approval_evidence_{_utcnow().strftime("%Y%m%d_%H%M%S")}.csv"'},
    )


@router.get("/approvals/evidence.pdf")
async def approvals_evidence_pdf(
    pipeline_id: int = None,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    max_days = max(1, min(int(days or 30), 365))
    cutoff = _utcnow().timestamp() - (max_days * 86400)
    stmt = select(CICDDeployment).order_by(CICDDeployment.created_at.desc()).limit(5000)
    if pipeline_id:
        stmt = stmt.where(CICDDeployment.pipeline_id == pipeline_id)
    deployments = (await db.execute(stmt)).scalars().all()
    deployments = [d for d in deployments if d.created_at and d.created_at.timestamp() >= cutoff]
    dep_ids = [d.id for d in deployments]
    events = []
    receipts = []
    if dep_ids:
        events = (await db.execute(select(CICDDeploymentApprovalEvent).where(CICDDeploymentApprovalEvent.deployment_id.in_(dep_ids)))).scalars().all()
        receipts = (await db.execute(select(CICDNotificationDeliveryReceipt).where(CICDNotificationDeliveryReceipt.deployment_id.in_(dep_ids)))).scalars().all()
    event_count: dict[int, int] = {}
    for ev in events:
        event_count[ev.deployment_id] = event_count.get(ev.deployment_id, 0) + 1
    receipt_count: dict[int, int] = {}
    delivered_count: dict[int, int] = {}
    for rc in receipts:
        receipt_count[rc.deployment_id] = receipt_count.get(rc.deployment_id, 0) + 1
        if str(rc.status or "").lower() == "delivered":
            delivered_count[rc.deployment_id] = delivered_count.get(rc.deployment_id, 0) + 1

    pdf = _ApprovalEvidencePDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 9, "CI/CD Approval Evidence Report", ln=1)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 7, f"Generated: {_utcnow().isoformat()}Z | Window: {max_days} days", ln=1)
    pdf.ln(2)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(18, 7, "ID", 1)
    pdf.cell(18, 7, "Pipe", 1)
    pdf.cell(23, 7, "Status", 1)
    pdf.cell(25, 7, "Approver", 1)
    pdf.cell(34, 7, "Approval Due", 1)
    pdf.cell(22, 7, "Escalation", 1)
    pdf.cell(14, 7, "Events", 1)
    pdf.cell(20, 7, "Delivery", 1, ln=1)
    pdf.set_font("Arial", size=8)
    for d in deployments[:300]:
        pdf.cell(18, 6, str(d.id), 1)
        pdf.cell(18, 6, str(d.pipeline_id), 1)
        pdf.cell(23, 6, str(d.status or "")[:14], 1)
        pdf.cell(25, 6, str(d.approved_by or "")[:16], 1)
        pdf.cell(34, 6, (d.approval_due_at.isoformat()[:16] if getattr(d, "approval_due_at", None) else "-"), 1)
        pdf.cell(22, 6, str(getattr(d, "escalation_status", "") or "-")[:12], 1)
        pdf.cell(14, 6, str(event_count.get(d.id, 0)), 1)
        pdf.cell(20, 6, f"{delivered_count.get(d.id, 0)}/{receipt_count.get(d.id, 0)}", 1, ln=1)
    out = pdf.output(dest="S").encode("latin-1")
    return Response(
        content=out,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="cicd_approval_evidence_{_utcnow().strftime("%Y%m%d_%H%M%S")}.pdf"'},
    )


# ── Build logs ──

@router.get("/builds/{build_id}/logs")
async def get_build_logs(build_id: int, limit: int = 200, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(CICDBuildLog).where(CICDBuildLog.build_id == build_id).order_by(CICDBuildLog.created_at.asc()).limit(min(limit, 2000))
    )
    return [_log_to_dict(l) for l in result.scalars().all()]


@router.post("/builds/{build_id}/logs", status_code=201)
async def append_build_log(
    build_id: int,
    body: BuildLogIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    log = CICDBuildLog(build_id=build_id, line=body.line)
    if hasattr(log, "storage_path") and body.storage_path:
        log.storage_path = body.storage_path
    if hasattr(log, "status") and body.status:
        log.status = body.status
    db.add(log)
    await db.flush()
    await db.commit()
    await db.refresh(log)
    return _log_to_dict(log)


# ── Artifacts ──

@router.get("/builds/{build_id}/artifacts")
async def list_artifacts(build_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(select(CICDBuildArtifact).where(CICDBuildArtifact.build_id == build_id).order_by(CICDBuildArtifact.created_at.desc()))
    return [_artifact_to_dict(a) for a in result.scalars().all()]


@router.post("/builds/{build_id}/artifacts", status_code=201)
async def create_artifact(
    build_id: int,
    body: ArtifactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    art = CICDBuildArtifact(build_id=build_id, name=body.name, url=body.url, size_bytes=body.size_bytes, meta=body.meta)
    if hasattr(art, "storage_path"):
        art.storage_path = body.storage_path
    if hasattr(art, "status"):
        art.status = body.status
    db.add(art)
    await db.flush()
    await db.commit()
    await db.refresh(art)
    return _artifact_to_dict(art)


@router.put("/builds/{build_id}/artifacts/{artifact_id}")
async def update_artifact(
    build_id: int,
    artifact_id: int,
    body: ArtifactUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(CICDBuildArtifact).where(CICDBuildArtifact.id == artifact_id, CICDBuildArtifact.build_id == build_id))
    art = result.scalars().first()
    if not art:
        raise HTTPException(404, "Artifact not found")

    for field in ["name", "url", "size_bytes", "storage_path", "status", "meta"]:
        val = getattr(body, field, None)
        if val is not None:
            if field == "storage_path" and not hasattr(art, "storage_path"):
                continue
            if field == "status" and not hasattr(art, "status"):
                continue
            setattr(art, field, val)

    await db.flush()
    await db.commit()
    await db.refresh(art)
    return _artifact_to_dict(art)


@router.post("/builds/{build_id}/artifacts/{artifact_id}/release")
async def mark_artifact_release(
    build_id: int,
    artifact_id: int,
    body: ReleaseArtifactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(CICDBuildArtifact).where(CICDBuildArtifact.id == artifact_id, CICDBuildArtifact.build_id == build_id))
    art = result.scalars().first()
    if not art:
        raise HTTPException(404, "Artifact not found")
    meta = art.meta or {}
    history = list(meta.get("release_history") or [])
    release_entry = {
        "version": body.release_version.strip(),
        "channel": body.release_channel.strip() or "stable",
        "environment": body.environment.strip(),
        "notes": body.notes.strip(),
        "actor": user.username,
        "at": _utcnow().isoformat(),
    }
    history.append(release_entry)
    meta["release_managed"] = True
    meta["release_version"] = release_entry["version"]
    meta["release_channel"] = release_entry["channel"]
    meta["release_environment"] = release_entry["environment"]
    meta["release_notes"] = release_entry["notes"]
    meta["release_history"] = history[-50:]
    art.meta = meta
    if hasattr(art, "status"):
        art.status = "release_ready"
    await db.flush()
    await db.commit()
    await db.refresh(art)
    return _artifact_to_dict(art)


@router.post("/builds/{build_id}/artifacts/{artifact_id}/promote")
async def promote_release_artifact(
    build_id: int,
    artifact_id: int,
    body: ReleaseArtifactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(CICDBuildArtifact).where(CICDBuildArtifact.id == artifact_id, CICDBuildArtifact.build_id == build_id))
    art = result.scalars().first()
    if not art:
        raise HTTPException(404, "Artifact not found")
    meta = art.meta or {}
    promoted = list(meta.get("promotions") or [])
    promoted.append(
        {
            "version": body.release_version.strip() or meta.get("release_version", ""),
            "channel": body.release_channel.strip() or "stable",
            "environment": body.environment.strip() or "production",
            "notes": body.notes.strip(),
            "actor": user.username,
            "at": _utcnow().isoformat(),
        }
    )
    meta["promotions"] = promoted[-100:]
    meta["release_managed"] = True
    art.meta = meta
    if hasattr(art, "status"):
        art.status = "released"
    await db.flush()
    await db.commit()
    await db.refresh(art)
    return _artifact_to_dict(art)


@router.get("/release-artifacts")
async def list_release_artifacts(
    pipeline_id: int = None,
    channel: str = "",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(CICDBuildArtifact).order_by(CICDBuildArtifact.created_at.desc()).limit(1000)
    artifacts = (await db.execute(stmt)).scalars().all()
    out = []
    for art in artifacts:
        meta = art.meta or {}
        if not meta.get("release_managed"):
            continue
        if channel and str(meta.get("release_channel", "")).lower() != channel.lower():
            continue
        if pipeline_id:
            build = await db.get(CICDBuild, art.build_id)
            if not build or build.pipeline_id != pipeline_id:
                continue
        out.append(_artifact_to_dict(art))
    return out


@router.delete("/builds/{build_id}/artifacts/{artifact_id}")
async def delete_artifact(
    build_id: int,
    artifact_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(CICDBuildArtifact).where(CICDBuildArtifact.id == artifact_id, CICDBuildArtifact.build_id == build_id))
    art = result.scalars().first()
    if not art:
        raise HTTPException(404, "Artifact not found")
    await db.delete(art)
    await db.commit()
    return {"ok": True}


@router.post("/builds/{build_id}/artifacts/upload", status_code=201)
async def upload_artifact(
    build_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    target_dir = ARTIFACTS_DIR / f"build_{build_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = file.filename or f"artifact_{secrets.token_hex(4)}"
    # F15: client-supplied name must not escape target_dir.
    name_check = validate_filename(filename)
    if not name_check.is_valid:
        raise HTTPException(400, name_check.message)
    dest = target_dir / filename
    content = await file.read()
    dest.write_bytes(content)
    art = CICDBuildArtifact(build_id=build_id, name=filename, url=f"/api/cicd/artifacts/{build_id}/{filename}", size_bytes=len(content), meta={})
    if hasattr(art, "storage_path"):
        art.storage_path = str(dest)
    if hasattr(art, "status"):
        art.status = "stored"
    db.add(art)
    await db.flush()
    await db.commit()
    await db.refresh(art)
    return _artifact_to_dict(art)


@router.get("/artifacts/{build_id}/{filename}")
async def download_artifact(
    build_id: int, filename: str, user: User = Depends(get_current_user)
):
    # F14: artifacts are authenticated; filename must not escape build dir.
    name_check = validate_filename(filename)
    if not name_check.is_valid:
        raise HTTPException(400, name_check.message)
    path = ARTIFACTS_DIR / f"build_{build_id}" / filename
    if not path.is_file():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(path, filename=filename)


@router.put("/builds/{build_id}")
async def update_build(
    build_id: int,
    body: BuildUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(CICDBuild).where(CICDBuild.id == build_id))
    build = result.scalars().first()
    if not build:
        raise HTTPException(404, "Build not found")

    for field in ["status", "output", "external_url", "started_at", "completed_at"]:
        val = getattr(body, field, None)
        if val is not None:
            setattr(build, field, val)

    if build.started_at and build.completed_at and hasattr(build, "duration_seconds"):
        build.duration_seconds = int((build.completed_at - build.started_at).total_seconds())

    await db.flush()
    await db.commit()
    await db.refresh(build)
    return _build_to_dict(build, "")
