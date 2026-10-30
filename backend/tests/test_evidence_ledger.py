"""S1-5 Evidence Ledger tests (RED first)."""

import asyncio
import os

import pytest

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from evidence import create_bundle, _hash_payload


def _run(coro):
    return asyncio.run(coro)


def test_hash_payload_deterministic():
    assert _hash_payload({"a": 1, "b": 2}) == _hash_payload({"b": 2, "a": 1})


def test_create_bundle_records_hash_chain(mock_db_session):
    import unittest.mock as m
    mock_result = m.MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result
    mock_db_session.flush = m.AsyncMock()
    mock_db_session.add = lambda x: None

    bundle = _run(create_bundle(
        mock_db_session,
        job_id="job-1",
        items=[{"step": "patch", "kind": "result", "payload": {"ok": True}}],
    ))
    assert bundle.bundle_hash
    assert bundle.item_count == 1
    assert bundle.previous_bundle_hash is None  # first bundle