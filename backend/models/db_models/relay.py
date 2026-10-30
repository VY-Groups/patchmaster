"""Relay + network model (S2-5, S2-6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, JSON, Index, Boolean
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class Site(Base):
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    route = Column(String(40), default="direct")  # direct | via_relay
    relay_id = Column(Integer, ForeignKey("relays.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Network(Base):
    __tablename__ = "networks"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=True)
    cidr = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Relay(Base):
    __tablename__ = "relays"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True)
    mode = Column(String(20), default="jump")  # jump | distribution
    bandwidth_cap_mbps = Column(Integer, nullable=True)
    cache_quota_gb = Column(Integer, nullable=True)
    status = Column(String(20), default="registered")
    enrolled_at = Column(DateTime, default=_utcnow)
    last_seen = Column(DateTime, nullable=True)