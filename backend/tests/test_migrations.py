"""S0-4 migration framework evidence (plan.md 15.1.4: FAIL first, then PASS).

plan.md S0-4 requires one migration tool with up/down migrations, the dated
``backend/migrations/*.sql`` scripts converted into its baseline chain, and a
migration test proving that a fresh install and an upgrade from the previous
release's provisioning mechanism end at the same schema.

Postgres-backed tests need a database URL (``PM_TEST_MIGRATION_DB_URL``, or the
``DATABASE_URL`` stashed by conftest) and are skipped otherwise - same contract
as the rest of the DB-less suite, which mocks the engine.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

import conftest

sys.path.insert(0, str(Path(__file__).parent.parent))

from schema_migrations import BACKEND_DIR, split_sql_statements  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (os.environ.get("PM_TEST_MIGRATION_DB_URL") or conftest.REAL_DATABASE_URL),
    reason="requires a live Postgres (PM_TEST_MIGRATION_DB_URL or DATABASE_URL)",
)

DB_URL = (
    os.environ.get("PM_TEST_MIGRATION_DB_URL") or conftest.REAL_DATABASE_URL or ""
)

FRESH_DB = "pm_migrate_fresh"
UPGRADE_DB = "pm_migrate_upgrade"
DRIFT_DB = "pm_migrate_drift"


# ── helpers ────────────────────────────────────────────────────────────────


def _url_for(dbname: str) -> str:
    """Same server, different database name."""
    from sqlalchemy import make_url

    return make_url(DB_URL).set(database=dbname).render_as_string(hide_password=False)


def _asyncpg_dsn(dbname: str) -> str:
    """asyncpg speaks postgresql:// - SQLAlchemy speaks postgresql+asyncpg://."""
    return _url_for(dbname).replace("+asyncpg", "")


async def _reset_db(dbname: str) -> None:
    """DROP/CREATE cannot run inside a transaction, so use raw asyncpg."""
    import asyncpg

    admin = await asyncpg.connect(_asyncpg_dsn("postgres"))
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        await admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await admin.close()


def _alembic(dbname: str, *args: str) -> str:
    """Run the alembic CLI against a scratch database (same path startup uses)."""
    env = dict(os.environ, DATABASE_URL=_url_for(dbname))
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(BACKEND_DIR / "alembic.ini"), *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"alembic {' '.join(args)} failed ({proc.returncode})\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout


async def _provision_previous_release(dbname: str) -> None:
    """What the previous release did: ad hoc create_all + manually applied
    dated SQL scripts (docs/internal/PRODUCTION_HARDENING_RUNBOOK.md runs them
    with ``psql -f``). Raw asyncpg executes a whole script in one call, which
    is what psql does, so this path does not depend on our SQL splitter."""
    import asyncpg
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import database  # noqa: F401
    from models import db_models  # noqa: F401

    engine = create_async_engine(_url_for(dbname))
    async with engine.begin() as conn:
        await conn.run_sync(database.Base.metadata.create_all, checkfirst=True)
    await engine.dispose()

    dsn = _asyncpg_dsn(dbname)
    for script in sorted((BACKEND_DIR / "migrations").glob("*.sql")):
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(script.read_text(encoding="utf-8"))
        finally:
            await conn.close()


async def _schema_signature(dbname: str) -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_url_for(dbname))
    out: dict = {}
    async with engine.connect() as conn:
        out["columns"] = [
            tuple(r)
            for r in (
                await conn.execute(
                    text(
                        "SELECT table_name, column_name, data_type, is_nullable "
                        "FROM information_schema.columns WHERE table_schema='public' "
                        "ORDER BY 1, 2"
                    )
                )
            ).all()
        ]
        out["indexes"] = [
            tuple(r)
            for r in (
                await conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE schemaname='public' ORDER BY 1"
                    )
                )
            ).all()
        ]
        out["constraints"] = [
            tuple(r)
            for r in (
                await conn.execute(
                    text(
                        "SELECT conrelid::regclass::text, conname, "
                        "pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE connamespace='public'::regnamespace ORDER BY 1, 2"
                    )
                )
            ).all()
        ]
        out["tables"] = sorted(
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname='public' ORDER BY 1"
                    )
                )
            ).all()
        )
        has_version = (
            await conn.execute(
                text("SELECT to_regclass('alembic_version') IS NOT NULL")
            )
        ).scalar()
        out["alembic_version"] = (
            sorted(
                r[0]
                for r in (
                    await conn.execute(text("SELECT version_num FROM alembic_version"))
                ).all()
            )
            if has_version
            else []
        )
    await engine.dispose()
    return out


