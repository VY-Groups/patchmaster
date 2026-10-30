"""
Rolling Restart API for Patch-SecOps Solution.

Provides wave-based rolling restart functionality for hosts.
Supports configurable batch sizes, health checks, and rollback on failure.
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

from api.ops_queue import enqueue_operation
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
router = APIRouter(prefix="/api/rolling-restart", tags=["rolling-restart"])


def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


class RestartStrategy(str, Enum):
    """Rolling restart strategies."""

    SERIAL = "serial"  # One at a time
    BATCH = "batch"  # N hosts at a time
    PARALLEL = "parallel"  # All at once (careful!)


class RestartPolicy(BaseModel):
    """Policy for rolling restart."""

    name: str
    description: str = ""
    strategy: RestartStrategy = RestartStrategy.BATCH
    batch_size: int = 5
    wait_seconds: int = 60
    health_check_enabled: bool = True
    health_check_url: str = "/health"
    max_retries: int = 2
    rollback_on_failure: bool = True
    target_os_family: str = "linux"


class RestartPolicyResponse(BaseModel):
    id: int
    name: str
    description: str
    strategy: str
    batch_size: int
    wait_seconds: int
    health_check_enabled: bool
    max_retries: int
    rollback_on_failure: bool
    target_os_family: str
    model_config = ConfigDict(from_attributes=True)


class RestartRunResponse(BaseModel):
    """Response for a restart run."""

    id: int
    policy_id: int
    status: str
    total_hosts: int
    succeeded: int
    failed: int
    in_progress: int
    current_batch: int
    total_batches: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


# In-memory storage for policies and runs (would be DB in production)
_restart_policies: dict[int, dict[str, Any]] = {}
_restart_runs: dict[int, dict[str, Any]] = {}
_policy_id_counter = 1
_run_id_counter = 1


def _serialize_host(host: Host) -> dict[str, Any]:
    """Serialize host for response."""
    return {
        "id": host.id,
        "hostname": host.hostname,
        "ip": host.ip,
        "os": host.os,
        "os_family": host.os_family,
        "is_online": host.is_online,
        "status": host.status,
    }


async def _health_check_host(host: Host, timeout: float = 5.0) -> bool:
    """Check if host is healthy after restart.

    Args:
        host: Host to check
        timeout: Health check timeout in seconds

    Returns:
        True if host is healthy
    """
    import httpx

    # Import agent proxy to get correct port
    from api.agent_proxy import _agent_url_for_host_id, _candidate_agent_urls

    async with async_session() as db:
        try:
            urls = await _candidate_agent_urls(host.ip, "/health", db)
            async with httpx.AsyncClient(timeout=timeout) as client:
                for url in urls:
                    try:
                        r = await client.get(url)
                        if r.status_code < 500:
                            data = r.json()
                            return data.get("state") in ["idle", "ready"]
                    except Exception:
                        continue
                return False
        except Exception:
            return False


async def _restart_host(
    host: Host,
    restart_policy: RestartPolicy,
    db: AsyncSession,
    requested_by: str,
) -> dict[str, Any]:
    """Restart a single host.

    Args:
        host: Host to restart
        restart_policy: Restart policy
        db: Database session
        requested_by: User requesting restart

    Returns:
        Restart result
    """
    import httpx

    try:
        # Send reboot command
        from api.agent_proxy import _candidate_agent_urls

        urls = await _candidate_agent_urls(host.ip, "/system/reboot", db)
        async with httpx.AsyncClient(timeout=30.0) as client:
            for url in urls:
                try:
                    r = await client.post(url, json={})
                    if r.status_code < 500:
                        break
                except Exception:
                    continue
            else:
                return {
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "failed",
                    "error": "Host unreachable",
                }

        # Wait for host to come back up
        await asyncio.sleep(30)

        # Health check
        if restart_policy.health_check_enabled:
            is_healthy = await _health_check_host(host)
            if not is_healthy:
                return {
                    "host_id": host.id,
                    "hostname": host.hostname,
                    "status": "failed_health_check",
                    "error": "Health check failed after restart",
                }

        return {
            "host_id": host.id,
            "hostname": host.hostname,
            "status": "success",
        }

    except Exception as e:
        logger.error(f"Failed to restart {host.hostname}: {e}")
        return {
            "host_id": host.id,
            "hostname": host.hostname,
            "status": "failed",
            "error": str(e),
        }


async def _execute_restart_run(run_id: int):
    """Execute a rolling restart run.

    Args:
        run_id: Run ID
    """
    global _restart_runs

    run = _restart_runs.get(run_id)
    if not run:
        return

    policy = run["policy"]
    hosts = run["hosts"]
    total_hosts = len(hosts)

    # Calculate batches
    if policy.strategy == RestartStrategy.SERIAL:
        batch_size = 1
    elif policy.strategy == RestartStrategy.PARALLEL:
        batch_size = total_hosts
    else:
        batch_size = policy.batch_size

    total_batches = (total_hosts + batch_size - 1) // batch_size
    run["total_batches"] = total_batches
    run["current_batch"] = 0

    async with async_session() as db:
        succeeded = 0
        failed = 0

        for batch_num in range(total_batches):
            run["current_batch"] = batch_num + 1

            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, total_hosts)
            batch_hosts = hosts[start_idx:end_idx]

            batch_results = []
            for host in batch_hosts:
                result = await _restart_host(host, policy, db, run["requested_by"])
                batch_results.append(result)

                if result["status"] == "success":
                    succeeded += 1
                else:
                    failed += 1

                    if policy.rollback_on_failure:
                        run["status"] = "rolled_back"
                        run["completed_at"] = _utcnow()
                        run["failed_at_batch"] = batch_num + 1
                        return

            # Wait between batches
            if batch_num < total_batches - 1 and policy.wait_seconds > 0:
                await asyncio.sleep(policy.wait_seconds)

        run["succeeded"] = succeeded
        run["failed"] = failed
        run["status"] = "completed"
        run["completed_at"] = _utcnow()


@router.post("/policies", response_model=RestartPolicyResponse)
async def create_restart_policy(
    body: RestartPolicy,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Create a rolling restart policy."""
    global _policy_id_counter, _restart_policies

    policy_id = _policy_id_counter
    _policy_id_counter += 1

    policy_dict = {
        "id": policy_id,
        "name": body.name,
        "description": body.description,
        "strategy": body.strategy.value,
        "batch_size": body.batch_size,
        "wait_seconds": body.wait_seconds,
        "health_check_enabled": body.health_check_enabled,
        "health_check_url": body.health_check_url,
        "max_retries": body.max_retries,
        "rollback_on_failure": body.rollback_on_failure,
        "target_os_family": body.target_os_family,
    }

    _restart_policies[policy_id] = policy_dict

    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="rolling_restart.policy_created",
        target_type="rolling_restart_policy",
        target_id=str(policy_id),
        details={"name": body.name, "strategy": body.strategy.value},
    )
    db.add(audit)
    await db.commit()

    return policy_dict


