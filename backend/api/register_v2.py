"""Agent registration & heartbeat — persisted to PostgreSQL."""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid import uuid4
import os

from database import get_db
from models.db_models import Host, HostGroup, host_group_assoc
from prometheus_targets import sync_prometheus_agent_targets
from sqlalchemy import text

router = APIRouter(tags=["agent"])


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return ""


class RegisterRequest(BaseModel):
    agent_id: str = ""
    hostname: str
    os: str
    os_version: str
    kernel: str
    arch: str
    ip: str
    site: str = ""
    hardware_inventory: dict = Field(default_factory=dict)
    agent_version: str = ""


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean_ip(ip: str) -> str:
    return ip.split("/")[0].strip() if ip else ""


def _clean_agent_id(agent_id: str) -> str:
    return (agent_id or "").strip()


def _clean_site(site: str) -> str:
    return (site or "").strip()[:120]


def _clean_hardware_inventory(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    cleaned: dict[str, object] = {}
    for key in (
        "cpu_model",
        "cpu_cores",
        "memory_mb",
        "disk_total_gb",
        "platform_node",
        "boot_mode",
        "uefi_present",
        "secure_boot_enabled",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            cleaned[key] = value.strip()[:200]
        elif isinstance(value, (int, float)):
            cleaned[key] = value
        elif isinstance(value, bool):
            cleaned[key] = value
    return cleaned


def _schedule_mirror_automation_for_host(host_id: int, reason: str) -> None:
    try:
        from api.mirror_repos import schedule_auto_bootstrap_for_host

        schedule_auto_bootstrap_for_host(host_id, reason=reason)
    except Exception:
        return


OS_FAMILY_GROUPS = {
    "windows": ("Windows", "Windows hosts (WSUS/Windows Update)"),
    "debian": ("Debian/Ubuntu", "Debian family hosts (apt/dpkg)"),
    "rhel": ("RHEL/RPM", "RHEL family hosts (dnf/yum/rpm)"),
    "freebsd": ("FreeBSD", "FreeBSD hosts (pkg)"),
    "solaris": ("Solaris", "Solaris hosts (IPS/pkg)"),
    "hpux": ("HP-UX", "HP-UX hosts (SD-UX/swinstall)"),
    "aix": ("AIX", "AIX hosts (installp/NIM)"),
    # _detect_os_family() can return these too; a missing key 500s the whole
    # registration after the host row is created, so the agent never gets its
    # token (found by the S0-8 fleet's first Alpine registration).
    "arch": ("Arch", "Arch/Manjaro hosts (pacman)"),
    "alpine": ("Alpine", "Alpine hosts (apk)"),
    "opensuse": ("openSUSE", "openSUSE hosts (zypper)"),
    "other": ("Other", "Other/unknown OS family"),
}


def _detect_os_family(os_name: str) -> str:
    s = (os_name or "").strip().lower()
    if not s:
        return "other"
    if "windows" in s and "wsl" not in s and "subsystem" not in s:
        return "windows"
    # WSL detection - Windows Subsystem for Linux
    if "wsl" in s or "windows subsystem" in s or "microsoft" in s:
        # WSL is Linux-based, check the distro
        if any(x in s for x in ["ubuntu", "debian", "mint", "kali"]):
            return "debian"
        if any(x in s for x in ["rhel", "centos", "fedora", "rocky", "alma"]):
            return "rhel"
        return "debian"  # Default WSL to debian family
    if any(
        x in s for x in ["ubuntu", "debian", "linux mint", "pop!_os", "pop os", "kali"]
    ):
        return "debian"
    if any(
        x in s
        for x in [
            "red hat",
            "rhel",
            "centos",
            "rocky",
            "alma",
            "almalinux",
            "fedora",
            "oracle linux",
        ]
    ):
        return "rhel"
    if "freebsd" in s:
        return "freebsd"
    if "arch" in s or "manjaro" in s:
        return "arch"
    if "alpine" in s:
        return "alpine"
    if "suse" in s or "sles" in s:
        return "opensuse"
    # Oracle/Solaris detection
    if "solaris" in s or "opensolaris" in s or "oracle solaris" in s:
        return "solaris"
    if "sunos" in s:
        return "solaris"
    # HP-UX detection
    if "hp-ux" in s or "hpux" in s:
        return "hpux"
    # AIX detection
    if "aix" in s:
        return "aix"
    return "other"


async def _get_or_create_group(
    db: AsyncSession, name: str, description: str
) -> HostGroup:
    result = await db.execute(select(HostGroup).where(HostGroup.name == name))
    g = result.scalar_one_or_none()
    if g:
        return g
    g = HostGroup(name=name, description=description)
    db.add(g)
    await db.flush()
    return g


async def _ensure_host_schema(db: AsyncSession) -> None:
    """
    Defensive: on older databases some columns may be missing.
    Add the columns we need if they don't exist so registration won't 500.
    Safe to run repeatedly thanks to IF NOT EXISTS.
    """
    stmts = [
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS agent_id VARCHAR(100);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS site VARCHAR(120);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS hardware_inventory JSONB DEFAULT '{}'::jsonb;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS os_version VARCHAR(50);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS kernel VARCHAR(100);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS arch VARCHAR(20);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS agent_version VARCHAR(20);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS agent_token VARCHAR(100);",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS reboot_required BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS installed_count INTEGER DEFAULT 0;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS upgradable_count INTEGER DEFAULT 0;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS cve_count INTEGER DEFAULT 0;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS compliance_score FLOAT DEFAULT 100.0;",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();",
        "ALTER TABLE hosts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();",
    ]
    for stmt in stmts:
        try:
            await db.execute(text(stmt))
        except Exception:
            # If we don't have privilege or the column already exists, ignore.
            pass
    try:
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hosts_agent_id ON hosts(agent_id);")
        )
    except Exception:
        pass
    try:
        await db.execute(
            text("CREATE INDEX IF NOT EXISTS ix_hosts_site ON hosts(site);")
        )
    except Exception:
        pass


async def _ensure_os_family_group(db: AsyncSession, host: Host, os_name: str) -> None:
    family = _detect_os_family(os_name)
    group_name, desc = OS_FAMILY_GROUPS.get(family, OS_FAMILY_GROUPS["other"])
    desired = await _get_or_create_group(db, group_name, desc)
    family_names = {v[0] for v in OS_FAMILY_GROUPS.values()}
    state = sa_inspect(host)
    if state.pending or state.transient:
        existing = list(getattr(host, "groups", []) or [])
        kept = [g for g in existing if g.name not in family_names]
        host.groups = kept + [desired]
        return

    result = await db.execute(
        select(HostGroup)
        .join(host_group_assoc, HostGroup.id == host_group_assoc.c.group_id)
        .where(host_group_assoc.c.host_id == host.id)
    )
    existing = list(result.scalars().all())
    kept_ids = [g.id for g in existing if g.name not in family_names]
    desired_ids = list(dict.fromkeys(kept_ids + [desired.id]))

    await db.execute(
        delete(host_group_assoc).where(host_group_assoc.c.host_id == host.id)
    )
    for group_id in desired_ids:
        await db.execute(
            insert(host_group_assoc).values(host_id=host.id, group_id=group_id)
        )


def _effective_ip(request: Request, reported_ip: str) -> str:
    source = _clean_ip(getattr(getattr(request, "client", None), "host", ""))
    if source and source not in {"127.0.0.1", "::1", "localhost"}:
        return source
    return _clean_ip(reported_ip)


async def _find_host_by_agent_id(db: AsyncSession, agent_id: str):
    if not agent_id:
        return None
    result = await db.execute(
        select(Host).options(selectinload(Host.groups)).where(Host.agent_id == agent_id)
    )
    rows = result.scalars().all()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    # Duplicate agent_id rows — return the most recently updated one and log a warning
    import logging

    logging.getLogger("patchmaster.register").warning(
        "Duplicate agent_id '%s' found in %d rows — using most recent",
        agent_id,
        len(rows),
    )
    rows.sort(
        key=lambda x: x.updated_at or x.created_at or _utcnow_naive(), reverse=True
    )
    return rows[0]


async def _find_legacy_host(
    db: AsyncSession, hostname: str, ip: str, incoming_agent_id: str = ""
):
    """
    Legacy fallback: find a host by IP or hostname.
    NEVER merges two hosts that both have distinct non-empty agent_ids —
    that would collapse Windows + WSL (or any two agents on the same machine) into one row.
    """
    if ip:
        result = await db.execute(
            select(Host).options(selectinload(Host.groups)).where(Host.ip == ip)
        )
        hosts = result.scalars().all()
        if hosts:
            clean_name = (hostname or "").strip().lower()
            # If the caller has an agent_id, exclude any host that already has a
            # *different* non-empty agent_id — those are distinct agents on the same IP.
            if incoming_agent_id:
                hosts = [
                    h
                    for h in hosts
                    if not h.agent_id or h.agent_id == incoming_agent_id
                ]
            if not hosts:
                return None
            exact_name = [
                h
                for h in hosts
                if (h.hostname or "").strip().lower() == clean_name and clean_name
            ]
            if exact_name:
                exact_name.sort(
                    key=lambda x: x.updated_at or x.created_at or _utcnow_naive(),
                    reverse=True,
                )
                return exact_name[0]
            hosts.sort(
                key=lambda x: x.updated_at or x.created_at or _utcnow_naive(),
                reverse=True,
            )
            return hosts[0]
    if hostname:
        result = await db.execute(
            select(Host)
            .options(selectinload(Host.groups))
            .where(Host.hostname == hostname)
        )
        h = result.scalar_one_or_none()
        if h and incoming_agent_id and h.agent_id and h.agent_id != incoming_agent_id:
            return None
        return h
    return None


async def _allocate_hostname(db: AsyncSession, base_hostname: str, os_name: str) -> str:
    base = (base_hostname or "host").strip() or "host"
    result = await db.execute(select(Host.id).where(Host.hostname == base))
    if not result.first():
        return base

    family = _detect_os_family(os_name)
    suffix = {
        "windows": "windows",
        "debian": "linux",
        "rhel": "linux",
        "freebsd": "freebsd",
        "solaris": "solaris",
        "hpux": "hpux",
        "aix": "aix",
        "arch": "arch",
        "alpine": "alpine",
        "opensuse": "opensuse",
        "other": "agent",
    }[family]
    candidate = f"{base}-{suffix}"
    idx = 2
    while True:
        result = await db.execute(select(Host.id).where(Host.hostname == candidate))
        if not result.first():
            return candidate
        candidate = f"{base}-{suffix}-{idx}"
        idx += 1


@router.post("/api/register")
async def register_agent(
    req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    try:
        agent_token = str(uuid4())
        clean_ip = _effective_ip(request, req.ip)
        clean_agent_id = _clean_agent_id(req.agent_id)
        clean_site = _clean_site(req.site)
        clean_hardware_inventory = _clean_hardware_inventory(req.hardware_inventory)
        host = await _find_host_by_agent_id(db, clean_agent_id)
        if not host:
            host = await _find_legacy_host(
                db, req.hostname, clean_ip, incoming_agent_id=clean_agent_id
            )

        if host:
            # Credential gate (plan S0-1): only the holder of the current
            # per-host token, or the operator's AGENT_API_TOKEN, may update an
            # existing host or obtain a rotated token. Bootstrap (no token yet)
            # stays open — a one-time enrolment token is a later plan item.
            presented = _bearer_token(request)
            host_token = (host.agent_token or "").strip()
            if host_token and presented != host_token:
                shared = os.getenv("AGENT_API_TOKEN", "").strip()
                if not (shared and presented == shared):
                    raise HTTPException(status_code=401, detail="unauthorized")
            if clean_agent_id:
                host.agent_id = clean_agent_id
            # Update hostname even if it exists (agent may have renamed itself)
            if req.hostname:
                host.hostname = req.hostname
            host.ip = clean_ip or host.ip
            if clean_site:
                host.site = clean_site
            if clean_hardware_inventory:
                host.hardware_inventory = clean_hardware_inventory
            host.os = req.os or host.os
            host.os_version = req.os_version or host.os_version
            host.kernel = req.kernel or host.kernel
            host.arch = req.arch or host.arch
            host.agent_version = req.agent_version or host.agent_version
            if not (host_token and presented == host_token):
                # Mint only for tokenless hosts or an authenticated rotation;
                # a holder of the current token is never rotated.
                host.agent_token = agent_token
            host.is_online = True
            host.last_heartbeat = _utcnow_naive()
            await _ensure_os_family_group(db, host, req.os)
        else:
            host = Host(
                hostname=await _allocate_hostname(db, req.hostname, req.os),
                ip=clean_ip,
                site=clean_site,
                hardware_inventory=clean_hardware_inventory,
                agent_id=clean_agent_id,
                os=req.os,
                os_version=req.os_version,
                kernel=req.kernel,
                arch=req.arch,
                agent_version=req.agent_version or "",
                agent_token=agent_token,
                is_online=True,
                last_heartbeat=_utcnow_naive(),
            )
            db.add(host)
            await _ensure_os_family_group(db, host, req.os)

        await db.flush()
        if host and host.id:
            _schedule_mirror_automation_for_host(host.id, reason="agent_register")
        try:
            await sync_prometheus_agent_targets(db)
        except Exception as exc:
            import logging as _log

            _log.getLogger("patchmaster.register").warning(
                "Prometheus target sync failed (register): %s", exc
            )
        await db.commit()
        return {"agent_token": host.agent_token}
    except HTTPException:
        raise
    except Exception:
        import logging

        logging.getLogger("patchmaster.register").exception("Register failed")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("registration failed", status_code=500)


@router.post("/api/heartbeat")
async def heartbeat(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        body = await request.json()
        ip = _effective_ip(request, body.get("ip", ""))
        agent_id = _clean_agent_id(body.get("agent_id", ""))
        agent_token = str(body.get("agent_token") or "").strip()
        hostname = body.get("hostname", "")
        os_name = body.get("os", "")
        os_version = body.get("os_version", "")
        kernel = body.get("kernel", "")
        arch = body.get("arch", "")
        site = _clean_site(body.get("site", ""))
        hardware_inventory = _clean_hardware_inventory(
            body.get("hardware_inventory", {})
        )
        agent_version = body.get("agent_version", "")

        host = await _find_host_by_agent_id(db, agent_id)
        if not host:
            host = await _find_legacy_host(db, hostname, ip, incoming_agent_id=agent_id)

        # Heartbeat is update-only — never create a new host row
        if not host:
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("not found", status_code=404)

        # Require a matching agent_token.
        # Legacy hosts (created before token support) have no stored token — they
        # must re-register via /api/register to obtain one before heartbeat works.
        if not agent_token or not host.agent_token or host.agent_token != agent_token:
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse("unauthorized", status_code=401)

        if agent_id:
            host.agent_id = agent_id
        host.ip = ip or host.ip
        if site:
            host.site = site
        if hardware_inventory:
            host.hardware_inventory = hardware_inventory
        if hostname and hostname != host.hostname and not host.agent_id:
            host.hostname = hostname
        host.os = os_name or host.os
        host.os_version = os_version or host.os_version
        host.kernel = kernel or host.kernel
        host.arch = arch or host.arch
        host.agent_version = agent_version or host.agent_version
        host.is_online = True
        host.last_heartbeat = _utcnow_naive()
        await _ensure_os_family_group(db, host, host.os)

        await db.flush()
        if host and host.id:
            _schedule_mirror_automation_for_host(host.id, reason="agent_heartbeat")
        try:
            await sync_prometheus_agent_targets(db)
        except Exception as exc:
            import logging as _log

            _log.getLogger("patchmaster.register").warning(
                "Prometheus target sync failed (heartbeat): %s", exc
            )

        await db.commit()
        return {"status": "ok"}
    except Exception:
        import logging

        logging.getLogger("patchmaster.register").exception("Heartbeat failed")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("heartbeat failed", status_code=500)
