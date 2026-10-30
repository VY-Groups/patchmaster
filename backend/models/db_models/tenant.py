"""Tenant / organization model (SaaS)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, JSON, Boolean

from database import Base
from .hosts import _utcnow


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    slug = Column(String(80), nullable=False, unique=True, index=True)
    plan = Column(String(40), default="standard")
    is_root = Column(Boolean, default=False)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)