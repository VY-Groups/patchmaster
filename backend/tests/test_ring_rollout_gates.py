"""Characterization test for S1-1/S1-2: configured gates drive hold/rollback in the rollout run."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from api.ring_rollout import _execute_rollout_run


def _make(policy_gates):
    class P:
        id = 1
        rings = [{"name": "canary", "batch_percent": 100, "wait_seconds": 0}]
        guardrails = {}
        rollout_config = {"gates": policy_gates, "on_gate_failure": "hold"}
        target_os_family = "any"

    class R:
        id = 1
        policy_id = 1
        status = None
        action = None
        dry_run = True
        requested_by = "t"
        request_payload = {}
        summary = {}
        queue_job_id = ""
        started_at = None
        completed_at = None
        created_at = None
        updated_at = None

    def fake_session():
        s = AsyncMock()
        async def get(model, pk):
            name = getattr(model, "__name__", str(model))
            if name == "RingRolloutRun":
                return R()
            if name == "RingRolloutPolicy":
                return P()
            return None
        s.get = get
        s.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        s.commit = AsyncMock()
        s.flush = AsyncMock()
        s.add = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=s)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    return fake_session


def test_failing_pre_gate_holds_run():
    fake_session = _make({"pre": [{"type": "approval_granted"}], "on_failure": "hold"})
    import api.ring_rollout as rr
    rr.async_session = fake_session
    res = asyncio.run(_execute_rollout_run(1))
    assert res["status"] == "hold"
    # gate_results recorded
    # re-fetch run object not available; check via returned error
    assert res.get("error") == "gate_failed_pre"


def test_passing_pre_gate_promotes():
    fake_session = _make({"pre": [{"type": "approval_granted"}], "on_failure": "hold"})
    # inject approval via policy? approval comes from context/run_summary; default False -> fail.
    # To pass, use a gate type that passes on empty hosts: host_reachable (vacuous)
    fake_session = _make({"pre": [{"type": "host_reachable"}], "on_failure": "hold"})
    import api.ring_rollout as rr
    rr.async_session = fake_session
    res = asyncio.run(_execute_rollout_run(1))
    assert res["status"] == "success"