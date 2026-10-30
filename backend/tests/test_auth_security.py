"""S0-1 token-handling hardening tests (plan.md Stage 0, work package S0-1).

Requirements quoted from plan.md S0-1: "close every item ... token handling,
hard-coded defaults".

Covers three concrete defects found by audit (line-verified 2026-10-25):
1. POST /api/auth/forgot returned a working reset JWT in the response body and
   404'd for unknown users (account takeover + user enumeration).
2. A reset-purpose JWT was accepted by get_current_user as an access token
   (auth.py only rejected type == "refresh").
3. Password reset did not revoke the user's existing refresh tokens
   (revoke_all_user_tokens had zero call sites).

Tests are written first and must FAIL against the pre-fix code (plan.md 15.1.4).
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import ALGORITHM, SECRET_KEY, create_access_token, get_current_user
from api.auth_api import (
    ForgotPasswordRequest,
    forgot_password,
)
from fastapi import HTTPException
from starlette.requests import Request
from models.db_models import User, UserRole


class _Result:
    """Stand-in for a SQLAlchemy Result: user lookup OR channel lookup."""

    def __init__(self, user=None, channel=None):
        self._user = user
        self._channel = channel

    def scalar_one_or_none(self):
        return self._user

    def scalars(self):
        channel = self._channel
        class _First:
            def first(_self):
                return channel

        return _First()


def _user():
    return User(
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        is_active=True,
        role=UserRole.admin,
    )


def _db(user, channel=None):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result(user, channel))
    db.commit = AsyncMock()
    return db


def _request():
    """slowapi's @limiter.limit wrapper refuses to run without a Request.

    These tests call the handler directly instead of over HTTP, so hand it a
    bare scope with the limiter check pre-marked as done - the rate-limit
    budget itself is asserted in test_forgot_rate_limit.py.
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


def _reset_jwt():
    return jwt.encode(
        {
            "sub": "admin",
            "purpose": "reset",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


# 1. /api/auth/forgot must never return a reset token -------------------------


def test_forgot_does_not_return_reset_token_for_existing_user():
    db = _db(_user())
    req = ForgotPasswordRequest(username_or_email="admin")
    result = asyncio.run(forgot_password(_request(), req, db))
    assert isinstance(result, dict)
    assert "reset_token" not in result, "reset token leaked in response body"


def test_forgot_is_identical_for_unknown_user():
    """No user enumeration: unknown user must not 404 or differ in shape."""
    db = _db(user=None)
    req = ForgotPasswordRequest(username_or_email="nobody")
    result = asyncio.run(forgot_password(_request(), req, db))  # pre-fix: raises 404
    assert isinstance(result, dict)
    assert "reset_token" not in result
    known = asyncio.run(
        forgot_password(
            _request(), ForgotPasswordRequest(username_or_email="admin"), _db(_user())
        )
    )
    assert set(result.keys()) == set(known.keys()), "response differs by user existence"


# 2. Reset token must not act as an access token ------------------------------


def test_reset_token_rejected_by_get_current_user():
    token = _reset_jwt()

    async def _call():
        return await get_current_user(token=token, db=_db(_user()))

    with pytest.raises(HTTPException) as ei:
        asyncio.run(_call())
    assert ei.value.status_code == 401


def test_valid_access_token_still_accepted():
    token = create_access_token({"sub": "admin"})
    user = _user()

    async def _call():
        return await get_current_user(token=token, db=_db(user))

    assert asyncio.run(_call()) is user


# 3. Password reset revokes existing sessions --------------------------------
#    The reset contract is now OTP-based; the end-to-end reset test lives in
#    test_password_reset_otp.py (test_reset_with_valid_otp_sets_password_and_revokes
#    asserts revoke_all_user_tokens is awaited).


# 4. Token delivery: out-of-band, to the account's own address, off the request path
#    (OTP delivery + deferral: test_password_reset_otp.py)


def test_forgot_without_email_channel_still_ok_and_queues_nothing(monkeypatch):
    from fastapi import BackgroundTasks
    from api import notifications

    sender = AsyncMock()
    monkeypatch.setattr(notifications, "_send_notification", sender)

    db = _db(_user(), channel=None)
    bg = BackgroundTasks()
    result = asyncio.run(
        forgot_password(_request(), ForgotPasswordRequest(username_or_email="admin"), bg, db)
    )
    assert result == {"status": "ok"}
    assert bg.tasks == []
