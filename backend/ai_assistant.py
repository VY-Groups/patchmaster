"""Optional read-only AI assistant (P6), introduced after core is stable."""

from __future__ import annotations

from typing import Any


async def answer(question: str, context: dict | None = None) -> dict:
    # read-only: never mutates. Returns a placeholder until an LLM is wired.
    return {"answer": "AI assistant not yet configured (read-only).", "sources": [], "read_only": True}