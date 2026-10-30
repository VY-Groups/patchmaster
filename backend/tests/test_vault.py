"""S2-1 Credential Vault tests."""

import asyncio
import os

import pytest

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
os.environ["PM_MASTER_KEY"] = "test-master-key"

from vault import CredentialVault, EnvMasterKeyProvider, CredentialType


def _run(coro):
    return asyncio.run(coro)


def test_roundtrip_encrypt_decrypt():
    v = CredentialVault()
    wrapped, ct = v.encrypt("secret-value")
    assert v.decrypt(wrapped, ct) == "secret-value"


def test_different_keys_fail():
    v1 = CredentialVault(EnvMasterKeyProvider(master_key="key-a"))
    v2 = CredentialVault(EnvMasterKeyProvider(master_key="key-b"))
    wrapped, ct = v1.encrypt("x")
    try:
        v2.decrypt(wrapped, ct)
        assert False, "expected failure"
    except Exception:
        pass


def test_store_and_retrieve_scope():
    async def main():
        from unittest.mock import AsyncMock, MagicMock
        session = AsyncMock()
        session.add = lambda x: None
        session.flush = AsyncMock()
        # store
        v = CredentialVault()
        cred = await v.store(session, "db", "ssh_password", scope="host", scope_id="h1", value="pw")
        assert cred.name == "db"
        # retrieve: mock session.execute to return the cred
        res = MagicMock()
        res.scalars.return_value.all.return_value = [cred]
        session.execute.return_value = res
        got = await v.retrieve(session, "ssh_password", scope="host", scope_id="h1")
        assert got == "pw"
    _run(main())


def test_test_credential_empty():
    v = CredentialVault()
    assert v.test_credential("ssh_password", "")["ok"] is False
    assert v.test_credential("ssh_password", "x")["ok"] is True