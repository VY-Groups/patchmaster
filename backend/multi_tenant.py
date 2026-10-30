"""Multi-tenant isolation middleware and utilities.

Provides tenant context management, row-level security, and tenant isolation
for Patch-SecOps Solution data.
"""

import logging
from typing import Optional, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum

from fastapi import Request, HTTPException, Depends
from starlette.middleware.base import BaseHTTPMiddleware

from auth import get_current_user
from models.db_models import User, UserRole

logger = logging.getLogger(__name__)


# Context variable for storing current tenant ID
_current_tenant_id: ContextVar[Optional[int]] = ContextVar(
    "current_tenant_id", default=None
)


class TenantIsolationError(Exception):
    """Raised when tenant isolation is violated."""

    pass


@dataclass
class TenantContext:
    """Current tenant context information."""

    tenant_id: int
    tenant_name: str
    is_root: bool  # Root tenant can access all data


def get_current_tenant_id() -> Optional[int]:
    """Get the current tenant ID from context."""
    return _current_tenant_id.get()


def set_current_tenant(tenant_id: Optional[int]) -> None:
    """Set the current tenant ID in context."""
    _current_tenant_id.set(tenant_id)


def require_tenant(tenant_id: int) -> None:
    """Require that a tenant context is set.

    Raises:
        TenantIsolationError: If no tenant context is set
    """
    current = get_current_tenant_id()
    if current is None:
        raise TenantIsolationError("No tenant context set")
    if current != tenant_id and current != 0:  # 0 = root tenant
        raise TenantIsolationError(
            f"Tenant {tenant_id} does not match current tenant {current}"
        )


class TenantIsolationLevel(str, Enum):
    """Level of tenant isolation enforcement."""

    NONE = "none"  # No isolation - legacy behavior
    STRICT = "strict"  # Full tenant isolation
    AUDIT = "audit"  # Log all cross-tenant access attempts


class MultiTenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts tenant information from JWT or API key
    and sets the tenant context for the request.
    """

    def __init__(
        self, app, isolation_level: TenantIsolationLevel = TenantIsolationLevel.STRICT
    ):
        super().__init__(app)
        self.isolation_level = isolation_level

    async def dispatch(self, request: Request, call_next):
        tenant_id = None

        # Extract tenant from JWT claims if available
        # The actual user extraction is done by auth.get_current_user
        # Here we rely on the request state set by auth middleware

        # Check for tenant header (for service-to-service calls)
        tenant_header = request.headers.get("X-Tenant-ID")
        if tenant_header:
            try:
                tenant_id = int(tenant_header)
                if tenant_id < 0 or tenant_id > 999999:  # Reasonable bounds
                    logger.warning(f"Invalid X-Tenant-ID header: {tenant_header}")
                    tenant_id = None
            except ValueError:
                logger.warning(f"Invalid X-Tenant-ID header: {tenant_header}")
                tenant_id = None

        # Set tenant context
        token = _current_tenant_id.set(tenant_id)
        try:
            response = await call_next(request)
            return response
        finally:
            _current_tenant_id.reset(token)


def filter_by_tenant(query, model_class, tenant_column_name: str = "tenant_id"):
    """
    Filter a SQLAlchemy query by current tenant.

    Args:
        query: SQLAlchemy query to filter
        model_class: Model class to apply filter to
        tenant_column_name: Name of the tenant ID column

    Returns:
        Filtered query with tenant constraint
    """
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        # No tenant context - return query as-is (legacy behavior)
        # In strict mode, this might raise an error
        return query

    # Apply tenant filter if the column exists
    if hasattr(model_class, tenant_column_name):
        return query.where(getattr(model_class, tenant_column_name) == tenant_id)

    return query


def require_root_tenant() -> None:
    """Require root tenant access."""
    tenant_id = get_current_tenant_id()
    if tenant_id != 0:
        raise HTTPException(status_code=403, detail="Root tenant access required")


async def get_tenant_from_request(request: Request) -> Optional[int]:
    """Extract tenant ID from request."""
    # Try to get from JWT
    # For now, return None - would be connected to auth system
    return None


def tenant_dependency() -> Optional[int]:
    """FastAPI dependency for getting current tenant."""

    async def _get_tenant(request: Request):
        return await get_tenant_from_request(request)

    return Depends(_get_tenant)


# Tenant-aware query helpers
class TenantQueryMixin:
    """Mixin to add tenant filtering to models."""

    @classmethod
    def get_tenant_filter(cls, tenant_id: int):
        """Get tenant filter for this model."""
        if hasattr(cls, "tenant_id"):
            return cls.tenant_id == tenant_id
        return None


# Decorator for tenant-scoped operations
def tenant_scoped(tenant_id: int) -> Callable:
    """Decorator to execute code within a specific tenant context."""

    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            token = _current_tenant_id.set(tenant_id)
            try:
                return await func(*args, **kwargs)
            finally:
                _current_tenant_id.reset(token)

        return wrapper

    return decorator


# Tenant validation utilities
def validate_tenant_access(
    requested_tenant_id: int,
    user_tenant_id: Optional[int],
    is_admin: bool = False,
) -> bool:
    """
    Validate that a user can access a specific tenant's data.

    Args:
        requested_tenant_id: The tenant being accessed
        user_tenant_id: The user's assigned tenant
        is_admin: Whether user has admin role

    Returns:
        True if access is allowed
    """
    # Admin can access any tenant
    if is_admin:
        return True

    # User can only access their own tenant
    if user_tenant_id is None:
        return False

    return user_tenant_id == requested_tenant_id or user_tenant_id == 0


# Tenant context manager for manual scoping
class TenantScope:
    """Context manager for temporarily setting tenant context."""

    def __init__(self, tenant_id: int):
        self.tenant_id = tenant_id
        self.token = None

    def __enter__(self):
        self.token = _current_tenant_id.set(self.tenant_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _current_tenant_id.reset(self.token)
        return False

    async def __aenter__(self):
        self.token = _current_tenant_id.set(self.tenant_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        _current_tenant_id.reset(self.token)
        return False


# Tenant-aware API key validation
async def validate_tenant_api_key(
    api_key: str,
    required_tenant_id: int,
) -> bool:
    """Validate that an API key has access to a specific tenant."""
    # Would check API key against database
    # For now, return False - needs implementation
    return False
