"""Characterization / unit tests for the S1-1 Gate model and S1-2 decision engine.

Written BEFORE the implementation (RED first). Each gate type must be runnable
and produce a deterministic pass/fail result.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from gates.model import (
    GateDefinition,
    GateResult,
    GateDecision,
    GateSeverity,
    GateStatus,
    RunStatus,
)
from gates.checkers import check_gate, GATE_CHECKERS
from restore_points.model import Capability
from restore_points.capabilities import host_capability
from gates.evaluator import evaluate_gates, decide, parse_gates


def _host(**kw):
    defaults = dict(
        id=1,
        is_online=True,
        compliance_score=95.0,
        cve_count=1,
        disk_free_gb=10.0,
        last_snapshot_at=datetime.now(timezone.utc),
        services_healthy=True,
        last_heartbeat=datetime.now(timezone.utc),
        drift_status="clean",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ---- Model serialization ---------------------------------------------------


def test_gate_definition_required_property():
    g = GateDefinition(type="host_reachable", severity="required")
    assert g.required is True
    g2 = GateDefinition(type="host_reachable", severity="advisory")
    assert g2.required is False


def test_gate_definition_roundtrip():
    d = {
        "type": "disk_space",
        "parameters": {"min_free_gb": 5},
        "severity": "advisory",
        "timeout_seconds": 30,
        "retry_count": 2,
    }
    g = GateDefinition.from_dict(d)
    assert g.type == "disk_space"
    assert g.parameters == {"min_free_gb": 5}
    assert g.severity == "advisory"
    assert g.timeout_seconds == 30
    assert g.retry_count == 2
    assert g.to_dict() == d


def test_gate_result_to_dict_has_timestamps():
    now = datetime.now(timezone.utc)
    r = GateResult(
        gate_type="host_reachable",
        status=GateStatus.passed.value,
        observed={"hosts": [1]},
        started_at=now,
        finished_at=now,
        raw_output_ref="ptr://x",
        reason="ok",
    )
    d = r.to_dict()
    assert d["gate_type"] == "host_reachable"
    assert d["status"] == "passed"
    assert d["started_at"] == now.isoformat()
    assert d["raw_output_ref"] == "ptr://x"


# ---- Checker registry ------------------------------------------------------


def test_all_ten_gate_types_registered():
    expected = {
        "restore_capable",
        "host_reachable",
        "maintenance_window",
        "disk_space",
        "snapshot_present",
        "service_health",
        "heartbeat_alive",
        "custom_probe",
        "drift_clean",
        "restore_drill_passed",
        "approval_granted",
    }
    assert expected.issubset(set(GATE_CHECKERS.keys()))


# ---- Host-level gates: pass and fail --------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_host_reachable_pass_and_fail():
    g = GateDefinition(type="host_reachable")
    ctx_pass = {"hosts": [_host(is_online=True), _host(id=2, is_online=True)]}
    r = _run(check_gate(g, ctx_pass))
    assert r.status == GateStatus.passed.value

    ctx_fail = {"hosts": [_host(is_online=False)]}
    r = _run(check_gate(g, ctx_fail))
    assert r.status == GateStatus.failed.value
    assert "host_offline" in r.reason or "offline" in r.reason.lower()


def test_heartbeat_alive_fail_when_stale():
    g = GateDefinition(type="heartbeat_alive", parameters={"max_age_seconds": 60})
    stale = _host(last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=300))
    r = _run(check_gate(g, {"hosts": [stale]}))
    assert r.status == GateStatus.failed.value

    fresh = _host(last_heartbeat=datetime.now(timezone.utc))
    r = _run(check_gate(g, {"hosts": [fresh]}))
    assert r.status == GateStatus.passed.value


def test_disk_space_fail_when_low():
    g = GateDefinition(type="disk_space", parameters={"min_free_gb": 5})
    r = _run(check_gate(g, {"hosts": [_host(disk_free_gb=1.0)]}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"hosts": [_host(disk_free_gb=10.0)]}))
    assert r.status == GateStatus.passed.value


def test_snapshot_present_fail_when_missing():
    g = GateDefinition(type="snapshot_present")
    r = _run(check_gate(g, {"hosts": [_host(last_snapshot_at=None)]}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"hosts": [_host(last_snapshot_at=datetime.now(timezone.utc))]}))
    assert r.status == GateStatus.passed.value


def test_service_health_fail_when_unhealthy():
    g = GateDefinition(type="service_health")
    r = _run(check_gate(g, {"hosts": [_host(services_healthy=False)]}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"hosts": [_host(services_healthy=True)]}))
    assert r.status == GateStatus.passed.value


def test_drift_clean_fail_when_drifted():
    g = GateDefinition(type="drift_clean")
    r = _run(check_gate(g, {"hosts": [_host(drift_status="drifted")]}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"hosts": [_host(drift_status="clean")]}))
    assert r.status == GateStatus.passed.value


# ---- Policy / context gates ------------------------------------------------


def test_restore_drill_passed_uses_context():
    g = GateDefinition(type="restore_drill_passed")
    r = _run(check_gate(g, {"drill_result": {"passed": False}}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"drill_result": {"passed": True}}))
    assert r.status == GateStatus.passed.value


def test_approval_granted_uses_context():
    g = GateDefinition(type="approval_granted")
    r = _run(check_gate(g, {"approval": False}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"approval": True}))
    assert r.status == GateStatus.passed.value


def test_custom_probe_uses_context():
    g = GateDefinition(type="custom_probe", parameters={"name": "http"})
    r = _run(check_gate(g, {"probe_result": False}))
    assert r.status == GateStatus.failed.value
    r = _run(check_gate(g, {"probe_result": True}))
    assert r.status == GateStatus.passed.value


def test_restore_capable_fail_for_unknown_host():
    g = GateDefinition(type="restore_capable")
    r = _run(check_gate(g, {"hosts": [_host(os="")] if False else SimpleNamespace(id=1, os="")} ))
    assert r.status == GateStatus.failed.value
    from restore_points.capabilities import host_capability
    assert host_capability(SimpleNamespace(os="")) == Capability.none


def test_maintenance_window_passes_when_all_allowed():
    g = GateDefinition(type="maintenance_window")
    # No windows provided and no session -> gate passes (no blocking window)
    r = _run(check_gate(g, {"hosts": [_host()]}))
    assert r.status == GateStatus.passed.value


# ---- evaluate_gates + decide ----------------------------------------------


def test_evaluate_gates_returns_one_result_per_defn():
    defs = [
        GateDefinition(type="host_reachable"),
        GateDefinition(type="disk_space", parameters={"min_free_gb": 5}),
    ]
    ctx = {"hosts": [_host()]}
    results = _run(evaluate_gates(defs, ctx))
    assert len(results) == 2
    assert all(isinstance(r, GateResult) for r in results)


def test_decide_promote_when_all_required_pass():
    defs = [GateDefinition(type="host_reachable", severity="required")]
    results = [GateResult(gate_type="host_reachable", status=GateStatus.passed.value)]
    d = decide(results, defs)
    assert d.outcome == "promote"


def test_decide_hold_when_required_fails_default():
    defs = [GateDefinition(type="host_reachable", severity="required")]
    results = [GateResult(gate_type="host_reachable", status=GateStatus.failed.value)]
    d = decide(results, defs)
    assert d.outcome == "hold"
    assert "host_reachable" in d.failed_required


def test_decide_rollback_when_policy_says_so():
    defs = [GateDefinition(type="host_reachable", severity="required")]
    results = [GateResult(gate_type="host_reachable", status=GateStatus.failed.value)]
    d = decide(results, defs, on_failure="rollback")
    assert d.outcome == "rollback"


def test_decide_promote_when_only_advisory_fails():
    defs = [GateDefinition(type="disk_space", severity="advisory")]
    results = [GateResult(gate_type="disk_space", status=GateStatus.failed.value)]
    d = decide(results, defs)
    assert d.outcome == "promote"
    assert "disk_space" in d.failed_advisory


# ---- parse_gates -----------------------------------------------------------


def test_parse_gates_from_rollout_config():
    cfg = {
        "gates": {
            "pre": [{"type": "host_reachable", "severity": "required"}],
            "post": [{"type": "service_health", "severity": "required"}],
        }
    }
    pre = parse_gates(cfg, phase="pre")
    post = parse_gates(cfg, phase="post")
    assert len(pre) == 1 and pre[0].type == "host_reachable"
    assert len(post) == 1 and post[0].type == "service_health"


def test_parse_gates_ring_overrides_global():
    cfg = {
        "gates": {"pre": [{"type": "host_reachable"}]},
    }
    ring = {"gates": {"pre": [{"type": "disk_space", "parameters": {"min_free_gb": 2}}]}}
    pre = parse_gates(cfg, phase="pre", ring=ring)
    assert len(pre) == 1 and pre[0].type == "disk_space"


def test_parse_gates_empty_when_absent():
    assert parse_gates({}, phase="pre") == []
    assert parse_gates({"gates": {}}, phase="pre") == []


# ---- RunStatus enum exists -------------------------------------------------


def test_run_status_states():
    for s in ("pending", "running", "passed", "failed", "held", "rolled_back", "overridden"):
        assert RunStatus(s).value == s