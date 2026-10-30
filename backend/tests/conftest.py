"""Pytest fixtures with mocks for testing without real database."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# CRITICAL: Import database and reset any existing state BEFORE other imports
# This must be done at the very top before any backend.* imports

# Add backend to path for imports
backend_path = str(Path(__file__).parent.parent)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Reset database module state
import database

if hasattr(database, "reset_engine"):
    database.reset_engine()

# Ensure DATABASE_URL is not set to trigger mock mode.
# REAL_DATABASE_URL keeps the original for tests that opt into a live database
# (S0-4 migration tests); everything else stays in mock mode.
REAL_DATABASE_URL = os.environ.pop("DATABASE_URL", None)

# S0-1: auth fails closed without a JWT_SECRET; tests supply their own secret.
os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

# Create mock engine that doesn't try to connect
mock_engine = MagicMock()
mock_engine.begin = MagicMock(
    return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock())
)
mock_engine.dispose = MagicMock()
mock_engine.sync_engine = MagicMock()
mock_engine._is_mock = True

# Create mock async session maker
mock_async_session = MagicMock()
mock_session = AsyncMock()
mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
mock_async_session.return_value.__aexit__ = AsyncMock(return_value=None)


@pytest.fixture(autouse=True)
def mock_database(monkeypatch):
    """Auto-mock database for all tests."""
    # Reset database state first
    database._engine = None
    database._async_session = None

    # Ensure get_engine returns our mock
    with patch.object(database, "get_engine", return_value=mock_engine):
        with patch.object(
            database, "_get_async_session", return_value=mock_async_session
        ):
            with patch.object(database, "get_database_url", return_value=""):
                yield mock_session


@pytest.fixture(autouse=True)
def reset_rate_limits(monkeypatch):
    """slowapi keeps its counters in process memory; without this a test that
    spends a route's budget would 429 the tests that run after it."""
    from api.auth_api import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def mock_db_session():
    """Provide a mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_db_engine():
    """Provide a mock database engine."""
    engine = MagicMock()
    engine.begin = AsyncMock()
    engine.dispose = MagicMock()
    return engine


@pytest.fixture
def mock_async_session_maker():
    """Provide a mock async session maker."""
    session = AsyncMock()
    session_maker = MagicMock()
    session_maker.return_value.__aenter__ = AsyncMock(return_value=session)
    session_maker.return_value.__aexit__ = AsyncMock(return_value=None)
    return session_maker


@pytest.fixture
def mock_httpx_client():
    """Provide a mock httpx client."""
    client = AsyncMock(spec=["get", "post", "put", "delete", "close"])
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_api_response():
    """Provide a mock API response."""

    def _mock_response(status=200, json_data=None, text=""):
        response = MagicMock()
        response.status_code = status
        response.json = MagicMock(return_value=json_data or {})
        response.text = text
        response.raise_for_status = MagicMock()
        if status >= 400:
            response.raise_for_status.side_effect = Exception(f"HTTP {status}")
        return response

    return _mock_response


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def sample_license_data():
    """Provide sample license data for tests."""
    return {
        "id": "test-license-001",
        "customer": "Test Customer",
        "product": "PatchMaster Enterprise",
        "edition": "Enterprise",
        " seats": 100,
        "expiry": "2027-12-31T23:59:59Z",
        "features": ["agent", "monitoring", "reports", "plugins"],
        "status": "active",
    }


@pytest.fixture
def sample_host_data():
    """Provide sample host data for tests."""
    return {
        "id": "test-host-001",
        "hostname": "test-server.example.com",
        "ip_address": "192.168.1.100",
        "os": "Ubuntu 22.04",
        "status": "online",
        "last_seen": "2026-04-14T10:00:00Z",
    }


@pytest.fixture
def sample_package_data():
    """Provide sample package data for tests."""
    return {
        "name": "openssl",
        "version": "3.0.2-1ubuntu2",
        "installed_version": "3.0.2-0ubuntu1",
        "repository": "ubuntu-security",
        "priority": "required",
        "security": True,
    }
