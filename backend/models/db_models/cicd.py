"""CI/CD pipelines, builds, deployments, secrets and the built-in git server."""

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


class CICDPipeline(Base):
    __tablename__ = "cicd_pipelines"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, default="")
    tool = Column(String(50), nullable=False)
    server_url = Column(String(255), nullable=False, default="")
    auth_type = Column(String(50), default="token")
    auth_credentials = Column(JSON, default=dict)
    job_path = Column(String(255), default="")
    script_type = Column(String(50), default="groovy")
    script_content = Column(Text, default="")
    webhook_secret = Column(String(100), default="")
    trigger_events = Column(JSON, default=list)
    status = Column(String(20), default="active")
    last_triggered = Column(DateTime, nullable=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    builds = relationship(
        "CICDBuild", back_populates="pipeline", cascade="all, delete-orphan"
    )


class CICDBuild(Base):
    __tablename__ = "cicd_builds"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("cicd_pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    build_number = Column(Integer, default=0)
    status = Column(String(20), default="pending")
    trigger_type = Column(String(50), default="manual")
    trigger_info = Column(JSON, default=dict)
    external_url = Column(String(500), default="")
    output = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    pipeline = relationship("CICDPipeline", back_populates="builds")

    __table_args__ = (
        Index("ix_cicd_builds_pipeline_id_created_at", "pipeline_id", "created_at"),
    )


class CICDVariable(Base):
    __tablename__ = "cicd_variables"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("cicd_pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key = Column(String(200), nullable=False)
    value = Column(Text, default="")
    is_secret = Column(Boolean, default=False)
    status = Column(String(30), default="active")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    pipeline = relationship("CICDPipeline", backref="variables")

    __table_args__ = (
        UniqueConstraint("pipeline_id", "key", name="uq_cicd_variables_pipeline_key"),
        Index("ix_cicd_variables_pipeline_id_key", "pipeline_id", "key"),
    )


class CICDEnvironment(Base):
    __tablename__ = "cicd_environments"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("cicd_pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    webhook_url = Column(String(500), default="")
    requires_approval = Column(Boolean, default=False)
    approvers = Column(JSON, default=list)
    approval_quorum = Column(Integer, default=1)
    approval_sla_minutes = Column(Integer, default=60)
    escalation_after_minutes = Column(Integer, default=120)
    escalation_targets = Column(JSON, default=list)
    status = Column(String(30), default="active")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    pipeline = relationship("CICDPipeline", backref="environments")

    __table_args__ = (
        UniqueConstraint("pipeline_id", "name", name="uq_cicd_env_pipeline_name"),
        Index("ix_cicd_environments_pipeline_id_name", "pipeline_id", "name"),
    )


class CICDDeployment(Base):
    __tablename__ = "cicd_deployments"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("cicd_pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id = Column(
        Integer,
        ForeignKey("cicd_environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    build_id = Column(
        Integer,
        ForeignKey("cicd_builds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(30), default="pending")
    triggered_by = Column(String(100), default="")
    notes = Column(Text, default="")
    external_url = Column(String(500), default="")
    storage_path = Column(String(500), default="")
    approved_by = Column(String(100), default="")
    approved_at = Column(DateTime, nullable=True)
    approval_due_at = Column(DateTime, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    escalation_status = Column(String(30), default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    pipeline = relationship("CICDPipeline", backref="deployments")
    environment = relationship("CICDEnvironment", backref="deployments")
    build = relationship("CICDBuild", backref="deployments")

    __table_args__ = (
        Index(
            "ix_cicd_deployments_pipeline_id_created_at", "pipeline_id", "created_at"
        ),
    )


class CICDDeploymentApproval(Base):
    __tablename__ = "cicd_deployment_approvals"
    id = Column(Integer, primary_key=True)
    deployment_id = Column(
        Integer,
        ForeignKey("cicd_deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approver = Column(String(100), nullable=False, index=True)
    decision = Column(String(20), nullable=False, index=True)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    deployment = relationship("CICDDeployment", backref="approvals")

    __table_args__ = (
        UniqueConstraint(
            "deployment_id",
            "approver",
            name="uq_cicd_deployment_approval_deployment_user",
        ),
        Index(
            "ix_cicd_deployment_approval_deployment_decision",
            "deployment_id",
            "decision",
        ),
    )


class CICDDeploymentApprovalEvent(Base):
    __tablename__ = "cicd_deployment_approval_events"
    id = Column(Integer, primary_key=True)
    deployment_id = Column(
        Integer,
        ForeignKey("cicd_deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(40), nullable=False, index=True)
    actor = Column(String(100), default="")
    note = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    deployment = relationship("CICDDeployment", backref="approval_events")

    __table_args__ = (
        Index(
            "ix_cicd_deployment_approval_events_deployment_created",
            "deployment_id",
            "created_at",
        ),
    )


class CICDNotificationDeliveryReceipt(Base):
    __tablename__ = "cicd_notification_delivery_receipts"
    id = Column(Integer, primary_key=True)
    deployment_id = Column(
        Integer,
        ForeignKey("cicd_deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(40), nullable=False, index=True)
    channel_type = Column(String(40), nullable=False, index=True)
    target = Column(String(255), nullable=False, index=True)
    status = Column(String(30), default="pending", index=True)
    attempt_count = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_retry_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    deployment = relationship("CICDDeployment", backref="delivery_receipts")

    __table_args__ = (
        Index(
            "ix_cicd_delivery_receipt_deployment_event", "deployment_id", "event_type"
        ),
        Index("ix_cicd_delivery_receipt_status_next_retry", "status", "next_retry_at"),
        UniqueConstraint(
            "deployment_id",
            "event_type",
            "channel_type",
            "target",
            name="uq_cicd_delivery_receipt_key",
        ),
    )


class CICDBuildStageRun(Base):
    __tablename__ = "cicd_build_stage_runs"
    id = Column(Integer, primary_key=True)
    build_id = Column(
        Integer,
        ForeignKey("cicd_builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_name = Column(String(120), nullable=False, index=True)
    order_index = Column(Integer, default=0)
    status = Column(String(30), default="pending", index=True)
    duration_seconds = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    output = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    build = relationship("CICDBuild", backref="stage_runs")

    __table_args__ = (
        Index("ix_cicd_stage_runs_build_order", "build_id", "order_index"),
        UniqueConstraint(
            "build_id", "stage_name", name="uq_cicd_stage_runs_build_stage"
        ),
    )


class CICDBuildLog(Base):
    __tablename__ = "cicd_build_logs"
    id = Column(Integer, primary_key=True)
    build_id = Column(
        Integer,
        ForeignKey("cicd_builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line = Column(Text, default="")
    storage_path = Column(String(500), default="")
    status = Column(String(30), default="info")
    created_at = Column(DateTime, default=_utcnow)

    build = relationship("CICDBuild", backref="logs")

    __table_args__ = (
        Index("ix_cicd_build_logs_build_id_created_at", "build_id", "created_at"),
    )


class CICDBuildArtifact(Base):
    __tablename__ = "cicd_build_artifacts"
    id = Column(Integer, primary_key=True)
    build_id = Column(
        Integer,
        ForeignKey("cicd_builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    url = Column(String(500), default="")
    size_bytes = Column(Integer, default=0)
    storage_path = Column(String(500), default="")
    status = Column(String(30), default="stored")
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)

    build = relationship("CICDBuild", backref="artifacts")

    __table_args__ = (
        Index("ix_cicd_build_artifacts_build_id_created_at", "build_id", "created_at"),
    )


class GitRepository(Base):
    __tablename__ = "git_repositories"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    server_url = Column(String(255), nullable=False, default="")
    repo_full_name = Column(String(255), nullable=False)
    default_branch = Column(String(100), default="main")
    auth_token = Column(String(255), default="")
    webhook_secret = Column(String(100), default="")
    webhook_id = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    last_synced = Column(DateTime, nullable=True)
    repo_meta = Column(JSON, default=dict)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "provider", "repo_full_name", name="uq_git_repo_provider_fullname"
        ),
        Index("ix_git_repositories_provider", "provider"),
    )


# ── PatchRepo (Built-in Git Server) ──


class PatchRepo(Base):
    """Local Git repository managed by PatchRepo server."""

    __tablename__ = "patch_repos"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    description = Column(Text, default="")
    repo_path = Column(
        String(500), nullable=False, unique=True
    )  # Absolute path on disk
    default_branch = Column(String(100), default="main")
    # Access control
    is_public = Column(Boolean, default=False)
    allow_push = Column(Boolean, default=True)
    allow_read = Column(Boolean, default=True)
    # Metadata
    size_bytes = Column(Integer, default=0)
    commit_count = Column(Integer, default=0)
    branch_count = Column(Integer, default=1)
    repo_meta = Column(JSON, default=dict)
    # Tracking
    last_activity = Column(DateTime, nullable=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    pull_requests = relationship(
        "PullRequest", back_populates="repo", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_patch_repos_created_at", "created_at"),)


class PullRequestState(str, enum.Enum):
    open = "open"
    merged = "merged"
    closed = "closed"


class PullRequestReviewStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    changes_requested = "changes_requested"
    commented = "commented"


class PullRequest(Base):
    """Pull Request for PatchRepo repositories."""

    __tablename__ = "pull_requests"
    id = Column(Integer, primary_key=True)
    repo_id = Column(
        Integer,
        ForeignKey("patch_repos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number = Column(Integer, nullable=False)  # PR number within repo
    title = Column(String(500), nullable=False)
    description = Column(Text, default="")
    state = Column(Enum(PullRequestState), default=PullRequestState.open, index=True)
    source_branch = Column(String(255), nullable=False)
    target_branch = Column(String(255), nullable=False)
    # Author
    author = Column(String(100), nullable=False)
    # Review tracking
    review_status = Column(
        Enum(PullRequestReviewStatus), default=PullRequestReviewStatus.pending
    )
    reviewer = Column(String(100), nullable=True)
    review_note = Column(Text, default="")
    reviewed_at = Column(DateTime, nullable=True)
    # Merge info
    merged_at = Column(DateTime, nullable=True)
    merged_by = Column(String(100), nullable=True)
    merge_commit_sha = Column(String(40), nullable=True)
    # Tracking
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("PatchRepo", back_populates="pull_requests")

    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_pull_request_repo_number"),
        Index("ix_pull_requests_repo_state", "repo_id", "state"),
        Index("ix_pull_requests_author", "author"),
    )


# â”€â”€ CI/CD Secret Manager â”€â”€


class CICDSecret(Base):
    """Encrypted secret store for CI/CD pipelines.

    Secrets are referenced in pipeline scripts as ${{ secrets.NAME }}.
    scope='global' means available to all pipelines; scope='pipeline' scopes to one.
    encrypted_value stores the Fernet-encrypted secret value.
    """

    __tablename__ = "cicd_secrets"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, default="")
    scope = Column(String(20), nullable=False, default="global")  # global | pipeline
    pipeline_id = Column(
        Integer,
        ForeignKey("cicd_pipelines.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    encrypted_value = Column(Text, nullable=False, default="")
    created_by = Column(String(100), nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    pipeline = relationship("CICDPipeline", backref="secrets")

    __table_args__ = (
        UniqueConstraint("name", "pipeline_id", name="uq_cicd_secret_name_pipeline"),
        Index("ix_cicd_secrets_scope", "scope"),
    )


# â”€â”€ CI/CD Agent Targets (CD to specific hosts via agent) â”€â”€


class CICDAgentTarget(Base):
    """Maps a pipeline+environment to a specific agent host for CD execution."""

    __tablename__ = "cicd_agent_targets"
    id = Column(Integer, primary_key=True)
    pipeline_id = Column(
        Integer,
        ForeignKey("cicd_pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id = Column(
        Integer,
        ForeignKey("cicd_environments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label = Column(String(200), nullable=False, default="")
    run_as = Column(String(100), nullable=False, default="")  # sudo user on Linux
    working_dir = Column(String(500), nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(100), nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    pipeline = relationship("CICDPipeline", backref="agent_targets")
    environment = relationship("CICDEnvironment", backref="agent_targets")
    host = relationship("Host", backref="cicd_agent_targets")

    # pipeline_id and host_id already use index=True above; avoid defining
    # the same single-column indexes twice because create_all will try to
    # recreate them on fresh installs/upgrades.
    __table_args__ = ()


class CICDAgentRun(Base):
    """Execution record for a CD command dispatched to an agent host."""

    __tablename__ = "cicd_agent_runs"
    id = Column(Integer, primary_key=True)
    build_id = Column(
        Integer,
        ForeignKey("cicd_builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id = Column(
        Integer,
        ForeignKey("cicd_agent_targets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    host_ip = Column(String(60), nullable=False, default="")
    stage_name = Column(String(200), nullable=False, default="")
    command = Column(Text, nullable=False, default="")
    status = Column(String(30), nullable=False, default="pending", index=True)
    output = Column(Text, nullable=False, default="")
    exit_code = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    build = relationship("CICDBuild", backref="agent_runs")
    target = relationship("CICDAgentTarget", backref="runs")
    host = relationship("Host", backref="cicd_agent_runs")

    # build_id and status already use index=True above; avoid redefining the
    # same single-column indexes because create_all will attempt to recreate
    # them on installs/upgrades.
    __table_args__ = ()
