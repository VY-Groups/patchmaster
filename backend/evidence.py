"""Evidence Ledger service (S1-5/S1-6).

Creates hash-chained evidence bundles. Signs with Ed25519 when a dedicated
evidence signing key is available (PM_EVIDENCE_SIGNING_KEY env); otherwise
stores unsigned (shortcut preserved).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_models import EvidenceBundle, EvidenceItem


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def _previous_bundle_hash(session: AsyncSession) -> Optional[str]:
    row = (await session.execute(
        select(EvidenceBundle).order_by(EvidenceBundle.id.desc()).limit(1)
    )).scalar_one_or_none()
    return row.bundle_hash if row is not None else None


def _signing_key():
    raw = os.environ.get("PM_EVIDENCE_SIGNING_KEY")
    if not raw:
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        # accept base64-encoded 32-byte seed
        seed = base64.b64decode(raw)
        if len(seed) != 32:
            seed = hashlib.sha256(raw.encode()).digest()
        return Ed25519PrivateKey.from_private_bytes(seed)
    except Exception:
        return None


def _public_key_b64(priv) -> str:
    if priv is None:
        return ""
    pub = priv.public_key()
    from cryptography.hazmat.primitives import serialization
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


async def create_bundle(session: AsyncSession, job_id: Optional[str] = None,
                       tenant_id: Optional[str] = None,
                       items: Optional[list[dict]] = None) -> EvidenceBundle:
    items = items or []
    prev = await _previous_bundle_hash(session)
    bundle = EvidenceBundle(
        job_id=job_id,
        tenant_id=tenant_id,
        previous_bundle_hash=prev,
        item_count=len(items),
    )
    session.add(bundle)
    await session.flush()

    item_hashes = []
    for it in items:
        ph = _hash_payload(it.get("payload", {}))
        item = EvidenceItem(
            bundle_id=bundle.id,
            step=str(it.get("step", "")),
            kind=str(it.get("kind", "")),
            payload_ref=it.get("payload_ref"),
            payload_hash=ph,
        )
        session.add(item)
        item_hashes.append(ph)

    h = hashlib.sha256()
    if prev:
        h.update(prev.encode("utf-8"))
    for ih in sorted(item_hashes):
        h.update(ih.encode("utf-8"))
    h.update(str(job_id or "").encode("utf-8"))
    bundle.bundle_hash = h.hexdigest()

    # sign if key available
    priv = _signing_key()
    if priv is not None:
        sig = priv.sign(bundle.bundle_hash.encode("utf-8"))
        bundle.signature = base64.b64encode(sig).decode("utf-8")
        bundle.signer_key_id = _public_key_b64(priv)[:16]

    await session.flush()
    return bundle