"""Topology / service graph (S6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, JSON, ForeignKey
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class ServiceNode(Base):
    __tablename__ = "service_nodes"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True)
    service_type = Column(String(60), default="")
    tolerance = Column(Integer, default=1)  # how many members can be down
    created_at = Column(DateTime, default=_utcnow)


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("service_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    depends_on_id = Column(Integer, ForeignKey("service_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)