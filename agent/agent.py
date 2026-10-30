#!/usr/bin/env python3
"""PatchMaster by VYGROUP Agent - Full patch management with snapshot/rollback, offline install, package comparison."""

import argparse
import logging
import os
import shutil
import subprocess
import time
import json
import glob
import re
import stat
import uuid
from datetime import datetime, timezone
import platform
from logging.handlers import RotatingFileHandler
import yaml
import urllib.request
import urllib.error
import tempfile
import threading
import zipfile
import tarfile
import psutil
import functools
import hmac as _hmac
import gc
import sys
from pathlib import Path

# Flask imports are optional - only needed when running the agent API server
# This allows package manager classes to be imported in tests without Flask
try:
    from flask import Flask, jsonify, request, send_file
    from werkzeug.utils import secure_filename

    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    Flask = None
    jsonify = None
    request = None
    send_file = None
    secure_filename = None

from prometheus_client import start_http_server, Gauge, CollectorRegistry

__version__ = "2.0.0"

# Import new platform managers (Solaris, HP-UX, AIX)
try:
    from agent.solaris_manager import SolarisManager
except ImportError:
    SolarisManager = None

try:
    from agent.hpux_manager import HPUXManager
except ImportError:
    HPUXManager = None

try:
    from agent.aix_manager import AIXManager
except ImportError:
    AIXManager = None

# --- Config ---
IS_WINDOWS = platform.system() == "Windows"

# ── Agent API token auth ──────────────────────────────────────────────────────
# The agent accepts two valid tokens (either is sufficient):
#   1. AGENT_API_TOKEN env var — a shared/override token set by the operator.
#   2. The per-host registration token written to STATE_DIR/token by main.py
#      after the agent registers with the backend.  The backend stores the same
#      value in hosts.agent_token, so it can look it up per-host and send it.
#
# If neither token is configured yet, privileged endpoints stay unavailable until
# the heartbeat service registers and persists the per-host token.


def _load_valid_tokens() -> set:
    """Return the set of currently valid bearer tokens."""
    tokens = set()
    env_tok = os.environ.get("AGENT_API_TOKEN", "").strip()
    if env_tok:
        tokens.add(env_tok)
    # Per-host registration token written by main.py
    _state_dir = os.environ.get("PATCHMASTER_AGENT_STATE") or (
        r"C:\ProgramData\PatchMaster-Agent" if IS_WINDOWS else "/var/lib/patch-agent"
    )
    _token_path = os.path.join(_state_dir, "token")
    try:
        if os.path.isfile(_token_path):
            reg_tok = open(_token_path).read().strip()
            if reg_tok:
                tokens.add(reg_tok)
    except OSError:
        pass
    return tokens


def run_cmd(cmd, timeout=3600, cwd=None):
    """Execute a shell command and return (returncode, output)."""
    # Use a dummy logger if not yet initialized
    log = globals().get('logger')
    if log:
        log.info("CMD: %s", " ".join(str(c) for c in cmd) if isinstance(cmd, list) else cmd)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        return -1, "Command timed out"
    except Exception as e:
        return -1, str(e)


def _require_auth(fn):
    """Decorator: enforce bearer-token auth when any token is configured."""
    if not FLASK_AVAILABLE:
        # If Flask is not available, return the function as-is (for testing)
        return fn

    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        valid_tokens = _load_valid_tokens()
        if not valid_tokens:
            return jsonify({"error": "agent auth token not initialized"}), 503
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided = auth_header.split(" ", 1)[1].strip()
        else:
            provided = ""
        # Constant-time comparison against each valid token
        if not provided or not any(
            _hmac.compare_digest(provided, t) for t in valid_tokens
        ):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return _wrapper


def _real_norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _is_within_dir(path: str, root: str) -> bool:
    root_real = _real_norm(root)
    path_real = _real_norm(path)
    return path_real == root_real or path_real.startswith(root_real + os.sep)


