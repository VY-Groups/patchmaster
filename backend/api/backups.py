import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from database import async_session, get_db
from models.db_models import BackupConfig, BackupLog, BackupType, JobStatus, User, UserRole, Host
from auth import get_current_user, require_role
from api.ops_queue import enqueue_operation
from license import TIER_FEATURES, get_license_info
from api.cicd_secrets import decrypt_json_field, decrypt_text_field, encrypt_json_field, encrypt_text_field
from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime, timezone
import logging
import httpx
import os

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
from pathlib import Path

logger = logging.getLogger("patchmaster.backups")

router = APIRouter(prefix="/api/backups", tags=["Backups"])

AGENT_PORT = 8080

# Agent API token — per-host from DB, falls back to global env var.
_GLOBAL_AGENT_API_TOKEN = os.environ.get("AGENT_API_TOKEN", "").strip()

def _agent_auth_headers(host=None) -> dict:
    token = (getattr(host, "agent_token", None) or "").strip() if host else ""
    if not token:
        token = _GLOBAL_AGENT_API_TOKEN
    return {"Authorization": f"Bearer {token}"} if token else {}

# Pydantic models
class BackupConfigBase(BaseModel):
    host_id: int
    name: str
    backup_type: str  # database, file, vm, live
    source_path: Optional[str] = None
    db_type: Optional[str] = None
    schedule: Optional[str] = None
    retention_count: int = 5
    compression_level: int = 6
    encryption_key: Optional[str] = None
    storage_path: Optional[str] = None
    storage_type: str = "local"  # local, s3, sftp, nfs, minio
    storage_config: dict = {}

class BackupConfigCreate(BackupConfigBase):
    pass

class BackupConfigResponse(BackupConfigBase):
    id: int
    is_active: bool
    created_at: datetime
    last_test_status: Optional[str] = ""
    last_test_at: Optional[datetime] = None
    last_run_status: Optional[str] = ""
    last_run_size: Optional[int] = 0
    last_run_duration: Optional[float] = 0.0
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    has_storage_config: bool = False
    model_config = ConfigDict(from_attributes=True)

class BackupLogResponse(BaseModel):
    id: int
    config_id: int
    status: str
    output: Optional[str]
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    started_at: datetime
    completed_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_obj(cls, obj):
        return cls(
            id=obj.id,
            config_id=obj.config_id,
            status=obj.status.value if hasattr(obj.status, 'value') else str(obj.status),
            output=obj.output,
            file_size_bytes=obj.file_size_bytes or 0,
            duration_seconds=obj.duration_seconds or 0.0,
            started_at=obj.started_at,
            completed_at=obj.completed_at,
        )

class StorageTestRequest(BaseModel):
    storage_type: str
    storage_config: dict = {}
    storage_path: Optional[str] = None

class RestoreRequest(BaseModel):
    backup_log_id: Optional[int] = None
    target_path: Optional[str] = None


class AgentBackupUpdate(BaseModel):
    log_id: int
    status: str
    output_file: Optional[str] = None
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    message: str = ""


def _config_to_response(config: BackupConfig) -> BackupConfigResponse:
    storage_config = decrypt_json_field(config.storage_config)
    return BackupConfigResponse(
        id=config.id,
        host_id=config.host_id,
        name=config.name,
        backup_type=config.backup_type.value if hasattr(config.backup_type, "value") else str(config.backup_type),
        source_path=config.source_path,
        db_type=config.db_type,
        schedule=config.schedule,
        retention_count=config.retention_count,
        compression_level=config.compression_level,
        encryption_key=None,
        storage_path=config.storage_path,
        storage_type=config.storage_type,
        storage_config={},
        is_active=config.is_active,
        created_at=config.created_at,
        last_test_status=config.last_test_status or "",
        last_test_at=config.last_test_at,
        last_run_status=config.last_run_status or "",
        last_run_size=config.last_run_size or 0,
        last_run_duration=config.last_run_duration or 0.0,
        last_run_at=config.last_run_at,
        next_run_at=config.next_run_at,
        has_storage_config=bool(storage_config),
    )