async def _migrate(dbname: str) -> dict:
    """Run the exact startup path (alembic head + additive reconcile)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from schema_migrations import migrate_engine_to_head

    engine = create_async_engine(_url_for(dbname))
    try:
        return await migrate_engine_to_head(engine)
    finally:
        await engine.dispose()


def _head_revision() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(BACKEND_DIR / "alembic.ini"),
         "heads"],
        cwd=str(BACKEND_DIR),
        env=dict(os.environ, DATABASE_URL=_url_for("postgres")),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().split()[0]


# ── 1. SQL splitter unit test (no database needed) ─────────────────────────


def test_split_sql_statements_handles_comments_and_quoted_semicolons():
    sql = """
    -- a comment; with a semicolon
    ALTER TABLE hosts DROP CONSTRAINT IF EXISTS uq;
    COMMENT ON CONSTRAINT uq ON hosts IS 'keeps ip; hostname unique';
    """
    stmts = split_sql_statements(sql)
    assert len(stmts) == 2, stmts
    assert stmts[0].startswith("ALTER TABLE hosts")
    assert "ip; hostname" in stmts[1]


# ── 2. fresh install ───────────────────────────────────────────────────────


def test_fresh_install_reaches_head():
    asyncio.run(_reset_db(FRESH_DB))
    asyncio.run(_migrate(FRESH_DB))

    sig = asyncio.run(_schema_signature(FRESH_DB))
    assert sig["alembic_version"] == [_head_revision()]
    assert "hosts" in sig["tables"], "models must be materialised on a fresh install"
    assert "notification_channels" in sig["tables"]


# ── 3. upgrade from the previous release's provisioning ────────────────────


def test_upgrade_from_previous_release_matches_fresh_install():
    asyncio.run(_reset_db(UPGRADE_DB))
    asyncio.run(_provision_previous_release(UPGRADE_DB))
    before = asyncio.run(_schema_signature(UPGRADE_DB))
    assert before["alembic_version"] == [], "old installs have no alembic_version"

    asyncio.run(_migrate(UPGRADE_DB))

    fresh = asyncio.run(_schema_signature(FRESH_DB))
    upgraded = asyncio.run(_schema_signature(UPGRADE_DB))
    assert upgraded["alembic_version"] == fresh["alembic_version"]
    for key in ("tables", "columns", "indexes", "constraints"):
        missing = set(map(str, fresh[key])) - set(map(str, upgraded[key]))
        extra = set(map(str, upgraded[key])) - set(map(str, fresh[key]))
        assert not missing and not extra, (
            f"{key} differ after upgrade\nmissing: {sorted(missing)}\nextra: {sorted(extra)}"
        )


# ── 4. schema drift added since the last release ───────────────────────────


def test_upgrade_restores_columns_and_indexes_added_since_last_release():
    """A previous-release database can lack tables/columns/indexes the current
    models declare; startup must converge it on the model schema (additive
    only - nothing is dropped)."""

    asyncio.run(_reset_db(DRIFT_DB))
    asyncio.run(_provision_previous_release(DRIFT_DB))

    # Simulate "models gained these since that release".
    asyncio.run(_apply_drift(DRIFT_DB))

    asyncio.run(_migrate(DRIFT_DB))

    fresh = asyncio.run(_schema_signature(FRESH_DB))
    drifted = asyncio.run(_schema_signature(DRIFT_DB))
    fresh_cols = {(c[0], c[1]) for c in fresh["columns"]}
    drifted_cols = {(c[0], c[1]) for c in drifted["columns"]}
    missing = fresh_cols - drifted_cols
    assert not missing, f"columns still missing after upgrade: {sorted(missing)}"
    fresh_idx = {i[0] for i in fresh["indexes"]}
    drifted_idx = {i[0] for i in drifted["indexes"]}
    assert not (fresh_idx - drifted_idx), (
        f"indexes still missing after upgrade: {sorted(fresh_idx - drifted_idx)}"
    )


async def _apply_drift(dbname: str) -> None:
    """Drop a model-declared column and index to fake an older schema."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_url_for(dbname))
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE hosts DROP COLUMN IF EXISTS kernel"))
        await conn.execute(text("DROP INDEX IF EXISTS ix_hosts_last_heartbeat"))
        await conn.execute(text("DROP TABLE IF EXISTS notification_channels"))
    await engine.dispose()


# ── 5. downgrade ───────────────────────────────────────────────────────────


def test_downgrade_to_base_removes_schema():
    asyncio.run(_reset_db(FRESH_DB))
    asyncio.run(_migrate(FRESH_DB))
    _alembic(FRESH_DB, "downgrade", "base")

    sig = asyncio.run(_schema_signature(FRESH_DB))
    assert "hosts" not in sig["tables"], "downgrade must drop the model schema"
