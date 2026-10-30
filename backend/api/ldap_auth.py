"""Active Directory / LDAP authentication and user sync."""
import os
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from auth import get_current_user, require_role, create_access_token, hash_password
from models.db_models import User, UserRole

logger = logging.getLogger("patchmaster.ldap")
router = APIRouter(prefix="/api/auth/ldap", tags=["ldap"])

# ── Config model ──

class LDAPConfig(BaseModel):
    server: str                          # e.g. ldap://dc.corp.local or ldaps://dc.corp.local:636
    base_dn: str                         # e.g. DC=corp,DC=local
    bind_dn: str                         # service account DN
    bind_password: str
    user_search_filter: str = "(sAMAccountName={username})"
    group_search_base: Optional[str] = None
    admin_group_dn: Optional[str] = None   # members get admin role
    operator_group_dn: Optional[str] = None
    use_ssl: bool = False
    verify_ssl: bool = True
    timeout: int = 10

class LDAPLoginRequest(BaseModel):
    username: str
    password: str

class LDAPTestRequest(BaseModel):
    config: LDAPConfig

class LDAPSyncRequest(BaseModel):
    config: LDAPConfig
    default_role: str = "viewer"

# ── Helpers ──

def _get_ldap_config_from_env() -> Optional[LDAPConfig]:
    """Load LDAP config from environment variables if set."""
    server = os.getenv("LDAP_SERVER", "").strip()
    if not server:
        return None
    return LDAPConfig(
        server=server,
        base_dn=os.getenv("LDAP_BASE_DN", ""),
        bind_dn=os.getenv("LDAP_BIND_DN", ""),
        bind_password=os.getenv("LDAP_BIND_PASSWORD", ""),
        user_search_filter=os.getenv("LDAP_USER_FILTER", "(sAMAccountName={username})"),
        group_search_base=os.getenv("LDAP_GROUP_SEARCH_BASE") or None,
        admin_group_dn=os.getenv("LDAP_ADMIN_GROUP") or None,
        operator_group_dn=os.getenv("LDAP_OPERATOR_GROUP") or None,
        use_ssl=os.getenv("LDAP_USE_SSL", "false").lower() == "true",
        verify_ssl=os.getenv("LDAP_VERIFY_SSL", "true").lower() == "true",
        timeout=int(os.getenv("LDAP_TIMEOUT", "10")),
    )


def _ldap_connect(cfg: LDAPConfig):
    """Create and return an ldap3 Connection bound with the service account."""
    try:
        from ldap3 import Server, Connection, ALL, Tls, NTLM, SIMPLE
        import ssl
    except ImportError:
        raise HTTPException(500, "ldap3 package not installed. Run: pip install ldap3")

    tls = None
    if cfg.use_ssl or cfg.server.startswith("ldaps://"):
        ctx = ssl.create_default_context()
        if not cfg.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        tls = Tls(validate=ssl.CERT_REQUIRED if cfg.verify_ssl else ssl.CERT_NONE, ca_certs_file=None)

    server = Server(cfg.server, use_ssl=cfg.use_ssl or cfg.server.startswith("ldaps://"), tls=tls, get_info=ALL, connect_timeout=cfg.timeout)
    conn = Connection(server, user=cfg.bind_dn, password=cfg.bind_password, authentication=SIMPLE, auto_bind=True, raise_exceptions=True)
    return conn


def _resolve_role(cfg: LDAPConfig, member_of: list[str]) -> UserRole:
    """Map AD group membership to a Patch-SecOps Solution role."""
    if cfg.admin_group_dn and any(cfg.admin_group_dn.lower() in g.lower() for g in member_of):
        return UserRole.admin
    if cfg.operator_group_dn and any(cfg.operator_group_dn.lower() in g.lower() for g in member_of):
        return UserRole.operator
    return UserRole.viewer


