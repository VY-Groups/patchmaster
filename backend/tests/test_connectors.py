"""S2-2 Connector tests."""

import asyncio
import os

import pytest

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from connectors import connector_for, CommandResult
from command_templates import get_template


def _run(coro):
    return asyncio.run(coro)


def test_connector_for_modes():
    for mode in ("agent", "ssh", "winrm", "relay"):
        c = connector_for(None, mode=mode)
        assert _run(c.connect()) is True
        r = _run(c.run("list_packages"))
        assert isinstance(r, CommandResult)
        assert r.ok is True


def test_command_templates():
    assert "dpkg" in get_template("linux", "list_packages") or "rpm" in get_template("linux", "list_packages")
    assert get_template("windows", "list_packages") != ""
    assert get_template("unknown", "list_packages") != ""  # falls back to linux