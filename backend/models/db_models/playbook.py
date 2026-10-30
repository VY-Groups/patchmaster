"""Mitigation playbooks (S3-7)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, Boolean

from database import Base
from .hosts import _utcnow


class MitigationPlaybook(Base):
    __tablename__ = "mitigation_playbooks"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    version = Column(String(40), default="1.0")
    vulnerability_pattern = Column(String(200), default="")
    steps = Column(JSON, default=list)
    reversible = Column(Boolean, default=True)
    tested = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)