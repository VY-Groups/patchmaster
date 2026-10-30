"""OIDC / OAuth2 SSO integration for Patch-SecOps Solution.

Supports any standards-compliant identity provider:
  - Okta:         OIDC_DISCOVERY_URL=https://{domain}/.well-known/openid-configuration
  - Azure AD:     OIDC_DISCOVERY_URL=https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration
  - Google:       OIDC_DISCOVERY_URL=https://accounts.google.com/.well-known/openid-configuration
  - Keycloak:     OIDC_DISCOVERY_URL=https://{host}/realms/{realm}/.well-known/openid-configuration

Required environment variables:
  OIDC_ENABLED=true
  OIDC_CLIENT_ID=<your-client-id>
  OIDC_CLIENT_SECRET=<your-client-secret>
  OIDC_DISCOVERY_URL=<discovery-url>
  OIDC_REDIRECT_URI=https://your-server/api/auth/oidc/callback
  OIDC_ROLE_CLAIM=groups   (optional: OIDC claim to map to Patch-SecOps Solution roles)
  OIDC_ROLE_MAP={"admin":["pm-admins"],"operator":["pm-ops"]}   (optional JSON mapping)
"""
import os
import json
import secrets
import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models.db_models import User, UserRole
from auth import create_access_token, create_refresh_token

logger = logging.getLogger("patchmaster.oidc")

OIDC_ENABLED = os.getenv("OIDC_ENABLED", "false").lower() == "true"
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL", "")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")
OIDC_SCOPE = os.getenv("OIDC_SCOPE", "openid email profile")
OIDC_ROLE_CLAIM = os.getenv("OIDC_ROLE_CLAIM", "groups")
OIDC_DEFAULT_ROLE = os.getenv("OIDC_DEFAULT_ROLE", "viewer")
OIDC_FRONTEND_REDIRECT = os.getenv("OIDC_FRONTEND_REDIRECT", "/")

# Parse role map: e.g. {"admin": ["pm-admins","Administrators"], "operator": ["pm-ops"]}
try:
    _raw_role_map = os.getenv("OIDC_ROLE_MAP", "{}")
    OIDC_ROLE_MAP: dict = json.loads(_raw_role_map)
except Exception:
    OIDC_ROLE_MAP = {}

router = APIRouter(prefix="/api/auth/oidc", tags=["oidc-sso"])

# In-memory state store (use Redis in HA deployments)
_STATE_STORE: dict[str, str] = {}


def _get_oauth_client():
    """Create authlib OAuth2 client with OIDC discovery."""
    try:
        from authlib.integrations.httpx_client import AsyncOAuth2Client
    except ImportError:
        raise HTTPException(503, "authlib not installed. Run: pip install authlib")

    client = AsyncOAuth2Client(
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        scope=OIDC_SCOPE,
        redirect_uri=OIDC_REDIRECT_URI,
    )
    return client


def _map_role(claims: dict) -> str:
    """Map OIDC claims to a Patch-SecOps Solution role using OIDC_ROLE_MAP."""
    if not OIDC_ROLE_MAP:
        return OIDC_DEFAULT_ROLE

    user_groups = claims.get(OIDC_ROLE_CLAIM, [])
    if isinstance(user_groups, str):
        user_groups = [user_groups]

    # Check roles in priority order (admin > operator > viewer)
    for pm_role in ("admin", "operator", "auditor", "viewer"):
        allowed_groups = OIDC_ROLE_MAP.get(pm_role, [])
        if isinstance(allowed_groups, str):
            allowed_groups = [allowed_groups]
        if any(g in user_groups for g in allowed_groups):
            return pm_role

    return OIDC_DEFAULT_ROLE


@router.get("/login")
async def oidc_login(request: Request):
    """Redirect the browser to the IdP login page."""
    if not OIDC_ENABLED:
        raise HTTPException(404, "OIDC SSO is not enabled on this server.")
    if not all([OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_DISCOVERY_URL, OIDC_REDIRECT_URI]):
        raise HTTPException(503, "OIDC is not fully configured. Check server environment variables.")

    client = _get_oauth_client()

    # Fetch OIDC discovery document to get authorization_endpoint
    import httpx
    async with httpx.AsyncClient(timeout=10) as http:
        disc = await http.get(OIDC_DISCOVERY_URL)
        disc.raise_for_status()
        disc_data = disc.json()

    auth_endpoint = disc_data.get("authorization_endpoint")
    if not auth_endpoint:
        raise HTTPException(503, "OIDC discovery document missing authorization_endpoint")

    state = secrets.token_urlsafe(32)
    _STATE_STORE[state] = "pending"  # simple CSRF guard

    uri, _ = client.create_authorization_url(auth_endpoint, state=state)
    return RedirectResponse(uri)


