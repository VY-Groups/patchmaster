import time
import requests
import socket
import platform
import os
import json
import subprocess
import logging
import shutil
from pathlib import Path
from logging.handlers import RotatingFileHandler
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

try:
    import psutil
except Exception:  # pragma: no cover - fallback when runtime is incomplete
    psutil = None

IS_WINDOWS = os.name == "nt"
AGENT_VERSION = os.environ.get("PATCHMASTER_AGENT_VERSION", "2.0.0")
_FIRMWARE_CACHE = None

# Paths and logging
DEV_ROOT = Path.cwd() / ".patchmaster-agent"


def ensure_dir(primary: Path, fallback: Path) -> Path:
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except PermissionError:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


STATE_DIR = ensure_dir(
    Path(
        os.environ.get("PATCHMASTER_AGENT_STATE")
        or (
            r"C:\ProgramData\PatchMaster-Agent"
            if IS_WINDOWS
            else "/var/lib/patch-agent"
        )
    ),
    DEV_ROOT / "state",
)
LOG_DIR = ensure_dir(
    Path(
        os.environ.get("PATCHMASTER_AGENT_LOG_DIR")
        or (
            r"C:\ProgramData\PatchMaster-Agent\logs"
            if IS_WINDOWS
            else "/var/log/patch-agent"
        )
    ),
    DEV_ROOT / "logs",
)

logger = logging.getLogger("patchmaster-agent-heartbeat")
logger.setLevel(logging.INFO)

# Set up formatter
fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

# Try to set up file logging, fall back to console-only if permission denied (e.g., during tests)
try:
    fh = RotatingFileHandler(
        LOG_DIR / "agent-heartbeat.log", maxBytes=1_000_000, backupCount=3
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
except (PermissionError, OSError) as e:
    # Running without admin privileges (e.g., in tests) - use console logging only
    pass

console = logging.StreamHandler()
console.setFormatter(fmt)
logger.addHandler(console)


def safe_call(fn, default=None):
    try:
        return fn()
    except Exception as e:
        logger.warning(f"{fn.__name__} failed: {e}")
        return default


def _write_private_text(path: Path, value: str) -> None:
    path.write_text(value)
    if not IS_WINDOWS:
        try:
            path.chmod(0o600)
        except Exception:
            logger.warning("Failed to chmod %s to 600", path)


def get_real_ip():
    """Get host IP; keep it Windows-safe."""
    # UDP socket trick works on Windows and Linux
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        logger.debug("socket ip detection failed", exc_info=True)
    # Linux specific: ip route / hostname -I
    if not IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["ip", "route", "get", "1.1.1.1"], text=True, timeout=5
            )
            parts = out.split()
            for i, token in enumerate(parts):
                if token == "src" and i + 1 < len(parts):
                    ip = parts[i + 1].split("/")[0]
                    if ip and not ip.startswith("127."):
                        return ip
        except Exception:
            logger.debug("ip route failed", exc_info=True)
        try:
            out = subprocess.check_output(
                ["hostname", "-I"], text=True, timeout=5
            ).strip()
            for candidate in out.split():
                if candidate.count(".") == 3 and not candidate.startswith("127."):
                    return candidate
        except Exception:
            logger.debug("hostname -I failed", exc_info=True)
    # Fallback
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return ip.split("/")[0]
    except Exception:
        return "0.0.0.0"


def get_os_info():
    """Return (name, version) cross-platform."""
    if IS_WINDOWS:
        ver = platform.win32_ver()
        version = ver[1] or platform.release()
        return "Windows", version
    try:
        info = {}
        with open("/etc/os-release") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, val = line.partition("=")
                    info[key] = val.strip('"')
        name = info.get("NAME", info.get("ID", "Linux"))
        version = info.get("VERSION_ID", info.get("VERSION", ""))

        # Detect WSL (Windows Subsystem for Linux). Docker Desktop containers
        # see the same WSL2 kernel, so /.dockerenv has to veto the prefix -
        # otherwise every fleet container reports itself as a WSL host.
        if not os.path.exists("/.dockerenv"):
            try:
                with open("/proc/version") as f:
                    proc_version = f.read().lower()
                    if "wsl" in proc_version or "microsoft" in proc_version:
                        name = f"WSL {name}"  # Prefix with WSL for identification
            except Exception:
                pass

        return name, version
    except Exception:
        return platform.system(), platform.version()


def _stable_agent_id() -> str:
    agent_id_path = STATE_DIR / "agent_id"
    try:
        if agent_id_path.exists():
            value = agent_id_path.read_text().strip()
            if value:
                return value
        value = str(uuid4())
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        agent_id_path.write_text(value)
        return value
    except Exception:
        logger.warning("agent_id persistence failed", exc_info=True)
        return f"ephemeral-{uuid4()}"


def _site_name() -> str:
    return (
        os.environ.get("PATCHMASTER_SITE")
        or os.environ.get("PATCHMASTER_LOCATION")
        or ""
    ).strip()[:120]


