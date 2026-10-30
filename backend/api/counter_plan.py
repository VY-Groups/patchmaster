"""Counter-plan endpoints (P1-P6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import get_current_user, require_role, User, UserRole
from policy_templates import list_templates

router = APIRouter(prefix="/api/counter-plan", tags=["counter-plan"])


@router.get("/policy-templates")
async def policy_templates():
    return list_templates()


@router.get("/auto-deploy-rules")
async def list_auto_deploy_rules(db: AsyncSession = Depends(get_db)):
    # table may not exist in older DBs; return empty on failure
    try:
        from sqlalchemy import text
        rows = (await db.execute(text("SELECT id, name, enabled FROM auto_deploy_rules"))).fetchall()
        return [{"id": r[0], "name": r[1], "enabled": r[2]} for r in rows]
    except Exception:
        return []


@router.get("/reports")
async def list_reports():
    # P5: 14 patch report types (names only; generation wired separately)
    return [
        "patch_summary", "compliance_status", "cve_exposure", "deployment_success",
        "deployment_failures", "rollback_history", "agent_health", "patch_coverage",
        "sla_violations", "risk_ranking", "mitigation_status", "relay_usage",
        "audit_trail", "executive_summary",
    ]