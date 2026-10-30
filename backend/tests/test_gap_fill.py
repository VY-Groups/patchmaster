import os, asyncio

os.environ.setdefault("JWT_SECRET", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

from playbooks import apply_playbook
from compliance_engine import run_controls
from auto_deploy import evaluate_rules
from pmrs_backtest import backtest
from airgap import validate_bundle
from deploy_flow import transition
from noise_reduction import dedup_superseded, rank


def _run(coro):
    return asyncio.run(coro)


def test_playbook_apply():
    async def exec(host, step):
        return True
    r = _run(apply_playbook({"name": "mp", "steps": [{"a": 1}, {"b": 2}]}, object(), exec))
    assert r["ok"] is True


def test_compliance_run():
    async def chk(host, c):
        return True
    r = _run(run_controls([{"control_id": "c1"}], [object()], chk))
    assert r[0]["status"] == "passed"


def test_auto_deploy():
    rules = [{"name": "r1", "enabled": True, "severities": ["Critical"], "categories": ["Security"]}]
    assert len(evaluate_rules(rules, {"severity": "Critical", "category": "Security", "app": "x"}, object())) == 1
    assert len(evaluate_rules(rules, {"severity": "Low", "category": "Security", "app": "x"}, object())) == 0


def test_pmrs_backtest():
    cases = [{"factors": {"severity": 9, "known_exploited": True}, "known_exploited": True},
             {"factors": {"severity": 9, "known_exploited": False}, "known_exploited": False}]
    r = backtest(cases)
    assert r["exploited_ranked_higher"] is True


def test_validate_bundle():
    import hashlib, json
    items = [{"step": "p", "payload": {"ok": True}}]
    ph = hashlib.sha256(json.dumps(items[0]["payload"], sort_keys=True).encode()).hexdigest()
    items[0]["payload_hash"] = ph
    h = hashlib.sha256()
    for x in sorted([ph]):
        h.update(x.encode())
    h.update(b"j1")
    b = {"bundle_hash": h.hexdigest(), "item_count": 1, "items": items, "job_id": "j1", "previous_bundle_hash": None}
    ok, fails = validate_bundle(b)
    assert ok is True
    # tamper
    b["items"][0]["payload"]["ok"] = False
    ok2, fails2 = validate_bundle(b)
    assert ok2 is False


def test_deploy_transition():
    assert transition("draft", "preview") == "preview"
    assert transition("preview", "publish") == "published"


def test_dedup():
    items = [{"id": "a"}, {"id": "b", "supersedes": "a"}]
    out = dedup_superseded(items)
    assert len(out) == 1