def _safe_extract_zip(zip_obj: zipfile.ZipFile, dest: str) -> None:
    dest_real = _real_norm(dest)
    for member in zip_obj.infolist():
        member_name = member.filename
        if os.path.isabs(member_name):
            raise ValueError(f"Archive member uses absolute path: {member_name}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"Archive member is a symlink: {member_name}")
        out_path = _real_norm(os.path.join(dest, member_name))
        if not (out_path == dest_real or out_path.startswith(dest_real + os.sep)):
            raise ValueError(f"Archive member escapes target directory: {member_name}")
    # reason: every member validated above (abs path, symlink, traversal)
    zip_obj.extractall(dest)  # nosec B202


def _safe_extract_tar(tar_obj: tarfile.TarFile, dest: str) -> None:
    dest_real = _real_norm(dest)
    for member in tar_obj.getmembers():
        member_name = member.name
        if os.path.isabs(member_name):
            raise ValueError(f"Archive member uses absolute path: {member_name}")
        if member.issym() or member.islnk():
            raise ValueError(f"Archive member is a link: {member_name}")
        out_path = _real_norm(os.path.join(dest, member_name))
        if not (out_path == dest_real or out_path.startswith(dest_real + os.sep)):
            raise ValueError(f"Archive member escapes target directory: {member_name}")
    # reason: every member validated above (abs path, hard/sym link, traversal)
    tar_obj.extractall(dest)  # nosec B202


def _agent_callback_token() -> str:
    state_dir = os.environ.get("PATCHMASTER_AGENT_STATE") or (
        r"C:\ProgramData\PatchMaster-Agent" if IS_WINDOWS else "/var/lib/patch-agent"
    )
    token_path = os.path.join(state_dir, "token")
    try:
        if os.path.isfile(token_path):
            token = open(token_path).read().strip()
            if token:
                return token
    except OSError:
        pass
    return os.environ.get("AGENT_API_TOKEN", "").strip()


def _controller_url() -> str:
    return str(os.environ.get("CONTROLLER_URL", "") or "").strip().rstrip("/")


def _path_size_bytes(path: str) -> int:
    if not path or not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return int(os.path.getsize(path))
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return int(total)


def _report_backup_result(
    log_id, status, output_file="", duration_seconds=0.0, file_size_bytes=0, message=""
):
    controller_url = _controller_url()
    token = _agent_callback_token()
    if not controller_url or not token or not log_id:
        return
    body = json.dumps(
        {
            "log_id": int(log_id),
            "status": str(status or ""),
            "output_file": str(output_file or ""),
            "file_size_bytes": int(file_size_bytes or 0),
            "duration_seconds": float(duration_seconds or 0.0),
            "message": str(message or ""),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{controller_url}/api/backups/agent-callback",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as exc:
        logger.error(f"Backup callback failed for log {log_id}: {exc}")


# --- Metrics ---
# Use a dedicated registry to avoid duplicate timeseries errors when the module is
# imported multiple times (e.g., by Windows services restarting quickly).
REGISTRY = CollectorRegistry()
cpu_usage = Gauge(
    "system_cpu_usage_percent", "System CPU usage percent", registry=REGISTRY
)
memory_usage = Gauge(
    "system_memory_usage_percent", "System memory usage percent", registry=REGISTRY
)
disk_usage = Gauge(
    "system_disk_usage_percent",
    "System disk usage percent",
    ["mountpoint"],
    registry=REGISTRY,
)
disk_read_bps = Gauge(
    "system_disk_read_bytes_per_sec",
    "System disk read throughput bytes/sec",
    registry=REGISTRY,
)
disk_write_bps = Gauge(
    "system_disk_write_bytes_per_sec",
    "System disk write throughput bytes/sec",
    registry=REGISTRY,
)
uptime_seconds = Gauge(
    "system_uptime_seconds", "System uptime in seconds", registry=REGISTRY
)
host_info = Gauge(
    "patchmaster_host_info",
    "Static host metadata (1=present)",
    ["host_os"],
    registry=REGISTRY,
)
patch_gauge = Gauge(
    "patch_job_status",
    "Current patch job status (0=idle, 1=running, 2=success, 3=failed)",
    registry=REGISTRY,
)
last_patch_ts = Gauge(
    "patch_last_success_timestamp",
    "Timestamp of last successful patch",
    registry=REGISTRY,
)

# Memory leak detection - tracked in update_metrics_loop
_memory_baseline_bytes = 0
_memory_baseline_set_time = 0
_memory_warnings_logged = {"100mb": False, "200mb": False}

logger = logging.getLogger("patch-agent")
agent_memory_delta = Gauge(
    "agent_memory_delta_bytes",
    "Agent memory delta from baseline in bytes",
    registry=REGISTRY,
)

# Cache for WSUS operations (Windows only). Helps report scan/install progress to the backend/UI.
WSUS_CACHE = {
    "status": "idle",  # idle | scanning | installing | error
    "pending": [],
    "last_scan": None,
    "last_error": None,
}


def _host_os_label() -> str:
    system = (platform.system() or "").strip().lower()
    if "win" in system:
        return "windows"
    if system == "linux":
        return "linux"
    return system or "unknown"


def update_metrics_loop():
    global _memory_baseline_bytes, _memory_baseline_set_time
    prev_read = None
    prev_write = None
    prev_ts = None

    while True:
        try:
            cpu_usage.set(psutil.cpu_percent(interval=None))
            memory_usage.set(psutil.virtual_memory().percent)
            host_info.labels(host_os=_host_os_label()).set(1)
            io_now = psutil.disk_io_counters()
            now_ts = time.time()

            # Memory leak detection - set baseline on first run, monitor growth
            process = psutil.Process()
            current_rss = process.memory_info().rss
            if _memory_baseline_bytes == 0:
                _memory_baseline_bytes = current_rss
                _memory_baseline_set_time = now_ts
                logger.info(
                    f"Memory baseline set: {_memory_baseline_bytes / (1024 * 1024):.1f} MB"
                )
            else:
                memory_growth = current_rss - _memory_baseline_bytes
                agent_memory_delta.set(max(0, memory_growth))
                # Log warning if memory grows >100MB above baseline after 30 minutes
                uptime_mins = (now_ts - _memory_baseline_set_time) / 60
                if uptime_mins >= 30 and memory_growth > 100 * 1024 * 1024:
                    if not _memory_warnings_logged["100mb"]:
                        logger.warning(
                            f"Memory leak indicator: memory grew {memory_growth / (1024 * 1024):.1f} MB "
                            f"({uptime_mins:.0f} minutes after baseline)"
                        )
                        _memory_warnings_logged["100mb"] = True
                # Log error if memory grows >200MB above baseline
                if memory_growth > 200 * 1024 * 1024:
                    if not _memory_warnings_logged["200mb"]:
                        logger.error(
                            f"Memory leak detected: memory grew {memory_growth / (1024 * 1024):.1f} MB "
                            f"({uptime_mins:.0f} minutes after baseline)"
                        )
                        _memory_warnings_logged["200mb"] = True

            if (
                io_now
                and prev_read is not None
                and prev_write is not None
                and prev_ts is not None
            ):
                dt = max(now_ts - prev_ts, 0.001)
                disk_read_bps.set(max((io_now.read_bytes - prev_read) / dt, 0.0))
                disk_write_bps.set(max((io_now.write_bytes - prev_write) / dt, 0.0))
            if io_now:
                prev_read = io_now.read_bytes
                prev_write = io_now.write_bytes
                prev_ts = now_ts
            for part in psutil.disk_partitions(all=False):
                if IS_WINDOWS or part.mountpoint == "/":
                    try:
                        usage = psutil.disk_usage(part.mountpoint).percent
                        disk_usage.labels(mountpoint=part.mountpoint).set(usage)
                    except (OSError, PermissionError):
                        # Disk may be unmounted or inaccessible
                        pass
            uptime_seconds.set(time.time() - psutil.boot_time())
        except Exception as e:
            logger.error(f"Metrics error: {e}")
        time.sleep(15)


threading.Thread(target=update_metrics_loop, daemon=True).start()

# Prefer ProgramData\PatchMaster-Agent for Windows to align with service logs.
LOG_DIR = (
    r"C:\ProgramData\PatchMaster-Agent\logs" if IS_WINDOWS else "/var/log/patch-agent"
)
SNAPSHOT_DIR = (
    r"C:\ProgramData\PatchMaster-Agent\snapshots"
    if IS_WINDOWS
    else "/var/lib/patch-agent/snapshots"
)
OFFLINE_DIR = (
    r"C:\ProgramData\PatchMaster-Agent\offline-pkgs"
    if IS_WINDOWS
    else "/var/lib/patch-agent/offline-pkgs"
)

for d in [LOG_DIR, SNAPSHOT_DIR, OFFLINE_DIR]:
    try:
        os.makedirs(d, exist_ok=True)
    except PermissionError:
        # Fallback for dev/non-root
        if IS_WINDOWS:
            LOG_DIR = r".\logs"
            SNAPSHOT_DIR = r".\snapshots"
            OFFLINE_DIR = r".\offline-pkgs"
        else:
            LOG_DIR = "./logs"
            SNAPSHOT_DIR = "./snapshots"
            OFFLINE_DIR = "./offline-pkgs"
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        os.makedirs(OFFLINE_DIR, exist_ok=True)

STATE_DIR = os.path.dirname(SNAPSHOT_DIR) or "."
SHUTDOWN_QUEUE_FILE = os.path.join(STATE_DIR, "software-shutdown-queue.json")
QUEUE_LOCK = threading.Lock()

logger.setLevel(logging.INFO)

# Set up formatter
fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

# Try to set up file logging, fall back to console-only if permission denied (e.g., during tests)
log_file = os.path.join(LOG_DIR, "agent.log")
try:
    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
except (PermissionError, OSError) as e:
    # Running without admin privileges (e.g., in tests) - use console logging only
    pass

console = logging.StreamHandler()
console.setFormatter(fmt)
logger.addHandler(console)

# Flask app initialization - only when Flask is available
if FLASK_AVAILABLE:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = None  # No limit - handle uploads of any size

    # Canonical health endpoint (guaranteed here so the agent API is never
    # without a health route even if the split-module import is skipped).
    @app.route("/health")
    def _health():
        try:
            import platform as _platform
            reboot_required = False
            mgr = globals().get("pkg_mgr")
            checker = getattr(mgr, "check_reboot", None) if mgr is not None else None
            if callable(checker):
                reboot_required = bool(checker())
            version = globals().get("__version__", "unknown")
            return jsonify({"status": "ok", "hostname": _platform.node() or "", "os": _platform.system() or "", "agent_version": str(version), "reboot_required": reboot_required})
        except Exception as _e:
            return jsonify({"status": "ok", "reboot_required": False, "error": str(_e)}), 200
else:
    app = None

    # Create a dummy app object with a route decorator that does nothing
    class _DummyApp:
        def route(self, *args, **kwargs):
            def decorator(f):
                return f

            return decorator

    app = _DummyApp()


# --- Package Manager Abstraction (split: agent_parts/managers.py, S0-5) -----
# Split modules resolve this module's namespace through agent_parts._hub on
# every attribute read, so tests that patch run_cmd / JOB_STATUS / pkg_mgr on
# the module object they imported see the change from moved code.
if __package__:
    from . import agent_parts as _agent_parts
else:
    import agent_parts as _agent_parts

# A canonical import (registered in sys.modules) always publishes its
# namespace; a test that execs this file through importlib.util outside
# sys.modules only binds when no hub has bound yet - so _hub keeps pointing at
# the module the tests patch.
if sys.modules.get(__name__) is not None or _agent_parts.HUB is None:
    _agent_parts.HUB = globals()

if __package__:
    from .agent_parts import managers as _managers
    from .agent_parts.managers import AptManager, DnfManager, get_pkg_manager
else:
    from agent_parts import managers as _managers
    from agent_parts.managers import AptManager, DnfManager, get_pkg_manager

globals().update(
    (k, v) for k, v in vars(_managers).items() if not k.startswith("__")
)


pkg_mgr = get_pkg_manager()

# --- Rest of the code ---


JOB_STATUS = {
    "state": "idle",
    "current_job": None,
    "progress": 0,
    "log": [],
    "last_result": None,
    "started_at": None,
}


# run_cmd is now defined earlier in the file (after _load_valid_tokens)


def _normalize_job_result(result):
    if isinstance(result, dict):
        if "success" in result:
            return result
        return {"success": True, "result": result}
    if isinstance(result, tuple) and len(result) >= 2:
        rc = int(result[0])
        out = result[1]
        return {
            "success": rc == 0,
            "rc": rc,
            "output": out,
            "message": str(out or ""),
        }
    if isinstance(result, bool):
        return {"success": result}
    if result is None:
        return {"success": True}
    return {"success": bool(result), "result": result}


def _load_shutdown_queue():
    with QUEUE_LOCK:
        try:
            if not os.path.isfile(SHUTDOWN_QUEUE_FILE):
                return []
            with open(SHUTDOWN_QUEUE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error(f"Failed to load shutdown software queue: {exc}")
            return []


def _save_shutdown_queue(items):
    os.makedirs(os.path.dirname(SHUTDOWN_QUEUE_FILE) or ".", exist_ok=True)
    with QUEUE_LOCK:
        with open(SHUTDOWN_QUEUE_FILE, "w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=2)


def _enqueue_shutdown_packages(action, packages, requested_by="", reason=""):
    item = {
        "id": str(uuid.uuid4()),
        "action": str(action or "install"),
        "packages": [str(pkg).strip() for pkg in (packages or []) if str(pkg).strip()],
        "requested_by": str(requested_by or "").strip(),
        "reason": str(reason or "").strip(),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_shutdown_queue()
    items.append(item)
    _save_shutdown_queue(items)
    return item


def _execute_shutdown_queue():
    queued = _load_shutdown_queue()
    if not queued:
        return {
            "success": True,
            "executed": [],
            "failed": [],
            "message": "No queued shutdown installs",
        }

    executed = []
    failed_items = []
    for item in queued:
        action = str(item.get("action") or "install").strip().lower()
        packages = [
            str(pkg).strip() for pkg in (item.get("packages") or []) if str(pkg).strip()
        ]
        if not packages:
            continue
        if action == "remove":
            rc, out = pkg_mgr.remove(packages)
        else:
            rc, out = pkg_mgr.install(packages)
        result = {
            "id": item.get("id"),
            "action": action,
            "packages": packages,
            "rc": rc,
            "output": out,
            "success": rc == 0,
        }
        executed.append(result)
        if rc != 0:
            failed_copy = dict(item)
            failed_copy["last_error"] = str(out or "")
            failed_items.append(failed_copy)

    _save_shutdown_queue(failed_items)
    return {
        "success": len(failed_items) == 0,
        "executed": executed,
        "failed": failed_items,
        "message": "Shutdown install queue executed"
        if not failed_items
        else "One or more queued shutdown installs failed",
    }


def record_job(job_data):
    """Log job history to disk (simple JSON lines)."""
    with open(os.path.join(LOG_DIR, "jobs.jsonl"), "a") as f:
        f.write(json.dumps(job_data) + "\n")


def run_async_job(job_type, target_func, *args, **kwargs):
    """Run a job in a background thread."""
    if JOB_STATUS["state"] == "running":
        return False, "Another job is already running"

    def wrapper():
        JOB_STATUS["state"] = "running"
        JOB_STATUS["current_job"] = job_type
        JOB_STATUS["started_at"] = time.time()
        JOB_STATUS["progress"] = 0
        JOB_STATUS["log"] = []
        try:
            result = _normalize_job_result(target_func(*args, **kwargs))
            JOB_STATUS["state"] = "success" if result.get("success") else "failed"
            JOB_STATUS["last_result"] = result
        except Exception as e:
            JOB_STATUS["state"] = "failed"
            JOB_STATUS["last_result"] = {"error": str(e)}
            JOB_STATUS["log"].append(f"Critical Error: {str(e)}")
        finally:
            JOB_STATUS["progress"] = 100
            record_job(
                {
                    "type": job_type,
                    "status": JOB_STATUS["state"],
                    "result": JOB_STATUS["last_result"],
                    "ts": time.time(),
                }
            )
            # Reset to idle after a short delay or let client acknowledge?
            # For simplicity, we stay in success/failed state until next job starts,
            # but maybe auto-reset is risky if client misses it.
            # We'll rely on client polling to see 'success' then stop polling.
            # We can set state to idle on next job request start check.
            pass

    t = threading.Thread(target=wrapper)
    t.start()
    return True, "Job started"


def _run_powershell(script, timeout=600):
    exe = "powershell"
    return run_cmd(
        [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


def _powershell_json(script, timeout=600):
    rc, out = _run_powershell(script, timeout=timeout)
    if rc != 0:
        raise Exception(out)
    txt = (out or "").strip()
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        raise Exception(txt)

def _restore_windows_backup_manifest(path, target_override=None):
    manifest = _load_windows_backup_manifest(path)
    if not manifest:
        return {"success": False, "error": "Windows backup manifest not found"}

    target = (target_override or manifest.get("backup_target") or "").strip()
    if not target:
        return {
            "success": False,
            "error": "Windows backup target is missing from manifest",
        }

    version = str(manifest.get("version_identifier") or "").strip()
    if not version:
        versions = _detect_wbadmin_versions(target)
        version = versions[0] if versions else ""
    if not version:
        return {
            "success": False,
            "error": f"No wbadmin version found at {target}",
            "backup_target": target,
        }

    attempts = []
    commands = [
        [
            "wbadmin",
            "start",
            "sysrecovery",
            f"-version:{version}",
            f"-backuptarget:{target}",
            "-quiet",
        ],
        [
            "wbadmin",
            "start",
            "systemstaterecovery",
            f"-version:{version}",
            f"-backuptarget:{target}",
            "-quiet",
        ],
    ]
    for command in commands:
        rc, out = run_cmd(command, timeout=7200)
        attempts.append(
            {
                "command": " ".join(command),
                "rc": rc,
                "output": out[:800],
            }
        )
        if rc == 0:
            return {
                "success": True,
                "backup_target": target,
                "version": version,
                "output": out[:800],
                "attempts": attempts,
            }

    return {
        "success": False,
        "error": "wbadmin restore failed",
        "backup_target": target,
        "version": version,
        "attempts": attempts,
    }

def _rollback_snapshot(name):
    snap_dir = os.path.join(SNAPSHOT_DIR, name)
    result = {"name": name, "success": False, "steps": []}
    if not os.path.isdir(snap_dir):
        result["error"] = f"Snapshot '{name}' not found"
        return result
    try:
        meta_path = os.path.join(snap_dir, "meta.json")
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
        if meta.get("mode") == "full_system":
            r = _restore_full_snapshot(meta, snap_dir)
            result["steps"].append(r)
            result["success"] = r.get("success", False)
            return result

        pkg_mgr.refresh()
        packages_file = os.path.join(snap_dir, "packages.json")
        if os.path.exists(packages_file):
            with open(packages_file) as f:
                old_pkgs = json.load(f)
            if IS_WINDOWS:
                current_pkgs = pkg_mgr.list_installed()
                desired = {
                    key: pkg
                    for pkg in old_pkgs
                    if (key := _windows_package_identity(pkg))
                }
                current = {
                    key: pkg
                    for pkg in current_pkgs
                    if (key := _windows_package_identity(pkg))
                }
                failures = 0
                warnings = []

                for key, desired_pkg in desired.items():
                    current_pkg = current.get(key)
                    if current_pkg and str(current_pkg.get("version") or "") == str(
                        desired_pkg.get("version") or ""
                    ):
                        continue
                    rc, out = _windows_install_snapshot_package(desired_pkg)
                    result["steps"].append(
                        {
                            "step": "reconcile-package",
                            "package": desired_pkg.get("id") or desired_pkg.get("name"),
                            "target_version": desired_pkg.get("version", ""),
                            "rc": rc,
                            "output": out[:500],
                        }
                    )
                    if rc != 0:
                        failures += 1

                for key, current_pkg in current.items():
                    if key in desired:
                        continue
                    rc, out = _windows_remove_snapshot_package(current_pkg)
                    result["steps"].append(
                        {
                            "step": "remove-extra-package",
                            "package": current_pkg.get("id") or current_pkg.get("name"),
                            "rc": rc,
                            "output": out[:500],
                        }
                    )
                    if rc != 0:
                        warnings.append(
                            f"Could not remove {current_pkg.get('id') or current_pkg.get('name')}"
                        )

                result["warnings"] = warnings
                result["success"] = failures == 0
                if failures:
                    result["error"] = (
                        f"{failures} Windows package rollback action(s) failed"
                    )
                return result
            # Build a list of "name=version" targets to downgrade/reinstall to snapshot state
            if isinstance(pkg_mgr, AptManager):
                targets = [
                    f"{p['name']}={p['version']}"
                    for p in old_pkgs
                    if p.get("name") and p.get("version")
                ]
                if targets:
                    # apt-get install with pinned versions will downgrade if needed
                    rc, out = run_cmd(
                        [
                            "apt-get",
                            "install",
                            "-y",
                            "--allow-downgrades",
                            "--no-install-recommends",
                        ]
                        + targets,
                        timeout=600,
                    )
                    result["steps"].append(
                        {"step": "downgrade-packages", "rc": rc, "output": out[:500]}
                    )
                    result["success"] = rc == 0
                else:
                    result["success"] = True
            elif isinstance(pkg_mgr, DnfManager):
                targets = [
                    f"{p['name']}-{p['version']}"
                    for p in old_pkgs
                    if p.get("name") and p.get("version")
                ]
                if targets:
                    rc, out = run_cmd(["dnf", "downgrade", "-y"] + targets, timeout=600)
                    result["steps"].append(
                        {"step": "downgrade-packages", "rc": rc, "output": out[:500]}
                    )
                    result["success"] = rc == 0
                else:
                    result["success"] = True
            else:
                result["error"] = "Rollback not supported for this package manager"
    except Exception as e:
        result["error"] = str(e)
    record_job({"type": "rollback", **result})
    return result

def backup_full_system(output_file):
    """Create a full system image (Linux only, root required)."""
    if IS_WINDOWS:
        target = _resolve_windows_backup_target()
        if not target:
            raise Exception(
                "No writable backup target available for Windows full-system backup"
            )
        versions_before = set(_detect_wbadmin_versions(target))
        rc, out = run_cmd(
            [
                "wbadmin",
                "start",
                "backup",
                f"-backupTarget:{target}",
                "-allCritical",
                "-quiet",
            ],
            timeout=7200,
        )
        if rc != 0:
            raise Exception(f"wbadmin failed: {out[:400]}")
        versions_after = _detect_wbadmin_versions(target)
        version_identifier = next(
            (v for v in versions_after if v not in versions_before),
            versions_after[0] if versions_after else "",
        )
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        _write_windows_backup_manifest(
            output_file,
            target,
            version_identifier=version_identifier,
            command_output=out,
            backup_mode="full_system",
        )
        return output_file

    # DD backup of root partition (DANGEROUS - Mocking for safety)
    # cmd = f"dd if=/dev/sda of={output_file} bs=4M status=progress"

    # Safer alternative: Tarball of root with excludes
    cmd = [
        "tar",
        "czf",
        output_file,
        "--exclude=/proc",
        "--exclude=/sys",
        "--exclude=/dev",
        "--exclude=/tmp",
        "--exclude=/run",
        "--exclude=/mnt",
        "--exclude=/media",
        "--exclude=/lost+found",
        "/",
    ]
    rc, out = run_cmd(cmd, timeout=7200)  # 2 hours timeout
    if rc != 0:
        raise Exception(f"Full system backup failed: {out}")
    return output_file


# --- Split HTTP/task modules (plan.md S0-5) --------------------------------
# Snapshot helpers this file's own functions call: imported statically so
# linters see them, but they live in this namespace, so monkeypatch.setattr
# on this module still wins at call time.
if __package__:
    from .agent_parts import (
        api as _api,
        backup as _backup,
        executor as _executor,
        offline as _offline,
        snapshot as _snapshot,
    )
    from .agent_parts.snapshot import (
        _detect_wbadmin_versions,
        _load_windows_backup_manifest,
        _resolve_windows_backup_target,
        _restore_full_snapshot,
        _windows_install_snapshot_package,
        _windows_package_identity,
        _windows_remove_snapshot_package,
        _write_windows_backup_manifest,
    )
else:
    from agent_parts import (
        api as _api,
        backup as _backup,
        executor as _executor,
        offline as _offline,
        snapshot as _snapshot,
    )
    from agent_parts.snapshot import (
        _detect_wbadmin_versions,
        _load_windows_backup_manifest,
        _resolve_windows_backup_target,
        _restore_full_snapshot,
        _windows_install_snapshot_package,
        _windows_package_identity,
        _windows_remove_snapshot_package,
        _write_windows_backup_manifest,
    )

pass

# Re-export everything the split modules define so agent.X / agent.agent.X
# resolve exactly as they did when agent.py was a single file.
for _part in (_api, _backup, _executor, _offline, _snapshot):
    globals().update(
        (k, v) for k, v in vars(_part).items() if not k.startswith("__")
    )

pass



def main(port=8080, metrics_port=9100):
    start_http_server(metrics_port, registry=REGISTRY)
    logger.info("Agent metrics listening on port %s", metrics_port)
    while True:
        try:
            logger.info("Agent API starting on port %s", port)
            _app = _hub.app
            @_app.before_request
            def _log_path():
                import sys
                print("BEFORE_REQUEST path=", __import__("flask").request.path, flush=True)
            _app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        except KeyboardInterrupt:
            raise
        except SystemExit as exc:
            logger.error("Agent API exited (%s). Retrying in 5s.", exc)
            time.sleep(5)
        except Exception as exc:
            logger.error("Agent API failed (%s). Retrying in 5s.", exc)
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--metrics-port", type=int, default=9100)
    args = parser.parse_args()
    main(port=args.port, metrics_port=args.metrics_port)
