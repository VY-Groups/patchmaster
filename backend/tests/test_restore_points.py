"""S1-3 RestorePoint abstraction: interface contract + capability detection (RED first)."""

import asyncio
from types import SimpleNamespace

import pytest

from restore_points.model import Capability, RestorePoint, RestorePointResult
from restore_points.capabilities import host_capability
from restore_points.adapters import (
    BackupRestorePoint,
    WindowsVssRestorePoint,
    LinuxSnapshotRestorePoint,
    NoopRestorePoint,
)


def _host(os_name="Ubuntu 22.04", arch="x86_64", **kw):
    return SimpleNamespace(os=os_name, arch=arch, id=kw.get("id", 1))


# ---- Capability detection ---------------------------------------------------


def test_linux_host_gets_package_rollback_or_full():
    cap = host_capability(_host("Ubuntu 22.04"))
    assert cap in (Capability.full_snapshot, Capability.package_rollback, Capability.config_only)


def test_windows_host_gets_full_snapshot():
    cap = host_capability(_host("Windows Server 2022"))
    assert cap == Capability.full_snapshot


def test_unknown_host_gets_none():
    cap = host_capability(_host(""))
    assert cap == Capability.none


# ---- Interface contract (ABC) ---------------------------------------------


def test_restore_point_is_abstract():
    with pytest.raises(TypeError):
        RestorePoint()  # type: ignore


def test_noop_restore_point_capability_none():
    rp = NoopRestorePoint(host=_host())
    assert rp.capability == Capability.none
    assert rp.describe()["capability"] == "none"


def test_backup_restore_point_capability():
    rp = BackupRestorePoint(host=_host())
    assert rp.capability in (Capability.package_rollback, Capability.config_only, Capability.full_snapshot)


# ---- Async create/verify/restore/delete/describe contract -------------------


def _run(coro):
    return asyncio.run(coro)


def test_noop_create_returns_result():
    rp = NoopRestorePoint(host=_host())
    r = _run(rp.create())
    assert isinstance(r, RestorePointResult)
    assert r.ok is False  # noop cannot create a real restore point


def test_describe_returns_dict():
    rp = WindowsVssRestorePoint(host=_host("Windows Server 2022"))
    d = rp.describe()
    assert isinstance(d, dict)
    assert "capability" in d
    assert "platform" in d