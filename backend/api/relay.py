"""Relay Service API (S2-5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from auth import require_role, get_current_user
from models.db_models import Relay, User, UserRole

router = APIRouter(prefix="/api/relays", tags=["relays"])

# in-memory cache: {relay_id: {patch_id: {"data": bytes, "checksum": str}}}
_RELAY_CACHE = {}


def cache_put(relay_id, patch_id, data: bytes, checksum: str) -> None:
    _RELAY_CACHE.setdefault(relay_id, {})[patch_id] = {"data": data, "checksum": checksum}


def cache_get(relay_id, patch_id):
    entry = _RELAY_CACHE.get(relay_id, {}).get(patch_id)
    if entry is None:
        return None
    # verify checksum
    import hashlib
    if hashlib.sha256(entry["data"]).hexdigest() != entry["checksum"]:
        return None
    return entry["data"]


@router.post("/register")
async def register_relay(name: str, mode: str = "jump", db: AsyncSession = Depends(get_db)):
    r = Relay(name=name, mode=mode, status="registered")
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return {"id": r.id, "name": r.name, "mode": r.mode, "status": r.status}


@router.get("/")
async def list_relays(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Relay))).scalars().all()
    return [{"id": r.id, "name": r.name, "mode": r.mode, "status": r.status} for r in rows]


@router.post("/{relay_id}/cache/{patch_id}")
async def relay_cache_put(relay_id: int, patch_id: str, checksum: str, data: str = ""):
    import base64
    raw = base64.b64decode(data) if data else b""
    cache_put(relay_id, patch_id, raw, checksum)
    return {"cached": True, "patch_id": patch_id}


@router.get("/{relay_id}/cache/{patch_id}")
async def relay_cache_get(relay_id: int, patch_id: str):
    data = cache_get(relay_id, patch_id)
    if data is None:
        return {"hit": False}
    import base64
    return {"hit": True, "data": base64.b64encode(data).decode()}


@router.get("/{relay_id}/distribution/{patch_id}")
async def relay_distribution_download(relay_id: int, patch_id: str):
    data = cache_get(relay_id, patch_id)
    if data is None:
        return {"hit": False, "mode": "distribution", "reason": "not_cached"}
    import base64, hashlib
    return {"hit": True, "mode": "distribution", "patch_id": patch_id,
            "checksum": hashlib.sha256(data).hexdigest(),
            "data": base64.b64encode(data).decode()}


@router.get("/{relay_id}/health")
async def relay_health(relay_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.get(Relay, relay_id)
    if r is None:
        raise HTTPException(status_code=404, detail="relay not found")
    return {"id": r.id, "status": r.status, "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "cache_quota_gb": r.cache_quota_gb, "bandwidth_cap_mbps": r.bandwidth_cap_mbps}