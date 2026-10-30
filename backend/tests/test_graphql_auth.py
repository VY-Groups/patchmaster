"""S0-1 change set D: the GraphQL endpoint must require authentication.

Defect (line-verified 2026-10-25): api/graphql.py exposed hosts (IPs, tenant ids),
patch jobs, CVEs and a create_host WRITE mutation through /graphql with no auth
whatsoever (no get_current_user/Depends/require_role anywhere in the file), while
main.py:359 even lists it as "read-only by default". GraphiQL was enabled too.

No frontend or in-repo caller uses /graphql (grep verified), so requiring a Bearer
access token breaks nothing internal.

Tests are written first and must FAIL against the pre-fix code (plan.md 15.1.4).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from auth import create_access_token, get_current_user  # noqa: E402
from api.graphql import create_graphql_router  # noqa: E402
from database import get_db  # noqa: E402
from models.db_models import User, UserRole  # noqa: E402

QUERY = {"query": "{ __typename }"}


def _app():
    app = FastAPI()
    app.include_router(create_graphql_router())
    return app


def _active_user_db():
    user = User(
        username="admin",
        email="admin@example.com",
        hashed_password="x",
        is_active=True,
        role=UserRole.admin,
    )

    class _Res:
        def scalar_one_or_none(self):
            return user

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Res())
    return db


def test_graphql_rejects_missing_token():
    client = TestClient(_app())
    resp = client.post("/graphql", json=QUERY)
    # Pre-fix: 200 with full schema data.
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}"


def test_graphql_rejects_garbage_token():
    client = TestClient(_app())
    resp = client.post(
        "/graphql", json=QUERY, headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401


def test_graphql_accepts_valid_access_token():
    app = _app()
    app.dependency_overrides[get_db] = lambda: _active_user_db()
    client = TestClient(app)
    token = create_access_token({"sub": "admin"})
    resp = client.post(
        "/graphql", json=QUERY, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["__typename"] == "Query"
