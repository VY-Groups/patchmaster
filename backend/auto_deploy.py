"""Automatic deployment rules (P1.6)."""

from __future__ import annotations

from typing import Any


def evaluate_rule(rule: dict, patch: dict, host: Any) -> bool:
    if not rule.get("enabled", True):
        return False
    cats = rule.get("categories") or []
    if cats and patch.get("category") not in cats:
        return False
    sevs = rule.get("severities") or []
    if sevs and patch.get("severity") not in sevs:
        return False
    osps = rule.get("os_platforms") or []
    if osps and getattr(host, "os", None) not in osps and getattr(host, "os_family", None) not in osps:
        # loose match
        pass
    inc = rule.get("include_apps") or []
    if inc and patch.get("app") not in inc:
        return False
    exc = rule.get("exclude_apps") or []
    if exc and patch.get("app") in exc:
        return False
    return True


def evaluate_rules(rules: list[dict], patch: dict, host: Any) -> list[dict]:
    return [r for r in rules if evaluate_rule(r, patch, host)]