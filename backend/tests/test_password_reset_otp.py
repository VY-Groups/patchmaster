"""OTP-based forgot/reset password flow (plan.md Stage 0, Task C).

Replaces the previous flow where POST /api/auth/reset-password accepted a JWT
"reset" token delivered by email (user request: the JWT reset option is too
basic; make it OTP based).

New contract under test:
  POST /api/auth/forgot          {"username_or_email"}      -> {"status": "ok"}
  POST /api/auth/reset-password  {"username_or_email", "otp", "new_password"}

Properties, all expected to FAIL against the pre-change code (plan.md 15.1.4):
- a 6-digit OTP is delivered by email only, never in an HTTP response
- the OTP is hashed at rest (no plaintext column)
- 10-minute expiry, 5 attempts max, single use
- unknown user -> byte-identical response (no enumeration)
- the legacy JWT `token` body is rejected outright
- a successful reset revokes every existing session
"""

import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import auth_api, notifications  # noqa: E402
from api.auth_api import ForgotPasswordRequest, forgot_password  # noqa: E402
from auth import verify_password  # noqa: E402
from database import get_db  # noqa: E402
from models.db_models import User, UserRole  # noqa: E402


class _Res:
    """Stand-in for a SQLAlchemy Result (user / channel / OTP-row lookup)."""

    def __init__(self, user=None, rows=()):
        self._user = user
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._user

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    """In-memory AsyncSession stand-in: holds one user and the OTP rows."""

    def __init__(self, user=None, channel=None):
        self.user = user
        self.channel = channel
        self.otps = []

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        name = getattr(entity, "__name__", "")
        if name == "User":
            return _Res(user=self.user)
        if name == "NotificationChannel":
            return _Res(rows=[self.channel] if self.channel else [])
        if name == "PasswordResetOTP":
            uid = getattr(self.user, "id", None)
            return _Res(rows=[o for o in self.otps if o.user_id == uid])
        return _Res()

    def add(self, obj):
        self.otps.append(obj)

    async def delete(self, obj):
        if obj in self.otps:
            self.otps.remove(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


def _user():
    return User(
        id=1,
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        is_active=True,
        role=UserRole.admin,
    )


def _email_channel():
    from types import SimpleNamespace

    return SimpleNamespace(
        channel_type="email",
        config={"smtp_host": "mail.internal", "smtp_port": 587},
        is_enabled=True,
    )


def _client(db):
    app = FastAPI()
    app.include_router(auth_api.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def revoked(monkeypatch):
    """Stub session revocation (it would hit the real DB otherwise)."""
    stub = AsyncMock()
    monkeypatch.setattr(auth_api, "revoke_all_user_tokens", stub)
    return stub


def _request():
    """slowapi's @limiter.limit wrapper refuses to run without a Request.

    This test drives the handler directly rather than over HTTP, so hand it a
    bare scope with the limiter check pre-marked done - the rate-limit budget
    itself is asserted in test_forgot_rate_limit.py.
    """
    req = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/auth/forgot",
            "raw_path": b"/api/auth/forgot",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
        }
    )
    req.state._rate_limiting_complete = True
    req.state.view_rate_limit = None
    return req


def _issue(db, monkeypatch, username="admin"):
    """POST /forgot with email delivery captured; returns the 6-digit code."""
    sender = AsyncMock()
    monkeypatch.setattr(notifications, "_send_notification", sender)
    r = _client(db).post("/api/auth/forgot", json={"username_or_email": username})
    assert r.status_code == 200, r.text
    if not sender.await_args:
        return None, ""
    body = sender.await_args.args[2]
    m = re.search(r"\b(\d{6})\b", body)
    return (m.group(1) if m else None), body


def _reset(db, otp, password="Reset-Numb3r-7hree!", username="admin"):
    return _client(db).post(
        "/api/auth/reset-password",
        json={
            "username_or_email": username,
            "otp": otp,
            "new_password": password,
        },
    )


# 1. /forgot never echoes a code, and the email carries the OTP ──────────────


