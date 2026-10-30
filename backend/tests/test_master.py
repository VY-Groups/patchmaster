import asyncio
import base64
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Ensure we import backend.main, not agent.main
sys.path.insert(0, str(Path(__file__).parent.parent))
import license as lic
import monitoring_manager as mm
import api.monitoring as monitoring
import api.register_v2 as register_v2
import prometheus_targets
import main as backend_app
from fastapi.testclient import TestClient
import api.metrics as metrics_api


os.environ.setdefault("LICENSE_SIGN_KEY", "test-sign-key")
SIGN_KEY = os.environ["LICENSE_SIGN_KEY"]


def _make_key(no_bind: bool, hw_id: str = "", days: int = 30) -> str:
    """Build a signed v3 license payload for tests."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    payload = {
        "v": 3,
        "license_id": "test-lic",
        "tier": "enterprise",
        "tier_label": "Enterprise (Advance)",
        "features": lic.TIER_FEATURES["enterprise"],
        "plan": "testing",
        "plan_label": "Testing (30 Days)",
        "customer": "Test Customer",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "max_hosts": 0,
        "hw_id": "" if no_bind else hw_id,
        "no_bind": no_bind,
        "version_compat": "2.x",
        "tool_version": "2.0",
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(SIGN_KEY.encode(), payload_b64.encode(), lic.hashlib.sha256).hexdigest()
    return f"PM1-{payload_b64}.{signature}"


def _make_public_key(no_bind: bool, private_key: Ed25519PrivateKey, hw_id: str = "", days: int = 30) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    payload = {
        "v": 4,
        "license_id": "test-lic-pub",
        "tier": "enterprise",
        "tier_label": "Enterprise (Advance)",
        "features": lic.TIER_FEATURES["enterprise"],
        "plan": "testing",
        "plan_label": "Testing (30 Days)",
        "customer": "Test Customer",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "max_hosts": 0,
        "hw_id": "" if no_bind else hw_id,
        "no_bind": no_bind,
        "version_compat": "2.x",
        "tool_version": "2.0",
        "sig_alg": "ed25519",
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = private_key.sign(payload_b64.encode()).hex()
    return f"PM1-{payload_b64}.{signature}"


def _make_pm2_key(no_bind: bool, signing_private_key: Ed25519PrivateKey, decrypt_private_key: X25519PrivateKey, hw_id: str = "", days: int = 30) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    payload = {
        "v": 5,
        "license_id": "test-lic-pm2",
        "tier": "enterprise",
        "tier_label": "Enterprise (Advance)",
        "features": lic.TIER_FEATURES["enterprise"],
        "plan": "testing" if no_bind else "trial",
        "plan_label": "Testing (30 Days)" if no_bind else "Trial (45 Days)",
        "customer": "Test Customer",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_hosts": 0,
        "hw_id": "" if no_bind else hw_id,
        "no_bind": no_bind,
        "binding_mode": "portable" if no_bind else "hardware_id",
        "version_compat": "2.x",
        "tool_version": "2.0",
        "license_format": "PM2",
    }
    header = {
        "v": 5,
        "license_id": payload["license_id"],
        "sig_alg": "ed25519",
        "enc_alg": "x25519-aes256gcm",
    }
    header_b64 = base64.urlsafe_b64encode(
        json.dumps(header, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    recipient_public = decrypt_private_key.public_key()
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public = ephemeral_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    shared_secret = ephemeral_private.exchange(recipient_public)
    aead_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"patchmaster-pm2-license-v1",
    ).derive(shared_secret)
    nonce = b"\x01" * 12
    ciphertext = AESGCM(aead_key).encrypt(
        nonce,
        json.dumps(payload, separators=(",", ":")).encode(),
        header_b64.encode(),
    )
    envelope = {
        "epk": base64.urlsafe_b64encode(ephemeral_public).decode().rstrip("="),
        "nonce": base64.urlsafe_b64encode(nonce).decode().rstrip("="),
        "ct": base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
    }
    envelope_b64 = base64.urlsafe_b64encode(
        json.dumps(envelope, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signed_message = f"{header_b64}.{envelope_b64}"
    signature = signing_private_key.sign(signed_message.encode()).hex()
    return f"PM2-{header_b64}.{envelope_b64}.{signature}"


def _pm2_license(monkeypatch, no_bind: bool, hw_id: str = "", days: int = 30) -> str:
    """Build a PM2 key and wire its test keypair into license._load_setting.

    PM2 is the only accepted format (decode_license rejects anything else),
    so tests that need a decodable key must go through this helper.
    """
    signing_private_key = Ed25519PrivateKey.generate()
    verify_public_key = base64.urlsafe_b64encode(
        signing_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode().rstrip("=")
    decrypt_private_key = X25519PrivateKey.generate()
    decrypt_private_b64 = base64.urlsafe_b64encode(
        decrypt_private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode().rstrip("=")
    key = _make_pm2_key(
        no_bind=no_bind,
        hw_id=hw_id,
        days=days,
        signing_private_key=signing_private_key,
        decrypt_private_key=decrypt_private_key,
    )
    original_load_setting = lic._load_setting

    def fake_load_setting(name: str) -> str:
        if name == "LICENSE_VERIFY_PUBLIC_KEY":
            return verify_public_key
        if name == "LICENSE_DECRYPT_PRIVATE_KEY":
            return decrypt_private_b64
        if name == "LICENSE_SIGN_KEY":
            return ""
        return original_load_setting(name)

    monkeypatch.setattr(lic, "_load_setting", fake_load_setting)
    return key


# ── License tests ──
def test_license_allows_no_bind(monkeypatch):
    key = _pm2_license(monkeypatch, no_bind=True, hw_id="00:11:22:33:44:55")
    monkeypatch.setattr(lic, "get_mac_addresses", lambda: ["aa:bb:cc:dd:ee:ff"])
    payload = lic.decode_license(key)
    assert payload["no_bind"] is True
    assert payload["hw_id"] == ""


def test_license_rejects_legacy_pm1_format(monkeypatch):
    """PM1 keys (plaintext HMAC and Ed25519) must be refused: only encrypted PM2 is accepted."""
    monkeypatch.setattr(lic, "get_mac_addresses", lambda: ["aa:bb:cc:dd:ee:ff"])
    legacy_hmac = _make_key(no_bind=True)
    legacy_ed25519 = _make_public_key(
        no_bind=True, private_key=Ed25519PrivateKey.generate()
    )
    for legacy_key in (legacy_hmac, legacy_ed25519):
        with pytest.raises(lic.LicenseError, match="Only PM2"):
            lic.decode_license(legacy_key)


def test_license_accepts_pm2_encrypted_license(monkeypatch):
    signing_private_key = Ed25519PrivateKey.generate()
    verify_public_key = base64.urlsafe_b64encode(
        signing_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode().rstrip("=")
    decrypt_private_key = X25519PrivateKey.generate()
    decrypt_private_b64 = base64.urlsafe_b64encode(
        decrypt_private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode().rstrip("=")
    key = _make_pm2_key(no_bind=True, signing_private_key=signing_private_key, decrypt_private_key=decrypt_private_key)
    original_load_setting = lic._load_setting

    def fake_load_setting(name: str) -> str:
        if name == "LICENSE_VERIFY_PUBLIC_KEY":
            return verify_public_key
        if name == "LICENSE_DECRYPT_PRIVATE_KEY":
            return decrypt_private_b64
        if name == "LICENSE_SIGN_KEY":
            return ""
        return original_load_setting(name)

    monkeypatch.setattr(lic, "_load_setting", fake_load_setting)
    monkeypatch.setattr(lic, "get_mac_addresses", lambda: ["aa:bb:cc:dd:ee:ff"])
    payload = lic.decode_license(key)
    assert payload["license_id"] == "test-lic-pm2"
    assert payload["license_format"] == "PM2"
    assert payload["enc_alg"] == "x25519-aes256gcm"


def test_license_pm2_enforces_binding(monkeypatch):
    signing_private_key = Ed25519PrivateKey.generate()
    verify_public_key = base64.urlsafe_b64encode(
        signing_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode().rstrip("=")
    decrypt_private_key = X25519PrivateKey.generate()
    decrypt_private_b64 = base64.urlsafe_b64encode(
        decrypt_private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode().rstrip("=")
    key = _make_pm2_key(
        no_bind=False,
        hw_id="00:11:22:33:44:55",
        signing_private_key=signing_private_key,
        decrypt_private_key=decrypt_private_key,
    )
    original_load_setting = lic._load_setting

    def fake_load_setting(name: str) -> str:
        if name == "LICENSE_VERIFY_PUBLIC_KEY":
            return verify_public_key
        if name == "LICENSE_DECRYPT_PRIVATE_KEY":
            return decrypt_private_b64
        if name == "LICENSE_SIGN_KEY":
            return ""
        return original_load_setting(name)

    monkeypatch.setattr(lic, "_load_setting", fake_load_setting)
    monkeypatch.setattr(lic, "get_mac_addresses", lambda: ["aa:bb:cc:dd:ee:ff"])
    with pytest.raises(lic.LicenseError):
        lic.decode_license(key)


def test_license_info_exposes_epochs_and_flags(monkeypatch, tmp_path):
    key_path = tmp_path / "license.key"
    key = _pm2_license(monkeypatch, no_bind=True)
    key_path.write_text(key)

    monkeypatch.setattr(lic, "LICENSE_FILE", str(key_path))
    lic.invalidate_cache()

    info = lic.get_license_info(force_refresh=True)
    assert info["valid"] is True
    assert isinstance(info["issued_at_ts"], int)
    assert isinstance(info["expires_at_ts"], int)
    assert info["binding_required"] is False
    assert info["no_bind"] is True
    assert "monitoring" in info["features"]


def test_decode_license_accepts_wrapped_vendor_text(monkeypatch):
    key = _pm2_license(monkeypatch, no_bind=True)
    wrapped = f"License key:\n\n  {key}\n\nUse this in PatchMaster."
    monkeypatch.setattr(lic, "get_mac_addresses", lambda: ["aa:bb:cc:dd:ee:ff"])
    payload = lic.decode_license(wrapped)
    assert payload["license_id"] == "test-lic-pm2"


def test_license_info_reads_json_wrapped_key_file(monkeypatch, tmp_path):
    key_path = tmp_path / "license.key"
    key = _pm2_license(monkeypatch, no_bind=True)
    key_path.write_text(json.dumps({"license_key": key}))

    monkeypatch.setattr(lic, "LICENSE_FILE", str(key_path))
    lic.invalidate_cache()

    info = lic.get_license_info(force_refresh=True)
    assert info["valid"] is True
    assert info["activated"] is True
    assert info["license_id"] == "test-lic-pm2"


# ── Monitoring manager tests (systemd calls stubbed) ──
def test_monitoring_status_stub(monkeypatch):
    fake = {"prometheus": {"installed": True, "running": True}}
    monkeypatch.setattr(mm, "_run_ctl", lambda action, arg="", timeout=300: {"ok": True, "data": fake})
    status = mm.get_status()
    assert status == fake


def test_monitoring_enforce_uses_features(monkeypatch):
    calls = []

    def stub(action, arg="", timeout=300):
        calls.append((action, arg))
        return {"ok": True, "data": {"prometheus": {"installed": True, "running": arg == "1"}}}

    monkeypatch.setattr(mm, "_run_ctl", stub)
    result = mm.enforce_license(["monitoring"])
    assert calls[-1] == ("enforce", "1")
    assert result["prometheus"]["running"] is True

    calls.clear()
    result = mm.enforce_license([])
    assert calls[-1] == ("enforce", "0")


# ── Monitoring API contract (without hitting DB/systemd) ──
def test_monitoring_status_marks_licensed(monkeypatch):
    monkeypatch.setattr(monitoring, "get_license_info", lambda: {"features": ["monitoring"], "tier": "enterprise", "tier_label": "Enterprise"})
    monkeypatch.setattr(mm, "get_status", lambda: {"prometheus": {"installed": True, "running": True}})

    resp = asyncio.run(monitoring.monitoring_status(user=None))
    assert resp["licensed"] is True
    assert resp["tier"] == "enterprise"
    assert resp["services"]["prometheus"]["running"] is True


def test_monitoring_probe_rejects_backend_health_for_grafana():
    response = httpx.Response(200, json={"status": "healthy", "version": "2.0.0"})
    assert monitoring._response_matches_service("grafana", response) is False


def test_monitoring_probe_accepts_real_grafana_health():
    response = httpx.Response(200, json={"database": "ok", "version": "12.0.0"})
    assert monitoring._response_matches_service("grafana", response) is True


def test_rewrite_location_preserves_public_absolute_url():
    location = "http://172.24.52.222:8000/api/monitoring/embed/grafana/login?redirect=%2F"
    rewritten = monitoring._rewrite_location(
        location,
        "http://127.0.0.1:3001",
        "/api/monitoring/embed/grafana/",
    )
    assert rewritten == "/api/monitoring/embed/grafana/login?redirect=%2F"


def test_rewrite_location_rewrites_upstream_absolute_url():
    rewritten = monitoring._rewrite_location(
        "http://127.0.0.1:9090/graph",
        "http://127.0.0.1:9090",
        "/api/monitoring/embed/prometheus/",
    )
    assert rewritten == "/api/monitoring/embed/prometheus/graph"


def test_build_upstream_service_url_uses_proxy_prefix_root():
    url = monitoring._build_upstream_service_url(
        "http://127.0.0.1:3001",
        "/api/monitoring/embed/grafana/",
        "",
    )
    assert url == "http://127.0.0.1:3001/api/monitoring/embed/grafana/"


def test_build_upstream_service_url_preserves_prometheus_graph_path():
    url = monitoring._build_upstream_service_url(
        "http://127.0.0.1:9090",
        "/api/monitoring/embed/prometheus/",
        "graph",
        "g0.expr=up",
    )
    assert url == "http://127.0.0.1:9090/api/monitoring/embed/prometheus/graph?g0.expr=up"


def test_heartbeat_ensures_schema_before_lookup(monkeypatch):
    class FakeHost:
        id = 7
        hostname = "host-1"
        ip = "172.24.50.211"
        os = "Ubuntu"
        os_version = "24.04"
        kernel = "6.8.0"
        arch = "x86_64"
        agent_version = ""
        agent_id = "agent-1"
        agent_token = "token-1"
        is_online = False
        last_heartbeat = None

    class FakeRequest:
        def __init__(self):
            self.client = type("Client", (), {"host": "172.24.50.211"})()

        async def json(self):
            return {
                "agent_id": "agent-1",
                "agent_token": "token-1",
                "hostname": "host-1",
                "os": "Ubuntu",
                "os_version": "24.04",
                "kernel": "6.8.0",
                "arch": "x86_64",
                "ip": "172.24.50.211",
                "agent_version": "2.0.0",
            }

    class FakeDB:
        def add(self, _obj):
            return None

        async def flush(self):
            return None

        async def commit(self):
            return None

    state = {"schema": False}

    async def fake_ensure_schema(_db):
        state["schema"] = True

    async def fake_find_by_agent_id(_db, agent_id):
        assert state["schema"] is True
        assert agent_id == "agent-1"
        return FakeHost()

    async def fake_find_legacy(_db, hostname, ip, incoming_agent_id=None):
        raise AssertionError("legacy lookup should not run when agent_id matches an existing host")

    async def fake_allocate_hostname(_db, hostname, os_name):
        return f"{hostname}-linux"

    async def fake_group(_db, host, os_name):
        assert host.agent_id == "agent-1"
        assert host.agent_version == "2.0.0"
        assert os_name == "Ubuntu"

    monkeypatch.setattr(register_v2, "_ensure_host_schema", fake_ensure_schema)
    monkeypatch.setattr(register_v2, "_find_host_by_agent_id", fake_find_by_agent_id)
    monkeypatch.setattr(register_v2, "_find_legacy_host", fake_find_legacy)
    monkeypatch.setattr(register_v2, "_allocate_hostname", fake_allocate_hostname)
    monkeypatch.setattr(register_v2, "_ensure_os_family_group", fake_group)

    resp = asyncio.run(register_v2.heartbeat(FakeRequest(), FakeDB()))
    assert resp == {"status": "ok"}


def test_heartbeat_returns_plaintext_when_schema_setup_fails(monkeypatch):
    class FakeRequest:
        client = type("Client", (), {"host": "172.24.50.211"})()

        async def json(self):
            return {"hostname": "host-1", "ip": "172.24.50.211"}

    async def fake_ensure_schema(_db):
        raise RuntimeError("schema unavailable")

    monkeypatch.setattr(register_v2, "_ensure_host_schema", fake_ensure_schema)

    resp = asyncio.run(register_v2.heartbeat(FakeRequest(), object()))
    assert resp.status_code == 500
    assert resp.body == b"heartbeat failed"


def test_ensure_os_family_group_persistent_host_avoids_relationship_lazy_load(monkeypatch):
    desired = register_v2.HostGroup(id=11, name="Windows", description="")
    other = register_v2.HostGroup(id=22, name="Prod", description="")
    stale_family = register_v2.HostGroup(id=33, name="Debian/Ubuntu", description="")

    class PersistentHost:
        id = 7

        @property
        def groups(self):
            raise AssertionError("persistent path should not touch host.groups directly")

    class FakeScalarResult:
        def __init__(self, values):
            self._values = values

        def all(self):
            return self._values

    class FakeResult:
        def __init__(self, values):
            self._values = values

        def scalars(self):
            return FakeScalarResult(self._values)

    class FakeDB:
        def __init__(self):
            self.calls = []

        async def execute(self, stmt):
            text = str(stmt)
            self.calls.append(text)
            if "FROM host_groups JOIN host_group_assoc" in text:
                return FakeResult([other, stale_family])
            return None

    class FakeState:
        pending = False
        transient = False

    async def fake_group(_db, name, desc):
        assert name == "Windows"
        return desired

    monkeypatch.setattr(register_v2, "_get_or_create_group", fake_group)
    monkeypatch.setattr(register_v2, "sa_inspect", lambda _host: FakeState())

    db = FakeDB()
    asyncio.run(register_v2._ensure_os_family_group(db, PersistentHost(), "Windows 11"))

    assert any("DELETE FROM host_group_assoc" in call for call in db.calls)
    inserts = [call for call in db.calls if "INSERT INTO host_group_assoc" in call]
    assert len(inserts) == 2


def test_prometheus_config_uses_local_backend_and_file_sd():
    text = prometheus_targets.prometheus_config_text(8000)
    assert "localhost:8000" in text
    assert "file_sd_configs" in text
    assert "/opt/patchmaster/monitoring/prometheus/agents/*.json" in text
    assert "backend:8000" not in text


def test_host_details_dashboard_has_os_detection_fallbacks():
    dashboard_path = Path(__file__).resolve().parents[2] / "monitoring" / "grafana" / "dashboards" / "patchmaster-host-details.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    os_panel = next(panel for panel in dashboard["panels"] if panel.get("title") == "Host OS Kind")
    expr = os_panel["targets"][0]["expr"]
    assert "patchmaster_host_info" in expr
    assert "system_disk_usage_percent" in expr


def test_sync_prometheus_agent_targets_writes_known_online_hosts(tmp_path, monkeypatch):
    class FakeResult:
        def all(self):
            return [
                ("172.24.50.211", "Windows"),
                ("127.0.0.1", "Linux"),
                ("172.24.52.10", "Linux"),
            ]

    class FakeDB:
        async def execute(self, _stmt):
            return FakeResult()

    sd_dir = tmp_path / "agents"
    sd_file = sd_dir / "patchmaster-agents.json"
    monkeypatch.setattr(prometheus_targets, "PROM_AGENT_SD_DIR", sd_dir)
    monkeypatch.setattr(prometheus_targets, "PROM_AGENT_SD_FILE", sd_file)
    monkeypatch.setattr(prometheus_targets, "AGENT_METRICS_PORT", 9100)

    targets = asyncio.run(prometheus_targets.sync_prometheus_agent_targets(FakeDB()))
    assert targets == ["172.24.50.211:9100", "172.24.52.10:9100"]
    data = json.loads(sd_file.read_text())
    assert data == [
        {"targets": ["172.24.50.211:9100"], "labels": {"component": "agent", "host_ip": "172.24.50.211", "host_os": "windows", "host_kind": "windows"}},
        {"targets": ["172.24.52.10:9100"], "labels": {"component": "agent", "host_ip": "172.24.52.10", "host_os": "linux", "host_kind": "linux"}},
    ]


def test_sync_prometheus_agent_targets_adds_extra_ports_for_duplicate_ip(tmp_path, monkeypatch):
    class FakeResult:
        def all(self):
            return [
                ("172.24.50.211", "Windows"),
                ("172.24.50.211", "Ubuntu"),
            ]

    class FakeDB:
        async def execute(self, _stmt):
            return FakeResult()

    sd_dir = tmp_path / "agents"
    sd_file = sd_dir / "patchmaster-agents.json"
    monkeypatch.setattr(prometheus_targets, "PROM_AGENT_SD_DIR", sd_dir)
    monkeypatch.setattr(prometheus_targets, "PROM_AGENT_SD_FILE", sd_file)
    monkeypatch.setattr(prometheus_targets, "AGENT_METRICS_PORT", 9100)

    targets = asyncio.run(prometheus_targets.sync_prometheus_agent_targets(FakeDB()))
    # Both Windows and Linux share port 9100. Windows takes precedence so the
    # single emitted entry carries host_os="windows".
    assert targets == ["172.24.50.211:9100"]
    data = json.loads(sd_file.read_text())
    assert len(data) == 1
    assert data[0]["targets"] == ["172.24.50.211:9100"]
    assert data[0]["labels"]["host_os"] == "windows"
    assert data[0]["labels"]["component"] == "agent"


def test_sanitize_upstream_query_drops_backend_token():
    query = monitoring._sanitize_upstream_query("token=abc123&kiosk=tv&orgId=1")
    assert query == "kiosk=tv&orgId=1"


def test_monitoring_probe_tries_prefixed_health_paths(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            self.calls.append(url)
            if url.endswith("/api/monitoring/embed/grafana/api/health"):
                return httpx.Response(200, json={"database": "ok"})
            return httpx.Response(404, text="not found")

    fake_client = FakeClient()
    monkeypatch.setattr(monitoring, "_candidate_service_bases", lambda service: ["http://127.0.0.1:3001"])
    monkeypatch.setattr(monitoring.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    base, port = asyncio.run(monitoring._resolve_service_base("grafana"))
    assert base == "http://127.0.0.1:3001"
    assert port == 3001
    assert any(url.endswith("/api/monitoring/embed/grafana/api/health") for url in fake_client.calls)


def test_monitoring_probe_marks_reachable_service_running(monkeypatch):
    async def fake_resolve(service):
        assert service == "grafana"
        return "http://127.0.0.1:3001", 3001

    monkeypatch.setattr(monitoring, "_resolve_service_base", fake_resolve)
    result = asyncio.run(monitoring._probe_service_http("grafana", {"installed": False, "running": False}))
    assert result["installed"] is True
    assert result["running"] is True
    assert result["port"] == 3001


def test_monitoring_health_uses_probed_service_state(monkeypatch):
    monkeypatch.setattr(mm, "get_status", lambda: {"grafana-server.service": {"installed": False, "running": False, "port": 3001}})

    async def fake_resolve(service):
        assert service == "grafana"
        return "http://127.0.0.1:3001", 3001

    monkeypatch.setattr(monitoring, "_resolve_service_base", fake_resolve)

    resp = asyncio.run(monitoring.monitoring_health(user=None))
    assert resp["services"]["grafana-server.service"]["installed"] is True
    assert resp["services"]["grafana-server.service"]["running"] is True


def test_health_endpoint(monkeypatch, tmp_path):
    # Avoid real DB/systemctl during TestClient lifespan
    async def no_init_db():
        return None
    monkeypatch.setattr(backend_app, "init_db", no_init_db)
    monkeypatch.setattr(backend_app.monitoring_manager, "enforce_license", lambda features: {})

    client = TestClient(backend_app.app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json().get("status") == "healthy"


def test_license_status_endpoint(monkeypatch, tmp_path):
    key_path = tmp_path / "license.key"
    key = _pm2_license(monkeypatch, no_bind=True)
    key_path.write_text(key)

    monkeypatch.setattr(lic, "LICENSE_FILE", str(key_path))
    lic.invalidate_cache()

    async def no_init_db():
        return None
    monkeypatch.setattr(backend_app, "init_db", no_init_db)
    monkeypatch.setattr(backend_app.monitoring_manager, "enforce_license", lambda features: {})

    client = TestClient(backend_app.app)
    res = client.get("/api/license/status")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["plan"] == "testing"
    assert data["tier"] == "enterprise"


def test_metrics_endpoint(monkeypatch):
    # Prevent DB work inside refresh_gauges
    async def _no_refresh():
        return None
    monkeypatch.setattr(metrics_api, "refresh_gauges", _no_refresh)
    # Skip init/monitoring enforcement
    async def no_init_db():
        return None
    monkeypatch.setattr(backend_app, "init_db", no_init_db)
    monkeypatch.setattr(backend_app.monitoring_manager, "enforce_license", lambda features: {})

    client = TestClient(backend_app.app)
    res = client.get("/metrics")
    assert res.status_code == 200
    assert b"patchmaster" in res.content
