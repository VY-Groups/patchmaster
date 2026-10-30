"""Compliance controls and findings (S5)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class ComplianceControl(Base):
    __tablename__ = "compliance_controls"
    id = Column(Integer, primary_key=True)
    control_id = Column(String(64), nullable=False, unique=True, index=True)
    title = Column(String(200), default="")
    framework = Column(String(60), default="")
    severity = Column(String(20), default="medium")
    automated_check = Column(String(200), default="")
    remediation_hint = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)


class ComplianceFinding(Base):
    __tablename__ = "compliance_findings"
    id = Column(Integer, primary_key=True)
    control_id = Column(String(64), nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(String(20), default="open")  # open | mitigated | fixed | accepted | false_positive
    evidence = Column(JSON, default=dict)
    remediation = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)