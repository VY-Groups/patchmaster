"""Database engine & session factory — PostgreSQL via SQLAlchemy async."""

import os
import sys
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import event

# Global state
_DATABASE_URL: Optional[str] = None
_engine = None
_async_session = None
_engine_is_mock = False


def reset_engine():
    """Reset the engine state - useful for testing."""
    global _engine, _async_session, _DATABASE_URL, _engine_is_mock
    if _engine is not None and _engine_is_mock:
        # Keep mock, just reset
        pass
    else:
        _engine = None
        _async_session = None
        _engine_is_mock = False


def get_database_url() -> str:
    """Get DATABASE_URL from environment."""
    global _DATABASE_URL
    if _DATABASE_URL is None:
        _DATABASE_URL = os.environ.get("DATABASE_URL", "")
    return _DATABASE_URL


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""

    pass


def get_engine():
    """Lazily create and return the database engine."""
    global _engine, _async_session, async_session, _engine_is_mock

    if _engine is None:
        url = get_database_url()
        if not url:
            from unittest.mock import MagicMock

            _engine = MagicMock()
            _engine.begin = MagicMock()
            _engine.dispose = MagicMock()
            _engine.sync_engine = MagicMock()
            _engine_is_mock = True
            _async_session = MagicMock()
            async_session = _async_session
            return _engine

        _engine = create_async_engine(
            url,
            echo=False,
            pool_size=100,
            max_overflow=50,
            pool_timeout=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            poolclass=AsyncAdaptedQueuePool,
            connect_args={"command_timeout": 30},
            isolation_level="READ COMMITTED",
        )

        @event.listens_for(_engine.sync_engine, "connect")
        def set_statement_timeout(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET statement_timeout = '30s'")
            cursor.close()

        _async_session = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        async_session = _async_session
        _engine_is_mock = False

    return _engine


def _get_engine():
    return get_engine()


def _get_async_session():
    get_engine()
    return _async_session


def __getattr__(name):
    if name == "engine":
        return get_engine()
    if name == "async_session":
        get_engine()
        return _async_session
    if name == "Base":
        return Base
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    session_maker = _get_async_session()
    if session_maker is None:
        raise RuntimeError(
            "Database not configured. Set DATABASE_URL environment variable."
        )
    async with session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            # Commit only if no exception occurred during the request.
            # If the transaction is already invalid (e.g. a failed query was
            # swallowed by an endpoint), roll back instead of raising
            # PendingRollbackError. Endpoints that perform writes are expected
            # to commit explicitly; this is a safety net for legacy callers.
            try:
                await session.commit()
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise


async def init_db():
    """Bring the database to the current schema (plan.md S0-4).

    One migration tool replaces ad hoc create_all plus the manually applied
    dated SQL scripts: alembic runs the baseline chain (schema_migrations),
    then additive_reconcile closes any gap between the models and an older
    database by adding what is missing - never dropping.
    """
    db_engine = get_engine()
    if db_engine is None:
        raise RuntimeError(
            "Database not configured. Set DATABASE_URL environment variable."
        )

    from schema_migrations import migrate_engine_to_head

    added = await migrate_engine_to_head(db_engine)

    created = sum(len(objects) for objects in added.values())
    detail = f" (+{created} objects added)" if created else ""
    print(f"Database schema migrated to head{detail}")
