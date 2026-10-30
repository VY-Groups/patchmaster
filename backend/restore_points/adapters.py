"""Platform adapters for RestorePoint (S1-3)."""

from __future__ import annotations

from .model import Capability, RestorePoint, RestorePointResult
from .capabilities import host_capability


def restore_point_for(host, context=None) -> RestorePoint:
    name = str(getattr(host, "os", "") or "").lower()
    if "windows" in name:
        return WindowsVssRestorePoint(host, context)
    if any(k in name for k in ("ubuntu", "debian", "centos", "rhel", "rocky", "fedora",
                                "alpine", "opensuse", "suse", "arch", "linux", "freebsd")):
        return LinuxSnapshotRestorePoint(host, context)
    if not name.strip():
        return NoopRestorePoint(host, context)
    return BackupRestorePoint(host, context)


class NoopRestorePoint(RestorePoint):
    @property
    def capability(self) -> Capability:
        return Capability.none

    @property
    def platform(self) -> str:
        return "none"

    async def create(self) -> RestorePointResult:
        return RestorePointResult(ok=False, message="no restore capability")

    async def verify(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, message="no restore capability")

    async def restore(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, message="no restore capability")

    async def delete(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, message="no restore capability")


class WindowsVssRestorePoint(RestorePoint):
    @property
    def capability(self) -> Capability:
        return Capability.full_snapshot

    @property
    def platform(self) -> str:
        return "windows_vss"

    async def create(self) -> RestorePointResult:
        # shortcut: real VSS creation is triggered via agent /snapshot/create;
        # this adapter is the seam. Returns ok=False until wired (not simulated).
        return RestorePointResult(ok=False, ref=None, message="not implemented: delegated to agent /snapshot/create")

    async def verify(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")

    async def restore(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")

    async def delete(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")


class LinuxSnapshotRestorePoint(RestorePoint):
    @property
    def capability(self) -> Capability:
        return Capability.package_rollback

    @property
    def platform(self) -> str:
        return "linux_snapshot"

    async def create(self) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=None, message="not implemented: delegated to agent snapshot hooks")

    async def verify(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")

    async def restore(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")

    async def delete(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")


class BackupRestorePoint(RestorePoint):
    def __init__(self, host=None, context=None):
        super().__init__(host, context)
        self._cap = host_capability(host) if host is not None else Capability.config_only
        if self._cap == Capability.none:
            self._cap = Capability.config_only

    @property
    def capability(self) -> Capability:
        return self._cap

    @property
    def platform(self) -> str:
        return "backup"

    async def create(self) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=None, message="not implemented: delegated to backup service")

    async def verify(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")

    async def restore(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")

    async def delete(self, ref=None) -> RestorePointResult:
        return RestorePointResult(ok=False, ref=ref, message="not implemented")