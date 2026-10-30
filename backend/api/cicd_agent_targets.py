"""CI/CD Agent Targets — run CD pipeline steps on specific hosts via the Patch-SecOps Solution agent.

Each CICDAgentTarget links a pipeline+environment to a registered host.
When a pipeline stage has runner_label matching a target label (or 'agent'),
the internal executor dispatches the command to that host via /run endpoint
and streams the output back into the build log.
"""
import asyncio
import os
from datetime import datetime

def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_role
from database import get_db, async_session
from models.db_models import (
    CICDAgentRun,
    CICDAgentTarget,
    CICDPipeline,
    CICDEnvironment,
    Host,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/cicd/agent-targets", tags=["cicd-agent-targets"])

AGENT_PORT = int(os.getenv("PM_AGENT_PORT", "8080"))
WINDOWS_AGENT_PORT = int(os.getenv("PM_WINDOWS_AGENT_PORT", "18080"))

# ── Pydantic schemas ──

class AgentTargetCreate(BaseModel):
    pipeline_id: int
    environment_id: Optional[int] = None
    host_id: int
    label: str = ""
    run_as: str = ""
    working_dir: str = ""
    is_active: bool = True


class AgentTargetUpdate(BaseModel):
    environment_id: Optional[int] = None
    host_id: Optional[int] = None
    label: Optional[str] = None
    run_as: Optional[str] = None
    working_dir: Optional[str] = None
    is_active: Optional[bool] = None


class AgentRunOut(BaseModel):
    id: int
    build_id: int
    target_id: Optional[int]
    host_ip: str
    stage_name: str
    command: str
    status: str
    output: str
    exit_code: Optional[int]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str


def _target_to_dict(t: CICDAgentTarget, host: Optional[Host] = None) -> dict:
    return {
        "id": t.id,
        "pipeline_id": t.pipeline_id,
        "environment_id": t.environment_id,
        "host_id": t.host_id,
        "host_ip": host.ip if host else "",
        "hostname": host.hostname if host else "",
        "label": t.label or "",
        "run_as": t.run_as or "",
        "working_dir": t.working_dir or "",
        "is_active": bool(t.is_active),
        "created_by": t.created_by or "",
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "updated_at": t.updated_at.isoformat() if t.updated_at else "",
    }


def _run_to_dict(r: CICDAgentRun) -> dict:
    return {
        "id": r.id,
        "build_id": r.build_id,
        "target_id": r.target_id,
        "host_ip": r.host_ip or "",
        "stage_name": r.stage_name or "",
        "command": r.command or "",
        "status": r.status or "pending",
        "output": r.output or "",
        "exit_code": r.exit_code,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ── Routes ──

@router.get("/")
async def list_targets(
    pipeline_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(CICDAgentTarget).order_by(CICDAgentTarget.id.asc())
    if pipeline_id is not None:
        stmt = stmt.where(CICDAgentTarget.pipeline_id == pipeline_id)
    rows = (await db.execute(stmt)).scalars().all()
    result = []
    for t in rows:
        host = await db.get(Host, t.host_id)
        result.append(_target_to_dict(t, host))
    return result


@router.post("/", status_code=201)
async def create_target(
    body: AgentTargetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    pipeline = await db.get(CICDPipeline, body.pipeline_id)
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    host = await db.get(Host, body.host_id)
    if not host:
        raise HTTPException(404, "Host not found")
    if body.environment_id is not None:
        env = await db.get(CICDEnvironment, body.environment_id)
        if not env or env.pipeline_id != body.pipeline_id:
            raise HTTPException(404, "Environment not found for this pipeline")

    target = CICDAgentTarget(
        pipeline_id=body.pipeline_id,
        environment_id=body.environment_id,
        host_id=body.host_id,
        label=body.label.strip() or host.hostname or host.ip,
        run_as=body.run_as.strip(),
        working_dir=body.working_dir.strip(),
        is_active=body.is_active,
        created_by=getattr(user, "username", "system"),
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)
    return _target_to_dict(target, host)


@router.put("/{target_id}")
async def update_target(
    target_id: int,
    body: AgentTargetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    target = await db.get(CICDAgentTarget, target_id)
    if not target:
        raise HTTPException(404, "Agent target not found")
    if body.host_id is not None:
        host = await db.get(Host, body.host_id)
        if not host:
            raise HTTPException(404, "Host not found")
        target.host_id = body.host_id
    if body.environment_id is not None:
        target.environment_id = body.environment_id
    if body.label is not None:
        target.label = body.label.strip()
    if body.run_as is not None:
        target.run_as = body.run_as.strip()
    if body.working_dir is not None:
        target.working_dir = body.working_dir.strip()
    if body.is_active is not None:
        target.is_active = body.is_active
    target.updated_at = _utcnow()
    db.add(target)
    await db.commit()
    await db.refresh(target)
    host = await db.get(Host, target.host_id)
    return _target_to_dict(target, host)


@router.delete("/{target_id}")
async def delete_target(
    target_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    target = await db.get(CICDAgentTarget, target_id)
    if not target:
        raise HTTPException(404, "Agent target not found")
    await db.delete(target)
    await db.commit()
    return {"status": "ok"}


@router.get("/runs")
async def list_runs(
    build_id: Optional[int] = None,
    target_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(CICDAgentRun).order_by(CICDAgentRun.created_at.desc())
    if build_id is not None:
        stmt = stmt.where(CICDAgentRun.build_id == build_id)
    if target_id is not None:
        stmt = stmt.where(CICDAgentRun.target_id == target_id)
    rows = (await db.execute(stmt.limit(200))).scalars().all()
    return [_run_to_dict(r) for r in rows]


@router.post("/runs/{run_id}/retry")
async def retry_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    run = await db.get(CICDAgentRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status == "running":
        raise HTTPException(409, "Run is already in progress")
    # Reset and re-dispatch
    run.status = "pending"
    run.output = ""
    run.exit_code = None
    run.started_at = None
    run.completed_at = None
    db.add(run)
    await db.commit()
    asyncio.create_task(_dispatch_agent_run(run.id))
    return {"status": "retrying", "run_id": run.id}


# ── Internal dispatcher ──

def _agent_port(host: Host) -> int:
    os_name = (host.os or "").lower()
    return WINDOWS_AGENT_PORT if "win" in os_name else AGENT_PORT


async def _dispatch_agent_run(run_id: int) -> None:
    """Execute a command on the target agent and record the result."""
    async with async_session() as db:
        run = await db.get(CICDAgentRun, run_id)
        if not run:
            return
        host = await db.get(Host, run.host_id) if run.host_id else None
        ip = run.host_ip or (host.ip if host else "")
        if not ip:
            run.status = "failed"
            run.output = "No host IP available for this agent run"
            run.completed_at = _utcnow()
            db.add(run)
            await db.commit()
            return

        port = _agent_port(host) if host else AGENT_PORT
        run.status = "running"
        run.started_at = _utcnow()
        db.add(run)
        await db.commit()

        # Resolve working_dir from target if available
        working_dir = ""
        if run.target_id:
            target = await db.get(CICDAgentTarget, run.target_id)
            if target:
                working_dir = target.working_dir or ""

        try:
            payload = {
                "command": run.command,
                "timeout": 300,
                "working_dir": working_dir,
            }
            _global_agent_token = os.environ.get("AGENT_API_TOKEN", "").strip()
            _host_token = (host.agent_token or "").strip() if host else ""
            _token = _host_token or _global_agent_token
            _auth_headers = {"Authorization": f"Bearer {_token}"} if _token else {}
            async with httpx.AsyncClient(timeout=310.0) as client:
                resp = await client.post(
                    f"http://{ip}:{port}/run",
                    json=payload,
                    headers=_auth_headers,
                )
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"output": resp.text}
            run.exit_code = int(data.get("exit_code", 0) if resp.status_code < 400 else 1)
            run.output = str(data.get("output", "") or data.get("stdout", "") or "")[:32000]
            run.status = "success" if run.exit_code == 0 else "failed"
        except Exception as exc:
            run.exit_code = -1
            run.output = f"Dispatch error: {exc}"
            run.status = "failed"

        run.completed_at = _utcnow()
        db.add(run)
        await db.commit()


async def dispatch_stage_to_agents(
    build_id: int,
    pipeline_id: int,
    environment_id: Optional[int],
    stage_name: str,
    command: str,
    runner_label: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Find all active agent targets for this pipeline+environment whose label
    matches runner_label (or runner_label == 'agent' to match all).
    Dispatch the command to each and return run records.
    """
    stmt = select(CICDAgentTarget).where(
        CICDAgentTarget.pipeline_id == pipeline_id,
        CICDAgentTarget.is_active == True,
    )
    if environment_id is not None:
        stmt = stmt.where(
            (CICDAgentTarget.environment_id == environment_id) |
            (CICDAgentTarget.environment_id.is_(None))
        )
    targets = (await db.execute(stmt)).scalars().all()

    # Filter by label
    matched = []
    for t in targets:
        if runner_label in ("agent", "all", "*", ""):
            matched.append(t)
        elif t.label and t.label.lower() == runner_label.lower():
            matched.append(t)

    runs = []
    for target in matched:
        host = await db.get(Host, target.host_id)
        run = CICDAgentRun(
            build_id=build_id,
            target_id=target.id,
            host_id=target.host_id,
            host_ip=host.ip if host else "",
            stage_name=stage_name,
            command=command,
            status="pending",
        )
        db.add(run)
        await db.flush()
        runs.append(run)

    await db.commit()

    # Dispatch all in parallel
    tasks = [_dispatch_agent_run(r.id) for r in runs]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Refresh and return
    result = []
    for r in runs:
        await db.refresh(r)
        result.append(_run_to_dict(r))
    return result
