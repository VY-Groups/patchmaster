"""Hosts, groups, tags, snapshots, config baselines, provisioning and network boot."""

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


def _utcnow() -> datetime:
    """Timezone-naive UTC datetime for SQLAlchemy column defaults."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -- Association tables --

host_group_assoc = Table(
    "host_group_assoc",
    Base.metadata,
    Column("host_id", Integer, ForeignKey("hosts.id", ondelete="CASCADE")),
    Column("group_id", Integer, ForeignKey("host_groups.id", ondelete="CASCADE")),
)

host_tag_assoc = Table(
    "host_tag_assoc",
    Base.metadata,
    Column("host_id", Integer, ForeignKey("hosts.id", ondelete="CASCADE")),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE")),
)


class Host(Base):
    __tablename__ = "hosts"
    id = Column(Integer, primary_key=True)
    hostname = Column(String(255), unique=True, nullable=False, index=True)
    ip = Column(String(45), nullable=False)
    tenant_id = Column(Integer, nullable=True, index=True)
    management_mode = Column(String(20), default="agent")  # agent | agentless | both
    site = Column(String(120), default="", index=True)
    hardware_inventory = Column(JSON, default=dict)
    agent_id = Column(String(100), default="", index=True)
    os = Column(String(100), default="")
    os_version = Column(String(50), default="")
    kernel = Column(String(100), default="")
    arch = Column(String(20), default="")
    agent_version = Column(String(20), default="")
    agent_token = Column(String(100), default="")
    is_online = Column(Boolean, default=False)
    last_heartbeat = Column(DateTime, nullable=True)
    last_patched = Column(DateTime, nullable=True)
    reboot_required = Column(Boolean, default=False)
    installed_count = Column(Integer, default=0)
    upgradable_count = Column(Integer, default=0)
    cve_count = Column(Integer, default=0)
    compliance_score = Column(Float, default=100.0)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    groups = relationship(
        "HostGroup", secondary=host_group_assoc, back_populates="hosts"
    )
    tags = relationship("Tag", secondary=host_tag_assoc, back_populates="hosts")
    patch_jobs = relationship("PatchJob", back_populates="host")
    snapshots_db = relationship("Snapshot", back_populates="host")
    host_cves = relationship("HostCVE", back_populates="host")

    __table_args__ = (
        Index("ix_hosts_ip", "ip"),
        Index("ix_hosts_is_online", "is_online"),
        Index("ix_hosts_last_heartbeat", "last_heartbeat"),
        # Partial unique index: agent_id must be unique among rows where it is non-empty.
        Index(
            "uq_hosts_agent_id_nonempty",
            "agent_id",
            unique=True,
            postgresql_where=text("agent_id IS NOT NULL AND agent_id != ''"),
        ),
        # Unique constraint on IP+hostname to prevent duplicate hosts
        UniqueConstraint("ip", "hostname", name="uq_hosts_ip_hostname"),
    )


# â”€â”€ Host Groups â”€â”€


class HostGroup(Base):
    __tablename__ = "host_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    hosts = relationship("Host", secondary=host_group_assoc, back_populates="groups")
    schedules = relationship("PatchSchedule", back_populates="group")


# â”€â”€ Tags â”€â”€


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)

    hosts = relationship("Host", secondary=host_tag_assoc, back_populates="tags")


# â”€â”€ Snapshots â”€â”€


class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(200), nullable=False)
    packages_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    host = relationship("Host", back_populates="snapshots_db")

    __table_args__ = (UniqueConstraint("host_id", "name", name="uq_host_snapshot"),)


class ConfigBaseline(Base):
    """Stored configuration baseline for a host."""

    __tablename__ = "config_baselines"

    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_name = Column(String(100), nullable=False)
    baseline_type = Column(String(20), nullable=False)  # snapshot, manual, scheduled
    # JSON stores the baseline data - structure varies by drift_type
    packages = Column(JSON, default=dict)  # {package_name: version}
    services = Column(JSON, default=dict)  # {service_name: status}
    network = Column(JSON, default=dict)  # {interface: {key: value}}
    registry = Column(JSON, default=dict)  # Windows registry entries
    files = Column(JSON, default=dict)  # {file_path: {hash, mtime, content}}
    baseline_metadata = Column(JSON, default=dict)  # Additional metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(100), nullable=True)

    # Note: Host relationship intentionally omitted to avoid conflicts

    def __repr__(self):
        return f"<ConfigBaseline id={self.id} host_id={self.host_id} name={self.baseline_name}>"


# â”€â”€ Host Timeline â”€â”€


class HostTimelineEvent(Base):
    __tablename__ = "host_timeline"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type = Column(
        String(50), nullable=False
    )  # patch | snapshot | cve | reboot | agent_update | login
    title = Column(String(200), nullable=False)
    detail = Column(JSON, nullable=True)
    severity = Column(String(20), default="info")  # info | warning | danger | success
    ref_id = Column(String(50), nullable=True)  # job_id, cve_id, etc.
    created_at = Column(DateTime, default=_utcnow, index=True)

    host = relationship("Host", backref="timeline_events")

    __table_args__ = (Index("ix_host_timeline_host_created", "host_id", "created_at"),)


class ProvisioningTemplate(Base):
    __tablename__ = "provisioning_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    description = Column(Text, default="")
    source_host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_snapshot_name = Column(String(200), nullable=False)
    snapshot_mode = Column(String(24), default="full_system")
    os_family = Column(String(40), default="", index=True)
    platform_label = Column(String(120), default="")
    site_scope = Column(String(120), default="", index=True)
    hardware_profile = Column(JSON, default=dict)
    labels = Column(JSON, default=list)
    archive_file_name = Column(String(255), nullable=False, default="")
    archive_checksum = Column(String(128), nullable=False, default="")
    archive_size_bytes = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True, index=True)
    created_by = Column(String(100), default="")
    last_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    source_host = relationship("Host", foreign_keys=[source_host_id])
    runs = relationship(
        "ProvisioningRun", back_populates="template", cascade="all, delete-orphan"
    )


class ProvisioningRun(Base):
    __tablename__ = "provisioning_runs"
    id = Column(Integer, primary_key=True)
    template_id = Column(
        Integer,
        ForeignKey("provisioning_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    initiated_by = Column(String(100), default="")
    mode = Column(String(24), default="reimage")
    status = Column(String(24), default="pending", index=True)
    allow_cross_site = Column(Boolean, default=False)
    target_host_ids = Column(JSON, default=list)
    result_summary = Column(JSON, default=dict)
    queue_job_id = Column(String(64), default="", index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    template = relationship("ProvisioningTemplate", back_populates="runs")


class BootRelay(Base):
    __tablename__ = "boot_relays"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer,
        ForeignKey("hosts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    name = Column(String(160), nullable=False, unique=True, index=True)
    site_scope = Column(String(120), default="", index=True)
    install_root = Column(String(255), default="/var/lib/patchmaster/network-boot")
    public_base_url = Column(String(255), default="")
    notes = Column(Text, default="")
    is_enabled = Column(Boolean, default=True, index=True)
    status = Column(String(24), default="idle", index=True)
    applied_version = Column(String(64), default="")
    rendered_config_checksum = Column(String(128), default="")
    last_install_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_validation_at = Column(DateTime, nullable=True)
    last_validation_status = Column(String(24), default="", index=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    host = relationship("Host")
    networks = relationship("NetworkBootNetwork", back_populates="relay")
    runs = relationship(
        "BootRelayRun", back_populates="relay", cascade="all, delete-orphan"
    )
    sessions = relationship("BootSession", back_populates="relay")


class NetworkBootNetwork(Base):
    __tablename__ = "network_boot_networks"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    interface_name = Column(String(120), default="")
    vlan_id = Column(Integer, nullable=True)
    cidr = Column(String(64), default="")
    gateway = Column(String(64), default="")
    dns_servers = Column(JSON, default=list)
    dhcp_range_start = Column(String(64), default="")
    dhcp_range_end = Column(String(64), default="")
    next_server = Column(String(255), default="")
    controller_url = Column(String(255), default="")
    relay_id = Column(
        Integer,
        ForeignKey("boot_relays.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artifact_version = Column(String(64), default="")
    rendered_config_checksum = Column(String(128), default="")
    last_rendered_at = Column(DateTime, nullable=True)
    last_validated_at = Column(DateTime, nullable=True)
    last_validation_status = Column(String(24), default="", index=True)
    boot_file_bios = Column(String(255), default="undionly.kpxe")
    boot_file_uefi = Column(String(255), default="ipxe.efi")
    is_enabled = Column(Boolean, default=True, index=True)
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    relay = relationship("BootRelay", back_populates="networks")
    profiles = relationship("NetworkBootProfile", back_populates="network")
    assignments = relationship("NetworkBootAssignment", back_populates="network")
    sessions = relationship("BootSession", back_populates="network")


class NetworkBootProfile(Base):
    __tablename__ = "network_boot_profiles"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, unique=True, index=True)
    network_id = Column(
        Integer,
        ForeignKey("network_boot_networks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provisioning_template_id = Column(
        Integer,
        ForeignKey("provisioning_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mirror_repo_id = Column(
        Integer,
        ForeignKey("mirror_repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    os_family = Column(String(40), default="", index=True)
    os_version = Column(String(80), default="")
    architecture = Column(String(40), default="x86_64")
    firmware_mode = Column(String(24), default="uefi")
    install_mode = Column(String(40), default="ubuntu_autoinstall")
    kernel_url = Column(String(500), default="")
    initrd_url = Column(String(500), default="")
    rootfs_url = Column(String(500), default="")
    answer_template = Column(Text, default="")
    post_install_script = Column(Text, default="")
    is_enabled = Column(Boolean, default=True, index=True)
    release_label = Column(String(40), default="stable")
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    network = relationship("NetworkBootNetwork", back_populates="profiles")
    provisioning_template = relationship("ProvisioningTemplate")
    mirror_repo = relationship("MirrorRepo")
    assignments = relationship("NetworkBootAssignment", back_populates="profile")
    sessions = relationship("BootSession", back_populates="profile")


class NetworkBootAssignment(Base):
    __tablename__ = "network_boot_assignments"
    id = Column(Integer, primary_key=True)
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    network_id = Column(
        Integer,
        ForeignKey("network_boot_networks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id = Column(
        Integer,
        ForeignKey("network_boot_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hostname = Column(String(255), default="", index=True)
    mac_address = Column(String(32), nullable=False, unique=True, index=True)
    reserved_ip = Column(String(64), default="")
    firmware_mode = Column(String(24), default="uefi")
    boot_once = Column(Boolean, default=True)
    is_enabled = Column(Boolean, default=True, index=True)
    site_scope = Column(String(120), default="", index=True)
    created_by = Column(String(100), default="")
    last_boot_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    host = relationship("Host")
    network = relationship("NetworkBootNetwork", back_populates="assignments")
    profile = relationship("NetworkBootProfile", back_populates="assignments")
    sessions = relationship("BootSession", back_populates="assignment")


class BootRelayRun(Base):
    __tablename__ = "boot_relay_runs"
    id = Column(Integer, primary_key=True)
    relay_id = Column(
        Integer,
        ForeignKey("boot_relays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action = Column(String(24), nullable=False, index=True)  # install | sync | validate
    status = Column(String(24), default="pending", index=True)
    requested_by = Column(String(100), default="")
    queue_job_id = Column(String(64), default="", index=True)
    payload = Column(JSON, default=dict)
    result_summary = Column(JSON, default=dict)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    relay = relationship("BootRelay", back_populates="runs")


class BootSession(Base):
    __tablename__ = "boot_sessions"
    id = Column(Integer, primary_key=True)
    session_token = Column(String(64), nullable=False, unique=True, index=True)
    assignment_id = Column(
        Integer,
        ForeignKey("network_boot_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    profile_id = Column(
        Integer,
        ForeignKey("network_boot_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    network_id = Column(
        Integer,
        ForeignKey("network_boot_networks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    relay_id = Column(
        Integer,
        ForeignKey("boot_relays.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    host_id = Column(
        Integer, ForeignKey("hosts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mac_address = Column(String(32), default="", index=True)
    hostname = Column(String(255), default="", index=True)
    controller_url = Column(String(255), default="")
    current_stage = Column(String(40), default="assignment_served", index=True)
    status = Column(String(24), default="active", index=True)
    provisioning_source = Column(String(80), default="")
    event_count = Column(Integer, default=0)
    result_summary = Column(JSON, default=dict)
    started_at = Column(DateTime, default=_utcnow, index=True)
    last_event_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    assignment = relationship("NetworkBootAssignment", back_populates="sessions")
    profile = relationship("NetworkBootProfile", back_populates="sessions")
    network = relationship("NetworkBootNetwork", back_populates="sessions")
    relay = relationship("BootRelay", back_populates="sessions")
    host = relationship("Host")
    events = relationship(
        "BootEvent", back_populates="session", cascade="all, delete-orphan"
    )


class BootEvent(Base):
    __tablename__ = "boot_events"
    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("boot_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(64), nullable=False, index=True)
    source = Column(String(40), default="", index=True)
    message = Column(Text, default="")
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow, index=True)

    session = relationship("BootSession", back_populates="events")
