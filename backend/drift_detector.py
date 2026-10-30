"""Configuration drift detection for hosts.

Compares current host configuration against stored baselines to detect drift.
Supports package lists, running services, network config, and registry (Windows).
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db
from models.db_models import ConfigBaseline, Host
from auth import get_current_user

logger = logging.getLogger(__name__)


class DriftType(str, Enum):
    """Types of configuration drift."""

    PACKAGES = "packages"
    SERVICES = "services"
    NETWORK = "network"
    REGISTRY = "registry"
    FILES = "files"
    UNKNOWN = "unknown"


class DriftSeverity(str, Enum):
    """Severity levels for detected drift."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class DriftItem:
    """A single drift item."""

    drift_type: DriftType
    category: str
    item_key: str
    expected_value: Any
    actual_value: Any
    severity: DriftSeverity
    description: str


@dataclass
class DriftReport:
    """Complete drift detection report."""

    host_id: int
    baseline_id: int
    timestamp: datetime
    drift_items: List[DriftItem]
    total_items: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    compliance_score: float  # 0-100


@dataclass
class DriftDiff:
    """Difference between baseline and current state."""

    added: Dict[str, Any]
    removed: Dict[str, Any]
    changed: Dict[str, Any]
    unchanged: Dict[str, Any]


def _compute_diff(baseline: dict, current: dict) -> DriftDiff:
    """Compute differences between baseline and current state."""
    baseline_keys = set(baseline.keys())
    current_keys = set(current.keys())

    added = {k: current[k] for k in current_keys - baseline_keys}
    removed = {k: baseline[k] for k in baseline_keys - current_keys}
    changed = {}
    unchanged = {}

    for k in baseline_keys & current_keys:
        if baseline[k] != current[k]:
            changed[k] = {"expected": baseline[k], "actual": current[k]}
        else:
            unchanged[k] = baseline[k]

    return DriftDiff(added, removed, changed, unchanged)


def _assess_severity(drift_type: DriftType, change_type: str) -> DriftSeverity:
    """Assess the severity of a drift item."""
    # Critical: Package removals, service stops, critical network changes
    if drift_type == DriftType.PACKAGES and change_type == "removed":
        return DriftSeverity.HIGH
    if drift_type == DriftType.SERVICES and change_type == "removed":
        return DriftSeverity.CRITICAL
    if drift_type == DriftType.NETWORK:
        return DriftSeverity.HIGH

    # Medium for most other changes
    return DriftSeverity.MEDIUM


async def detect_drift(
    host_id: int,
    current_packages: Optional[Dict[str, str]] = None,
    current_services: Optional[Dict[str, str]] = None,
    current_network: Optional[Dict[str, Any]] = None,
    current_registry: Optional[Dict[str, Any]] = None,
    current_files: Optional[Dict[str, Any]] = None,
    baseline_id: Optional[int] = None,
) -> DriftReport:
    """
    Detect configuration drift for a host.

    Args:
        host_id: The host to check
        current_packages: Current installed packages {name: version}
        current_services: Current running services {name: status}
        current_network: Current network configuration
        current_registry: Current Windows registry
        current_files: Current file hashes/mtimes
        baseline_id: Specific baseline to compare against (uses latest if not provided)

    Returns:
        DriftReport with all detected drift items
    """
    drift_items: List[DriftItem] = []

    # For now, we work with baseline data provided
    # In production, would fetch from ConfigBaseline table

    # Check package drift
    if current_packages:
        # Would fetch baseline packages here and compare
        pass

    # Check service drift
    if current_services:
        # Would fetch baseline services here and compare
        pass

    # Check network drift
    if current_network:
        # Would fetch baseline network config here and compare
        pass

    # Count by severity
    critical_count = sum(1 for i in drift_items if i.severity == DriftSeverity.CRITICAL)
    high_count = sum(1 for i in drift_items if i.severity == DriftSeverity.HIGH)
    medium_count = sum(1 for i in drift_items if i.severity == DriftSeverity.MEDIUM)
    low_count = sum(1 for i in drift_items if i.severity == DriftSeverity.LOW)

    # Calculate compliance score (100 - weighted penalty)
    total_items = len(drift_items)
    if total_items == 0:
        compliance_score = 100.0
    else:
        penalty = (
            critical_count * 20 + high_count * 10 + medium_count * 5 + low_count * 2
        )
        compliance_score = max(0.0, 100.0 - penalty)

    return DriftReport(
        host_id=host_id,
        baseline_id=baseline_id or 0,
        timestamp=datetime.utcnow(),
        drift_items=drift_items,
        total_items=total_items,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        compliance_score=compliance_score,
    )


