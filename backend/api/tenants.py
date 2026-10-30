"""Tenant onboarding & administration (SaaS)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import require_role, User, UserRole, get_current_user
from models.db_models import Tenant

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


@router.post("/")
async def create_tenant(name: str, slug: str, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_role(UserRole.admin))):
    existing = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="tenant slug already exists")
    t = Tenant(name=name, slug=slug)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return {"id": t.id, "name": t.name, "slug": t.slug, "plan": t.plan}


@router.get("/")
async def list_tenants(db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_role(UserRole.admin))):
    rows = (await db.execute(select(Tenant))).scalars().all()
    return [{"id": t.id, "name": t.name, "slug": t.slug, "plan": t.plan} for t in rows]


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return {"id": t.id, "name": t.name, "slug": t.slug, "plan": t.plan, "settings": t.settings}