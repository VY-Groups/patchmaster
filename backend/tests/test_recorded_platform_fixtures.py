"""plan.md S0-8: recorded command-output fixtures for Windows/AIX/Solaris/HP-UX.

The fake fleet (docker-compose.fleet.yml) covers Debian, Ubuntu, RHEL-family and
Alpine containers; these fixtures stand in for the platforms that cannot be
containerised. Every recording lives in ``tests/fixtures/recordings.json`` and is
fed to the *real* parser, so the assertions below are the parsing contract.

Recordings are representative (the formats each manager documents), not captures
from live AIX/Solaris/HP-UX/Windows hardware - plan.md treats recorded outputs as
the substitute for that hardware. Commands absent from a section replay as
``(0, "")`` so multi-command flows (catalog refresh, version lookups) complete
without recording every incidental call.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Add agent directory to path (same convention as the other agent tests)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agent"))

import aix_manager  # noqa: E402
import hpux_manager  # noqa: E402
import solaris_manager  # noqa: E402
from importlib import import_module  # noqa: E402

# `agent` resolves to agent/agent.py (module) or to the agent/ package depending
# on sys.path; reach the implementation either way so run_cmd is patched where
# the classes actually read it.
try:
    agent_mod = import_module("agent.agent")
except ModuleNotFoundError:
    agent_mod = import_module("agent")

RECORDINGS = json.loads(
    (Path(__file__).parent / "fixtures" / "recordings.json").read_text(
        encoding="utf-8"
    )
)


def replay(section: str):
    """Build a ``_run_cmd`` replacement that answers from the recordings."""
    table = RECORDINGS[section]

    def _run(cmd, timeout=None, **kwargs):
        hit = table.get(" ".join(str(c) for c in cmd)) or {"rc": 0, "out": ""}
        return int(hit["rc"]), str(hit["out"])

    return _run


def _bind(manager, section):
    manager._run_cmd = replay(section)
    return manager


# ── AIX ────────────────────────────────────────────────────────────────────


def test_aix_list_installed_parses_lslpp_table():
    mgr = _bind(aix_manager.AIXManager(), "aix")
    pkgs = mgr.list_installed()

    assert [p["name"] for p in pkgs] == ["bos.rte", "openssh.client", "perl532.interp"]
    assert pkgs[0]["version"] == "7.2.5.0"
    assert {p["status"] for p in pkgs} == {"installed"}


def test_aix_list_installed_falls_back_when_qc_is_rejected():
    """``lslpp -L -qc all`` is recorded as failing, so the fallback runs."""
    calls = []

    def _run(cmd, timeout=None, **kwargs):
        calls.append(" ".join(str(c) for c in cmd))
        return replay("aix")(cmd)

    mgr = aix_manager.AIXManager()
    mgr._run_cmd = _run

    assert mgr.list_installed()
    assert calls[0] == "lslpp -L -qc all"
    assert calls[1] == "lslpp -L"


def test_aix_list_upgradable_parses_emgr_efixes():
    mgr = _bind(aix_manager.AIXManager(), "aix")
    updates = mgr.list_upgradable()

    assert [(u["name"], u["current_version"], u["efix_id"]) for u in updates] == [
        ("ssh", "1.0", "EH0001"),
        ("openssl", "3.0.2", "EH0002"),
    ]
    assert {u["available_version"] for u in updates} == {"update"}


# ── Solaris ────────────────────────────────────────────────────────────────


def test_solaris_list_installed_parses_fmr_is():
    mgr = _bind(solaris_manager.SolarisManager(), "solaris")
    pkgs = mgr.list_installed()

    assert [(p["name"], p["version"]) for p in pkgs] == [
        ("top", "1.12"),
        ("ssh", "8.1p1"),
        ("zsh", "5.8"),
    ]
    assert {p["status"] for p in pkgs} == {"installed"}


def test_solaris_list_upgradable_reports_available_versions():
    mgr = _bind(solaris_manager.SolarisManager(), "solaris")
    updates = mgr.list_upgradable()

    assert [(u["name"], u["current_version"], u["available_version"]) for u in updates] == [
        ("top", "1.12", "1.13.0"),
        ("ssh", "8.1p1", "8.9p2"),
    ]


# ── HP-UX ──────────────────────────────────────────────────────────────────


def test_hpux_list_installed_parses_swlist_revisions():
    mgr = _bind(hpux_manager.HPUXManager(), "hpux")
    pkgs = mgr.list_installed()

    assert [(p["name"], p["version"]) for p in pkgs] == [
        ("T1471AC", "B.11.31"),
        ("T1471AC-CORE", "B.11.31"),
        ("perl532", "D.5.32"),
    ]
    assert pkgs[0]["title"] == "HP-UX Runtime Core"


def test_hpux_list_upgradable_skips_comments_and_resolves_versions():
    mgr = _bind(hpux_manager.HPUXManager(), "hpux")
    updates = mgr.list_upgradable()

    assert [(u["name"], u["current_version"], u["available_version"]) for u in updates] == [
        ("T1471AC", "B.11.31", "B.11.31.002"),
        ("perl532", "D.5.32", "D.5.32.001"),
    ]


# ── Windows ────────────────────────────────────────────────────────────────


@pytest.fixture
def win_agent(monkeypatch):
    monkeypatch.setattr(agent_mod, "run_cmd", replay("windows"))
    return agent_mod


def test_windows_get_package_inventory_parses_json(win_agent):
    packages = win_agent.WinManager().list_installed()

    assert [p["name"] for p in packages] == [
        "Microsoft Visual C++ 2015-2022 Redistributable (x64)",
        "7-Zip",
    ]
    assert packages[1] == {
        "name": "7-Zip",
        "version": "23.01",
        "status": "installed",
    }


def test_windows_winget_upgrade_columns(win_agent):
    updates = win_agent.WinManager().list_upgradable()

    assert updates == [
        {
            "name": "7-Zip",
            "id": "7zip.7zip",
            "current_version": "23.01",
            "available_version": "24.08",
        },
        {
            "name": "Git",
            "id": "Git.Git",
            "current_version": "2.45.1",
            "available_version": "2.47.0",
        },
    ]


def test_windows_powershell_json_decodes_recorded_payload(win_agent):
    data = win_agent._powershell_json(
        "Get-Content -Raw C:/state/wsus-pending.json", timeout=5
    )

    assert data["Pending"] == 2
    assert data["RebootRequired"] is True
    assert data["Updates"][0]["KB"] == "KB5034441"
