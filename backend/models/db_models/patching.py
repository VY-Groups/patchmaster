"""Patch jobs, schedules, runbooks, hooks, rollouts, agent updates and backups."""

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


class JobStatus(str, enum.Enum):
    pending = "pending"
    scheduled = "scheduled"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"
    rolled_back = "rolled_back"
    aborted = "aborted"


class PatchAction(str, enum.Enum):
    upgrade = "upgrade"
    install = "install"
    rollback = "rollback"
    snapshot = "snapshot"
    offline_install = "offline_install"
    server_patch = "server_patch"


# â”€â”€ Patch Jobs â”€â”€


class PatchJob(Base):
    __tablename__ = "patch_jobs"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    action = Column(Enum(PatchAction), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.pending)
    packages = Column(JSON, default=list)
    hold_packages = Column(JSON, default=list)
    dry_run = Column(Boolean, default=False)
    auto_snapshot = Column(Boolean, default=True)
    auto_rollback = Column(Boolean, default=True)
    result = Column(JSON, nullable=True)
    output = Column(Text, default="")
    initiated_by = Column(String(100), default="system")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    host = relationship("Host", back_populates="patch_jobs")

    __table_args__ = (Index("idx_jobs_created_status", "created_at", "status"),)


# â”€â”€ Patch Schedules â”€â”€


class PatchSchedule(Base):
    __tablename__ = "patch_schedules"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    group_id = Column(
        Integer, ForeignKey("host_groups.id", ondelete="SET NULL"), nullable=True
    )
    cron_expression = Column(String(100), nullable=False)  # e.g. "0 2 * * SAT"
    auto_snapshot = Column(Boolean, default=True)
    auto_rollback = Column(Boolean, default=True)
    auto_reboot = Column(Boolean, default=False)
    packages = Column(JSON, default=list)
    hold_packages = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    group = relationship("HostGroup", back_populates="schedules")


