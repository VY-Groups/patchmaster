"""Mitigation playbook application (S3-7)."""

from __future__ import annotations

from typing import Any


async def apply_playbook(playbook: dict, host, executor) -> dict:
    """Apply a mitigation playbook's steps via executor(host, step)."""
    results = []
    for step in playbook.get("steps", []):
        try:
            ok = await executor(host, step)
            results.append({"step": step, "ok": bool(ok)})
            if not ok and step.get("stop_on_failure", True):
                break
        except Exception as e:
            results.append({"step": step, "ok": False, "error": str(e)})
            break
    return {"playbook": playbook.get("name"), "results": results,
            "ok": all(r.get("ok") for r in results)}