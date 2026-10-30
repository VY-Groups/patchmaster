"""Prometheus metrics for Patch-SecOps Solution backend."""
import time
from prometheus_client import (
    Counter, Gauge, Histogram, Info,
    generate_latest, CONTENT_TYPE_LATEST,
)
from fastapi import APIRouter, Response, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models.db_models import Host, PatchJob, CVE, HostCVE, JobStatus, Severity

router = APIRouter(tags=["metrics"])

# ── Gauges (current state) ──
hosts_total = Gauge("patchmaster_hosts_total", "Total registered hosts")
hosts_online = Gauge("patchmaster_hosts_online", "Currently online hosts")
hosts_reboot_required = Gauge("patchmaster_hosts_reboot_required", "Hosts needing reboot")
packages_upgradable = Gauge("patchmaster_packages_upgradable_total", "Total upgradable packages across all hosts")
compliance_avg = Gauge("patchmaster_compliance_avg_score", "Average compliance score (0-100)")
cve_total = Gauge("patchmaster_cve_total", "Total tracked CVEs", ["severity"])
cve_unpatched = Gauge("patchmaster_cve_unpatched_total", "Unpatched CVEs", ["severity"])

# ── Counters (cumulative) ──
api_requests = Counter("patchmaster_api_requests_total", "API requests", ["method", "path", "status"])

# ── Gauges for job status counts (reset-able, unlike counters) ──
jobs_by_status = Gauge("patchmaster_jobs_by_status", "Patch jobs by status", ["status"])

# ── Histograms ──
api_latency = Histogram("patchmaster_api_request_duration_seconds", "API request latency", ["method", "path"])

# ── Info ──
app_info = Info("patchmaster", "Patch-SecOps Solution application info")
app_info.info({"version": "2.0.0", "component": "backend"})


async def refresh_gauges():
    """Query DB and update all gauge metrics."""
    try:
        async with async_session() as db:
            # Hosts
            result = await db.execute(select(func.count(Host.id)))
            hosts_total.set(result.scalar() or 0)

            result = await db.execute(select(func.count(Host.id)).where(Host.is_online == True))
            hosts_online.set(result.scalar() or 0)

            result = await db.execute(select(func.count(Host.id)).where(Host.reboot_required == True))
            hosts_reboot_required.set(result.scalar() or 0)

            result = await db.execute(select(func.coalesce(func.sum(Host.upgradable_count), 0)))
            packages_upgradable.set(result.scalar() or 0)

            result = await db.execute(select(func.coalesce(func.avg(Host.compliance_score), 100.0)))
            compliance_avg.set(round(result.scalar() or 100.0, 1))

            # Jobs by status
            for s in JobStatus:
                result = await db.execute(
                    select(func.count(PatchJob.id)).where(PatchJob.status == s)
                )
                jobs_by_status.labels(status=s.value).set(result.scalar() or 0)

            # CVEs by severity
            for sev in [Severity.critical, Severity.high, Severity.medium, Severity.low]:
                result = await db.execute(
                    select(func.count(CVE.id)).where(CVE.severity == sev)
                )
                cve_total.labels(severity=sev.value).set(result.scalar() or 0)

                result = await db.execute(
                    select(func.count()).select_from(HostCVE).where(
                        HostCVE.status == "active",
                        HostCVE.cve_id.in_(
                            select(CVE.id).where(CVE.severity == sev)
                        )
                    )
                )
                cve_unpatched.labels(severity=sev.value).set(result.scalar() or 0)
    except Exception:
        pass  # Metrics refresh should never crash the app


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint."""
    await refresh_gauges()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class MetricsMiddleware:
    """ASGI middleware to track request count and latency."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Skip metrics endpoint itself to avoid recursion
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        # Normalize path: collapse IDs to {id}
        import re
        normalized = re.sub(r"/\d+", "/{id}", path)

        start = time.time()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.time() - start
            api_requests.labels(method=method, path=normalized, status=str(status_code)).inc()
            api_latency.labels(method=method, path=normalized).observe(duration)
