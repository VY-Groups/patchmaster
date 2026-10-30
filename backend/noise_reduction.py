"""CVE noise reduction (P3): rank exploited/reachable first; de-dup superseded."""

from __future__ import annotations

from typing import Any


def dedup_superseded(items: list[dict]) -> list[dict]:
    """Remove entries whose patch is superseded by another in the list."""
    seen = set()
    out = []
    for it in items:
        sid = it.get("supersedes")
        if sid and sid in {x.get("id") for x in items}:
            continue
        key = it.get("id")
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def rank(items: list[dict]) -> list[dict]:
    def key(it):
        return (
            -int(bool(it.get("known_exploited"))),
            -float(it.get("exposure", 0)),
            -float(it.get("cvss", 0)),
        )
    return sorted(items, key=key)