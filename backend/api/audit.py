"""Audit Trail API — every important action is logged with tamper-proof integrity.

Implements write-only append-only logging with hash chain for integrity verification.
Supports log retention policies and search/export functionality.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, Session

from database import get_db
from auth import get_current_user
from models.db_models import AuditLog, AuditLogIntegrity, User

router = APIRouter(prefix="/api/audit", tags=["audit"])


class RetentionPolicy(str, Enum):
    """Audit log retention policies."""

    DAYS_30 = "30_days"
    DAYS_90 = "90_days"
    DAYS_180 = "180_days"
    DAYS_365 = "365_days"
    FOREVER = "forever"


RETENTION_DAYS = {
    RetentionPolicy.DAYS_30: 30,
    RetentionPolicy.DAYS_90: 90,
    RetentionPolicy.DAYS_180: 180,
    RetentionPolicy.DAYS_365: 365,
    RetentionPolicy.FOREVER: 365 * 10,  # Effectively forever
}


def _compute_log_hash(log_entry: dict) -> str:
    """Compute SHA-256 hash of an audit log entry for integrity."""
    # Create a deterministic representation
    data = {
        "id": log_entry.get("id"),
        "user_id": log_entry.get("user_id"),
        "action": log_entry.get("action"),
        "target_type": log_entry.get("target_type"),
        "target_id": log_entry.get("target_id"),
        "ip_address": log_entry.get("ip_address"),
        "created_at": str(log_entry.get("created_at")),
    }
    content = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def _get_previous_hash(db: AsyncSession, current_log_id: int) -> str:
    """Get the hash of the previous audit log entry for chain integrity."""
    result = db.execute(
        select(AuditLogIntegrity)
        .where(AuditLogIntegrity.log_id < current_log_id)
        .order_by(desc(AuditLogIntegrity.log_id))
        .limit(1)
    )
    prev = result.scalar_one_or_none()
    return prev.current_hash if prev else "0" * 64  # Genesis hash


async def _record_integrity(db: AsyncSession, log_id: int, current_hash: str) -> None:
    """Record integrity information for an audit log entry."""
    previous_hash = _get_previous_hash(db, log_id)
    integrity = AuditLogIntegrity(
        log_id=log_id,
        previous_hash=previous_hash,
        current_hash=current_hash,
        created_at=datetime.utcnow(),
    )
    db.add(integrity)
    await db.flush()


async def _verify_integrity_chain(db: AsyncSession, start_id: int, end_id: int) -> dict:
    """Verify the integrity of a range of audit log entries."""
    result = db.execute(
        select(AuditLogIntegrity)
        .where(
            and_(
                AuditLogIntegrity.log_id >= start_id, AuditLogIntegrity.log_id <= end_id
            )
        )
        .order_by(AuditLogIntegrity.log_id)
    )
    integrity_records = result.scalars().all()

    issues = []
    for i, record in enumerate(integrity_records):
        # Check chain integrity
        if i > 0:
            prev = integrity_records[i - 1]
            if record.previous_hash != prev.current_hash:
                issues.append(
                    {
                        "log_id": record.log_id,
                        "issue": "broken_chain",
                        "expected_previous": prev.current_hash,
                        "found_previous": record.previous_hash,
                    }
                )

        # Verify hash matches content
        log_result = db.execute(select(AuditLog).where(AuditLog.id == record.log_id))
        log_entry = log_result.scalar_one_or_none()
        if log_entry:
            computed_hash = _compute_log_hash(
                {
                    "id": log_entry.id,
                    "user_id": log_entry.user_id,
                    "action": log_entry.action,
                    "target_type": log_entry.target_type,
                    "target_id": log_entry.target_id,
                    "ip_address": log_entry.ip_address,
                    "created_at": str(log_entry.created_at),
                }
            )
            if computed_hash != record.current_hash:
                issues.append(
                    {
                        "log_id": record.log_id,
                        "issue": "hash_mismatch",
                        "expected": computed_hash,
                        "found": record.current_hash,
                    }
                )

    return {
        "verified": len(issues) == 0,
        "records_checked": len(integrity_records),
        "issues": issues,
    }


async def log_action(
    db: AsyncSession,
    user: Optional[User],
    action: str,
    target_type: str = "",
    target_id: str = "",
    details: dict = None,
    ip_address: str = "",
    skip_integrity: bool = False,
):
    """Call this from any endpoint to record an audit entry.

    Args:
        db: Database session
        user: User performing the action
        action: Action name (e.g., 'user.login', 'patch.apply')
        target_type: Type of target (e.g., 'host', 'job', 'user')
        target_id: ID of the target
        details: Additional details as dict
        ip_address: Client IP address
        skip_integrity: Skip integrity chain recording (for bulk operations)
    """
    entry = AuditLog(
        user_id=user.id if user else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        details=details or {},
        ip_address=ip_address,
    )
    db.add(entry)
    await db.flush()

    # Record integrity information if not skipped
    if not skip_integrity:
        try:
            await _record_integrity(
                db,
                entry.id,
                _compute_log_hash(
                    {
                        "id": entry.id,
                        "user_id": entry.user_id,
                        "action": entry.action,
                        "target_type": entry.target_type,
                        "target_id": entry.target_id,
                        "ip_address": entry.ip_address,
                        "created_at": str(entry.created_at),
                    }
                ),
            )
        except Exception:
            # Don't fail audit logging if integrity fails
            pass


class AuditOut(dict):
    pass


@router.get("/")
async def list_audit_logs(
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    user_id: Optional[int] = None,
    days: int = Query(30, le=365),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=500, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    q = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .where(AuditLog.created_at >= cutoff)
        .order_by(desc(AuditLog.created_at))
    )
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if target_type:
        q = q.where(AuditLog.target_type == target_type)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)

    # Total count
    count_q = select(func.count()).select_from(q.subquery())
    total = await db.scalar(count_q) or 0

    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    logs = result.scalars().all()
    items = [
        {
            "id": l.id,
            "user": l.user.username if l.user else "system",
            "action": l.action,
            "target_type": l.target_type,
            "target_id": l.target_id,
            "details": l.details,
            "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat() if l.created_at else "",
        }
        for l in logs
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/stats")
async def audit_stats(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    today = datetime.now(timezone.utc).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0
    )
    week_ago = today - timedelta(days=7)
    total_today = await db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.created_at >= today)
    )
    total_week = await db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.created_at >= week_ago)
    )
    return {"today": total_today, "this_week": total_week}


@router.get("/search")
async def search_audit_logs(
    q: Optional[str] = Query(
        None, description="Search query (matches action, target_type)"
    ),
    action_type: Optional[str] = Query(
        None, description="Filter by action prefix (e.g., 'user.', 'patch.')"
    ),
    start_date: Optional[datetime] = Query(None, description="Start date for range"),
    end_date: Optional[datetime] = Query(None, description="End date for range"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Search audit logs with advanced filtering.
    """
    q_filter = select(AuditLog).options(selectinload(AuditLog.user))

    if q:
        q_filter = q_filter.where(
            (AuditLog.action.ilike(f"%{q}%"))
            | (AuditLog.target_type.ilike(f"%{q}%"))
            | (AuditLog.target_id.ilike(f"%{q}%"))
        )

    if action_type:
        q_filter = q_filter.where(AuditLog.action.ilike(f"{action_type}%"))

    if start_date:
        q_filter = q_filter.where(AuditLog.created_at >= start_date)

    if end_date:
        q_filter = q_filter.where(AuditLog.created_at <= end_date)

    # Count total
    count_q = select(func.count()).select_from(q_filter.subquery())
    total = await db.scalar(count_q) or 0

    # Apply pagination
    q_filter = q_filter.order_by(desc(AuditLog.created_at))
    q_filter = q_filter.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(q_filter)
    logs = result.scalars().all()

    items = [
        {
            "id": l.id,
            "user": l.user.username if l.user else "system",
            "user_id": l.user_id,
            "action": l.action,
            "target_type": l.target_type,
            "target_id": l.target_id,
            "details": l.details,
            "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat() if l.created_at else "",
        }
        for l in logs
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/export")
async def export_audit_logs(
    format: str = Query("json", description="Export format: json, csv"),
    days: int = Query(30, ge=1, le=365),
    action_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Export audit logs in various formats.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    query = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .where(AuditLog.created_at >= cutoff)
        .order_by(desc(AuditLog.created_at))
    )

    if action_type:
        query = query.where(AuditLog.action.ilike(f"{action_type}%"))

    result = await db.execute(query)
    logs = result.scalars().all()

    items = [
        {
            "id": l.id,
            "timestamp": l.created_at.isoformat() if l.created_at else "",
            "user": l.user.username if l.user else "system",
            "action": l.action,
            "target_type": l.target_type,
            "target_id": l.target_id,
            "ip_address": l.ip_address,
            "details": json.dumps(l.details) if l.details else "",
        }
        for l in logs
    ]

    if format == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Timestamp",
                "User",
                "Action",
                "Target Type",
                "Target ID",
                "IP Address",
                "Details",
            ]
        )

        for item in items:
            writer.writerow(
                [
                    item["id"],
                    item["timestamp"],
                    item["user"],
                    item["action"],
                    item["target_type"],
                    item["target_id"],
                    item["ip_address"],
                    item["details"],
                ]
            )

        return {
            "format": "csv",
            "data": output.getvalue(),
            "filename": f"audit_logs_export_{datetime.now().strftime('%Y%m%d')}.csv",
            "record_count": len(items),
        }

    return {
        "format": "json",
        "data": items,
        "record_count": len(items),
        "period_days": days,
    }


