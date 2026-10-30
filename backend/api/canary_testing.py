"""
Canary Testing API for Patch-SecOps Solution.

Provides canary deployment and testing functionality.
Routes a small percentage of traffic to new patches, monitors for issues,
and gradually rolls out to all hosts.
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from database import async_session, get_db
from models.db_models import (
    AuditLog,
    Host,
    HostGroup,
    JobStatus,
    PatchAction,
    PatchJob,
    User,
    UserRole,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/canary", tags=["canary-testing"])


def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


class CanaryStrategy(str, Enum):
    """Canary deployment strategies."""

    PERCENTAGE = "percentage"  # X% of hosts
    HOST_GROUP = "host_group"  # Specific host group
    RANDOM = "random"  # Random selection


class CanaryStatus(str, Enum):
    """Canary run status."""

    PENDING = "pending"
    RUNNING = "running"
    MONITORING = "monitoring"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class CanaryPolicy(BaseModel):
    """Policy for canary testing."""

    name: str
    description: str = ""
    strategy: CanaryStrategy = CanaryStrategy.PERCENTAGE
    canary_percentage: float = 5.0  # 5% default
    canary_group_id: Optional[int] = None
    packages: list[str] = []
    hold_packages: list[str] = []
    monitor_duration_seconds: int = 300  # 5 minutes default
    success_threshold: float = 0.95  # 95% success rate
    failure_threshold: float = 0.10  # 10% failure triggers rollback
    auto_promote: bool = False
    target_os_family: str = "linux"


class CanaryPolicyResponse(BaseModel):
    id: int
    name: str
    description: str
    strategy: str
    canary_percentage: float
    canary_group_id: Optional[int]
    packages: list[str]
    monitor_duration_seconds: int
    success_threshold: float
    failure_threshold: float
    auto_promote: bool
    target_os_family: str
    model_config = ConfigDict(from_attributes=True)


class CanaryRunResponse(BaseModel):
    """Response for canary run."""

    id: int
    policy_id: int
    status: str
    canary_hosts: int
    total_hosts: int
    canary_succeeded: int
    canary_failed: int
    monitoring_until: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    promoted_at: Optional[datetime]


# In-memory storage (would be DB in production)
_canary_policies: dict[int, dict[str, Any]] = {}
_canary_runs: dict[int, dict[str, Any]] = {}
_policy_id_counter = 1
_run_id_counter = 1


async def _trigger_full_rollout(run_id: int):
    """Trigger full rollout to all remaining hosts after successful canary.

    Args:
        run_id: Canary run ID that was promoted
    """
    global _canary_runs

    run = _canary_runs.get(run_id)
    if not run:
        logger.warning(f"Cannot trigger rollout: run {run_id} not found")
        return

    policy = run["policy"]
    all_hosts = run["hosts"]
    canary_host_count = run.get("canary_hosts", 0)

    # Get remaining hosts (exclude canary hosts)
    remaining_hosts = all_hosts[canary_host_count:]

    if not remaining_hosts:
        logger.info(f"No remaining hosts for rollout in run {run_id}")
        return

    logger.info(
        f"Triggering full rollout for run {run_id}: "
        f"{len(remaining_hosts)} remaining hosts"
    )

    async with async_session() as db:
        rollout_job_ids = []
        for host in remaining_hosts:
            try:
                job = await _create_canary_job(
                    host,
                    policy.packages,
                    policy.hold_packages,
                    f"canary-rollout-{run_id}",
                    db,
                )
                rollout_job_ids.append(job.id)
            except Exception as e:
                logger.error(f"Failed to create rollout job for host {host.id}: {e}")

        await db.commit()

        # Store rollout job IDs in run metadata
        run["rollout_job_ids"] = rollout_job_ids
        run["rollout_triggered_at"] = _utcnow()

        logger.info(
            f"Full rollout triggered for run {run_id}: "
            f"{len(rollout_job_ids)} jobs created"
        )


async def _create_canary_job(
    host: Host,
    packages: list[str],
    hold_packages: list[str],
    requested_by: str,
    db: AsyncSession,
) -> PatchJob:
    """Create a patch job for canary host."""
    job = PatchJob(
        host_id=host.id,
        action=PatchAction.upgrade,
        status=JobStatus.pending,
        packages=packages,
        hold_packages=hold_packages,
        dry_run=False,
        auto_snapshot=True,
        auto_rollback=True,
        initiated_by=requested_by,
    )
    db.add(job)
    await db.flush()
    return job


async def _monitor_canary_run(run_id: int):
    """Monitor a canary run and determine success/failure.

    Args:
        run_id: Run ID to monitor
    """
    global _canary_runs

    run = _canary_runs.get(run_id)
    if not run:
        return

    policy = run["policy"]
    monitor_duration = policy.monitor_duration_seconds

    # Wait for monitoring period
    await asyncio.sleep(monitor_duration)

    # Check results
    async with async_session() as db:
        canary_job_ids = run.get("canary_job_ids", [])
        if not canary_job_ids:
            run["status"] = CanaryStatus.FAILED
            return

        result = await db.execute(
            select(PatchJob).where(PatchJob.id.in_(canary_job_ids))
        )
        jobs = result.scalars().all()

        total = len(jobs)
        if total == 0:
            run["status"] = CanaryStatus.FAILED
            return

        succeeded = sum(1 for j in jobs if j.status == JobStatus.success)
        failed = sum(
            1 for j in jobs if j.status in {JobStatus.failed, JobStatus.cancelled}
        )

        success_rate = succeeded / total if total > 0 else 0
        failure_rate = failed / total if total > 0 else 0

        run["canary_succeeded"] = succeeded
        run["canary_failed"] = failed

        if failure_rate >= policy.failure_threshold:
            run["status"] = CanaryStatus.ROLLED_BACK
            run["completed_at"] = _utcnow()
            run["failure_reason"] = (
                f"Failure rate {failure_rate:.1%} exceeded threshold"
            )
        elif success_rate >= policy.success_threshold:
            if policy.auto_promote:
                run["status"] = CanaryStatus.PROMOTED
                run["promoted_at"] = _utcnow()
                # Trigger full rollout to remaining hosts
                await _trigger_full_rollout(run_id)
            else:
                run["status"] = CanaryStatus.MONITORING
        else:
            run["status"] = CanaryStatus.FAILED
            run["completed_at"] = _utcnow()
            run["failure_reason"] = f"Success rate {success_rate:.1%} below threshold"


async def _execute_canary_run(run_id: int):
    """Execute a canary run.

    Args:
        run_id: Run ID
    """
    global _canary_runs

    run = _canary_runs.get(run_id)
    if not run:
        return

    policy = run["policy"]
    hosts = run["hosts"]

    total_hosts = len(hosts)

    # Select canary hosts
    if policy.strategy == CanaryStrategy.PERCENTAGE:
        canary_count = max(1, int(total_hosts * (policy.canary_percentage / 100)))
        canary_hosts = hosts[:canary_count]
    elif policy.strategy == CanaryStrategy.HOST_GROUP and policy.canary_group_id:
        async with async_session() as db:
            result = await db.execute(
                select(Host).where(
                    Host.groups.any(HostGroup.id == policy.canary_group_id),
                    Host.is_online == True,
                )
            )
            canary_hosts = result.scalars().all()
    else:
        canary_hosts = hosts[:1]  # At least one

    run["canary_hosts"] = len(canary_hosts)
    run["status"] = CanaryStatus.RUNNING

    async with async_session() as db:
        # Create jobs for canary hosts
        canary_job_ids = []
        for host in canary_hosts:
            job = await _create_canary_job(
                host,
                policy.packages,
                policy.hold_packages,
                run["requested_by"],
                db,
            )
            canary_job_ids.append(job.id)

        await db.commit()
        run["canary_job_ids"] = canary_job_ids

    # Start monitoring
    run["status"] = CanaryStatus.MONITORING
    run["monitoring_until"] = _utcnow()

    await _monitor_canary_run(run_id)


@router.post("/policies", response_model=CanaryPolicyResponse)
async def create_canary_policy(
    body: CanaryPolicy,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Create a canary testing policy."""
    global _policy_id_counter, _canary_policies

    policy_id = _policy_id_counter
    _policy_id_counter += 1

    policy_dict = {
        "id": policy_id,
        "name": body.name,
        "description": body.description,
        "strategy": body.strategy.value,
        "canary_percentage": body.canary_percentage,
        "canary_group_id": body.canary_group_id,
        "packages": body.packages,
        "hold_packages": body.hold_packages,
        "monitor_duration_seconds": body.monitor_duration_seconds,
        "success_threshold": body.success_threshold,
        "failure_threshold": body.failure_threshold,
        "auto_promote": body.auto_promote,
        "target_os_family": body.target_os_family,
    }

    _canary_policies[policy_id] = policy_dict

    audit = AuditLog(
        user_id=current_user.id,
        action="canary.policy_created",
        target_type="canary_policy",
        target_id=str(policy_id),
        details={"name": body.name},
    )
    db.add(audit)
    await db.commit()

    return policy_dict