def _linux_firmware_inventory() -> dict:
    efi_root = Path("/sys/firmware/efi")
    efivars_root = efi_root / "efivars"
    inventory = {
        "boot_mode": "uefi" if efi_root.exists() else "bios",
        "uefi_present": bool(efi_root.exists()),
        "secure_boot_enabled": None,
    }
    if efivars_root.exists():
        try:
            secure_boot_vars = sorted(efivars_root.glob("SecureBoot-*"))
            if secure_boot_vars:
                raw = secure_boot_vars[0].read_bytes()
                if raw:
                    inventory["secure_boot_enabled"] = bool(raw[-1])
                    return inventory
        except Exception:
            logger.debug("Failed to read SecureBoot efivar", exc_info=True)
    if shutil.which("mokutil"):
        try:
            out = subprocess.check_output(
                ["mokutil", "--sb-state"], text=True, timeout=5
            )
            lowered = out.lower()
            if "secureboot enabled" in lowered:
                inventory["secure_boot_enabled"] = True
            elif "secureboot disabled" in lowered:
                inventory["secure_boot_enabled"] = False
        except Exception:
            logger.debug("mokutil secure boot probe failed", exc_info=True)
    return inventory


def _windows_firmware_inventory() -> dict:
    script = r"""
    $firmware = $null
    try {
      $firmware = (Get-ComputerInfo -Property BiosFirmwareType).BiosFirmwareType
    } catch {}
    $secureBoot = $null
    try {
      $secureBoot = Confirm-SecureBootUEFI
    } catch {}
    @{
      boot_mode = if ($firmware) { "$firmware" } else { "Unknown" }
      uefi_present = [bool]($firmware -match 'UEFI')
      secure_boot_enabled = $secureBoot
    } | ConvertTo-Json -Compress
    """
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            text=True,
            timeout=10,
        ).strip()
        if out:
            data = json.loads(out)
            boot_mode = str(data.get("boot_mode") or "Unknown").strip()
            secure_boot = data.get("secure_boot_enabled", None)
            if isinstance(secure_boot, str):
                secure_boot = secure_boot.strip().lower() in {
                    "true",
                    "1",
                    "yes",
                    "enabled",
                }
            elif secure_boot is not None:
                secure_boot = bool(secure_boot)
            return {
                "boot_mode": boot_mode.lower() if boot_mode else "unknown",
                "uefi_present": bool(data.get("uefi_present")),
                "secure_boot_enabled": secure_boot,
            }
    except Exception:
        logger.debug("Windows firmware probe failed", exc_info=True)
    return {"boot_mode": "unknown", "uefi_present": False, "secure_boot_enabled": None}


def _firmware_inventory() -> dict:
    global _FIRMWARE_CACHE
    if isinstance(_FIRMWARE_CACHE, dict):
        return dict(_FIRMWARE_CACHE)
    if IS_WINDOWS:
        _FIRMWARE_CACHE = _windows_firmware_inventory()
    else:
        _FIRMWARE_CACHE = _linux_firmware_inventory()
    return dict(_FIRMWARE_CACHE)


def _hardware_inventory() -> dict:
    cpu_model = (platform.processor() or "").strip()
    cpu_cores = 0
    memory_mb = 0
    disk_total_gb = 0
    if psutil is not None:
        try:
            cpu_cores = int(psutil.cpu_count(logical=True) or 0)
        except Exception:
            cpu_cores = 0
        try:
            memory_mb = int((psutil.virtual_memory().total or 0) / (1024 * 1024))
        except Exception:
            memory_mb = 0
        try:
            disk_total_gb = round(
                (psutil.disk_usage("C:\\" if IS_WINDOWS else "/").total or 0)
                / (1024**3),
                1,
            )
        except Exception:
            disk_total_gb = 0
    return {
        "cpu_model": cpu_model[:200],
        "cpu_cores": cpu_cores,
        "memory_mb": memory_mb,
        "disk_total_gb": disk_total_gb,
        "platform_node": platform.node()[:200],
        **_firmware_inventory(),
    }


def get_inventory():
    os_name, os_version = get_os_info()
    return {
        "agent_id": _stable_agent_id(),
        "hostname": socket.gethostname(),
        "os": os_name,
        "os_version": os_version,
        "kernel": platform.release(),
        "arch": platform.machine(),
        "ip": get_real_ip(),
        "site": _site_name(),
        "hardware_inventory": _hardware_inventory(),
        "agent_version": AGENT_VERSION,
    }