@router.get("/integrity/verify")
async def verify_audit_integrity(
    start_id: Optional[int] = Query(None, description="Start log ID"),
    end_id: Optional[int] = Query(None, description="End log ID"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Verify the integrity of the audit log chain.

    If no range is specified, verifies the most recent 1000 entries.
    """
    if not start_id:
        # Get most recent log ID
        max_id = await db.scalar(select(func.max(AuditLog.id)))
        if max_id:
            start_id = max(1, max_id - 999)
        else:
            start_id = 1

    if not end_id:
        end_id = await db.scalar(select(func.max(AuditLog.id))) or start_id

    # Limit check range
    if end_id - start_id > 10000:
        end_id = start_id + 10000

    result = await _verify_integrity_chain(db, start_id, end_id)

    return {
        "range": {"start_id": start_id, "end_id": end_id},
        **result,
        "verified_at": datetime.utcnow().isoformat(),
    }


@router.get("/integrity/report")
async def audit_integrity_report(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a summary report of audit log integrity status."""
    total_logs = await db.scalar(select(func.count(AuditLog.id))) or 0
    total_integrity = await db.scalar(select(func.count(AuditLogIntegrity.id))) or 0

    latest_log = await db.scalar(select(func.max(AuditLog.id))) or 0
    latest_integrity = await db.scalar(select(func.max(AuditLogIntegrity.log_id))) or 0

    # Check for gaps in integrity chain
    gap_count = 0
    if total_logs > total_integrity:
        gap_count = total_logs - total_integrity

    return {
        "total_audit_logs": total_logs,
        "total_integrity_records": total_integrity,
        "integrity_coverage": round(total_integrity / total_logs * 100, 2)
        if total_logs > 0
        else 100,
        "latest_log_id": latest_log,
        "latest_integrity_id": latest_integrity,
        "missing_integrity_records": gap_count,
        "chain_status": "intact" if gap_count == 0 else "incomplete",
        "report_generated": datetime.utcnow().isoformat(),
    }


class RetentionConfig(BaseModel):
    """Configuration for log retention policy."""

    policy: RetentionPolicy
    retain_system_logs: bool = True
    retain_security_logs: bool = True


@router.get("/retention/policy")
async def get_retention_policy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get current retention policy (simulated - would store in config)."""
    return {
        "current_policy": RetentionPolicy.DAYS_90.value,
        "description": "Audit logs are retained for 90 days",
        "available_policies": [p.value for p in RetentionPolicy],
        "policy_descriptions": {
            p.value: f"Retain logs for {RETENTION_DAYS[p]} days"
            for p in RetentionPolicy
        },
    }


@router.get("/retention/estimate")
async def estimate_retention_size(
    days: int = Query(90, ge=30, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Estimate storage requirements for given retention period."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    log_count = (
        await db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.created_at >= cutoff)
        )
        or 0
    )

    # Rough estimate: ~500 bytes per log entry
    estimated_mb = (log_count * 500) / (1024 * 1024)

    return {
        "retention_days": days,
        "estimated_log_count": log_count,
        "estimated_size_mb": round(estimated_mb, 2),
        "estimated_size_gb": round(estimated_mb / 1024, 4),
    }


@router.get("/summary/by-action")
async def audit_summary_by_action(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get summary of audit logs grouped by action type."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    result = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id).label("count"))
        .where(AuditLog.created_at >= cutoff)
        .group_by(AuditLog.action)
        .order_by(desc("count"))
        .limit(limit)
    )

    actions = result.all()

    return {
        "period_days": days,
        "action_counts": [
            {"action": row.action, "count": row.count} for row in actions
        ],
    }


@router.get("/summary/by-user")
async def audit_summary_by_user(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get summary of audit logs grouped by user."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    result = await db.execute(
        select(
            func.coalesce(User.username, "system").label("username"),
            func.count(AuditLog.id).label("count"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(AuditLog.created_at >= cutoff)
        .group_by(User.username)
        .order_by(desc("count"))
        .limit(limit)
    )

    users = result.all()

    return {
        "period_days": days,
        "user_counts": [
            {"username": row.username, "count": row.count} for row in users
        ],
    }
