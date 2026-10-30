"""S1-3 RestorePoint abstraction: unified snapshot/restore interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Capability(str, Enum):
    full_snapshot = "full_snapshot"
    package_rollback = "package_rollback"
    config_only = "config_only"
    none = "none"


@dataclass
class RestorePointResult:
    ok: bool
    ref: Optional[str] = None
    message: str = ""
    observed: dict = field(default_factory=dict)


class RestorePoint(ABC):
    """Unified interface over platform snapshot/backup capabilities."""

    def __init__(self, host: Any = None, context: Optional[dict] = None):
        self.host = host
        self.context = context or {}

    @property
    @abstractmethod
    def capability(self) -> Capability:
        ...

    @property
    @abstractmethod
    def platform(self) -> str:
        ...

    @abstractmethod
    async def create(self) -> RestorePointResult:
        ...

    @abstractmethod
    async def verify(self, ref: Optional[str] = None) -> RestorePointResult:
        ...

    @abstractmethod
    async def restore(self, ref: Optional[str] = None) -> RestorePointResult:
        ...

    @abstractmethod
    async def delete(self, ref: Optional[str] = None) -> RestorePointResult:
        ...

    def describe(self) -> dict:
        return {
            "platform": self.platform,
            "capability": self.capability.value,
            "host_id": getattr(self.host, "id", None),
        }