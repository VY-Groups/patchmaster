import io
import hashlib
import json
import tarfile
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.agent_proxy import _agent_auth_headers as _relay_agent_headers
from api.agent_proxy import _agent_url_for_host_id
from api.ops_queue import enqueue_operation
from auth import get_current_user, require_role
from database import async_session, get_db
from models.db_models import (
    BootEvent,
    BootRelay,
    BootRelayRun,
    BootSession,
    Host,
    MirrorRepo,
    NetworkBootAssignment,
    NetworkBootNetwork,
    NetworkBootProfile,
    Policy,
    ProvisioningTemplate,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/network-boot", tags=["network-boot"])
public_router = APIRouter(prefix="/boot/network-boot", tags=["network-boot-public"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _ensure_network_boot_schema(db: AsyncSession) -> None:
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS boot_relays (
            id SERIAL PRIMARY KEY,
            host_id INTEGER NOT NULL UNIQUE REFERENCES hosts(id) ON DELETE CASCADE,
            name VARCHAR(160) NOT NULL UNIQUE,
            site_scope VARCHAR(120) DEFAULT '',
            install_root VARCHAR(255) DEFAULT '/var/lib/patchmaster/network-boot',
            public_base_url VARCHAR(255) DEFAULT '',
            notes TEXT DEFAULT '',
            is_enabled BOOLEAN DEFAULT TRUE,
            status VARCHAR(24) DEFAULT 'idle',
            applied_version VARCHAR(64) DEFAULT '',
            rendered_config_checksum VARCHAR(128) DEFAULT '',
            last_install_at TIMESTAMP NULL,
            last_sync_at TIMESTAMP NULL,
            last_validation_at TIMESTAMP NULL,
            last_validation_status VARCHAR(24) DEFAULT '',
            created_by VARCHAR(100) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS network_boot_networks (
            id SERIAL PRIMARY KEY,
            name VARCHAR(160) NOT NULL UNIQUE,
            interface_name VARCHAR(120) DEFAULT '',
            vlan_id INTEGER NULL,
            cidr VARCHAR(64) DEFAULT '',
            gateway VARCHAR(64) DEFAULT '',
            dns_servers JSONB DEFAULT '[]'::jsonb,
            dhcp_range_start VARCHAR(64) DEFAULT '',
            dhcp_range_end VARCHAR(64) DEFAULT '',
            next_server VARCHAR(255) DEFAULT '',
            controller_url VARCHAR(255) DEFAULT '',
            relay_id INTEGER NULL REFERENCES boot_relays(id) ON DELETE SET NULL,
            artifact_version VARCHAR(64) DEFAULT '',
            rendered_config_checksum VARCHAR(128) DEFAULT '',
            last_rendered_at TIMESTAMP NULL,
            last_validated_at TIMESTAMP NULL,
            last_validation_status VARCHAR(24) DEFAULT '',
            boot_file_bios VARCHAR(255) DEFAULT 'undionly.kpxe',
            boot_file_uefi VARCHAR(255) DEFAULT 'ipxe.efi',
            is_enabled BOOLEAN DEFAULT TRUE,
            created_by VARCHAR(100) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS network_boot_profiles (
            id SERIAL PRIMARY KEY,
            name VARCHAR(160) NOT NULL UNIQUE,
            network_id INTEGER NULL REFERENCES network_boot_networks(id) ON DELETE SET NULL,
            provisioning_template_id INTEGER NULL REFERENCES provisioning_templates(id) ON DELETE SET NULL,
            mirror_repo_id INTEGER NULL REFERENCES mirror_repos(id) ON DELETE SET NULL,
            os_family VARCHAR(40) DEFAULT '',
            os_version VARCHAR(80) DEFAULT '',
            architecture VARCHAR(40) DEFAULT 'x86_64',
            firmware_mode VARCHAR(24) DEFAULT 'uefi',
            install_mode VARCHAR(40) DEFAULT 'ubuntu_autoinstall',
            kernel_url VARCHAR(500) DEFAULT '',
            initrd_url VARCHAR(500) DEFAULT '',
            rootfs_url VARCHAR(500) DEFAULT '',
            answer_template TEXT DEFAULT '',
            post_install_script TEXT DEFAULT '',
            is_enabled BOOLEAN DEFAULT TRUE,
            release_label VARCHAR(40) DEFAULT 'stable',
            created_by VARCHAR(100) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS network_boot_assignments (
            id SERIAL PRIMARY KEY,
            host_id INTEGER NULL REFERENCES hosts(id) ON DELETE SET NULL,
            network_id INTEGER NOT NULL REFERENCES network_boot_networks(id) ON DELETE CASCADE,
            profile_id INTEGER NOT NULL REFERENCES network_boot_profiles(id) ON DELETE CASCADE,
            hostname VARCHAR(255) DEFAULT '',
            mac_address VARCHAR(32) NOT NULL UNIQUE,
            reserved_ip VARCHAR(64) DEFAULT '',
            firmware_mode VARCHAR(24) DEFAULT 'uefi',
            boot_once BOOLEAN DEFAULT TRUE,
            is_enabled BOOLEAN DEFAULT TRUE,
            site_scope VARCHAR(120) DEFAULT '',
            created_by VARCHAR(100) DEFAULT '',
            last_boot_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS boot_sessions (
            id SERIAL PRIMARY KEY,
            session_token VARCHAR(64) NOT NULL UNIQUE,
            assignment_id INTEGER NULL REFERENCES network_boot_assignments(id) ON DELETE SET NULL,
            profile_id INTEGER NULL REFERENCES network_boot_profiles(id) ON DELETE SET NULL,
            network_id INTEGER NULL REFERENCES network_boot_networks(id) ON DELETE SET NULL,
            relay_id INTEGER NULL REFERENCES boot_relays(id) ON DELETE SET NULL,
            host_id INTEGER NULL REFERENCES hosts(id) ON DELETE SET NULL,
            mac_address VARCHAR(32) DEFAULT '',
            hostname VARCHAR(255) DEFAULT '',
            controller_url VARCHAR(255) DEFAULT '',
            current_stage VARCHAR(40) DEFAULT 'assignment_served',
            status VARCHAR(24) DEFAULT 'active',
            provisioning_source VARCHAR(80) DEFAULT '',
            event_count INTEGER DEFAULT 0,
            result_summary JSONB DEFAULT '{}'::jsonb,
            started_at TIMESTAMP DEFAULT NOW(),
            last_event_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS boot_events (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES boot_sessions(id) ON DELETE CASCADE,
            event_type VARCHAR(64) NOT NULL,
            source VARCHAR(40) DEFAULT '',
            message TEXT DEFAULT '',
            payload JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS boot_relay_runs (
            id SERIAL PRIMARY KEY,
            relay_id INTEGER NOT NULL REFERENCES boot_relays(id) ON DELETE CASCADE,
            action VARCHAR(24) NOT NULL,
            status VARCHAR(24) DEFAULT 'pending',
            requested_by VARCHAR(100) DEFAULT '',
            queue_job_id VARCHAR(64) DEFAULT '',
            payload JSONB DEFAULT '{}'::jsonb,
            result_summary JSONB DEFAULT '{}'::jsonb,
            started_at TIMESTAMP NULL,
            completed_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_network_boot_networks_enabled ON network_boot_networks(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_network_boot_profiles_enabled ON network_boot_profiles(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_network_boot_profiles_release ON network_boot_profiles(release_label);",
        "CREATE INDEX IF NOT EXISTS ix_network_boot_assignments_enabled ON network_boot_assignments(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_network_boot_assignments_network_profile ON network_boot_assignments(network_id, profile_id);",
        "CREATE INDEX IF NOT EXISTS ix_boot_relays_enabled ON boot_relays(is_enabled);",
        "CREATE INDEX IF NOT EXISTS ix_boot_relays_status ON boot_relays(status);",
        "CREATE INDEX IF NOT EXISTS ix_boot_sessions_status ON boot_sessions(status);",
        "CREATE INDEX IF NOT EXISTS ix_boot_sessions_stage ON boot_sessions(current_stage);",
        "CREATE INDEX IF NOT EXISTS ix_boot_sessions_assignment ON boot_sessions(assignment_id);",
        "CREATE INDEX IF NOT EXISTS ix_boot_events_session_created ON boot_events(session_id, created_at);",
        "CREATE INDEX IF NOT EXISTS ix_boot_relay_runs_relay_action ON boot_relay_runs(relay_id, action);",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS controller_url VARCHAR(255) DEFAULT '';",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS relay_id INTEGER NULL REFERENCES boot_relays(id) ON DELETE SET NULL;",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS artifact_version VARCHAR(64) DEFAULT '';",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS rendered_config_checksum VARCHAR(128) DEFAULT '';",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS last_rendered_at TIMESTAMP NULL;",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMP NULL;",
        "ALTER TABLE network_boot_networks ADD COLUMN IF NOT EXISTS last_validation_status VARCHAR(24) DEFAULT '';",
        "ALTER TABLE network_boot_profiles ADD COLUMN IF NOT EXISTS mirror_repo_id INTEGER NULL REFERENCES mirror_repos(id) ON DELETE SET NULL;",
        "ALTER TABLE network_boot_profiles ADD COLUMN IF NOT EXISTS release_label VARCHAR(40) DEFAULT 'stable';",
        "UPDATE network_boot_profiles SET release_label = COALESCE(NULLIF(TRIM(release_label), ''), 'stable');",
    ]
    for stmt in stmts:
        await db.execute(text(stmt))


def _normalize_list(values: list[str] | None) -> list[str]:
    normalized = []
    for raw in values or []:
        value = str(raw or "").strip()
        if value and value not in normalized:
            normalized.append(value[:120])
    return normalized


def _normalize_install_mode(value: str | None) -> str:
    mode = str(value or "ubuntu_autoinstall").strip().lower()
    allowed = {"ubuntu_autoinstall", "rocky_kickstart", "windows_autounattend", "image_restore"}
    return mode if mode in allowed else "ubuntu_autoinstall"


def _normalize_firmware_mode(value: str | None) -> str:
    mode = str(value or "uefi").strip().lower()
    return mode if mode in {"bios", "uefi", "mixed"} else "uefi"


def _normalize_mac_address(value: str | None) -> str:
    raw = "".join(ch for ch in str(value or "").lower() if ch.isalnum())
    if len(raw) != 12 or any(ch not in "0123456789abcdef" for ch in raw):
        raise HTTPException(status_code=400, detail="MAC address must contain 12 hexadecimal characters")
    return ":".join(raw[idx : idx + 2] for idx in range(0, 12, 2))


def _shell_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _boot_base_url(network: NetworkBootNetwork | None) -> str:
    next_server = str(getattr(network, "next_server", "") or "").strip()
    if next_server.startswith("http://") or next_server.startswith("https://"):
        return next_server.rstrip("/")
    if next_server:
        return f"http://{next_server.rstrip('/')}"
    return "http://patchmaster-boot.local"


def _network_server_name(network: NetworkBootNetwork | None) -> str:
    raw = str(getattr(network, "next_server", "") or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        return parsed.hostname or "patchmaster-boot.local"
    if raw:
        return raw.split("/")[0].split(":")[0]
    return "patchmaster-boot.local"


def _controller_api_base(network: NetworkBootNetwork | None) -> str:
    explicit = str(getattr(network, "controller_url", "") or "").strip()
    if explicit:
        if explicit.startswith("http://") or explicit.startswith("https://"):
            return explicit.rstrip("/")
        return f"http://{explicit.rstrip('/')}"
    raw = str(getattr(network, "next_server", "") or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "patchmaster-boot.local"
        port = parsed.port
        if port in (None, 3000):
            return f"{scheme}://{host}:8000" if scheme == "http" else f"{scheme}://{host}"
        if scheme == "https" and port == 443:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"
    if raw:
        return f"http://{raw}:8000" if ":" not in raw else f"http://{raw}"
    return "http://patchmaster.local:8000"


def _controller_health_url(network: NetworkBootNetwork | None) -> str:
    return f"{_controller_api_base(network)}/api/health"


def _boot_events_url(network: NetworkBootNetwork | None) -> str:
    return f"{_controller_api_base(network)}/api/network-boot/events"


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _artifact_version_payload(
    network: NetworkBootNetwork | None,
    profiles: list[NetworkBootProfile],
    assignments: list[NetworkBootAssignment],
) -> dict[str, Any]:
    return {
        "network": {
            "id": getattr(network, "id", None),
            "name": getattr(network, "name", ""),
            "next_server": getattr(network, "next_server", ""),
            "controller_url": getattr(network, "controller_url", ""),
            "relay_id": getattr(network, "relay_id", None),
        },
        "profiles": [
            {
                "id": profile.id,
                "name": profile.name,
                "install_mode": profile.install_mode,
                "kernel_url": profile.kernel_url,
                "initrd_url": profile.initrd_url,
                "rootfs_url": profile.rootfs_url,
                "mirror_repo_id": getattr(profile, "mirror_repo_id", None),
            }
            for profile in profiles
        ],
        "assignments": [
            {
                "id": assignment.id,
                "mac_address": assignment.mac_address,
                "reserved_ip": assignment.reserved_ip,
                "hostname": assignment.hostname,
            }
            for assignment in assignments
        ],
    }


def _artifact_version_details(
    network: NetworkBootNetwork | None,
    profiles: list[NetworkBootProfile],
    assignments: list[NetworkBootAssignment],
) -> tuple[str, str]:
    payload = _artifact_version_payload(network, profiles, assignments)
    checksum = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return f"nb-{checksum[:12]}", checksum


def _mirror_repo_ready(repo: MirrorRepo | None) -> bool:
    if not repo:
        return False
    if not bool(getattr(repo, "enabled", False)):
        return False
    if not str(getattr(repo, "source_url", "") or "").strip():
        return False
    status = str(getattr(repo, "last_sync_status", "") or "").lower()
    return status in {"success", "completed", "synced"}


def _mirror_repo_public(repo: MirrorRepo | None) -> dict[str, Any] | None:
    if not repo:
        return None
    return {
        "id": repo.id,
        "name": repo.name,
        "provider": repo.provider.value if hasattr(repo.provider, "value") else str(repo.provider),
        "source_url": repo.source_url or "",
        "enabled": bool(repo.enabled),
        "last_sync_status": repo.last_sync_status.value if hasattr(repo.last_sync_status, "value") else str(repo.last_sync_status),
        "last_sync_at": repo.last_sync_at.isoformat() if repo.last_sync_at else None,
        "is_ready": _mirror_repo_ready(repo),
    }


def _network_urls(network: NetworkBootNetwork) -> dict[str, str]:
    base = _boot_base_url(network)
    root = f"{base}/boot/network-boot/networks/{network.id}"
    return {"root": root, "menu": f"{root}/menu.ipxe"}


def _artifact_urls(profile: NetworkBootProfile, network: NetworkBootNetwork | None) -> dict[str, str]:
    base = _boot_base_url(network)
    profile_root = f"{base}/boot/network-boot/profiles/{profile.id}"
    return {
        "profile_root": profile_root,
        "ipxe": f"{profile_root}/boot.ipxe",
        "answer": f"{profile_root}/answer",
    }


def _assignment_urls(assignment: NetworkBootAssignment) -> dict[str, str]:
    base = _boot_base_url(assignment.network)
    assignment_root = f"{base}/boot/network-boot/assignments/{assignment.id}"
    return {
        "assignment_root": assignment_root,
        "ipxe": f"{assignment_root}/boot.ipxe",
        "answer": f"{assignment_root}/answer",
    }


def _session_assignment_urls(assignment: NetworkBootAssignment, session_token: str) -> dict[str, str]:
    urls = _assignment_urls(assignment)
    return {
        **urls,
        "ipxe": f"{urls['ipxe']}?session={session_token}",
        "answer": f"{urls['answer']}?session={session_token}",
    }


def _event_report_command(
    event_url: str,
    session_token: str,
    event_type: str,
    source: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    if not session_token:
        return "true"
    body: dict[str, Any] = {
        "session_token": session_token,
        "event_type": event_type,
        "source": source,
    }
    if message:
        body["message"] = message
    if payload:
        body["payload"] = payload
    return (
        "curl -fsS -X POST -H 'Content-Type: application/json' "
        f"--data-binary {_shell_single_quote(json.dumps(body, sort_keys=True))} "
        f"{_shell_single_quote(event_url)} >/dev/null 2>&1 || true"
    )


def _event_report_powershell(
    event_url: str,
    session_token: str,
    event_type: str,
    source: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    if not session_token:
        return ""
    body: dict[str, Any] = {
        "session_token": session_token,
        "event_type": event_type,
        "source": source,
    }
    if message:
        body["message"] = message
    if payload:
        body["payload"] = payload
    json_body = json.dumps(body, sort_keys=True).replace("'", "''")
    return (
        "try {"
        f" $pmBody = '{json_body}';"
        f" Invoke-WebRequest -UseBasicParsing -Method POST -Uri '{event_url}'"
        " -ContentType 'application/json' -Body $pmBody | Out-Null;"
        "} catch {}"
    )


def _site_scope(profile: NetworkBootProfile, assignment: NetworkBootAssignment | None = None) -> str:
    assignment_scope = getattr(assignment, "site_scope", "") if assignment else ""
    if assignment_scope:
        return str(assignment_scope).strip()
    template = getattr(profile, "provisioning_template", None)
    return str(getattr(template, "site_scope", "") or "").strip()


def _default_answer_template(
    profile: NetworkBootProfile,
    network: NetworkBootNetwork | None = None,
    assignment: NetworkBootAssignment | None = None,
    session_token: str = "",
) -> str:
    mode = _normalize_install_mode(profile.install_mode)
    template = profile.provisioning_template
    controller_url = _controller_api_base(network)
    events_url = _boot_events_url(network)
    site_scope = _site_scope(profile, assignment)
    installer_started_cmd = _event_report_command(
        events_url,
        session_token,
        "installer_started",
        "answer_template",
        f"{mode} workflow started",
    )
    first_boot_cmd = _event_report_command(
        events_url,
        session_token,
        "first_boot_reached",
        "answer_template",
        "First-boot enrollment stage reached",
    )
    enrollment_success_cmd = _event_report_command(
        events_url,
        session_token,
        "enrollment_succeeded",
        "answer_template",
        "Patch-SecOps Solution agent enrollment completed",
    )
    enrollment_failed_cmd = _event_report_command(
        events_url,
        session_token,
        "enrollment_failed",
        "answer_template",
        "Patch-SecOps Solution agent enrollment failed",
    )
    linux_agent_cmd = (
        f"curl -fsSL {_shell_single_quote(controller_url + '/static/install-agent.sh')} "
        f"-o /tmp/patchmaster-install-agent.sh && chmod +x /tmp/patchmaster-install-agent.sh && "
        f"MASTER_URL={_shell_single_quote(controller_url)} "
        f"{f'PATCHMASTER_SITE={_shell_single_quote(site_scope)} ' if site_scope else ''}"
        "/tmp/patchmaster-install-agent.sh"
    )
    linux_enrollment_cmd = (
        f"{first_boot_cmd}; "
        f"if {linux_agent_cmd}; then {enrollment_success_cmd}; else {enrollment_failed_cmd}; fi"
    )
    windows_site_arg = f" -Site '{site_scope}'" if site_scope else ""
    windows_started = _event_report_powershell(
        events_url,
        session_token,
        "first_boot_reached",
        "answer_template",
        "Windows first-logon enrollment stage reached",
    )
    windows_success = _event_report_powershell(
        events_url,
        session_token,
        "enrollment_succeeded",
        "answer_template",
        "Windows agent enrollment completed",
    )
    windows_failed = _event_report_powershell(
        events_url,
        session_token,
        "enrollment_failed",
        "answer_template",
        "Windows agent enrollment failed",
    )
    windows_agent_cmd = (
        "powershell -ExecutionPolicy Bypass -Command "
        f"\"{windows_started}; "
        f"Invoke-WebRequest -UseBasicParsing -Uri '{controller_url}/static/install-agent.ps1' "
        f"-OutFile C:\\Windows\\Temp\\install-agent.ps1; "
        f"& C:\\Windows\\Temp\\install-agent.ps1 -MasterUrl '{controller_url}'{windows_site_arg}; "
        f"if ($LASTEXITCODE -eq 0) {{ {windows_success} }} else {{ {windows_failed} }}\""
    )
    if mode == "ubuntu_autoinstall":
        return f"""#cloud-config
autoinstall:
  version: 1
  early-commands:
    - /bin/bash -lc "{installer_started_cmd}"
  identity:
    hostname: patchmaster-ubuntu
    username: patchmaster
    password: "$6$replace-me"
  locale: en_US.UTF-8
  keyboard:
    layout: us
  storage:
    layout:
      name: direct
  late-commands:
    - curtin in-target -- /bin/bash -lc "{linux_enrollment_cmd}"
"""
    if mode == "rocky_kickstart":
        return f"""lang en_US.UTF-8
keyboard us
timezone UTC --utc
rootpw --plaintext changeme
reboot
url --url={profile.rootfs_url or "http://mirror.local/rocky"}
bootloader --location=mbr
clearpart --all --initlabel
autopart
%pre
{installer_started_cmd}
%end
%packages
@^minimal-environment
%end
%post
{linux_enrollment_cmd}
%end
"""
    if mode == "windows_autounattend":
        return f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <DiskConfiguration>
        <WillShowUI>OnError</WillShowUI>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallToAvailablePartition>true</InstallToAvailablePartition>
        </OSImage>
      </ImageInstall>
      <UserData>
        <AcceptEula>true</AcceptEula>
        <FullName>Patch-SecOps Solution</FullName>
        <Organization>VYGROUP</Organization>
      </UserData>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
      <AutoLogon>
        <Enabled>true</Enabled>
        <LogonCount>1</LogonCount>
        <Username>Administrator</Username>
      </AutoLogon>
      <FirstLogonCommands>
        <SynchronousCommand wcm:action="add" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
          <Order>1</Order>
          <Description>Enroll Patch-SecOps Solution agent</Description>
          <CommandLine>{windows_agent_cmd}</CommandLine>
        </SynchronousCommand>
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
"""
    template_name = template.name if template else "golden-image-template"
    return json.dumps(
        {
            "mode": "image_restore",
        "template_name": template_name,
        "controller_url": controller_url,
        "agent_install_url": f"{controller_url}/static/install-agent.sh",
        "event_report_url": events_url,
        "session_token": session_token,
        "site_scope": site_scope,
        "note": "Boot into a live restore environment, restore the stored template, then install the Patch-SecOps Solution agent on first boot.",
    },
        indent=2,
    )


def _render_ipxe_script(
    profile: NetworkBootProfile,
    network: NetworkBootNetwork | None,
    assignment: NetworkBootAssignment | None = None,
    session_token: str = "",
) -> str:
    urls = (
        _session_assignment_urls(assignment, session_token)
        if assignment and session_token
        else (_assignment_urls(assignment) if assignment else _artifact_urls(profile, network))
    )
    mode = _normalize_install_mode(profile.install_mode)
    assignment_firmware = getattr(assignment, "firmware_mode", "") if assignment else ""
    firmware = _normalize_firmware_mode(assignment_firmware or profile.firmware_mode)
    lines = [
        "#!ipxe",
        f"# Patch-SecOps Solution network boot profile: {profile.name}",
        f"# Firmware mode: {firmware}",
    ]
    if assignment:
        lines.extend(
            [
                f"# Assignment hostname: {assignment.hostname or 'unassigned'}",
                f"# Assignment MAC: {assignment.mac_address}",
                f"set pm-assignment-id {assignment.id}",
                f"set pm-assignment-hostname {assignment.hostname or assignment.mac_address.replace(':', '-')}",
            ]
        )
        if session_token:
            lines.append(f"set pm-session-token {session_token}")
    lines.extend(["dhcp", f"set profile-root {urls.get('profile_root') or urls.get('assignment_root')}"])
    if mode == "ubuntu_autoinstall":
        lines.extend(
            [
                f"kernel {profile.kernel_url or '${profile-root}/vmlinuz'} ip=dhcp autoinstall ds=nocloud-net;s={urls['answer']}/",
                f"initrd {profile.initrd_url or '${profile-root}/initrd'}",
                "boot",
            ]
        )
    elif mode == "rocky_kickstart":
        lines.extend(
            [
                f"kernel {profile.kernel_url or '${profile-root}/vmlinuz'} ip=dhcp inst.ks={urls['answer']} inst.repo={profile.rootfs_url or '${profile-root}/repo'}",
                f"initrd {profile.initrd_url or '${profile-root}/initrd.img'}",
                "boot",
            ]
        )
    elif mode == "windows_autounattend":
        lines.extend(
            [
                "kernel wimboot",
                f"initrd {profile.kernel_url or '${profile-root}/bootmgr'} bootmgr",
                f"initrd {profile.initrd_url or '${profile-root}/boot.sdi'} boot.sdi",
                f"initrd {profile.rootfs_url or '${profile-root}/boot.wim'} boot.wim",
                f"imgargs wimboot initrd=bootmgr initrd=boot.sdi initrd=boot.wim answer={urls['answer']}",
                "boot",
            ]
        )
    else:
        lines.extend(
            [
                f"kernel {profile.kernel_url or '${profile-root}/vmlinuz'} ip=dhcp",
                f"initrd {profile.initrd_url or '${profile-root}/initrd.img'}",
                f"imgargs vmlinuz template={profile.provisioning_template.name if profile.provisioning_template else 'unset'} metadata={urls['answer']}",
                "boot",
            ]
        )
    return "\n".join(lines)


def _render_network_menu(network: NetworkBootNetwork, profiles: list[NetworkBootProfile]) -> str:
    lines = [
        "#!ipxe",
        f"# Patch-SecOps Solution network boot menu for {network.name}",
        "dhcp",
        ":menu",
        "menu Patch-SecOps Solution bare-metal deployment",
    ]
    active_profiles = [profile for profile in profiles if bool(profile.is_enabled)]
    for profile in active_profiles:
        lines.append(f"item profile-{profile.id} {profile.name} ({profile.install_mode})")
    lines.extend(["choose selected || goto menu", "goto ${selected}"])
    for profile in active_profiles:
        lines.extend([f":profile-{profile.id}", f"chain {_artifact_urls(profile, network)['ipxe']}"])
    return "\n".join(lines)


def _render_dnsmasq_config(
    networks: list[NetworkBootNetwork],
    profiles: list[NetworkBootProfile],
    assignments: list[NetworkBootAssignment],
) -> str:
    lines = [
        "# Patch-SecOps Solution generated dnsmasq PXE configuration",
        "port=0",
        "log-dhcp",
        "enable-tftp",
        "tftp-root=/var/lib/patchmaster/network-boot/tftp",
        "dhcp-no-override",
        "dhcp-userclass=set:ipxe,iPXE",
        "dhcp-match=set:efi64,option:client-arch,7",
        "dhcp-match=set:efi64,option:client-arch,9",
        "",
    ]
    profiles_by_network: dict[int, list[NetworkBootProfile]] = {}
    for profile in profiles:
        if profile.network_id:
            profiles_by_network.setdefault(profile.network_id, []).append(profile)
    assignments_by_network: dict[int, list[NetworkBootAssignment]] = {}
    for assignment in assignments:
        assignments_by_network.setdefault(assignment.network_id, []).append(assignment)

    for network in networks:
        if not bool(network.is_enabled):
            continue
        tag = f"net{network.id}"
        lines.append(f"# Network {network.name}")
        if network.interface_name:
            lines.append(f"interface={network.interface_name}")
        if network.dhcp_range_start and network.dhcp_range_end:
            lines.append(f"dhcp-range=set:{tag},{network.dhcp_range_start},{network.dhcp_range_end},12h")
        if network.gateway:
            lines.append(f"dhcp-option=tag:{tag},option:router,{network.gateway}")
        if network.dns_servers:
            lines.append(f"dhcp-option=tag:{tag},option:dns-server,{','.join(network.dns_servers)}")
        lines.append(f"dhcp-boot=tag:{tag},tag:efi64,{network.boot_file_uefi or 'ipxe.efi'}")
        lines.append(f"dhcp-boot=tag:{tag},tag:!efi64,{network.boot_file_bios or 'undionly.kpxe'}")
        lines.append(f"dhcp-boot=tag:ipxe,tag:{tag},{_network_urls(network)['menu']}")
        for assignment in assignments_by_network.get(network.id, []):
            if not assignment.is_enabled:
                continue
            assign_tag = f"pmassign{assignment.id}"
            host_bits = [assignment.mac_address]
            if assignment.reserved_ip:
                host_bits.append(assignment.reserved_ip)
            if assignment.hostname:
                host_bits.append(assignment.hostname)
            host_bits.append(f"set:{assign_tag}")
            lines.append(f"dhcp-host={','.join(host_bits)}")
            lines.append(f"dhcp-boot=tag:ipxe,tag:{assign_tag},{_assignment_urls(assignment)['ipxe']}")
        lines.append("")

    if not any(bool(network.is_enabled) for network in networks):
        lines.append("# No enabled boot networks are currently defined.")
    return "\n".join(lines)


def _render_tftp_manifest(
    networks: list[NetworkBootNetwork],
    profiles: list[NetworkBootProfile],
    assignments: list[NetworkBootAssignment],
) -> dict[str, Any]:
    return {
        "generated_at": _utcnow().isoformat() + "Z",
        "tftp_root": "/var/lib/patchmaster/network-boot/tftp",
        "required_boot_files": ["undionly.kpxe", "ipxe.efi", "wimboot"],
        "networks": [
            {
                "name": network.name,
                "menu_url": _network_urls(network)["menu"],
                "controller_url": _controller_api_base(network),
                "server_name": _network_server_name(network),
                "boot_file_bios": network.boot_file_bios,
                "boot_file_uefi": network.boot_file_uefi,
            }
            for network in networks
            if network.is_enabled
        ],
        "profiles": [
            {
                "id": profile.id,
                "name": profile.name,
                "install_mode": profile.install_mode,
                "artifact_urls": _artifact_urls(profile, profile.network),
            }
            for profile in profiles
            if profile.is_enabled
        ],
        "assignments": [
            {
                "id": assignment.id,
                "hostname": assignment.hostname,
                "mac_address": assignment.mac_address,
                "reserved_ip": assignment.reserved_ip,
                "boot_urls": _assignment_urls(assignment),
            }
            for assignment in assignments
            if assignment.is_enabled
        ],
    }


def _render_nginx_config(networks: list[NetworkBootNetwork]) -> str:
    server_names = sorted({_network_server_name(network) for network in networks if bool(network.is_enabled)})
    if not server_names:
        server_names = ["patchmaster-boot.local"]
    return "\n".join(
        [
            "# Patch-SecOps Solution generated nginx HTTP-boot configuration",
            "server {",
            "    listen 80;",
            f"    server_name {' '.join(server_names)};",
            "",
            "    location /boot/network-boot/ {",
            "        alias /var/lib/patchmaster/network-boot/http-boot/;",
            "        types {",
            "            text/plain ipxe answer cfg ks xml json;",
            "            application/octet-stream efi kpxe wim sdi;",
            "        }",
            "        autoindex on;",
            "        add_header Cache-Control \"no-store\" always;",
            "        try_files $uri $uri/ =404;",
            "    }",
            "}",
        ]
    )


def _render_boot_host_install_script() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"',
            'HTTP_ROOT="/var/lib/patchmaster/network-boot/http-boot"',
            'TFTP_ROOT="/var/lib/patchmaster/network-boot/tftp"',
            'MISSING_FILE_REPORT="/var/lib/patchmaster/network-boot/missing-boot-files.txt"',
            "",
            "log() {",
            '  printf "[patchmaster-boot] %s\\n" "$1"',
            "}",
            "",
            "install_packages() {",
            "  if command -v apt-get >/dev/null 2>&1; then",
            "    export DEBIAN_FRONTEND=noninteractive",
            "    apt-get update -qq",
            "    apt-get install -y -qq dnsmasq nginx rsync curl jq",
            "    return 0",
            "  fi",
            "  if command -v dnf >/dev/null 2>&1; then",
            "    dnf install -y dnsmasq nginx rsync curl jq",
            "    return 0",
            "  fi",
            '  log "Unsupported package manager. Install dnsmasq, nginx, rsync, curl, and jq manually."',
            "  return 1",
            "}",
            "",
            "copy_if_found() {",
            '  local target_name="$1"',
            "  shift",
            "  for candidate in \"$@\"; do",
            '    if [[ -f "$candidate" ]]; then',
            '      install -m 0644 "$candidate" "${TFTP_ROOT}/${target_name}"',
            '      log "Installed boot file ${target_name} from ${candidate}"',
            "      return 0",
            "    fi",
            "  done",
            '  printf "%s\\n" "$target_name" >> "${MISSING_FILE_REPORT}"',
            '  log "Missing required boot file: ${target_name}"',
            "  return 1",
            "}",
            "",
            "install_packages",
            'install -d -m 0755 "${HTTP_ROOT}" "${TFTP_ROOT}" /var/lib/patchmaster/network-boot',
            'rm -f "${MISSING_FILE_REPORT}"',
            'rsync -a --delete "${BUNDLE_ROOT}/http-boot/" "${HTTP_ROOT}/"',
            'install -D -m 0644 "${BUNDLE_ROOT}/dnsmasq/patchmaster-network-boot.conf" /etc/dnsmasq.d/patchmaster-network-boot.conf',
            'install -D -m 0644 "${BUNDLE_ROOT}/nginx/patchmaster-network-boot.conf" /etc/nginx/sites-available/patchmaster-network-boot.conf',
            'ln -sf /etc/nginx/sites-available/patchmaster-network-boot.conf /etc/nginx/sites-enabled/patchmaster-network-boot.conf',
            'copy_if_found "undionly.kpxe" /usr/lib/ipxe/undionly.kpxe /usr/share/ipxe/undionly.kpxe /usr/lib/PXELINUX/undionly.kpxe || true',
            'copy_if_found "ipxe.efi" /usr/lib/ipxe/ipxe.efi /usr/share/ipxe/ipxe.efi /usr/lib64/ipxe/ipxe.efi || true',
            'copy_if_found "wimboot" /usr/lib/ipxe/wimboot /usr/share/ipxe/wimboot /usr/lib64/ipxe/wimboot || true',
            "dnsmasq --test",
            "nginx -t",
            "systemctl enable dnsmasq nginx",
            "systemctl restart dnsmasq nginx",
            'log "Boot services are installed. Review ${MISSING_FILE_REPORT} if any boot files were unavailable on this host."',
            'log "HTTP boot root: ${HTTP_ROOT}"',
            'log "TFTP root: ${TFTP_ROOT}"',
            "",
        ]
    )


def _add_text_file_to_tar(bundle: tarfile.TarFile, name: str, content: str, mode: int = 0o644) -> None:
    payload = content.encode("utf-8")
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    info.mode = mode
    bundle.addfile(info, io.BytesIO(payload))


def _relay_public(relay: BootRelay) -> dict[str, Any]:
    host = getattr(relay, "host", None)
    return {
        "id": relay.id,
        "host_id": relay.host_id,
        "name": relay.name,
        "site_scope": relay.site_scope or "",
        "install_root": relay.install_root or "",
        "public_base_url": relay.public_base_url or "",
        "notes": relay.notes or "",
        "is_enabled": bool(relay.is_enabled),
        "status": relay.status or "",
        "applied_version": relay.applied_version or "",
        "rendered_config_checksum": relay.rendered_config_checksum or "",
        "last_install_at": relay.last_install_at.isoformat() if relay.last_install_at else None,
        "last_sync_at": relay.last_sync_at.isoformat() if relay.last_sync_at else None,
        "last_validation_at": relay.last_validation_at.isoformat() if relay.last_validation_at else None,
        "last_validation_status": relay.last_validation_status or "",
        "created_by": relay.created_by or "",
        "created_at": relay.created_at.isoformat() if relay.created_at else None,
        "updated_at": relay.updated_at.isoformat() if relay.updated_at else None,
        "host": {
            "id": host.id,
            "hostname": host.hostname,
            "ip": host.ip,
            "site": host.site or "",
            "os": host.os or "",
            "is_online": bool(host.is_online),
        }
        if host
        else None,
    }


def _network_public(network: NetworkBootNetwork) -> dict[str, Any]:
    return {
        "id": network.id,
        "name": network.name,
        "interface_name": network.interface_name or "",
        "vlan_id": network.vlan_id,
        "cidr": network.cidr or "",
        "gateway": network.gateway or "",
        "dns_servers": list(network.dns_servers or []),
        "dhcp_range_start": network.dhcp_range_start or "",
        "dhcp_range_end": network.dhcp_range_end or "",
        "next_server": network.next_server or "",
        "controller_url": network.controller_url or "",
        "relay_id": network.relay_id,
        "artifact_version": network.artifact_version or "",
        "rendered_config_checksum": network.rendered_config_checksum or "",
        "last_rendered_at": network.last_rendered_at.isoformat() if network.last_rendered_at else None,
        "last_validated_at": network.last_validated_at.isoformat() if network.last_validated_at else None,
        "last_validation_status": network.last_validation_status or "",
        "boot_file_bios": network.boot_file_bios or "",
        "boot_file_uefi": network.boot_file_uefi or "",
        "is_enabled": bool(network.is_enabled),
        "published_urls": _network_urls(network),
        "created_by": network.created_by or "",
        "created_at": network.created_at.isoformat() if network.created_at else None,
        "updated_at": network.updated_at.isoformat() if network.updated_at else None,
        "relay": _relay_public(network.relay) if getattr(network, "relay", None) else None,
    }


def _profile_public(profile: NetworkBootProfile) -> dict[str, Any]:
    network = profile.network
    template = profile.provisioning_template
    return {
        "id": profile.id,
        "name": profile.name,
        "os_family": profile.os_family or "",
        "os_version": profile.os_version or "",
        "architecture": profile.architecture or "x86_64",
        "firmware_mode": profile.firmware_mode or "uefi",
        "install_mode": profile.install_mode or "ubuntu_autoinstall",
        "kernel_url": profile.kernel_url or "",
        "initrd_url": profile.initrd_url or "",
        "rootfs_url": profile.rootfs_url or "",
        "answer_template": profile.answer_template or "",
        "post_install_script": profile.post_install_script or "",
        "is_enabled": bool(profile.is_enabled),
        "release_label": profile.release_label or "stable",
        "published_urls": _artifact_urls(profile, network),
        "created_by": profile.created_by or "",
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "network": _network_public(network) if network else None,
        "mirror_repo": _mirror_repo_public(getattr(profile, "mirror_repo", None)),
        "provisioning_template": {
            "id": template.id,
            "name": template.name,
            "site_scope": template.site_scope or "",
            "os_family": template.os_family or "",
        }
        if template
        else None,
    }


def _assignment_public(assignment: NetworkBootAssignment) -> dict[str, Any]:
    host = assignment.host
    return {
        "id": assignment.id,
        "host_id": assignment.host_id,
        "hostname": assignment.hostname or (host.hostname if host else ""),
        "mac_address": assignment.mac_address,
        "reserved_ip": assignment.reserved_ip or "",
        "firmware_mode": assignment.firmware_mode or "uefi",
        "boot_once": bool(assignment.boot_once),
        "is_enabled": bool(assignment.is_enabled),
        "site_scope": assignment.site_scope or "",
        "published_urls": _assignment_urls(assignment),
        "created_by": assignment.created_by or "",
        "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
        "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
        "last_boot_at": assignment.last_boot_at.isoformat() if assignment.last_boot_at else None,
        "host": {
            "id": host.id,
            "hostname": host.hostname,
            "ip": host.ip,
            "site": host.site or "",
        }
        if host
        else None,
        "network": _network_public(assignment.network) if assignment.network else None,
        "profile": _profile_public(assignment.profile) if assignment.profile else None,
    }


def _boot_event_public(event: BootEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "source": event.source or "",
        "message": event.message or "",
        "payload": dict(event.payload or {}),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _boot_session_public(session: BootSession) -> dict[str, Any]:
    assignment = getattr(session, "assignment", None)
    profile = getattr(session, "profile", None)
    relay = getattr(session, "relay", None)
    host = getattr(session, "host", None)
    return {
        "id": session.id,
        "session_token": session.session_token,
        "assignment_id": session.assignment_id,
        "profile_id": session.profile_id,
        "network_id": session.network_id,
        "relay_id": session.relay_id,
        "host_id": session.host_id,
        "mac_address": session.mac_address or "",
        "hostname": session.hostname or "",
        "controller_url": session.controller_url or "",
        "current_stage": session.current_stage or "",
        "status": session.status or "",
        "provisioning_source": session.provisioning_source or "",
        "event_count": int(session.event_count or 0),
        "result_summary": dict(session.result_summary or {}),
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "last_event_at": session.last_event_at.isoformat() if session.last_event_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "assignment": {
            "id": assignment.id,
            "hostname": assignment.hostname,
            "mac_address": assignment.mac_address,
            "site_scope": assignment.site_scope or "",
        }
        if assignment
        else None,
        "profile": {
            "id": profile.id,
            "name": profile.name,
            "install_mode": profile.install_mode,
        }
        if profile
        else None,
        "relay": _relay_public(relay) if relay else None,
        "host": {
            "id": host.id,
            "hostname": host.hostname,
            "ip": host.ip,
            "site": host.site or "",
        }
        if host
        else None,
        "events": [_boot_event_public(event) for event in list(getattr(session, "events", []) or [])[:20]],
    }


def _relay_run_public(run: BootRelayRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "relay_id": run.relay_id,
        "action": run.action,
        "status": run.status,
        "requested_by": run.requested_by or "",
        "queue_job_id": run.queue_job_id or "",
        "payload": dict(run.payload or {}),
        "result_summary": dict(run.result_summary or {}),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


async def _load_network_profiles(db: AsyncSession, network_id: int) -> list[NetworkBootProfile]:
    query = (
        select(NetworkBootProfile)
        .options(
            selectinload(NetworkBootProfile.network),
            selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootProfile.network_id == network_id, NetworkBootProfile.is_enabled == True)
        .order_by(NetworkBootProfile.name.asc())
    )
    return list((await db.execute(query)).scalars().all())


def _session_stage_for_event(event_type: str, default_stage: str = "assignment_served") -> tuple[str, str]:
    mapping = {
        "assignment_served": ("assignment_served", "active"),
        "answer_served": ("answer_served", "active"),
        "installer_started": ("installer_started", "active"),
        "first_boot_reached": ("first_boot_reached", "active"),
        "enrollment_attempted": ("enrollment_attempted", "active"),
        "enrollment_succeeded": ("enrollment_succeeded", "success"),
        "enrollment_failed": ("enrollment_failed", "failed"),
        "relay_validated": ("relay_validated", "active"),
    }
    return mapping.get(event_type, (default_stage, "active"))


def _touch_host_inventory(host: Host | None, updates: dict[str, Any]) -> None:
    if not host:
        return
    inventory = dict(host.hardware_inventory or {})
    inventory.update({key: value for key, value in updates.items() if value not in (None, "")})
    host.hardware_inventory = inventory


async def _record_boot_event(
    db: AsyncSession,
    session: BootSession,
    event_type: str,
    source: str,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> BootEvent:
    stage, status = _session_stage_for_event(event_type, session.current_stage or "assignment_served")
    now = _utcnow()
    event = BootEvent(
        session_id=session.id,
        event_type=event_type,
        source=source,
        message=message,
        payload=dict(payload or {}),
        created_at=now,
    )
    db.add(event)
    session.current_stage = stage
    session.status = status
    session.last_event_at = now
    session.event_count = int(session.event_count or 0) + 1
    summary = dict(session.result_summary or {})
    summary.update({"last_event_type": event_type, "last_event_source": source, "last_event_message": message})
    session.result_summary = summary
    if status in {"success", "failed"}:
        session.completed_at = now
    host = getattr(session, "host", None)
    _touch_host_inventory(
        host,
        {
            "last_boot_session": session.session_token,
            "last_boot_stage": stage,
            "provisioning_source": session.provisioning_source or "",
        },
    )
    await db.flush()
    return event


async def _create_assignment_boot_session(db: AsyncSession, assignment: NetworkBootAssignment) -> BootSession:
    network = assignment.network
    profile = assignment.profile
    relay = network.relay if network else None
    session = BootSession(
        session_token=uuid.uuid4().hex,
        assignment_id=assignment.id,
        profile_id=assignment.profile_id,
        network_id=assignment.network_id,
        relay_id=network.relay_id if network else None,
        host_id=assignment.host_id,
        mac_address=assignment.mac_address,
        hostname=assignment.hostname or (assignment.host.hostname if assignment.host else ""),
        controller_url=_controller_api_base(network),
        current_stage="assignment_served",
        status="active",
        provisioning_source=profile.install_mode if profile else "",
        event_count=0,
        started_at=_utcnow(),
        result_summary={},
    )
    db.add(session)
    await db.flush()
    assignment.last_boot_at = _utcnow()
    _touch_host_inventory(
        assignment.host,
        {
            "last_boot_session": session.session_token,
            "last_boot_stage": "assignment_served",
            "provisioning_source": session.provisioning_source,
        },
    )
    if relay and relay.host:
        _touch_host_inventory(relay.host, {"relay_role": "boot_relay", "relay_site_scope": relay.site_scope or ""})
    await _record_boot_event(
        db,
        session,
        "assignment_served",
        "boot_endpoint",
        "Assignment boot artifact served",
        {"assignment_id": assignment.id},
    )
    return session


async def _load_boot_session_by_token(db: AsyncSession, session_token: str) -> BootSession | None:
    query = (
        select(BootSession)
        .options(
            selectinload(BootSession.assignment),
            selectinload(BootSession.profile),
            selectinload(BootSession.network),
            selectinload(BootSession.relay).selectinload(BootRelay.host),
            selectinload(BootSession.host),
            selectinload(BootSession.events),
        )
        .where(BootSession.session_token == session_token)
    )
    return (await db.execute(query)).scalar_one_or_none()


def _relay_networks(networks: list[NetworkBootNetwork], relay_id: int | None = None) -> list[NetworkBootNetwork]:
    if relay_id is None:
        return list(networks)
    return [network for network in networks if int(getattr(network, "relay_id", 0) or 0) == int(relay_id)]


async def _stamp_network_render_metadata(
    db: AsyncSession,
    networks: list[NetworkBootNetwork],
    profiles: list[NetworkBootProfile],
    assignments: list[NetworkBootAssignment],
) -> None:
    now = _utcnow()
    for network in networks:
        network_profiles = [profile for profile in profiles if profile.network_id == network.id]
        network_assignments = [assignment for assignment in assignments if assignment.network_id == network.id]
        version, checksum = _artifact_version_details(network, network_profiles, network_assignments)
        network.artifact_version = version
        network.rendered_config_checksum = checksum
        network.last_rendered_at = now
    await db.flush()


def _build_bundle_buffer(
    networks: list[NetworkBootNetwork],
    profiles: list[NetworkBootProfile],
    assignments: list[NetworkBootAssignment],
    relay: BootRelay | None = None,
) -> io.BytesIO:
    dnsmasq_config = _render_dnsmasq_config(list(networks), list(profiles), list(assignments))
    nginx_config = _render_nginx_config(list(networks))
    manifest = _render_tftp_manifest(list(networks), list(profiles), list(assignments))
    boot_host_install_script = _render_boot_host_install_script()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        scope_label = f" for relay {relay.name}" if relay else ""
        _add_text_file_to_tar(
            bundle,
            "README.txt",
            "\n".join(
                [
                    f"Patch-SecOps Solution PXE deployment bundle{scope_label}",
                    "",
                    "1. Copy this bundle to the designated boot relay host.",
                    "2. Run scripts/install-boot-host.sh as root on that host.",
                    "3. Review manifest/boot-artifacts.json and missing-boot-files.txt for any missing binaries.",
                    "4. Ensure DHCP or iPXE traffic is pointed at the configured next_server for the included networks.",
                ]
            ),
        )
        _add_text_file_to_tar(bundle, "dnsmasq/patchmaster-network-boot.conf", dnsmasq_config)
        _add_text_file_to_tar(bundle, "nginx/patchmaster-network-boot.conf", nginx_config)
        _add_text_file_to_tar(bundle, "manifest/boot-artifacts.json", json.dumps(manifest, indent=2))
        _add_text_file_to_tar(bundle, "scripts/install-boot-host.sh", boot_host_install_script, mode=0o755)
        for network in networks:
            if not network.is_enabled:
                continue
            menu = _render_network_menu(network, [profile for profile in profiles if profile.network_id == network.id])
            _add_text_file_to_tar(bundle, f"http-boot/networks/{network.id}/menu.ipxe", menu)
        for profile in profiles:
            if not profile.is_enabled:
                continue
            _add_text_file_to_tar(bundle, f"http-boot/profiles/{profile.id}/boot.ipxe", _render_ipxe_script(profile, profile.network))
            _add_text_file_to_tar(
                bundle,
                f"http-boot/profiles/{profile.id}/answer",
                profile.answer_template or _default_answer_template(profile, profile.network),
            )
        for assignment in assignments:
            if not assignment.is_enabled:
                continue
            _add_text_file_to_tar(
                bundle,
                f"http-boot/assignments/{assignment.id}/boot.ipxe",
                _render_ipxe_script(assignment.profile, assignment.network, assignment),
            )
            _add_text_file_to_tar(
                bundle,
                f"http-boot/assignments/{assignment.id}/answer",
                assignment.profile.answer_template or _default_answer_template(assignment.profile, assignment.network, assignment),
            )
    buffer.seek(0)
    return buffer


async def _run_agent_command_on_host(
    db: AsyncSession,
    host_id: int,
    command: str,
    timeout: int = 180,
    working_dir: str | None = None,
) -> dict[str, Any]:
    host, url = await _agent_url_for_host_id(host_id, "/run", db)
    async with httpx.AsyncClient(timeout=float(timeout) + 10.0) as client:
        response = await client.post(
            url,
            json={"command": command, "timeout": timeout, "working_dir": working_dir or ""},
            headers=_relay_agent_headers(host),
        )
        payload = response.json()
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=payload.get("error") or payload.get("detail") or "Agent relay command failed")
    payload.setdefault("host_id", host.id)
    payload.setdefault("host_ip", host.ip)
    return payload


async def _execute_relay_action(run_id: int, relay_id: int, action: str) -> dict[str, Any]:
    async with async_session() as db:
        relay_query = (
            select(BootRelay)
            .options(selectinload(BootRelay.host), selectinload(BootRelay.networks))
            .where(BootRelay.id == relay_id)
        )
        relay = (await db.execute(relay_query)).scalar_one_or_none()
        run = await db.get(BootRelayRun, run_id)
        if not relay or not run:
            raise HTTPException(status_code=404, detail="Boot relay run not found")
        relay_networks = [
            network
            for network in relay.networks
            if bool(network.is_enabled)
        ]
        if not relay_networks:
            raise HTTPException(status_code=409, detail="No enabled networks are bound to this boot relay")
        control_network = relay_networks[0]
        bundle_url = f"{_controller_api_base(control_network)}/boot/network-boot/relays/{relay.id}/bundle.tar.gz"
        health_url = _controller_health_url(control_network)
        if action in {"install", "sync"}:
            remote_cmd = (
                "set -euo pipefail\n"
                "TMP_DIR=$(mktemp -d)\n"
                f"curl -fsSL {_shell_single_quote(bundle_url)} -o \"$TMP_DIR/relay-bundle.tar.gz\"\n"
                "tar -xzf \"$TMP_DIR/relay-bundle.tar.gz\" -C \"$TMP_DIR\"\n"
                "bash \"$TMP_DIR/scripts/install-boot-host.sh\"\n"
            )
        elif action == "validate":
            remote_cmd = (
                "set -euo pipefail\n"
                "dnsmasq --test\n"
                "nginx -t\n"
                "test -f /etc/dnsmasq.d/patchmaster-network-boot.conf\n"
                "test -f /etc/nginx/sites-available/patchmaster-network-boot.conf\n"
                f"curl -fsSI {_shell_single_quote(health_url)} >/dev/null\n"
                "echo '{\"dnsmasq\":\"ok\",\"nginx\":\"ok\",\"controller\":\"ok\"}'\n"
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported relay action")
        run.status = "running"
        run.started_at = _utcnow()
        relay.status = f"{action}_running"
        await db.commit()
        result = await _run_agent_command_on_host(db, relay.host_id, remote_cmd, timeout=240, working_dir=relay.install_root or None)
        now = _utcnow()
        success = int(result.get("rc", 1)) == 0
        run.status = "success" if success else "failed"
        run.completed_at = now
        run.result_summary = {
            "rc": int(result.get("rc", 1)),
            "output": str(result.get("output", "") or "")[:4000],
            "host_ip": result.get("host_ip"),
            "action": action,
            "bundle_url": bundle_url,
        }
        relay.status = "ready" if success else "error"
        relay.applied_version = relay_networks[0].artifact_version or relay.applied_version
        relay.rendered_config_checksum = relay_networks[0].rendered_config_checksum or relay.rendered_config_checksum
        if action == "install":
            relay.last_install_at = now
        if action == "sync":
            relay.last_sync_at = now
        if action == "validate":
            relay.last_validation_at = now
            relay.last_validation_status = "success" if success else "failed"
        if success:
            relay_host = relay.host
            _touch_host_inventory(
                relay_host,
                {
                    "relay_role": "boot_relay",
                    "relay_site_scope": relay.site_scope or "",
                    "last_relay_action": action,
                },
            )
        await db.commit()
        return {"relay": _relay_public(relay), "run_id": run.id, "action": action, "result": run.result_summary}


class BootNetworkUpsert(BaseModel):
    name: str
    interface_name: str = ""
    vlan_id: int | None = None
    cidr: str = ""
    gateway: str = ""
    dns_servers: list[str] = Field(default_factory=list)
    dhcp_range_start: str = ""
    dhcp_range_end: str = ""
    next_server: str = ""
    controller_url: str = ""
    relay_id: int | None = None
    boot_file_bios: str = "undionly.kpxe"
    boot_file_uefi: str = "ipxe.efi"
    is_enabled: bool = True


class BootProfileUpsert(BaseModel):
    name: str
    network_id: int | None = None
    provisioning_template_id: int | None = None
    mirror_repo_id: int | None = None
    os_family: str = ""
    os_version: str = ""
    architecture: str = "x86_64"
    firmware_mode: str = "uefi"
    install_mode: str = "ubuntu_autoinstall"
    kernel_url: str = ""
    initrd_url: str = ""
    rootfs_url: str = ""
    answer_template: str = ""
    post_install_script: str = ""
    is_enabled: bool = True
    release_label: str = "stable"


class BootRelayUpsert(BaseModel):
    name: str
    host_id: int
    site_scope: str = ""
    install_root: str = "/var/lib/patchmaster/network-boot"
    public_base_url: str = ""
    notes: str = ""
    is_enabled: bool = True


class RelayActionRequest(BaseModel):
    action: str = "validate"


class BootSessionEventIn(BaseModel):
    session_token: str
    event_type: str
    source: str = "installer"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class BootAssignmentUpsert(BaseModel):
    network_id: int
    profile_id: int
    host_id: int | None = None
    hostname: str = ""
    mac_address: str
    reserved_ip: str = ""
    firmware_mode: str = "uefi"
    boot_once: bool = True
    is_enabled: bool = True
    site_scope: str = ""


@router.get("/workflows")
async def workflow_cards(user: User = Depends(get_current_user)):
    workflows = [
        {
            "id": "managed-networks",
            "label": "Workflow 1",
            "title": "Design managed relay networks",
            "status": "implemented",
            "capabilities": [
                "Boot networks",
                "Managed relay binding",
                "Controller URL separation",
                "Artifact version metadata",
            ],
        },
        {
            "id": "publish-sources",
            "label": "Workflow 2",
            "title": "Publish installer and image sources",
            "status": "implemented",
            "capabilities": [
                "Provisioning profiles",
                "Per-profile and per-assignment boot artifacts",
                "Mirror-aware source binding",
            ],
        },
        {
            "id": "operate-relays",
            "label": "Workflow 3",
            "title": "Install, sync, and validate boot relays",
            "status": "implemented",
            "capabilities": [
                "Controller-generated relay bundles",
                "Ops queue-driven relay actions",
                "dnsmasq/nginx validation and controller reachability checks",
            ],
        },
        {
            "id": "track-enrollment",
            "label": "Workflow 4",
            "title": "Track boot sessions through enrollment",
            "status": "implemented",
            "capabilities": [
                "Pre-agent host assignments",
                "Boot session creation on published assignment requests",
                "Installer and enrollment telemetry",
                "Live boot-session evidence in the control plane",
            ],
        },
    ]
    return {"items": workflows, "workflows": workflows}


@router.get("/relays")
async def list_relays(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = (
        select(BootRelay)
        .options(selectinload(BootRelay.host), selectinload(BootRelay.networks))
        .order_by(BootRelay.name.asc())
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_relay_public(row) for row in rows]}


@router.post("/relays")
async def create_relay(
    body: BootRelayUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    host = await db.get(Host, body.host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Boot relay name is required")
    existing_name = await db.execute(select(BootRelay).where(BootRelay.name == name))
    if existing_name.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A boot relay with this name already exists")
    existing_host = await db.execute(select(BootRelay).where(BootRelay.host_id == body.host_id))
    if existing_host.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This host is already registered as a boot relay")
    relay = BootRelay(
        host_id=host.id,
        name=name,
        site_scope=body.site_scope.strip() or (host.site or ""),
        install_root=body.install_root.strip() or "/var/lib/patchmaster/network-boot",
        public_base_url=body.public_base_url.strip() or f"http://{host.ip}",
        notes=body.notes,
        is_enabled=bool(body.is_enabled),
        status="idle",
        created_by=user.username,
    )
    db.add(relay)
    _touch_host_inventory(host, {"relay_role": "boot_relay", "relay_site_scope": relay.site_scope or ""})
    await db.commit()
    query = (
        select(BootRelay)
        .options(selectinload(BootRelay.host), selectinload(BootRelay.networks))
        .where(BootRelay.id == relay.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _relay_public(fresh)


async def _queue_relay_action(
    relay_id: int,
    action: str,
    db: AsyncSession,
    user: User,
) -> dict[str, Any]:
    relay_query = (
        select(BootRelay)
        .options(selectinload(BootRelay.host), selectinload(BootRelay.networks))
        .where(BootRelay.id == relay_id)
    )
    relay = (await db.execute(relay_query)).scalar_one_or_none()
    if not relay:
        raise HTTPException(status_code=404, detail="Boot relay not found")
    run = BootRelayRun(
        relay_id=relay.id,
        action=action,
        status="pending",
        requested_by=user.username,
        payload={"relay_id": relay.id, "action": action},
        result_summary={},
    )
    db.add(run)
    await db.flush()

    async def runner():
        return await _execute_relay_action(run.id, relay.id, action)

    queue_job = await enqueue_operation(
        op_type=f"network_boot.relay.{action}",
        payload={"relay_id": relay.id, "relay_name": relay.name, "action": action},
        runner=runner,
        requested_by=user.username,
    )
    run.queue_job_id = queue_job["id"]
    relay.status = f"{action}_queued"
    await db.commit()
    await db.refresh(run)
    return {"status": "accepted", "relay": _relay_public(relay), "run": _relay_run_public(run), "job": queue_job}


@router.post("/relays/{relay_id}/install")
async def install_relay(
    relay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _queue_relay_action(relay_id, "install", db, user)


@router.post("/relays/{relay_id}/sync")
async def sync_relay(
    relay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _queue_relay_action(relay_id, "sync", db, user)


@router.post("/relays/{relay_id}/validate")
async def validate_relay(
    relay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    return await _queue_relay_action(relay_id, "validate", db, user)


@router.get("/relays/{relay_id}/runs")
async def relay_runs(
    relay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(BootRelayRun).where(BootRelayRun.relay_id == relay_id).order_by(BootRelayRun.created_at.desc())
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_relay_run_public(row) for row in rows]}


@router.get("/boot-sessions")
async def list_boot_sessions(
    limit: int = 50,
    status: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        select(BootSession)
        .options(
            selectinload(BootSession.assignment),
            selectinload(BootSession.profile),
            selectinload(BootSession.network),
            selectinload(BootSession.relay).selectinload(BootRelay.host),
            selectinload(BootSession.host),
            selectinload(BootSession.events),
        )
        .order_by(BootSession.created_at.desc())
    )
    if status.strip():
        query = query.where(BootSession.status == status.strip())
    rows = (await db.execute(query.limit(max(1, min(limit, 200))))).scalars().all()
    return {"items": [_boot_session_public(row) for row in rows]}


@router.post("/events")
async def ingest_boot_event(
    body: BootSessionEventIn,
    db: AsyncSession = Depends(get_db),
):
    session = await _load_boot_session_by_token(db, body.session_token.strip())
    if not session:
        raise HTTPException(status_code=404, detail="Boot session not found")
    await _record_boot_event(
        db,
        session,
        body.event_type.strip() or "progress",
        body.source.strip() or "installer",
        body.message,
        body.payload,
    )
    await db.commit()
    fresh = await _load_boot_session_by_token(db, body.session_token.strip())
    return {"status": "ok", "session": _boot_session_public(fresh)}


@router.get("/networks")
async def list_networks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(NetworkBootNetwork)
            .options(selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host))
            .order_by(NetworkBootNetwork.name.asc())
        )
    ).scalars().all()
    return {"items": [_network_public(row) for row in rows]}


@router.post("/networks")
async def create_network(
    body: BootNetworkUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Boot network name is required")
    existing = await db.execute(select(NetworkBootNetwork).where(NetworkBootNetwork.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A boot network with this name already exists")
    relay = None
    if body.relay_id:
        relay = await db.get(BootRelay, body.relay_id)
        if not relay:
            raise HTTPException(status_code=404, detail="Boot relay not found")
    row = NetworkBootNetwork(
        name=name,
        interface_name=body.interface_name.strip(),
        vlan_id=body.vlan_id,
        cidr=body.cidr.strip(),
        gateway=body.gateway.strip(),
        dns_servers=_normalize_list(body.dns_servers),
        dhcp_range_start=body.dhcp_range_start.strip(),
        dhcp_range_end=body.dhcp_range_end.strip(),
        next_server=body.next_server.strip(),
        controller_url=body.controller_url.strip(),
        relay_id=relay.id if relay else None,
        boot_file_bios=body.boot_file_bios.strip() or "undionly.kpxe",
        boot_file_uefi=body.boot_file_uefi.strip() or "ipxe.efi",
        is_enabled=body.is_enabled,
        created_by=user.username,
    )
    db.add(row)
    await db.commit()
    query = (
        select(NetworkBootNetwork)
        .options(selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host))
        .where(NetworkBootNetwork.id == row.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _network_public(fresh)


@router.get("/profiles")
async def list_profiles(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = (
        select(NetworkBootProfile)
        .options(
            selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootProfile.mirror_repo),
        )
        .order_by(NetworkBootProfile.name.asc())
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_profile_public(row) for row in rows]}


@router.post("/profiles")
async def create_profile(
    body: BootProfileUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Boot profile name is required")
    existing = await db.execute(select(NetworkBootProfile).where(NetworkBootProfile.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A boot profile with this name already exists")
    network = None
    if body.network_id:
        network = await db.get(NetworkBootNetwork, body.network_id)
        if not network:
            raise HTTPException(status_code=404, detail="Boot network not found")
    template = None
    if body.provisioning_template_id:
        template = await db.get(ProvisioningTemplate, body.provisioning_template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Provisioning template not found")
    mirror_repo = None
    if body.mirror_repo_id:
        mirror_repo = await db.get(MirrorRepo, body.mirror_repo_id)
        if not mirror_repo:
            raise HTTPException(status_code=404, detail="Mirror repository not found")
    row = NetworkBootProfile(
        name=name,
        network_id=network.id if network else None,
        provisioning_template_id=template.id if template else None,
        mirror_repo_id=mirror_repo.id if mirror_repo else None,
        os_family=body.os_family.strip().lower(),
        os_version=body.os_version.strip(),
        architecture=body.architecture.strip() or "x86_64",
        firmware_mode=_normalize_firmware_mode(body.firmware_mode),
        install_mode=_normalize_install_mode(body.install_mode),
        kernel_url=body.kernel_url.strip(),
        initrd_url=body.initrd_url.strip(),
        rootfs_url=body.rootfs_url.strip(),
        answer_template=body.answer_template,
        post_install_script=body.post_install_script,
        is_enabled=body.is_enabled,
        release_label=(body.release_label or "stable").strip() or "stable",
        created_by=user.username,
    )
    db.add(row)
    await db.commit()
    query = (
        select(NetworkBootProfile)
        .options(
            selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootProfile.id == row.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _profile_public(fresh)


@router.get("/assignments")
async def list_assignments(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = (
        select(NetworkBootAssignment)
        .options(
            selectinload(NetworkBootAssignment.host),
            selectinload(NetworkBootAssignment.network),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
        )
        .order_by(NetworkBootAssignment.hostname.asc(), NetworkBootAssignment.id.asc())
    )
    rows = (await db.execute(query)).scalars().all()
    return {"items": [_assignment_public(row) for row in rows]}


@router.post("/assignments")
async def create_assignment(
    body: BootAssignmentUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    network = await db.get(NetworkBootNetwork, body.network_id)
    if not network:
        raise HTTPException(status_code=404, detail="Boot network not found")
    query = (
        select(NetworkBootProfile)
        .options(selectinload(NetworkBootProfile.network), selectinload(NetworkBootProfile.provisioning_template))
        .where(NetworkBootProfile.id == body.profile_id)
    )
    profile = (await db.execute(query)).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Boot profile not found")
    if profile.network_id and profile.network_id != network.id:
        raise HTTPException(status_code=409, detail="Profile is attached to a different boot network")
    host = None
    if body.host_id:
        host = await db.get(Host, body.host_id)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")
    mac_address = _normalize_mac_address(body.mac_address)
    existing = await db.execute(select(NetworkBootAssignment).where(NetworkBootAssignment.mac_address == mac_address))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A boot assignment for this MAC address already exists")
    row = NetworkBootAssignment(
        host_id=host.id if host else None,
        network_id=network.id,
        profile_id=profile.id,
        hostname=(body.hostname.strip() or (host.hostname if host else "")),
        mac_address=mac_address,
        reserved_ip=body.reserved_ip.strip(),
        firmware_mode=_normalize_firmware_mode(body.firmware_mode),
        boot_once=bool(body.boot_once),
        is_enabled=bool(body.is_enabled),
        site_scope=(body.site_scope.strip() or (host.site if host else "") or _site_scope(profile)),
        created_by=user.username,
    )
    db.add(row)
    await db.commit()
    query = (
        select(NetworkBootAssignment)
        .options(
            selectinload(NetworkBootAssignment.host),
            selectinload(NetworkBootAssignment.network),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
        )
        .where(NetworkBootAssignment.id == row.id)
    )
    fresh = (await db.execute(query)).scalar_one()
    return _assignment_public(fresh)


@router.get("/profiles/{profile_id}/artifact-preview")
async def artifact_preview(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        select(NetworkBootProfile)
        .options(
            selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootProfile.id == profile_id)
    )
    profile = (await db.execute(query)).scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Boot profile not found")
    answer_template = profile.answer_template or _default_answer_template(profile, profile.network)
    ipxe_script = _render_ipxe_script(profile, profile.network)
    return {
        "profile": _profile_public(profile),
        "artifact_urls": _artifact_urls(profile, profile.network),
        "ipxe_script": ipxe_script,
        "answer_template": answer_template,
        "post_install_script": profile.post_install_script or "",
        "notes": [
            "Published boot endpoints are live and can be consumed by iPXE or HTTP boot.",
            "The generated answer template includes first-boot Patch-SecOps Solution enrollment defaults.",
            "Download the deployment bundle to apply dnsmasq and TFTP settings on your boot infrastructure host.",
        ],
    }


@router.get("/service-preview")
async def service_preview(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    networks = (
        await db.execute(
            select(NetworkBootNetwork)
            .options(selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host))
            .order_by(NetworkBootNetwork.name.asc())
        )
    ).scalars().all()
    profiles = (
        await db.execute(
            select(NetworkBootProfile)
            .options(
                selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootProfile.provisioning_template),
                selectinload(NetworkBootProfile.mirror_repo),
            )
            .order_by(NetworkBootProfile.name.asc())
        )
    ).scalars().all()
    assignments = (
        await db.execute(
            select(NetworkBootAssignment)
            .options(
                selectinload(NetworkBootAssignment.host),
                selectinload(NetworkBootAssignment.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.mirror_repo),
            )
            .order_by(NetworkBootAssignment.hostname.asc(), NetworkBootAssignment.id.asc())
        )
    ).scalars().all()
    await _stamp_network_render_metadata(db, list(networks), list(profiles), list(assignments))
    relays = (
        await db.execute(
            select(BootRelay)
            .options(selectinload(BootRelay.host), selectinload(BootRelay.networks))
            .order_by(BootRelay.name.asc())
        )
    ).scalars().all()
    sessions = (
        await db.execute(
            select(BootSession)
            .options(
                selectinload(BootSession.assignment),
                selectinload(BootSession.profile),
                selectinload(BootSession.network),
                selectinload(BootSession.relay).selectinload(BootRelay.host),
                selectinload(BootSession.host),
                selectinload(BootSession.events),
            )
            .order_by(BootSession.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    await db.commit()
    return {
        "dnsmasq_config": _render_dnsmasq_config(list(networks), list(profiles), list(assignments)),
        "nginx_config": _render_nginx_config(list(networks)),
        "boot_host_install_script": _render_boot_host_install_script(),
        "tftp_manifest": _render_tftp_manifest(list(networks), list(profiles), list(assignments)),
        "published_profiles": [_profile_public(profile) for profile in profiles if profile.is_enabled],
        "assignments": [_assignment_public(assignment) for assignment in assignments if assignment.is_enabled],
        "relays": [_relay_public(relay) for relay in relays],
        "boot_sessions": [_boot_session_public(session) for session in sessions],
    }


@router.get("/deployment-bundle")
async def deployment_bundle(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    networks = (
        await db.execute(
            select(NetworkBootNetwork)
            .options(selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host))
            .order_by(NetworkBootNetwork.name.asc())
        )
    ).scalars().all()
    profiles = (
        await db.execute(
            select(NetworkBootProfile)
            .options(
                selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootProfile.provisioning_template),
                selectinload(NetworkBootProfile.mirror_repo),
            )
            .order_by(NetworkBootProfile.name.asc())
        )
    ).scalars().all()
    assignments = (
        await db.execute(
            select(NetworkBootAssignment)
            .options(
                selectinload(NetworkBootAssignment.host),
                selectinload(NetworkBootAssignment.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.mirror_repo),
            )
            .order_by(NetworkBootAssignment.hostname.asc(), NetworkBootAssignment.id.asc())
        )
    ).scalars().all()
    await _stamp_network_render_metadata(db, list(networks), list(profiles), list(assignments))
    await db.commit()
    buffer = _build_bundle_buffer(list(networks), list(profiles), list(assignments))
    return StreamingResponse(
        buffer,
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="patchmaster-network-boot-bundle.tar.gz"'},
    )


@router.get("/catalog")
async def provisioning_catalog(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    templates = (
        await db.execute(
            select(ProvisioningTemplate)
            .where(ProvisioningTemplate.is_enabled == True)
            .order_by(ProvisioningTemplate.name.asc())
        )
    ).scalars().all()
    mirror_repos = (
        await db.execute(select(MirrorRepo).order_by(MirrorRepo.name.asc()))
    ).scalars().all()
    return {
        "provisioning_templates": [
            {"id": row.id, "name": row.name, "os_family": row.os_family or "", "site_scope": row.site_scope or ""}
            for row in templates
        ],
        "mirror_repositories": [
            _mirror_repo_public(repo)
            for repo in mirror_repos
        ],
    }


@public_router.get("/relays/{relay_id}/bundle.tar.gz")
async def public_relay_bundle(relay_id: int, db: AsyncSession = Depends(get_db)):
    relay_query = (
        select(BootRelay)
        .options(selectinload(BootRelay.host), selectinload(BootRelay.networks))
        .where(BootRelay.id == relay_id, BootRelay.is_enabled == True)
    )
    relay = (await db.execute(relay_query)).scalar_one_or_none()
    if not relay:
        raise HTTPException(status_code=404, detail="Boot relay not found")
    networks = (
        await db.execute(
            select(NetworkBootNetwork)
            .options(selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host))
            .where(NetworkBootNetwork.relay_id == relay.id, NetworkBootNetwork.is_enabled == True)
            .order_by(NetworkBootNetwork.name.asc())
        )
    ).scalars().all()
    profiles = (
        await db.execute(
            select(NetworkBootProfile)
            .options(
                selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootProfile.provisioning_template),
                selectinload(NetworkBootProfile.mirror_repo),
            )
            .where(NetworkBootProfile.network_id.in_([network.id for network in networks]) if networks else False)
            .order_by(NetworkBootProfile.name.asc())
        )
    ).scalars().all() if networks else []
    assignments = (
        await db.execute(
            select(NetworkBootAssignment)
            .options(
                selectinload(NetworkBootAssignment.host),
                selectinload(NetworkBootAssignment.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
                selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.mirror_repo),
            )
            .where(NetworkBootAssignment.network_id.in_([network.id for network in networks]) if networks else False)
            .order_by(NetworkBootAssignment.hostname.asc(), NetworkBootAssignment.id.asc())
        )
    ).scalars().all() if networks else []
    await _stamp_network_render_metadata(db, list(networks), list(profiles), list(assignments))
    relay_networks = list(networks)
    if relay_networks:
        relay.applied_version = relay_networks[0].artifact_version or relay.applied_version
        relay.rendered_config_checksum = relay_networks[0].rendered_config_checksum or relay.rendered_config_checksum
    await db.commit()
    return StreamingResponse(
        _build_bundle_buffer(relay_networks, list(profiles), list(assignments), relay=relay),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="patchmaster-boot-relay-{relay.id}.tar.gz"'},
    )


@public_router.get("/networks/{network_id}/menu.ipxe", response_class=PlainTextResponse)
async def published_network_menu(network_id: int, db: AsyncSession = Depends(get_db)):
    network = await db.get(NetworkBootNetwork, network_id)
    if not network or not network.is_enabled:
        raise HTTPException(status_code=404, detail="Boot network not found")
    profiles = await _load_network_profiles(db, network_id)
    return PlainTextResponse(_render_network_menu(network, profiles))


@public_router.get("/profiles/{profile_id}/boot.ipxe", response_class=PlainTextResponse)
async def published_profile_ipxe(profile_id: int, db: AsyncSession = Depends(get_db)):
    query = (
        select(NetworkBootProfile)
        .options(
            selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootProfile.id == profile_id)
    )
    profile = (await db.execute(query)).scalar_one_or_none()
    if not profile or not profile.is_enabled:
        raise HTTPException(status_code=404, detail="Boot profile not found")
    return PlainTextResponse(_render_ipxe_script(profile, profile.network))


@public_router.get("/profiles/{profile_id}/answer", response_class=PlainTextResponse)
async def published_profile_answer(profile_id: int, db: AsyncSession = Depends(get_db)):
    query = (
        select(NetworkBootProfile)
        .options(
            selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootProfile.id == profile_id)
    )
    profile = (await db.execute(query)).scalar_one_or_none()
    if not profile or not profile.is_enabled:
        raise HTTPException(status_code=404, detail="Boot profile not found")
    return PlainTextResponse(profile.answer_template or _default_answer_template(profile, profile.network))


@public_router.get("/assignments/{assignment_id}/boot.ipxe", response_class=PlainTextResponse)
async def published_assignment_ipxe(assignment_id: int, db: AsyncSession = Depends(get_db)):
    query = (
        select(NetworkBootAssignment)
        .options(
            selectinload(NetworkBootAssignment.network),
            selectinload(NetworkBootAssignment.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootAssignment.host),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootAssignment.id == assignment_id)
    )
    assignment = (await db.execute(query)).scalar_one_or_none()
    if not assignment or not assignment.is_enabled:
        raise HTTPException(status_code=404, detail="Boot assignment not found")
    session = await _create_assignment_boot_session(db, assignment)
    await db.commit()
    return PlainTextResponse(_render_ipxe_script(assignment.profile, assignment.network, assignment, session_token=session.session_token))


@public_router.get("/assignments/{assignment_id}/answer", response_class=PlainTextResponse)
async def published_assignment_answer(assignment_id: int, session: str | None = None, db: AsyncSession = Depends(get_db)):
    query = (
        select(NetworkBootAssignment)
        .options(
            selectinload(NetworkBootAssignment.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootAssignment.host),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.network).selectinload(NetworkBootNetwork.relay).selectinload(BootRelay.host),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.provisioning_template),
            selectinload(NetworkBootAssignment.profile).selectinload(NetworkBootProfile.mirror_repo),
        )
        .where(NetworkBootAssignment.id == assignment_id)
    )
    assignment = (await db.execute(query)).scalar_one_or_none()
    if not assignment or not assignment.is_enabled:
        raise HTTPException(status_code=404, detail="Boot assignment not found")
    profile = assignment.profile
    session_row = None
    if session:
        session_row = await _load_boot_session_by_token(db, session.strip())
    if session_row and session_row.assignment_id == assignment.id:
        await _record_boot_event(
            db,
            session_row,
            "answer_served",
            "boot_endpoint",
            "Installer answer artifact served",
            {"assignment_id": assignment.id},
        )
        await db.commit()
    return PlainTextResponse(
        profile.answer_template
        or _default_answer_template(profile, assignment.network, assignment, session_token=session_row.session_token if session_row else "")
    )
