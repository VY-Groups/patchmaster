"""First-run SMTP bootstrap (installer-driven, mirrors bootstrap_users.py).

Owner requirement: SMTP must be configured at tool setup time (first run), so
password-reset OTPs are deliverable from the very first login. Config comes
from PM_SMTP_* environment variables (filled by the installer / .env) and the
stored channel config must be encrypted at rest.

Tests are written first and must FAIL against pre-change code (plan.md 15.1.4):
bootstrap_smtp.py does not exist yet.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import bootstrap_smtp  # noqa: E402
from api.cicd_secrets import decrypt_json_field  # noqa: E402

SMTP_PASS = "s3cret-smtp-pass-123"


class FakeSession:
    def __init__(self, email_channels=0):
        self.email_channels = email_channels
        self.added = []
        self.committed = False

    async def scalar(self, _query):
        return self.email_channels

    def add(self, channel):
        self.added.append(channel)

    async def commit(self):
        self.committed = True


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _patch(monkeypatch, session, **env):
    monkeypatch.setattr(bootstrap_smtp, "async_session", lambda: FakeSessionFactory(session))
    for name in ("PM_SMTP_HOST", "PM_SMTP_PORT", "PM_SMTP_USERNAME",
                 "PM_SMTP_PASSWORD", "PM_SMTP_TO", "PM_SMTP_FROM", "PM_SMTP_USE_TLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PM_SECRET_KEY", "unit-test-key-for-fernet-derivation")
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _env_set(monkeypatch):
    return dict(
        PM_SMTP_HOST="smtp.example.test",
        PM_SMTP_PORT="587",
        PM_SMTP_USERNAME="otp@example.test",
        PM_SMTP_PASSWORD=SMTP_PASS,
        PM_SMTP_TO="otp@example.test",
    )


# 1. env present, no email channel yet -> one enabled, encrypted channel ─────


def test_smtp_bootstrap_creates_encrypted_email_channel(monkeypatch):
    session = FakeSession(email_channels=0)
    _patch(monkeypatch, session, **_env_set(monkeypatch))

    result = asyncio.run(bootstrap_smtp.ensure_bootstrap_smtp_channel())

    assert result["created"] is True, f"expected creation, got {result}"
    assert session.committed is True
    assert len(session.added) == 1, "exactly one channel must be created"

    channel = session.added[0]
    assert channel.channel_type == "email"
    assert channel.is_enabled is True
    assert SMTP_PASS not in str(channel.config), "SMTP password stored in plaintext"

    cfg = decrypt_json_field(channel.config)
    assert cfg["smtp_host"] == "smtp.example.test"
    assert cfg["smtp_port"] == 587
    assert cfg["password"] == SMTP_PASS, "config must survive the round trip"


def test_smtp_bootstrap_defaults_to_starttls_587(monkeypatch):
    """Zoho-style SMTP: port 587 + STARTTLS is what _send_notification expects
    (use_tls=True path); port 465 would need SMTP_SSL, which it does not do."""
    session = FakeSession(email_channels=0)
    env = _env_set(monkeypatch)
    del env["PM_SMTP_PORT"]
    _patch(monkeypatch, session, **env)

    asyncio.run(bootstrap_smtp.ensure_bootstrap_smtp_channel())

    cfg = decrypt_json_field(session.added[0].config)
    assert cfg["smtp_port"] == 587
    assert cfg["use_tls"] is True


# 2. not configured -> clean no-op (same contract as bootstrap_users) ────────


def test_smtp_bootstrap_noop_without_env(monkeypatch):
    session = FakeSession(email_channels=0)
    _patch(monkeypatch, session)  # no PM_SMTP_HOST

    result = asyncio.run(bootstrap_smtp.ensure_bootstrap_smtp_channel())

    assert result["created"] is False
    assert result["reason"] == "missing_smtp_config"
    assert session.added == []
    assert session.committed is False


# 3. an email channel already exists -> never clobber operator config ────────


def test_smtp_bootstrap_skips_when_email_channel_exists(monkeypatch):
    session = FakeSession(email_channels=1)
    _patch(monkeypatch, session, **_env_set(monkeypatch))

    result = asyncio.run(bootstrap_smtp.ensure_bootstrap_smtp_channel())

    assert result["created"] is False
    assert result["reason"] == "email_channel_exists"
    assert session.added == []
    assert session.committed is False
