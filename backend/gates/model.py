"""S1-1 Gate model: GateDefinition, GateResult, GateDecision, enums.

Behaviour-preserving data model. Serializable to/from dict so it can live inside
``ring_rollout_policies.rollout_config`` (JSON) today and in the S1-5 DB tables
later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class GateSeverity(str, Enum):
    required = "required"
    advisory = "advisory"


class GateStatus(str, Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    overridden = "overridden"


class RunStatus(str, Enum):
    pending = "pending"
    running = "running"
    passed = "passed"
    failed = "failed"
    held = "held"
    rolled_back = "rolled_back"
    overridden = "overridden"


@dataclass
class GateDefinition:
    type: str
    parameters: dict = field(default_factory=dict)
    severity: str = "required"
    timeout_seconds: int = 60
    retry_count: int = 0

    @property
    def required(self) -> bool:
        return str(self.severity) == "required"

    @classmethod
    def from_dict(cls, data: dict) -> "GateDefinition":
        data = data or {}
        return cls(
            type=str(data.get("type", "")),
            parameters=dict(data.get("parameters") or {}),
            severity=str(data.get("severity", "required")),
            timeout_seconds=int(data.get("timeout_seconds", 60) or 60),
            retry_count=int(data.get("retry_count", 0) or 0),
        )

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "parameters": dict(self.parameters or {}),
            "severity": str(self.severity),
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
        }


@dataclass
class GateResult:
    gate_type: str
    status: str
    observed: dict = field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    raw_output_ref: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "gate_type": self.gate_type,
            "status": self.status,
            "observed": dict(self.observed or {}),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "raw_output_ref": self.raw_output_ref,
            "reason": self.reason,
        }


@dataclass
class GateDecision:
    outcome: str  # promote | hold | rollback
    reason: str = ""
    failed_required: list = field(default_factory=list)
    failed_advisory: list = field(default_factory=list)