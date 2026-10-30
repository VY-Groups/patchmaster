"""Security audit logging for Patch-SecOps Solution Enterprise."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass, field

# Conditional imports to avoid hard dependencies when testing standalone
try:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from models.db_models import User
except ImportError:
    if TYPE_CHECKING:
        from typing import Union
    User = None
    AsyncSession = None

# Configure audit logger
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "audit.log")
AUDIT_LOG_LEVEL = logging.INFO

# Initialize audit logger
audit_logger = logging.getLogger("patchmaster.audit")
audit_logger.setLevel(AUDIT_LOG_LEVEL)

# Add file handler if not already present
if not audit_logger.handlers:
    try:
        handler = logging.FileHandler(AUDIT_LOG_FILE)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
        audit_logger.addHandler(handler)
    except (OSError, IOError):
        # If file logging fails, use stdout
        import sys

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        audit_logger.addHandler(handler)


# ── Audit Event Types ──


class AuditEventType(Enum):
    """Security audit event types."""

    # Authentication events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    LOGIN_ATTEMPT_BLOCKED = "login_attempt_blocked"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"
    MFA_CODE_SENT = "mfa_code_sent"
    MFA_CODE_FAILED = "mfa_code_failed"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_CHANGE_FAILED = "password_change_failed"
    TOKEN_ISSUED = "token_issued"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_REVOKED = "token_revoked"

    # Authorization events
    PERMISSION_DENIED = "permission_denied"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"

    # Data access events
    DATA_VIEWED = "data_viewed"
    DATA_EXPORTED = "data_exported"
    DATA_MODIFIED = "data_modified"
    DATA_DELETED = "data_deleted"

    # Configuration events
    CONFIG_CHANGED = "config_changed"
    CONFIG_ACCESSED = "config_accessed"
    POLICY_CHANGED = "policy_changed"

    # Security events
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    INTRUSION_ATTEMPT = "intrusion_attempt"
    SESSION_EXPIRED = "session_expired"
    CONCURRENT_LOGIN = "concurrent_login"

    # System events
    SYSTEM_START = "system_start"
    SYSTEM_SHUTDOWN = "system_shutdown"
    ERROR = "error"


@dataclass
class AuditEvent:
    """Security audit event."""

    event_type: AuditEventType
    user_id: Optional[int] = None
    username: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    result: str = "success"
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    request_id: Optional[str] = None


# ── Audit Logging Functions ──


def log_security_event(
    event_type: AuditEventType,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    resource: Optional[str] = None,
    action: Optional[str] = None,
    result: str = "success",
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
):
    """Log a security event."""
    event = AuditEvent(
        event_type=event_type,
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        user_agent=user_agent,
        resource=resource,
        action=action,
        result=result,
        details=details or {},
        request_id=request_id,
    )

    # Format as structured JSON
    event_data = {
        "event_type": event.event_type.value,
        "timestamp": event.timestamp,
        "user": {
            "id": event.user_id,
            "username": event.username,
        },
        "source": {
            "ip_address": event.ip_address,
            "user_agent": event.user_agent,
        },
        "resource": event.resource,
        "action": event.action,
        "result": event.result,
        "details": event.details,
        "request_id": event.request_id,
    }

    # Log both to logger and as structured JSON
    audit_logger.info(json.dumps(event_data))

    return event


def log_login_success(
    username: str,
    user_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    mfa_used: bool = False,
    request_id: Optional[str] = None,
):
    """Log successful login."""
    return log_security_event(
        event_type=AuditEventType.LOGIN_SUCCESS,
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        user_agent=user_agent,
        result="success",
        details={"mfa_used": mfa_used},
        request_id=request_id,
    )


def log_login_failed(
    username: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    reason: str = "invalid_credentials",
    request_id: Optional[str] = None,
):
    """Log failed login attempt."""
    return log_security_event(
        event_type=AuditEventType.LOGIN_FAILED,
        username=username,
        ip_address=ip_address,
        user_agent=user_agent,
        result="failure",
        details={"reason": reason},
        request_id=request_id,
    )


def log_permission_denied(
    user_id: int,
    username: str,
    permission: str,
    resource: Optional[str] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Log permission denied event."""
    return log_security_event(
        event_type=AuditEventType.PERMISSION_DENIED,
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        resource=resource,
        action=permission,
        result="denied",
        request_id=request_id,
    )


def log_rate_limit_exceeded(
    identifier: str,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Log rate limit exceeded event."""
    return log_security_event(
        event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
        username=identifier,
        ip_address=ip_address,
        resource=endpoint,
        result="blocked",
        request_id=request_id,
    )


def log_data_access(
    user_id: int,
    username: str,
    resource: str,
    action: str = "read",
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Log data access event."""
    return log_security_event(
        event_type=AuditEventType.DATA_VIEWED
        if action == "read"
        else AuditEventType.DATA_MODIFIED,
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        resource=resource,
        action=action,
        request_id=request_id,
    )


def log_config_change(
    user_id: int,
    username: str,
    config_key: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Log configuration change."""
    return log_security_event(
        event_type=AuditEventType.CONFIG_CHANGED,
        user_id=user_id,
        username=username,
        ip_address=ip_address,
        resource=config_key,
        result="changed",
        details={"old_value": old_value, "new_value": new_value},
        request_id=request_id,
    )


# ── Audit Query Helper ──


async def get_audit_logs(
    db: AsyncSession,
    user_id: Optional[int] = None,
    event_type: Optional[AuditEventType] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Query audit logs from database.

    Note: This is a placeholder. In production, you would have a dedicated
    audit log table/model. The actual implementation would query that table.
    """
    # Placeholder - in production, query actual audit log table
    return []


# ── Security Event Aggregation ──


def get_failed_login_count(username: str, window_minutes: int = 15) -> int:
    """Get count of failed login attempts in time window.

    Note: This is a placeholder. In production, this would query the audit logs.
    """
    # Placeholder - in production, query actual audit log table
    return 0


def get_suspicious_activity_alerts(timeframe_minutes: int = 60) -> List[Dict[str, Any]]:
    """Get suspicious activity alerts.

    Note: This is a placeholder. In production, this would query the audit logs.
    """
    # Placeholder - in production, query actual audit log table
    return []
