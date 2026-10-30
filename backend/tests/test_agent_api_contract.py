"""plan.md S0-5/S0-6: characterization tests for the agent HTTP contract.

Written BEFORE the agent.py decomposition (S0-5 rule: characterization first).
The route table below is frozen: a refactor must reproduce it exactly, so a
behaviour change fails here rather than in production. Update this file only
when the public contract itself is meant to change.

Requires Flask (agent/requirements.txt). CI installs that file alongside the
backend requirements, so these tests run in the CI-fidelity suite rather than
skipping.
"""

import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

# Pin the PACKAGE identity (agent/__init__ -> agent.agent) before any test
# inserts <repo>/agent on sys.path - a flat `import agent` there would cache
# agent as a non-package and break tests doing `import agent.agent`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
agent_mod = import_module("agent.agent")

# The full public surface of the agent Flask app: every rule and its verbs.
ROUTES = [
    ("/api/debug/gc", ["POST"]),
    ("/api/debug/memory", ["GET"]),
    ("/api/version", ["GET"]),
    ("/backup/restore", ["POST"]),
    ("/backup/trigger", ["POST"]),
    ("/cleanup", ["POST"]),
    ("/devops/run", ["POST"]),
    ("/health", ["GET"]),
    ("/history", ["GET"]),
    ("/job/history", ["GET"]),
    ("/job/reset", ["POST"]),
    ("/job/status", ["GET"]),
    ("/offline/clear", ["POST"]),
    ("/offline/install", ["POST"]),
    ("/offline/list", ["GET"]),
    ("/offline/upload", ["POST"]),
    ("/packages/installed", ["GET"]),
    ("/packages/refresh", ["POST"]),
    ("/packages/upgradable", ["GET"]),
    ("/packages/uris", ["POST"]),
    ("/patch/execute", ["POST"]),
    ("/policy/apply", ["POST"]),
    ("/run", ["POST"]),
    ("/snapshot/archive/<name>", ["GET"]),
    ("/snapshot/create", ["POST"]),
    ("/snapshot/delete", ["POST"]),
    ("/snapshot/list", ["GET"]),
    ("/snapshot/precheck", ["POST"]),
    ("/snapshot/restore_upload", ["POST"]),
    ("/snapshot/restore_url", ["POST"]),
    ("/snapshot/rollback", ["POST"]),
    ("/software/manage", ["POST"]),
    ("/software/queue", ["DELETE"]),
    ("/software/queue", ["GET"]),
    ("/software/queue", ["POST"]),
    ("/status", ["GET"]),
    ("/system/reboot", ["POST"]),
    ("/system/shutdown", ["POST"]),
    ("/wsus/download", ["POST"]),
    ("/wsus/install", ["POST"]),
    ("/wsus/status", ["GET"]),
    ("/wsus/updates", ["GET"]),
]


def _route_table():
    rows = [
        (rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}))
        for rule in agent_mod.app.url_map.iter_rules()
        if rule.endpoint != "static"
    ]
    return sorted(rows)


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Flask test client with an isolated, token-free agent state dir."""
    assert hasattr(agent_mod.app, "test_client"), (
        "Flask is required for the agent contract tests "
        "(pip install -r agent/requirements.txt)"
    )
    # Isolate from any token file a dev machine may have on disk.
    monkeypatch.setenv("PATCHMASTER_AGENT_STATE", str(tmp_path))
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)
    return agent_mod.app.test_client()


@pytest.fixture
def idle_job(monkeypatch):
    """Pin JOB_STATUS so job endpoints answer deterministically."""
    monkeypatch.setattr(
        agent_mod,
        "JOB_STATUS",
        {
            "state": "idle",
            "current_job": None,
            "progress": 0,
            "log": [],
            "last_result": None,
            "started_at": None,
        },
    )


# ── route table ────────────────────────────────────────────────────────────


def test_route_table_matches_characterization():
    assert _route_table() == ROUTES


def test_unknown_route_is_404(client):
    resp = client.get("/no/such/route")
    assert resp.status_code == 404


def test_head_options_allowed_on_get_routes(client):
    # Flask defaults: HEAD is implied on GET rules - part of the contract.
    resp = client.head("/health")
    assert resp.status_code == 200


# ── response shapes ────────────────────────────────────────────────────────


def test_health_shape(client, monkeypatch):
    # Stub the package manager so the probe never runs host commands.
    monkeypatch.setattr(
        agent_mod, "pkg_mgr", SimpleNamespace(check_reboot=lambda: False)
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {
        "status",
        "hostname",
        "os",
        "agent_version",
        "reboot_required",
        "state",
    }
    assert body["status"] == "ok"
    assert body["reboot_required"] is False


def test_api_version_shape(client):
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert set(resp.get_json()) == {"version"}
    assert isinstance(resp.get_json()["version"], str)


def test_job_status_shape(client, idle_job):
    resp = client.get("/job/status")
    assert resp.status_code == 200
    assert set(resp.get_json()) == {
        "state",
        "current_job",
        "progress",
        "log",
        "last_result",
        "started_at",
    }


# ── auth contract (agent.py _require_auth) ────────────────────────────────


def test_privileged_endpoint_503_without_any_token(client, idle_job):
    """No token configured -> privileged endpoints refuse with 503, not 401."""
    resp = client.post("/job/reset")
    assert resp.status_code == 503
    assert resp.get_json() == {"error": "agent auth token not initialized"}


def test_privileged_endpoint_401_with_wrong_token(client, monkeypatch, idle_job):
    monkeypatch.setenv("AGENT_API_TOKEN", "right-token")
    resp = client.post("/job/reset", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


def test_privileged_endpoint_accepts_valid_token(client, monkeypatch, idle_job):
    monkeypatch.setenv("AGENT_API_TOKEN", "right-token")
    resp = client.post(
        "/job/reset", headers={"Authorization": "Bearer right-token"}
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "reset"}


def test_state_dir_token_file_is_accepted(client, monkeypatch, tmp_path, idle_job):
    """The registration token main.py persists must unlock the API."""
    (tmp_path / "token").write_text("per-host-token", encoding="utf-8")
    resp = client.post(
        "/job/reset", headers={"Authorization": "Bearer per-host-token"}
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "reset"}


def test_unauthenticated_public_endpoints_stay_open(client):
    """Public read endpoints must NOT be behind _require_auth."""
    assert client.get("/job/status").status_code == 200
    assert client.get("/api/version").status_code == 200
