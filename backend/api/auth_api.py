"""Auth API — login, register, user management (enterprise hardened)."""

import logging
import os
import re
import secrets
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Response,
    BackgroundTasks,
    Request,
)
from pydantic import BaseModel, validator, ConfigDict
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict
import jwt
from jwt import InvalidTokenError

from database import get_db
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_and_rotate_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
    get_current_user,
    require_role,
    SECRET_KEY,
    ALGORITHM,
)
from api.rbac import Permission, get_user_permissions, check_permission, has_permission
from api.cicd_secrets import decrypt_json_field
from models.db_models import User, UserRole, NotificationChannel, PasswordResetOTP
from license import get_licensed_features
import monitoring_manager

logger = logging.getLogger(__name__)

# ── Rate limiter (brute-force / credential stuffing protection) ──
limiter = Limiter(key_func=get_remote_address)
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
# /forgot budget per IP: generous for a human (a couple of resets), tiny for
# someone trying to push OTP traffic or harvest codes.
FORGOT_MAX_PER_MINUTE = int(os.getenv("FORGOT_MAX_PER_MINUTE", "10"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))
REFRESH_COOKIE = os.getenv("REFRESH_COOKIE_NAME", "pm_refresh")


def install_rate_limiting(app) -> None:
    """Link this module's limiter to an app - slowapi is inert without it.

    The @limiter.limit decorators only fire from slowapi's middleware, and the
    429 body is built by its exception handler. main.py and the rate-limit
    tests both call this helper, so the wiring under test is what ships.
    """
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

# ── Feature list & role defaults ──
ALL_FEATURES = [
    "dashboard",
    "compliance",
    "hosts",
    "groups",
    "patches",
    "snapshots",
    "compare",
    "offline",
    "schedules",
    "cve",
    "jobs",
    "audit",
    "notifications",
    "users",
    "license",
    "cicd",
    "git",
    "onboarding",
    "settings",
    "monitoring",
    "testing",
    "local-repo",
    "software",
    "policies",
    "reports",
    "backups",
    "backup_db",
    "backup_file",
    "backup_vm",
    "backup_live",
    "linux_patching",
    "windows_patching",
    "wsus",
    "cicd_view",
    "cicd_manage",
    "cicd_execute",
    "cicd_approve",
]

ROLE_DEFAULTS = {
    "admin": {f: True for f in ALL_FEATURES},
    "operator": {
        f: True for f in ALL_FEATURES if f not in ("audit", "users", "license", "git")
    },
    "viewer": {
        f: True
        for f in [
            "dashboard",
            "compliance",
            "hosts",
            "groups",
            "compare",
            "cve",
            "jobs",
            "onboarding",
            "settings",
        ]
    },
    "auditor": {
        f: True
        for f in [
            "dashboard",
            "compliance",
            "hosts",
            "groups",
            "compare",
            "cve",
            "jobs",
            "audit",
            "onboarding",
            "settings",
            "cicd",
            "cicd_view",
        ]
    },
}
# Fill missing keys as False
for role_perms in ROLE_DEFAULTS.values():
    for f in ALL_FEATURES:
        role_perms.setdefault(f, False)


# Common passwords blocklist (top-20 to avoid storing a huge file)
_COMMON_PASSWORDS = {
    "password",
    "password1",
    "Password1",
    "Password1!",
    "123456",
    "12345678",
    "qwerty",
    "letmein",
    "welcome",
    "admin",
    "admin123",
    "Admin123!",
    "iloveyou",
    "monkey",
    "dragon",
    "master",
    "sunshine",
    "princess",
    "football",
    "charlie",
}


