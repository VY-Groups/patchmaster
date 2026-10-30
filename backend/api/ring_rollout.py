import asyncio
import math
from datetime import datetime

def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.ops_queue import enqueue_operation
from auth import require_role
from database import async_session, get_db
from evidence import create_bundle
from gates.evaluator import evaluate_gates, decide, parse_gates
from gates.model import GateStatus
from models.db_models import (
    AuditLog,
    Host,
    HostGroup,
    JobStatus,
    MaintenanceWindow,
    PatchAction,
    PatchJob,
    RingRolloutPolicy,
    RingRolloutRun,
    RingRolloutStatus,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/ring-rollout", tags=["ring-rollout"])


class RingRolloutPolicyCreate(BaseModel):
    name: str
    description: str = ""
    target_os_family: str = "linux"
    is_enabled: bool = True
    rings: list[dict[str, Any]] = []
    guardrails: dict[str, Any] = {}
    rollout_config: dict[str, Any] = {}


class RingRolloutPolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_os_family: str | None = None
    is_enabled: bool | None = None
    rings: list[dict[str, Any]] | None = None
    guardrails: dict[str, Any] | None = None
    rollout_config: dict[str, Any] | None = None


class RingRolloutLaunchRequest(BaseModel):
    action: str = "upgrade"
    dry_run: bool = False
    packages: list[str] = []
    hold_packages: list[str] = []


class RingApprovalDecisionRequest(BaseModel):
    note: str = ""


class RingRolloutPolicyOut(BaseModel):
    id: int
    name: str
    description: str
    target_os_family: str
    is_enabled: bool
    rings: list[dict[str, Any]]
    guardrails: dict[str, Any]
    rollout_config: dict[str, Any]
    created_by: str
    created_at: datetime
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class RingRolloutRunOut(BaseModel):
    id: int
    policy_id: int
    status: str
    action: str
    dry_run: bool
    requested_by: str
    request_payload: dict[str, Any]
    summary: dict[str, Any]
    queue_job_id: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


def _policy_default_rings() -> list[dict[str, Any]]:
    return [
        {"name": "canary", "batch_percent": 5, "wait_seconds": 60},
        {"name": "pilot", "batch_percent": 20, "wait_seconds": 120},
        {"name": "broad", "batch_percent": 100, "wait_seconds": 0},
    ]


def _serialize_run(run: RingRolloutRun) -> RingRolloutRunOut:
    return RingRolloutRunOut(
        id=run.id,
        policy_id=run.policy_id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        action=run.action.value if hasattr(run.action, "value") else str(run.action),
        dry_run=bool(run.dry_run),
        requested_by=run.requested_by or "",
        request_payload=run.request_payload or {},
        summary=run.summary or {},
        queue_job_id=run.queue_job_id or "",
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _parse_action(value: str) -> PatchAction:
    try:
        return PatchAction((value or "upgrade").strip().lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported rollout action")


def _normalize_percent(value: Any) -> int:
    try:
        num = int(value)
    except Exception:
        return 100
    return min(max(num, 1), 100)


async def _audit_rollout_event(
    session: AsyncSession,
    user: User | None,
    action: str,
    target_type: str,
    target_id: str,
    details: dict[str, Any],
):
    log = AuditLog(
        user_id=getattr(user, "id", None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=None,
    )
    session.add(log)
    await session.flush()


def _is_within_window(now_utc: datetime, day_of_week: list[int], start_hour: int, end_hour: int) -> bool:
    dow = now_utc.weekday()
    hour = now_utc.hour
    days = list(day_of_week or [])
    if days and dow not in days:
        return False
    start = max(min(int(start_hour or 0), 23), 0)
    end = max(min(int(end_hour or 0), 24), 0)
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _health_gate_for_host(host: Host, guardrails: dict[str, Any]) -> tuple[bool, list[str]]:
    health = dict((guardrails or {}).get("health") or {})
    reasons: list[str] = []
    if health.get("require_online", True) and not bool(host.is_online):
        reasons.append("host_offline")
    min_compliance = health.get("min_compliance_score")
    if min_compliance is not None:
        try:
            threshold = float(min_compliance)
            if float(host.compliance_score or 0.0) < threshold:
                reasons.append(f"compliance_below_{threshold}")
        except Exception:
            pass
    max_cve = health.get("max_cve_count")
    if max_cve is not None:
        try:
            threshold = int(max_cve)
            if int(host.cve_count or 0) > threshold:
                reasons.append(f"cve_above_{threshold}")
        except Exception:
            pass
    return (len(reasons) == 0), reasons


async def _maintenance_gate_for_hosts(session, hosts: list, guardrails: dict[str, Any], windows=None) -> tuple[list, dict[str, Any]]:
    maintenance = dict((guardrails or {}).get("maintenance") or {})
    if not maintenance.get("require_window", False):
        return hosts, {"enabled": False, "filtered": 0}
    if windows is None:
        windows = (
            await session.execute(
                select(MaintenanceWindow).where(
                    MaintenanceWindow.is_active == True,
                    MaintenanceWindow.block_outside == True,
                )
            )
        ).scalars().all()
    if not windows:
        return [], {"enabled": True, "filtered": len(hosts), "reason": "no_active_blocking_windows"}
    now_utc = _utcnow()
    allowed: list[Host] = []
    blocked = 0
    for host in hosts:
        host_group_ids = {g.id for g in (host.groups or [])}
        host_allowed = False
        applicable_blocking_window_found = False
        for window in windows:
            applies_hosts = set(window.applies_to_hosts or [])
            applies_groups = set(window.applies_to_groups or [])
            applies = (not applies_hosts and not applies_groups) or (host.id in applies_hosts) or bool(host_group_ids.intersection(applies_groups))
            if not applies:
                continue
            applicable_blocking_window_found = True
            if _is_within_window(now_utc, window.day_of_week or [], int(window.start_hour or 0), int(window.end_hour or 0)):
                host_allowed = True
                break
        if host_allowed:
            allowed.append(host)
        elif applicable_blocking_window_found:
            blocked += 1
        else:
            allowed.append(host)
    return allowed, {"enabled": True, "filtered": blocked}


async def _rollback_threshold_violation(session: AsyncSession, previous_ring: dict[str, Any], guardrails: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    rollback = dict((guardrails or {}).get("rollback") or {})
    max_failed_percent = rollback.get("max_failed_percent")
    if max_failed_percent is None:
        return False, {"enabled": False}
    try:
        threshold = float(max_failed_percent)
    except Exception:
        return False, {"enabled": False}
    job_ids = list(previous_ring.get("job_ids") or [])
    if not job_ids:
        return False, {"enabled": True, "threshold": threshold, "failed_percent": 0.0, "job_count": 0}
    rows = (await session.execute(select(PatchJob).where(PatchJob.id.in_(job_ids)))).scalars().all()
    fail_statuses = {JobStatus.failed, JobStatus.cancelled, JobStatus.aborted, JobStatus.rolled_back}
    failed = sum(1 for row in rows if row.status in fail_statuses)
    total = len(rows)
    failed_percent = (failed / total * 100.0) if total > 0 else 0.0
    return failed_percent > threshold, {
        "enabled": True,
        "threshold": threshold,
        "failed_percent": round(failed_percent, 2),
        "failed_count": failed,
        "job_count": total,
    }


async def _resolve_ring_hosts(session: AsyncSession, policy: RingRolloutPolicy, ring: dict[str, Any]) -> list[Host]:
    selector = ring.get("selector") if isinstance(ring, dict) else {}
    selector = selector if isinstance(selector, dict) else {}
    group_ids = selector.get("group_ids") or []
    host_ids = selector.get("host_ids") or []

    stmt = select(Host).where(Host.is_online == True)
    family = str(policy.target_os_family or "").strip().lower()
    if host_ids:
        ids = [int(v) for v in host_ids if str(v).isdigit()]
        if ids:
            stmt = stmt.where(Host.id.in_(ids))
    if group_ids:
        gids = [int(v) for v in group_ids if str(v).isdigit()]
        if gids:
            stmt = stmt.where(Host.groups.any(HostGroup.id.in_(gids)))
    rows = (await session.execute(stmt.order_by(Host.id.asc()))).scalars().all()
    if family and family != "any":
        try:
            from api.register_v2 import _detect_os_family
        except Exception:
            _detect_os_family = None
        if _detect_os_family is not None:
            rows = [r for r in rows if _detect_os_family(getattr(r, "os", "") or "") == family]
    return list(rows)


async def _execute_rollout_run(run_id: int) -> dict[str, Any]:
    async with async_session() as session:
        run = await session.get(RingRolloutRun, run_id)
        if not run:
            return {"status": "missing_run", "run_id": run_id}
        policy = await session.get(RingRolloutPolicy, run.policy_id)
        if not policy:
            run.status = RingRolloutStatus.failed
            run.summary = {"error": "Policy not found"}
            run.completed_at = _utcnow()
            await session.commit()
            return {"status": "missing_policy", "run_id": run_id}

        rings = list(policy.rings or _policy_default_rings())
        guardrails = dict(policy.guardrails or {})
        rollout_config = dict(policy.rollout_config or {})
        restore_drill_cfg = rollout_config.get("restore_drill") if isinstance(rollout_config.get("restore_drill"), dict) else {}
        gates_cfg = rollout_config.get("gates") if isinstance(rollout_config.get("gates"), dict) else {}
        on_gate_failure = str((gates_cfg or {}).get("on_failure") or rollout_config.get("on_gate_failure") or "hold")
        approval_cfg = dict(rollout_config.get("approval") or {})
        require_approval = bool(approval_cfg.get("required", False))
        per_ring = bool(approval_cfg.get("per_ring", True))

        if run.status != RingRolloutStatus.running:
            run.status = RingRolloutStatus.running
        if run.started_at is None:
            run.started_at = _utcnow()
        summary = dict(run.summary or {})
        summary.setdefault("rings_total", len(rings))
        summary.setdefault("rings", [])
        summary.setdefault("jobs_created", 0)
        summary.setdefault("guardrails", guardrails)
        summary.setdefault("gate_decisions", [])
        summary.setdefault("gate_results", [])
        summary.setdefault("restore_drill", restore_drill_cfg or {})
        summary.setdefault("approved_rings", [])
        summary.setdefault("approval_decisions", [])
        summary.setdefault("next_ring_index", 0)
        run.summary = summary
        await session.commit()

        total_jobs = int((run.summary or {}).get("jobs_created") or 0)
        try:
            for idx, ring in enumerate(rings):
                current_summary = dict(run.summary or {})
                if idx < int(current_summary.get("next_ring_index", 0)):
                    continue
                ring_name = str((ring or {}).get("name", f"ring-{idx+1}"))
                batch_percent = _normalize_percent((ring or {}).get("batch_percent", 100))
                wait_seconds = max(int((ring or {}).get("wait_seconds", 0) or 0), 0)
                rings_data = list(current_summary.get("rings") or [])
                gate_decisions = list(current_summary.get("gate_decisions") or [])
                approved_rings = list(current_summary.get("approved_rings") or [])

                if require_approval and (per_ring or idx == 0) and idx not in approved_rings:
                    run.status = RingRolloutStatus.pending
                    current_summary["awaiting_approval"] = {
                        "ring_index": idx,
                        "ring_name": ring_name,
                        "required": True,
                    }
                    gate_decisions.append(
                        {
                            "ring_index": idx,
                            "ring_name": ring_name,
                            "gate": "approval",
                            "decision": "blocked_waiting_approval",
                            "at": _utcnow().isoformat() + "Z",
                        }
                    )
                    current_summary["gate_decisions"] = gate_decisions
                    run.summary = current_summary
                    await session.commit()
                    return {"status": "awaiting_approval", "run_id": run_id, "ring_index": idx}

                if idx > 0 and rings_data:
                    violated, rollback_state = await _rollback_threshold_violation(session, rings_data[-1], guardrails)
                    if violated:
                        run.status = RingRolloutStatus.failed
                        run.completed_at = _utcnow()
                        current_summary["rollback_gate"] = rollback_state
                        gate_decisions.append(
                            {
                                "ring_index": idx,
                                "ring_name": ring_name,
                                "gate": "rollback_threshold",
                                "decision": "blocked",
                                "state": rollback_state,
                                "at": _utcnow().isoformat() + "Z",
                            }
                        )
                        current_summary["gate_decisions"] = gate_decisions
                        current_summary["error"] = "rollback_threshold_exceeded"
                        run.summary = current_summary
                        await session.commit()
                        return {"status": "failed", "run_id": run_id, "error": "rollback_threshold_exceeded", "rollback_gate": rollback_state}
                    current_summary["rollback_gate"] = rollback_state
                    gate_decisions.append(
                        {
                            "ring_index": idx,
                            "ring_name": ring_name,
                            "gate": "rollback_threshold",
                            "decision": "allowed",
                            "state": rollback_state,
                            "at": _utcnow().isoformat() + "Z",
                        }
                    )

                base_hosts = await _resolve_ring_hosts(session, policy, ring or {})

                # S1-1/S1-2: configured gates (pre-phase) for this ring.
                gate_results_list = list(current_summary.get("gate_results") or [])
                pre_gates = parse_gates(rollout_config, phase="pre", ring=ring)
                if pre_gates:
                    pre_ctx = {
                        "hosts": base_hosts,
                        "session": session,
                        "guardrails": guardrails,
                        "policy": policy,
                        "ring": ring or {},
                        "run_summary": current_summary,
                        "maintenance_windows": None,
                    }
                    pre_results = await evaluate_gates(pre_gates, pre_ctx)
                    pre_decision = decide(pre_results, pre_gates, on_failure=on_gate_failure)
                    gate_results_list.append(
                        {
                            "ring_index": idx,
                            "ring_name": ring_name,
                            "phase": "pre",
                            "results": [r.to_dict() for r in pre_results],
                            "decision": pre_decision.outcome,
                        }
                    )
                    gate_decisions.append(
                        {
                            "ring_index": idx,
                            "ring_name": ring_name,
                            "gate": "configured_gates",
                            "phase": "pre",
                            "decision": pre_decision.outcome,
                            "failed_required": pre_decision.failed_required,
                            "at": _utcnow().isoformat() + "Z",
                        }
                    )
                    current_summary["gate_results"] = gate_results_list
                    current_summary["gate_decisions"] = gate_decisions
                    run.summary = current_summary
                    await session.commit()
                    if pre_decision.outcome != "promote":
                        if pre_decision.outcome == "rollback":
                            run.status = RingRolloutStatus.failed
                        else:
                            run.status = RingRolloutStatus.held
                        run.completed_at = _utcnow()
                        current_summary["error"] = "gate_failed_pre"
                        run.summary = current_summary
                        await session.commit()
                        return {"status": pre_decision.outcome, "run_id": run_id,
                                "error": "gate_failed_pre", "failed": pre_decision.failed_required}

                healthy_hosts: list[Host] = []
                health_blocked = 0
                health_reason_counts: dict[str, int] = {}
                for host in base_hosts:
                    allowed, reasons = _health_gate_for_host(host, guardrails)
                    if allowed:
                        healthy_hosts.append(host)
                    else:
                        health_blocked += 1
                        for reason in reasons:
                            health_reason_counts[reason] = health_reason_counts.get(reason, 0) + 1
                hosts_after_health = healthy_hosts
                hosts_after_maintenance, maintenance_state = await _maintenance_gate_for_hosts(session, hosts_after_health, guardrails)
                hosts = hosts_after_maintenance
                gate_decisions.append(
                    {
                        "ring_index": idx,
                        "ring_name": ring_name,
                        "gate": "health",
                        "decision": "allowed" if len(hosts_after_health) > 0 else "blocked",
                        "health_block_reasons": health_reason_counts,
                        "at": _utcnow().isoformat() + "Z",
                    }
                )
                gate_decisions.append(
                    {
                        "ring_index": idx,
                        "ring_name": ring_name,
                        "gate": "maintenance_window",
                        "decision": "allowed" if len(hosts) > 0 else "blocked",
                        "state": maintenance_state,
                        "at": _utcnow().isoformat() + "Z",
                    }
                )
                target_count = math.ceil(len(hosts) * (batch_percent / 100.0)) if hosts else 0
                if hosts and target_count <= 0:
                    target_count = 1
                selected_hosts = hosts[:target_count]
                ring_jobs = []
                if not run.dry_run:
                    for host in selected_hosts:
                        job = PatchJob(
                            host_id=host.id,
                            action=run.action,
                            status=JobStatus.pending,
                            packages=list((run.request_payload or {}).get("packages") or []),
                            hold_packages=list((run.request_payload or {}).get("hold_packages") or []),
                            dry_run=False,
                            auto_snapshot=True,
                            auto_rollback=True,
                            initiated_by=run.requested_by or "system",
                        )
                        session.add(job)
                        await session.flush()
                        ring_jobs.append(job.id)
                total_jobs += len(ring_jobs)

                # S1-1/S1-2: configured gates (post-phase) for this ring.
                post_gates = parse_gates(rollout_config, phase="post", ring=ring)
                if post_gates:
                    post_ctx = {
                        "hosts": selected_hosts if selected_hosts else hosts,
                        "session": session,
                        "guardrails": guardrails,
                        "policy": policy,
                        "ring": ring or {},
                        "run_summary": current_summary,
                    }
                    post_results = await evaluate_gates(post_gates, post_ctx)
                    post_decision = decide(post_results, post_gates, on_failure=on_gate_failure)
                    gate_results_list.append(
                        {
                            "ring_index": idx,
                            "ring_name": ring_name,
                            "phase": "post",
                            "results": [r.to_dict() for r in post_results],
                            "decision": post_decision.outcome,
                        }
                    )
                    gate_decisions.append(
                        {
                            "ring_index": idx,
                            "ring_name": ring_name,
                            "gate": "configured_gates",
                            "phase": "post",
                            "decision": post_decision.outcome,
                            "failed_required": post_decision.failed_required,
                            "at": _utcnow().isoformat() + "Z",
                        }
                    )
                    if post_decision.outcome != "promote":
                        current_summary["gate_results"] = gate_results_list
                        current_summary["gate_decisions"] = gate_decisions
                        current_summary["error"] = "gate_failed_post"
                        run.summary = current_summary
                        await session.commit()
                        if post_decision.outcome == "rollback":
                            run.status = RingRolloutStatus.failed
                        else:
                            run.status = RingRolloutStatus.held
                        run.completed_at = _utcnow()
                        run.summary = current_summary
                        await session.commit()
                        return {"status": post_decision.outcome, "run_id": run_id,
                                "error": "gate_failed_post", "failed": post_decision.failed_required}

                rings_data.append(
                    {
                        "name": ring_name,
                        "batch_percent": batch_percent,
                        "wait_seconds": wait_seconds,
                        "hosts_considered": len(base_hosts),
                        "hosts_after_health_gate": len(hosts_after_health),
                        "hosts_health_blocked": health_blocked,
                        "health_block_reasons": health_reason_counts,
                        "hosts_after_maintenance_gate": len(hosts),
                        "maintenance_gate": maintenance_state,
                        "hosts_selected": len(selected_hosts),
                        "job_ids": ring_jobs,
                    }
                )
                current_summary["rings"] = rings_data
                current_summary["jobs_created"] = total_jobs
                current_summary["next_ring_index"] = idx + 1
                current_summary["gate_decisions"] = gate_decisions
                current_summary["gate_results"] = gate_results_list
                current_summary.pop("awaiting_approval", None)
                run.summary = current_summary
                await session.commit()
                if wait_seconds > 0 and idx < len(rings) - 1:
                    await asyncio.sleep(wait_seconds)

            run.status = RingRolloutStatus.success
            run.completed_at = _utcnow()
            final_summary = dict(run.summary or {})
            final_summary["completed"] = True
            final_summary["jobs_created"] = total_jobs
            final_summary["next_ring_index"] = len(rings)
            final_summary.pop("awaiting_approval", None)
            run.summary = final_summary
            await session.commit()
            return {"status": "success", "run_id": run_id, "jobs_created": total_jobs}
        except Exception as exc:
            run.status = RingRolloutStatus.failed
            run.completed_at = _utcnow()
            failed_summary = dict(run.summary or {})
            failed_summary["error"] = str(exc)
            run.summary = failed_summary
            await session.commit()
            return {"status": "failed", "run_id": run_id, "error": str(exc)}


async def _enqueue_rollout_run_job(
    run: RingRolloutRun,
    request: Request,
    requested_by: str,
    op_note: str = "",
) -> dict[str, Any]:
    request_id = str(getattr(getattr(request, "state", object()), "request_id", "") or "")
    trace_token = str(getattr(getattr(request, "state", object()), "trace_token", "") or "")
    run_id = run.id

    async def _runner():
        return await _execute_rollout_run(run_id)

    queue_job = await enqueue_operation(
        op_type="ring_rollout.run",
        payload={"policy_id": run.policy_id, "run_id": run_id, "action": run.action.value if hasattr(run.action, "value") else str(run.action), "note": op_note},
        runner=_runner,
        requested_by=requested_by,
        request_id=request_id or None,
        trace_token=trace_token or None,
    )
    return queue_job


@router.get("/policies", response_model=list[RingRolloutPolicyOut])
async def list_rollout_policies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    rows = (await db.execute(select(RingRolloutPolicy).order_by(RingRolloutPolicy.name.asc()))).scalars().all()
    return rows


@router.post("/policies", response_model=RingRolloutPolicyOut)
async def create_rollout_policy(
    body: RingRolloutPolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Policy name is required")
    exists = (await db.execute(select(RingRolloutPolicy).where(RingRolloutPolicy.name == name))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Policy name already exists")
    policy = RingRolloutPolicy(
        name=name,
        description=body.description.strip(),
        target_os_family=(body.target_os_family or "linux").strip().lower(),
        is_enabled=bool(body.is_enabled),
        rings=list(body.rings or _policy_default_rings()),
        guardrails=body.guardrails or {},
        rollout_config=body.rollout_config or {},
        created_by=getattr(current_user, "username", "system"),
    )
    db.add(policy)
    await _audit_rollout_event(
        db,
        current_user,
        action="ring_rollout.policy_created",
        target_type="ring_rollout_policy",
        target_id="new",
        details={"name": name, "target_os_family": policy.target_os_family},
    )
    await db.commit()
    await db.refresh(policy)
    return policy


@router.put("/policies/{policy_id}", response_model=RingRolloutPolicyOut)
async def update_rollout_policy(
    policy_id: int,
    body: RingRolloutPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    policy = await db.get(RingRolloutPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Rollout policy not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Policy name cannot be empty")
        conflict = (await db.execute(select(RingRolloutPolicy).where(RingRolloutPolicy.name == name, RingRolloutPolicy.id != policy_id))).scalar_one_or_none()
        if conflict:
            raise HTTPException(status_code=409, detail="Policy name already exists")
        policy.name = name
    if body.description is not None:
        policy.description = body.description.strip()
    if body.target_os_family is not None:
        policy.target_os_family = body.target_os_family.strip().lower() or "linux"
    if body.is_enabled is not None:
        policy.is_enabled = bool(body.is_enabled)
    if body.rings is not None:
        policy.rings = list(body.rings)
    if body.guardrails is not None:
        policy.guardrails = body.guardrails
    if body.rollout_config is not None:
        policy.rollout_config = body.rollout_config
    policy.updated_at = _utcnow()
    db.add(policy)
    await _audit_rollout_event(
        db,
        current_user,
        action="ring_rollout.policy_updated",
        target_type="ring_rollout_policy",
        target_id=str(policy.id),
        details={"name": policy.name, "is_enabled": policy.is_enabled},
    )
    await db.commit()
    await db.refresh(policy)
    return policy


@router.delete("/policies/{policy_id}")
async def delete_rollout_policy(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    policy = await db.get(RingRolloutPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Rollout policy not found")
    await _audit_rollout_event(
        db,
        current_user,
        action="ring_rollout.policy_deleted",
        target_type="ring_rollout_policy",
        target_id=str(policy.id),
        details={"name": policy.name},
    )
    await db.delete(policy)
    await db.commit()
    return {"status": "ok", "message": "Rollout policy deleted"}


@router.get("/policies/{policy_id}/runs", response_model=list[RingRolloutRunOut])
async def list_policy_runs(
    policy_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    policy = await db.get(RingRolloutPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Rollout policy not found")
    rows = (
        await db.execute(
            select(RingRolloutRun)
            .where(RingRolloutRun.policy_id == policy_id)
            .order_by(desc(RingRolloutRun.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return [_serialize_run(row) for row in rows]


@router.get("/runs/{run_id}", response_model=RingRolloutRunOut)
async def get_rollout_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    run = await db.get(RingRolloutRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Rollout run not found")
    return _serialize_run(run)


@router.post("/policies/{policy_id}/launch")
async def launch_rollout(
    policy_id: int,
    body: RingRolloutLaunchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    policy = await db.get(RingRolloutPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Rollout policy not found")
    if not policy.is_enabled:
        raise HTTPException(status_code=409, detail="Rollout policy is disabled")
    action = _parse_action(body.action)
    run = RingRolloutRun(
        policy_id=policy.id,
        status=RingRolloutStatus.pending,
        action=action,
        dry_run=bool(body.dry_run),
        requested_by=getattr(current_user, "username", "system"),
        request_payload={
            "action": action.value,
            "dry_run": bool(body.dry_run),
            "packages": list(body.packages or []),
            "hold_packages": list(body.hold_packages or []),
        },
        summary={},
    )
    db.add(run)
    await db.flush()
    queue_job = await _enqueue_rollout_run_job(
        run=run,
        request=request,
        requested_by=getattr(current_user, "username", "system"),
        op_note="launch",
    )
    run.queue_job_id = str(queue_job.get("id", ""))
    db.add(run)
    await _audit_rollout_event(
        db,
        current_user,
        action="ring_rollout.run_launched",
        target_type="ring_rollout_run",
        target_id=str(run.id),
        details={"policy_id": policy.id, "action": action.value, "dry_run": bool(body.dry_run), "queue_job_id": run.queue_job_id},
    )
    await db.commit()
    await db.refresh(run)
    return {"status": "accepted", "run": _serialize_run(run), "job": queue_job}


@router.post("/runs/{run_id}/approve")
async def approve_rollout_checkpoint(
    run_id: int,
    body: RingApprovalDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    run = await db.get(RingRolloutRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Rollout run not found")
    summary = dict(run.summary or {})
    awaiting = dict(summary.get("awaiting_approval") or {})
    if not awaiting:
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")
    ring_index = int(awaiting.get("ring_index", 0))
    approved_rings = list(summary.get("approved_rings") or [])
    if ring_index not in approved_rings:
        approved_rings.append(ring_index)
    summary["approved_rings"] = approved_rings
    decisions = list(summary.get("approval_decisions") or [])
    decisions.append(
        {
            "ring_index": ring_index,
            "decision": "approved",
            "by": getattr(current_user, "username", "system"),
            "note": body.note.strip(),
            "at": _utcnow().isoformat() + "Z",
        }
    )
    summary["approval_decisions"] = decisions
    summary.pop("awaiting_approval", None)
    run.summary = summary
    run.status = RingRolloutStatus.pending
    db.add(run)
    queue_job = await _enqueue_rollout_run_job(
        run=run,
        request=request,
        requested_by=getattr(current_user, "username", "system"),
        op_note="approval_resume",
    )
    run.queue_job_id = str(queue_job.get("id", ""))
    db.add(run)
    await _audit_rollout_event(
        db,
        current_user,
        action="ring_rollout.run_approved",
        target_type="ring_rollout_run",
        target_id=str(run.id),
        details={"ring_index": ring_index, "note": body.note.strip(), "queue_job_id": run.queue_job_id},
    )
    try:
        await create_bundle(
            db,
            job_id=str(run.id),
            items=[{"step": "approval", "kind": "approval_granted",
                    "payload": {"ring_index": ring_index, "by": getattr(current_user, "username", "system"),
                                "note": body.note.strip()}}],
        )
    except Exception:
        pass
    await db.commit()
    await db.refresh(run)
    return {"status": "accepted", "run": _serialize_run(run), "job": queue_job}


@router.post("/runs/{run_id}/reject")
async def reject_rollout_checkpoint(
    run_id: int,
    body: RingApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    run = await db.get(RingRolloutRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Rollout run not found")
    summary = dict(run.summary or {})
    awaiting = dict(summary.get("awaiting_approval") or {})
    if not awaiting:
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")
    ring_index = int(awaiting.get("ring_index", 0))
    decisions = list(summary.get("approval_decisions") or [])
    decisions.append(
        {
            "ring_index": ring_index,
            "decision": "rejected",
            "by": getattr(current_user, "username", "system"),
            "note": body.note.strip(),
            "at": _utcnow().isoformat() + "Z",
        }
    )
    summary["approval_decisions"] = decisions
    summary["error"] = "approval_rejected"
    summary.pop("awaiting_approval", None)
    run.summary = summary
    run.status = RingRolloutStatus.canceled
    run.completed_at = _utcnow()
    db.add(run)
    await _audit_rollout_event(
        db,
        current_user,
        action="ring_rollout.run_rejected",
        target_type="ring_rollout_run",
        target_id=str(run.id),
        details={"ring_index": ring_index, "note": body.note.strip()},
    )
    await db.commit()
    await db.refresh(run)
    return {"status": "ok", "run": _serialize_run(run)}


@router.get("/policies/{policy_id}/audit")
async def list_rollout_policy_audit(
    policy_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator, UserRole.auditor)),
):
    policy = await db.get(RingRolloutPolicy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Rollout policy not found")
    run_ids = (
        await db.execute(
            select(RingRolloutRun.id).where(RingRolloutRun.policy_id == policy_id).order_by(desc(RingRolloutRun.created_at)).limit(1000)
        )
    ).scalars().all()
    audit_rows = (
        await db.execute(
            select(AuditLog)
            .where(
                or_(
                    (AuditLog.target_type == "ring_rollout_policy") & (AuditLog.target_id == str(policy_id)),
                    (AuditLog.target_type == "ring_rollout_run") & (AuditLog.target_id.in_([str(v) for v in run_ids] or ["-1"])),
                )
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "details": row.details or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in audit_rows
    ]
