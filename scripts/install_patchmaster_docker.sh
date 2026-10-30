#!/usr/bin/env bash
# One-shot Docker installer for Patch-SecOps Solution production.

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AUTHORITY_ENV_FILE="${PATCHMASTER_SHARED_AUTHORITY_ENV:-${ROOT}/.license-authority.env}"
PACKAGED_AUTHORITY_ENV="${ROOT}/patchmaster-license-authority.env"
PACKAGED_PUBLIC_AUTHORITY_ENV="${ROOT}/patchmaster-license-public.env"
EXPLICIT_LICENSE_SIGN_KEY="${LICENSE_SIGN_KEY:-}"
EXPLICIT_LICENSE_VERIFY_PUBLIC_KEY="${LICENSE_VERIFY_PUBLIC_KEY:-}"
EXPLICIT_LICENSE_DECRYPT_PRIVATE_KEY="${LICENSE_DECRYPT_PRIVATE_KEY:-}"
EXPLICIT_LICENSE_ENCRYPT_PUBLIC_KEY="${LICENSE_ENCRYPT_PUBLIC_KEY:-}"

if ! command -v docker >/dev/null 2>&1; then
  err "Docker is not installed."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  err "docker compose is not available."
  exit 1
fi

SERVER_IP="${SERVER_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
[[ -z "${SERVER_IP}" ]] && SERVER_IP="127.0.0.1"
FRONTEND_PORT="${FRONTEND_PORT:-80}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
POSTGRES_USER="${POSTGRES_USER:-patchmaster}"
POSTGRES_DB="${POSTGRES_DB:-patchmaster}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(python3 -c "import secrets; print(secrets.token_hex(16))")}"
JWT_SECRET="${JWT_SECRET:-$(python3 -c "import secrets; print(secrets.token_hex(32))")}"
LICENSE_SIGN_KEY="${LICENSE_SIGN_KEY:-}"
PM_SECRET_KEY="${PM_SECRET_KEY:-$(python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")}"
GF_ADMIN_USER="${GF_ADMIN_USER:-admin}"
GF_ADMIN_PASSWORD="${GF_ADMIN_PASSWORD:-$(python3 -c "import secrets; print('GfA!7' + secrets.token_hex(4))")}"
PM_ADMIN_USER="${PM_ADMIN_USER:-admin}"
PM_ADMIN_PASSWORD="${PM_ADMIN_PASSWORD:-$(python3 -c "import secrets; print('PmA!7' + secrets.token_hex(4))")}"
PM_SMOKE_USER="${PM_SMOKE_USER:-qa-smoke}"
PM_SMOKE_PASSWORD="${PM_SMOKE_PASSWORD:-$(python3 -c "import secrets; print('PmS!7' + secrets.token_hex(4))")}"
PLAYWRIGHT_REAL_BASE_URL="${PLAYWRIGHT_REAL_BASE_URL:-http://${SERVER_IP}:${FRONTEND_PORT}}"
PLAYWRIGHT_REAL_USER="${PLAYWRIGHT_REAL_USER:-${PM_SMOKE_USER}}"
PLAYWRIGHT_REAL_PASSWORD="${PLAYWRIGHT_REAL_PASSWORD:-${PM_SMOKE_PASSWORD}}"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright}"

ENV_FILE="${ROOT}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "${ROOT}/.env.production" "$ENV_FILE"
fi

mkdir -p "${ROOT}/reports"
chmod 0777 "${ROOT}/reports" 2>/dev/null || true

EXPLICIT_LICENSE_SIGN_KEY_ENV="$EXPLICIT_LICENSE_SIGN_KEY" EXPLICIT_LICENSE_VERIFY_PUBLIC_KEY_ENV="$EXPLICIT_LICENSE_VERIFY_PUBLIC_KEY" EXPLICIT_LICENSE_DECRYPT_PRIVATE_KEY_ENV="$EXPLICIT_LICENSE_DECRYPT_PRIVATE_KEY" EXPLICIT_LICENSE_ENCRYPT_PUBLIC_KEY_ENV="$EXPLICIT_LICENSE_ENCRYPT_PUBLIC_KEY" python3 - <<PY
import os
from pathlib import Path

path = Path(r"${ENV_FILE}")
text = path.read_text(encoding="utf-8")
lines = text.splitlines()
values = {}
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    value = value.split("#")[0].strip()
    values[key.strip()] = value