def _search_user(conn, cfg: LDAPConfig, username: str) -> Optional[dict]:
    """Search for a user entry and return their attributes."""
    search_filter = cfg.user_search_filter.format(username=username)
    conn.search(
        search_base=cfg.base_dn,
        search_filter=search_filter,
        attributes=["cn", "mail", "sAMAccountName", "displayName", "memberOf", "userPrincipalName"],
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    member_of = []
    try:
        member_of = list(entry.memberOf.values) if hasattr(entry, "memberOf") else []
    except Exception:
        pass
    return {
        "dn": entry.entry_dn,
        "username": str(entry.sAMAccountName) if hasattr(entry, "sAMAccountName") else username,
        "email": str(entry.mail) if hasattr(entry, "mail") and entry.mail else "",
        "full_name": str(entry.displayName) if hasattr(entry, "displayName") and entry.displayName else str(entry.cn) if hasattr(entry, "cn") else username,
        "member_of": member_of,
    }


# ── Endpoints ──

@router.post("/test")
async def test_ldap_connection(
    body: LDAPTestRequest,
    current: User = Depends(require_role(UserRole.admin)),
):
    """Test LDAP connectivity and service account bind."""
    try:
        conn = _ldap_connect(body.config)
        conn.unbind()
        return {"ok": True, "message": "LDAP connection successful. Service account bind verified."}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/login")
async def ldap_login(
    req: LDAPLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate a user against AD/LDAP.
    If the user doesn't exist locally, create them with the role mapped from their AD groups.
    Returns a JWT token identical to the local login flow.
    """
    cfg = _get_ldap_config_from_env()
    if not cfg:
        raise HTTPException(400, "LDAP is not configured on this server. Set LDAP_SERVER environment variable.")

    # 1. Bind with service account and find the user
    try:
        conn = _ldap_connect(cfg)
    except Exception as e:
        logger.error("LDAP service bind failed: %s", e)
        raise HTTPException(503, f"LDAP server unreachable: {e}")

    user_info = _search_user(conn, cfg, req.username)
    if not user_info:
        conn.unbind()
        raise HTTPException(401, "User not found in directory")

    # 2. Authenticate the user with their own credentials
    try:
        from ldap3 import Connection, SIMPLE
        user_conn = Connection(
            conn.server,
            user=user_info["dn"],
            password=req.password,
            authentication=SIMPLE,
            auto_bind=True,
            raise_exceptions=True,
        )
        user_conn.unbind()
    except Exception:
        conn.unbind()
        raise HTTPException(401, "Invalid credentials")
    finally:
        conn.unbind()

    # 3. Map role from AD groups
    role = _resolve_role(cfg, user_info["member_of"])

    # 4. Upsert local user record
    result = await db.execute(select(User).where(User.username == user_info["username"]))
    local_user = result.scalar_one_or_none()
    if not local_user:
        local_user = User(
            username=user_info["username"],
            email=user_info["email"] or f"{user_info['username']}@ldap.local",
            hashed_password=hash_password(os.urandom(32).hex()),  # unusable local password
            full_name=user_info["full_name"],
            role=role,
            is_active=True,
        )
        db.add(local_user)
        await db.commit()
        await db.refresh(local_user)
        logger.info("LDAP: created local user %s with role %s", local_user.username, role.value)
    else:
        # Sync role and name on every login
        local_user.role = role
        local_user.full_name = user_info["full_name"] or local_user.full_name
        if user_info["email"]:
            local_user.email = user_info["email"]
        await db.commit()
        await db.refresh(local_user)

    if not local_user.is_active:
        raise HTTPException(400, "Account is disabled")

    token = create_access_token({"sub": local_user.username, "role": local_user.role.value})
    from api.auth_api import get_effective_permissions
    perms = get_effective_permissions(local_user.role.value, local_user.custom_permissions)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": local_user.id,
            "username": local_user.username,
            "role": local_user.role.value,
            "full_name": local_user.full_name,
            "permissions": perms,
        },
    }


@router.post("/sync")
async def sync_ldap_users(
    body: LDAPSyncRequest,
    current: User = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull all users from AD/LDAP and create/update local accounts.
    Useful for pre-populating users before they first log in.
    """
    try:
        conn = _ldap_connect(body.config)
    except Exception as e:
        raise HTTPException(503, f"LDAP connection failed: {e}")

    conn.search(
        search_base=body.config.base_dn,
        search_filter="(&(objectClass=person)(sAMAccountName=*))",
        attributes=["cn", "mail", "sAMAccountName", "displayName", "memberOf", "userAccountControl"],
    )

    created = 0
    updated = 0
    skipped = 0

    for entry in conn.entries:
        try:
            uac = int(str(entry.userAccountControl)) if hasattr(entry, "userAccountControl") and entry.userAccountControl else 0
            # Bit 2 (0x2) = account disabled
            is_active = not bool(uac & 0x2)
            username = str(entry.sAMAccountName) if hasattr(entry, "sAMAccountName") else None
            if not username:
                skipped += 1
                continue
            email = str(entry.mail) if hasattr(entry, "mail") and entry.mail else f"{username}@ldap.local"
            full_name = str(entry.displayName) if hasattr(entry, "displayName") and entry.displayName else str(entry.cn) if hasattr(entry, "cn") else username
            member_of = list(entry.memberOf.values) if hasattr(entry, "memberOf") else []
            role = _resolve_role(body.config, member_of)

            result = await db.execute(select(User).where(User.username == username))
            local = result.scalar_one_or_none()
            if not local:
                local = User(
                    username=username,
                    email=email,
                    hashed_password=hash_password(os.urandom(32).hex()),
                    full_name=full_name,
                    role=role,
                    is_active=is_active,
                )
                db.add(local)
                created += 1
            else:
                local.role = role
                local.full_name = full_name
                local.email = email
                local.is_active = is_active
                updated += 1
        except Exception as ex:
            logger.warning("LDAP sync: skipped entry due to error: %s", ex)
            skipped += 1

    conn.unbind()
    await db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "total": len(conn.entries)}


@router.get("/status")
async def ldap_status(current: User = Depends(require_role(UserRole.admin))):
    """Return whether LDAP is configured via environment variables."""
    cfg = _get_ldap_config_from_env()
    if not cfg:
        return {"configured": False, "message": "LDAP_SERVER environment variable not set"}
    return {
        "configured": True,
        "server": cfg.server,
        "base_dn": cfg.base_dn,
        "bind_dn": cfg.bind_dn,
        "use_ssl": cfg.use_ssl,
        "admin_group": cfg.admin_group_dn,
        "operator_group": cfg.operator_group_dn,
    }