@router.get("/callback")
async def oidc_callback(request: Request, code: str, state: str):
    """Handle the IdP callback, exchange code for tokens, and log in the user."""
    if not OIDC_ENABLED:
        raise HTTPException(404, "OIDC SSO is not enabled on this server.")

    if state not in _STATE_STORE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OIDC state parameter (CSRF protection)")
    del _STATE_STORE[state]

    client = _get_oauth_client()

    import httpx
    async with httpx.AsyncClient(timeout=15) as http:
        # Fetch discovery doc again for token_endpoint and userinfo_endpoint
        disc = await http.get(OIDC_DISCOVERY_URL)
        disc.raise_for_status()
        disc_data = disc.json()

    token_endpoint = disc_data.get("token_endpoint")
    userinfo_endpoint = disc_data.get("userinfo_endpoint")

    if not token_endpoint:
        raise HTTPException(503, "OIDC discovery missing token_endpoint")

    # Exchange code for tokens
    try:
        token_resp = await client.fetch_token(
            token_endpoint,
            code=code,
            redirect_uri=OIDC_REDIRECT_URI,
        )
    except Exception as e:
        logger.error("OIDC token exchange failed: %s", e)
        raise HTTPException(502, f"OIDC token exchange failed: {e}")

    # Fetch user info
    claims = {}
    if userinfo_endpoint:
        try:
            async with httpx.AsyncClient(timeout=10) as uhttp:
                ur = await uhttp.get(
                    userinfo_endpoint,
                    headers={"Authorization": f"Bearer {token_resp.get('access_token', '')}"}
                )
                if ur.status_code == 200:
                    claims = ur.json()
        except Exception as e:
            logger.warning("OIDC userinfo fetch failed: %s", e)

    # Try to decode id_token for claims if userinfo is empty
    if not claims:
        id_token = token_resp.get("id_token", "")
        if id_token:
            import jwt as pyjwt
            try:
                claims = pyjwt.decode(id_token, options={"verify_signature": False})
            except Exception:
                pass

    email = claims.get("email") or claims.get("upn") or claims.get("preferred_username") or ""
    given_name = claims.get("given_name") or claims.get("name") or ""
    sub = claims.get("sub") or email

    if not email and not sub:
        raise HTTPException(400, "OIDC provider did not return email or subject claim")

    # Map to Patch-SecOps Solution role
    pm_role = _map_role(claims)

    # Upsert user in DB
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            # Auto-provision on first SSO login
            import re
            username_base = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower()) or f"sso_{sub[:12]}"
            # Ensure unique username
            existing = await db.execute(select(User).where(User.username == username_base))
            if existing.scalar_one_or_none():
                username_base = f"{username_base}_{secrets.token_hex(3)}"

            import hashlib
            dummy_pw = hashlib.sha256(os.urandom(32)).hexdigest()  # unusable password

            user = User(
                username=username_base,
                email=email or f"{sub}@sso.local",
                hashed_password=dummy_pw,
                full_name=given_name,
                role=UserRole(pm_role),
                is_active=True,
            )
            db.add(user)
            await db.flush()
            logger.info("OIDC: Auto-provisioned user '%s' with role '%s'", user.username, pm_role)
        else:
            # Update role on each login (tracks IdP group changes)
            user.role = UserRole(pm_role)
            if given_name:
                user.full_name = given_name

        if not user.is_active:
            raise HTTPException(403, "Your account has been disabled. Contact your administrator.")

        access_token = create_access_token({"sub": user.username, "role": user.role.value})
        client_ip = request.client.host if request.client else ""
        ua = request.headers.get("User-Agent", "")[:512]
        raw_refresh = await create_refresh_token(user.id, db, ip_address=client_ip, user_agent=ua)
        await db.commit()

    # Redirect to frontend with token in URL fragment (client reads it then clears URL)
    frontend_url = OIDC_FRONTEND_REDIRECT or "/"
    redirect_url = f"{frontend_url}#sso_token={access_token}&refresh={raw_refresh}"
    return RedirectResponse(redirect_url)


@router.get("/config")
async def oidc_config():
    """Return OIDC config for the frontend (public, no secrets)."""
    return {
        "enabled": OIDC_ENABLED,
        "provider_name": os.getenv("OIDC_PROVIDER_NAME", "SSO"),
        "login_url": "/api/auth/oidc/login" if OIDC_ENABLED else None,
    }
