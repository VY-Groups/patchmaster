import os

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from risk_score import compute_pmrs


def test_higher_for_known_exploited():
    a = compute_pmrs({"severity": 9, "known_exploited": True, "patch_available": True})["score"]
    b = compute_pmrs({"severity": 9, "known_exploited": False, "patch_available": True})["score"]
    assert a > b


def test_breakdown_present():
    r = compute_pmrs({"severity": 7})
    assert "breakdown" in r
    assert "score" in r


def test_range():
    r = compute_pmrs({"severity": 10, "exploit_likelihood": 1.0, "known_exploited": True,
                      "exposure": 1.0, "criticality": 1.0, "patch_available": True})["score"]
    assert 0 <= r <= 100