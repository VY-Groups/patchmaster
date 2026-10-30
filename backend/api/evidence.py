"""Evidence Ledger API (S1-5/S1-7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from auth import get_current_user, require_role
from models.db_models import EvidenceBundle, EvidenceItem

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("/bundles")
async def list_bundles(job_id: str = None, limit: int = 50, db: AsyncSession = Depends(get_db)):
    stmt = select(EvidenceBundle).order_by(EvidenceBundle.id.desc()).limit(limit)
    if job_id:
        stmt = stmt.where(EvidenceBundle.job_id == job_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": r.id, "job_id": r.job_id, "bundle_hash": r.bundle_hash,
             "previous_bundle_hash": r.previous_bundle_hash, "signature": r.signature,
             "item_count": r.item_count, "created_at": r.created_at.isoformat() if r.created_at else None,
             "storage_ref": r.storage_ref} for r in rows]


@router.get("/bundles/{bundle_id}")
async def get_bundle(bundle_id: int, db: AsyncSession = Depends(get_db)):
    bundle = await db.get(EvidenceBundle, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="bundle not found")
    items = (await db.execute(
        select(EvidenceItem).where(EvidenceItem.bundle_id == bundle_id).order_by(EvidenceItem.id)
    )).scalars().all()
    return {
        "id": bundle.id,
        "job_id": bundle.job_id,
        "tenant_id": bundle.tenant_id,
        "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
        "bundle_hash": bundle.bundle_hash,
        "previous_bundle_hash": bundle.previous_bundle_hash,
        "signature": bundle.signature,
        "signer_key_id": bundle.signer_key_id,
        "storage_ref": bundle.storage_ref,
        "item_count": bundle.item_count,
        "items": [{"id": it.id, "step": it.step, "kind": it.kind,
                   "payload_ref": it.payload_ref, "payload_hash": it.payload_hash,
                   "created_at": it.created_at.isoformat() if it.created_at else None} for it in items],
    }