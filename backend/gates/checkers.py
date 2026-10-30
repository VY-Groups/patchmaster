"""S1-1 gate checkers: one async checker per gate type.

Each checker is ``(GateDefinition, context) -> GateResult``. Host-level gates
evaluate every host in ``context["hosts"]`` and pass only when ALL pass.
Reuses ``api.ring_rollout`` health/maintenance helpers instead of duplicating.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from gates.model import GateDefinition, GateResult, GateStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hosts(ctx: dict) -> list:
    return list(ctx.get("hosts") or [])


def _param(defn: GateDefinition, ctx: dict, key: str, default: Any = None) -> Any:
    params = dict(defn.parameters or {})
    # context may override via same key
    if key in ctx:
        return ctx[key]
    return params.get(key, default)


def _host_attr(host: Any, name: str, default: Any = None) -> Any:
    if isinstance(host, dict):
        return host.get(name, default)
    return getattr(host, name, default)


def _make_result(defn: GateDefinition, status: str, observed: dict, reason: str = "",
                 raw_ref: Any = None) -> GateResult:
    now = _now()
    return GateResult(
        gate_type=defn.type,
        status=status,
        observed=observed or {},
        started_at=now,
        finished_at=now,
        raw_output_ref=raw_ref,
        reason=reason,
    )


# ---- host-level gates ------------------------------------------------------


async def _host_reachable(defn: GateDefinition, ctx: dict) -> GateResult:
    hosts = _hosts(ctx)
    bad = []
    obs = []
    for h in hosts:
        online = bool(_host_attr(h, "is_online", False))
        obs.append({"id": _host_attr(h, "id"), "online": online})
        if not online:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"host_offline: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "all online")


async def _heartbeat_alive(defn: GateDefinition, ctx: dict) -> GateResult:
    max_age = int(_param(defn, ctx, "max_age_seconds", 300))
    hosts = _hosts(ctx)
    bad = []
    obs = []
    now = _now()
    for h in hosts:
        hb = _host_attr(h, "last_heartbeat", None)
        age = None
        if hb is None:
            age = 10**9
        elif isinstance(hb, (int, float)):
            age = int(hb)
        else:
            try:
                if hb.tzinfo is None:
                    hb = hb.replace(tzinfo=timezone.utc)
                age = int((now - hb).total_seconds())
            except Exception:
                age = 10**9
        ok = age <= max_age
        obs.append({"id": _host_attr(h, "id"), "age_seconds": age, "ok": ok})
        if not ok:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"heartbeat_stale: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "all fresh")


async def _disk_space(defn: GateDefinition, ctx: dict) -> GateResult:
    min_free = float(_param(defn, ctx, "min_free_gb", 1.0))
    hosts = _hosts(ctx)
    bad = []
    obs = []
    for h in hosts:
        free = float(_host_attr(h, "disk_free_gb", 0.0) or 0.0)
        ok = free >= min_free
        obs.append({"id": _host_attr(h, "id"), "free_gb": free, "ok": ok})
        if not ok:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"disk_below_{min_free}: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "ok")


async def _snapshot_present(defn: GateDefinition, ctx: dict) -> GateResult:
    hosts = _hosts(ctx)
    bad = []
    obs = []
    for h in hosts:
        snap = _host_attr(h, "last_snapshot_at", None)
        ok = snap is not None
        obs.append({"id": _host_attr(h, "id"), "snapshot": snap is not None})
        if not ok:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"no_snapshot: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "ok")


async def _service_health(defn: GateDefinition, ctx: dict) -> GateResult:
    hosts = _hosts(ctx)
    bad = []
    obs = []
    for h in hosts:
        healthy = bool(_host_attr(h, "services_healthy", True))
        obs.append({"id": _host_attr(h, "id"), "healthy": healthy})
        if not healthy:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"service_unhealthy: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "ok")


async def _drift_clean(defn: GateDefinition, ctx: dict) -> GateResult:
    hosts = _hosts(ctx)
    bad = []
    obs = []
    for h in hosts:
        status = str(_host_attr(h, "drift_status", "clean") or "clean")
        ok = status == "clean"
        obs.append({"id": _host_attr(h, "id"), "drift_status": status, "ok": ok})
        if not ok:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"drift_detected: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "ok")


# ---- context / policy gates -----------------------------------------------


async def _maintenance_window(defn: GateDefinition, ctx: dict) -> GateResult:
    hosts = _hosts(ctx)
    guardrails = dict(ctx.get("guardrails") or {})
    maintenance = dict((guardrails.get("maintenance") if isinstance(guardrails, dict) else None) or {})
    # merge defn parameters into maintenance config
    for k, v in (defn.parameters or {}).items():
        maintenance.setdefault(k, v)
    if not maintenance.get("require_window", False) and not defn.parameters.get("require_window"):
        # default: no window required -> pass
        pass
    # reuse ring_rollout helper
    try:
        import api.ring_rollout as rr
    except Exception:
        rr = None

    windows = ctx.get("maintenance_windows", None)
    session = ctx.get("session", None)

    if rr is not None and (session is not None or windows is not None):
        try:
            allowed, state = await rr._maintenance_gate_for_hosts(
                session, hosts, {"maintenance": maintenance}, windows=windows,
            )
        except TypeError:
            # older signature without windows kw
            allowed, state = await rr._maintenance_gate_for_hosts(session, hosts, {"maintenance": maintenance})
        filtered = int((state or {}).get("filtered", 0) or 0)
        if filtered and len(allowed) < len(hosts):
            return _make_result(defn, GateStatus.failed.value,
                                {"allowed": len(allowed), "filtered": filtered, "state": state},
                                f"maintenance_window_blocked: {filtered}")
        return _make_result(defn, GateStatus.passed.value,
                            {"allowed": len(allowed), "filtered": filtered, "state": state}, "ok")

    # No session/windows: pass if no blocking window declared
    return _make_result(defn, GateStatus.passed.value, {"hosts": len(hosts)}, "no window enforcement")


async def _restore_drill(defn: GateDefinition, ctx: dict) -> GateResult:
    drill = ctx.get("drill_result")
    if drill is None:
        # fall back to run_summary
        rs = ctx.get("run_summary") or {}
        drill = rs.get("restore_drill") if isinstance(rs, dict) else None
    passed = False
    if isinstance(drill, dict):
        passed = bool(drill.get("passed", False))
    elif isinstance(drill, bool):
        passed = drill
    if not passed:
        return _make_result(defn, GateStatus.failed.value, {"drill": drill}, "restore_drill_failed")
    return _make_result(defn, GateStatus.passed.value, {"drill": drill}, "ok")


async def _restore_capable(defn: GateDefinition, ctx: dict) -> GateResult:
    from restore_points.capabilities import host_capability
    hosts = _hosts(ctx)
    rs = ctx.get("run_summary") if isinstance(ctx.get("run_summary"), dict) else {}
    override = bool(ctx.get("override_irreversible", False)) or bool((rs or {}).get("override_irreversible", False))
    if override:
        return _make_result(defn, GateStatus.passed.value, {"override": True}, "override")
    bad = []
    obs = []
    for h in hosts:
        cap = host_capability(h)
        ok = cap.value != "none"
        obs.append({"id": _host_attr(h, "id"), "capability": cap.value, "ok": ok})
        if not ok:
            bad.append(_host_attr(h, "id"))
    if bad:
        return _make_result(defn, GateStatus.failed.value, {"hosts": obs},
                            f"no_restore_capability: {bad}")
    return _make_result(defn, GateStatus.passed.value, {"hosts": obs}, "ok")


async def _approval_granted(defn: GateDefinition, ctx: dict) -> GateResult:
    approval = ctx.get("approval", None)
    if approval is None:
        rs = ctx.get("run_summary") or {}
        if isinstance(rs, dict):
            approval = rs.get("approval_granted", rs.get("approved", False))
    if not bool(approval):
        return _make_result(defn, GateStatus.failed.value, {"approval": approval}, "approval_not_granted")
    return _make_result(defn, GateStatus.passed.value, {"approval": approval}, "ok")


async def _custom_probe(defn: GateDefinition, ctx: dict) -> GateResult:
    # context may carry a pre-computed result
    if "probe_result" in ctx:
        ok = bool(ctx.get("probe_result"))
        return _make_result(defn, GateStatus.passed.value if ok else GateStatus.failed.value,
                            {"probe_result": ok},
                            "ok" if ok else "probe_failed")
    results = ctx.get("probe_results")
    if isinstance(results, dict):
        name = (defn.parameters or {}).get("name")
        if name is not None and name in results:
            ok = bool(results[name])
            return _make_result(defn, GateStatus.passed.value if ok else GateStatus.failed.value,
                                {"probe_result": ok}, "ok" if ok else "probe_failed")
        if results:
            ok = all(bool(v) for v in results.values())
            return _make_result(defn, GateStatus.passed.value if ok else GateStatus.failed.value,
                                {"probe_results": results}, "ok" if ok else "probe_failed")
    # try HTTP probe if url provided
    url = (defn.parameters or {}).get("url") or (defn.parameters or {}).get("http_url")
    if url:
        try:
            import httpx
            timeout = int((defn.parameters or {}).get("timeout_seconds", 5))
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                ok = r.status_code < 400
                return _make_result(defn, GateStatus.passed.value if ok else GateStatus.failed.value,
                                    {"url": url, "status_code": r.status_code},
                                    "ok" if ok else f"http_{r.status_code}")
        except Exception as e:
            return _make_result(defn, GateStatus.failed.value, {"url": url}, f"probe_error: {e}")
    # no way to execute -> fail closed
    return _make_result(defn, GateStatus.failed.value, {"probe_results": results},
                        "probe_not_executed")


GATE_CHECKERS: dict[str, Callable[[GateDefinition, dict], Awaitable[GateResult]]] = {
    "restore_capable": _restore_capable,
    "host_reachable": _host_reachable,
    "maintenance_window": _maintenance_window,
    "disk_space": _disk_space,
    "snapshot_present": _snapshot_present,
    "service_health": _service_health,
    "heartbeat_alive": _heartbeat_alive,
    "custom_probe": _custom_probe,
    "drift_clean": _drift_clean,
    "restore_drill_passed": _restore_drill,
    "approval_granted": _approval_granted,
}


async def check_gate(defn: GateDefinition, ctx: dict) -> GateResult:
    checker = GATE_CHECKERS.get(defn.type)
    if checker is None:
        return _make_result(defn, GateStatus.failed.value, {}, f"unknown_gate_type: {defn.type}")
    try:
        return await checker(defn, ctx or {})
    except Exception as exc:  # pragma: no cover - defensive
        return _make_result(defn, GateStatus.failed.value, {}, f"checker_error: {exc}")