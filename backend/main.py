import os
import sys
from pathlib import Path
import re
import logging
import json
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
# Ensure `backend/` is importable regardless of current working directory.
# This allows running `uvicorn backend.main:app` from the repo root (and keeps
# existing `uvicorn main:app` behavior when started from `backend/`).
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load root install env first, then backend env to allow backend-specific values
# to override shared install settings. This keeps `python -c "import main"` and
# other direct entrypoints working during installs/upgrades, not just systemd.
load_dotenv(BACKEND_DIR.parent / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=True)

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from database import init_db, get_db
from bootstrap_users import ensure_bootstrap_users
from bootstrap_smtp import ensure_bootstrap_smtp_channel
from sqlalchemy import select, func
from models.db_models import Host
from api.auth_api import router as auth_router
from api.register_v2 import router as register_router
from api.hosts_v2 import router as hosts_router
from api.jobs_v2 import router as jobs_router
from api.agent_proxy import router as agent_proxy_router
from api.groups import router as groups_router, tags_router
from api.schedules import router as schedules_router
from api.rolling_restart import router as rolling_restart_router
from api.windows_snapshot import router as windows_snapshot_router
from api.canary_testing import router as canary_testing_router
from api.audit import router as audit_router
from api.compliance import router as compliance_router
from api.cve import router as cve_router
from api.notifications import router as notifications_router
from api.metrics import router as metrics_router, MetricsMiddleware
from api.packages_router import router as packages_router
from api.license_router import router as license_router
from api.cicd import router as cicd_router
from api.cicd_secrets import router as cicd_secrets_router
from api.cicd_agent_targets import router as cicd_agent_targets_router
from api.git_integration import router as git_router
from api.monitoring import router as monitoring_router
from api.backups import router as backups_router
from api.backups import check_schedules  # New scheduler
from api.policies import router as policies_router
from api.reports import router as reports_router
from api.dashboard import router as dashboard_router
from api.search import router as search_router
from api.sla import router as sla_router
from api.remediation import router as remediation_router
from api.maintenance import router as maintenance_router
from api.hooks import router as hooks_router
from api.bulk_patch import router as bulk_patch_router
from api.host_timeline import router as host_timeline_router
from api.agent_update import router as agent_update_router
from api.testing import router as testing_router
from api.mirror_repos import router as mirror_router, run_due_mirror_tasks
from api.ops_queue import router as ops_queue_router, ensure_ops_queue_started
from api.plugins import router as plugins_router
from api.counter_plan import router as counter_plan_router
from api.evidence import router as evidence_router
from api.tenants import router as tenants_router
from api.ring_rollout import router as ring_rollout_router
from api.relay import router as relay_router
from api.restore_drills import router as restore_drills_router
from api.runbook import router as runbook_router, run_due_runbook_schedules
from api.patch_history_presets import router as patch_history_presets_router
from api.ldap_auth import router as ldap_router
from api.software_kiosk import router as software_kiosk_router
from api.provisioning import router as provisioning_router
from api.oidc_auth import router as oidc_router
from api.network_boot import (
    public_router as network_boot_public_router,
    router as network_boot_router,
)
from license import get_license_info, get_licensed_features
from api.graphql import create_graphql_router
from multi_tenant import MultiTenantMiddleware
import monitoring_manager
from drift_detector import router as drift_router
from prometheus_targets import sync_prometheus_agent_targets
import version_checker
import asyncio
import uuid


def _configure_json_logging():
    """Optional JSON logging for easier ingestion (set BACKEND_JSON_LOGS=1)."""
    if os.getenv("BACKEND_JSON_LOGS", "0").lower() not in {"1", "true", "yes"}:
        return

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_configure_json_logging()

logger = logging.getLogger("patchmaster")


async def backup_scheduler_loop():
    while True:
        try:
            from database import async_session

            async with async_session() as session:
                await check_schedules(session)
        except Exception as e:
            logger.error(f"Backup scheduler error: {e}")
        await asyncio.sleep(60)


async def mirror_scheduler_loop():
    while True:
        try:
            from database import async_session

            async with async_session() as session:
                await run_due_mirror_tasks(session)
        except Exception as e:
            logger.error(f"Mirror scheduler error: {e}")
        await asyncio.sleep(60)


