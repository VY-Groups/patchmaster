"""CVE data, host vulnerability state, remediation workflow and patch SLAs."""

import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Enum,
    Table,
    JSON,
    UniqueConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.orm import relationship
from database import Base
from .hosts import _utcnow


class Severity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    negligible = "negligible"


# â”€â”€ CVEs â”€â”€


class CVE(Base):
    __tablename__ = "cves"
    id = Column(String(50), primary_key=True)
    description = Column(Text, default="")
    severity = Column(Enum(Severity), default=Severity.medium)
    cvss_score = Column(Float, default=0.0)
    published_date = Column(DateTime, nullable=True)
    cwe_id = Column(String(50), default="")
    references = Column(Text, default="")
    affected_products = Column(Text, default="")
    source = Column(String(50), default="manual")

    host_cves = relationship("HostCVE", back_populates="cve")


class HostCVE(Base):
    __tablename__ = "host_cves"
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), primary_key=True
    )
    cve_id = Column(
        String(50), ForeignKey("cves.id", ondelete="CASCADE"), primary_key=True
    )
    package_name = Column(String(100), nullable=True, default="")
    current_version = Column(String(50), nullable=True, default="")
    fixed_version = Column(String(50), nullable=True)
    status = Column(String(20), default="active")  # active, patched, ignored
    detected_at = Column(DateTime, default=_utcnow)

    host = relationship("Host", back_populates="host_cves")
    cve = relationship("CVE", back_populates="host_cves")


# ── Patch SLA ──


class PatchSLA(Base):
    __tablename__ = "patch_slas"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    severity = Column(Enum(Severity), nullable=False)
    days_to_patch = Column(Integer, nullable=False, default=7)  # SLA window in days
    notify_before_days = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)


class SLAViolation(Base):
    __tablename__ = "sla_violations"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    cve_id = Column(
        String(50), ForeignKey("cves.id", ondelete="CASCADE"), nullable=False
    )
    sla_id = Column(
        Integer, ForeignKey("patch_slas.id", ondelete="SET NULL"), nullable=True
    )
    detected_at = Column(DateTime, default=_utcnow)
    deadline = Column(DateTime, nullable=False)
    patched_at = Column(DateTime, nullable=True)
    is_violated = Column(Boolean, default=False)
    is_resolved = Column(Boolean, default=False)

    host = relationship("Host", backref="sla_violations")
    cve = relationship("CVE", backref="sla_violations")


# â”€â”€ CVE Remediation Workflow â”€â”€


class RemediationStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    accepted_risk = "accepted_risk"
    false_positive = "false_positive"


class CVERemediation(Base):
    __tablename__ = "cve_remediations"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    cve_id = Column(
        String(50), ForeignKey("cves.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(Enum(RemediationStatus), default=RemediationStatus.open)
    assigned_to = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes = Column(Text, default="")
    due_date = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    host = relationship("Host", backref="remediations")
    cve = relationship("CVE", backref="remediations")
    assignee = relationship(
        "User", backref="assigned_remediations", foreign_keys=[assigned_to]
    )

    __table_args__ = (
        UniqueConstraint("host_id", "cve_id", name="uq_remediation_host_cve"),
        Index("ix_remediations_status", "status"),
    )