def register(controller_url, token=None):
    inv = get_inventory()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Check agent version compatibility with backend before registration
    try:
        r_version = requests.get(f"{controller_url}/api/version", timeout=5)
        if r_version.status_code == 200:
            backend_info = r_version.json()
            backend_version = backend_info.get("version", "unknown")
            agent_version = AGENT_VERSION
            if backend_version != agent_version:
                logger.warning(
                    f"Version mismatch: agent={agent_version}, backend expects={backend_version}. Registration may still proceed."
                )
    except Exception as e:
        logger.warning(f"Could not verify backend version: {e}")

    try:
        r = requests.post(
            f"{controller_url}/api/register", json=inv, headers=headers, timeout=10
        )
        if r.status_code == 200:
            logger.info("Registered successfully.")
            return r.json().get("agent_token")
        else:
            logger.error(f"Registration failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"Registration error: {e}")
    return None


def heartbeat(controller_url, agent_token):
    inv = get_inventory()
    inv["agent_token"] = (
        agent_token  # included in body for server-side token validation
    )
    headers = {
        "Authorization": f"Bearer {agent_token}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(
            f"{controller_url}/api/heartbeat", json=inv, headers=headers, timeout=10
        )
        if r.status_code == 200:
            logger.info("Heartbeat sent.")
        elif r.status_code in (401, 404):
            logger.warning(
                "Heartbeat rejected (%s) — host not found or token stale, will re-register on next cycle.",
                r.status_code,
            )
            return False  # signal caller to re-register
        else:
            logger.error(f"Heartbeat failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")
    return True


def _normalize_controller_url(value: str) -> str:
    raw = (value or "").strip().strip("`'\" ").replace(" ", "")
    if not raw:
        return raw
    if raw.startswith("http:") and not raw.startswith("http://"):
        raw = "http://" + raw[len("http:") :].lstrip("/")
    if raw.startswith("https:") and not raw.startswith("https://"):
        raw = "https://" + raw[len("https:") :].lstrip("/")
    raw = raw.rstrip("/")
    try:
        parsed = urlsplit(raw)
    except Exception:
        return raw
    if not parsed.scheme or not parsed.netloc:
        return raw
    host = parsed.hostname or parsed.netloc
    port = parsed.port
    if port == 3000:
        port = 8000
    elif port is None and parsed.scheme == "http":
        port = 8000
    elif port is None and parsed.scheme == "https":
        port = 443
    netloc = f"{host}:{port}" if port not in (80, 443) else host
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def check_local_api():
    """Watchdog: verify the local agent API is running."""
    port = int(os.environ.get("AGENT_PORT", "8080"))
    try:
        r = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        if r.status_code == 200:
            return True
    except Exception:
        pass
    return False


def restart_agent_service():
    """Attempt to restart the agent service if the API is dead."""
    logger.error("Watchdog: Local API is unresponsive. Attempting service restart.")
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["powershell", "-c", "Restart-Service PatchMasterAgent"], check=False
            )
        except Exception as e:
            logger.error(f"Restart-Service failed: {e}")
    else:
        # Containers don't have systemd; try service(8), then fall back to
        # re-executing the agent process itself.
        restarted = False
        for cmd in (["service", "patch-agent", "restart"], ["service", "patch-agent", "start"]):
            try:
                r = subprocess.run(cmd, check=False, capture_output=True)
                if r.returncode == 0:
                    restarted = True
                    break
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.debug("restart via %s failed: %s", cmd, e)
        if not restarted:
            logger.warning(
                "No service manager available (systemctl/service missing); "
                "relying on Docker restart policy for recovery."
            )


def main():
    controller_url = os.environ.get("CONTROLLER_URL", "http://localhost:8000")
    controller_url = _normalize_controller_url(controller_url)
    token_path = STATE_DIR / "token"
    agent_token = None
    if token_path.exists():
        agent_token = token_path.read_text().strip()
        if not IS_WINDOWS:
            try:
                token_path.chmod(0o600)
            except Exception:
                logger.warning("Failed to chmod %s to 600", token_path)
    else:
        agent_token = register(
            controller_url, token=os.environ.get("AGENT_API_TOKEN", "").strip() or None
        )
        if agent_token:
            try:
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                _write_private_text(token_path, agent_token)
            except PermissionError:
                logger.warning(
                    f"Cannot write token to {token_path} (permission denied). Running without persistent token."
                )

    failed_api_checks = 0

    while True:
        try:
            # Watchdog check
            if check_local_api():
                failed_api_checks = 0
            else:
                failed_api_checks += 1
                logger.warning(
                    f"Watchdog: API health check failed ({failed_api_checks}/3)"
                )
                if failed_api_checks >= 3:
                    restart_agent_service()
                    failed_api_checks = 0

            # Heartbeat check
            if agent_token:
                ok = heartbeat(controller_url, agent_token)
                if ok is False:
                    # Token rejected — clear it and re-register next cycle
                    agent_token = None
                    try:
                        token_path.unlink(missing_ok=True)
                    except Exception:
                        pass
            else:
                agent_token = register(
                    controller_url,
                    token=os.environ.get("AGENT_API_TOKEN", "").strip() or None,
                )
                if agent_token:
                    try:
                        _write_private_text(token_path, agent_token)
                    except PermissionError:
                        logger.warning(f"Cannot persist token to {token_path}")
        except Exception as e:
            logger.error(f"Loop error: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
