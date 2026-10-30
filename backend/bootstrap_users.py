"""Bootstrap initial product users from environment variables."""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import select, func

from auth import hash_password
from database import async_session
from models.db_models import User, UserRole

logger = logging.getLogger("patchmaster.bootstrap")


def _user_config(
    prefix: str, *, default_email: str, default_full_name: str, role: UserRole
) -> dict[str, Any]:
    username = (os.getenv(f"{prefix}_USER") or "").strip()
    password = (os.getenv(f"{prefix}_PASSWORD") or "").strip()
    return {
        "username": username,
        "password": password,
        "email": (os.getenv(f"{prefix}_EMAIL") or default_email).strip(),
        "full_name": (os.getenv(f"{prefix}_FULL_NAME") or default_full_name).strip(),
        "role": role,
    }


async def ensure_bootstrap_users() -> dict[str, Any]:
    """Create the initial admin + smoke users when the DB is empty.

    This is intentionally installer-driven: if the env vars are absent, the
    function simply no-ops and preserves the existing first-run registration
    flow.
    """
    admin = _user_config(
        "PM_ADMIN",
        default_email="admin@patchmaster.local",
        default_full_name="Patch-SecOps Solution Administrator",
        role=UserRole.admin,
    )
    smoke = _user_config(
        "PM_SMOKE",
        default_email="qa-smoke@patchmaster.local",
        default_full_name="Patch-SecOps Solution QA Smoke",
        role=UserRole.operator,
    )

    if not admin["username"] or not admin["password"]:
        return {"created": [], "reason": "missing_admin_credentials"}

    async with async_session() as session:
        user_count = await session.scalar(select(func.count(User.id))) or 0
        if user_count > 0:
            return {"created": [], "reason": "users_exist"}

        created: list[str] = []

        admin_user = User(
            username=admin["username"],
            email=admin["email"],
            hashed_password=hash_password(admin["password"]),
            full_name=admin["full_name"],
            role=admin["role"],
            is_active=True,
        )
        session.add(admin_user)
        created.append(admin["username"])

        if (
            smoke["username"]
            and smoke["password"]
            and smoke["username"] != admin["username"]
        ):
            smoke_user = User(
                username=smoke["username"],
                email=smoke["email"],
                hashed_password=hash_password(smoke["password"]),
                full_name=smoke["full_name"],
                role=smoke["role"],
                is_active=True,
            )
            session.add(smoke_user)
            created.append(smoke["username"])

        await session.commit()
        logger.warning(
            "Bootstrapped initial users from environment: %s", ", ".join(created)
        )
        return {"created": created, "reason": "created"}
