"""S0-1 change set B: JWT_SECRET fail-closed (plan.md Stage 0, work package S0-1).

Defects (line-verified 2026-10-25):
1. backend/auth.py:20 defaulted JWT_SECRET to a value committed in the repo
   -> anyone who deploys without setting JWT_SECRET can forge access tokens.
2. packaging/env.example:25 ships a fixed 64-hex JWT_SECRET that the installer
   copies to .env (install-bare.sh:673) and is_placeholder_secret does not
   catch (no case pattern matches hex) -> identical secret across installs.
3. docker-compose.yml:26 defaults to "change-me-to-a-secure-random-string",
   which misses install-bare.sh's exact-match "change-me" pattern.

Tests are written first and must FAIL against the pre-fix code (plan.md 15.1.4).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))

import auth  # noqa: E402

# Every secret that has ever shipped as a default must be rejected.
KNOWN_BAD = [
    "patchmaster-change-me-in-production-32chars!",  # auth.py:20 old default
    "change-me-to-a-secure-random-string",           # docker-compose.yml:26 old default
    "5e91c5c9d0b5494f8c2a4c0c8f9f5a9d6b8f184f3e30e0c9e225a34a8c9f0f5b",  # env.example:25
    "changeme-whatever",
    "change-me",
    "short",
]


@pytest.mark.parametrize("secret", KNOWN_BAD)
def test_known_bad_secrets_rejected(monkeypatch, secret):
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth._load_jwt_secret()


def test_missing_jwt_secret_rejected(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth._load_jwt_secret()


def test_strong_secret_accepted(monkeypatch):
    good = "a" * 63 + "b"
    monkeypatch.setenv("JWT_SECRET", good)
    assert auth._load_jwt_secret() == good


def test_module_constant_is_not_a_placeholder():
    # With conftest supplying a test secret, the imported module must expose it,
    # never one of the shipped defaults.
    assert auth.SECRET_KEY not in KNOWN_BAD
    assert len(auth.SECRET_KEY) >= 32


def test_auth_source_has_no_hardcoded_secret_default():
    """S0-1: auth.py's _derive_fernet_key defaulted PM_SECRET_KEY to a committed
    literal (dead code, zero callers). The literal must never return to source."""
    source = (BACKEND / "auth.py").read_text(encoding="utf-8")
    assert "ZGV2LW9ubHktZmVybmV0LWtleS1kb25vdC11c2UtaW4tcHJvZA==" not in source
    assert "_derive_fernet_key" not in source


def test_import_fails_closed_without_jwt_secret():
    """End-to-end: a process started with no JWT_SECRET must refuse to boot."""
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
    proc = subprocess.run(
        [sys.executable, "-c", "import auth"],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0, "auth imported with no JWT_SECRET (fail-open)"
    assert "JWT_SECRET" in (proc.stderr + proc.stdout)
