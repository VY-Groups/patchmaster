"""Policy templates (P1.1-P1.3)."""

from __future__ import annotations

POLICY_TEMPLATES = [
    {
        "name": "Business Hours Deployment - No Reboot",
        "description": "Deploy during business hours, never reboot.",
        "target_os_family": "any",
        "reboot_behaviour": "never",
        "approval_mode": "manual",
        "schedule": "0 9 * * 1-5",
    },
    {
        "name": "24x7 Deploy at Startup",
        "description": "Deploy 24x7, reboot at startup if required.",
        "target_os_family": "any",
        "reboot_behaviour": "if_required",
        "approval_mode": "none",
        "schedule": "0 * * * *",
    },
    {
        "name": "24x7 with User Intervention Allowed",
        "description": "Deploy 24x7, allow user to defer reboot.",
        "target_os_family": "any",
        "reboot_behaviour": "if_required",
        "approval_mode": "manual",
        "schedule": "0 * * * *",
    },
]


def list_templates() -> list[dict]:
    return [dict(t) for t in POLICY_TEMPLATES]