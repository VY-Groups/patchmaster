"""Security middleware for API - headers, CORS, request tracing."""

import os
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers

# Security configuration
HSTS_MAX_AGE = 31536000  # 1 year
ALLOWED_CSP_SOURCES = os.getenv("ALLOWED_CSP_SOURCES", "self https:").split(",")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        return self.add_security_headers(response, request)

    def add_security_headers(
        self, response: Response, request: Request = None
    ) -> Response:
        """Add security headers to response."""
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = "nosniff"

        # X-Frame-Options
        origin = request.url.path if request else ""
        embed_prefixes = ("/api/monitoring/embed/", "/api/grafana/", "/api/prometheus/")

        if any(origin.startswith(p) for p in embed_prefixes):
            # Allow framing for embed endpoints
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        else:
            response.headers["X-Frame-Options"] = "DENY"

        # HSTS (only for HTTPS)
        if request and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                f"max-age={HSTS_MAX_AGE}; includeSubDomains; preload"
            )

        # Content-Security-Policy
        csp = self._build_csp()
        response.headers["Content-Security-Policy"] = csp

        # Referrer-Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
        )

        # Remove sensitive headers
        response.headers["Server"] = "Patch-SecOps Solution"
        response.headers["X-Powered-By"] = "Patch-SecOps Solution"

        return response

    def _build_csp(self) -> str:
        """Build Content-Security-Policy header value."""
        sources = " ".join(ALLOWED_CSP_SOURCES)

        return (
            f"default-src 'self'; "
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            f"style-src 'self' 'unsafe-inline' https:; "
            f"img-src 'self' data: blob: https:; "
            f"font-src 'self' https: data:; "
            f"connect-src 'self' https: http: ws: wss:; "
            f"frame-ancestors 'self'; "
            f"base-uri 'self'; "
            f"form-action 'self';"
        )


def get_security_headers() -> dict:
    """Return dictionary of security headers for manual addition."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": f"max-age={HSTS_MAX_AGE}; includeSubDomains; preload",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }


# ── CORS Configuration ──


def get_cors_config() -> dict:
    """Get CORS configuration from environment."""
    frontend_origins = os.getenv("FRONTEND_ORIGINS", "*")
    origins = [o.strip() for o in frontend_origins.split(",") if o.strip()]

    return {
        "allow_origins": origins,
        "allow_credentials": origins != ["*"],
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["*"],
        "expose_headers": ["X-Request-ID", "X-Trace-Token", "Content-Length"],
        "max_age": 600,  # 10 minutes cache for preflight
    }


# ── Request Tracing ──


def generate_request_id() -> str:
    """Generate a unique request ID."""
    import uuid

    return uuid.uuid4().hex


def get_request_id(request: Request) -> str:
    """Get request ID from headers or generate new one."""
    request_id = request.headers.get("X-Request-ID", "")
    if not request_id:
        request_id = generate_request_id()
    return request_id


def get_trace_token(request: Request) -> str:
    """Get trace token from headers or generate new one."""
    trace_token = request.headers.get("X-Trace-Token", "")
    if not trace_token:
        trace_token = generate_request_id()
    return trace_token


# ── Sensitive Data Filtering ──

# Headers that should not be exposed to clients
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}

# Response headers to remove
REMOVE_ON_RESPONSE = {
    "server",  # Hide server info
    "x-powered-by",
}


def filter_sensitive_headers(headers: Headers) -> dict:
    """Filter out sensitive headers from response."""
    return {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}


def remove_sensitive_response_headers(response: Response) -> Response:
    """Remove sensitive headers from response."""
    for header in REMOVE_ON_RESPONSE:
        if header in response.headers:
            del response.headers[header]
    return response
