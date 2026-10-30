"""The single migration tool (plan.md S0-4).

Alembic replaces ad hoc ``create_all`` plus the dated, manually applied
``backend/migrations/*.sql`` scripts. The chain is:

    20261025_0001_baseline      create_all from the ORM models
    20261025_0002_legacy_sql    the dated scripts, in filename order

``database.init_db()`` runs ``upgrade head`` on every startup, so a database
provisioned by an older release moves onto the chain, and then calls
``additive_reconcile()``, which adds whatever the models declare and the
database is missing: new tables, columns and indexes. Reconcile only ever
adds - dropping, renaming or tightening stays in an explicit revision with a
downgrade, where a backfill can be written.

New model-only changes need no revision; changes that must be reversible or
that transform data get one via ``alembic revision --autogenerate`` (env.py
exposes ``Base.metadata`` for that).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("patchmaster.migrations")

BACKEND_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def split_sql_statements(sql: str) -> list[str]:
    """Split a psql-style script into single statements.

    Handles ``--`` line comments and single-quoted strings (with ``''``
    escapes), so a semicolon inside a comment or a COMMENT ON string does not
    cut a statement in half.
    shortcut: no dollar-quoted bodies - add a ``$tag$`` scanner if a migration
    ever needs a plpgsql ``DO`` block.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_string = False
    in_comment = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if in_comment:
            if ch == "\n":
                in_comment = False
                buf.append(ch)
            i += 1
            continue
        if in_string:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "-" and sql.startswith("--", i):
            in_comment = True
            i += 2
            continue
        if ch == "'":
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def run_alembic(action: str, revision: str = "head", database_url: str | None = None) -> str:
    """Run the alembic CLI in a child process and return its stdout.

    Alembic's Python API is synchronous while its environment drives the async
    engine (asyncpg) from its own event loop, so the supported way to run it
    from the already-running application - or from a test - is the CLI.
    """
    env = dict(os.environ)
    if database_url:
        env["DATABASE_URL"] = database_url
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), action, revision],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"alembic {action} {revision} failed ({proc.returncode})\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    last = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "done"
    logger.info("alembic %s %s -> %s", action, revision, last)
    return proc.stdout


async def migrate_engine_to_head(engine) -> dict[str, list[str]]:
    """The complete startup migration: alembic ``upgrade head``, then reconcile.

    ``database.init_db()`` calls this, and the migration tests call it against
    scratch databases, so what is tested is exactly what ships.
    """
    run_alembic(
        "upgrade",
        "head",
        database_url=engine.url.render_as_string(hide_password=False),
    )
    async with engine.begin() as conn:
        return await conn.run_sync(additive_reconcile)


def additive_reconcile(sync_conn) -> dict[str, list[str]]:
    """Add model-declared tables, columns and indexes the database lacks.

    Runs on every startup after ``upgrade head`` so an older release's
    database converges on the schema the models describe. Additive only:
    nothing is dropped, renamed or made NOT NULL (an existing table may hold
    rows) - those belong in an explicit revision.
    """
    from sqlalchemy import inspect, text

    from database import Base
    from models import db_models  # noqa: F401  (registers every table on Base)

    dialect = sync_conn.dialect
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    added: dict[str, list[str]] = {"tables": [], "columns": [], "indexes": []}

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            table.create(sync_conn, checkfirst=True)
            inspector.clear_cache()
            existing_tables.add(table.name)
            added["tables"].append(table.name)
            continue

        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
            stmt += column.type.compile(dialect=dialect)
            if column.server_default is not None:
                stmt += f" DEFAULT {column.server_default.compile(dialect=dialect)}"
            sync_conn.execute(text(stmt))
            added["columns"].append(f"{table.name}.{column.name}")

        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in existing_indexes:
                continue
            index.create(sync_conn, checkfirst=True)
            added["indexes"].append(index.name)

    if any(added.values()):
        logger.warning("Schema reconcile added missing objects: %s", added)
    return added
