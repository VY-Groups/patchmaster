"""License management API — view status, activate, deactivate."""
import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel

from auth import get_current_user, require_role
from models.db_models import UserRole
from license import (
    get_license_info,
    decode_license,
    invalidate_cache,
    LicenseError,
    LICENSE_FILE,
    normalize_license_key,
)
import monitoring_manager

router = APIRouter(prefix="/api/license", tags=["License"])


def _vendor_activation_callback_enabled() -> bool:
    return os.getenv("PM_ENABLE_VENDOR_ACTIVATION_CALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}


class ActivateRequest(BaseModel):
    license_key: str


class LicenseResponse(BaseModel):
    valid: bool
    expired: bool
    activated: bool
    plan: str = ""
    plan_label: str = ""
    customer: str = ""
    issued_at: str = ""
    expires_at: str = ""
    issued_at_ts: int | None = None
    expires_at_ts: int | None = None
    days_remaining: int = 0
    max_hosts: int = 0
    tier: str = ""
    tier_label: str = ""
    features: List[str] = []
    license_id: str = ""
    version_compat: str = ""
    tool_version: str = ""
    binding_required: bool = False
    no_bind: bool = False
    error: str = ""
    hardware_id: str = "" # Current machine HW ID for binding

class LicenseActivationRequest(BaseModel):
    key: str = ""
    license_key: str = ""

@router.get("/status", response_model=LicenseResponse)
async def license_status():
    """Get current license status. No auth required — frontend needs this."""
    info = get_license_info(force_refresh=True)  # Always re-read file so manual edits are instant
    from license import get_hardware_id
    return LicenseResponse(
        valid=info.get("valid", False),
        expired=info.get("expired", False),
        activated=info.get("activated", False),
        plan=info.get("plan", ""),
        plan_label=info.get("plan_label", ""),
        customer=info.get("customer", ""),
        issued_at=info.get("issued_at", ""),
        expires_at=info.get("expires_at", ""),
        issued_at_ts=info.get("issued_at_ts"),
        expires_at_ts=info.get("expires_at_ts"),
        days_remaining=info.get("days_remaining", 0),
        max_hosts=info.get("max_hosts", 0),
        tier=info.get("tier", ""),
        tier_label=info.get("tier_label", ""),
        features=info.get("features", []),
        license_id=info.get("license_id", ""),
        version_compat=info.get("version_compat", ""),
        tool_version=info.get("tool_version", ""),
        binding_required=info.get("binding_required", False),
        no_bind=info.get("no_bind", False),
        error=info.get("error", ""),
        hardware_id=get_hardware_id(),
    )


@router.post("/activate-manual", response_model=LicenseResponse)
async def activate_license(req: ActivateRequest, user=Depends(require_role(UserRole.admin))):
    """Admin activates a license key."""
    key = normalize_license_key(req.license_key)
    if not key:
        raise HTTPException(400, "License key cannot be empty")

    # Validate before saving
    try:
        payload = decode_license(key)
    except LicenseError as e:
        msg = str(e)
        if "bound to a different machine" in msg:
            msg = "License already used / bound to another hardware ID. Please contact support."
        raise HTTPException(400, f"Invalid license key: {msg}")

    # Write to file
    with open(LICENSE_FILE, "w") as f:
        f.write(key)

    # Force reload
    get_license_info(force_refresh=True)

    info = get_license_info(force_refresh=True)
    from license import get_hardware_id
    return LicenseResponse(
        valid=info.get("valid", False),
        expired=info.get("expired", False),
        activated=info.get("activated", False),
        plan=info.get("plan", ""),
        plan_label=info.get("plan_label", ""),
        customer=info.get("customer", ""),
        issued_at=info.get("issued_at", ""),
        expires_at=info.get("expires_at", ""),
        issued_at_ts=info.get("issued_at_ts"),
        expires_at_ts=info.get("expires_at_ts"),
        days_remaining=info.get("days_remaining", 0),
        max_hosts=info.get("max_hosts", 0),
        tier=info.get("tier", ""),
        tier_label=info.get("tier_label", ""),
        features=info.get("features", []),
        license_id=info.get("license_id", ""),
        version_compat=info.get("version_compat", ""),
        tool_version=info.get("tool_version", ""),
        binding_required=info.get("binding_required", False),
        no_bind=info.get("no_bind", False),
        error=info.get("error", ""),
        hardware_id=get_hardware_id(),
    )

@router.post("/activate", response_model=LicenseResponse)
async def activate_license_with_bg(
    payload: LicenseActivationRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(require_role(UserRole.admin, UserRole.operator))
):
    """Activate a new license key (with background ping)."""
    key = normalize_license_key(payload.key) or normalize_license_key(payload.license_key)
    if not key:
        raise HTTPException(400, "License key cannot be empty")
    
    # Validate before saving
    try:
        decoded = decode_license(key)
    except LicenseError as e:
        msg = str(e)
        if "bound to a different machine" in msg:
            msg = "License already used / bound to another hardware ID. Please contact support."
        raise HTTPException(400, f"Invalid license key: {msg}")

    # Write to file
    with open(LICENSE_FILE, "w") as f:
        f.write(key)

    # Force reload
    get_license_info(force_refresh=True)
    
    # Legacy-only vendor activation callback. Default posture is fully offline.
    url = decoded.get("activation_url")
    if url and _vendor_activation_callback_enabled():
        from license import get_hardware_id

        background_tasks.add_task(
            ping_vendor_activation,
            url,
            decoded.get("license_id"),
            get_hardware_id(),
        )

    # Return refreshed info
    info = get_license_info(force_refresh=True)
    from license import get_hardware_id
    return LicenseResponse(
        valid=info.get("valid", False),
        expired=info.get("expired", False),
        activated=info.get("activated", False),
        plan=info.get("plan", ""),
        plan_label=info.get("plan_label", ""),
        customer=info.get("customer", ""),
        issued_at=info.get("issued_at", ""),
        expires_at=info.get("expires_at", ""),
        issued_at_ts=info.get("issued_at_ts"),
        expires_at_ts=info.get("expires_at_ts"),
        days_remaining=info.get("days_remaining", 0),
        max_hosts=info.get("max_hosts", 0),
        tier=info.get("tier", ""),
        tier_label=info.get("tier_label", ""),
        features=info.get("features", []),
        license_id=info.get("license_id", ""),
        version_compat=info.get("version_compat", ""),
        tool_version=info.get("tool_version", ""),
        binding_required=info.get("binding_required", False),
        no_bind=info.get("no_bind", False),
        error=info.get("error", ""),
        hardware_id=get_hardware_id(),
    )

async def ping_vendor_activation(url: str, license_id: str, hw_id: str):
    """Notify vendor of activation. Fail silently if offline."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"license_id": license_id, "hw_id": hw_id})
    except Exception:
        # Expected if air-gapped
        pass


@router.post("/deactivate", response_model=LicenseResponse)
async def deactivate_license(user=Depends(require_role(UserRole.admin))):
    """Admin deactivates the current license."""
    license_path = Path(LICENSE_FILE)
    if license_path.exists():
        license_path.unlink()
    
    # Clear cache
    invalidate_cache()
    
    # Stop all licensed services
    try:
        monitoring_manager.enforce_license([])
    except Exception:
        pass

    info = get_license_info(force_refresh=True)
    from license import get_hardware_id
    return LicenseResponse(
        valid=info.get("valid", False),
        expired=info.get("expired", False),
        activated=info.get("activated", False),
        plan=info.get("plan", ""),
        plan_label=info.get("plan_label", ""),
        customer=info.get("customer", ""),
        issued_at=info.get("issued_at", ""),
        expires_at=info.get("expires_at", ""),
        days_remaining=info.get("days_remaining", 0),
        max_hosts=info.get("max_hosts", 0),
        tier=info.get("tier", ""),
        tier_label=info.get("tier_label", ""),
        features=info.get("features", []),
        license_id=info.get("license_id", ""),
        version_compat=info.get("version_compat", ""),
        tool_version=info.get("tool_version", ""),
        error=info.get("error", ""),
        hardware_id=get_hardware_id(),
    )


@router.delete("/deactivate")
async def deactivate_license_delete(user=Depends(require_role(UserRole.admin))):

    license_path = Path(LICENSE_FILE)
    if license_path.is_file():
        license_path.unlink()

    invalidate_cache()
    return {"detail": "License deactivated"}
