"""Draft/preview/publish flow for deployments (P1.5)."""

from __future__ import annotations


def transition(current: str, action: str) -> str:
    """draft -> preview -> published; publish requires preview."""
    current = (current or "draft").lower()
    action = (action or "").lower()
    if action == "preview" and current in ("draft",):
        return "preview"
    if action == "publish" and current in ("preview", "draft"):
        return "published"
    if action == "save_draft":
        return "draft"
    return current


def is_publishable(status: str) -> bool:
    return (status or "").lower() in ("preview", "published")