"""Patch Jobs API — tracks all patch operations in PostgreSQL."""

from datetime import datetime


def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import List, Optional

from database import get_db
from database import async_session
from auth import get_current_user, require_role
from license import get_license_info
from models.db_models import PatchJob, Host, JobStatus, PatchAction, UserRole, User

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobOut(BaseModel):
    id: int
    host_id: int
    host_name: str = ""
    host_ip: str = ""
    action: str
    status: str
    packages: list = []
    dry_run: bool
    auto_snapshot: bool
    auto_rollback: bool
    result: Optional[dict] = None
    output: str = ""
    initiated_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class JobCreate(BaseModel):
    host_id: int
    action: str = "server_patch"
    packages: List[str] = []
    hold_packages: List[str] = []
    dry_run: bool = False
    auto_snapshot: bool = True
    auto_rollback: bool = True


class JobUpdate(BaseModel):
    status: Optional[str] = None
    result: Optional[dict] = None
    output: Optional[str] = None


def _job_to_out(job: PatchJob) -> dict:
    d = {c.name: getattr(job, c.name) for c in job.__table__.columns}
    d["action"] = job.action.value if job.action else ""
    d["status"] = job.status.value if job.status else ""
    d["host_name"] = job.host.hostname if job.host else ""
    d["host_ip"] = job.host.ip if job.host else ""
    return d


