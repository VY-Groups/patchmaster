"""PatchMaster Risk Score (PMRS) (S3-5)."""

from __future__ import annotations

from typing import Any, Optional


def compute_pmrs(factors: dict, weights: Optional[dict] = None) -> dict:
    """Compute PMRS (0-100) with breakdown. factors: severity, exploit_likelihood,
    known_exploited, exposure, criticality, compensating_controls, patch_available.
    """
    w = weights or {}
    sev = float(factors.get("severity", 5.0))  # 0-10
    exploit = float(factors.get("exploit_likelihood", 0.0))  # 0-1
    known = 1.0 if factors.get("known_exploited") else 0.0
    exposure = float(factors.get("exposure", 0.5))  # 0-1
    criticality = float(factors.get("criticality", 0.5))  # 0-1
    comp = float(factors.get("compensating_controls", 0.0))  # 0-1 (reduces)
    patch = 1.0 if factors.get("patch_available") else 0.0

    # weights (defaults)
    ws = {
        "severity": w.get("severity", 0.30),
        "exploit": w.get("exploit", 0.25),
        "known": w.get("known", 0.15),
        "exposure": w.get("exposure", 0.15),
        "criticality": w.get("criticality", 0.10),
        "patch": w.get("patch", 0.05),
    }
    # comp reduces by up to 0.2
    base = (ws["severity"] * (sev / 10.0)
            + ws["exploit"] * exploit
            + ws["known"] * known
            + ws["exposure"] * exposure
            + ws["criticality"] * criticality
            + ws["patch"] * patch)
    score = base * (1.0 - 0.2 * comp)
    score = max(0.0, min(1.0, score)) * 100.0
    breakdown = {
        "severity": round(ws["severity"] * (sev / 10.0) * 100, 2),
        "exploit": round(ws["exploit"] * exploit * 100, 2),
        "known_exploited": round(ws["known"] * known * 100, 2),
        "exposure": round(ws["exposure"] * exposure * 100, 2),
        "criticality": round(ws["criticality"] * criticality * 100, 2),
        "patch_available": round(ws["patch"] * patch * 100, 2),
        "compensating_controls_reduction": round(0.2 * comp * 100, 2),
    }
    return {"score": round(score, 2), "breakdown": breakdown}