async def runbook_scheduler_loop():
    while True:
        try:
            from database import async_session

            async with async_session() as session:
                await run_due_runbook_schedules(session)
        except Exception as e:
            logger.error(f"Runbook scheduler error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables (optional for faster startup).
    # Default keeps existing behavior for safety.
    auto_create = os.getenv("PM_AUTO_CREATE_TABLES", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }
    init_timeout = int(os.getenv("PM_INIT_DB_TIMEOUT_SECONDS", "15"))
    if auto_create:
        try:
            await asyncio.wait_for(init_db(), timeout=init_timeout)
            bootstrap_result = await ensure_bootstrap_users()
            if bootstrap_result.get("created"):
                logger.warning(
                    "Bootstrap users are ready for first login: %s",
                    ", ".join(bootstrap_result["created"]),
                )
            smtp_result = await ensure_bootstrap_smtp_channel()
            if smtp_result.get("created"):
                logger.warning("SMTP email channel ready for OTP delivery at first run")
            # Run schema self-heal once at startup (not on every request)
            try:
                from api.register_v2 import _ensure_host_schema
                from api.cicd_secrets import migrate_legacy_inline_secrets
                from database import async_session as _async_session

                async with _async_session() as _db:
                    await _ensure_host_schema(_db)
                    migrated = await migrate_legacy_inline_secrets(_db)
                    if migrated:
                        logger.info(
                            "Migrated %s legacy inline CI/CD or Git secrets to encrypted storage.",
                            migrated,
                        )
                    await _db.commit()
            except Exception as _e:
                logger.warning("Startup schema/secret hardening step failed: %s", _e)
        except asyncio.TimeoutError:
            logger.error("Database initialization timed out on startup")
        except Exception as e:
            logger.error(f"Database initialization failed on startup: {e}")
    else:
        logger.info("Skipping auto DB table creation (PM_AUTO_CREATE_TABLES=0)")

    try:
        from database import async_session as _async_session

        async with _async_session() as _db:
            await sync_prometheus_agent_targets(_db)
    except Exception as e:
        logger.warning("Prometheus agent target sync failed on startup: %s", e)

    # Background tasks
    ensure_ops_queue_started(worker_count=int(os.getenv("PM_OPS_QUEUE_WORKERS", "2")))
    asyncio.create_task(backup_scheduler_loop())
    asyncio.create_task(mirror_scheduler_loop())
    asyncio.create_task(runbook_scheduler_loop())

    # Enforce license-based monitoring
    try:
        info = get_license_info(force_refresh=True)  # Always force-refresh on startup
        features = info.get("features", [])
        if info.get("valid") and not info.get("expired"):
            monitoring_manager.enforce_license(features)
        else:
            monitoring_manager.enforce_license([])
    except Exception as e:
        logger.warning(f"Monitoring startup check failed: {e}")

    yield


app = FastAPI(title="Patch-SecOps Solution by VYGROUP", version="2.0.17", lifespan=lifespan)

# Rate limiting (S0-1): without this link slowapi's @limiter.limit decorators
# never fire - it checks limits from its middleware only.
from api.auth_api import install_rate_limiting  # noqa: E402

install_rate_limiting(app)

# ── License enforcement middleware ──
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _request_trace_from_state(request: Request) -> tuple[str, str]:
    request_id = (
        str(getattr(request.state, "request_id", "") or "").strip() or uuid.uuid4().hex
    )
    trace_token = (
        str(getattr(request.state, "trace_token", "") or "").strip() or uuid.uuid4().hex
    )
    return request_id, trace_token


def _error_envelope(
    request: Request, status_code: int, detail: object, error_type: str
) -> dict:
    request_id, trace_token = _request_trace_from_state(request)
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or "Request failed")
    else:
        message = str(detail or "Request failed")
    return {
        "error": {
            "type": error_type,
            "status_code": status_code,
            "message": message,
            "request_id": request_id,
            "trace_token": trace_token,
        },
        "detail": detail,
        "request_id": request_id,
        "trace_token": trace_token,
    }


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = (
            str(request.headers.get("x-request-id", "")).strip() or uuid.uuid4().hex
        )
        trace_token = (
            str(request.headers.get("x-trace-token", "")).strip() or uuid.uuid4().hex
        )
        request.state.request_id = request_id
        request.state.trace_token = trace_token
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-Token"] = trace_token
        return response


