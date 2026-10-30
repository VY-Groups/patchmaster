"""S0-1 change set C: /api/register must not rotate agent tokens unauthenticated.

Defect (line-verified 2026-10-25): register_v2.py:352 accepted POST /api/register
with no credential, minted a fresh agent_token on every call (line 358), overwrote
host.agent_token (line 385) and returned it (line 420). That token gates heartbeats
(register_v2.py:464) and every backend->agent API (agent_proxy, backups, jobs_v2,
policies, ...). Unauthenticated consequence: steal a live agent credential and
lock the real agent out of its own heartbeat.

Contract enforced here (existing-host case):
  - Bearer == host.agent_token        -> accepted, token kept (no rotation)
  - Bearer == AGENT_API_TOKEN (env)   -> accepted, token rotated (operator path)
  - no/wrong Bearer                   -> 401
  - host without a token (legacy)     -> mint (documented bootstrap, keep working)
  - new host                          -> mint (bootstrap; enrollment secret = later plan item)

Tests are written first and must FAIL against the pre-fix code (plan.md 15.1.4).
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import register_v2  # noqa: E402
from api.register_v2 import RegisterRequest, register_agent  # noqa: E402


def _request(bearer=None):
    headers = []
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/register",
            "query_string": b"",
            "headers": headers,
            "client": ("9.9.9.9", 12345),
        }
    )


def _host(agent_token="current-host-token"):
    return SimpleNamespace(
        id=7,
        hostname="pc1",
        agent_id="agent-1",
        ip="10.0.0.5",
        site="",
        hardware_inventory={},
        os="Windows",
        os_version="11",
        kernel="10.0",
        arch="amd64",
        agent_version="2.0.0",
        agent_token=agent_token,
        is_online=False,
        last_heartbeat=None,
    )


def _payload():
    return RegisterRequest(
        hostname="pc1",
        os="Windows",
        os_version="11",
        kernel="10.0",
        arch="amd64",
        ip="10.0.0.5",
    )


def _register(bearer, host):
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    with patch.object(register_v2, "_ensure_host_schema", AsyncMock()), patch.object(
        register_v2, "_find_host_by_agent_id", AsyncMock(return_value=host)
    ), patch.object(register_v2, "_find_legacy_host", AsyncMock(return_value=None)), patch.object(
        register_v2, "_ensure_os_family_group", AsyncMock()
    ), patch.object(
        register_v2, "_schedule_mirror_automation_for_host"
    ), patch.object(
        register_v2, "sync_prometheus_agent_targets", AsyncMock()
    ):
        return asyncio.run(register_agent(_payload(), _request(bearer), db))


def test_unauthenticated_register_of_tokened_host_rejected():
    host = _host()
    with pytest.raises(Exception) as ei:
        _register(None, host)
    # Pre-fix this returned {"agent_token": <fresh uuid>} with HTTP 200.
    assert getattr(ei.value, "status_code", None) == 401, (
        f"expected 401, got {type(ei.value).__name__}: {ei.value}"
    )
    assert host.agent_token == "current-host-token"


def test_wrong_token_rejected():
    with pytest.raises(Exception) as ei:
        _register("attacker-guess", _host())
    assert getattr(ei.value, "status_code", None) == 401


def test_holder_of_current_token_accepted_without_rotation():
    host = _host()
    out = _register("current-host-token", host)
    # Pre-fix: a new uuid was minted and returned -> token churn.
    assert out == {"agent_token": "current-host-token"}
    assert host.agent_token == "current-host-token"


def test_shared_secret_can_rotate(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "operator-shared-secret")
    host = _host()
    out = _register("operator-shared-secret", host)
    assert out["agent_token"] not in ("", "current-host-token")
    assert host.agent_token == out["agent_token"]


def test_legacy_host_without_token_still_mints():
    # Documented bootstrap: heartbeat 401s tokenless hosts until they re-register.
    host = _host(agent_token=None)
    out = _register(None, host)
    assert out["agent_token"]
    assert host.agent_token == out["agent_token"]