@router.get("/")
async def list_jobs(
    status: Optional[str] = None,
    host_id: Optional[int] = None,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .order_by(desc(PatchJob.created_at))
    )
    if status:
        try:
            q = q.where(PatchJob.status == JobStatus(status))
        except ValueError:
            raise HTTPException(
                400,
                f"Invalid status '{status}'. Valid values: {[s.value for s in JobStatus]}",
            )
    if host_id:
        q = q.where(PatchJob.host_id == host_id)

    # Get total count
    count_q = select(func.count()).select_from(q.subquery())
    total = await db.scalar(count_q) or 0

    # Apply pagination
    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    items = [_job_to_out(j) for j in result.scalars().all()]
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/stats")
async def job_stats(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    total = await db.scalar(select(func.count(PatchJob.id)))
    running = await db.scalar(
        select(func.count(PatchJob.id)).where(PatchJob.status == JobStatus.running)
    )
    success = await db.scalar(
        select(func.count(PatchJob.id)).where(PatchJob.status == JobStatus.success)
    )
    failed = await db.scalar(
        select(func.count(PatchJob.id)).where(PatchJob.status == JobStatus.failed)
    )
    pending = await db.scalar(
        select(func.count(PatchJob.id)).where(PatchJob.status == JobStatus.pending)
    )
    rolled_back = await db.scalar(
        select(func.count(PatchJob.id)).where(PatchJob.status == JobStatus.rolled_back)
    )
    return {
        "total": total,
        "running": running,
        "success": success,
        "failed": failed,
        "pending": pending,
        "rolled_back": rolled_back,
    }


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_out(job)


@router.post("/", response_model=JobOut)
async def create_job(
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    # Lock host row to prevent concurrent jobs on same host
    result = await db.execute(
        select(Host).where(Host.id == body.host_id).with_for_update()
    )
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(404, "Host not found")
    _ensure_patch_license_for_host(host)

    job = PatchJob(
        host_id=body.host_id,
        action=PatchAction(body.action),
        status=JobStatus.pending,
        packages=body.packages,
        hold_packages=body.hold_packages,
        dry_run=body.dry_run,
        auto_snapshot=body.auto_snapshot,
        auto_rollback=body.auto_rollback,
        initiated_by=user.username,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    # Eagerly load host
    result = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == job.id)
    )
    job = result.scalar_one()
    return _job_to_out(job)


@router.delete("/{job_id}")
async def delete_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await db.execute(select(PatchJob).where(PatchJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    await db.delete(job)
    await db.commit()
    return {"ok": True}


async def update_job(
    job_id: int,
    body: JobUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    # Use FOR UPDATE to prevent transaction locks
    result = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == job_id)
        .with_for_update()
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")

    if body.status:
        try:
            job.status = JobStatus(body.status)
        except ValueError:
            raise HTTPException(400, "Invalid status")
    if body.result is not None:
        job.result = body.result
    if body.output is not None:
        job.output = body.output

    # BUG-001 FIX: Set completed_at and fire notifications BEFORE commit
    # This ensures all side effects complete before transaction is committed
    status = job.status
    host = job.host

    if status in [JobStatus.success, JobStatus.failed]:
        job.completed_at = _utcnow()
        # Fire notifications synchronously before commit to ensure consistency
        if status == JobStatus.failed:
            from api.notifications import notify_system_event

            try:
                await notify_system_event(
                    "job_failed",
                    f"Patch Job Failed: {host.hostname}",
                    f"Job #{job_id} failed on {host.ip}. Click to view details.",
                    f"/jobs/{job_id}",
                )
            except Exception:
                pass  # Don't fail the update if notification fails
        elif status == JobStatus.success:
            from api.notifications import notify_system_event

            try:
                await notify_system_event(
                    "job_success",
                    f"Patch Job Completed: {host.hostname}",
                    f"Job #{job_id} completed successfully.",
                    f"/jobs/{job_id}",
                )
            except Exception:
                pass  # Don't fail the update if notification fails

    # Commit once after all side effects are complete
    await db.commit()
    await db.refresh(job)
    return _job_to_out(job)


def _ensure_patch_license_for_host(host: Host):
    """License gate per-OS patching."""
    license_info = get_license_info()
    features = set(license_info.get("features") or [])
    os_name = (host.os or "").lower()
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


@router.get("/status/{job_id}")
async def get_job_status(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # BUG-002 FIX: Acquire lock FIRST, then check age inside the lock
    # This prevents race condition where multiple readers all see stale job
    # and try to mark it failed simultaneously

    # First, try to acquire lock on pending job
    locked = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == job_id, PatchJob.status == JobStatus.pending)
        .with_for_update(skip_locked=True)
    )
    locked_job = locked.scalar_one_or_none()

    if locked_job:
        # NOW check age inside the lock - only one request will get here
        age_seconds = 0
        if locked_job.created_at:
            age_seconds = max(
                int((_utcnow() - locked_job.created_at).total_seconds()), 0
            )

        if age_seconds >= 120:
            # Mark as failed - we have exclusive lock
            locked_job.status = JobStatus.failed
            locked_job.completed_at = _utcnow()
            base_out = (locked_job.output or "").strip()
            extra = "Job remained pending for too long and was marked failed. Retry the operation."
            locked_job.output = f"{base_out}\n{extra}" if base_out else extra
            await db.commit()
            await db.refresh(locked_job)
            return _job_to_out(locked_job)
        else:
            # Job is pending but not stale yet
            return _job_to_out(locked_job)

    # Job is not pending (or someone else has the lock), fetch normally
    result = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_out(job)


@router.post("/{job_id}/rollback", response_model=JobOut)
async def rollback_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Roll back a completed patch job by reverting to the pre-patch snapshot."""
    import httpx

    result = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in [JobStatus.success, JobStatus.failed]:
        raise HTTPException(
            400,
            f"Cannot rollback a job with status '{job.status}'. Only success/failed jobs can be rolled back.",
        )

    host = job.host
    if not host:
        raise HTTPException(404, "Host not found for this job")

    # Create a rollback job record
    rollback_job = PatchJob(
        host_id=host.id,
        action=PatchAction.rollback,
        status=JobStatus.running,
        packages=job.packages,
        dry_run=False,
        auto_snapshot=False,
        auto_rollback=False,
        initiated_by=user.username,
        output=f"Rolling back job #{job_id} on {host.hostname}...\n",
        started_at=_utcnow(),
    )
    db.add(rollback_job)
    await db.flush()
    await db.refresh(rollback_job)

    # Attempt snapshot rollback via agent
    AGENT_PORT = int(os.getenv("AGENT_PORT", "8080"))
    _global_agent_token = os.environ.get("AGENT_API_TOKEN", "").strip()
    _host_token = (host.agent_token or "").strip() if host else ""
    _token = _host_token or _global_agent_token
    _auth_headers = {"Authorization": f"Bearer {_token}"} if _token else {}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"http://{host.ip}:{AGENT_PORT}/snapshot/rollback",
                json={"ref_job_id": job_id},
                headers=_auth_headers,
            )
            result_data = r.json() if r.status_code == 200 else {"error": r.text}

            # BUG-012 FIX: Check for Windows "not supported" error and provide clear message
            agent_success = r.status_code == 200 and result_data.get("success", True)

            # Check if Windows doesn't support snapshots
            error_msg = str(result_data.get("error", "")).lower()
            if "not supported" in error_msg:
                rollback_job.status = JobStatus.failed
                rollback_job.output += "\n\nSnapshot rollback is not supported on Windows. Use Windows System Restore or backup tools instead."
            else:
                rollback_job.status = (
                    JobStatus.rolled_back if agent_success else JobStatus.failed
                )
                rollback_job.output += result_data.get("output", r.text or "Done")
            rollback_job.result = result_data
    except Exception as e:
        rollback_job.status = JobStatus.failed
        rollback_job.output += f"Rollback failed: {e}"
        rollback_job.result = {"error": str(e)}

    rollback_job.completed_at = _utcnow()
    # Mark original job as rolled_back
    job.status = JobStatus.rolled_back
    await db.commit()
    await db.refresh(rollback_job)
    result2 = await db.execute(
        select(PatchJob)
        .options(selectinload(PatchJob.host))
        .where(PatchJob.id == rollback_job.id)
    )
    return _job_to_out(result2.scalar_one())


@router.websocket("/ws/job/{job_id}")
async def job_status_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    # F5: job status streams host/patch data - authenticate like /api/notifications/ws.
    from api.notifications import _resolve_websocket_user

    if not await _resolve_websocket_user(websocket):
        await websocket.close(code=4401)
        return
    if not job_id.isdigit():
        await websocket.send_json({"error": "Invalid job ID"})
        await websocket.close()
        return
    async with async_session() as session:
        try:
            async with asyncio.timeout(300):
                while True:
                    result = await session.execute(
                        select(PatchJob)
                        .options(selectinload(PatchJob.host))
                        .where(PatchJob.id == int(job_id))
                    )
                    job = result.scalar_one_or_none()
                    if not job:
                        await websocket.send_json({"error": "Job not found"})
                        break
                    await websocket.send_json(_job_to_out(job))
                    if job.status in [
                        JobStatus.success,
                        JobStatus.failed,
                        JobStatus.rolled_back,
                        JobStatus.aborted,
                    ]:
                        break
                    await asyncio.sleep(2)
        except asyncio.TimeoutError:
            await websocket.send_json(
                {"error": "WebSocket timeout after 5 minutes of inactivity"}
            )
        except Exception:
            pass
        finally:
            await websocket.close()