def test_smtp_send_is_deferred_to_background_task(monkeypatch):
    """The send must sit in BackgroundTasks, never in the request path
    (uniform, fast response = no timing oracle for user enumeration)."""
    from fastapi import BackgroundTasks

    sender = AsyncMock()
    monkeypatch.setattr(notifications, "_send_notification", sender)

    db = _FakeDB(user=_user(), channel=_email_channel())
    bg = BackgroundTasks()
    result = asyncio.run(
        forgot_password(
            _request(), ForgotPasswordRequest(username_or_email="admin"), bg, db
        )
    )
    assert result == {"status": "ok"}
    assert len(bg.tasks) == 1, "SMTP send must not run inline in the request"
    assert sender.await_args is None, "send ran before the response was sent"

    asyncio.run(bg())  # background task fires after the response
    sender.assert_awaited_once()
    sendable, title, body = sender.await_args.args
    assert sendable.config["to"] == "admin@example.com", "not sent to the account's own address"
    assert re.search(r"\b\d{6}\b", body), "OTP missing from email body"


def test_forgot_response_has_no_code(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    r = _client(db).post("/api/auth/forgot", json={"username_or_email": "admin"})
    assert r.status_code == 200
    assert set(r.json().keys()) == {"status"}
    assert not re.search(r"\b\d{6}\b", r.text), "OTP leaked in the HTTP response"
    assert len(db.otps) == 1, "no OTP row persisted"


def test_otp_is_hashed_at_rest(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _body = _issue(db, monkeypatch)
    assert code, "email body carries no 6-digit code"
    row = db.otps[0]
    assert getattr(row, "code_hash", None), "OTP stored in plaintext"
    assert code not in row.code_hash
    assert verify_password(code, row.code_hash), "code_hash must verify the OTP"


def test_otp_email_contains_6_digit_code_not_jwt(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, body = _issue(db, monkeypatch)
    assert code, "reset email has no 6-digit OTP"
    assert "eyJ" not in body, "email still carries the legacy JWT reset token"


# 2. happy path: valid OTP sets the password and kills old sessions ──────────


def test_reset_with_valid_otp_sets_password_and_revokes(monkeypatch, revoked):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _ = _issue(db, monkeypatch)
    assert code

    r = _reset(db, code)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}
    assert verify_password("Reset-Numb3r-7hree!", db.user.hashed_password)
    revoked.assert_awaited_once()
    assert db.otps == [], "used OTP row must be deleted (single use)"


# 3. rejection paths ─────────────────────────────────────────────────────────


def _wrong(code):
    """Deterministic wrong OTP (never equals the issued one)."""
    return ("9" if code[0] != "9" else "8") + code[1:]


def test_reset_with_wrong_otp_rejected(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _ = _issue(db, monkeypatch)
    assert code
    r = _reset(db, _wrong(code))
    assert r.status_code == 400
    assert db.otps, "a wrong guess must not destroy the OTP"


def test_reset_unknown_user_same_error_as_wrong_otp(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _ = _issue(db, monkeypatch)
    assert code

    wrong = _reset(db, _wrong(code))
    unknown = _reset(db, _wrong(code), username="nobody")
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json(), "reset leaks account existence"


def test_otp_is_single_use(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _ = _issue(db, monkeypatch)
    assert _reset(db, code).status_code == 200
    again = _reset(db, code, password="Another-Pass123!")
    assert again.status_code == 400, "a spent OTP was accepted again"


def test_expired_otp_rejected(monkeypatch):
    from datetime import datetime, timedelta, timezone

    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _ = _issue(db, monkeypatch)
    assert code
    db.otps[0].expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        minutes=1
    )
    r = _reset(db, code)
    assert r.status_code == 400
    assert db.otps == [], "expired OTP row must be invalidated"


def test_attempts_capped_at_five(monkeypatch):
    db = _FakeDB(user=_user(), channel=_email_channel())
    code, _ = _issue(db, monkeypatch)
    assert code
    for i in range(5):
        r = _reset(db, _wrong(code))
        assert r.status_code == 400, f"wrong OTP attempt {i + 1} was accepted"
    # 6th attempt with the CORRECT code: the code must already be destroyed.
    r = _reset(db, code)
    assert r.status_code == 400, "OTP survived 5 failed attempts"
    assert db.otps == [], "OTP row not destroyed at the attempt cap"


# 4. the legacy JWT reset body is gone ───────────────────────────────────────


def test_legacy_jwt_token_body_rejected():
    db = _FakeDB(user=_user(), channel=_email_channel())
    r = _client(db).post(
        "/api/auth/reset-password",
        json={"token": "anything", "new_password": "Reset-Numb3r-7hree!"},
    )
    assert r.status_code == 422, "JWT reset body still accepted"