@app.middleware("http")
async def api_versioning_rewrite(request: Request, call_next):
    """Seamlessly alias /api/v1/ endpoints to their /api/ equivalents."""
    if request.url.path.startswith("/api/v1/"):
        request.scope["path"] = request.scope["path"].replace("/api/v1/", "/api/", 1)
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_exception_envelope_handler(request: Request, exc: HTTPException):
    payload = _error_envelope(request, exc.status_code, exc.detail, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers={
            "X-Request-ID": payload["request_id"],
            "X-Trace-Token": payload["trace_token"],
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_envelope_handler(
    request: Request, exc: RequestValidationError
):
    payload = _error_envelope(request, 422, exc.errors(), "validation_error")
    return JSONResponse(
        status_code=422,
        content=payload,
        headers={
            "X-Request-ID": payload["request_id"],
            "X-Trace-Token": payload["trace_token"],
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_envelope_handler(request: Request, exc: Exception):
    expose_reason = os.getenv(
        "PM_EXPOSE_INTERNAL_ERROR_REASON", "0"
    ).strip().lower() in {"1", "true", "yes"}
    detail: object = {"message": "Internal server error"}
    if expose_reason:
        detail = {"message": "Internal server error", "reason": str(exc)}
    payload = _error_envelope(request, 500, detail, "internal_error")
    return JSONResponse(
        status_code=500,
        content=payload,
        headers={
            "X-Request-ID": payload["request_id"],
            "X-Trace-Token": payload["trace_token"],
        },
    )


class LicenseMiddleware(BaseHTTPMiddleware):
    # Paths that work without a valid license
    EXEMPT_PATHS = (
        "/api/health",
        "/api/register",
        "/api/heartbeat",
        "/api/license/",
        "/api/auth/",  # all auth endpoints exempt (login, me, register, forgot, reset, etc.)
        "/api/monitoring/status",
        "/docs",
        "/openapi.json",
        "/static/",
        "/boot/",
        "/metrics",
        "/graphql",  # GraphQL API (requires Bearer access token; has write mutations)
    )

    # Map API path prefixes to required feature names for tier enforcement
    FEATURE_PATH_MAP = {
        "/api/cicd": "cicd",
        "/api/git": "git",
        "/api/cve": "cve",
        "/api/compliance": "compliance",
        "/api/audit": "audit",
        "/api/notifications": "notifications",
        "/api/monitoring": "monitoring",
        "/api/backups": "backup_db",  # Check base backup permission
        "/api/policies": "policies",
        "/api/reports": "reports",
        "/api/packages": "local-repo",
        "/api/mirror": "local-repo",
        "/api/network-boot": "onboarding",
    }
    FEATURE_PATH_ITEMS = tuple(FEATURE_PATH_MAP.items())
    EXEMPT_PREFIXES = tuple(EXEMPT_PATHS)
    AGENT_SOFTWARE_RE = re.compile(r"^/api/agent/[^/]+/software/manage")
    EMBED_PREFIXES = (
        "/api/monitoring/embed/prometheus",
        "/api/monitoring/embed/grafana",
    )

    async def dispatch(self, request, call_next):
        path = request.url.path
        # Always allow OPTIONS (CORS preflight) — CORSMiddleware handles it but be safe
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response
        # Allow exempt paths
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            response = await call_next(request)
            return self.add_security_headers(response, path)

        # Check license
        info = get_license_info()
        if not info.get("valid", False):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": info.get(
                        "error", "License is invalid. Please activate a valid license."
                    ),
                    "license_status": "invalid",
                },
            )
        if not info.get("activated", False):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "No license activated. Please activate a license to use Patch-SecOps Solution.",
                    "license_status": "not_activated",
                },
            )
        if info.get("expired", True):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"License expired on {info.get('expires_at', 'unknown')}. Please renew.",
                    "license_status": "expired",
                },
            )
        # Tier-based feature enforcement
        licensed_features = info.get("features", [])
        has_backup_feature = any(f.startswith("backup_") for f in licensed_features)
        tier = info.get("tier_label", info.get("tier", "Unknown"))
        current_tier = info.get("tier", "")
        for prefix, feature in self.FEATURE_PATH_ITEMS:
            if path.startswith(prefix):
                # For backups, granular check is done in endpoint, but base check here
                # Check if ANY backup feature is enabled
                if "backups" in prefix:
                    if not has_backup_feature:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Backups not included in license"},
                        )
                elif feature not in licensed_features:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": f"Feature '{feature}' is not included in your {tier} license. Upgrade to access this feature.",
                            "license_status": "tier_restricted",
                            "required_feature": feature,
                            "current_tier": current_tier,
                        },
                    )

        # Fine-grained checks for specific agent proxy routes
        if self.AGENT_SOFTWARE_RE.match(path):
            if "software" not in licensed_features:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": f"Feature 'software' is not included in your {tier} license. Upgrade to access this feature.",
                        "license_status": "tier_restricted",
                        "required_feature": "software",
                        "current_tier": current_tier,
                    },
                )

        # Host limit enforcement (only on registration/adding hosts)
        if path == "/api/register" and request.method == "POST":
            max_hosts = info.get("max_hosts", 0)
            if max_hosts > 0:
                from database import async_session

                async with async_session() as db:
                    count = await db.scalar(select(func.count(Host.id)))
                    if count >= max_hosts:
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": f"Host limit reached ({max_hosts}). Please upgrade your license to add more hosts.",
                                "license_status": "host_limit_reached",
                                "limit": max_hosts,
                            },
                        )

        response = await call_next(request)
        return self.add_security_headers(response, path)

    def add_security_headers(self, response, path: str = ""):
        # Add basic API security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not any(path.startswith(prefix) for prefix in self.EMBED_PREFIXES):
            response.headers["X-Frame-Options"] = "DENY"
        elif "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Enterprise Hardening: Full security headers
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' https:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https:; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' https: data:; "
            "connect-src 'self' https: http: ws: wss:;"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        return response


