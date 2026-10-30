import hashlib
import asyncio
import json
import os
import socket
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from prometheus_client import Counter, Gauge
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_role
from api.ops_queue import enqueue_operation
from api.cicd_secrets import decrypt_json_field, encrypt_json_field
from database import async_session, get_db
from models.db_models import (
    MirrorPackageIndex,
    MirrorRepo,
    MirrorRepoProvider,
    MirrorSyncLease,
    MirrorSyncRun,
    MirrorSyncStatus,
    AuditLog,
    Host,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/mirror", tags=["mirror"])

MIRROR_BASE_DIR = Path(__file__).resolve().parent.parent / "static" / "mirror"
MIRROR_BASE_DIR.mkdir(parents=True, exist_ok=True)
AGENT_PORT = 8080
_REPO_SYNC_LOCKS: dict[int, asyncio.Lock] = {}
_LEASE_TTL_SECONDS_DEFAULT = int(os.getenv("PM_MIRROR_LEASE_TTL_SECONDS", "900"))
_LEASE_NODE = os.getenv("HOSTNAME") or os.getenv("COMPUTERNAME") or socket.gethostname()
_LEASE_HOLDER_ID = f"{_LEASE_NODE}:{os.getpid()}:{uuid.uuid4().hex[:10]}"
MIRROR_SYNC_LOCK_CONFLICTS_TOTAL = Counter(
    "patchmaster_mirror_sync_lock_conflicts_total",
    "Mirror sync lock conflicts",
    ["reason"],
)
MIRROR_SYNC_LEASE_TAKEOVERS_TOTAL = Counter(
    "patchmaster_mirror_sync_lease_takeovers_total",
    "Mirror sync lease takeovers",
)
MIRROR_STALE_LEASES_CLEANED_TOTAL = Counter(
    "patchmaster_mirror_stale_leases_cleaned_total",
    "Number of stale mirror sync leases cleaned",
)
MIRROR_STALE_LEASES_REMOVED_LAST_RUN = Gauge(
    "patchmaster_mirror_stale_leases_removed_last_run",
    "Removed stale mirror sync leases in last cleanup run",
)
MIRROR_ACTIVE_LEASES = Gauge(
    "patchmaster_mirror_active_leases",
    "Current non-expired mirror sync leases",
)
_AUTO_BOOTSTRAP_ON_AGENT_ACTIVE = (os.getenv("PM_MIRROR_AUTO_BOOTSTRAP_ON_AGENT_ACTIVE", "1") or "1").strip() != "0"
_AUTO_BOOTSTRAP_COOLDOWN_SECONDS = max(int(os.getenv("PM_MIRROR_AUTO_BOOTSTRAP_COOLDOWN_SECONDS", "1800")), 30)
_AUTO_BOOTSTRAP_LAST_RUN: dict[str, datetime] = {}
DEFAULT_SOURCE_BY_PROVIDER = {
    MirrorRepoProvider.microsoft: "https://api.msrc.microsoft.com/cvrf/v3.0/updates",
    MirrorRepoProvider.ubuntu: "https://ubuntu.com/security/notices.json",
    MirrorRepoProvider.redhat: "https://access.redhat.com/hydra/rest/securitydata/csaf.json",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MirrorRepoCreate(BaseModel):
    name: str
    provider: str
    os_family: str = "linux"
    channel: str = "default"
    source_url: str = ""
    enabled: bool = True
    metadata_only: bool = True
    sync_interval_minutes: int = 360
    retention_days: int = 30
    keep_versions: int = 2
    auth_config: dict = {}
    extra_config: dict = {}


class MirrorRepoUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    os_family: Optional[str] = None
    channel: Optional[str] = None
    source_url: Optional[str] = None
    enabled: Optional[bool] = None
    metadata_only: Optional[bool] = None
    sync_interval_minutes: Optional[int] = None
    retention_days: Optional[int] = None
    keep_versions: Optional[int] = None
    auth_config: Optional[dict] = None
    extra_config: Optional[dict] = None


class MirrorRepoResponse(BaseModel):
    id: int
    name: str
    provider: str
    os_family: str
    channel: str
    source_url: str
    enabled: bool
    metadata_only: bool
    sync_interval_minutes: int
    retention_days: int
    keep_versions: int
    mirror_path: str
    auth_config: dict
    has_auth_token: bool = False
    extra_config: dict
    last_sync_at: Optional[datetime]
    next_sync_at: Optional[datetime]
    last_sync_status: str
    last_sync_summary: dict
    created_by: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_obj(cls, obj: MirrorRepo):
        auth_config = decrypt_json_field(obj.auth_config)
        return cls(
            id=obj.id,
            name=obj.name,
            provider=obj.provider.value if hasattr(obj.provider, "value") else str(obj.provider),
            os_family=obj.os_family,
            channel=obj.channel,
            source_url=obj.source_url,
            enabled=obj.enabled,
            metadata_only=obj.metadata_only,
            sync_interval_minutes=obj.sync_interval_minutes,
            retention_days=obj.retention_days,
            keep_versions=obj.keep_versions,
            mirror_path=obj.mirror_path,
            auth_config={},
            has_auth_token=bool(str((auth_config or {}).get("token", "")).strip()),
            extra_config=obj.extra_config or {},
            last_sync_at=obj.last_sync_at,
            next_sync_at=obj.next_sync_at,
            last_sync_status=obj.last_sync_status.value if hasattr(obj.last_sync_status, "value") else str(obj.last_sync_status),
            last_sync_summary=obj.last_sync_summary or {},
            created_by=obj.created_by or "",
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class MirrorSyncRunResponse(BaseModel):
    id: int
    repo_id: int
    trigger_type: str
    status: str
    summary: dict
    error: str
    started_at: datetime
    completed_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_obj(cls, obj: MirrorSyncRun):
        return cls(
            id=obj.id,
            repo_id=obj.repo_id,
            trigger_type=obj.trigger_type,
            status=obj.status.value if hasattr(obj.status, "value") else str(obj.status),
            summary=obj.summary or {},
            error=obj.error or "",
            started_at=obj.started_at,
            completed_at=obj.completed_at,
        )


def _lease_ttl_seconds(repo: MirrorRepo) -> int:
    raw = (repo.extra_config or {}).get("lease_ttl_seconds", _LEASE_TTL_SECONDS_DEFAULT)
    try:
        value = int(str(raw))
    except Exception:
        value = _LEASE_TTL_SECONDS_DEFAULT
    return max(value, 60)


def _audit_log(action: str, repo: MirrorRepo, details: dict[str, Any]) -> AuditLog:
    return AuditLog(
        user_id=None,
        action=action,
        target_type="mirror_repo",
        target_id=str(repo.id),
        details=details,
    )


async def _refresh_active_lease_metric(db: AsyncSession):
    now = _utc_now()
    active_count = (
        await db.execute(select(func.count(MirrorSyncLease.id)).where(MirrorSyncLease.expires_at > now))
    ).scalar() or 0
    MIRROR_ACTIVE_LEASES.set(float(active_count))


async def _acquire_repo_lease(db: AsyncSession, repo: MirrorRepo, trigger_type: str) -> tuple[bool, dict[str, Any]]:
    now = _utc_now()
    ttl = _lease_ttl_seconds(repo)
    expires_at = now + timedelta(seconds=ttl)
    lease = (
        await db.execute(select(MirrorSyncLease).where(MirrorSyncLease.repo_id == repo.id))
    ).scalar_one_or_none()
    if lease is None:
        lease = MirrorSyncLease(
            repo_id=repo.id,
            holder_id=_LEASE_HOLDER_ID,
            holder_node=_LEASE_NODE,
            heartbeat_at=now,
            expires_at=expires_at,
            meta={"trigger_type": trigger_type},
        )
        db.add(lease)
        try:
            await db.commit()
            await _refresh_active_lease_metric(db)
            return True, {"holder_id": _LEASE_HOLDER_ID, "holder_node": _LEASE_NODE, "expires_at": expires_at}
        except IntegrityError:
            await db.rollback()
            lease = (
                await db.execute(select(MirrorSyncLease).where(MirrorSyncLease.repo_id == repo.id))
            ).scalar_one_or_none()
    if lease and lease.holder_id != _LEASE_HOLDER_ID and lease.expires_at and lease.expires_at > now:
        MIRROR_SYNC_LOCK_CONFLICTS_TOTAL.labels(reason="leased").inc()
        db.add(
            _audit_log(
                "mirror_sync_lock_conflict",
                repo,
                {
                    "holder_id": lease.holder_id,
                    "holder_node": lease.holder_node,
                    "expires_at": lease.expires_at.isoformat() if lease.expires_at else "",
                    "trigger_type": trigger_type,
                },
            )
        )
        await db.commit()
        return False, {
            "holder_id": lease.holder_id,
            "holder_node": lease.holder_node,
            "expires_at": lease.expires_at,
        }
    if lease is None:
        return False, {"holder_id": "", "holder_node": "", "expires_at": now}
    takeover = bool(lease.holder_id and lease.holder_id != _LEASE_HOLDER_ID)
    previous_holder_id = lease.holder_id
    previous_holder_node = lease.holder_node
    lease.holder_id = _LEASE_HOLDER_ID
    lease.holder_node = _LEASE_NODE
    lease.heartbeat_at = now
    lease.expires_at = expires_at
    lease.meta = {"trigger_type": trigger_type}
    db.add(lease)
    if takeover:
        MIRROR_SYNC_LEASE_TAKEOVERS_TOTAL.inc()
        db.add(
            _audit_log(
                "mirror_sync_lease_takeover",
                repo,
                {
                    "previous_holder_id": previous_holder_id,
                    "previous_holder_node": previous_holder_node,
                    "new_holder_id": _LEASE_HOLDER_ID,
                    "new_holder_node": _LEASE_NODE,
                    "trigger_type": trigger_type,
                },
            )
        )
    await db.commit()
    await _refresh_active_lease_metric(db)
    return True, {"holder_id": _LEASE_HOLDER_ID, "holder_node": _LEASE_NODE, "expires_at": expires_at}


async def _heartbeat_repo_lease(db: AsyncSession, repo: MirrorRepo):
    lease = (
        await db.execute(
            select(MirrorSyncLease).where(
                MirrorSyncLease.repo_id == repo.id,
                MirrorSyncLease.holder_id == _LEASE_HOLDER_ID,
            )
        )
    ).scalar_one_or_none()
    if not lease:
        return
    now = _utc_now()
    lease.heartbeat_at = now
    lease.expires_at = now + timedelta(seconds=_lease_ttl_seconds(repo))
    db.add(lease)
    await db.commit()


async def _release_repo_lease(db: AsyncSession, repo: MirrorRepo):
    lease = (
        await db.execute(
            select(MirrorSyncLease).where(
                MirrorSyncLease.repo_id == repo.id,
                MirrorSyncLease.holder_id == _LEASE_HOLDER_ID,
            )
        )
    ).scalar_one_or_none()
    if lease:
        await db.delete(lease)
        await db.commit()
        await _refresh_active_lease_metric(db)


async def cleanup_stale_repo_leases(db: AsyncSession, max_rows: int = 500) -> dict[str, Any]:
    now = _utc_now()
    stale = (
        await db.execute(
            select(MirrorSyncLease)
            .where(MirrorSyncLease.expires_at <= now)
            .order_by(MirrorSyncLease.expires_at.asc())
            .limit(max_rows)
        )
    ).scalars().all()
    removed = len(stale)
    if removed:
        for lease in stale:
            await db.delete(lease)
        db.add(
            AuditLog(
                user_id=None,
                action="mirror_stale_lease_cleanup",
                target_type="mirror_repo",
                target_id="*",
                details={
                    "removed": removed,
                    "repo_ids": [lease.repo_id for lease in stale],
                    "holder_ids": [lease.holder_id for lease in stale],
                },
            )
        )
        await db.commit()
        MIRROR_STALE_LEASES_CLEANED_TOTAL.inc(float(removed))
    MIRROR_STALE_LEASES_REMOVED_LAST_RUN.set(float(removed))
    await _refresh_active_lease_metric(db)
    return {"removed": removed}


def _safe_dir_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.lower())
    return cleaned.strip("-") or "repo"


def _default_source(provider: MirrorRepoProvider, channel: str) -> str:
    base = DEFAULT_SOURCE_BY_PROVIDER.get(provider, "")
    if not base:
        return ""
    if provider == MirrorRepoProvider.ubuntu and channel and channel != "default":
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}release={channel}"
    return base


def _satellite_source_from_config(repo: MirrorRepo) -> str:
    cfg = dict(repo.extra_config or {})
    if str(cfg.get("feed_family", "")).strip().lower() != "satellite":
        return ""
    base = str(cfg.get("satellite_url", "")).strip().rstrip("/")
    org = str(cfg.get("satellite_org", "")).strip()
    env = str(cfg.get("satellite_env", "")).strip()
    if not base:
        return ""
    query = []
    if org:
        query.append(f"organization_id={org}")
    if env:
        query.append(f"environment_id={env}")
    query.append("per_page=1000")
    return f"{base}/katello/api/v2/errata?{'&'.join(query)}"


def _effective_source_url(repo: MirrorRepo) -> str:
    explicit = str(repo.source_url or "").strip()
    if explicit:
        return explicit
    satellite = _satellite_source_from_config(repo)
    if satellite:
        return satellite
    return _default_source(repo.provider, repo.channel)


def _extract_debian_packages(payload: Any, channel: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    target_release = ""
    if channel.startswith("debian-"):
        target_release = channel.split("debian-", 1)[1].strip().lower()
    results: list[dict[str, Any]] = []
    for package_name, release_info in payload.items():
        if not isinstance(release_info, dict):
            continue
        for release_name, detail in release_info.items():
            if not isinstance(detail, dict):
                continue
            release_key = str(release_name).strip().lower()
            if target_release and target_release not in release_key:
                continue
            fixed_version = str(detail.get("fixed_version", "")).strip()
            urgency = str(detail.get("urgency", "")).strip()
            status = str(detail.get("status", "")).strip().lower()
            if status in {"not-affected", "open"} and not fixed_version:
                continue
            results.append(
                {
                    "name": str(package_name).strip(),
                    "version": fixed_version or urgency or _utc_now().strftime("%Y%m%d%H%M%S"),
                    "architecture": "",
                    "channel": channel,
                    "fixed_version": fixed_version,
                    "source_url": "https://security-tracker.debian.org/tracker/data/json",
                    "package_meta": {"release": release_name, "status": status, "urgency": urgency},
                }
            )
    return results


def _normalize_host_channel(host: Host) -> str:
    os_text = f"{str(host.os or '')} {str(host.os_version or '')}".lower()
    if "windows" in os_text:
        if "11" in os_text:
            return "windows-11"
        if "10" in os_text:
            return "windows-10"
        if "8.1" in os_text:
            return "windows-8.1"
        if "8" in os_text:
            return "windows-8"
        if "7" in os_text:
            return "windows-7"
        if "server 2025" in os_text:
            return "windows-server-2025"
        if "server 2022" in os_text:
            return "windows-server-2022"
        if "server 2019" in os_text:
            return "windows-server-2019"
        return "windows-default"
    if "ubuntu" in os_text:
        m = re.search(r"(20\.04|22\.04|24\.04|18\.04)", os_text)
        return f"ubuntu-{m.group(1)}" if m else "ubuntu-default"
    if "debian" in os_text:
        m = re.search(r"\b(10|11|12|13)\b", os_text)
        return f"debian-{m.group(1)}" if m else "debian-default"
    if any(x in os_text for x in ["red hat", "rhel", "centos", "rocky", "alma", "almalinux", "oracle linux", "fedora"]):
        m = re.search(r"\b([5-9]|10)\b", os_text)
        prefix = "rhel"
        if "alma" in os_text:
            prefix = "alma"
        elif "rocky" in os_text:
            prefix = "rocky"
        elif "centos" in os_text:
            prefix = "centos"
        elif "oracle" in os_text:
            prefix = "oracle"
        elif "fedora" in os_text:
            prefix = "fedora"
        return f"{prefix}-{m.group(1)}" if m else f"{prefix}-default"
    if "arch" in os_text:
        return "arch-default"
    return "default"


def _host_repo_blueprints(host: Host) -> list[dict[str, Any]]:
    os_text = f"{str(host.os or '')} {str(host.os_version or '')}".lower()
    channel = _normalize_host_channel(host)
    if "windows" in os_text:
        return [{
            "name": f"windows-{channel}",
            "provider": MirrorRepoProvider.microsoft,
            "os_family": "windows",
            "channel": channel,
            "source_url": "",
            "extra_config": {"auto_managed": True, "source_profile": "microsoft"},
        }]
    if "ubuntu" in os_text:
        return [{
            "name": f"ubuntu-{channel}",
            "provider": MirrorRepoProvider.ubuntu,
            "os_family": "linux",
            "channel": channel,
            "source_url": "",
            "extra_config": {"auto_managed": True, "source_profile": "ubuntu"},
        }]
    if "debian" in os_text:
        return [{
            "name": f"debian-{channel}",
            "provider": MirrorRepoProvider.custom,
            "os_family": "linux",
            "channel": channel,
            "source_url": "https://security-tracker.debian.org/tracker/data/json",
            "extra_config": {"auto_managed": True, "feed_family": "debian", "source_profile": "debian"},
        }]
    if any(x in os_text for x in ["red hat", "rhel", "centos", "rocky", "alma", "almalinux", "oracle linux", "fedora"]):
        satellite_mode = "satellite" in os_text
        return [{
            "name": f"rhel-family-{channel}",
            "provider": MirrorRepoProvider.custom if satellite_mode else MirrorRepoProvider.redhat,
            "os_family": "linux",
            "channel": channel,
            "source_url": "" if not satellite_mode else "",
            "extra_config": {
                "auto_managed": True,
                "source_profile": "rhel-family",
                "feed_family": "satellite" if satellite_mode else "redhat",
                "requires_source_url": bool(satellite_mode),
            },
        }]
    if "arch" in os_text:
        return [{
            "name": f"archlinux-{channel}",
            "provider": MirrorRepoProvider.custom,
            "os_family": "linux",
            "channel": channel,
            "source_url": "https://security.archlinux.org/all.json",
            "extra_config": {"auto_managed": True, "feed_family": "archlinux", "source_profile": "archlinux"},
        }]
    return []

def _extract_package_name(item: dict[str, Any]) -> str:
    for key in ("name", "package", "title", "id", "kb", "cve"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    source = str(item.get("url", "")).rstrip("/").split("/")
    if source and source[-1]:
        return source[-1]
    return "unknown-package"


def _extract_package_version(item: dict[str, Any]) -> str:
    for key in ("version", "fixed_version", "release", "revision", "updated", "published", "currentReleaseDate"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return _utc_now().strftime("%Y%m%d%H%M%S")


def _normalize_feed_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [i for i in payload if isinstance(i, dict)]
    if isinstance(payload, dict):
        for key in ("packages", "items", "value", "notices", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
    return []


def _extract_ubuntu_packages(notice: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    releases = notice.get("releases", {})
    if isinstance(releases, dict):
        for release_name, release_data in releases.items():
            if not isinstance(release_data, dict):
                continue
            pkgs = release_data.get("packages", {})
            if isinstance(pkgs, dict):
                for pkg_name, pkg_data in pkgs.items():
                    version = ""
                    if isinstance(pkg_data, dict):
                        version = str(pkg_data.get("version", "")).strip()
                    if not version:
                        continue
                    results.append(
                        {
                            "name": str(pkg_name),
                            "version": version,
                            "architecture": "",
                            "channel": str(release_name),
                            "fixed_version": version,
                            "source_url": str(notice.get("url", "")).strip(),
                            "package_meta": {"notice": notice, "release": release_name},
                        }
                    )
    return results


def _extract_redhat_packages(item: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    title = str(item.get("title", "") or item.get("id", "") or "redhat-advisory")
    severity = str(item.get("severity", "")).strip()
    fixed = str(item.get("fixed_version", "")).strip()
    affected = item.get("affected_packages") if isinstance(item.get("affected_packages"), list) else []
    if affected:
        for pkg in affected:
            if not isinstance(pkg, dict):
                continue
            pkg_name = str(pkg.get("name", "")).strip()
            pkg_ver = str(pkg.get("fixed_version", "") or pkg.get("version", "")).strip()
            if not pkg_name:
                continue
            results.append(
                {
                    "name": pkg_name,
                    "version": pkg_ver or fixed or _utc_now().strftime("%Y%m%d"),
                    "architecture": str(pkg.get("arch", "")).strip(),
                    "channel": str(item.get("product", "") or "redhat"),
                    "fixed_version": pkg_ver or fixed,
                    "source_url": str(item.get("url", "")).strip(),
                    "package_meta": {"advisory": item, "severity": severity},
                }
            )
        return results
    cves = item.get("cves") if isinstance(item.get("cves"), list) else []
    if cves:
        for cve in cves:
            cve_id = str(cve if isinstance(cve, str) else cve.get("id", "")).strip()
            if not cve_id:
                continue
            results.append(
                {
                    "name": cve_id,
                    "version": fixed or _utc_now().strftime("%Y%m%d"),
                    "architecture": "",
                    "channel": "redhat",
                    "fixed_version": fixed,
                    "source_url": str(item.get("url", "")).strip(),
                    "package_meta": {"advisory": title, "severity": severity, "cve": cve_id, "raw": item},
                }
            )
    return results


def _extract_microsoft_packages(item: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cvrf_id = str(item.get("cvrfUrl", "")).strip()
    release_date = str(item.get("currentReleaseDate", "")).strip()
    title = str(item.get("alias", "") or item.get("id", "") or item.get("title", "")).strip()
    source_url = cvrf_id or str(item.get("url", "")).strip()
    if not title:
        return results
    kb_matches = re.findall(r"KB\d{5,8}", json.dumps(item, default=str))
    if kb_matches:
        for kb in sorted(set(kb_matches)):
            results.append(
                {
                    "name": kb,
                    "version": release_date or _utc_now().strftime("%Y%m%d"),
                    "architecture": "",
                    "channel": "windows",
                    "fixed_version": release_date,
                    "source_url": source_url,
                    "package_meta": {"bulletin": title, "kb": kb, "raw": item},
                }
            )
    else:
        results.append(
            {
                "name": title,
                "version": release_date or _utc_now().strftime("%Y%m%d"),
                "architecture": "",
                "channel": "windows",
                "fixed_version": release_date,
                "source_url": source_url,
                "package_meta": {"bulletin": title, "raw": item},
            }
        )
    return results


def _provider_items(payload: Any, repo: MirrorRepo) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    feed_family = str((repo.extra_config or {}).get("feed_family", "")).strip().lower()
    if feed_family == "debian":
        return _extract_debian_packages(payload, repo.channel)
    if feed_family in {"satellite", "redhat"}:
        advisories = _normalize_feed_items(payload)
        for advisory in advisories:
            items.extend(_extract_redhat_packages(advisory))
        return items
    if repo.provider == MirrorRepoProvider.ubuntu:
        notices = _normalize_feed_items(payload)
        for notice in notices:
            items.extend(_extract_ubuntu_packages(notice))
    elif repo.provider == MirrorRepoProvider.redhat:
        advisories = _normalize_feed_items(payload)
        for advisory in advisories:
            items.extend(_extract_redhat_packages(advisory))
    elif repo.provider == MirrorRepoProvider.microsoft:
        updates = _normalize_feed_items(payload)
        for update in updates:
            items.extend(_extract_microsoft_packages(update))
    else:
        generic = _normalize_feed_items(payload)
        for item in generic:
            items.append(
                {
                    "name": _extract_package_name(item),
                    "version": _extract_package_version(item),
                    "architecture": str(item.get("architecture", "") or item.get("arch", "")).strip(),
                    "channel": repo.channel,
                    "fixed_version": str(item.get("fixed_version", "") or item.get("available_version", "")).strip(),
                    "source_url": str(item.get("url", "") or item.get("download_url", "") or item.get("href", "")).strip(),
                    "package_meta": item,
                }
            )
    return items


async def _fetch_catalog(repo: MirrorRepo) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_url = _effective_source_url(repo)
    if not source_url:
        raise HTTPException(status_code=400, detail=f"Repository '{repo.name}' has no source URL configured")
    headers = {}
    auth_config = decrypt_json_field(repo.auth_config)
    token = str((auth_config or {}).get("token", "")).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    checkpoint = (repo.extra_config or {}).get("delta_checkpoint", {})
    if checkpoint.get("etag"):
        headers["If-None-Match"] = str(checkpoint.get("etag"))
    if checkpoint.get("last_modified"):
        headers["If-Modified-Since"] = str(checkpoint.get("last_modified"))
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(source_url, headers=headers)
        if response.status_code == 304:
            return [], {
                "not_modified": True,
                "etag": str(response.headers.get("etag", "")).strip(),
                "last_modified": str(response.headers.get("last-modified", "")).strip(),
                "source_hash": str(checkpoint.get("source_hash", "")).strip(),
            }
        response.raise_for_status()
        content_type = (response.headers.get("content-type", "") or "").lower()
        text = response.text
        fetch_meta = {
            "not_modified": False,
            "etag": str(response.headers.get("etag", "")).strip(),
            "last_modified": str(response.headers.get("last-modified", "")).strip(),
            "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    if "json" in content_type:
        payload = json.loads(text)
        items = _provider_items(payload, repo)
    else:
        try:
            payload = json.loads(text)
            items = _provider_items(payload, repo)
        except Exception:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            items = [{"name": ln.split()[0], "version": _utc_now().strftime("%Y%m%d"), "raw_line": ln} for ln in lines[:5000]]
    normalized = []
    for item in items[:40000]:
        pkg_name = str(item.get("name", "")).strip() or _extract_package_name(item)
        pkg_version = str(item.get("version", "")).strip() or _extract_package_version(item)
        architecture = str(item.get("architecture", "") or item.get("arch", "") or "").strip()
        download_url = str(item.get("source_url", "") or item.get("url", "") or item.get("download_url", "") or item.get("href", "")).strip()
        checksum = str(item.get("checksum", "") or item.get("sha256", "") or "").strip()
        fixed_version = str(item.get("fixed_version", "")).strip()
        normalized.append(
            {
                "package_name": pkg_name,
                "package_version": pkg_version,
                "architecture": architecture,
                "source_url": download_url,
                "checksum": checksum,
                "package_meta": {**(item.get("package_meta") if isinstance(item.get("package_meta"), dict) else {}), "fixed_version": fixed_version},
            }
        )
    return normalized, fetch_meta


async def _download_package(repo_dir: Path, item: dict[str, Any]) -> Optional[str]:
    source_url = item.get("source_url", "")
    if not source_url:
        return None
    file_name = os.path.basename(source_url.split("?")[0].strip())
    if not file_name:
        raw = f"{item.get('package_name', 'pkg')}-{item.get('package_version', 'ver')}"
        file_name = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    file_path = repo_dir / file_name
    if file_path.exists():
        return file_name
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        async with client.stream("GET", source_url) as response:
            response.raise_for_status()
            with open(file_path, "wb") as out:
                async for chunk in response.aiter_bytes():
                    out.write(chunk)
    return file_name


async def execute_repo_sync(db: AsyncSession, repo: MirrorRepo, trigger_type: str = "manual") -> dict[str, Any]:
    lock = _REPO_SYNC_LOCKS.setdefault(repo.id, asyncio.Lock())
    if lock.locked():
        MIRROR_SYNC_LOCK_CONFLICTS_TOTAL.labels(reason="local_runtime_lock").inc()
        return {
            "status": "skipped",
            "reason": "sync_in_progress",
            "repo_id": repo.id,
        }
    async with lock:
        acquired, lease_info = await _acquire_repo_lease(db, repo, trigger_type)
        if not acquired:
            return {
                "status": "skipped",
                "reason": "sync_locked_by_other_node",
                "repo_id": repo.id,
                "lease": lease_info,
            }
        run = MirrorSyncRun(
            repo_id=repo.id,
            trigger_type=trigger_type,
            status=MirrorSyncStatus.running,
            summary={},
            error="",
            started_at=_utc_now(),
        )
        db.add(run)
        repo.last_sync_status = MirrorSyncStatus.running
        await db.commit()
        await db.refresh(run)
        seen = _utc_now()
        repo_dir = Path(repo.mirror_path or "")
        if not repo_dir:
            repo_dir = MIRROR_BASE_DIR / f"{repo.id}-{_safe_dir_name(repo.name)}"
        repo_dir.mkdir(parents=True, exist_ok=True)
        inserted = 0
        updated = 0
        unchanged = 0
        downloaded = 0
        try:
            items, fetch_meta = await _fetch_catalog(repo)
            if fetch_meta.get("not_modified"):
                summary = {
                    "source_url": _effective_source_url(repo),
                    "items_seen": 0,
                    "inserted": 0,
                    "updated": 0,
                    "unchanged": 0,
                    "downloaded": 0,
                    "mirror_path": str(repo_dir),
                    "delta_skipped": True,
                    "checkpoint": fetch_meta,
                    "lease": lease_info,
                }
                extra = dict(repo.extra_config or {})
                extra["delta_checkpoint"] = fetch_meta
                repo.extra_config = extra
                repo.last_sync_at = _utc_now()
                repo.next_sync_at = _utc_now() + timedelta(minutes=max(repo.sync_interval_minutes, 5))
                repo.last_sync_status = MirrorSyncStatus.success
                repo.last_sync_summary = summary
                run.status = MirrorSyncStatus.success
                run.summary = summary
                run.completed_at = _utc_now()
                db.add(run)
                db.add(repo)
                await db.commit()
                return summary
            limit_downloads = int(str((repo.extra_config or {}).get("max_downloads_per_sync", 10)))
            for idx, item in enumerate(items):
                stmt = select(MirrorPackageIndex).where(
                    MirrorPackageIndex.repo_id == repo.id,
                    MirrorPackageIndex.package_name == item["package_name"],
                    MirrorPackageIndex.package_version == item["package_version"],
                    MirrorPackageIndex.architecture == item["architecture"],
                )
                existing = (await db.execute(stmt)).scalar_one_or_none()
                file_name = ""
                if not repo.metadata_only and downloaded < limit_downloads:
                    file_name = await _download_package(repo_dir, item) or ""
                    if file_name:
                        downloaded += 1
                if existing:
                    existing.last_seen_at = seen
                    existing_fp = hashlib.sha1(
                        json.dumps(
                            {
                                "source_url": existing.source_url or "",
                                "checksum": existing.checksum or "",
                                "meta": existing.package_meta or {},
                            },
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8"),
                        usedforsecurity=False,
                    ).hexdigest()
                    incoming_fp = hashlib.sha1(
                        json.dumps(
                            {
                                "source_url": item["source_url"] or "",
                                "checksum": item["checksum"] or "",
                                "meta": item["package_meta"] or {},
                            },
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8"),
                        usedforsecurity=False,
                    ).hexdigest()
                    if existing_fp != incoming_fp or file_name:
                        existing.source_url = item["source_url"]
                        existing.checksum = item["checksum"]
                        existing.package_meta = item["package_meta"]
                        if file_name:
                            existing.file_name = file_name
                        updated += 1
                    else:
                        unchanged += 1
                    db.add(existing)
                else:
                    db.add(
                        MirrorPackageIndex(
                            repo_id=repo.id,
                            package_name=item["package_name"],
                            package_version=item["package_version"],
                            os_family=repo.os_family,
                            channel=repo.channel,
                            architecture=item["architecture"],
                            source_url=item["source_url"],
                            file_name=file_name,
                            checksum=item["checksum"],
                            package_meta=item["package_meta"],
                            discovered_at=seen,
                            last_seen_at=seen,
                        )
                    )
                    inserted += 1
                if idx % 250 == 0:
                    await _heartbeat_repo_lease(db, repo)
            repo.last_sync_at = _utc_now()
            repo.next_sync_at = _utc_now() + timedelta(minutes=max(repo.sync_interval_minutes, 5))
            repo.last_sync_status = MirrorSyncStatus.success
            summary = {
                "source_url": _effective_source_url(repo),
                "items_seen": len(items),
                "inserted": inserted,
                "updated": updated,
                "unchanged": unchanged,
                "downloaded": downloaded,
                "mirror_path": str(repo_dir),
                "delta_skipped": False,
                "checkpoint": fetch_meta,
                "lease": lease_info,
            }
            extra = dict(repo.extra_config or {})
            extra["delta_checkpoint"] = fetch_meta
            repo.extra_config = extra
            run.status = MirrorSyncStatus.success
            run.summary = summary
            run.completed_at = _utc_now()
            repo.last_sync_summary = summary
            repo.mirror_path = str(repo_dir)
            db.add(run)
            db.add(repo)
            await db.commit()
            return summary
        except Exception as exc:
            run.status = MirrorSyncStatus.failed
            run.error = str(exc)
            run.summary = {
                "inserted": inserted,
                "updated": updated,
                "unchanged": unchanged,
                "downloaded": downloaded,
                "lease": lease_info,
            }
            run.completed_at = _utc_now()
            repo.last_sync_status = MirrorSyncStatus.failed
            repo.last_sync_summary = {"error": str(exc)}
            repo.next_sync_at = _utc_now() + timedelta(minutes=max(repo.sync_interval_minutes, 5))
            db.add(run)
            db.add(repo)
            await db.commit()
            raise
        finally:
            await _release_repo_lease(db, repo)


def _retention_candidates(
    repo: MirrorRepo,
    packages: list[MirrorPackageIndex],
    cutoff: datetime,
) -> tuple[set[int], list[dict[str, Any]]]:
    delete_ids: set[int] = set()
    details: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], list[MirrorPackageIndex]] = {}
    for pkg in packages:
        by_key.setdefault((pkg.package_name, pkg.architecture), []).append(pkg)
    for group in by_key.values():
        for idx, pkg in enumerate(group):
            remove_old_version = idx >= max(repo.keep_versions, 1)
            remove_by_age = bool(pkg.last_seen_at and pkg.last_seen_at < cutoff)
            if remove_old_version or remove_by_age:
                delete_ids.add(pkg.id)
                details.append(
                    {
                        "id": pkg.id,
                        "package_name": pkg.package_name,
                        "package_version": pkg.package_version,
                        "architecture": pkg.architecture,
                        "file_name": pkg.file_name,
                        "last_seen_at": pkg.last_seen_at,
                        "reason": "version_limit" if remove_old_version else "age_limit",
                    }
                )
    return delete_ids, details


async def execute_repo_retention(
    db: AsyncSession,
    repo: MirrorRepo,
    preview_only: bool = False,
    preview_limit: int = 200,
) -> dict[str, Any]:
    cutoff = _utc_now() - timedelta(days=max(repo.retention_days, 1))
    packages = (
        await db.execute(
            select(MirrorPackageIndex)
            .where(MirrorPackageIndex.repo_id == repo.id)
            .order_by(MirrorPackageIndex.package_name, MirrorPackageIndex.architecture, desc(MirrorPackageIndex.last_seen_at), desc(MirrorPackageIndex.id))
        )
    ).scalars().all()
    delete_ids, details = _retention_candidates(repo, packages, cutoff)
    preview = details[:max(preview_limit, 1)]
    if preview_only:
        return {
            "dry_run": True,
            "cutoff": cutoff,
            "would_remove_packages": len(delete_ids),
            "preview": preview,
        }
    removed_files = 0
    if delete_ids:
        to_remove = [pkg for pkg in packages if pkg.id in delete_ids and pkg.file_name]
        for pkg in to_remove:
            file_path = Path(repo.mirror_path or "") / pkg.file_name
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                    removed_files += 1
                except Exception:
                    pass
        await db.execute(delete(MirrorPackageIndex).where(MirrorPackageIndex.id.in_(delete_ids)))
        await db.commit()
    return {
        "dry_run": False,
        "cutoff": cutoff,
        "removed_packages": len(delete_ids),
        "removed_files": removed_files,
        "preview": preview,
    }


async def run_due_mirror_tasks(db: AsyncSession):
    await cleanup_stale_repo_leases(db)
    now = _utc_now()
    due_repos = (
        await db.execute(
            select(MirrorRepo).where(
                MirrorRepo.enabled == True,
                (MirrorRepo.next_sync_at.is_(None)) | (MirrorRepo.next_sync_at <= now),
            )
        )
    ).scalars().all()
    for repo in due_repos:
        try:
            await execute_repo_sync(db, repo, trigger_type="scheduler")
            await execute_repo_retention(db, repo)
        except Exception:
            continue


def schedule_auto_bootstrap_for_host(host_id: int, reason: str = "agent_active") -> bool:
    if not _AUTO_BOOTSTRAP_ON_AGENT_ACTIVE:
        return False
    now = _utc_now()
    key = f"{host_id}:{reason}"
    last = _AUTO_BOOTSTRAP_LAST_RUN.get(key)
    if last and (now - last).total_seconds() < _AUTO_BOOTSTRAP_COOLDOWN_SECONDS:
        return False
    _AUTO_BOOTSTRAP_LAST_RUN[key] = now
    async def _runner():
        await _bootstrap_and_sync_for_host_background(host_id, reason)
        return {"host_id": host_id, "reason": reason}
    asyncio.create_task(
        enqueue_operation(
            op_type="mirror.bootstrap_host",
            payload={"host_id": host_id, "reason": reason},
            runner=_runner,
            requested_by="system-auto",
        )
    )
    return True


async def _bootstrap_and_sync_for_host_background(host_id: int, reason: str):
    async with async_session() as db:
        host = await db.get(Host, host_id)
        if not host:
            return
        blueprints = _host_repo_blueprints(host)
        if not blueprints:
            return
        repos_to_sync: list[int] = []
        for blueprint in blueprints:
            repo = (
                await db.execute(
                    select(MirrorRepo).where(
                        MirrorRepo.provider == blueprint["provider"],
                        MirrorRepo.os_family == blueprint["os_family"],
                        MirrorRepo.channel == blueprint["channel"],
                    )
                )
            ).scalar_one_or_none()
            if repo is None:
                base_name = _safe_dir_name(blueprint["name"])
                candidate = base_name
                suffix = 2
                while (await db.execute(select(MirrorRepo.id).where(MirrorRepo.name == candidate))).scalar_one_or_none():
                    candidate = f"{base_name}-{suffix}"
                    suffix += 1
                repo = MirrorRepo(
                    name=candidate,
                    provider=blueprint["provider"],
                    os_family=blueprint["os_family"],
                    channel=blueprint["channel"],
                    source_url=str(blueprint.get("source_url", "")).strip(),
                    enabled=True,
                    metadata_only=True,
                    sync_interval_minutes=360,
                    retention_days=30,
                    keep_versions=2,
                    auth_config={},
                    extra_config=blueprint.get("extra_config", {}) or {},
                    created_by="system-auto",
                    next_sync_at=_utc_now(),
                    last_sync_status=MirrorSyncStatus.pending,
                    last_sync_summary={"auto_bootstrap_reason": reason},
                )
                db.add(repo)
                await db.flush()
                repo_dir = MIRROR_BASE_DIR / f"{repo.id}-{_safe_dir_name(repo.name)}"
                repo_dir.mkdir(parents=True, exist_ok=True)
                repo.mirror_path = str(repo_dir)
                db.add(repo)
            else:
                extra = dict(repo.extra_config or {})
                extra.update(blueprint.get("extra_config", {}) or {})
                repo.extra_config = extra
                if not repo.source_url and blueprint.get("source_url"):
                    repo.source_url = str(blueprint.get("source_url", "")).strip()
                repo.enabled = True
                repo.next_sync_at = _utc_now()
                db.add(repo)
            repos_to_sync.append(repo.id)
        await db.commit()
    for repo_id in repos_to_sync:
        async def _sync_runner(repo_id_value: int = repo_id):
            return await _run_manual_sync_background(repo_id_value, trigger_type="auto_bootstrap")
        await enqueue_operation(
            op_type="mirror.sync",
            payload={"repo_id": repo_id, "trigger_type": "auto_bootstrap", "reason": reason},
            runner=_sync_runner,
            requested_by="system-auto",
        )


async def _run_manual_sync_background(repo_id: int, trigger_type: str = "manual") -> dict[str, Any]:
    async with async_session() as db:
        repo = await db.get(MirrorRepo, repo_id)
        if not repo:
            return {"status": "missing", "repo_id": repo_id}
        return await execute_repo_sync(db, repo, trigger_type=trigger_type)


async def _fetch_host_package_data(host: Host) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Optional[str]]:
    if not host.ip:
        return [], [], "Host has no IP address"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            installed_resp = await client.get(f"http://{host.ip}:{AGENT_PORT}/packages/installed")
            upgradable_resp = await client.get(f"http://{host.ip}:{AGENT_PORT}/packages/upgradable")
        installed_payload = installed_resp.json() if installed_resp.status_code == 200 else {}
        upgradable_payload = upgradable_resp.json() if upgradable_resp.status_code == 200 else {}
        installed = installed_payload.get("packages", []) if isinstance(installed_payload, dict) else []
        upgradable = upgradable_payload.get("packages", []) if isinstance(upgradable_payload, dict) else []
        return (installed if isinstance(installed, list) else []), (upgradable if isinstance(upgradable, list) else []), None
    except Exception as exc:
        return [], [], str(exc)


@router.get("/repos", response_model=list[MirrorRepoResponse])
async def list_mirror_repos(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    repos = (await db.execute(select(MirrorRepo).order_by(MirrorRepo.name.asc()))).scalars().all()
    return [MirrorRepoResponse.from_orm_obj(repo) for repo in repos]


@router.post("/automation/bootstrap-sync")
async def bootstrap_and_sync_from_hosts(
    online_only: bool = Query(True),
    max_hosts: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    stmt = select(Host).order_by(Host.last_heartbeat.desc().nullslast(), Host.id.desc()).limit(max_hosts)
    if online_only:
        stmt = stmt.where(Host.is_online == True)
    hosts = (await db.execute(stmt)).scalars().all()
    scheduled = 0
    skipped = 0
    os_rollup: dict[str, int] = {}
    for host in hosts:
        os_key = (str(host.os or "unknown").split(" ", 1)[0] or "unknown").lower()
        os_rollup[os_key] = os_rollup.get(os_key, 0) + 1
        if schedule_auto_bootstrap_for_host(host.id, reason="manual_bootstrap"):
            scheduled += 1
        else:
            skipped += 1
    return {
        "status": "ok",
        "hosts_considered": len(hosts),
        "scheduled": scheduled,
        "skipped": skipped,
        "online_only": online_only,
        "os_rollup": os_rollup,
    }


@router.post("/repos", response_model=MirrorRepoResponse)
async def create_mirror_repo(
    body: MirrorRepoCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    try:
        provider = MirrorRepoProvider(body.provider)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid provider")
    exists = (await db.execute(select(MirrorRepo).where(MirrorRepo.name == body.name))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Repository name already exists")
    repo = MirrorRepo(
        name=body.name.strip(),
        provider=provider,
        os_family=(body.os_family or "linux").strip().lower(),
        channel=(body.channel or "default").strip(),
        source_url=(body.source_url or "").strip(),
        enabled=body.enabled,
        metadata_only=body.metadata_only,
        sync_interval_minutes=max(body.sync_interval_minutes, 5),
        retention_days=max(body.retention_days, 1),
        keep_versions=max(body.keep_versions, 1),
        auth_config=encrypt_json_field(body.auth_config),
        extra_config=body.extra_config or {},
        created_by=getattr(current_user, "username", "system"),
        next_sync_at=_utc_now() + timedelta(minutes=1),
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    repo_dir = MIRROR_BASE_DIR / f"{repo.id}-{_safe_dir_name(repo.name)}"
    repo_dir.mkdir(parents=True, exist_ok=True)
    repo.mirror_path = str(repo_dir)
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return MirrorRepoResponse.from_orm_obj(repo)


@router.put("/repos/{repo_id}", response_model=MirrorRepoResponse)
async def update_mirror_repo(
    repo_id: int,
    body: MirrorRepoUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    repo = await db.get(MirrorRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    data = body.model_dump(exclude_unset=True)
    if "provider" in data and data["provider"] is not None:
        try:
            repo.provider = MirrorRepoProvider(data["provider"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid provider")
        data.pop("provider")
    for key, value in data.items():
        if key in {"sync_interval_minutes", "retention_days", "keep_versions"} and value is not None:
            value = max(int(value), 1 if key != "sync_interval_minutes" else 5)
        if key == "auth_config":
            existing_auth = decrypt_json_field(repo.auth_config)
            incoming_auth = value or {}
            merged_auth = dict(existing_auth or {})
            for auth_key, auth_value in incoming_auth.items():
                if isinstance(auth_value, str):
                    auth_value = auth_value.strip()
                    if not auth_value:
                        continue
                if auth_value is None:
                    continue
                merged_auth[auth_key] = auth_value
            if merged_auth == (existing_auth or {}):
                continue
            value = encrypt_json_field(merged_auth)
        setattr(repo, key, value)
    if "name" in data and repo.name:
        repo_dir = MIRROR_BASE_DIR / f"{repo.id}-{_safe_dir_name(repo.name)}"
        repo_dir.mkdir(parents=True, exist_ok=True)
        repo.mirror_path = str(repo_dir)
    db.add(repo)
    await db.commit()
    await db.refresh(repo)
    return MirrorRepoResponse.from_orm_obj(repo)


@router.delete("/repos/{repo_id}")
async def delete_mirror_repo(
    repo_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    request_id = str(request.headers.get("x-request-id", "")).strip() or uuid.uuid4().hex
    trace_token = uuid.uuid4().hex
    try:
        repo = await db.get(MirrorRepo, repo_id)
        if not repo:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Repository not found",
                    "request_id": request_id,
                    "trace_token": trace_token,
                },
            )
        mirror_path = repo.mirror_path
        await db.execute(delete(MirrorSyncLease).where(MirrorSyncLease.repo_id == repo.id))
        await db.execute(delete(MirrorSyncRun).where(MirrorSyncRun.repo_id == repo.id))
        await db.execute(delete(MirrorPackageIndex).where(MirrorPackageIndex.repo_id == repo.id))
        await db.delete(repo)
        await db.commit()
        if mirror_path:
            path = Path(mirror_path)
            if path.exists() and path.is_dir():
                for child in path.glob("**/*"):
                    if child.is_file():
                        try:
                            child.unlink()
                        except Exception:
                            pass
                try:
                    path.rmdir()
                except Exception:
                    pass
        return {"message": "Mirror repository deleted", "request_id": request_id}
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Delete repository failed",
                "reason": str(exc),
                "request_id": request_id,
                "trace_token": trace_token,
            },
        )


@router.post("/repos/{repo_id}/sync")
async def manual_sync_repo(
    repo_id: int,
    request: Request,
    wait: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    repo = await db.get(MirrorRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not wait:
        request_id = str(getattr(getattr(request, "state", object()), "request_id", "") or "")
        trace_token = str(getattr(getattr(request, "state", object()), "trace_token", "") or "")
        async def _runner():
            return await _run_manual_sync_background(repo_id, trigger_type="manual")
        queue_job = await enqueue_operation(
            op_type="mirror.sync",
            payload={"repo_id": repo_id, "trigger_type": "manual"},
            runner=_runner,
            requested_by=getattr(current_user, "username", "system"),
            request_id=request_id or None,
            trace_token=trace_token or None,
        )
        return {
            "status": "accepted",
            "job": queue_job,
            "summary": {
                "status": "running",
                "repo_id": repo_id,
                "reason": "queued",
            },
        }
    summary = await execute_repo_sync(db, repo, trigger_type="manual")
    return {"status": "ok", "summary": summary}


@router.post("/repos/{repo_id}/retention")
async def run_repo_retention(
    repo_id: int,
    request: Request,
    wait: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    repo = await db.get(MirrorRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not wait:
        request_id = str(getattr(getattr(request, "state", object()), "request_id", "") or "")
        trace_token = str(getattr(getattr(request, "state", object()), "trace_token", "") or "")
        async def _runner():
            async with async_session() as session:
                repo_row = await session.get(MirrorRepo, repo_id)
                if not repo_row:
                    return {"status": "missing", "repo_id": repo_id}
                return await execute_repo_retention(session, repo_row)
        queue_job = await enqueue_operation(
            op_type="mirror.retention",
            payload={"repo_id": repo_id},
            runner=_runner,
            requested_by=getattr(current_user, "username", "system"),
            request_id=request_id or None,
            trace_token=trace_token or None,
        )
        return {"status": "accepted", "job": queue_job}
    summary = await execute_repo_retention(db, repo)
    return {"status": "ok", "summary": summary}


@router.get("/repos/{repo_id}/retention/preview")
async def preview_repo_retention(
    repo_id: int,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    repo = await db.get(MirrorRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    summary = await execute_repo_retention(db, repo, preview_only=True, preview_limit=limit)
    return {"status": "ok", "summary": summary}


@router.get("/repos/{repo_id}/runs", response_model=list[MirrorSyncRunResponse])
async def list_sync_runs(
    repo_id: int,
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = await db.get(MirrorRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    runs = (
        await db.execute(
            select(MirrorSyncRun)
            .where(MirrorSyncRun.repo_id == repo_id)
            .order_by(MirrorSyncRun.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [MirrorSyncRunResponse.from_orm_obj(run) for run in runs]


@router.get("/repos/{repo_id}/packages")
async def list_repo_packages(
    repo_id: int,
    q: str = "",
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = await db.get(MirrorRepo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    stmt = select(MirrorPackageIndex).where(MirrorPackageIndex.repo_id == repo_id)
    needle = q.strip()
    if needle:
        stmt = stmt.where(MirrorPackageIndex.package_name.ilike(f"%{needle}%"))
    rows = (
        await db.execute(
            stmt.order_by(MirrorPackageIndex.last_seen_at.desc(), MirrorPackageIndex.id.desc()).limit(limit)
        )
    ).scalars().all()
    items = [
        {
            "id": row.id,
            "package_name": row.package_name,
            "package_version": row.package_version,
            "architecture": row.architecture,
            "os_family": row.os_family,
            "channel": row.channel,
            "source_url": row.source_url,
            "file_name": row.file_name,
            "checksum": row.checksum,
            "fixed_version": (row.package_meta or {}).get("fixed_version", ""),
            "last_seen_at": row.last_seen_at,
        }
        for row in rows
    ]
    return {"items": items, "count": len(items)}


@router.get("/compare/host/{host_id}")
async def compare_host_against_catalog(
    host_id: int,
    repo_id: Optional[int] = None,
    q: str = "",
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    host = await db.get(Host, host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    installed, upgradable, fetch_error = await _fetch_host_package_data(host)
    os_hint = "windows" if "windows" in str(host.os or "").lower() else "linux"
    if repo_id:
        repo = await db.get(MirrorRepo, repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Mirror repository not found")
        repo_ids = [repo.id]
    else:
        repo_ids = [
            repo.id
            for repo in (
                await db.execute(select(MirrorRepo).where(MirrorRepo.enabled == True, MirrorRepo.os_family == os_hint))
            ).scalars().all()
        ]
    catalog_rows = []
    if repo_ids:
        stmt = select(MirrorPackageIndex).where(MirrorPackageIndex.repo_id.in_(repo_ids))
        needle = q.strip()
        if needle:
            stmt = stmt.where(MirrorPackageIndex.package_name.ilike(f"%{needle}%"))
        catalog_rows = (
            await db.execute(stmt.order_by(MirrorPackageIndex.package_name.asc(), MirrorPackageIndex.last_seen_at.desc()))
        ).scalars().all()
    catalog_latest: dict[str, MirrorPackageIndex] = {}
    for row in catalog_rows:
        key = str(row.package_name or "").lower()
        if key not in catalog_latest:
            catalog_latest[key] = row
    upgradable_map = {}
    for item in upgradable:
        name = str(item.get("name", "")).strip().lower()
        if name:
            upgradable_map[name] = item
    rows = []
    for pkg in installed:
        name = str(pkg.get("name", "")).strip()
        if not name:
            continue
        if q.strip() and q.strip().lower() not in name.lower():
            continue
        key = name.lower()
        catalog = catalog_latest.get(key)
        installed_version = str(pkg.get("version", "") or pkg.get("current_version", "")).strip()
        upg = upgradable_map.get(key)
        upgradable_version = str(upg.get("available_version", "")).strip() if upg else ""
        available_version = str(catalog.package_version).strip() if catalog else ""
        fixed_version = str((catalog.package_meta or {}).get("fixed_version", "")).strip() if catalog else ""
        if upg:
            status = "outdated"
        elif available_version and installed_version == available_version:
            status = "up_to_date"
        elif available_version and installed_version and installed_version != available_version:
            status = "behind_catalog"
        else:
            status = "not_in_catalog"
        rows.append(
            {
                "package_name": name,
                "installed_version": installed_version,
                "upgradable_version": upgradable_version,
                "catalog_version": available_version,
                "fixed_version": fixed_version,
                "status": status,
                "repo_id": catalog.repo_id if catalog else None,
            }
        )
    rows = rows[:limit]
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    return {
        "host": {"id": host.id, "hostname": host.hostname, "ip": host.ip, "os": host.os},
        "repo_scope": repo_ids,
        "totals": {
            "installed_count": len(installed),
            "upgradable_count": len(upgradable),
            "compared_count": len(rows),
            "status": status_counts,
        },
        "agent_fetch_error": fetch_error,
        "items": rows,
    }