authority_path = Path(r"${AUTHORITY_ENV_FILE}")
packaged_authority_path = Path(r"${PACKAGED_AUTHORITY_ENV}")
packaged_public_authority_path = Path(r"${PACKAGED_PUBLIC_AUTHORITY_ENV}")
authority_values = {}
if authority_path.exists():
    for line in authority_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        authority_values[key.strip()] = value.split("#")[0].strip()

packaged_authority_values = {}
if packaged_authority_path.exists():
    for line in packaged_authority_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        packaged_authority_values[key.strip()] = value.split("#")[0].strip()

packaged_public_authority_values = {}
if packaged_public_authority_path.exists():
    for line in packaged_public_authority_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        packaged_public_authority_values[key.strip()] = value.split("#")[0].strip()

def is_placeholder(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return True
    lowered = value.lower()
    if lowered in {"change-me", "replace-me"}:
        return True
    if lowered.startswith("changeme-") or lowered.startswith("replace-me"):
        return True
    if value == "PatchMaster-License-SignKey-2026-Secure":
        return True
    return False

def resolve(key: str, suggested: str) -> str:
    current = values.get(key, "").strip()
    if current and not is_placeholder(current):
        return current
    return suggested

def resolve_license_sign_key(suggested: str) -> str:
    explicit = os.environ.get("EXPLICIT_LICENSE_SIGN_KEY_ENV", "").strip()
    if explicit and not is_placeholder(explicit):
        return explicit
    if resolve_license_verify_public_key():
        current = values.get("LICENSE_SIGN_KEY", "").strip()
        return "" if is_placeholder(current) else current
    packaged = packaged_authority_values.get("LICENSE_SIGN_KEY", "").strip()
    if packaged and not is_placeholder(packaged):
        return packaged
    shared = authority_values.get("LICENSE_SIGN_KEY", "").strip()
    if shared and not is_placeholder(shared):
        return shared
    current = values.get("LICENSE_SIGN_KEY", "").strip()
    if current and not is_placeholder(current):
        return current
    return suggested

def resolve_license_verify_public_key() -> str:
    explicit = os.environ.get("EXPLICIT_LICENSE_VERIFY_PUBLIC_KEY_ENV", "").strip()
    if explicit:
        return explicit
    packaged_public = packaged_public_authority_values.get("LICENSE_VERIFY_PUBLIC_KEY", "").strip()
    if packaged_public:
        return packaged_public
    packaged = packaged_authority_values.get("LICENSE_VERIFY_PUBLIC_KEY", "").strip()
    if packaged:
        return packaged
    shared = authority_values.get("LICENSE_VERIFY_PUBLIC_KEY", "").strip()
    if shared:
        return shared
    return values.get("LICENSE_VERIFY_PUBLIC_KEY", "").strip()

def resolve_license_decrypt_private_key() -> str:
    explicit = os.environ.get("EXPLICIT_LICENSE_DECRYPT_PRIVATE_KEY_ENV", "").strip()
    if explicit:
        return explicit
    packaged_public = packaged_public_authority_values.get("LICENSE_DECRYPT_PRIVATE_KEY", "").strip()
    if packaged_public:
        return packaged_public
    packaged = packaged_authority_values.get("LICENSE_DECRYPT_PRIVATE_KEY", "").strip()
    if packaged:
        return packaged
    shared = authority_values.get("LICENSE_DECRYPT_PRIVATE_KEY", "").strip()
    if shared:
        return shared
    return values.get("LICENSE_DECRYPT_PRIVATE_KEY", "").strip()

def resolve_license_encrypt_public_key() -> str:
    explicit = os.environ.get("EXPLICIT_LICENSE_ENCRYPT_PUBLIC_KEY_ENV", "").strip()
    if explicit:
        return explicit
    packaged_public = packaged_public_authority_values.get("LICENSE_ENCRYPT_PUBLIC_KEY", "").strip()
    if packaged_public:
        return packaged_public
    packaged = packaged_authority_values.get("LICENSE_ENCRYPT_PUBLIC_KEY", "").strip()
    if packaged:
        return packaged
    shared = authority_values.get("LICENSE_ENCRYPT_PUBLIC_KEY", "").strip()
    if shared:
        return shared
    return values.get("LICENSE_ENCRYPT_PUBLIC_KEY", "").strip()

updates = {
    "SERVER_IP": resolve("SERVER_IP", "${SERVER_IP}"),
    "FRONTEND_PORT": resolve("FRONTEND_PORT", "${FRONTEND_PORT}"),
    "BACKEND_PORT": resolve("BACKEND_PORT", "${BACKEND_PORT}"),
    "POSTGRES_USER": resolve("POSTGRES_USER", "${POSTGRES_USER}"),
    "POSTGRES_DB": resolve("POSTGRES_DB", "${POSTGRES_DB}"),
    "POSTGRES_PASSWORD": resolve("POSTGRES_PASSWORD", "${POSTGRES_PASSWORD}"),
    "JWT_SECRET": resolve("JWT_SECRET", "${JWT_SECRET}"),
    "LICENSE_SIGN_KEY": resolve_license_sign_key("${LICENSE_SIGN_KEY}"),
    "LICENSE_VERIFY_PUBLIC_KEY": resolve_license_verify_public_key(),
    "LICENSE_DECRYPT_PRIVATE_KEY": resolve_license_decrypt_private_key(),
    "LICENSE_ENCRYPT_PUBLIC_KEY": resolve_license_encrypt_public_key(),
    "PM_SECRET_KEY": resolve("PM_SECRET_KEY", "${PM_SECRET_KEY}"),
    "GF_ADMIN_USER": resolve("GF_ADMIN_USER", "${GF_ADMIN_USER}"),
    "GF_ADMIN_PASSWORD": resolve("GF_ADMIN_PASSWORD", "${GF_ADMIN_PASSWORD}"),
    "PM_ADMIN_USER": resolve("PM_ADMIN_USER", "${PM_ADMIN_USER}"),
    "PM_ADMIN_PASSWORD": resolve("PM_ADMIN_PASSWORD", "${PM_ADMIN_PASSWORD}"),
    "PM_SMOKE_USER": resolve("PM_SMOKE_USER", "${PM_SMOKE_USER}"),
    "PM_SMOKE_PASSWORD": resolve("PM_SMOKE_PASSWORD", "${PM_SMOKE_PASSWORD}"),
    "PLAYWRIGHT_REAL_BASE_URL": resolve("PLAYWRIGHT_REAL_BASE_URL", "${PLAYWRIGHT_REAL_BASE_URL}"),
    "PLAYWRIGHT_REAL_USER": resolve("PLAYWRIGHT_REAL_USER", "${PLAYWRIGHT_REAL_USER}"),
    "PLAYWRIGHT_REAL_PASSWORD": resolve("PLAYWRIGHT_REAL_PASSWORD", "${PLAYWRIGHT_REAL_PASSWORD}"),
    "PLAYWRIGHT_BROWSERS_PATH": resolve("PLAYWRIGHT_BROWSERS_PATH", "${PLAYWRIGHT_BROWSERS_PATH}"),
}

out = []
seen = set()
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    out.append(line)

for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
authority_path.parent.mkdir(parents=True, exist_ok=True)
authority_lines = []
if updates["LICENSE_SIGN_KEY"]:
    authority_lines.append(f"LICENSE_SIGN_KEY={updates['LICENSE_SIGN_KEY']}")
if updates["LICENSE_VERIFY_PUBLIC_KEY"]:
    authority_lines.append(f"LICENSE_VERIFY_PUBLIC_KEY={updates['LICENSE_VERIFY_PUBLIC_KEY']}")
if updates["LICENSE_DECRYPT_PRIVATE_KEY"]:
    authority_lines.append(f"LICENSE_DECRYPT_PRIVATE_KEY={updates['LICENSE_DECRYPT_PRIVATE_KEY']}")
if updates["LICENSE_ENCRYPT_PUBLIC_KEY"]:
    authority_lines.append(f"LICENSE_ENCRYPT_PUBLIC_KEY={updates['LICENSE_ENCRYPT_PUBLIC_KEY']}")
authority_path.write_text("\n".join(authority_lines).rstrip() + "\n", encoding="utf-8")
for candidate in (path, authority_path):
    try:
        os.chmod(candidate, 0o600)
    except OSError:
        pass
print(f"Updated {path}")
PY

log "Starting Docker production stack..."
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo -e "${BLUE}Patch-SecOps Solution Docker install complete.${NC}"
echo "  Frontend:   http://${SERVER_IP}:${FRONTEND_PORT}"
echo "  Backend:    http://127.0.0.1:${BACKEND_PORT}/api/health"
echo "  Admin user: ${PM_ADMIN_USER}"
echo "  Admin pass: ${PM_ADMIN_PASSWORD}"
echo "  Smoke user: ${PM_SMOKE_USER}"
echo "  Smoke pass: ${PM_SMOKE_PASSWORD}"
echo "  Live smoke: ${PLAYWRIGHT_REAL_BASE_URL}"
echo ""