class RunbookProfile(Base):
    __tablename__ = "runbook_profiles"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    channel = Column(String(20), default="linux")
    config = Column(JSON, default=dict)
    require_approval = Column(Boolean, default=False)
    approval_role = Column(String(30), default="operator")
    is_active = Column(Boolean, default=True)
    created_by = Column(String(100), default="")
    updated_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class RunbookSchedule(Base):
    __tablename__ = "runbook_schedules"
    id = Column(Integer, primary_key=True)
    profile_id = Column(
        Integer,
        ForeignKey("runbook_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(150), nullable=False)
    cron_expression = Column(String(100), nullable=False, default="0 2 * * *")
    timezone = Column(String(50), default="UTC")
    is_active = Column(Boolean, default=True)
    approved_by = Column(String(100), default="")
    approved_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    profile = relationship("RunbookProfile", backref="schedules")


class RunbookExecution(Base):
    __tablename__ = "runbook_executions"
    id = Column(Integer, primary_key=True)
    profile_id = Column(
        Integer,
        ForeignKey("runbook_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    schedule_id = Column(
        Integer,
        ForeignKey("runbook_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_type = Column(String(30), default="manual")
    status = Column(String(30), default="pending", index=True)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)
    initiated_by = Column(String(100), default="")
    summary = Column(JSON, default=dict)
    logs = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    profile = relationship("RunbookProfile", backref="executions")
    schedule = relationship("RunbookSchedule", backref="executions")


# â”€â”€ Backups â”€â”€


class BackupType(str, enum.Enum):
    database = "database"
    file = "file"
    vm = "vm"
    live = "live"
    full_system = "full_system"


class BackupConfig(Base):
    __tablename__ = "backup_configs"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(100), nullable=False)
    backup_type = Column(Enum(BackupType), nullable=False)

    source_path = Column(String(255), nullable=True)
    db_type = Column(String(50), nullable=True)
    schedule = Column(String(50), nullable=True)
    retention_count = Column(Integer, default=5)
    compression_level = Column(Integer, default=6)
    encryption_key = Column(String(255), nullable=True)  # If set, backup is encrypted
    storage_path = Column(String(255), nullable=True)  # Remote path (s3://, scp://)
    storage_type = Column(String(50), default="local")  # local, s3, sftp, nfs, minio
    storage_config = Column(JSON, default=dict)  # provider-specific settings
    last_test_status = Column(String(50), default="")
    last_test_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(50), default="")
    last_run_size = Column(Integer, default=0)
    last_run_duration = Column(Float, default=0.0)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    host = relationship("Host", backref="backup_configs")


class BackupLog(Base):
    __tablename__ = "backup_logs"
    id = Column(Integer, primary_key=True)
    config_id = Column(
        Integer, ForeignKey("backup_configs.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(Enum(JobStatus), default=JobStatus.pending)
    output = Column(Text, nullable=True)
    file_size_bytes = Column(Integer, default=0)
    duration_seconds = Column(Float, default=0.0)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    config = relationship("BackupConfig", backref="logs")

    __table_args__ = (
        Index("ix_backup_logs_config_id", "config_id"),
        Index("ix_backup_logs_started_at", "started_at"),
    )


class RestoreDrillRun(Base):
    __tablename__ = "restore_drill_runs"
    id = Column(Integer, primary_key=True)
    config_id = Column(
        Integer,
        ForeignKey("backup_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    backup_log_id = Column(
        Integer,
        ForeignKey("backup_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(Enum(JobStatus), default=JobStatus.pending, index=True)
    requested_by = Column(String(100), default="")
    target_path = Column(String(255), default="")
    target_rto_minutes = Column(Float, nullable=True)
    target_rpo_minutes = Column(Float, nullable=True)
    actual_rto_seconds = Column(Float, nullable=True)
    actual_rpo_minutes = Column(Float, nullable=True)
    within_sla = Column(Boolean, nullable=True, index=True)
    summary = Column(JSON, default=dict)
    queue_job_id = Column(String(64), default="", index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    config = relationship("BackupConfig", backref="restore_drills")
    host = relationship("Host", backref="restore_drills")
    backup_log = relationship("BackupLog")

    __table_args__ = (
        Index("ix_restore_drill_config_created", "config_id", "created_at"),
        Index("ix_restore_drill_status_created", "status", "created_at"),
    )


class RingRolloutStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    canceled = "canceled"
    held = "held"
    rolled_back = "rolled_back"


class RingRolloutPolicy(Base):
    __tablename__ = "ring_rollout_policies"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    target_os_family = Column(String(30), default="linux", index=True)
    is_enabled = Column(Boolean, default=True, index=True)
    rings = Column(JSON, default=list)
    guardrails = Column(JSON, default=dict)
    rollout_config = Column(JSON, default=dict)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    runs = relationship(
        "RingRolloutRun", back_populates="policy", cascade="all, delete-orphan"
    )


class RingRolloutRun(Base):
    __tablename__ = "ring_rollout_runs"
    id = Column(Integer, primary_key=True)
    policy_id = Column(
        Integer,
        ForeignKey("ring_rollout_policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(
        Enum(RingRolloutStatus), default=RingRolloutStatus.pending, index=True
    )
    action = Column(Enum(PatchAction), default=PatchAction.upgrade)
    dry_run = Column(Boolean, default=False)
    requested_by = Column(String(100), default="")
    request_payload = Column(JSON, default=dict)
    summary = Column(JSON, default=dict)
    queue_job_id = Column(String(64), default="", index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    policy = relationship("RingRolloutPolicy", back_populates="runs")

    __table_args__ = (
        Index("ix_ring_rollout_runs_policy_created", "policy_id", "created_at"),
    )


# â”€â”€ Maintenance Windows â”€â”€


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    # cron-style: day_of_week (0=Mon..6=Sun), start_hour, end_hour, timezone
    day_of_week = Column(JSON, default=list)  # e.g. [5, 6] = Sat+Sun
    start_hour = Column(Integer, default=2)  # 2 AM
    end_hour = Column(Integer, default=6)  # 6 AM
    timezone = Column(String(50), default="UTC")
    applies_to_groups = Column(JSON, default=list)  # list of group IDs
    applies_to_hosts = Column(JSON, default=list)  # list of host IDs
    is_active = Column(Boolean, default=True)
    block_outside = Column(Boolean, default=True)  # block patches outside window
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)


# â”€â”€ Pre/Post Patch Hooks â”€â”€


class HookTrigger(str, enum.Enum):
    pre_patch = "pre_patch"
    post_patch = "post_patch"
    pre_snapshot = "pre_snapshot"
    post_snapshot = "post_snapshot"
    on_failure = "on_failure"
    on_success = "on_success"


class PatchHook(Base):
    __tablename__ = "patch_hooks"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    trigger = Column(Enum(HookTrigger), nullable=False)
    script_type = Column(String(20), default="bash")  # bash | powershell | python
    script_content = Column(Text, nullable=False)
    timeout_seconds = Column(Integer, default=120)
    applies_to_groups = Column(JSON, default=list)
    applies_to_hosts = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    stop_on_failure = Column(Boolean, default=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)


class HookExecution(Base):
    __tablename__ = "hook_executions"
    id = Column(Integer, primary_key=True)
    hook_id = Column(
        Integer, ForeignKey("patch_hooks.id", ondelete="CASCADE"), nullable=False
    )
    job_id = Column(
        Integer, ForeignKey("patch_jobs.id", ondelete="CASCADE"), nullable=True
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    trigger = Column(Enum(HookTrigger), nullable=False)
    status = Column(
        String(20), default="pending"
    )  # pending | success | failed | skipped
    output = Column(Text, default="")
    exit_code = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    hook = relationship("PatchHook", backref="executions")


# â”€â”€ Bulk Patch Jobs â”€â”€


class BulkPatchJob(Base):
    __tablename__ = "bulk_patch_jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    host_ids = Column(JSON, default=list)
    packages = Column(JSON, default=list)
    action = Column(Enum(PatchAction), default=PatchAction.server_patch)
    dry_run = Column(Boolean, default=False)
    auto_snapshot = Column(Boolean, default=True)
    auto_rollback = Column(Boolean, default=True)
    status = Column(
        String(20), default="pending"
    )  # pending | running | jobs_created | failed
    total_hosts = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    job_ids = Column(JSON, default=list)  # list of PatchJob IDs created
    initiated_by = Column(String(100), default="system")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # BUG-014 FIX: Globally unique bulk job names
    # Changed from (name, created_at) to just (name) to prevent duplicates
    __table_args__ = (
        UniqueConstraint("name", name="uq_bulk_patch_job_name"),
        Index("ix_bulk_patch_jobs_status", "status"),
        Index("ix_bulk_patch_jobs_created_at", "created_at"),
    )


# â”€â”€ Agent Updates â”€â”€


class AgentUpdateChannel(str, enum.Enum):
    stable = "stable"
    beta = "beta"


class AgentUpdatePolicy(Base):
    __tablename__ = "agent_update_policies"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, default="Default")
    channel = Column(Enum(AgentUpdateChannel), default=AgentUpdateChannel.stable)
    auto_update = Column(Boolean, default=False)
    target_version = Column(String(20), nullable=True)  # None = latest
    applies_to_groups = Column(JSON, default=list)
    applies_to_hosts = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class SoftwareCatalogItem(Base):
    __tablename__ = "software_catalog_items"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, index=True)
    package_name = Column(String(200), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    supported_platforms = Column(JSON, default=list)
    allowed_actions = Column(JSON, default=list)
    default_execution_mode = Column(String(20), default="immediate")
    is_enabled = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    requests = relationship("SoftwareKioskRequest", back_populates="catalog_item")


class SoftwareKioskRequest(Base):
    __tablename__ = "software_kiosk_requests"
    id = Column(Integer, primary_key=True)
    catalog_item_id = Column(
        Integer,
        ForeignKey("software_catalog_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approved_by_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requested_action = Column(String(20), nullable=False, default="install")
    execution_mode = Column(String(20), nullable=False, default="immediate")
    note = Column(Text, default="")
    status = Column(String(24), default="submitted", index=True)
    status_message = Column(Text, default="")
    fulfilled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    catalog_item = relationship("SoftwareCatalogItem", back_populates="requests")
    host = relationship("Host")
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
