"""Users, RBAC, notifications, alerts, policies, admin tasks and plugin integrations."""

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


# â”€â”€ Enums â”€â”€


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"
    auditor = "auditor"


# -- Users --


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(200), default="")
    role = Column(Enum(UserRole), default=UserRole.viewer, nullable=False)
    is_active = Column(Boolean, default=True)
    custom_permissions = Column(JSON, nullable=True)  # per-user feature overrides
    # Brute-force lockout tracking
    login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    audit_logs = relationship("AuditLog", back_populates="user")
    notifications = relationship("UserNotification", back_populates="user")
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """Server-side refresh token store for JWT rotation and revocation."""

    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(
        String(64), unique=True, nullable=False, index=True
    )  # SHA-256 hex
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    ip_address = Column(String(45), default="")  # IPv4 or IPv6
    user_agent = Column(String(512), default="")
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="refresh_tokens")


class PasswordResetOTP(Base):
    """Single-use, expiring password-reset OTP (hashed at rest).

    One live row per user: issuing a new code drops the previous one.
    """

    __tablename__ = "password_reset_otps"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash = Column(String(255), nullable=False)  # pbkdf2-sha256, never plaintext
    attempts = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")


class PatchHistoryPreset(Base):
    __tablename__ = "patch_history_presets"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, index=True)
    scope_type = Column(
        String(20), default="user", nullable=False, index=True
    )  # user | role | global
    role = Column(String(20), nullable=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filters = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# -- Notifications --


class UserNotification(Base):
    __tablename__ = "user_notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )  # Null = System wide
    type = Column(String(50), nullable=False)  # update, job, alert
    title = Column(String(200), nullable=False)
    message = Column(Text, default="")
    link = Column(String(255), nullable=True)  # Frontend route or API link
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="notifications")


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    channel_type = Column(String(50), nullable=False)  # email, slack, webhook, telegram
    config = Column(JSON, default=dict)
    events = Column(JSON, default=list)
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class AlertActionType(str, enum.Enum):
    acknowledge = "acknowledge"
    snooze = "snooze"
    unsnooze = "unsnooze"
    ticket_create = "ticket_create"
    notify = "notify"


class AlertTicketStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class AlertAction(Base):
    __tablename__ = "alert_actions"
    id = Column(Integer, primary_key=True)
    alert_key = Column(String(255), nullable=False, index=True)
    alert_name = Column(String(120), nullable=False, index=True)
    instance = Column(String(255), default="", index=True)
    severity = Column(String(20), default="warning")
    action_type = Column(Enum(AlertActionType), nullable=False)
    note = Column(Text, default="")
    snooze_until = Column(DateTime, nullable=True, index=True)
    ticket_id = Column(
        Integer,
        ForeignKey("alert_tickets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow, index=True)

    ticket = relationship("AlertTicket", back_populates="actions")


class AlertTicket(Base):
    __tablename__ = "alert_tickets"
    id = Column(Integer, primary_key=True)
    alert_key = Column(String(255), nullable=False, index=True)
    alert_name = Column(String(120), nullable=False, index=True)
    instance = Column(String(255), default="", index=True)
    severity = Column(String(20), default="warning")
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(Enum(AlertTicketStatus), default=AlertTicketStatus.open, index=True)
    external_ref = Column(String(120), default="")
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    actions = relationship("AlertAction", back_populates="ticket")


# â”€â”€ Policies (DevOps) â”€â”€


class Policy(Base):
    __tablename__ = "policies"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    yaml_content = Column(Text, nullable=False)  # The actual YAML
    active_revision_id = Column(Integer, nullable=True, index=True)
    latest_revision_number = Column(Integer, default=0)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    revisions = relationship(
        "PolicyRevision", back_populates="policy", cascade="all, delete-orphan"
    )
    executions = relationship(
        "PolicyExecution", back_populates="policy", cascade="all, delete-orphan"
    )


class PolicyRevision(Base):
    __tablename__ = "policy_revisions"
    id = Column(Integer, primary_key=True)
    policy_id = Column(
        Integer,
        ForeignKey("policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = Column(Integer, nullable=False)
    name = Column(String(100), nullable=False, default="")
    description = Column(Text, default="")
    yaml_content = Column(Text, nullable=False)
    status = Column(
        String(24), default="draft", index=True
    )  # draft | active | archived
    change_summary = Column(Text, default="")
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow, index=True)

    policy = relationship("Policy", back_populates="revisions")
    executions = relationship("PolicyExecution", back_populates="revision")

    __table_args__ = (
        UniqueConstraint(
            "policy_id", "revision_number", name="uq_policy_revision_number"
        ),
    )


class PolicyExecution(Base):
    __tablename__ = "policy_executions"
    id = Column(Integer, primary_key=True)
    policy_id = Column(
        Integer,
        ForeignKey("policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id = Column(
        Integer,
        ForeignKey("policy_revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    execution_mode = Column(
        String(24), default="apply", index=True
    )  # dry_run | apply | rollback
    status = Column(String(24), default="pending", index=True)
    requested_by = Column(String(100), default="")
    host_ids = Column(JSON, default=list)
    host_results = Column(JSON, default=list)
    guardrails = Column(JSON, default=dict)
    summary = Column(JSON, default=dict)
    queue_job_id = Column(String(64), default="", index=True)
    requested_at = Column(DateTime, default=_utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    policy = relationship("Policy", back_populates="executions")
    revision = relationship("PolicyRevision", back_populates="executions")


class AdminTaskTemplate(Base):
    __tablename__ = "admin_task_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    task_key = Column(String(80), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    command_template = Column(Text, default="")
    default_timeout_seconds = Column(Integer, default=120)
    default_working_dir = Column(String(255), default="")
    allowed_roles = Column(JSON, default=list)
    is_enabled = Column(Boolean, default=True, index=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    executions = relationship("AdminTaskExecution", back_populates="template")


class AdminTaskExecution(Base):
    __tablename__ = "admin_task_executions"
    id = Column(Integer, primary_key=True)
    template_id = Column(
        Integer,
        ForeignKey("admin_task_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_key = Column(String(80), nullable=False, default="", index=True)
    execution_mode = Column(String(24), default="queued", index=True)
    status = Column(String(24), default="pending", index=True)
    requested_by = Column(String(100), default="")
    queue_job_id = Column(String(64), default="", index=True)
    parameters = Column(JSON, default=dict)
    result_summary = Column(JSON, default=dict)
    requested_at = Column(DateTime, default=_utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    template = relationship("AdminTaskTemplate", back_populates="executions")
    host = relationship("Host")


class PluginType(str, enum.Enum):
    webhook = "webhook"
    jira = "jira"
    servicenow = "servicenow"
    cmdb = "cmdb"


class PluginDeliveryStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class PluginIntegration(Base):
    __tablename__ = "plugin_integrations"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    plugin_type = Column(
        Enum(PluginType), nullable=False, default=PluginType.webhook, index=True
    )
    is_enabled = Column(Boolean, default=True, index=True)
    config = Column(JSON, default=dict)
    secret = Column(String(255), default="")
    max_attempts = Column(Integer, default=3)
    retry_backoff_seconds = Column(JSON, default=lambda: [5, 20, 60])
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    delivery_logs = relationship(
        "PluginDeliveryLog", back_populates="plugin", cascade="all, delete-orphan"
    )


class PluginDeliveryLog(Base):
    __tablename__ = "plugin_delivery_logs"
    id = Column(Integer, primary_key=True)
    plugin_id = Column(
        Integer,
        ForeignKey("plugin_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(120), nullable=False, index=True)
    status = Column(
        Enum(PluginDeliveryStatus), default=PluginDeliveryStatus.pending, index=True
    )
    request_payload = Column(JSON, default=dict)
    request_headers = Column(JSON, default=dict)
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, default="")
    error = Column(Text, default="")
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    plugin = relationship("PluginIntegration", back_populates="delivery_logs")

    __table_args__ = (
        Index("ix_plugin_delivery_plugin_created", "plugin_id", "created_at"),
        Index("ix_plugin_delivery_status_retry", "status", "next_retry_at"),
    )
