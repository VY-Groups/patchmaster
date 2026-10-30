"""JWT authentication & RBAC for Patch-SecOps Solution — enterprise hardened."""

import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.db_models import User, UserRole, RefreshToken

# Secrets that have shipped as defaults in this repo; all must be rejected so a
# copy-paste deployment can never mint forgeable tokens (plan S0-1 fail-closed).
_PLACEHOLDER_SECRETS = frozenset(
    {
        "patchmaster-change-me-in-production-32chars!",  # old auth.py default
        "change-me-to-a-secure-random-string",          # old docker-compose default
        "5e91c5c9d0b5494f8c2a4c0c8f9f5a9d6b8f184f3e30e0c9e225a34a8c9f0f5b",  # old env.example
    }
)


def _load_jwt_secret() -> str:
    """No default, no placeholder, no short secret: refuse to start instead."""
    secret = os.getenv("JWT_SECRET", "").strip()
    if (
        not secret
        or len(secret) < 32
        or secret in _PLACEHOLDER_SECRETS
        or secret.lower().startswith(("changeme", "change-me", "replace-me"))
    ):
        raise RuntimeError(
            "JWT_SECRET is unset or is a known placeholder and Patch-SecOps Solution "
            "refuses to start. Generate one with "
            'python -c "import secrets; print(secrets.token_hex(32))" '
            "and set JWT_SECRET in .env."
        )
    return secret


SECRET_KEY = _load_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("TOKEN_EXPIRE_MINUTES", "60")
)  # 60 min for long-running operations
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
# Optional bearer token extractor (no auto error) for endpoints that do their own fallback auth
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        import bcrypt as bcrypt_lib

        return bcrypt_lib.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ── Refresh Token Helpers ──


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash of a raw token for safe DB storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_refresh_token(
    user_id: int,
    db: AsyncSession,
    ip_address: str = "",
    user_agent: str = "",
) -> str:
    """Generate a cryptographically secure refresh token and persist its hash."""
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )

    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip_address=ip_address[:45],
        user_agent=user_agent[:512],
    )
    db.add(rt)
    await db.flush()
    return raw  # return the raw token to send to the client (never stored)


async def verify_and_rotate_refresh_token(
    raw_token: str,
    db: AsyncSession,
    ip_address: str = "",
    user_agent: str = "",
) -> Optional[User]:
    """Validate a refresh token, revoke it, issue a new one (rotation), and return the user.
    Returns (user, new_raw_token) or raises HTTPException on failure."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
        )
    )
    rt = result.scalar_one_or_none()
    if not rt:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token"
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if rt.expires_at < now:
        rt.revoked = True
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expired")

    # Rotate: revoke old token
    rt.revoked = True
    await db.flush()

    # Load user
    user = await db.get(User, rt.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    return user


async def revoke_refresh_token(raw_token: str, db: AsyncSession) -> bool:
    """Revoke a specific refresh token (called on logout)."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt:
        rt.revoked = True
        await db.commit()
        return True
    return False


async def revoke_all_user_tokens(user_id: int, db: AsyncSession):
    """Revoke ALL refresh tokens for a user (e.g. on password change)."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        )
    )
    for rt in result.scalars().all():
        rt.revoked = True
    await db.commit()


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Only access tokens are credentials: reject refresh tokens AND any
        # purpose-specific token (e.g. password-reset) — plan S0-1 token handling.
        if payload.get("type") != "access":
            raise cred_exc
        username: str = payload.get("sub")
        if not username:
            raise cred_exc
    except InvalidTokenError:
        raise cred_exc

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise cred_exc
    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Same as get_current_user but returns None instead of raising when token is absent/invalid."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        username: str = payload.get("sub")
        if not username:
            return None
    except InvalidTokenError:
        return None

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return None
    return user


def require_role(*roles: UserRole):
    """Dependency factory — restrict endpoint to specific roles."""

    async def role_checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' not authorized. Required: {[r.value for r in roles]}",
            )
        return user

    return role_checker
