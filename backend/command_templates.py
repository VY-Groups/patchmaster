"""Named command templates per OS family (S2-2). Free-form execution stays in live-command."""

from __future__ import annotations

TEMPLATES = {
    "linux": {
        "list_packages": "dpkg -l 2>/dev/null || rpm -qa",
        "apply_updates": "apt-get update && apt-get upgrade -y 2>/dev/null || yum update -y",
        "reboot_required": "test -f /var/run/reboot-required && echo yes || echo no",
    },
    "windows": {
        "list_packages": "Get-WindowsPackage -Online",
        "apply_updates": "Install-WindowsUpdate -AcceptAll",
        "reboot_required": "if (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired') { 'yes' } else { 'no' }",
    },
}

def get_template(os_family: str, name: str) -> str:
    family = (os_family or "linux").lower()
    if family not in TEMPLATES:
        family = "linux"
    return TEMPLATES[family].get(name, "")