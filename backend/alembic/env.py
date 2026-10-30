"""Alembic environment for Patch-SecOps Solution (plan.md S0-4).

Online only: the application runs migrations through ``python -m alembic``
with ``DATABASE_URL`` set (see schema_migrations.run_alembic). Target
metadata is exposed so ``alembic revision --autogenerate`` can diff a new
model change against a live database at release time.
"""

import os
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Importing the models registers every table on Base.metadata.
from database import Base  # noqa: E402
from models import db_models  # noqa: F402,F401

config = context.config
target_metadata = Base.metadata

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "No database URL: set DATABASE_URL (or sqlalchemy.url in alembic.ini)."
        )
    return url


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


run_migrations_online()
