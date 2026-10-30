"""Bootstrap the transactional-email channel from the environment at first run.

Installer-driven, same contract as bootstrap_users: fill PM_SMTP_* in .env at
setup time and the channel exists before the first login, so password-reset
OTPs (api/auth_api.py forgot_password) can be delivered without a post-install
UI step. With no PM_SMTP_HOST this no-ops and the channel stays a UI concern.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import func, select

from api.cicd_secrets import encrypt_json_field
from database import async_session
from models.db_models import NotificationChannel

logger = logging.getLogger("patchmaster.bootstrap_smtp")


def _smtp_config() -> dict[str, Any]:
    host = (os.getenv("PM_SMTP_HOST") or "").strip()
    if not host:
        return {}
    username = (os.getenv("PM_SMTP_USERNAME") or "").strip()
    recipient = (os.getenv("PM_SMTP_TO") or username).strip()
    return {
        "smtp_host": host,
        "smtp_port": int(os.getenv("PM_SMTP_PORT", "587")),
        # STARTTLS on 587 is what api.notifications._send_notification does with
        # use_tls; 465 needs SMTP_SSL, which that path does not implement.
        "use_tls": os.getenv("PM_SMTP_USE_TLS", "1").strip().lower()
        not in {"0", "false", "no", "off"},
        "username": username,
        "password": os.getenv("PM_SMTP_PASSWORD") or "",
        "to": recipient,
        "from_addr": (os.getenv("PM_SMTP_FROM") or username).strip(),
    }


async def ensure_bootstrap_smtp_channel() -> dict[str, Any]:
    """Create the email channel once, when PM_SMTP_HOST is set and no email
    channel exists yet (operator-configured channels are never clobbered)."""
    cfg = _smtp_config()
    if not cfg.get("smtp_host"):
        return {"created": False, "reason": "missing_smtp_config"}
    if not cfg.get("to"):
        return {"created": False, "reason": "missing_smtp_recipient"}

    async with async_session() as session:
        existing = (
            await session.scalar(
                select(func.count(NotificationChannel.id)).where(
                    NotificationChannel.channel_type == "email"
                )
            )
            or 0
        )
        if existing:
            return {"created": False, "reason": "email_channel_exists"}

        session.add(
            NotificationChannel(
                name="Transactional email (OTP)",
                channel_type="email",
                config=encrypt_json_field(cfg),
                events=[],  # OTP delivery only; event alerts are opt-in in the UI
                is_enabled=True,
            )
        )
        await session.commit()
        logger.warning(
            "Bootstrapped SMTP email channel from PM_SMTP_* (OTP delivery enabled)"
        )
        return {"created": True, "reason": "created"}
