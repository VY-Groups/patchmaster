"""CI/CD Secret Manager — encrypted key-value store for pipeline secrets.

Secrets are stored Fernet-encrypted at rest.  The encryption key is read from
the PM_SECRET_KEY environment variable (32-byte URL-safe base64).  This variable
is required — the service will raise RuntimeError on startup if it is absent.
Generate a suitable key with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Reference syntax in pipeline scripts:  ${{ secrets.MY_SECRET }}
"""
import base64
import hashlib
import json
import os
from datetime import datetime

def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_role
from database import get_db
from models.db_models import (
    BackupConfig,
    CICDPipeline,
    CICDSecret,
    CICDVariable,
    GitRepository,
    MirrorRepo,
    NotificationChannel,
    PluginIntegration,
    User,
    UserRole,
)

router = APIRouter(prefix="/api/cicd/secrets", tags=["cicd-secrets"])


# ── Encryption helpers ──

def _fernet() -> Fernet:
    raw = os.getenv("PM_SECRET_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "PM_SECRET_KEY environment variable is not set. "
            "Set it to a 32-byte URL-safe base64 key before starting Patch-SecOps Solution."
        )
    raw_bytes = raw.encode() if isinstance(raw, str) else raw
    # Validate: a proper Fernet key is exactly 44 URL-safe base64 chars (32 bytes decoded)
    try:
        decoded = base64.urlsafe_b64decode(raw_bytes)
        if len(decoded) == 32:
            key = raw_bytes
        else:
            # Wrong length — derive a proper 32-byte key from the provided value
            key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    except Exception:
        key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def _encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ""


def encrypt_text_field(value: str) -> str:
    text = str(value or "").strip()
    return _encrypt(text) if text else ""


