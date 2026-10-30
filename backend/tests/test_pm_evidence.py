import json, hashlib, subprocess, sys, os

def _make_bundle(items, job_id="j1", prev=None, tamper_hash=False):
    phs = []
    for it in items:
        ph = hashlib.sha256(json.dumps(it.get("payload", {}), sort_keys=True).encode()).hexdigest()
        it["payload_hash"] = ph
        phs.append(ph)
    h = hashlib.sha256()
    if prev:
        h.update(prev.encode())
    for x in sorted(phs):
        h.update(x.encode())
    h.update(job_id.encode())
    bh = h.hexdigest()
    if tamper_hash:
        bh = "0" * 64
    return {"bundle_hash": bh, "item_count": len(items), "items": items,
            "job_id": job_id, "previous_bundle_hash": prev}


def test_removed_step_fails():
    items = [{"step": "patch", "kind": "result", "payload": {"ok": True}}]
    b = _make_bundle(items)
    policy = {"required_steps": ["patch", "verify"]}
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mktemp(suffix=".json"))
    p.write_text(json.dumps(b))
    pp = pathlib.Path(tempfile.mktemp(suffix=".json"))
    pp.write_text(json.dumps(policy))
    r = subprocess.run([sys.executable, "scripts/pm_evidence.py", str(p), "--policy", str(pp)],
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/..")
    assert r.returncode == 1
    assert "missing required steps" in r.stdout


def test_broken_chain_fails():
    items = [{"step": "patch", "kind": "result", "payload": {"ok": True}}]
    b = _make_bundle(items)
    b["previous_bundle_hash"] = "abc"
    # recompute hash with prev so payload matches, but claim prev is wrong chain by tampering prev
    b2 = _make_bundle(items, prev="xyz")
    b2["previous_bundle_hash"] = "abc"  # mismatched previous
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mktemp(suffix=".json"))
    p.write_text(json.dumps(b2))
    r = subprocess.run([sys.executable, "scripts/pm_evidence.py", str(p)],
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/..")
    assert r.returncode == 1


def test_valid_passes():
    items = [{"step": "patch", "kind": "result", "payload": {"ok": True}}]
    b = _make_bundle(items)
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mktemp(suffix=".json"))
    p.write_text(json.dumps(b))
    r = subprocess.run([sys.executable, "scripts/pm_evidence.py", str(p)],
                       capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/..")
    assert r.returncode == 0
    assert "PASS" in r.stdout