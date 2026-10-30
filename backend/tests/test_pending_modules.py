import os
import asyncio

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from feed_ingestion import NVDSource, OSVSource, sync_source
from scanning import in_scope, enforce_scope, ScopeViolation, scan_target
from topology_orchestrator import patch_service
from airgap import import_bundle


def _run(coro):
    return asyncio.run(coro)


def test_feed_sync_idempotent():
    from unittest.mock import patch
    with patch.object(NVDSource, "fetch", return_value=[]):
        r = _run(sync_source(NVDSource(), None))
    assert r["ingested"] == 0
    assert r["idempotent"] is True


def test_scan_scope_refusal():
    assert in_scope("10.0.0.1", ["10.0.0.1"]) is True
    assert in_scope("10.0.0.2", ["10.0.0.1"]) is False
    try:
        _run(scan_target("10.0.0.2", ["10.0.0.1"]))
        assert False
    except ScopeViolation:
        pass


def test_topology_stop_on_tolerance():
    async def main():
        async def pf(m):
            return m != "bad"
        return await patch_service({"name": "svc"}, ["a", "bad", "bad", "bad"], pf, tolerance=1)
    r = _run(main())
    assert r["status"] == "stopped"


def test_airgap_import_valid():
    async def main():
        from unittest.mock import AsyncMock, MagicMock
        session = AsyncMock()
        session.add = lambda x: None
        session.flush = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        session.execute.return_value = res
        bundle = {"bundle_hash": None, "items": [], "job_id": "j"}
        # compute hash
        import hashlib
        h = hashlib.sha256()
        h.update(b"j")
        bundle["bundle_hash"] = h.hexdigest()
        bundle["previous_bundle_hash"] = None
        return await import_bundle(session, bundle)
    r = _run(main())
    assert r["ok"] is True