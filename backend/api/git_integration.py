"""Git Repository Integration API — GitLab, Bitbucket, GitBucket."""
import os
import secrets
from datetime import datetime

def _utcnow():
    """Timezone-aware UTC now as naive datetime for DB storage."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
from typing import Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from auth import get_current_user, require_role
from api.cicd_secrets import decrypt_text_field, encrypt_text_field
from models.db_models import GitRepository, User, UserRole

router = APIRouter(prefix="/api/git", tags=["git"])

PROVIDERS = ("gitlab", "bitbucket", "gitbucket")

# TLS verification: opt-out only — set GIT_TLS_VERIFY=false to disable (e.g. self-signed CA labs).
# Defaults to True (verify certs).
_GIT_TLS_VERIFY = os.environ.get("GIT_TLS_VERIFY", "true").strip().lower() != "false"

# ── Provider API helpers ──

_DEFAULT_URLS = {
    "gitlab": "https://gitlab.com",
    "bitbucket": "https://api.bitbucket.org/2.0",
    "gitbucket": "",  # self-hosted, user provides
}


def _headers(repo: GitRepository) -> dict:
    """Build auth headers per provider."""
    h = {"Accept": "application/json"}
    token = decrypt_text_field(repo.auth_token)
    if not token:
        return h
    if repo.provider == "gitlab":
        h["PRIVATE-TOKEN"] = token
    elif repo.provider == "bitbucket":
        h["Authorization"] = f"Bearer {token}"
    elif repo.provider == "gitbucket":
        h["Authorization"] = f"token {token}"
    return h


async def _api_get(repo: GitRepository, path: str, params: dict = None) -> dict:
    """Generic GET against the provider API."""
    base = repo.server_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=15, verify=_GIT_TLS_VERIFY) as client:
        resp = await client.get(url, headers=_headers(repo), params=params)
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, f"Provider API error: {resp.text[:300]}")
        return resp.json()


async def _api_post(repo: GitRepository, path: str, json_body: dict = None) -> dict:
    base = repo.server_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=15, verify=_GIT_TLS_VERIFY) as client:
        resp = await client.post(url, headers=_headers(repo), json=json_body)
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, f"Provider API error: {resp.text[:300]}")
        return resp.json()


async def _api_delete(repo: GitRepository, path: str) -> bool:
    base = repo.server_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=15, verify=_GIT_TLS_VERIFY) as client:
        resp = await client.delete(url, headers=_headers(repo))
        return resp.status_code < 400


# ── Provider-specific path builders ──

def _repo_path(repo: GitRepository) -> str:
    """Return the API path prefix for this repo."""
    owner_repo = repo.repo_full_name
    if repo.provider == "gitlab":
        encoded = quote(owner_repo, safe="")
        return f"/api/v4/projects/{encoded}"
    elif repo.provider == "bitbucket":
        return f"/repositories/{owner_repo}"
    elif repo.provider == "gitbucket":
        return f"/api/v3/repos/{owner_repo}"
    return ""


# ── Schemas ──

class RepoCreate(BaseModel):
    name: str
    provider: str  # gitlab, bitbucket, gitbucket
    server_url: str = ""
    repo_full_name: str  # owner/repo
    default_branch: str = "main"
    auth_token: str = ""

class RepoUpdate(BaseModel):
    name: Optional[str] = None
    server_url: Optional[str] = None
    repo_full_name: Optional[str] = None
    default_branch: Optional[str] = None
    auth_token: Optional[str] = None
    is_active: Optional[bool] = None


class RepoDiscoverRequest(BaseModel):
    provider: str
    server_url: str = ""
    token: str = ""


def _repo_to_dict(r: GitRepository) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "provider": r.provider,
        "server_url": r.server_url,
        "repo_full_name": r.repo_full_name,
        "default_branch": r.default_branch,
        "has_token": bool(r.auth_token),
        # webhook_secret intentionally omitted — use /api/git/repos/{id}/webhook-secret
        "webhook_id": r.webhook_id or "",
        "is_active": r.is_active,
        "last_synced": r.last_synced.isoformat() if r.last_synced else None,
        "repo_meta": r.repo_meta or {},
        "created_by": r.created_by or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


# ── CRUD ──

@router.get("/repos")
async def list_repos(db: AsyncSession = Depends(get_db), user: User = Depends(require_role(UserRole.admin, UserRole.operator))):
    result = await db.execute(select(GitRepository).order_by(GitRepository.created_at.desc()))
    return [_repo_to_dict(r) for r in result.scalars().all()]


@router.get("/repos/{repo_id}/webhook-secret")
async def get_repo_webhook_secret(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Return the webhook secret for a repo. Requires admin/operator."""
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")
    return {"id": repo_id, "webhook_secret": decrypt_text_field(repo.webhook_secret)}


