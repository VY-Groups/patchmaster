import os
import shutil
import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from database import get_db
from auth import require_role, get_current_user
from validators import validate_filename
from models.db_models import UserRole, Host
from sqlalchemy import select

router = APIRouter(prefix="/api/packages/local", tags=["packages"])

LOCAL_REPO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "packages")
os.makedirs(LOCAL_REPO_DIR, exist_ok=True)
ARCHIVE_REPO_DIR = os.path.join(LOCAL_REPO_DIR, "archive")
os.makedirs(ARCHIVE_REPO_DIR, exist_ok=True)
WINDOWS_AGENT_PORT = int(os.getenv("PM_WINDOWS_AGENT_PORT", "18080"))
DEFAULT_AGENT_PORT = int(os.getenv("PM_AGENT_PORT", "8080"))
# Linux agents always run on 8080 — same as DEFAULT_AGENT_PORT
LINUX_SAME_IP_AGENT_PORT = int(os.getenv("PM_LINUX_AGENT_PORT_SAME_IP", "8080"))
_GLOBAL_AGENT_API_TOKEN = os.getenv("AGENT_API_TOKEN", "").strip()


def _agent_auth_headers(host: Host | None = None) -> dict:
    token = (getattr(host, "agent_token", None) or "").strip() if host else ""
    if not token:
        token = _GLOBAL_AGENT_API_TOKEN
    return {"Authorization": f"Bearer {token}"} if token else {}


def _windows_candidate_ports() -> list[int]:
    raw = (os.getenv("PM_WINDOWS_AGENT_PORTS") or "").strip()
    if raw:
        ports = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ports.append(int(part))
            except Exception:
                continue
        if ports:
            return list(dict.fromkeys(ports))
    return list(dict.fromkeys([WINDOWS_AGENT_PORT, DEFAULT_AGENT_PORT]))


async def _resolve_host_agent_port(host: Host, db: AsyncSession) -> int:
    os_name = (host.os or "").lower()
    if "win" in os_name:
        return WINDOWS_AGENT_PORT
    same_ip_hosts = (await db.scalars(select(Host).where(Host.ip == host.ip))).all()
    has_windows_peer = any("win" in ((h.os or "").lower()) for h in same_ip_hosts)
    if has_windows_peer:
        return LINUX_SAME_IP_AGENT_PORT
    return DEFAULT_AGENT_PORT


async def _candidate_upload_urls(host: Host, db: AsyncSession) -> list[str]:
    os_name = (host.os or "").lower()
    if "win" in os_name:
        return [f"http://{host.ip}:{p}/offline/upload" for p in _windows_candidate_ports()]
    port = await _resolve_host_agent_port(host, db)
    return [f"http://{host.ip}:{port}/offline/upload"]

@router.get("/")
async def list_local_packages(user=Depends(get_current_user)):
    """List all packages available in the local repository on the Master node."""
    pkgs = []
    for f in os.listdir(LOCAL_REPO_DIR):
        fpath = os.path.join(LOCAL_REPO_DIR, f)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            pkgs.append({
                "name": f,
                "size": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": stat.st_ctime
            })
    return {"packages": pkgs, "count": len(pkgs)}


@router.get("/archive")
async def list_archived_packages(user=Depends(get_current_user)):
    pkgs = []
    for f in os.listdir(ARCHIVE_REPO_DIR):
        fpath = os.path.join(ARCHIVE_REPO_DIR, f)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            pkgs.append({
                "name": f,
                "size": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": stat.st_ctime
            })
    return {"packages": pkgs, "count": len(pkgs)}


@router.get("/stats")
async def repo_stats(user=Depends(get_current_user)):
    def _scan(path: str):
        total = 0
        count = 0
        by_ext = {}
        for fname in os.listdir(path):
            fpath = os.path.join(path, fname)
            if not os.path.isfile(fpath):
                continue
            st = os.stat(fpath)
            total += st.st_size
            count += 1
            ext = os.path.splitext(fname)[1].lower() or "other"
            by_ext.setdefault(ext, {"count": 0, "bytes": 0})
            by_ext[ext]["count"] += 1
            by_ext[ext]["bytes"] += st.st_size
        return {"count": count, "bytes": total, "size_mb": round(total / (1024 * 1024), 2), "by_ext": by_ext}
    active = _scan(LOCAL_REPO_DIR)
    archived = _scan(ARCHIVE_REPO_DIR)
    return {"active": active, "archived": archived, "total_mb": round((active["bytes"] + archived["bytes"]) / (1024 * 1024), 2)}


@router.post("/archive/{filename}")
async def archive_package(filename: str, user=Depends(require_role(UserRole.admin))):
    safe = os.path.basename(filename)
    src = os.path.join(LOCAL_REPO_DIR, safe)
    if not os.path.isfile(src):
        raise HTTPException(404, "Package not found")
    dst = os.path.join(ARCHIVE_REPO_DIR, safe)
    shutil.move(src, dst)
    return {"message": f"Archived {safe}"}


