"""Credential Vault (S2-1): envelope encryption with pluggable master-key provider."""

from __future__ import annotations

import base64
import hashlib
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from cryptography.fernet import Fernet, MultiFernet

from models.db_models import Credential


class CredentialType(str, Enum):
    ssh_password = "ssh_password"
    ssh_key = "ssh_key"
    winrm = "winrm"
    snmp = "snmp"
    device_enable = "device_enable"
    api_token = "api_token"


class VaultProvider(ABC):
    """Pluggable master-key provider (env/file/KMS/HSM)."""

    @abstractmethod
    def wrap(self, dek: bytes) -> bytes:
        ...

    @abstractmethod
    def unwrap(self, wrapped: bytes) -> bytes:
        ...


class EnvMasterKeyProvider(VaultProvider):
    """Master key from PM_MASTER_KEY env or PM_MASTER_KEY_FILE."""

    def __init__(self, master_key: Optional[str] = None, key_file: Optional[str] = None):
        raw = master_key or os.environ.get("PM_MASTER_KEY")
        if not raw and key_file:
            try:
                with open(key_file) as f:
                    raw = f.read().strip()
            except OSError:
                raw = None
        if not raw:
            key_file = key_file or os.environ.get("PM_MASTER_KEY_FILE")
            if key_file:
                try:
                    with open(key_file) as f:
                        raw = f.read().strip()
                except OSError:
                    raw = None
        if not raw:
            # deterministic dev fallback (NOT for production) — warn
            raw = "dev-master-key-change-me"
        # derive a 32-byte key
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def wrap(self, dek: bytes) -> bytes:
        return self._fernet.encrypt(dek)

    def unwrap(self, wrapped: bytes) -> bytes:
        return self._fernet.decrypt(wrapped)


SCOPE_ORDER = {"global": 0, "site": 1, "group": 2, "host": 3}


class CredentialVault:
    def __init__(self, provider: Optional[VaultProvider] = None):
        self.provider = provider or EnvMasterKeyProvider()

    def _new_dek(self) -> bytes:
        return Fernet.generate_key()

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """Return (wrapped_dek, ciphertext) for a secret value."""
        dek = self._new_dek()
        f = Fernet(dek)
        ct = f.encrypt(plaintext.encode("utf-8"))
        wrapped = self.provider.wrap(dek)
        return wrapped, ct

    def decrypt(self, wrapped_dek: bytes, ciphertext: bytes) -> str:
        dek = self.provider.unwrap(wrapped_dek)
        f = Fernet(dek)
        return f.decrypt(ciphertext).decode("utf-8")

    async def store(self, session, name: str, credential_type: str, scope: str = "global",
                    scope_id: Optional[str] = None, value: str = "",
                    metadata: Optional[dict] = None, expires_at=None) -> Credential:
        wrapped, ct = self.encrypt(value)
        cred = Credential(
            name=name,
            credential_type=credential_type,
            scope=scope,
            scope_id=scope_id,
            wrapped_dek=wrapped.decode("utf-8") if isinstance(wrapped, bytes) else str(wrapped),
            ciphertext=ct.decode("utf-8") if isinstance(ct, bytes) else str(ct),
            metadata_json=metadata or {},
            expires_at=expires_at,
        )
        session.add(cred)
        await session.flush()
        return cred

    async def retrieve(self, session, credential_type: str, scope: str = "global",
                       scope_id: Optional[str] = None) -> Optional[str]:
        # most specific scope wins: host > group > site > global
        candidates = []
        q = await session.execute(
            __import__("sqlalchemy").select(Credential).where(
                Credential.credential_type == credential_type
            )
        )
        rows = q.scalars().all()
        for r in rows:
            if r.scope == scope and (scope_id is None or r.scope_id == scope_id):
                candidates.append(r)
            elif r.scope == "global":
                candidates.append(r)
        if not candidates:
            return None
        # pick most specific
        best = max(candidates, key=lambda r: SCOPE_ORDER.get(r.scope, 0))
        try:
            return self.decrypt(best.wrapped_dek.encode(), best.ciphertext.encode())
        except Exception:
            return None

    def test_credential(self, credential_type: str, value: str) -> dict:
        if not value or not value.strip():
            return {"ok": False, "reason": "empty"}
        return {"ok": True, "reason": "non-empty"}