@router.get("/policies", response_model=list[CanaryPolicyResponse])
async def list_canary_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """List all canary testing policies."""
    return list(_canary_policies.values())


@router.delete("/policies/{policy_id}")
async def delete_canary_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete a canary testing policy."""
    if policy_id not in _canary_policies:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy = _canary_policies.pop(policy_id)

    audit = AuditLog(
        user_id=current_user.id,
        action="canary.policy_deleted",
        target_type="canary_policy",
        target_id=str(policy_id),
        details={"name": policy.get("name")},
    )
    db.add(audit)
    await db.commit()

    return {"status": "ok"}


@router.post("/policies/{policy_id}/run")
async def start_canary_run(
    policy_id: int,
    host_ids: Optional[list[int]] = None,
    group_ids: Optional[list[int]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Start a canary test run."""
    global _run_id_counter, _canary_runs

    if policy_id not in _canary_policies:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy_dict = _canary_policies[policy_id]
    policy = CanaryPolicy(
        name=policy_dict["name"],
        description=policy_dict["description"],
        strategy=CanaryStrategy(policy_dict["strategy"]),
        canary_percentage=policy_dict["canary_percentage"],
        canary_group_id=policy_dict["canary_group_id"],
        packages=policy_dict["packages"],
        hold_packages=policy_dict["hold_packages"],
        monitor_duration_seconds=policy_dict["monitor_duration_seconds"],
        success_threshold=policy_dict["success_threshold"],
        failure_threshold=policy_dict["failure_threshold"],
        auto_promote=policy_dict["auto_promote"],
        target_os_family=policy_dict["target_os_family"],
    )

    # Resolve hosts
    stmt = select(Host).where(Host.is_online == True)
    if policy.target_os_family != "any":
        stmt = stmt.where(Host.os_family == policy.target_os_family)

    if host_ids:
        stmt = stmt.where(Host.id.in_(host_ids))
    if group_ids:
        stmt = stmt.where(Host.groups.any(HostGroup.id.in_(group_ids)))

    result = await db.execute(stmt)
    hosts = result.scalars().all()

    if not hosts:
        raise HTTPException(status_code=400, detail="No hosts found")

    # Create run
    run_id = _run_id_counter
    _run_id_counter += 1

    run = {
        "id": run_id,
        "policy_id": policy_id,
        "policy": policy,
        "hosts": list(hosts),
        "requested_by": current_user.username,
        "status": CanaryStatus.PENDING,
        "total_hosts": len(hosts),
        "canary_hosts": 0,
        "canary_succeeded": 0,
        "canary_failed": 0,
        "started_at": _utcnow(),
        "completed_at": None,
    }

    _canary_runs[run_id] = run

    # Start async execution
    asyncio.create_task(_execute_canary_run(run_id))

    audit = AuditLog(
        user_id=current_user.id,
        action="canary.run_started",
        target_type="canary_run",
        target_id=str(run_id),
        details={"policy_id": policy_id},
    )
    db.add(audit)
    await db.commit()

    return {
        "run_id": run_id,
        "status": "started",
        "total_hosts": len(hosts),
    }


