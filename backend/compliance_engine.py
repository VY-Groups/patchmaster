"""Compliance control runner (S5)."""

from __future__ import annotations

from typing import Any, Callable, Awaitable


async def run_control(control: dict, host, checker: Callable[[Any, dict], Awaitable[bool]]) -> dict:
    try:
        passed = await checker(host, control)
        return {"control_id": control.get("control_id"), "host_id": getattr(host, "id", None),
                "status": "passed" if passed else "open", "passed": bool(passed)}
    except Exception as e:
        return {"control_id": control.get("control_id"), "host_id": getattr(host, "id", None),
                "status": "error", "error": str(e)}


async def run_controls(controls: list[dict], hosts: list, checker) -> list[dict]:
    out = []
    for c in controls:
        for h in hosts:
            out.append(await run_control(c, h, checker))
    return out