# Middleware registration order matters in Starlette: last added = outermost (runs first).
# Correct order: LicenseMiddleware added first (innermost), CORSMiddleware added last (outermost).
# This ensures CORS headers are always present — even on 403 responses — so the browser
# never sees a CORS failure on OPTIONS preflight requests.

# 1. LicenseMiddleware — innermost, runs after CORS
app.add_middleware(LicenseMiddleware)

# 2. Multi-tenant isolation
app.add_middleware(MultiTenantMiddleware)

# 3. Prometheus metrics
app.add_middleware(MetricsMiddleware)

app.add_middleware(TraceMiddleware)

# 4. CORSMiddleware — outermost, runs first, handles OPTIONS preflight before anything else
frontend_origins = os.getenv("FRONTEND_ORIGINS", "*")
origins = [o.strip() for o in frontend_origins.split(",") if o.strip()]
allow_creds = origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Serve static files (for agent .deb download)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/api/health")
@app.get("/health")
@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "version": "2.0.17"}


@app.get("/api/version")
async def version_info():
    return {"version": "2.0.17"}


@app.get("/v1/models")
async def openai_models():
    return {"object": "list", "data": [{"id": "patchmaster", "object": "model", "owned_by": "patchmaster"}]}


@app.get("/api/system/update-status")
async def update_status():
    """Return whether a new Patch-SecOps Solution version is available."""
    return version_checker.get_update_status()


# Auth & Users
app.include_router(auth_router)
app.include_router(oidc_router)
# Agent registration & heartbeat
app.include_router(register_router)
# Host management
app.include_router(hosts_router)
# Patch jobs
app.include_router(jobs_router)
# Agent proxy (forward commands to agents)
app.include_router(agent_proxy_router)
# Host groups & tags
app.include_router(groups_router)
app.include_router(tags_router)
# Patch scheduling
app.include_router(schedules_router)
# Rolling restart
app.include_router(rolling_restart_router)
# Windows snapshots
app.include_router(windows_snapshot_router)
# Canary testing
app.include_router(canary_testing_router)
# Audit trail
app.include_router(audit_router)
# Compliance dashboard
app.include_router(compliance_router)
# CVE tracking
app.include_router(cve_router)
# Notifications
app.include_router(notifications_router)
# Prometheus metrics
app.include_router(metrics_router)
# Local packages (air-gapped repo)
app.include_router(packages_router)
# Monitoring service management
app.include_router(monitoring_router)
# License management
app.include_router(license_router)
# CI/CD pipelines
app.include_router(cicd_router)
app.include_router(cicd_secrets_router)
app.include_router(cicd_agent_targets_router)
# Git repository integration
app.include_router(git_router)
# Backups
app.include_router(backups_router)
# Policies
app.include_router(policies_router)
# Reports
app.include_router(reports_router)
# Dashboard summary
app.include_router(dashboard_router)
# Global search
app.include_router(search_router)
# SLA tracking
app.include_router(sla_router)
# CVE Remediation workflow
app.include_router(remediation_router)
# Maintenance windows
app.include_router(maintenance_router)
# Pre/Post patch hooks
app.include_router(hooks_router)
# Bulk patch jobs
app.include_router(bulk_patch_router)
app.include_router(host_timeline_router)
app.include_router(agent_update_router)
app.include_router(testing_router)
app.include_router(mirror_router)
app.include_router(ops_queue_router)
app.include_router(plugins_router)
app.include_router(counter_plan_router)
app.include_router(evidence_router)
app.include_router(tenants_router)
app.include_router(ring_rollout_router)
app.include_router(relay_router)
app.include_router(restore_drills_router)
app.include_router(runbook_router)
app.include_router(patch_history_presets_router)
app.include_router(ldap_router)
app.include_router(software_kiosk_router)
app.include_router(provisioning_router)
app.include_router(network_boot_router)
app.include_router(network_boot_public_router)

# Drift detection
app.include_router(drift_router)

# GraphQL API (strawberry-graphql)
graphql_router = create_graphql_router()
app.include_router(graphql_router)
