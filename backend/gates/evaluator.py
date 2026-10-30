"""S1-2 decision engine: evaluate gates and decide promote/hold/rollback."""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

from gates.model import GateDefinition, GateResult, GateDecision
from gates.checkers import check_gate, GATE_CHECKERS


def parse_gates(obj: Any, phase: str = "pre", ring: Any = None) -> list[GateDefinition]:
    """Extract GateDefinitions for a phase from rollout_config (+ optional ring override)."""
    cfg = obj if isinstance(obj, dict) else {}
    gates_cfg = cfg.get("gates") if isinstance(cfg.get("gates"), dict) else {}
    global_phase = gates_cfg.get(phase) if isinstance(gates_cfg, dict) else None
    ring_phase = None
    if isinstance(ring, dict):
        rg = ring.get("gates")
        if isinstance(rg, dict):
            ring_phase = rg.get(phase)
    chosen = ring_phase if ring_phase is not None else global_phase
    if not isinstance(chosen, list):
        return []
    return [GateDefinition.from_dict(d) for d in chosen if isinstance(d, dict)]


async def evaluate_gates(defns: Iterable[GateDefinition], ctx: dict) -> list[GateResult]:
    results: list[GateResult] = []
    for d in defns:
        results.append(await check_gate(d, ctx or {}))
    return results


def decide(results: Iterable[GateResult], defns: Iterable[GateDefinition],
           on_failure: str = "hold") -> GateDecision:
    defns_list = list(defns)
    results_list = list(results)
    # map type -> severity
    sev = {}
    for d in defns_list:
        sev[d.type] = d.severity
    failed_req = []
    failed_adv = []
    for r in results_list:
        st = r.status
        if st in ("passed", "overridden", "skipped"):
            continue
        if sev.get(r.gate_type, "required") == "advisory":
            failed_adv.append(r.gate_type)
        else:
            failed_req.append(r.gate_type)
    if failed_req:
        outcome = "rollback" if on_failure == "rollback" else "hold"
        return GateDecision(outcome=outcome, reason="required_gate_failed",
                            failed_required=failed_req, failed_advisory=failed_adv)
    return GateDecision(outcome="promote", reason="all_required_passed",
                        failed_required=[], failed_advisory=failed_adv)