def validate_password_strength(password: str):
    """
    Enterprise password policy:
    - 12–128 characters
    - At least one uppercase, one lowercase, one digit, one special character
    - Not in common passwords list
    """
    if len(password) < 12:
        raise HTTPException(400, "Password must be at least 12 characters long.")
    if len(password) > 128:
        raise HTTPException(400, "Password must not exceed 128 characters.")
    if not any(c.isupper() for c in password):
        raise HTTPException(400, "Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise HTTPException(400, "Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise HTTPException(400, "Password must contain at least one digit.")
    if not any(not c.isalnum() for c in password):
        raise HTTPException(
            400, "Password must contain at least one special character (!@#$%^&* etc)."
        )
    if password.lower() in _COMMON_PASSWORDS or password in _COMMON_PASSWORDS:
        raise HTTPException(
            400, "Password is too common. Please choose a more unique password."
        )


def get_effective_permissions(role: str, custom: dict = None) -> dict:
    """Merge role defaults with per-user custom overrides, then intersect with license tier."""
    base = dict(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["viewer"]))
    # Admin role: custom overrides can only grant, never revoke
    if custom:
        for k, v in custom.items():
            if k in base:
                if role == "admin":
                    # Admin always keeps their default True permissions; overrides can only add
                    base[k] = base[k] or bool(v)
                else:
                    base[k] = bool(v)
    # Intersect with license-allowed features (license tier enforcement)
    licensed = get_licensed_features()
    for f in base:
        if f not in licensed:
            base[f] = False
    return base


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _check_lockout(user: User):
    """Raise 429 if the account is locked due to too many failed attempts."""
    if user.locked_until:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds() / 60) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account locked due to too many failed login attempts. Try again in {remaining} minute(s).",
                headers={"Retry-After": str(remaining * 60)},
            )
        else:
            # Lockout expired — reset
            user.login_attempts = 0
            user.locked_until = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: str = ""


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    custom_permissions: Optional[dict] = None
    effective_permissions: Optional[dict] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name or "",
            role=user.role.value if hasattr(user.role, "value") else user.role,
            is_active=user.is_active,
            custom_permissions=user.custom_permissions,
            effective_permissions=get_effective_permissions(
                user.role.value if hasattr(user.role, "value") else user.role,
                user.custom_permissions,
            ),
            created_at=user.created_at,
        )


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: str = ""
    role: str = "viewer"


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class ForgotPasswordRequest(BaseModel):
    username_or_email: str


class ResetPasswordRequest(BaseModel):
    username_or_email: str
    otp: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
