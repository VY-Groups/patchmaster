"""Credential Vault models (S2-1)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, Index
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class Credential(Base):
    __tablename__ = "credentials"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, index=True)
    credential_type = Column(String(40), nullable=False, index=True)
    scope = Column(String(20), nullable=False, default="global", index=True)
    scope_id = Column(String(64), nullable=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    # envelope encryption: DEK wrapped by master key, secret encrypted by DEK
    wrapped_dek = Column(Text, nullable=False)
    ciphertext = Column(Text, nullable=False)
    metadata_json = Column(JSON, default=dict)
    expires_at = Column(DateTime, nullable=True)
    rotated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # (index intentionally omitted to keep migrations idempotent; see 20261026_0005)