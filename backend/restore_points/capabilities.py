"""Capability detection per host (S1-3)."""

from __future__ import annotations

from .model import Capability


def _os_lower(host) -> str:
    os_name = getattr(host, "os", None)
    if os_name is None and isinstance(host, dict):
        os_name = host.get("os")
    return str(os_name or "").lower()


def host_capability(host) -> Capability:
    name = _os_lower(host)
    if not name.strip():
        return Capability.none
    if "windows" in name or "win" in name.split():
        return Capability.full_snapshot
    if any(k in name for k in ("ubuntu", "debian", "centos", "rhel", "rocky", "fedora",
                                "alpine", "opensuse", "suse", "arch", "linux", "freebsd")):
        # Linux agents expose package-level rollback hooks; full VSS-style
        # snapshots are not guaranteed, so advertise package_rollback.
        return Capability.package_rollback
    return Capability.none