@router.post("/restore/{filename}")
async def restore_package(filename: str, user=Depends(require_role(UserRole.admin))):
    safe = os.path.basename(filename)
    src = os.path.join(ARCHIVE_REPO_DIR, safe)
    if not os.path.isfile(src):
        raise HTTPException(404, "Archived package not found")
    dst = os.path.join(LOCAL_REPO_DIR, safe)
    shutil.move(src, dst)
    return {"message": f"Restored {safe}"}


@router.post("/cleanup")
async def cleanup_repo(body: dict = {}, user=Depends(require_role(UserRole.admin))):
    mode = str(body.get("mode") or "active").lower()
    if mode not in {"active", "archive", "all"}:
        raise HTTPException(400, "mode must be active, archive, or all")
    filenames = [os.path.basename(str(x)) for x in (body.get("filenames") or []) if str(x).strip()]
    dirs = []
    if mode in {"active", "all"}:
        dirs.append(("active", LOCAL_REPO_DIR))
    if mode in {"archive", "all"}:
        dirs.append(("archive", ARCHIVE_REPO_DIR))
    deleted = []
    for label, d in dirs:
        names = filenames or [x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x))]
        for name in names:
            fpath = os.path.join(d, name)
            if os.path.isfile(fpath):
                os.remove(fpath)
                deleted.append({"name": name, "where": label})
    return {"message": "Cleanup done", "deleted_count": len(deleted), "deleted": deleted}

@router.post("/upload")
async def upload_local_package(
    file: UploadFile = File(...),
    user=Depends(require_role(UserRole.admin))
):
    """Upload a package (.deb, .rpm, .msi, .exe) to the local repository."""
    filename = os.path.basename(file.filename)
    dest = os.path.join(LOCAL_REPO_DIR, filename)
    
    # Security check: ensure extension is valid
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".deb", ".rpm", ".msi", ".exe", ".zip", ".gz"):
        raise HTTPException(400, f"Invalid file type: {ext}")

    with open(dest, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"message": f"Package {filename} uploaded successfully.", "filename": filename}

@router.post("/push/{host_id}")
async def push_package_to_agent(
    host_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role(UserRole.operator))
):
    """
    Push a package from the Master node's local repository to an air-gapped agent.
    This uses the agent's /offline/upload endpoint.
    """
    host = await db.get(Host, host_id)
    if host is None:
        raise HTTPException(404, "Host not found")
    
    # F13: filename comes from the request - never join it raw.
    name_check = validate_filename(filename)
    if not name_check.is_valid:
        raise HTTPException(400, name_check.message)
    pkg_path = os.path.join(LOCAL_REPO_DIR, filename)
    if not os.path.exists(pkg_path):
        raise HTTPException(404, "Package not found in local repository")

    agent_urls = await _candidate_upload_urls(host, db)
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(pkg_path, "rb") as f:
                resp = None
                last_error = ""
                for url in agent_urls:
                    f.seek(0)
                    files = {"file": (filename, f)}
                    resp = await client.post(url, files=files, headers=_agent_auth_headers(host))
                    if resp.status_code == 200:
                        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
                        return {
                            "message": f"Successfully pushed {filename} to agent on {host.hostname or host.ip}.",
                            "details": payload,
                            "agent_url": url,
                        }
                    last_error = f"{url} status={resp.status_code}"
            if resp is None:
                raise HTTPException(502, "Agent upload failed on all candidate ports")
            agent_payload = {}
            try:
                agent_payload = resp.json()
            except Exception:
                agent_payload = {"raw": (resp.text or "")[:1500]}
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Agent rejected package push",
                    "status_code": resp.status_code,
                    "agent_response": agent_payload,
                    "candidate_urls": agent_urls,
                    "last_error": last_error,
                    "host_id": host.id,
                    "host_ip": host.ip,
                    "filename": filename,
                },
            )
    except HTTPException:
        raise
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Unable to connect to agent",
                "reason": str(exc),
                "host_id": host.id,
                "host_ip": host.ip,
                "filename": filename,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to push package to agent",
                "reason": str(e),
                "host_id": host.id,
                "host_ip": host.ip,
                "filename": filename,
            },
        )

@router.delete("/{filename}")
async def delete_local_package(
    filename: str,
    archived: bool = False,
    user=Depends(require_role(UserRole.admin))
):
    """Delete a package from the local repository."""
    base = ARCHIVE_REPO_DIR if archived else LOCAL_REPO_DIR
    fpath = os.path.join(base, filename)
    if os.path.exists(fpath) and os.path.isfile(fpath):
        os.remove(fpath)
        return {"message": f"Deleted {filename}"}
    raise HTTPException(404, "Package not found")
