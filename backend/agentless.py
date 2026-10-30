"""Agentless patch operations (S2-3): reuse connector + templates."""

from __future__ import annotations

from typing import Any, Optional

from connectors import connector_for
from command_templates import get_template


async def inventory(host, mode: str = "ssh", credentials: dict = None) -> dict:
    conn = connector_for(host, mode=mode, credentials=credentials or {})
    await conn.connect()
    try:
        os_family = getattr(host, "os_family", None) or getattr(host, "os", "linux")
        cmd = get_template(str(os_family), "list_packages")
        r = await conn.run(cmd, {})
        return {"transport": mode, "output": r.stdout, "ok": r.ok}
    finally:
        await conn.close()


async def apply_updates(host, mode: str = "ssh", credentials: dict = None) -> dict:
    conn = connector_for(host, mode=mode, credentials=credentials or {})
    await conn.connect()
    try:
        os_family = getattr(host, "os_family", None) or getattr(host, "os", "linux")
        cmd = get_template(str(os_family), "apply_updates")
        r = await conn.run(cmd, {})
        return {"transport": mode, "output": r.stdout, "ok": r.ok}
    finally:
        await conn.close()


async def reboot_required(host, mode: str = "ssh", credentials: dict = None) -> bool:
    conn = connector_for(host, mode=mode, credentials=credentials or {})
    await conn.connect()
    try:
        os_family = getattr(host, "os_family", None) or getattr(host, "os", "linux")
        cmd = get_template(str(os_family), "reboot_required")
        r = await conn.run(cmd, {})
        return "yes" in (r.stdout or "").lower()
    finally:
        await conn.close()