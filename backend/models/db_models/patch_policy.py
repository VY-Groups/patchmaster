"""Structured patch policy (S4-1)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class PatchPolicy(Base):
    __tablename__ = "patch_policies"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    # target
    target_groups = Column(JSON, default=list)
    target_hosts = Column(JSON, default=list)
    exclusions = Column(JSON, default=list)
    target_os_family = Column(String(30), default="any")
    # patch filter
    patch_filter = Column(JSON, default=dict)  # severity, vendor, package, type, pmrs band
    # reboot behaviour
    reboot_behaviour = Column(String(30), default="if_required")  # never | if_required | always
    # approval
    approval_mode = Column(String(30), default="none")  # none | manual | multi
    # schedule
    schedule = Column(String(100), default="")
    retry_window_minutes = Column(Integer, default=60)
    # ring/gate set
    ring_set = Column(JSON, default=list)
    gate_set = Column(JSON, default=list)
    is_enabled = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)