@router.get("/runs/{run_id}", response_model=CanaryRunResponse)
async def get_canary_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """Get canary run status."""
    if run_id not in _canary_runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = _canary_runs[run_id]
    return {
        "id": run["id"],
        "policy_id": run["policy_id"],
        "status": run["status"].value
        if isinstance(run["status"], CanaryStatus)
        else run["status"],
        "canary_hosts": run["canary_hosts"],
        "total_hosts": run["total_hosts"],
        "canary_succeeded": run["canary_succeeded"],
        "canary_failed": run["canary_failed"],
        "monitoring_until": run.get("monitoring_until"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "promoted_at": run.get("promoted_at"),
    }


@router.get("/runs")
async def list_canary_runs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """List recent canary runs."""
    runs = list(_canary_runs.values())
    runs.sort(key=lambda r: r.get("started_at") or datetime.min, reverse=True)
    return runs[:limit]


@router.post("/runs/{run_id}/promote")
async def promote_canary(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Manually promote a canary to full rollout."""
    if run_id not in _canary_runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = _canary_runs[run_id]
    if run["status"] != CanaryStatus.MONITORING:
        raise HTTPException(status_code=400, detail="Canary not in monitoring state")

    run["status"] = CanaryStatus.PROMOTED
    run["promoted_at"] = _utcnow()

    audit = AuditLog(
        user_id=current_user.id,
        action="canary.promoted",
        target_type="canary_run",
        target_id=str(run_id),
        details={"policy_id": run["policy_id"]},
    )
    db.add(audit)
    await db.commit()

    return {"status": "promoted", "run_id": run_id}


@router.post("/runs/{run_id}/rollback")
async def rollback_canary(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Manually rollback a canary."""
    if run_id not in _canary_runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = _canary_runs[run_id]
    if run["status"] in {CanaryStatus.PROMOTED, CanaryStatus.ROLLED_BACK}:
        raise HTTPException(status_code=400, detail="Canary already finalized")

    run["status"] = CanaryStatus.ROLLED_BACK
    run["completed_at"] = _utcnow()
    run["failure_reason"] = "Manual rollback"

    audit = AuditLog(
        user_id=current_user.id,
        action="canary.rolled_back",
        target_type="canary_run",
        target_id=str(run_id),
        details={"policy_id": run["policy_id"]},
    )
    db.add(audit)
    await db.commit()

    return {"status": "rolled_back", "run_id": run_id}
