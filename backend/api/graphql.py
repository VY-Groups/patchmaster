"""GraphQL API - Query Patch-SecOps Solution data via GraphQL."""

import os
import logging
from typing import List, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from auth import get_current_user
from database import async_session
from models.db_models import Host, PatchJob, User, CVE

logger = logging.getLogger(__name__)


# --- GraphQL Types ---


@strawberry.type(description="A host in Patch-SecOps Solution")
class HostType:
    id: int
    hostname: str
    ip: str
    os_version: Optional[str]
    status: str
    last_seen: Optional[str]
    tenant_id: Optional[int]

    @classmethod
    def from_db(cls, host: Host) -> "HostType":
        return cls(
            id=host.id,
            hostname=host.hostname,
            ip=host.ip,
            os_version=host.os_version,
            status=host.status or "unknown",
            last_seen=host.last_seen.isoformat() if host.last_seen else None,
            tenant_id=host.tenant_id,
        )


@strawberry.type(description="A patch job")
class PatchJobType:
    id: int
    host_id: int
    status: str
    action: str
    started_at: Optional[str]
    completed_at: Optional[str]
    packages_installed: Optional[int]
    error_message: Optional[str]

    @classmethod
    def from_db(cls, job: PatchJob) -> "PatchJobType":
        return cls(
            id=job.id,
            host_id=job.host_id,
            status=job.status.value
            if hasattr(job.status, "value")
            else str(job.status),
            action=job.action.value
            if hasattr(job.action, "value")
            else str(job.action),
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            packages_installed=job.packages_installed,
            error_message=job.error_message,
        )


@strawberry.type(description="A CVE vulnerability")
class CVEType:
    id: int
    cve_id: str
    description: Optional[str]
    severity: str
    cvss_score: Optional[float]
    published_date: Optional[str]
    affected_packages: Optional[str]

    @classmethod
    def from_db(cls, cve: CVE) -> "CVEType":
        return cls(
            id=cve.id,
            cve_id=cve.cve_id,
            description=cve.description,
            severity=cve.severity or "unknown",
            cvss_score=cve.cvss_score,
            published_date=cve.published_date.isoformat()
            if cve.published_date
            else None,
            affected_packages=cve.affected_packages,
        )


@strawberry.type(description="A user")
class UserType:
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool

    @classmethod
    def from_db(cls, user: User) -> "UserType":
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name or "",
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            is_active=user.is_active,
        )


# --- Edge/Connection for Relay cursor pagination ---


@strawberry.type
class HostEdge:
    node: HostType
    cursor: str


@strawberry.type
class HostConnection:
    edges: List[HostEdge]
    page_info: "PageInfo"


@strawberry.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str]
    end_cursor: Optional[str]


# --- Queries ---


@strawberry.type
class Query:
    @strawberry.field(description="Get all hosts (paginated)")
    async def hosts(
        self,
        first: int = 10,
        after: Optional[str] = None,
        tenant_id: Optional[int] = None,
    ) -> HostConnection:
        async with async_session() as session:
            query = select(Host).order_by(Host.id)

            # Apply tenant filtering for multi-tenancy
            if tenant_id is not None:
                query = query.where(Host.tenant_id == tenant_id)

            # Handle cursor-based pagination
            if after:
                try:
                    after_id = int(after)
                    query = query.where(Host.id > after_id)
                except ValueError:
                    pass

            query = query.limit(first + 1)
            result = await session.execute(query)
            hosts = result.scalars().all()

            has_next = len(hosts) > first
            if has_next:
                hosts = hosts[:first]

            edges = [
                HostEdge(
                    node=HostType.from_db(h),
                    cursor=str(h.id),
                )
                for h in hosts
            ]

            return HostConnection(
                edges=edges,
                page_info=PageInfo(
                    has_next_page=has_next,
                    has_previous_page=after is not None,
                    start_cursor=edges[0].cursor if edges else None,
                    end_cursor=edges[-1].cursor if edges else None,
                ),
            )

    @strawberry.field(description="Get a single host by ID")
    async def host(self, id: int) -> Optional[HostType]:
        async with async_session() as session:
            result = await session.execute(select(Host).where(Host.id == id))
            host = result.scalar_one_or_none()
            return HostType.from_db(host) if host else None

    @strawberry.field(description="Get all patch jobs")
    async def patch_jobs(
        self,
        first: int = 10,
        host_id: Optional[int] = None,
    ) -> List[PatchJobType]:
        async with async_session() as session:
            query = select(PatchJob).order_by(PatchJob.id.desc())
            if host_id:
                query = query.where(PatchJob.host_id == host_id)
            query = query.limit(first)
            result = await session.execute(query)
            jobs = result.scalars().all()
            return [PatchJobType.from_db(j) for j in jobs]

    @strawberry.field(description="Get CVE by ID or CVE ID")
    async def cve(
        self,
        id: Optional[int] = None,
        cve_id: Optional[str] = None,
    ) -> Optional[CVEType]:
        async with async_session() as session:
            if id:
                result = await session.execute(select(CVE).where(CVE.id == id))
            elif cve_id:
                result = await session.execute(select(CVE).where(CVE.cve_id == cve_id))
            else:
                return None
            cve = result.scalar_one_or_none()
            return CVEType.from_db(cve) if cve else None

    @strawberry.field(description="List CVEs")
    async def cves(
        self,
        first: int = 10,
        severity: Optional[str] = None,
    ) -> List[CVEType]:
        async with async_session() as session:
            query = select(CVE).order_by(CVE.published_date.desc())
            if severity:
                query = query.where(CVE.severity == severity)
            query = query.limit(first)
            result = await session.execute(query)
            cves = result.scalars().all()
            return [CVEType.from_db(c) for c in cves]

    @strawberry.field(description="Get current user")
    async def me(self, info: strawberry.Info) -> Optional[UserType]:
        # This would use the request context to get current user
        # For now, return None - will be enhanced with auth context
        return None


# --- Mutations ---


@strawberry.input
class CreateHostInput:
    hostname: str
    ip: str
    os_version: Optional[str] = None
    tenant_id: Optional[int] = None


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Create a new host")
    async def create_host(self, input: CreateHostInput) -> HostType:
        async with async_session() as session:
            host = Host(
                hostname=input.hostname,
                ip=input.ip,
                os_version=input.os_version,
                tenant_id=input.tenant_id,
                status="pending",
            )
            session.add(host)
            await session.commit()
            await session.refresh(host)
            return HostType.from_db(host)


# --- Schema ---

schema = strawberry.Schema(query=Query, mutation=Mutation)


def create_graphql_router() -> GraphQLRouter:
    """Create and configure the GraphQL router.

    Every request must carry a valid access token (plan S0-1): the schema
    exposes host IPs/tenants and a create_host write mutation, so it is not
    read-only despite the old comment in main.py.
    """
    return GraphQLRouter(
        schema,
        path="/graphql",
        graphql_ide="graphiql",
        dependencies=[Depends(get_current_user)],
    )
