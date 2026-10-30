"""Topology Orchestrator (S6): ordered, gated patching of service members."""

from __future__ import annotations

from typing import Any, Callable, Awaitable, Optional


async def patch_service(service: dict, members: list, patch_fn: Callable[[Any], Awaitable[bool]],
                        tolerance: int = 1) -> dict:
    """Patch members one at a time, stopping if failures exceed tolerance."""
    results = []
    failed = 0
    for m in members:
        ok = await patch_fn(m)
        results.append({"member": m, "ok": ok})
        if not ok:
            failed += 1
            if failed > tolerance:
                return {"status": "stopped", "failed": failed, "results": results}
    return {"status": "success", "failed": failed, "results": results}