"""Normalized vulnerability intelligence model (S3-1)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, JSON, Index, ForeignKey
from sqlalchemy.orm import relationship

from database import Base
from .hosts import _utcnow


class VulnSource(Base):
    __tablename__ = "vuln_sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True, index=True)
    kind = Column(String(40), default="feed")
    last_sync = Column(DateTime, nullable=True)
    record_count = Column(Integer, default=0)
    status = Column(String(20), default="idle")
    created_at = Column(DateTime, default=_utcnow)


class Vulnerability(Base):
    __tablename__ = "vulnerabilities"
    id = Column(Integer, primary_key=True)
    cve_id = Column(String(32), nullable=False, unique=True, index=True)
    title = Column(String(300), default="")
    summary = Column(Text, default="")
    cvss_score = Column(Float, nullable=True)
    cvss_vector = Column(String(120), default="")
    cwe = Column(String(40), default="")
    published_at = Column(DateTime, nullable=True)
    modified_at = Column(DateTime, nullable=True)
    references = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class VulnAffected(Base):
    __tablename__ = "vuln_affected"
    id = Column(Integer, primary_key=True)
    vulnerability_id = Column(Integer, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), nullable=False, index=True)
    ecosystem = Column(String(40), nullable=False, index=True)
    product = Column(String(150), nullable=False, index=True)
    version_range = Column(String(200), default="")
    fixed_version = Column(String(80), default="")
    source = Column(String(80), default="")
    created_at = Column(DateTime, default=_utcnow)


class ExploitSignal(Base):
    __tablename__ = "exploit_signals"
    id = Column(Integer, primary_key=True)
    vulnerability_id = Column(Integer, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), nullable=False, index=True)
    exploit_likelihood = Column(Float, nullable=True)
    known_exploited = Column(String(10), default="false")
    source = Column(String(80), default="")
    as_of = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class VulnPatchMap(Base):
    __tablename__ = "vuln_patch_map"
    id = Column(Integer, primary_key=True)
    vulnerability_id = Column(Integer, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), nullable=False, index=True)
    patch_id = Column(String(100), nullable=True)
    package_version = Column(String(80), default="")
    created_at = Column(DateTime, default=_utcnow)