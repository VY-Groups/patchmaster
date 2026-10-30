"""S0-2 threat-model fixes (docs/security/threat-model.md) + login 500 fix.

Findings under test, all proven FAIL against pre-fix code (plan.md 15.1.4):
- F5  job-status websocket has zero authentication   (jobs_v2.py:446)
- F4  websocket resolver accepts non-access JWTs     (notifications.py:207)
- F13 package push joins raw filename               (packages_router.py:201)
- F14 artifact GET unauthenticated + raw filename    (cicd.py:2607)
- F15 artifact upload writes raw client filename     (cicd.py:2591)
- L-1 login with a nonexistent username returns 500  (auth_api.py:321,
      malformed dummy hash for timing equalization -> passlib ValueError)
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402
from auth import create_access_token  # noqa: E402
from database import get_db  # noqa: E402
from models.db_models import User, UserRole  # noqa: E402
from api import cicd as cicd_mod  # noqa: E402
from api import jobs_v2  # noqa: E402
from api import notifications  # noqa: E402
from api import packages_router  # noqa: E402


def _user(role):
    return User(
        username=role.value,
        email=f"{role.value}@example.com",
        hashed_password="x",
        is_active=True,
        role=role,
    )


def _app(routers, role=UserRole.admin):
    """Bare app with routers + fake db feeding `role` to auth (rbac harness)."""
    app = FastAPI()
    for r in routers:
        app.include_router(r)

    class _Res:
        def scalar_one_or_none(self):
            return _user(role)

        def scalars(self):
            return self

        def all(self):
            return []

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Res())
    app.dependency_overrides[get_db] = lambda: db
    return app


def _hdr(role=UserRole.admin):
    return {"Authorization": f"Bearer {create_access_token({'sub': role.value})}"}


# ── F5: job websocket must authenticate before streaming job data ──


def test_job_ws_rejects_unauthenticated():
    client = TestClient(_app([jobs_v2.router]))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/jobs/ws/job/1") as ws:
            ws.receive_json()
    assert exc.value.code == 4401, (
        f"expected 4401 close, got {exc.value.code} (pre-fix code accepts "
        "anonymous sockets and streams job objects)"
    )


def test_job_ws_rejects_non_access_token():
    # F4: a reset/refresh-purpose JWT must not open a privileged socket.
    bad = jwt.encode(
        {
            "sub": "admin",
            "type": "reset",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    client = TestClient(_app([jobs_v2.router]))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/jobs/ws/job/1?token={bad}") as ws:
            ws.receive_json()
    assert exc.value.code == 4401, f"non-access token accepted (close={exc.value.code})"


def test_ws_resolver_accepts_access_token():
    """Guard against over-blocking: a real access token still resolves."""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, _query):
            class _R:
                def scalar_one_or_none(self):
                    return _user(UserRole.viewer)

            return _R()

    class _WS:
        query_params = {"token": create_access_token({"sub": "viewer"})}
        cookies = {}

    original = notifications.async_session
    notifications.async_session = _FakeSession
    try:
        user = asyncio.run(notifications._resolve_websocket_user(_WS()))
    finally:
        notifications.async_session = original
    assert user is not None, "valid access token must pass the websocket resolver"


# ── F14: artifact download requires auth and rejects traversal ──


def test_artifact_download_requires_auth():
    client = TestClient(_app([cicd_mod.router]))
    r = client.get("/api/cicd/artifacts/1/something.txt")
    assert r.status_code in (401, 403), (
        f"unauthenticated artifact read returned {r.status_code}"
    )


def test_artifact_download_traversal_blocked():
    artifacts = cicd_mod.ARTIFACTS_DIR
    artifacts.mkdir(parents=True, exist_ok=True)
    canary = artifacts / "s02_canary_read.txt"
    canary.write_text("canary")
    try:
        client = TestClient(_app([cicd_mod.router]))
        r = client.get(
            "/api/cicd/artifacts/1/..%5Cs02_canary_read.txt", headers=_hdr()
        )
        assert r.status_code in (400, 404), (
            f"traversal read returned {r.status_code} (canary escaped)"
        )
    finally:
        canary.unlink(missing_ok=True)


# ── F15: artifact upload rejects traversal filenames ──


def test_artifact_upload_traversal_blocked():
    artifacts = cicd_mod.ARTIFACTS_DIR
    canary = artifacts / "s02_canary_up.txt"
    landed = artifacts / "build_999999" / "s02_canary_up.txt"
    canary.unlink(missing_ok=True)
    landed.unlink(missing_ok=True)
    try:
        client = TestClient(_app([cicd_mod.router]))
        r = client.post(
            "/api/cicd/builds/999999/artifacts/upload",
            files={"file": ("..\\s02_canary_up.txt", b"x")},
            headers=_hdr(),
        )
        assert not canary.exists(), "upload escaped the build directory"
        assert r.status_code in (400, 422), (
            f"traversal upload returned {r.status_code}"
        )
    finally:
        canary.unlink(missing_ok=True)
        landed.unlink(missing_ok=True)


# ── F13: package push rejects traversal filenames ──


def test_package_push_traversal_blocked():
    repo = Path(packages_router.LOCAL_REPO_DIR)
    canary = repo.parent / "s02_push_canary.pkg"
    canary.write_text("canary")
    try:
        client = TestClient(_app([packages_router.router], role=UserRole.operator))
        r = client.post(
            "/api/packages/local/push/1",
            params={"filename": "../s02_push_canary.pkg"},
            headers=_hdr(UserRole.operator),
        )
        assert r.status_code == 400, (
            f"push traversal returned {r.status_code} (pre-fix reads the canary "
            "outside LOCAL_REPO_DIR and proceeds to the agent)"
        )
    finally:
        canary.unlink(missing_ok=True)


# ── Login with a nonexistent username must be 401, not 500 ──


def test_login_unknown_user_returns_401_not_500():
    """auth_api.py:321 runs verify_password against a malformed dummy hash
    ('$pbkdf2-sha256$29000$dummy$dummyhash') for timing equalization ->
    passlib ValueError: invalid base64 input -> HTTP 500 for every login
    attempt with a username that does not exist."""
    from api import auth_api

    class _NoUser:
        def scalar_one_or_none(self):
            return None

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_NoUser())

    app = FastAPI()
    app.include_router(auth_api.router)
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post(
        "/api/auth/login",
        json={"username": "no-such-user-s02", "password": "Whatever-12345!"},
    )
    assert r.status_code == 401, (
        f"unknown-user login gave {r.status_code}; pre-fix the dummy hash "
        "raises ValueError -> 500"
    )