# Helper to check feature permission
def check_backup_permission(backup_type: str):
    license_info = get_license_info()
    if not license_info.get("valid"):
        pass # Fallback/Trial logic
    
    tier = license_info.get("tier", "basic")
    features = license_info.get("features") or TIER_FEATURES.get(tier, [])
    
    type_map = {
        "database": "backup_db",
        "file": "backup_file",
        "vm": "backup_vm",
        "live": "backup_live",
        "full_system": "backup_vm" # Treat full system as VM/Advanced feature
    }
    
    required_feature = type_map.get(backup_type)
    if not required_feature:
        raise HTTPException(status_code=400, detail="Unknown backup type")

    if required_feature not in features:
         raise HTTPException(
             status_code=403, 
             detail=f"Feature '{required_feature}' requires a higher license tier (Current: {tier})"
         )

async def trigger_agent_backup(host_ip: str, config: BackupConfig, log_id: int, host=None):
    url = f"http://{host_ip}:{AGENT_PORT}/backup/trigger"
    payload = {
        "type": config.backup_type.value,
        "source": config.source_path,
        "db_type": config.db_type,
        "destination": config.storage_path,
        "storage_type": getattr(config, "storage_type", "local"),
        "storage_config": decrypt_json_field(getattr(config, "storage_config", {}) or {}),
        "encryption_key": decrypt_text_field(config.encryption_key),
        "retention_count": config.retention_count,
        "log_id": log_id,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=_agent_auth_headers(host))
            async with async_session() as session:
                log_row = await session.get(BackupLog, log_id)
                cfg_row = await session.get(BackupConfig, config.id)
                if resp.status_code < 400:
                    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    output_file = str(data.get("output_file") or "").strip()
                    if log_row is not None:
                        if output_file:
                            log_row.output = output_file
                        if log_row.status == JobStatus.pending:
                            log_row.status = JobStatus.running
                    if cfg_row is not None:
                        cfg_row.last_run_status = JobStatus.running.value
                    await session.commit()
                else:
                    detail = resp.text[:4000]
                    if log_row is not None:
                        log_row.status = JobStatus.failed
                        log_row.output = detail
                        log_row.completed_at = _utcnow()
                    if cfg_row is not None:
                        cfg_row.last_run_status = JobStatus.failed.value
                        cfg_row.last_run_at = _utcnow()
                    await session.commit()
    except Exception as e:
        logger.error(f"Failed to trigger backup on {host_ip}: {e}")
        async with async_session() as session:
            log_row = await session.get(BackupLog, log_id)
            cfg_row = await session.get(BackupConfig, config.id)
            if log_row is not None:
                log_row.status = JobStatus.failed
                log_row.output = str(e)[:4000]
                log_row.completed_at = _utcnow()
            if cfg_row is not None:
                cfg_row.last_run_status = JobStatus.failed.value
                cfg_row.last_run_at = _utcnow()
            await session.commit()


def _bearer_token(authorization: str | None) -> str:
    header = str(authorization or "").strip()
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