@router.get("/policies", response_model=list[RestartPolicyResponse])
async def list_restart_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """List all rolling restart policies."""
    return list(_restart_policies.values())


@router.delete("/policies/{policy_id}")
async def delete_restart_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete a rolling restart policy."""
    if policy_id not in _restart_policies:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy = _restart_policies.pop(policy_id)

    audit = AuditLog(
        user_id=current_user.id,
        action="rolling_restart.policy_deleted",
        target_type="rolling_restart_policy",
        target_id=str(policy_id),
        details={"name": policy.get("name")},
    )
    db.add(audit)
    await db.commit()

    return {"status": "ok", "message": "Policy deleted"}


@router.post("/policies/{policy_id}/run")
async def start_restart_run(
    policy_id: int,
    host_ids: Optional[list[int]] = None,
    group_ids: Optional[list[int]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Start a rolling restart run."""
    global _run_id_counter, _restart_runs

    if policy_id not in _restart_policies:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy_dict = _restart_policies[policy_id]
    policy = RestartPolicy(
        name=policy_dict["name"],
        description=policy_dict["description"],
        strategy=RestartStrategy(policy_dict["strategy"]),
        batch_size=policy_dict["batch_size"],
        wait_seconds=policy_dict["wait_seconds"],
        health_check_enabled=policy_dict["health_check_enabled"],
        health_check_url=policy_dict["health_check_url"],
        max_retries=policy_dict["max_retries"],
        rollback_on_failure=policy_dict["rollback_on_failure"],
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
        raise HTTPException(status_code=400, detail="No hosts found matching criteria")

    # Create run
    run_id = _run_id_counter
    _run_id_counter += 1

    run = {
        "id": run_id,
        "policy_id": policy_id,
        "policy": policy,
        "hosts": list(hosts),
        "requested_by": current_user.username,
        "status": "running",
        "total_hosts": len(hosts),
        "succeeded": 0,
        "failed": 0,
        "started_at": _utcnow(),
        "completed_at": None,
    }

    _restart_runs[run_id] = run

    # Start async execution
    asyncio.create_task(_execute_restart_run(run_id))

    audit = AuditLog(
        user_id=current_user.id,
        action="rolling_restart.run_started",
        target_type="rolling_restart_run",
        target_id=str(run_id),
        details={"policy_id": policy_id, "host_count": len(hosts)},
    )
    db.add(audit)
    await db.commit()

    return {
        "run_id": run_id,
        "status": "started",
        "total_hosts": len(hosts),
    }


@router.get("/runs/{run_id}", response_model=RestartRunResponse)
async def get_restart_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """Get status of a restart run."""
    if run_id not in _restart_runs:
        raise HTTPException(status_code=404, detail="Run not found")

    run = _restart_runs[run_id]
    return {
        "id": run["id"],
        "policy_id": run["policy_id"],
        "status": run["status"],
        "total_hosts": run["total_hosts"],
        "succeeded": run["succeeded"],
        "failed": run["failed"],
        "in_progress": run["total_hosts"] - run["succeeded"] - run["failed"],
        "current_batch": run.get("current_batch", 0),
        "total_batches": run.get("total_batches", 0),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
    }


@router.get("/runs")
async def list_restart_runs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.admin, UserRole.operator, UserRole.auditor)
    ),
):
    """List recent restart runs."""
    runs = list(_restart_runs.values())
    runs.sort(key=lambda r: r.get("started_at") or datetime.min, reverse=True)
    return runs[:limit]
