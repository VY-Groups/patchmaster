"""Per-IP rate limit on POST /api/auth/forgot (plan.md S0-1, closes the
``shortcut: no per-IP rate limit on /forgot yet`` note in auth_api.py).

slowapi is already a dependency and ``/login`` already declares
``@limiter.limit``, but nothing ever linked the Limiter to the app, so slowapi
never checked a single request. This file pins the real behaviour:
  - under the limit from one IP  -> 200 (generic body, no enumeration change)
  - the next request from that IP -> 429, without touching the database
  - the wiring helper is what main.py must call

Expected to FAIL against pre-change code (no install_rate_limiting helper, no
middleware, no limit on /forgot).
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import test_password_reset_otp as otp  # noqa: E402  (shared fakes, same dir)
from api import auth_api, notifications  # noqa: E402
from api.auth_api import FORGOT_MAX_PER_MINUTE, install_rate_limiting  # noqa: E402
from database import get_db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_limits():
    """slowapi keeps counters in process memory - start every test empty."""
    auth_api.limiter.reset()
    yield
    auth_api.limiter.reset()


def _client(db):
    app = FastAPI()
    app.include_router(auth_api.router)
    app.dependency_overrides[get_db] = lambda: db
    install_rate_limiting(app)
    return TestClient(app, raise_server_exceptions=False)


def _db():
    return otp._FakeDB(user=otp._user(), channel=otp._email_channel())


def _forgot(client):
    return client.post("/api/auth/forgot", json={"username_or_email": "admin"})


def test_forgot_allows_up_to_the_limit_then_returns_429(monkeypatch):
    sender = AsyncMock()
    monkeypatch.setattr(notifications, "_send_notification", sender)

    client = _client(_db())
    allowed = [_forgot(client).status_code for _ in range(FORGOT_MAX_PER_MINUTE)]

    assert allowed == [200] * FORGOT_MAX_PER_MINUTE, f"under-limit calls: {allowed}"

    blocked = _forgot(client)
    assert blocked.status_code == 429, f"expected 429, got {blocked.status_code}"
    # The 429 must not depend on the user existing (no enumeration oracle).
    assert "admin" not in blocked.text


def test_rate_limit_blocks_before_the_handler_runs(monkeypatch):
    """A blocked request must not spend an OTP or queue an email."""
    sender = AsyncMock()
    monkeypatch.setattr(notifications, "_send_notification", sender)
    db = _db()

    client = _client(db)
    for _ in range(FORGOT_MAX_PER_MINUTE):
        _forgot(client)
    before_rows = len(db.otps)
    before_emails = sender.await_count

    blocked = _forgot(client)
    assert blocked.status_code == 429
    assert len(db.otps) == before_rows, "limited request still wrote an OTP row"
    assert sender.await_count == before_emails, "limited request still queued an email"


def test_install_rate_limiting_wires_the_limiter_into_the_app():
    """main.py must call this - without it slowapi's decorators never fire."""
    app = FastAPI()
    install_rate_limiting(app)

    assert app.state.limiter is auth_api.limiter
    from slowapi.errors import RateLimitExceeded

    assert RateLimitExceeded in app.exception_handlers
    middleware_names = [getattr(m, "cls", type(m)).__name__ for m in app.user_middleware]
    assert "SlowAPIMiddleware" in middleware_names, middleware_names