@limiter.limit(f"{MAX_LOGIN_ATTEMPTS}/minute")
async def login(
    request: Request,
    req: LoginRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    if not user:
        # Timing-safe: always do the same amount of work (valid hash — a
        # malformed one made passlib raise and turned every unknown-user
        # login into a 500).
        verify_password(
            req.password,
            "$pbkdf2-sha256$29000$YWyNce7dm7P2Xst5D8FYiw$RwWENLpD8yEl/G6iNKgPJhPMO4wapamgo7.1ID.p/VU",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Check account lockout
    _check_lockout(user)

    if not verify_password(req.password, user.hashed_password):
        # Increment failed attempt counter
        user.login_attempts = (user.login_attempts or 0) + 1
        if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc).replace(
                tzinfo=None
            ) + timedelta(minutes=LOCKOUT_MINUTES)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Account is disabled"
        )

    # Successful login — reset lockout counters
    user.login_attempts = 0
    user.locked_until = None

    perms = get_effective_permissions(user.role.value, user.custom_permissions)
    access_token = create_access_token({"sub": user.username, "role": user.role.value})

    # Issue refresh token
    client_ip = request.client.host if request.client else ""
    ua = request.headers.get("User-Agent", "")[:512]
    raw_refresh = await create_refresh_token(
        user.id, db, ip_address=client_ip, user_agent=ua
    )

    cookie_domain = os.getenv("AUTH_COOKIE_DOMAIN") or None
    cookie_secure = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
    cookie_samesite = os.getenv("AUTH_COOKIE_SAMESITE", "lax").lower()
    access_max_age = int(os.getenv("TOKEN_EXPIRE_MINUTES", "15")) * 60

    # Access token cookie (shorter-lived)
    cookie_name = os.getenv("AUTH_COOKIE_NAME", "pm_token")
    response.set_cookie(
        key=cookie_name,
        value=access_token,
        max_age=access_max_age,
        expires=access_max_age,
        path="/",
        domain=cookie_domain,
        secure=cookie_secure,
        httponly=True,
        samesite=cookie_samesite
        if cookie_samesite in ("lax", "strict", "none")
        else "lax",
    )
    # Refresh token cookie (longer-lived, httpOnly)
    refresh_max_age = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")) * 86400
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=raw_refresh,
        max_age=refresh_max_age,
        expires=refresh_max_age,
        path="/api/auth/refresh",
        domain=cookie_domain,
        secure=cookie_secure,
        httponly=True,
        samesite="strict",
    )

    await db.commit()

    # Monitor stack (fire-and-forget)
    features = get_licensed_features()
    if "monitoring" in features:
        background_tasks.add_task(monitoring_manager.enforce_license, features)
        background_tasks.add_task(monitoring_manager.reload_dashboards)

    return LoginResponse(
        access_token=access_token,
        user={
            "id": user.id,
            "username": user.username,
            "role": user.role.value,
            "full_name": user.full_name,
            "permissions": perms,
        },
    )


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new access token + rotated refresh token."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE) or (
        request.headers.get("X-Refresh-Token", "")
    )
    if not raw_refresh:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token provided")

    client_ip = request.client.host if request.client else ""
    ua = request.headers.get("User-Agent", "")[:512]
    user = await verify_and_rotate_refresh_token(
        raw_refresh, db, ip_address=client_ip, user_agent=ua
    )

    # Issue new tokens
    access_token = create_access_token({"sub": user.username, "role": user.role.value})
    new_raw_refresh = await create_refresh_token(
        user.id, db, ip_address=client_ip, user_agent=ua
    )
    await db.commit()

    cookie_domain = os.getenv("AUTH_COOKIE_DOMAIN") or None
    cookie_secure = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
    access_max_age = int(os.getenv("TOKEN_EXPIRE_MINUTES", "15")) * 60
    refresh_max_age = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")) * 86400
    cookie_name = os.getenv("AUTH_COOKIE_NAME", "pm_token")

    response.set_cookie(
        key=cookie_name,
        value=access_token,
        max_age=access_max_age,
        path="/",
        domain=cookie_domain,
        secure=cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=new_raw_refresh,
        max_age=refresh_max_age,
        path="/api/auth/refresh",
        domain=cookie_domain,
        secure=cookie_secure,
        httponly=True,
        samesite="strict",
    )

    perms = get_effective_permissions(user.role.value, user.custom_permissions)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role.value,
            "permissions": perms,
        },
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Revoke the refresh token and clear auth cookies."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE) or request.headers.get(
        "X-Refresh-Token", ""
    )
    if raw_refresh:
        await revoke_refresh_token(raw_refresh, db)
    cookie_name = os.getenv("AUTH_COOKIE_NAME", "pm_token")
    response.delete_cookie(key=cookie_name, path="/")
    response.delete_cookie(key=REFRESH_COOKIE, path="/api/auth/refresh")
    return {"ok": True, "message": "Logged out successfully"}


_RESET_EMAIL_SUBJECT = "Patch-SecOps Solution password reset code"
_RESET_EMAIL_BODY = (
    "Someone requested a password reset for your Patch-SecOps Solution account.\n\n"
    "Your 6-digit reset code, valid for {ttl} minutes:\n\n{otp}\n\n"
    "If you did not request this, you can ignore this message."
)

# OTP policy: 10^6 codes, 5 guesses, 10 minutes -> 0.05% guess chance per code,
# and each /forgot invalidates the previous one. /forgot is additionally capped
# per IP (FORGOT_MAX_PER_MINUTE), which is what keeps OTP email volume - and
# OTP harvesting - bounded; see install_rate_limiting for the wiring.
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def _utcnow():
    """Naive UTC now, matching db_models' DateTime storage convention."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _send_reset_email_safe(sendable, title: str, body: str) -> None:
    """Fire-and-forget send: mirrors notifications.send_event_notification's
    try/except so an SMTP failure after the response is sent is logged, not raised."""
    from api.notifications import _send_notification

    try:
        await _send_notification(sendable, title, body)
    except Exception:
        logger.exception("Password reset email delivery failed")


async def _queue_reset_email(
    background_tasks: BackgroundTasks, db: AsyncSession, user: User, otp: str
) -> bool:
    """Queue the OTP email to the user's own address; the code is never in an
    HTTP response. Only the SMTP send is deferred: FastAPI tears down the
    request's db session before background tasks run, and the send must not sit
    in the request path (uniform timing = no user-enumeration oracle)."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.channel_type == "email",
            NotificationChannel.is_enabled == True,
        )
    )
    channel = result.scalars().first()
    if not channel or not user.email:
        return False
    cfg = decrypt_json_field(channel.config)
    if not cfg.get("smtp_host"):
        return False
    sendable = SimpleNamespace(channel_type="email", config={**cfg, "to": user.email})
    background_tasks.add_task(
        _send_reset_email_safe,
        sendable,
        _RESET_EMAIL_SUBJECT,
        _RESET_EMAIL_BODY.format(otp=otp, ttl=OTP_TTL_MINUTES),
    )
    return True


