"""Package mirror repositories, sync runs and the package index."""

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


# â”€â”€ Mirror Repositories â”€â”€


class MirrorRepoProvider(str, enum.Enum):
    microsoft = "microsoft"
    ubuntu = "ubuntu"
    redhat = "redhat"
    custom = "custom"


class MirrorSyncStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class MirrorRepo(Base):
    __tablename__ = "mirror_repos"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    provider = Column(
        Enum(MirrorRepoProvider), default=MirrorRepoProvider.custom, nullable=False
    )
    os_family = Column(String(20), default="linux")  # linux | windows
    channel = Column(String(100), default="default")
    source_url = Column(String(500), default="")
    enabled = Column(Boolean, default=True)
    metadata_only = Column(Boolean, default=True)
    sync_interval_minutes = Column(Integer, default=360)
    retention_days = Column(Integer, default=30)
    keep_versions = Column(Integer, default=2)
    mirror_path = Column(String(500), default="")
    auth_config = Column(JSON, default=dict)
    extra_config = Column(JSON, default=dict)
    last_sync_at = Column(DateTime, nullable=True)
    next_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(Enum(MirrorSyncStatus), default=MirrorSyncStatus.pending)
    last_sync_summary = Column(JSON, default=dict)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    sync_runs = relationship(
        "MirrorSyncRun", back_populates="repo", cascade="all, delete-orphan"
    )
    package_index = relationship(
        "MirrorPackageIndex", back_populates="repo", cascade="all, delete-orphan"
    )
    sync_lease = relationship(
        "MirrorSyncLease",
        back_populates="repo",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_mirror_repos_enabled_next_sync", "enabled", "next_sync_at"),
    )


class MirrorSyncRun(Base):
    __tablename__ = "mirror_sync_runs"
    id = Column(Integer, primary_key=True)
    repo_id = Column(
        Integer,
        ForeignKey("mirror_repos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_type = Column(String(30), default="manual")  # manual | scheduler
    status = Column(Enum(MirrorSyncStatus), default=MirrorSyncStatus.pending)
    summary = Column(JSON, default=dict)
    error = Column(Text, default="")
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    repo = relationship("MirrorRepo", back_populates="sync_runs")

    __table_args__ = (
        Index("ix_mirror_sync_runs_repo_started", "repo_id", "started_at"),
    )


class MirrorSyncLease(Base):
    __tablename__ = "mirror_sync_leases"
    id = Column(Integer, primary_key=True)
    repo_id = Column(
        Integer,
        ForeignKey("mirror_repos.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    holder_id = Column(String(100), nullable=False, default="")
    holder_node = Column(String(255), nullable=False, default="")
    heartbeat_at = Column(DateTime, default=_utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    repo = relationship("MirrorRepo", back_populates="sync_lease")


class MirrorPackageIndex(Base):
    __tablename__ = "mirror_package_index"
    id = Column(Integer, primary_key=True)
    repo_id = Column(
        Integer,
        ForeignKey("mirror_repos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    package_name = Column(String(255), nullable=False)
    package_version = Column(String(255), nullable=False)
    os_family = Column(String(20), default="linux")
    channel = Column(String(100), default="default")
    architecture = Column(String(50), default="")
    source_url = Column(String(1000), default="")
    file_name = Column(String(255), default="")
    checksum = Column(String(255), default="")
    package_meta = Column("metadata", JSON, default=dict)
    discovered_at = Column(DateTime, default=_utcnow)
    last_seen_at = Column(DateTime, default=_utcnow)

    repo = relationship("MirrorRepo", back_populates="package_index")

    __table_args__ = (
        UniqueConstraint(
            "repo_id",
            "package_name",
            "package_version",
            "architecture",
            name="uq_mirror_pkg_repo_name_ver_arch",
        ),
        Index("ix_mirror_pkg_repo_name", "repo_id", "package_name"),
        Index("ix_mirror_pkg_last_seen", "last_seen_at"),
    )
