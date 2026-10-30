"""PMRS backtest harness (S3-5)."""

from __future__ import annotations

from risk_score import compute_pmrs


def backtest(cases: list[dict]) -> dict:
    """cases: list of {factors, known_exploited (bool)}. Returns ordering accuracy."""
    scored = []
    for c in cases:
        s = compute_pmrs(c["factors"])["score"]
        scored.append((s, bool(c.get("known_exploited", False))))
    # sort desc by score
    scored.sort(key=lambda x: -x[0])
    # check that known-exploited items rank above non-exploited on average
    exploited_ranks = [i for i, (_, ke) in enumerate(scored) if ke]
    non_ranks = [i for i, (_, ke) in enumerate(scored) if not ke]
    avg_exp = sum(exploited_ranks) / len(exploited_ranks) if exploited_ranks else 0
    avg_non = sum(non_ranks) / len(non_ranks) if non_ranks else 0
    return {"items": len(scored), "exploited_avg_rank": round(avg_exp, 2),
            "non_exploited_avg_rank": round(avg_non, 2),
            "exploited_ranked_higher": avg_exp < avg_non}