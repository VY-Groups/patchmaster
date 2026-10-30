"""Unauthenticated scanning with scope enforcement (S3-4)."""

from __future__ import annotations

import asyncio
import socket
from typing import Iterable, Optional


class ScopeViolation(Exception):
    pass


def in_scope(target: str, allowed: Iterable[str]) -> bool:
    allowed = set(allowed or [])
    return target in allowed


def enforce_scope(target: str, allowed: Iterable[str]) -> None:
    if not in_scope(target, allowed):
        raise ScopeViolation(f"target {target} not in authorised scope")


async def _tcp_connect(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def scan_target(target: str, allowed: Iterable[str], ports: Optional[list] = None,
                      rate_limit: int = 10) -> dict:
    enforce_scope(target, allowed)
    ports = ports or [22, 80, 443, 445, 3389, 8080]
    sem = asyncio.Semaphore(max(1, rate_limit))
    results = []

    async def probe(p):
        async with sem:
            ok = await _tcp_connect(target, p)
            return {"port": p, "open": ok}

    results = await asyncio.gather(*[probe(p) for p in ports])
    open_ports = [r["port"] for r in results if r["open"]]
    return {"target": target, "scanned": True, "open_ports": open_ports, "findings": []}