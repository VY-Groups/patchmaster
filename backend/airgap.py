"""Air-gapped bundle import (S7)."""

from __future__ import annotations

import json
from typing import Any, Optional

from evidence import create_bundle


def validate_bundle(bundle: dict) -> tuple[bool, list[str]]:
    failures = []
    if not isinstance(bundle, dict):
        return False, ["not a dict"]
    if "bundle_hash" not in bundle:
        failures.append("missing bundle_hash")
    items = bundle.get("items", [])
    if not isinstance(items, list):
        failures.append("items not a list")
        return False, failures
    # hash check
    import hashlib
    h = hashlib.sha256()
    prev = bundle.get("previous_bundle_hash")
    if prev:
        h.update(prev.encode("utf-8"))
    for ih in sorted(it.get("payload_hash", "") for it in items):
        h.update(ih.encode("utf-8"))
    h.update(str(bundle.get("job_id") or "").encode("utf-8"))
    if h.hexdigest() != bundle.get("bundle_hash"):
        failures.append("bundle_hash mismatch")
    # payload hash check
    for i, it in enumerate(items):
        if "payload" in it and "payload_hash" in it:
            ph = hashlib.sha256(__import__("json").dumps(it["payload"], sort_keys=True).encode()).hexdigest()
            if ph != it["payload_hash"]:
                failures.append(f"item {i} payload_hash mismatch")
    return len(failures) == 0, failures


async def import_bundle(session, bundle: dict, policy: Optional[dict] = None) -> dict:
    """Import a bundle produced offline: verify hash chain, then record as evidence."""
    # basic validation
    if not isinstance(bundle, dict) or "bundle_hash" not in bundle:
        return {"ok": False, "reason": "invalid bundle"}
    items = bundle.get("items", [])
    # recompute bundle hash
    import hashlib
    h = hashlib.sha256()
    prev = bundle.get("previous_bundle_hash")
    if prev:
        h.update(prev.encode("utf-8"))
    for ih in sorted(it.get("payload_hash", "") for it in items):
        h.update(ih.encode("utf-8"))
    h.update(str(bundle.get("job_id") or "").encode("utf-8"))
    if h.hexdigest() != bundle.get("bundle_hash"):
        return {"ok": False, "reason": "bundle_hash mismatch"}
    # record
    await create_bundle(session, job_id=bundle.get("job_id"), items=items)
    return {"ok": True, "imported": len(items)}