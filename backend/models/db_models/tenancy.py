"""Tenant-wide records: the audit log and its tamper-proof hash chain."""

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


# â”€â”€ Audit Logs â”€â”€


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)  # host, job, settings
    target_id = Column(String(50), nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="audit_logs")


class AuditLogIntegrity(Base):
    """Extended audit log table for tamper-proof logging."""

    __tablename__ = "audit_log_integrity"

    id = Column(Integer, primary_key=True)
    log_id = Column(Integer, nullable=False, index=True)
    previous_hash = Column(String(64), nullable=False)
    current_hash = Column(String(64), nullable=False)
    signature = Column(Text, nullable=True)  # Optional HMAC signature
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
