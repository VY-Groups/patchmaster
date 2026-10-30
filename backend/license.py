"""
Patch-SecOps Solution — License validation module.
Validates signed license keys and checks expiry.
"""

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

try:
    import psutil
except ImportError:
    psutil = None

PLACEHOLDER_VALUES = {
    "",
    "change-me",
    "replace-me",
    "PatchMaster-License-SignKey-2026-Secure",
    "changeme-set-a-strong-random-secret-here",
}


def _is_placeholder_value(value: str) -> bool:
    value = (value or "").strip()
    if value in PLACEHOLDER_VALUES:
        return True
    lowered = value.lower()
    return lowered.startswith("changeme-") or lowered.startswith("replace-me")


def _read_env_value_from_file(path: str, key: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                if name.strip() == key:
                    clean = value.split("#", 1)[0].strip().strip("\"'")
                    if clean:
                        return clean
    except Exception:
        pass
    return ""


def _load_setting(key: str) -> str:
    install_dir = os.environ.get("INSTALL_DIR", "").strip()
    current_dir = Path(__file__).resolve().parent
    candidates = []
    if key in {
        "LICENSE_SIGN_KEY",
        "LICENSE_VERIFY_PUBLIC_KEY",
        "LICENSE_DECRYPT_PRIVATE_KEY",
        "LICENSE_ENCRYPT_PUBLIC_KEY",
    }:
        candidates.extend(
            [
                os.environ.get("PATCHMASTER_ROOT_ENV", "").strip(),
                os.path.join(install_dir, "backend", ".env") if install_dir else "",
                os.path.join(install_dir, ".env") if install_dir else "",
                str(current_dir / ".env"),
                str(current_dir.parent / ".env"),
                "/opt/patchmaster/backend/.env",
                "/opt/patchmaster/.env",
            ]
        )
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        candidate = os.path.abspath(candidate)
        if candidate in seen or not os.path.isfile(candidate):
            continue
        seen.add(candidate)
        value = _read_env_value_from_file(candidate, key)
        if value and not _is_placeholder_value(value):
            os.environ[key] = value
            return value

    direct = os.environ.get(key, "").strip()
    if direct and not _is_placeholder_value(direct):
        return direct
    return ""


def _get_license_sign_key() -> str:
    return _load_setting("LICENSE_SIGN_KEY")


def _get_license_verify_public_key() -> str:
    return _load_setting("LICENSE_VERIFY_PUBLIC_KEY")


def _get_license_decrypt_private_key() -> str:
    return _load_setting("LICENSE_DECRYPT_PRIVATE_KEY")


def _get_license_encrypt_public_key() -> str:
    return _load_setting("LICENSE_ENCRYPT_PUBLIC_KEY")


LICENSE_SIGN_KEY = _get_license_sign_key()
LICENSE_VERIFY_PUBLIC_KEY = _get_license_verify_public_key()
LICENSE_DECRYPT_PRIVATE_KEY = _get_license_decrypt_private_key()
LICENSE_ENCRYPT_PUBLIC_KEY = _get_license_encrypt_public_key()
LICENSE_FILE = os.getenv(
    "LICENSE_FILE",
    os.path.join(os.getenv("INSTALL_DIR", "/opt/patchmaster"), "license.key"),
)

# Cached license state
_cached_license: Optional[dict] = None
_cache_time: Optional[datetime] = None
# Re-read the license file periodically.
# Increase TTL for speed; decrease for quicker manual edits.
try:
    _CACHE_TTL_SECONDS = max(
        1,
        int(os.getenv("PM_LICENSE_CACHE_TTL_SECONDS", "10")),
    )
except Exception:
    _CACHE_TTL_SECONDS = 10


class LicenseError(Exception):
    """Raised when the license is invalid or expired."""

    pass


# ── Feature / Tier definitions ──────────────────────────────────
ALL_FEATURES: List[str] = [
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
    "backup_db",
    "backup_file",
    "backup_vm",
    "backup_live",
    "backups",
    "linux_patching",
    "windows_patching",
    "wsus",
]

CORE_FEATURES = [
    "dashboard",
    "hosts",
    "groups",
    "patches",
    "snapshots",
    "compare",
    "offline",
    "schedules",
    "jobs",
    "onboarding",
    "settings",
    "license",
]

UNLICENSED_FEATURES = [
    "dashboard",
    "license",
    "onboarding",
    "settings",
]

STANDARD_ADDONS = [
    "compliance",
    "cve",
    "audit",
    "notifications",
    "users",
    "local-repo",
    "monitoring",
    "wsus",
    "reports",
    "software",
    "windows_patching",
]

DEVOPS_ADDONS = ["cicd", "git", "monitoring", "testing", "policies"]

TIER_FEATURES: dict = {
    "basic": CORE_FEATURES + ["linux_patching"],
    "basic_devops": CORE_FEATURES + ["linux_patching"] + DEVOPS_ADDONS,
    "standard": CORE_FEATURES + ["linux_patching"] + STANDARD_ADDONS,
    "standard_devops": CORE_FEATURES
    + ["linux_patching"]
    + STANDARD_ADDONS
    + DEVOPS_ADDONS
    + ["backup_db", "backup_file", "backups"],
    "enterprise": ALL_FEATURES[:],
}

TIER_HOST_LIMITS: dict = {
    "basic": 10,
    "basic_devops": 10,
    "standard": 100,
    "standard_devops": 100,
    "enterprise": 0,  # Unlimited
}

TIER_LABELS: dict = {
    "basic": "Basic",
    "basic_devops": "Basic + DevOps",
    "standard": "Standard",
    "standard_devops": "Standard + DevOps",
    "enterprise": "Enterprise (Advance)",
}

PM1_LICENSE_KEY_PATTERN = re.compile(r"PM1-[A-Za-z0-9_-]+\.[A-Fa-f0-9]{64,128}")
PM2_LICENSE_KEY_PATTERN = re.compile(
    r"PM2-[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Fa-f0-9]{64,128}"
)


def get_mac_addresses() -> List[str]:
    """Get all MAC addresses for current machine interfaces."""
    macs = []
    if psutil is None:
        return macs
    try:
        for _, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                # psutil.AF_LINK is the MAC address family
                if hasattr(psutil, "AF_LINK") and addr.family == psutil.AF_LINK:
                    mac = addr.address.lower().replace("-", ":")
                    if mac and mac != "00:00:00:00:00:00":
                        macs.append(mac)
    except Exception:
        pass
    return sorted(list(set(macs)))  # Deduplicate and sort


def get_hardware_id() -> str:
    """Return the primary hardware ID (MAC or Env) for license binding."""
    # 1. Check for Container/Cloud explicit binding ID
    bind_id = os.getenv("PM_BINDING_ID") or os.getenv("PM_INSTANCE_ID")
    if bind_id:
        return bind_id.strip().lower()

    # 2. Fallback to MAC address (Bare Metal)
    macs = get_mac_addresses()
    return macs[0] if macs else "unknown"


def _decode_key_bytes(value: str) -> bytes:
    text = (value or "").strip()
    if not text:
        return b""
    padding = "=" * ((4 - len(text) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((text + padding).encode())
    except Exception:
        return b""


def _verify_hmac_signature(message: str, signature: str, sign_key: str) -> bool:
    expected = hmac.new(sign_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_public_signature(message: str, signature: str, public_key: str) -> bool:
    public_key_bytes = _decode_key_bytes(public_key)
    if not public_key_bytes:
        return False
    try:
        signature_bytes = bytes.fromhex(signature)
        verifier = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        verifier.verify(signature_bytes, message.encode())
        return True
    except Exception:
        return False


def _verification_configured() -> bool:
    return bool(_get_license_verify_public_key() or _get_license_sign_key())


def _verify_signature(message: str, signature: str) -> bool:
    """Verify license signatures using Ed25519 first, then legacy HMAC fallback."""
    current_public_key = _get_license_verify_public_key()
    if current_public_key and _verify_public_signature(
        message, signature, current_public_key
    ):
        return True

    current_sign_key = _get_license_sign_key()
    if current_sign_key and _verify_hmac_signature(
        message, signature, current_sign_key
    ):
        return True

    return False


def _decode_b64_json(value: str, error_message: str) -> dict:
    raw = _decode_key_bytes(value)
    if not raw:
        raise LicenseError(error_message)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise LicenseError(error_message)


def _derive_pm2_aead_key(shared_secret: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"patchmaster-pm2-license-v1",
    ).derive(shared_secret)


def _decrypt_pm2_payload(header_b64: str, envelope_b64: str) -> dict:
    decrypt_private_key = _get_license_decrypt_private_key()
    if not decrypt_private_key:
        raise LicenseError("Patch-SecOps Solution PM2 decryption key is not configured")

    private_key_bytes = _decode_key_bytes(decrypt_private_key)
    if not private_key_bytes:
        raise LicenseError("Patch-SecOps Solution PM2 decryption key is invalid")

    envelope = _decode_b64_json(envelope_b64, "License key envelope is corrupted")
    epk = _decode_key_bytes(envelope.get("epk", ""))
    nonce = _decode_key_bytes(envelope.get("nonce", ""))
    ciphertext = _decode_key_bytes(envelope.get("ct", ""))
    if not epk or not nonce or not ciphertext:
        raise LicenseError("License key envelope is incomplete")

    try:
        private_key = X25519PrivateKey.from_private_bytes(private_key_bytes)
        peer_key = X25519PublicKey.from_public_bytes(epk)
        shared_secret = private_key.exchange(peer_key)
        aes_key = _derive_pm2_aead_key(shared_secret)
        plaintext = AESGCM(aes_key).decrypt(nonce, ciphertext, header_b64.encode())
        return json.loads(plaintext.decode("utf-8"))
    except LicenseError:
        raise
    except Exception:
        raise LicenseError("License key payload decryption failed")


def normalize_license_key(raw_value: str) -> str:
    """Extract a real Patch-SecOps Solution PM2 key from pasted text, JSON, or wrapped files."""
    if raw_value is None:
        return ""

    text = str(raw_value).replace("\ufeff", "").strip()
    if not text:
        return ""

    # Support payloads copied from API responses or support notes.
    if text[:1] in "{[":
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                for field in ("license_key", "key", "license"):
                    value = parsed.get(field)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break
        except Exception:
            pass

    # Only accept PM2 licenses
    direct = PM2_LICENSE_KEY_PATTERN.search(text)
    if direct:
        return direct.group(0)

    compact = re.sub(r"\s+", "", text)
    compact = compact.strip("\"'")
    wrapped = PM2_LICENSE_KEY_PATTERN.search(compact)
    if wrapped:
        return wrapped.group(0)

    return text.strip("\"'")


def decode_license(license_key: str) -> dict:
    """Decode and verify a license key string. Returns the payload dict."""
    license_key = normalize_license_key(license_key)
    if not license_key:
        raise LicenseError("Invalid license key format")
    
    # Only PM2 (encrypted) licenses are supported
    if not license_key.startswith("PM2-"):
        raise LicenseError("Invalid license key format. Only PM2 encrypted licenses are supported.")

    if not _verification_configured():
        raise LicenseError("Patch-SecOps Solution license verification is not configured")

    # PM2 License Processing
    body = license_key[4:]
    parts = body.split(".", 2)
    if len(parts) != 3:
        raise LicenseError("Invalid license key format")
    header_b64, envelope_b64, signature = parts
    signed_message = f"{header_b64}.{envelope_b64}"
    if not _verify_signature(signed_message, signature):
        raise LicenseError("License key signature verification failed")
    header = _decode_b64_json(header_b64, "License key header is corrupted")
    payload = _decrypt_pm2_payload(header_b64, envelope_b64)
    payload.setdefault("license_id", header.get("license_id", "legacy"))
    payload.setdefault("sig_alg", header.get("sig_alg", payload.get("sig_alg", "")))
    payload.setdefault("enc_alg", header.get("enc_alg", payload.get("enc_alg", "")))
    payload.setdefault("license_format", "PM2")

    # Validate required fields
    for field in ("plan", "customer"):
        if field not in payload:
            raise LicenseError(f"License key missing required field: {field}")

    # Hardware MAC/ID Binding check (skip if explicitly no_bind)
    if not payload.get("no_bind", False):
        hw_id = (payload.get("hw_id") or "").strip().lower()
        if hw_id:
            current_hw_id = get_hardware_id()
            # If running in container mode (PM_BINDING_ID set), check exact match
            if os.getenv("PM_BINDING_ID") or os.getenv("PM_INSTANCE_ID"):
                if hw_id != current_hw_id:
                    raise LicenseError(
                        f"License bound to ID '{hw_id}', but current container ID is '{current_hw_id}'."
                    )
            else:
                # Bare Metal: Check against list of MACs (handles multiple NICs)
                local_macs = get_mac_addresses()
                if hw_id not in local_macs:
                    raise LicenseError(
                        f"This license is bound to a different machine (HW-ID mismatch)."
                    )

    return payload


def read_license_file() -> Optional[str]:
    """Read the license key from the license file."""
    path = Path(LICENSE_FILE)
    if path.is_file():
        content = path.read_text(encoding="utf-8-sig", errors="ignore")
        content = normalize_license_key(content)
        if content:
            return content
    return None


def _check_expiry_warnings(days_remaining: int) -> list[str]:
    """Generate expiration warning messages."""
    warnings = []
    if days_remaining <= 0:
        warnings.append("EXPIRED: License has expired! Immediate action required.")
    elif days_remaining == 0:
        warnings.append("CRITICAL: License expires TODAY!")
    elif days_remaining == 1:
        warnings.append("CRITICAL: License expires TOMORROW!")
    elif days_remaining <= 7:
        warnings.append(f"WARNING: License expires in {days_remaining} days!")
    elif days_remaining <= 30:
        warnings.append(f"NOTICE: License expires in {days_remaining} days")
    return warnings


def get_license_info(force_refresh: bool = False) -> dict:
    """
    Get the current license status. Returns a dict with:
      - valid: bool
      - expired: bool
      - plan, customer, issued_at, expires_at, days_remaining, etc.
      - error: str (if invalid)
    """
    global _cached_license, _cache_time

    now = datetime.now(timezone.utc)

    # Use cache if fresh
    if (
        not force_refresh
        and _cached_license is not None
        and _cache_time is not None
        and (now - _cache_time).total_seconds() < _CACHE_TTL_SECONDS
    ):
        # Recheck expiry from cache
        info = _cached_license.copy()
        if info.get("valid") and info.get("expires_at_dt"):
            info["expired"] = now >= info["expires_at_dt"]
            info["days_remaining"] = max(0, (info["expires_at_dt"] - now).days)
            # Add expiration warnings
            info["warnings"] = _check_expiry_warnings(info["days_remaining"])
        return info

    license_key = read_license_file()

    if not license_key:
        info = {
            "valid": False,
            "expired": False,
            "activated": False,
            "error": "No license key found. Activate a license to use Patch-SecOps Solution.",
        }
        _cached_license = info
        _cache_time = now
        return info

    try:
        payload = decode_license(license_key)
    except LicenseError as e:
        info = {
            "valid": False,
            "expired": False,
            "activated": True,
            "error": str(e),
        }
        _cached_license = info
        _cache_time = now
        return info

    # Support v3 compact epoch fields (iat/exp) and legacy ISO fields
    try:
        if "exp" in payload and "iat" in payload:
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            issued_at = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        elif "expires_at" in payload and "issued_at" in payload:
            expires_at = datetime.fromisoformat(
                payload["expires_at"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            issued_at = datetime.fromisoformat(
                payload["issued_at"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        else:
            raise LicenseError("License key missing expiry/issue timestamps")
    except LicenseError:
        raise
    except Exception as e:
        raise LicenseError(f"License key has invalid timestamps: {e}")
    is_expired = now >= expires_at
    days_remaining = max(0, (expires_at - now).days)

    # Resolve allowed features from tier/payload
    tier = payload.get("tier", "enterprise")
    tier_defaults = TIER_FEATURES.get(tier, ALL_FEATURES)
    licensed_features = payload.get("features") or tier_defaults
    merged = set(tier_defaults) | set(licensed_features)
    if any(f.startswith("backup_") for f in merged):
        merged.add("backups")
    licensed_features = [f for f in ALL_FEATURES if f in merged] + [
        f for f in merged if f not in ALL_FEATURES
    ]

    # Resolve host limit (payload overrides tier default)
    max_hosts = payload.get("max_hosts")
    if max_hosts is None:
        max_hosts = TIER_HOST_LIMITS.get(tier, 0)

    info = {
        "valid": True,
        "expired": is_expired,
        "activated": True,
        "plan": payload.get("plan", "unknown"),
        "plan_label": payload.get("plan_label", payload.get("plan", "Unknown")),
        "customer": payload.get("customer", "Unknown"),
        "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issued_at_ts": int(issued_at.timestamp()),
        "expires_at_ts": int(expires_at.timestamp()),
        "expires_at_dt": expires_at,
        "issued_at_dt": issued_at,
        "days_remaining": days_remaining,
        "max_hosts": max_hosts,
        "tier": tier,
        "tier_label": payload.get("tier_label", TIER_LABELS.get(tier, tier.title())),
        "features": licensed_features,
        "license_id": payload.get("license_id", "legacy"),
        "version_compat": payload.get("version_compat", "2.x"),
        "tool_version": payload.get("tool_version", "1.x"),
        "license_format": payload.get("license_format", "PM1"),
        "binding_required": not payload.get("no_bind", False)
        and bool(payload.get("hw_id")),
        "no_bind": payload.get("no_bind", False),
    }

    # Add expiration warnings
    info["warnings"] = _check_expiry_warnings(days_remaining)

    # Add emergency flag for very low days
    if days_remaining <= 7:
        info["license_expiring_soon"] = True
        info["urgent_action_required"] = days_remaining <= 1

    _cached_license = info
    _cache_time = now
    return info


def invalidate_cache():
    """Force next call to re-read the license file."""
    global _cached_license, _cache_time
    _cached_license = None
    _cache_time = None


def is_license_active() -> bool:
    """Quick check: is the license valid and not expired?"""
    info = get_license_info()
    return info.get("valid", False) and not info.get("expired", True)


def get_licensed_features() -> List[str]:
    """Return the list of features allowed by the current license.
    Returns a minimal feature set if no valid license.
    """
    info = get_license_info()
    if info.get("valid") and not info.get("expired"):
        return info.get("features", ALL_FEATURES[:])
    return UNLICENSED_FEATURES[:]