@router.post("/agent-callback")
async def update_backup_from_agent(
    body: AgentBackupUpdate,
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    log_obj = await db.get(BackupLog, body.log_id)
    if not log_obj:
        raise HTTPException(status_code=404, detail="Backup log not found")

    config = await db.get(BackupConfig, log_obj.config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Backup config not found")

    host = (
        await db.execute(select(Host).where(Host.id == config.host_id))
    ).scalars().first()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    valid_global = bool(_GLOBAL_AGENT_API_TOKEN and token == _GLOBAL_AGENT_API_TOKEN)
    valid_host = bool(host.agent_token and token == host.agent_token)
    if not (valid_host or valid_global):
        raise HTTPException(status_code=401, detail="Invalid agent token")

    status_value = str(body.status or "").strip().lower()
    if status_value == "success":
        log_obj.status = JobStatus.success
        config.last_run_status = JobStatus.success.value
    elif status_value == "failed":
        log_obj.status = JobStatus.failed
        config.last_run_status = JobStatus.failed.value
    else:
        raise HTTPException(status_code=400, detail="Invalid backup status")

    output_file = str(body.output_file or "").strip()
    if output_file:
        log_obj.output = output_file
    elif body.message:
        log_obj.output = body.message[:4000]
    log_obj.file_size_bytes = max(int(body.file_size_bytes or 0), 0)
    log_obj.duration_seconds = max(float(body.duration_seconds or 0.0), 0.0)
    log_obj.completed_at = _utcnow()

    config.last_run_at = log_obj.completed_at
    config.last_run_size = log_obj.file_size_bytes
    config.last_run_duration = log_obj.duration_seconds
    db.add(log_obj)
    db.add(config)
    await db.commit()
    return {"ok": True}


async def _queueable_run_backup(config_id: int) -> dict:
    async with async_session() as session:
        result = await session.execute(select(BackupConfig).where(BackupConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        check_backup_permission(config.backup_type.value)
        host_result = await session.execute(select(Host).where(Host.id == config.host_id))
        host = host_result.scalar_one_or_none()
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")
        log_entry = BackupLog(config_id=config.id, status="pending")
        session.add(log_entry)
        config.last_run_status = JobStatus.pending.value if hasattr(JobStatus, "pending") else "pending"
        config.last_run_at = _utcnow()
        config.last_run_size = 0
        config.last_run_duration = 0.0
        session.add(config)
        await session.commit()
        await session.refresh(log_entry)
        await trigger_agent_backup(host.ip, config, log_entry.id, host)
        return {"status": "scheduled", "log_id": log_entry.id, "config_id": config_id}

from croniter import croniter

async def check_schedules(db: AsyncSession):
    """Background task to trigger scheduled backups."""
    now = _utcnow()
    query = select(BackupConfig).where(BackupConfig.is_active == True, BackupConfig.schedule.isnot(None))
    result = await db.execute(query)
    configs = result.scalars().all()
    
    for config in configs:
        try:
            # Check if it's time to run
            # Simple check: if next_run_at is passed or None
            # If None, calculate next from now
            if not config.next_run_at:
                cron_iter = croniter(config.schedule, now)
                config.next_run_at = cron_iter.get_next(datetime)
                db.add(config)
                await db.commit()
                continue
                
            if now >= config.next_run_at:
                logger.info(f"Triggering scheduled backup: {config.name}")
                # Create log entry
                log_entry = BackupLog(config_id=config.id, status="pending")
                db.add(log_entry)
                
                # Update next run
                cron_iter = croniter(config.schedule, now)
                config.next_run_at = cron_iter.get_next(datetime)
                config.last_run_at = now
                
                db.add(config)
                await db.commit()
                
                # Trigger agent (need host IP)
                host_res = await db.execute(select(Host).where(Host.id == config.host_id))
                host = host_res.scalar_one_or_none()
                if host:
                    # Notify
                    from api.notifications import notify_system_event
                    asyncio.create_task(notify_system_event(
                        "backup_started", 
                        f"Backup Started: {config.name}", 
                        f"Scheduled backup running on {host.hostname}",
                        f"/backups?config_id={config.id}"
                    ))
                    
                    # Fire and forget task (using asyncio.create_task since we are not in route context)
                    asyncio.create_task(trigger_agent_backup(host.ip, config, log_entry.id, host))
        except Exception as e:
            logger.error(f"Scheduler error for config {config.id}: {e}")

@router.post("/configs", response_model=BackupConfigResponse)
async def create_backup_config(
    config: BackupConfigCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator))
):
    try:
        b_type = BackupType(config.backup_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid backup type")

    if (config.storage_type or "local").lower() != "local":
        raise HTTPException(status_code=400, detail="Only local or mounted-path backup storage is currently supported")
        
    check_backup_permission(config.backup_type)
    
    result = await db.execute(select(Host).where(Host.id == config.host_id))
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    new_config = BackupConfig(
        host_id=config.host_id,
        name=config.name,
        backup_type=b_type,
        source_path=config.source_path,
        db_type=config.db_type,
        schedule=config.schedule,
        retention_count=config.retention_count,
        compression_level=config.compression_level,
        encryption_key=encrypt_text_field(config.encryption_key),
        storage_path=config.storage_path,
        storage_type=config.storage_type,
        storage_config=encrypt_json_field(config.storage_config),
        last_test_status="",
        last_run_status="",
    )
    db.add(new_config)
    await db.commit()
    await db.refresh(new_config)
    return _config_to_response(new_config)

@router.get("/configs", response_model=List[BackupConfigResponse])
async def list_backup_configs(
    host_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(BackupConfig)
    if host_id:
        query = query.where(BackupConfig.host_id == host_id)
    result = await db.execute(query)
    return [_config_to_response(row) for row in result.scalars().all()]

@router.post("/{config_id}/run")
async def run_backup(
    config_id: int,
    request: Request,
    wait: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator))
):
    request_id = str(getattr(getattr(request, "state", object()), "request_id", "") or "")
    trace_token = str(getattr(getattr(request, "state", object()), "trace_token", "") or "")
    if wait:
        return await _queueable_run_backup(config_id)
    async def _runner():
        return await _queueable_run_backup(config_id)
    queue_job = await enqueue_operation(
        op_type="backup.run",
        payload={"config_id": config_id},
        runner=_runner,
        requested_by=getattr(current_user, "username", "system"),
        request_id=request_id or None,
        trace_token=trace_token or None,
    )
    return {"status": "accepted", "job": queue_job}

@router.get("/{config_id}/logs", response_model=List[BackupLogResponse])
async def get_backup_logs(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(BackupLog).where(BackupLog.config_id == config_id).order_by(desc(BackupLog.started_at)).limit(50)
    result = await db.execute(query)
    return [BackupLogResponse.from_orm_obj(r) for r in result.scalars().all()]

@router.post("/storage/test")
async def test_storage_destination(
    body: StorageTestRequest,
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    stype = body.storage_type.lower()
    cfg = body.storage_config or {}
    if stype == "local":
        path = body.storage_path or cfg.get("path")
        if not path:
            raise HTTPException(400, "storage_path is required for local storage")
        p = Path(path)
        if not p.exists():
            return {"ok": False, "message": "Path not found"}
        if not os.access(p, os.W_OK):
            return {"ok": False, "message": "Path not writable"}
        return {"ok": True, "message": "Local path reachable"}
    return {"ok": False, "message": "Only local or mounted-path backup storage is currently supported."}

@router.post("/{config_id}/restore")
async def restore_backup(
    config_id: int,
    body: RestoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.operator))
):
    result = await db.execute(select(BackupConfig).where(BackupConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    host_result = await db.execute(select(Host).where(Host.id == config.host_id))
    host = host_result.scalar_one_or_none()
    if not host:
         raise HTTPException(status_code=404, detail="Host not found")

    log_obj = None
    if body.backup_log_id:
        log_res = await db.execute(select(BackupLog).where(BackupLog.id == body.backup_log_id, BackupLog.config_id == config_id))
        log_obj = log_res.scalar_one_or_none()
        if not log_obj:
            raise HTTPException(404, "Backup log not found")
        if log_obj.status != JobStatus.success:
            raise HTTPException(409, "Selected backup has not completed successfully")
    else:
        log_res = await db.execute(
            select(BackupLog)
            .where(BackupLog.config_id == config_id, BackupLog.status == JobStatus.success)
            .order_by(desc(BackupLog.started_at))
            .limit(1)
        )
        log_obj = log_res.scalar_one_or_none()
        if not log_obj:
            raise HTTPException(404, "No successful backups available to restore")

    url = f"http://{host.ip}:{AGENT_PORT}/backup/restore"
    payload = {
        "config_id": config.id,
        "log_id": log_obj.id,
        "storage_type": getattr(config, "storage_type", "local"),
        "storage_config": decrypt_json_field(getattr(config, "storage_config", {}) or {}),
        "storage_path": config.storage_path,
        "source_path": (str(log_obj.output or "").strip() or config.storage_path),
        "target_path": body.target_path or config.source_path,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload, headers=_agent_auth_headers(host))
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to trigger restore: {e}")

    return {"ok": True, "message": "Restore triggered", "log_id": log_obj.id}