def decrypt_text_field(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    decrypted = _decrypt(text)
    return decrypted or text


def encrypt_json_field(value: dict | None) -> dict:
    payload = value or {}
    if not payload:
        return {}
    return {"_enc": _encrypt(json.dumps(payload))}


def decrypt_json_field(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        enc = value.get("_enc")
        if isinstance(enc, str) and enc:
            decrypted = _decrypt(enc)
            if decrypted:
                try:
                    loaded = json.loads(decrypted)
                    return loaded if isinstance(loaded, dict) else {}
                except Exception:
                    return {}
        return value
    if isinstance(value, str):
        decrypted = _decrypt(value)
        candidate = decrypted or value
        try:
            loaded = json.loads(candidate)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}
    return {}


def is_encrypted_text(value: str) -> bool:
    return bool(value) and bool(_decrypt(value))


def is_encrypted_json(value) -> bool:
    return isinstance(value, dict) and isinstance(value.get("_enc"), str) and bool(_decrypt(value.get("_enc", "")))


async def migrate_legacy_inline_secrets(db: AsyncSession) -> int:
    """Encrypt legacy plaintext secrets still stored inline on pipeline/repo rows."""
    changed = 0

    pipelines = (await db.execute(select(CICDPipeline))).scalars().all()
    for pipeline in pipelines:
        creds = pipeline.auth_credentials or {}
        if creds and not is_encrypted_json(creds):
            pipeline.auth_credentials = encrypt_json_field(decrypt_json_field(creds) or creds)
            changed += 1
        if pipeline.webhook_secret and not is_encrypted_text(pipeline.webhook_secret):
            pipeline.webhook_secret = encrypt_text_field(pipeline.webhook_secret)
            changed += 1

    repos = (await db.execute(select(GitRepository))).scalars().all()
    for repo in repos:
        if repo.auth_token and not is_encrypted_text(repo.auth_token):
            repo.auth_token = encrypt_text_field(repo.auth_token)
            changed += 1
        if repo.webhook_secret and not is_encrypted_text(repo.webhook_secret):
            repo.webhook_secret = encrypt_text_field(repo.webhook_secret)
            changed += 1

    channels = (await db.execute(select(NotificationChannel))).scalars().all()
    for channel in channels:
        cfg = channel.config or {}
        if cfg and not is_encrypted_json(cfg):
            channel.config = encrypt_json_field(decrypt_json_field(cfg) or cfg)
            changed += 1

    mirror_repos = (await db.execute(select(MirrorRepo))).scalars().all()
    for repo in mirror_repos:
        auth_cfg = repo.auth_config or {}
        if auth_cfg and not is_encrypted_json(auth_cfg):
            repo.auth_config = encrypt_json_field(decrypt_json_field(auth_cfg) or auth_cfg)
            changed += 1

    plugins = (await db.execute(select(PluginIntegration))).scalars().all()
    for plugin in plugins:
        cfg = plugin.config or {}
        if cfg and not is_encrypted_json(cfg):
            plugin.config = encrypt_json_field(decrypt_json_field(cfg) or cfg)
            changed += 1
        if plugin.secret and not is_encrypted_text(plugin.secret):
            plugin.secret = encrypt_text_field(plugin.secret)
            changed += 1

    backup_configs = (await db.execute(select(BackupConfig))).scalars().all()
    for config in backup_configs:
        if config.encryption_key and not is_encrypted_text(config.encryption_key):
            config.encryption_key = encrypt_text_field(config.encryption_key)
            changed += 1
        storage_cfg = config.storage_config or {}
        if storage_cfg and not is_encrypted_json(storage_cfg):
            config.storage_config = encrypt_json_field(decrypt_json_field(storage_cfg) or storage_cfg)
            changed += 1

    variables = (await db.execute(select(CICDVariable))).scalars().all()
    for variable in variables:
        if variable.is_secret and variable.value and not is_encrypted_text(variable.value):
            variable.value = encrypt_text_field(variable.value)
            changed += 1

    if changed:
        await db.commit()
    return changed


# ── Pydantic schemas ──

class SecretCreate(BaseModel):
    name: str
    description: str = ""
    scope: str = "global"          # global | pipeline
    pipeline_id: Optional[int] = None
    value: str                     # plaintext — encrypted before storage


class SecretUpdate(BaseModel):
    description: Optional[str] = None
    value: Optional[str] = None    # if provided, re-encrypt


class SecretOut(BaseModel):
    id: int
    name: str
    description: str
    scope: str
    pipeline_id: Optional[int]
    has_value: bool                # never expose the actual value
    created_by: str
    created_at: str
    updated_at: str


def _to_out(s: CICDSecret) -> SecretOut:
    return SecretOut(
        id=s.id,
        name=s.name,
        description=s.description or "",
        scope=s.scope or "global",
        pipeline_id=s.pipeline_id,
        has_value=bool(s.encrypted_value),
        created_by=s.created_by or "",
        created_at=s.created_at.isoformat() if s.created_at else "",
        updated_at=s.updated_at.isoformat() if s.updated_at else "",
    )


# ── Routes ──

@router.get("/", response_model=list[SecretOut])
async def list_secrets(
    pipeline_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """List secrets.  Optionally filter by pipeline_id (returns global + pipeline-scoped)."""
    from sqlalchemy import or_
    stmt = select(CICDSecret).order_by(CICDSecret.name.asc())
    if pipeline_id is not None:
        stmt = stmt.where(
            or_(
                CICDSecret.scope == "global",
                (CICDSecret.scope == "pipeline") & (CICDSecret.pipeline_id == pipeline_id),
            )
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("/", response_model=SecretOut, status_code=201)
async def create_secret(
    body: SecretCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Secret name is required")
    scope = body.scope if body.scope in ("global", "pipeline") else "global"
    pipeline_id = body.pipeline_id if scope == "pipeline" else None

    if pipeline_id is not None:
        pipeline = await db.get(CICDPipeline, pipeline_id)
        if not pipeline:
            raise HTTPException(404, "Pipeline not found")

    # Uniqueness check
    existing = (await db.execute(
        select(CICDSecret).where(
            CICDSecret.name == name,
            CICDSecret.pipeline_id == pipeline_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Secret '{name}' already exists in this scope")

    secret = CICDSecret(
        name=name,
        description=body.description or "",
        scope=scope,
        pipeline_id=pipeline_id,
        encrypted_value=_encrypt(body.value),
        created_by=getattr(user, "username", "system"),
    )
    db.add(secret)
    await db.commit()
    await db.refresh(secret)
    return _to_out(secret)


@router.put("/{secret_id}", response_model=SecretOut)
async def update_secret(
    secret_id: int,
    body: SecretUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    secret = await db.get(CICDSecret, secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    if body.description is not None:
        secret.description = body.description
    if body.value is not None:
        secret.encrypted_value = _encrypt(body.value)
    secret.updated_at = _utcnow()
    db.add(secret)
    await db.commit()
    await db.refresh(secret)
    return _to_out(secret)


@router.delete("/{secret_id}")
async def delete_secret(
    secret_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    secret = await db.get(CICDSecret, secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    await db.delete(secret)
    await db.commit()
    return {"status": "ok", "message": f"Secret '{secret.name}' deleted"}


# ── Internal helper used by pipeline executor ──

async def resolve_secrets_for_pipeline(pipeline_id: Optional[int], db: AsyncSession) -> dict[str, str]:
    """Return {name: plaintext} for all secrets accessible to a pipeline."""
    from sqlalchemy import or_
    if pipeline_id is not None:
        stmt = select(CICDSecret).where(
            or_(
                CICDSecret.scope == "global",
                (CICDSecret.scope == "pipeline") & (CICDSecret.pipeline_id == pipeline_id),
            )
        )
    else:
        stmt = select(CICDSecret).where(CICDSecret.scope == "global")
    rows = (await db.execute(stmt)).scalars().all()
    return {r.name: _decrypt(r.encrypted_value) for r in rows}