@router.post("/repos", status_code=201)
async def create_repo(
    body: RepoCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    if body.provider not in PROVIDERS:
        raise HTTPException(400, f"provider must be one of: {', '.join(PROVIDERS)}")

    server_url = body.server_url.rstrip("/") if body.server_url else _DEFAULT_URLS.get(body.provider, "")
    if not server_url:
        raise HTTPException(400, "server_url is required for this provider")

    repo = GitRepository(
        name=body.name,
        provider=body.provider,
        server_url=server_url,
        repo_full_name=body.repo_full_name.strip(),
        default_branch=body.default_branch or "main",
        auth_token=encrypt_text_field(body.auth_token),
        webhook_secret=encrypt_text_field(secrets.token_hex(24)),
        created_by=user.username,
    )
    db.add(repo)
    await db.flush()
    await db.commit()
    await db.refresh(repo)

    # Try to sync repo metadata
    try:
        meta = await _fetch_repo_meta(repo)
        repo.repo_meta = meta
        repo.last_synced = _utcnow()
    except Exception:
        pass

    await db.flush()
    await db.commit()
    await db.refresh(repo)
    return _repo_to_dict(repo)


@router.put("/repos/{repo_id}")
async def update_repo(
    repo_id: int,
    body: RepoUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")
    for f in ("name", "server_url", "repo_full_name", "default_branch", "auth_token", "is_active"):
        val = getattr(body, f, None)
        if val is not None:
            if f == "server_url":
                val = val.rstrip("/")
            elif f == "auth_token":
                val = encrypt_text_field(val)
            setattr(repo, f, val)
    repo.updated_at = _utcnow()
    await db.flush()
    await db.commit()
    await db.refresh(repo)
    return _repo_to_dict(repo)


@router.delete("/repos/{repo_id}")
async def delete_repo(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")
    await db.delete(repo)
    await db.commit()
    return {"ok": True}

@router.post("/repos/{repo_id}/test")
async def test_repo_connection(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")
    try:
        meta = await _fetch_repo_meta(repo)
        repo.repo_meta = meta
        repo.last_synced = _utcnow()
        await db.flush()
        await db.commit()
        return {"ok": True, "message": f"Connected — {meta.get('full_name', repo.repo_full_name)}", "meta": meta}
    except Exception as e:
        return {"ok": False, "message": f"Connection failed: {str(e)}"}


# ── Sync repo metadata ──

async def _fetch_repo_meta(repo: GitRepository) -> dict:
    path = _repo_path(repo)
    data = await _api_get(repo, path)

    if repo.provider == "gitlab":
        return {
            "full_name": data.get("path_with_namespace", ""),
            "description": data.get("description", "") or "",
            "language": "",
            "visibility": data.get("visibility", ""),
            "stars": data.get("star_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "default_branch": data.get("default_branch", "main"),
            "html_url": data.get("web_url", ""),
            "clone_url": data.get("http_url_to_repo", ""),
            "updated_at": data.get("last_activity_at", ""),
        }
    elif repo.provider == "bitbucket":
        return {
            "full_name": data.get("full_name", ""),
            "description": data.get("description", "") or "",
            "language": data.get("language", ""),
            "visibility": "private" if data.get("is_private") else "public",
            "stars": 0,
            "forks": 0,
            "open_issues": 0,
            "default_branch": data.get("mainbranch", {}).get("name", "main"),
            "html_url": data.get("links", {}).get("html", {}).get("href", ""),
            "clone_url": next((l["href"] for l in data.get("links", {}).get("clone", []) if l.get("name") == "https"), ""),
            "updated_at": data.get("updated_on", ""),
        }
    elif repo.provider == "gitbucket":
        return {
            "full_name": data.get("full_name", ""),
            "description": data.get("description", "") or "",
            "language": data.get("language", ""),
            "visibility": "private" if data.get("private") else "public",
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "default_branch": data.get("default_branch", "master"),
            "html_url": data.get("html_url", ""),
            "clone_url": data.get("clone_url", ""),
            "updated_at": data.get("updated_at", ""),
        }
    return data


@router.post("/repos/{repo_id}/sync")
async def sync_repo(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")
    meta = await _fetch_repo_meta(repo)
    repo.repo_meta = meta
    repo.last_synced = _utcnow()
    if meta.get("default_branch"):
        repo.default_branch = meta["default_branch"]
    await db.flush()
    await db.commit()
    return {"ok": True, "meta": meta}


# ── Branches ──

@router.get("/repos/{repo_id}/branches")
async def list_branches(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    path = _repo_path(repo)
    if repo.provider == "gitlab":
        data = await _api_get(repo, f"{path}/repository/branches", {"per_page": "100"})
        return [{"name": b["name"], "sha": b["commit"]["id"], "protected": b.get("protected", False)} for b in data]
    elif repo.provider == "bitbucket":
        data = await _api_get(repo, f"{path}/refs/branches", {"pagelen": "100"})
        return [{"name": b["name"], "sha": b["target"]["hash"], "protected": False} for b in data.get("values", [])]
    elif repo.provider == "gitbucket":
        data = await _api_get(repo, f"{path}/branches")
        return [{"name": b["name"], "sha": b["commit"]["sha"], "protected": b.get("protected", False)} for b in data]
    return []


# ── Commits ──

@router.get("/repos/{repo_id}/commits")
async def list_commits(
    repo_id: int,
    branch: str = None,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    path = _repo_path(repo)
    ref = branch or repo.default_branch
    safe_limit = min(limit, 100)

    if repo.provider == "gitlab":
        data = await _api_get(repo, f"{path}/repository/commits", {"ref_name": ref, "per_page": str(safe_limit)})
        return [{
            "sha": c["short_id"], "full_sha": c["id"],
            "message": c["title"],
            "author": c["author_name"],
            "date": c["committed_date"],
            "url": c.get("web_url", ""),
        } for c in data]
    elif repo.provider == "bitbucket":
        params = {"pagelen": str(safe_limit)}
        if ref:
            params["include"] = ref
        data = await _api_get(repo, f"{path}/commits", params)
        return [{
            "sha": c["hash"][:8], "full_sha": c["hash"],
            "message": c.get("message", "").split("\n")[0],
            "author": c.get("author", {}).get("raw", ""),
            "date": c.get("date", ""),
            "url": c.get("links", {}).get("html", {}).get("href", ""),
        } for c in data.get("values", [])]
    elif repo.provider == "gitbucket":
        data = await _api_get(repo, f"{path}/commits", {"sha": ref, "per_page": str(safe_limit)})
        return [{
            "sha": c["sha"][:8], "full_sha": c["sha"],
            "message": c["commit"]["message"].split("\n")[0],
            "author": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
            "url": c.get("html_url", ""),
        } for c in data]
    return []


# ── Pull Requests / Merge Requests ──

@router.get("/repos/{repo_id}/pulls")
async def list_pull_requests(
    repo_id: int,
    state: str = "open",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    path = _repo_path(repo)

    if repo.provider == "gitlab":
        gl_state = {"open": "opened", "closed": "closed", "merged": "merged", "all": "all"}.get(state, "opened")
        data = await _api_get(repo, f"{path}/merge_requests", {"state": gl_state, "per_page": "50"})
        return [{
            "number": mr["iid"], "title": mr["title"],
            "state": mr["state"], "author": mr["author"]["username"],
            "branch": mr["source_branch"], "target": mr["target_branch"],
            "created_at": mr["created_at"], "updated_at": mr["updated_at"],
            "url": mr["web_url"], "mergeable": mr.get("merge_status") == "can_be_merged",
            "labels": mr.get("labels", []),
        } for mr in data]
    elif repo.provider == "bitbucket":
        bb_state = {"open": "OPEN", "closed": "DECLINED", "merged": "MERGED"}.get(state, "OPEN")
        data = await _api_get(repo, f"{path}/pullrequests", {"state": bb_state, "pagelen": "50"})
        return [{
            "number": pr["id"], "title": pr["title"],
            "state": pr["state"].lower(), "author": pr["author"]["display_name"],
            "branch": pr["source"]["branch"]["name"],
            "target": pr["destination"]["branch"]["name"],
            "created_at": pr["created_on"], "updated_at": pr["updated_on"],
            "url": pr.get("links", {}).get("html", {}).get("href", ""),
            "mergeable": None, "labels": [],
        } for pr in data.get("values", [])]
    elif repo.provider == "gitbucket":
        data = await _api_get(repo, f"{path}/pulls", {"state": state, "per_page": "50"})
        return [{
            "number": pr["number"], "title": pr["title"],
            "state": pr["state"], "author": pr["user"]["login"],
            "branch": pr["head"]["ref"], "target": pr["base"]["ref"],
            "created_at": pr["created_at"], "updated_at": pr["updated_at"],
            "url": pr.get("html_url", ""), "mergeable": pr.get("mergeable"),
            "labels": [l["name"] for l in pr.get("labels", [])],
        } for pr in data]
    return []


# ── Tags / Releases ──

@router.get("/repos/{repo_id}/tags")
async def list_tags(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    path = _repo_path(repo)

    if repo.provider == "gitlab":
        data = await _api_get(repo, f"{path}/repository/tags", {"per_page": "50"})
        return [{"name": t["name"], "sha": t["commit"]["short_id"]} for t in data]
    elif repo.provider == "bitbucket":
        data = await _api_get(repo, f"{path}/refs/tags", {"pagelen": "50"})
        return [{"name": t["name"], "sha": t["target"]["hash"][:8]} for t in data.get("values", [])]
    elif repo.provider == "gitbucket":
        data = await _api_get(repo, f"{path}/tags")
        return [{"name": t["name"], "sha": t["commit"]["sha"][:8]} for t in data]
    return []


# ── File browser ──

@router.get("/repos/{repo_id}/tree")
async def browse_tree(
    repo_id: int,
    path: str = "",
    ref: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Browse repository file tree."""
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    rp = _repo_path(repo)
    branch = ref or repo.default_branch

    if repo.provider == "gitlab":
        data = await _api_get(repo, f"{rp}/repository/tree", {"ref": branch, "path": path, "per_page": "100"})
        return [{"name": f["name"], "type": "dir" if f["type"] == "tree" else "file", "size": 0, "path": f["path"]} for f in data]
    elif repo.provider == "bitbucket":
        api_path = f"{rp}/src/{branch}/{path}" if path else f"{rp}/src/{branch}/"
        data = await _api_get(repo, api_path, {"pagelen": "100"})
        return [{"name": f["path"].split("/")[-1], "type": f["type"].replace("commit_directory", "dir").replace("commit_file", "file"), "size": f.get("size", 0), "path": f["path"]} for f in data.get("values", [])]
    elif repo.provider == "gitbucket":
        api_path = f"{rp}/contents/{path}" if path else f"{rp}/contents"
        data = await _api_get(repo, api_path, {"ref": branch})
        if isinstance(data, list):
            return [{"name": f["name"], "type": f["type"], "size": f.get("size", 0), "path": f["path"]} for f in data]
        return [{"name": data["name"], "type": data["type"], "size": data.get("size", 0), "path": data["path"]}]
    return []


# ── View file content ──

@router.get("/repos/{repo_id}/file")
async def get_file_content(
    repo_id: int,
    path: str,
    ref: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Get raw file content from repo."""
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    rp = _repo_path(repo)
    branch = ref or repo.default_branch

    if repo.provider == "gitlab":
        safe_path = quote(path, safe="")
        data = await _api_get(repo, f"{rp}/repository/files/{safe_path}", {"ref": branch})
        import base64
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return {"path": path, "content": content, "size": data.get("size", 0), "sha": data.get("blob_id", "")[:8]}
    elif repo.provider == "bitbucket":
        base = repo.server_url.rstrip("/")
        url = f"{base}{rp}/src/{branch}/{path}"
        async with httpx.AsyncClient(timeout=15, verify=_GIT_TLS_VERIFY) as client:
            resp = await client.get(url, headers=_headers(repo))
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, "File not found")
            return {"path": path, "content": resp.text[:100000], "size": len(resp.text), "sha": ""}
    elif repo.provider == "gitbucket":
        data = await _api_get(repo, f"{rp}/contents/{path}", {"ref": branch})
        import base64
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace") if data.get("encoding") == "base64" else data.get("content", "")
        return {"path": path, "content": content, "size": data.get("size", 0), "sha": data.get("sha", "")[:8]}
    return {"path": path, "content": "", "size": 0, "sha": ""}


# ── Webhook management ──

@router.post("/repos/{repo_id}/webhook/register")
async def register_webhook(
    repo_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """Register a Patch-SecOps Solution webhook on the remote Git provider."""
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    base_url = str(request.base_url).rstrip("/")
    hook_url = f"{base_url}/api/git/webhook/{repo_id}"
    path = _repo_path(repo)

    try:
        webhook_secret = decrypt_text_field(repo.webhook_secret)
        if repo.provider == "gitlab":
            data = await _api_post(repo, f"{path}/hooks", {
                "url": hook_url, "token": webhook_secret,
                "push_events": True, "merge_requests_events": True, "pipeline_events": True,
            })
            repo.webhook_id = str(data.get("id", ""))
        elif repo.provider == "bitbucket":
            data = await _api_post(repo, f"{path}/hooks", {
                "description": "Patch-SecOps Solution webhook",
                "url": hook_url, "active": True,
                "events": ["repo:push", "pullrequest:created", "pullrequest:updated"],
            })
            repo.webhook_id = data.get("uuid", "")
        elif repo.provider == "gitbucket":
            data = await _api_post(repo, f"{path}/hooks", {
                "name": "web",
                "config": {"url": hook_url, "content_type": "json", "secret": webhook_secret},
                "events": ["push", "pull_request"],
                "active": True,
            })
            repo.webhook_id = str(data.get("id", ""))

        await db.flush()
        await db.commit()
        return {"ok": True, "message": "Webhook registered", "webhook_id": repo.webhook_id}
    except Exception as e:
        return {"ok": False, "message": f"Failed: {str(e)}"}


@router.delete("/repos/{repo_id}/webhook")
async def remove_webhook(
    repo_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo or not repo.webhook_id:
        raise HTTPException(404, "Repository or webhook not found")

    path = _repo_path(repo)
    try:
        if repo.provider == "gitlab":
            await _api_delete(repo, f"{path}/hooks/{repo.webhook_id}")
        elif repo.provider == "bitbucket":
            await _api_delete(repo, f"{path}/hooks/{repo.webhook_id}")
        elif repo.provider == "gitbucket":
            await _api_delete(repo, f"{path}/hooks/{repo.webhook_id}")
        repo.webhook_id = ""
        await db.flush()
        await db.commit()
        return {"ok": True, "message": "Webhook removed"}
    except Exception as e:
        return {"ok": False, "message": f"Failed: {str(e)}"}


# ── Incoming webhook from Git providers ──

@router.post("/webhook/{repo_id}")
async def receive_git_webhook(
    repo_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive push/PR/pipeline events from Git providers."""
    import hashlib, hmac as hmac_mod, json

    result = await db.execute(select(GitRepository).where(GitRepository.id == repo_id))
    repo = result.scalars().first()
    if not repo:
        raise HTTPException(404, "Repository not found")

    body_bytes = await request.body()

    # Validate signature
    webhook_secret = decrypt_text_field(repo.webhook_secret)
    if webhook_secret:
        sig = request.headers.get("X-Hub-Signature-256", "")
        gl_token = request.headers.get("X-Gitlab-Token", "")
        if sig:
            expected = "sha256=" + hmac_mod.new(webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
            if not hmac_mod.compare_digest(sig, expected):
                raise HTTPException(403, "Invalid signature")
        elif gl_token:
            if gl_token != webhook_secret:
                raise HTTPException(403, "Invalid token")

    try:
        payload = json.loads(body_bytes)
    except Exception:
        payload = {}

    event_type = request.headers.get("X-Gitlab-Event", "push")

    return {
        "ok": True,
        "event": event_type,
        "repo": repo.repo_full_name,
        "received_at": _utcnow().isoformat(),
    }


# ── User repos discovery (list repos the token has access to) ──

@router.post("/discover")
async def discover_repos(
    body: RepoDiscoverRequest,
    user: User = Depends(require_role(UserRole.admin, UserRole.operator)),
):
    """List repos accessible by the provided token."""
    provider = body.provider
    server_url = body.server_url
    token = body.token
    if provider not in PROVIDERS:
        raise HTTPException(400, f"provider must be one of: {', '.join(PROVIDERS)}")

    base = server_url.rstrip("/") if server_url else _DEFAULT_URLS.get(provider, "")
    if not base:
        raise HTTPException(400, "server_url required")

    headers = {"Accept": "application/json"}
    if provider == "gitlab":
        headers["PRIVATE-TOKEN"] = token
        url = f"{base}/api/v4/projects?membership=true&per_page=100&order_by=updated_at"
    elif provider == "bitbucket":
        headers["Authorization"] = f"Bearer {token}"
        url = f"{base}/repositories?role=member&pagelen=100"
    elif provider == "gitbucket":
        headers["Authorization"] = f"token {token}"
        url = f"{base}/api/v3/user/repos?per_page=100"
    else:
        raise HTTPException(400, "Unsupported provider")

    try:
        async with httpx.AsyncClient(timeout=15, verify=_GIT_TLS_VERIFY) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                return {"ok": False, "repos": [], "message": f"API returned {resp.status_code}"}
            data = resp.json()

        repos = []
        items = data if isinstance(data, list) else data.get("values", data.get("items", []))
        for r in items[:100]:
            if provider == "gitbucket":
                repos.append({
                    "full_name": r.get("full_name", ""),
                    "description": r.get("description", "") or "",
                    "private": r.get("private", False),
                    "default_branch": r.get("default_branch", "main"),
                    "html_url": r.get("html_url", ""),
                })
            elif provider == "gitlab":
                repos.append({
                    "full_name": r.get("path_with_namespace", ""),
                    "description": r.get("description", "") or "",
                    "private": r.get("visibility") == "private",
                    "default_branch": r.get("default_branch", "main"),
                    "html_url": r.get("web_url", ""),
                })
            elif provider == "bitbucket":
                repos.append({
                    "full_name": r.get("full_name", ""),
                    "description": r.get("description", "") or "",
                    "private": r.get("is_private", False),
                    "default_branch": r.get("mainbranch", {}).get("name", "main"),
                    "html_url": r.get("links", {}).get("html", {}).get("href", ""),
                })
        return {"ok": True, "repos": repos, "message": f"Found {len(repos)} repositories"}
    except Exception as e:
        return {"ok": False, "repos": [], "message": str(e)}
