#!/usr/bin/env python3
"""plan.md S0-8: seed generator - hundreds of hosts and thousands of CVEs.

Idempotent: hostnames and CVE ids are the conflict keys, so re-running only
fills in what is missing. Seeded rows are tagged (hosts.site="seed",
cves.source="seed") so they can be counted and deleted again.

Run it where DATABASE_URL is reachable, e.g. against the dev stack:

    docker run --rm --network patchmaster_internal -v <repo>:/work -w /work \\
        -e DATABASE_URL=... patchmaster-backend python scripts/seed_data.py

Exit status is non-zero if the database did not end up with at least as many
seeded rows as were asked for (the self-check).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from models.db_models import CVE, Host, HostCVE, Severity  # noqa: E402

SITE = "seed"
OS_MATRIX = (
    ("Debian GNU/Linux", "12"),
    ("Ubuntu", "22.04"),
    ("Rocky Linux", "9"),
    ("Alpine Linux", "3.19"),
    ("Windows Server 2022", "10.0.20348"),
    ("Windows 11 Enterprise", "10.0.22631"),
)
SEVERITIES = (
    Severity.critical,
    Severity.high,
    Severity.medium,
    Severity.low,
    Severity.negligible,
)


def host_rows(count: int, rng: random.Random) -> list[dict]:
    """Stable hostnames/ips so a second run collides instead of duplicating."""
    rows = []
    for i in range(1, count + 1):
        os_name, os_version = OS_MATRIX[i % len(OS_MATRIX)]
        rows.append(
            {
                "hostname": f"seed-{i:04d}.{SITE}.example.internal",
                "ip": f"10.{(i // 250) % 250}.{(i // 250) % 250}.{i % 250 or 250}",
                "site": SITE,
                "os": os_name,
                "os_version": os_version,
                "kernel": "5.15.0-seed",
                "arch": "x86_64",
                "agent_version": "2.0.0",
                "is_online": True,
                "last_heartbeat": datetime.now(timezone.utc).replace(tzinfo=None),
                "installed_count": rng.randint(120, 900),
                "upgradable_count": rng.randint(0, 40),
                "compliance_score": round(rng.uniform(55.0, 100.0), 1),
            }
        )
    return rows


def cve_rows(count: int, rng: random.Random) -> list[dict]:
    """CVE ids from 2020 on are unique; re-running hits the primary key."""
    rows = []
    for i in range(1, count + 1):
        year = 2020 + (i % 7)
        severity = SEVERITIES[min(int(rng.triangular(0, 4.99)), len(SEVERITIES) - 1)]
        score = {
            Severity.critical: 9.4,
            Severity.high: 8.0,
            Severity.medium: 5.5,
            Severity.low: 3.1,
            Severity.negligible: 1.0,
        }[severity]
        rows.append(
            {
                "id": f"CVE-{year}-{i:05d}",
                "description": f"Seeded vulnerability {i} (plan.md S0-8 fixture).",
                "severity": severity,
                "cvss_score": round(min(10.0, score + rng.uniform(-0.9, 0.9)), 1),
                "published_date": datetime(year, 1, 1)
                + timedelta(days=rng.randint(0, 364)),
                "source": "seed",
            }
        )
    return rows


def link_rows(host_ids: list[int], cve_ids: list[str], count: int, rng: random.Random):
    """(host_id, cve_id) pairs, de-duplicated so the run stays idempotent."""
    sample = min(3, len(cve_ids))
    pairs = {(h, c) for h in host_ids for c in rng.sample(cve_ids, sample)}
    ceiling = len(host_ids) * len(cve_ids)
    while len(pairs) < count and len(pairs) < ceiling:
        pairs.add((rng.choice(host_ids), rng.choice(cve_ids)))
    return [
        {
            "host_id": h,
            "cve_id": c,
            "package_name": f"pkg-{rng.randint(1, 400)}",
            "current_version": f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.0",
            "fixed_version": f"{rng.randint(1, 9)}.{rng.randint(21, 40)}.0",
            "status": "active",
        }
        for h, c in sorted(pairs)
    ]


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy import func
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(
            pg_insert(Host)
            .values(host_rows(args.hosts, rng))
            .on_conflict_do_nothing(index_elements=["hostname"])
        )
        await conn.execute(
            pg_insert(CVE)
            .values(cve_rows(args.cves, rng))
            .on_conflict_do_nothing(index_elements=["id"])
        )

    async with session_factory() as session:
        host_ids = (
            (await session.execute(select(Host.id).where(Host.site == SITE)))
            .scalars()
            .all()
        )
        cve_ids = (
            (await session.execute(select(CVE.id).where(CVE.source == "seed")))
            .scalars()
            .all()
        )

    async with engine.begin() as conn:
        await conn.execute(
            pg_insert(HostCVE)
            .values(link_rows(list(host_ids), list(cve_ids), args.links, rng))
            .on_conflict_do_nothing()
        )

    async with session_factory() as session:
        got_hosts = len(
            (await session.execute(select(Host.id).where(Host.site == SITE)))
            .scalars()
            .all()
        )
        got_cves = len(
            (await session.execute(select(CVE.id).where(CVE.source == "seed")))
            .scalars()
            .all()
        )
        got_links = len(
            (
                await session.execute(
                    select(HostCVE.host_id)
                    .join(Host, HostCVE.host_id == Host.id)
                    .where(Host.site == SITE)
                )
            )
            .scalars()
            .all()
        )

    await engine.dispose()
    print(f"hosts={got_hosts} cves={got_cves} host_cves={got_links}")
    ok = got_hosts >= args.hosts and got_cves >= args.cves and got_links > 0
    if not ok:
        print(
            f"FAILED: wanted hosts>={args.hosts} cves>={args.cves} host_cves>0",
            file=sys.stderr,
        )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosts", type=int, default=300)
    parser.add_argument("--cves", type=int, default=2000)
    parser.add_argument("--links", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20261026)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