@router.post("/forgot")
@limiter.limit(f"{FORGOT_MAX_PER_MINUTE}/minute")
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Always returns the same generic response — no user enumeration and no
    OTP in the body (the code is delivered out-of-band by email only)."""
    if not req.username_or_email:
        raise HTTPException(400, "username_or_email is required")
    try:
        result = await db.execute(
            select(User).where(
                (User.username == req.username_or_email)
                | (User.email == req.username_or_email)
            )
        )
        user = result.scalar_one_or_none()
        if user and user.is_active:
            otp = f"{secrets.randbelow(10 ** 6):06d}"
            # One live code per user: a resend invalidates the previous one.
            stale = (
                await db.execute(
                    select(PasswordResetOTP).where(
                        PasswordResetOTP.user_id == user.id
                    )
                )
            ).scalars().all()
            for row in stale:
                await db.delete(row)
            db.add(
                PasswordResetOTP(
                    user_id=user.id,
                    code_hash=hash_password(otp),
                    attempts=0,
                    expires_at=_utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
                )
            )
            await db.commit()
            await _queue_reset_email(background_tasks, db, user, otp)
    except Exception:
        # Delivery or lookup failures must not change the response shape.
        logger.warning("Password reset delivery failed", exc_info=True)
    return {"status": "ok"}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    # One generic error for every failure mode: an attacker must not learn
    # whether the account exists or how close the guess was.
    invalid = HTTPException(400, "Invalid or expired reset code")

    result = await db.execute(
        select(User).where(
            (User.username == req.username_or_email)
            | (User.email == req.username_or_email)
        )
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise invalid

    rows = (
        await db.execute(
            select(PasswordResetOTP).where(PasswordResetOTP.user_id == user.id)
        )
    ).scalars().all()
    row = rows[0] if rows else None
    if row is None:
        raise invalid
    if row.expires_at < _utcnow() or (row.attempts or 0) >= OTP_MAX_ATTEMPTS:
        await db.delete(row)
        await db.commit()
        raise invalid
    if not verify_password(req.otp, row.code_hash):
        row.attempts = (row.attempts or 0) + 1
        if row.attempts >= OTP_MAX_ATTEMPTS:
            await db.delete(row)  # cap reached: burn the code
        await db.commit()
        raise invalid

    # Checked only after the code verifies, and before it is spent, so a weak
    # password never burns the user's OTP.
    validate_password_strength(req.new_password)

    await db.delete(row)
    user.hashed_password = hash_password(req.new_password)
    await db.commit()
    # A reset password must invalidate every session opened with the old one.
    await revoke_all_user_tokens(user.id, db)
    return {"status": "ok"}


@router.post("/register", response_model=UserOut)
async def register_user(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Validate password strength
    validate_password_strength(req.password)

    # First user becomes admin, rest need admin to create
    count = await db.scalar(select(func.count(User.id)))
    if count > 0:
        # After first user, we check if current user is admin (this is a public endpoint only for first user)
        # However, for simplicity, we allow any registration but assign roles based on count.
        # In a real app, you might disable public registration after the first user.
        raise HTTPException(
            403,
            "Public registration is only available for the first administrator. Please contact your system admin.",
        )

    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username or email already exists")

    role = UserRole.admin if count == 0 else UserRole.viewer
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.from_user(user)


@router.post("/users", response_model=UserOut)
async def create_user(
    req: CreateUserRequest,
    current: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Admin creates a new user with a specific role."""
    validate_password_strength(req.password)
    if req.role not in [r.value for r in UserRole]:
        raise HTTPException(
            400, f"Invalid role. Must be one of: {[r.value for r in UserRole]}"
        )
    existing = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username or email already exists")

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=UserRole(req.role),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserOut.from_user(user)


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    req: AdminResetPasswordRequest,
    current: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Admin resets another user's password."""
    validate_password_strength(req.new_password)
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")
    target.hashed_password = hash_password(req.new_password)
    await db.commit()
    return {"ok": True, "message": f"Password reset for user '{target.username}'"}


