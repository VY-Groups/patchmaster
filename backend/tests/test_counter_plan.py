import os

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from policy_templates import list_templates
from noise_reduction import dedup_superseded, rank
from itsm import get_connector
from ai_assistant import answer


def test_policy_templates_count():
    t = list_templates()
    assert len(t) == 3
    assert any("Business Hours" in x["name"] for x in t)


def test_dedup_superseded():
    items = [{"id": "a", "supersedes": None}, {"id": "b", "supersedes": "a"}]
    out = dedup_superseded(items)
    assert len(out) == 1
    assert out[0]["id"] == "a"


def test_rank_exploited_first():
    items = [{"id": "x", "known_exploited": False, "cvss": 9}, {"id": "y", "known_exploited": True, "cvss": 5}]
    out = rank(items)
    assert out[0]["id"] == "y"


def test_itsm_connector():
    c = get_connector("jira")
    assert c.name == "jira"


def test_ai_assistant_readonly():
    import asyncio
    r = asyncio.run(answer("q"))
    assert r["read_only"] is True