"""S0-1 change set E: RBAC on destructive routes + session revocation on password change.

Defects (line-verified 2026-10-25, inventory produced by parsing every
@router.(post|put|delete|patch) in the four files):
- agent_proxy.py: 30 mutating routes (reboot, shutdown, snapshot rollback/delete/
  restore, patch/execute, wsus/install, cleanup, ...) gate only on
  get_current_user -> a VIEWER can reboot and patch machines. (The /run handlers
  even contain manual `user.role not in (admin, operator)` checks - the intended
  gate - just not in the dependency.)
- backups.py: create config / run / restore gate on get_current_user only, and
  POST /storage/test has NO auth at all (local filesystem path probing).
- policies.py: create/update/delete gate on get_current_user while sibling
  revision routes already use require_role(admin, operator).
- license_router.py: POST /activate gates on get_current_user while its sibling
  activate-manual/deactivate all require admin.
- auth_api.change_password never calls revoke_all_user_tokens -> sessions opened
  with the old password survive a password change.

Convention used (repo-wide grep, 134 occurrences): require_role(UserRole.admin,
UserRole.operator) for mutation, require_role(UserRole.admin) for license ops.

Tests are written first and must FAIL against the pre-fix code (plan.md 15.1.4).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))

from auth import create_access_token, get_db, hash_password  # noqa: E402
from api import auth_api  # noqa: E402
from api.agent_proxy import router as agent_proxy_router  # noqa: E402
from api.backups import router as backups_router  # noqa: E402
from api.policies import router as policies_router  # noqa: E402
from api.license_router import router as license_router  # noqa: E402
from models.db_models import User, UserRole  # noqa: E402

# Every mutating route that must not be reachable by a viewer.
VIEWER_FORBIDDEN = [
    *(f"POST /api/agent/10.0.0.1/{p}" for p in [
        "system/reboot", "system/shutdown", "software/manage", "software/queue",
        "packages/refresh", "snapshot/create", "snapshot/precheck",
        "snapshot/rollback", "snapshot/delete", "snapshot/restore-url",
        "snapshot/restore-upload", "cleanup", "patch/execute",
        "offline/install", "offline/clear", "wsus/install", "wsus/download",
        "wsus/install-selected", "packages/uris", "patch/server-patch", "run",
    ]),
    *(f"POST /api/agent/by-host/1/{p}" for p in [
        "snapshot/create", "snapshot/precheck", "snapshot/rollback",
        "snapshot/delete", "snapshot/restore-url", "snapshot/restore-upload",
        "cleanup", "run",
    ]),
    "POST /api/agent/clone-snapshot",
    "POST /api/backups/configs",
    "POST /api/backups/1/run",
    "POST /api/backups/storage/test",
    "POST /api/backups/1/restore",
    "POST /api/policies/",
    "PUT /api/policies/1",
    "DELETE /api/policies/1",
    "POST /api/license/activate",
]

# Reads must stay open for viewers (regression guard for over-blocking).
# Only non-proxying routes: agent_proxy GETs stream from a live agent host.
VIEWER_ALLOWED = [
    "GET /api/backups/configs",
    "GET /api/policies/",
]


def _user(role):
    return User(
        username=role.value,
        email=f"{role.value}@example.com",
        hashed_password="x",
        is_active=True,
        role=role,
    )


def _app(role):
    app = FastAPI()
    for r in (agent_proxy_router, backups_router, policies_router, license_router):
        app.include_router(r)

    def fake_db():
        wanted = _user(role)

        class _Res:
            def scalar_one_or_none(self):
                return wanted

            def scalars(self):
                return self

            def all(self):
                return []

            def first(self):
                return None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Res())
        return db

    app.dependency_overrides[get_db] = fake_db
    return app


def _call(role, spec):
    method, path = spec.split(" ", 1)
    client = TestClient(_app(role))
    token = create_access_token({"sub": role.value})
    return client.request(
        method, path, json={}, headers={"Authorization": f"Bearer {token}"}
    )


@pytest.mark.parametrize("spec", VIEWER_FORBIDDEN)
def test_viewer_cannot_mutate(spec):
    resp = _call(UserRole.viewer, spec)
    # Pre-fix: any active user passed the gate (200/422/500 from downstream).
    assert resp.status_code == 403, (
        f"{spec}: expected 403 for viewer, got {resp.status_code}"
    )


@pytest.mark.parametrize("spec", VIEWER_ALLOWED)
def test_viewer_can_read(spec):
    resp = _call(UserRole.viewer, spec)
    assert resp.status_code != 403, f"{spec}: reads must stay open for viewers"


@pytest.mark.parametrize("spec", ["POST /api/agent/10.0.0.1/system/reboot",
                                  "POST /api/policies/",
                                  "POST /api/license/activate"])
def test_admin_passes_the_gate(spec):
    resp = _call(UserRole.admin, spec)
    assert resp.status_code != 403, f"{spec}: admin was blocked"


# --- change_password must revoke existing sessions (same rule as reset) ---


def test_change_password_revokes_all_refresh_tokens(monkeypatch):
    revoker = AsyncMock()
    monkeypatch.setattr(auth_api, "revoke_all_user_tokens", revoker)

    user = _user(UserRole.admin)
    user.hashed_password = hash_password("Old-V4lid-Passw0rd!")
    db = AsyncMock()
    db.commit = AsyncMock()
    out = asyncio.run(
        auth_api.change_password(
            {"old_password": "Old-V4lid-Passw0rd!",
             "new_password": "Changed-Numb3r-9ine!"},
            user,
            db,
        )
    )
    assert out == {"ok": True}
    revoker.assert_awaited_once()


def test_auth_module_and_package_do_not_collide():
    """S0-1/S0-3: backend/auth/ was a dead duplicate beside backend/auth.py —
    unimportable (auth.py shadows it), zero importers, and it still carried the
    pre-S0-1 JWT default plus an F821 bug in its 403 f-string. Either form,
    never both: auth.py as module, or auth/ as a package, not the two together."""
    module = BACKEND / "auth.py"
    package = BACKEND / "auth"
    assert not (module.is_file() and package.exists()), (
        "backend/auth.py and backend/auth/ both exist — the package is shadowed "
        "and drifts (see git history for the stale copy)."
    )