@router.get("/setup/check")
async def check_setup(db: AsyncSession = Depends(get_db)):
    """Check if any user exists in the database. Used for first-time setup flow."""
    count = await db.scalar(select(func.count(User.id)))
    return {"setup_required": count == 0}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return UserOut.from_user(user)


@router.get("/users")
async def list_users(
    user: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    return [UserOut.from_user(u) for u in result.scalars().all()]


@router.get("/role-defaults")
async def role_defaults(user: User = Depends(require_role(UserRole.admin))):
    """Return default permissions for every role and the full feature list."""
    return {"features": ALL_FEATURES, "role_defaults": ROLE_DEFAULTS}


@router.put("/users/{user_id}/permissions")
async def update_user_permissions(
    user_id: int,
    body: dict,
    current: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Admin sets per-user custom permission overrides."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")
    raw_perms = body.get("permissions") or {}
    if not isinstance(raw_perms, dict):
        raw_perms = {}
    # Store only keys that are valid features; compute overrides vs role defaults
    role_name = target.role.value if hasattr(target.role, "value") else str(target.role)
    role_defaults = ROLE_DEFAULTS.get(role_name, {})
    overrides = {}
    for k, v in raw_perms.items():
        if k in ALL_FEATURES:
            val = bool(v)
            # Only store if it differs from the role default
            if val != role_defaults.get(k, False):
                overrides[k] = val
    target.custom_permissions = overrides if overrides else None
    await db.commit()
    await db.refresh(target)
    return UserOut.from_user(target)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    current: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")
    if body.email is not None:
        target.email = body.email
    if body.full_name is not None:
        target.full_name = body.full_name
    if body.role is not None:
        target.role = UserRole(body.role)
    if body.is_active is not None:
        target.is_active = body.is_active
    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == current.id:
        raise HTTPException(400, "Cannot delete yourself")
    await db.delete(target)
    await db.commit()
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.get("old_password", ""), user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")
    new_pw = body.get("new_password", "")
    validate_password_strength(new_pw)
    user.hashed_password = hash_password(new_pw)
    await db.commit()
    # A password change must invalidate every session opened with the old one.
    await revoke_all_user_tokens(user.id, db)
    return {"ok": True}


# ── Monitoring tools status ──

MONITORING_TOOLS = {
    "prometheus": {"name": "Prometheus", "default_port": 9090, "path": "/-/healthy"},
    "grafana": {"name": "Grafana", "default_port": 3001, "path": "/api/health"},
}


def _check_port(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


@router.get("/monitoring-status")
async def monitoring_status(user: User = Depends(get_current_user)):
    """Check which monitoring tools are reachable on localhost."""
    import os

    results = {}
    master_ip = os.getenv("MASTER_IP", "localhost")
    for key, info in MONITORING_TOOLS.items():
        port_env = os.getenv(f"{key.upper()}_PORT", str(info["default_port"]))
        port = int(port_env)
        url_env = os.getenv(f"{key.upper()}_URL", "")
        reachable = _check_port("127.0.0.1", port)
        url = (
            url_env if url_env else (f"http://{master_ip}:{port}" if reachable else "")
        )
        results[key] = {
            "name": info["name"],
            "port": port,
            "reachable": reachable,
            "url": url,
        }
    return results


@router.get("/me/permissions")
async def get_my_permissions(
    current_user: User = Depends(get_current_user),
):
    """Get granular permissions for the current user based on RBAC."""
    perms = get_user_permissions(current_user)
    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role),
        "permissions": {feature: perm.value for feature, perm in perms.items()},
    }


@router.get("/permissions/features")
async def list_all_features(
    current_user: User = Depends(get_current_user),
):
    """List all available features and their permission levels."""
    from api.rbac import (
        list_all_features as rbac_list_features,
        get_feature_permissions,
    )

    features = rbac_list_features()
    return {
        "features": [
            {
                "name": f,
                "available_permissions": [p.value for p in get_feature_permissions(f)],
            }
            for f in features
        ]
    }
