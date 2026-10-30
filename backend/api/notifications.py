"""Notifications API - manage alert channels and send notifications."""

import asyncio
from collections import defaultdict
import logging
from typing import Optional

import httpx
import jwt
from jwt import InvalidTokenError
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_db
from auth import ALGORITHM, SECRET_KEY, get_current_user, require_role
from api.cicd_secrets import decrypt_json_field, encrypt_json_field
from api.webhook_retry import deliver_with_retry as deliver_webhook_with_retry
from models.db_models import NotificationChannel, User, UserNotification, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notifications", tags=["notifications"])

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 5]


async def _deliver_webhook_with_retry(url: str, payload: dict) -> bool:
    """Deliver webhook with exponential backoff retry."""
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code < 400:
                    return True
        except Exception as e:
            logger.warning(f"Webhook attempt {attempt + 1} failed: {e}")

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAYS[attempt])

    return False


class _NotificationHub:
    def __init__(self):
        self._connections = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket):
        async with self._lock:
            sockets = self._connections.get(user_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(user_id, None)

    async def active_user_ids(self) -> list[int]:
        async with self._lock:
            return list(self._connections.keys())

    async def send_snapshot(self, user_id: int, payload: dict):
        async with self._lock:
            sockets = list(self._connections.get(user_id, set()))
        stale = []
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(user_id, websocket)


notification_hub = _NotificationHub()


def _redacted_channel_config(channel_type: str, config: dict) -> dict:
    cfg = config or {}
    if channel_type == "telegram":
        return {"chat_id": cfg.get("chat_id", "")}
    if channel_type == "email":
        return {
            "to": cfg.get("to", ""),
            "smtp_host": cfg.get("smtp_host", ""),
            "smtp_port": cfg.get("smtp_port", 587),
            "username": cfg.get("username", ""),
            "use_tls": cfg.get("use_tls", True),
        }
    return {}


def _has_secret_channel_config(channel_type: str, config: dict) -> bool:
    cfg = config or {}
    if channel_type == "webhook":
        return bool(str(cfg.get("url", "")).strip())
    if channel_type == "slack":
        return bool(str(cfg.get("webhook_url", "")).strip())
    if channel_type == "telegram":
        return bool(str(cfg.get("bot_token", "")).strip())
    if channel_type == "email":
        return bool(str(cfg.get("password", "")).strip())
    return bool(cfg)


def _merge_channel_config(channel_type: str, existing: dict, incoming: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        merged[key] = value
    return merged


class UserNotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    message: str
    link: Optional[str]
    is_read: bool
    created_at: str


class ChannelCreate(BaseModel):
    name: str
    channel_type: str
    config: dict
    events: list[str] = ["job_failed", "cve_critical"]
    is_enabled: bool = True


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    events: Optional[list[str]] = None
    is_enabled: Optional[bool] = None


def _serialize_notification(note: UserNotification) -> dict:
    return {
        "id": note.id,
        "type": note.type,
        "title": note.title,
        "message": note.message,
        "link": note.link,
        "is_read": note.is_read,
        "created_at": note.created_at.isoformat(),
    }


async def _notification_items_for_user(db: AsyncSession, user_id: int) -> list[dict]:
    stmt = (
        select(UserNotification)
        .where(
            (UserNotification.user_id == None) | (UserNotification.user_id == user_id)
        )
        .order_by(UserNotification.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    notes = result.scalars().all()
    return [_serialize_notification(note) for note in notes]


async def _notification_snapshot_payload(db: AsyncSession, user_id: int) -> dict:
    items = await _notification_items_for_user(db, user_id)
    return {
        "type": "snapshot",
        "items": items,
        "unread_count": sum(1 for item in items if not item["is_read"]),
    }


async def _broadcast_notification_updates(target_user_id: Optional[int] = None):
    user_ids = (
        [target_user_id]
        if target_user_id is not None
        else await notification_hub.active_user_ids()
    )
    if not user_ids:
        return
    async with async_session() as db:
        for user_id in user_ids:
            payload = await _notification_snapshot_payload(db, user_id)
            await notification_hub.send_snapshot(user_id, payload)


async def _resolve_websocket_user(websocket: WebSocket) -> Optional[User]:
    token = (
        websocket.query_params.get("token") or websocket.cookies.get("pm_token") or ""
    ).strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
        # F4: reset/refresh-purpose tokens must never open a websocket.
        if payload.get("type", "access") != "access":
            return None
    except InvalidTokenError:
        return None

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            return None
        return user


async def notify_system_event(
    event_type: str, title: str, message: str, link: str = None, user_id: int = None
):
    """Internal utility to create notifications."""
    try:
        async with async_session() as db:
            note = UserNotification(
                user_id=user_id,
                type=event_type,
                title=title,
                message=message,
                link=link,
            )
            db.add(note)
            await db.commit()
        await _broadcast_notification_updates(user_id)
    except Exception as e:
        logger.error("Failed to create notification: %s", e)


@router.get("/me", response_model=list[UserNotificationResponse])
async def my_notifications(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Get unread notifications for current user + system wide."""
    return await _notification_items_for_user(db, user.id)


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket):
    user = await _resolve_websocket_user(websocket)
    if not user:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await notification_hub.connect(user.id, websocket)
    try:
        async with async_session() as db:
            await websocket.send_json(await _notification_snapshot_payload(db, user.id))
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Notification websocket failed for user_id=%s", user.id)
    finally:
        await notification_hub.disconnect(user.id, websocket)
        try:
            await websocket.close()
        except Exception:
            pass


@router.post("/{note_id}/read")
async def mark_read(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    note = await db.get(UserNotification, note_id)
    if not note:
        raise HTTPException(404, "Notification not found")
    if note.user_id and note.user_id != user.id:
        raise HTTPException(403, "Not your notification")

    note.is_read = True
    await db.commit()
    await _broadcast_notification_updates(None if note.user_id is None else user.id)
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    stmt = select(UserNotification).where(
        (UserNotification.user_id == None) | (UserNotification.user_id == user.id),
        UserNotification.is_read == False,
    )
    result = await db.execute(stmt)
    notes = result.scalars().all()
    for note in notes:
        note.is_read = True
    await db.commit()
    await _broadcast_notification_updates(None)
    return {"status": "ok", "count": len(notes)}


@router.get("/channels")
async def list_channels(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await db.execute(
        select(NotificationChannel).order_by(NotificationChannel.name)
    )
    channels = result.scalars().all()
    return [
        {
            "id": channel.id,
            "name": channel.name,
            "channel_type": channel.channel_type,
            "config": _redacted_channel_config(
                channel.channel_type, decrypt_json_field(channel.config)
            ),
            "has_secret_config": _has_secret_channel_config(
                channel.channel_type, decrypt_json_field(channel.config)
            ),
            "events": channel.events,
            "is_enabled": channel.is_enabled,
            "created_at": channel.created_at.isoformat(),
        }
        for channel in channels
    ]


@router.post("/channels", status_code=201)
async def create_channel(
    data: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    valid_types = {"email", "slack", "webhook", "telegram"}
    if data.channel_type not in valid_types:
        raise HTTPException(400, f"channel_type must be one of {valid_types}")
    channel = NotificationChannel(
        name=data.name,
        channel_type=data.channel_type,
        config=encrypt_json_field(data.config),
        events=data.events,
        is_enabled=data.is_enabled,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return {"id": channel.id, "name": channel.name}


@router.put("/channels/{channel_id}")
async def update_channel(
    channel_id: int,
    data: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    for field, value in data.model_dump(exclude_none=True).items():
        if field == "config":
            existing_config = decrypt_json_field(channel.config)
            merged_config = _merge_channel_config(
                channel.channel_type, existing_config, value or {}
            )
            value = encrypt_json_field(merged_config)
        setattr(channel, field, value)
    await db.commit()
    return {"status": "updated"}


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    await db.delete(channel)
    await db.commit()


@router.post("/test/{channel_id}")
async def test_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    """Send a test notification through the channel."""
    channel = await db.get(NotificationChannel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    try:
        await _send_notification(
            channel, "Test Notification", "This is a test from Patch-SecOps Solution."
        )
        return {"status": "sent"}
    except Exception as e:
        raise HTTPException(500, f"Send failed: {str(e)}")


async def send_event_notification(
    db: AsyncSession, event: str, title: str, message: str
):
    """Send notification to all channels subscribed to this event."""
    result = await db.execute(
        select(NotificationChannel).where(NotificationChannel.is_enabled == True)
    )
    channels = result.scalars().all()
    for channel in channels:
        if event in (channel.events or []):
            try:
                await _send_notification(channel, title, message)
            except Exception:
                logger.exception("Failed to send notification via %s", channel.name)


async def _send_notification(channel: NotificationChannel, title: str, message: str):
    """Dispatch notification based on channel type."""
    import httpx

    config = decrypt_json_field(channel.config)

    if channel.channel_type == "webhook":
        url = config.get("url", "")
        if not url:
            raise ValueError("Webhook URL not configured")
        # Use retry wrapper with exponential backoff
        payload = {"title": title, "message": message}
        success, status_code, attempts = await deliver_webhook_with_retry(url, payload)
        if not success:
            raise ValueError(
                f"Webhook delivery failed after retries: {attempts[-1].get('error', 'Unknown')}"
            )

    elif channel.channel_type == "slack":
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            raise ValueError("Slack webhook URL not configured")
        # Use retry wrapper for Slack webhooks too
        payload = {"text": f"*{title}*\n{message}"}
        success, status_code, attempts = await deliver_webhook_with_retry(
            webhook_url, payload
        )
        if not success:
            raise ValueError(f"Slack webhook delivery failed after retries")

    elif channel.channel_type == "telegram":
        bot_token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot_token and chat_id required")
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": f"{title}\n{message}",
                    "parse_mode": "HTML",
                },
            )

    elif channel.channel_type == "email":
        import smtplib
        from email.mime.text import MIMEText

        cfg = config or {}
        to_addr = cfg.get("to")
        host = cfg.get("smtp_host")
        port = int(cfg.get("smtp_port", 587))
        username = cfg.get("username")
        password = cfg.get("password")
        use_tls = cfg.get("use_tls", True)
        if not (to_addr and host):
            raise ValueError("Email channel requires to, smtp_host")
        msg = MIMEText(message)
        msg["Subject"] = title
        msg["From"] = cfg.get("from_addr", username or "patchmaster@localhost")
        msg["To"] = to_addr
        if use_tls:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls()
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                if username and password:
                    smtp.login(username, password)
                smtp.send_message(msg)

    else:
        raise ValueError(f"Unknown channel type: {channel.channel_type}")
