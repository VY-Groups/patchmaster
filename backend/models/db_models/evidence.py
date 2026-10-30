"""Evidence Ledger models (S1-5)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON, Index
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"
    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), nullable=True, index=True)
    tenant_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    bundle_hash = Column(String(64), nullable=False)
    previous_bundle_hash = Column(String(64), nullable=True)
    signature = Column(Text, nullable=True)
    signer_key_id = Column(String(100), nullable=True)
    storage_ref = Column(String(500), nullable=True)
    item_count = Column(Integer, default=0)

    items = relationship("EvidenceItem", back_populates="bundle", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_evidence_bundles_job_created", "job_id", "created_at"),
    )


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id = Column(Integer, primary_key=True)
    bundle_id = Column(Integer, ForeignKey("evidence_bundles.id", ondelete="CASCADE"), nullable=False, index=True)
    step = Column(String(100), nullable=False)
    kind = Column(String(100), nullable=False)
    payload_ref = Column(String(500), nullable=True)
    payload_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    bundle = relationship("EvidenceBundle", back_populates="items")