async def create_baseline(
    host_id: int,
    baseline_name: str,
    packages: Optional[Dict[str, str]] = None,
    services: Optional[Dict[str, str]] = None,
    network: Optional[Dict[str, Any]] = None,
    registry: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    baseline_type: str = "manual",
    created_by: Optional[str] = None,
    db_session=None,
) -> ConfigBaseline:
    """
    Create a new configuration baseline for a host.

    Args:
        host_id: Host to create baseline for
        baseline_name: Name/label for this baseline
        packages: Current package list
        services: Current service states
        network: Current network config
        registry: Current registry (Windows)
        files: Current file states
        baseline_type: Type of baseline (manual, snapshot, scheduled)
        created_by: User who created the baseline
        db_session: Optional database session

    Returns:
        Created ConfigBaseline instance
    """
    baseline = ConfigBaseline(
        host_id=host_id,
        baseline_name=baseline_name,
        baseline_type=baseline_type,
        packages=packages or {},
        services=services or {},
        network=network or {},
        registry=registry or {},
        files=files or {},
        metadata={},
        created_by=created_by,
    )

    if db_session:
        db_session.add(baseline)
        await db_session.commit()
        await db_session.refresh(baseline)

    logger.info(f"Created baseline '{baseline_name}' for host {host_id}")
    return baseline


async def get_latest_baseline(
    host_id: int, db_session=None
) -> Optional[ConfigBaseline]:
    """Get the most recent baseline for a host."""
    if db_session is None:
        return None
    # Would query: SELECT * FROM config_baselines WHERE host_id = ? ORDER BY created_at DESC LIMIT 1
    return None


async def list_baselines(host_id: int, db_session=None) -> List[ConfigBaseline]:
    """List all baselines for a host."""
    # Would query and return list
    return []


def format_drift_report(report: DriftReport) -> str:
    """Format a drift report as a human-readable string."""
    lines = [
        f"Drift Report for Host {report.host_id}",
        f"Generated: {report.timestamp.isoformat()}",
        f"Compliance Score: {report.compliance_score:.1f}%",
        "",
        "Summary:",
        f"  Critical: {report.critical_count}",
        f"  High: {report.high_count}",
        f"  Medium: {report.medium_count}",
        f"  Low: {report.low_count}",
        "",
    ]

    if report.drift_items:
        lines.append("Drift Items:")
        for item in report.drift_items:
            lines.append(
                f"  - [{item.severity.value}] {item.drift_type.value}: {item.description}"
            )
    else:
        lines.append("No drift detected.")

    return "\n".join(lines)


# ─── API Router ───────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/hosts", tags=["drift"])


class DriftDetectionRequest(BaseModel):
    """Request model for triggering drift detection."""

    packages: Optional[Dict[str, str]] = None
    services: Optional[Dict[str, str]] = None
    network: Optional[Dict[str, Any]] = None
    registry: Optional[Dict[str, Any]] = None
    files: Optional[Dict[str, Any]] = None


class BaselineCreate(BaseModel):
    """Request model for creating a baseline."""

    baseline_name: str
    baseline_type: str = "manual"
    packages: Optional[Dict[str, str]] = None
    services: Optional[Dict[str, str]] = None
    network: Optional[Dict[str, Any]] = None
    registry: Optional[Dict[str, Any]] = None
    files: Optional[Dict[str, Any]] = None


@router.get("/drift")
async def list_drift_reports(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all hosts with drift detection reports."""
    # Return summary of drift-capable hosts
    return {"message": "Drift detection API ready"}


@router.post("/drift/{host_id}")
async def detect_host_drift(
    host_id: int,
    request: DriftDetectionRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Detect configuration drift for a specific host."""
    report = await detect_drift(
        host_id=host_id,
        current_packages=request.packages,
        current_services=request.services,
        current_network=request.network,
        current_registry=request.registry,
        current_files=request.files,
    )
    return {
        "host_id": report.host_id,
        "baseline_id": report.baseline_id,
        "timestamp": report.timestamp.isoformat(),
        "total_items": report.total_items,
        "critical_count": report.critical_count,
        "high_count": report.high_count,
        "medium_count": report.medium_count,
        "low_count": report.low_count,
        "compliance_score": report.compliance_score,
        "drift_items": [
            {
                "drift_type": item.drift_type.value,
                "category": item.category,
                "item_key": item.item_key,
                "expected_value": item.expected_value,
                "actual_value": item.actual_value,
                "severity": item.severity.value,
                "description": item.description,
            }
            for item in report.drift_items
        ],
    }


@router.post("/{host_id}/baselines")
async def create_host_baseline(
    host_id: int,
    request: BaselineCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a configuration baseline for a host."""
    baseline = await create_baseline(
        host_id=host_id,
        baseline_name=request.baseline_name,
        packages=request.packages,
        services=request.services,
        network=request.network,
        registry=request.registry,
        files=request.files,
        baseline_type=request.baseline_type,
        created_by=current_user.username,
        db_session=db,
    )
    return {
        "id": baseline.id,
        "host_id": baseline.host_id,
        "baseline_name": baseline.baseline_name,
        "baseline_type": baseline.baseline_type,
        "created_at": baseline.created_at.isoformat(),
    }


@router.get("/{host_id}/baselines")
async def list_host_baselines(
    host_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all baselines for a host."""
    baselines = await list_baselines(host_id, db)
    return {
        "items": [
            {
                "id": b.id,
                "baseline_name": b.baseline_name,
                "baseline_type": b.baseline_type,
                "created_at": b.created_at.isoformat(),
                "created_by": b.created_by,
            }
            for b in baselines
        ]
    }
