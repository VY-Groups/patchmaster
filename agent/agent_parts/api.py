"""Agent HTTP routes: jobs, system, software, WSUS, packages, snapshots
helpers, cleanup, policy and the live command runner (split out of agent.py,
plan.md S0-5).

Handlers register on the ONE app object the hub published and read all hub
state through the _hub proxy at call time.
"""
import glob
import json
import os
import platform
import re
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psutil
import yaml

try:
    from flask import jsonify, request, send_file
    from werkzeug.utils import secure_filename
except ImportError:  # Flask is optional until the API server runs (agent.py parity)
    jsonify = request = send_file = secure_filename = None

from . import _hub
from .managers import AptManager, DnfManager

@_hub.app.route("/job/status")
def job_status():
    return jsonify(_hub.JOB_STATUS)


@_hub.app.route("/job/reset", methods=["POST"])
@_hub._require_auth
def job_reset():
    if _hub.JOB_STATUS["state"] == "running":
        return jsonify({"error": "Cannot reset running job"}), 400
    _hub.JOB_STATUS["state"] = "idle"
    _hub.JOB_STATUS["log"] = []
    _hub.JOB_STATUS["last_result"] = None
    return jsonify({"status": "reset"})


@_hub.app.route("/health")
def health():
    try:
        reboot_required = False
        checker = getattr(_hub.pkg_mgr, "check_reboot", None)
        if callable(checker):
            reboot_required = bool(checker())
        state = _hub.JOB_STATUS.get("state", "unknown")
        if not isinstance(state, str):
            state = str(state)
        return jsonify(
            {
                "status": "ok",
                "hostname": str(platform.node() or ""),
                "os": str(platform.system() or ""),
                "agent_version": str(_hub.__version__),
                "reboot_required": reboot_required,
                "state": state,
            }
        )
    except Exception as e:
        _hub.logger.error(f"Health endpoint failure: {e}")
        return jsonify({"status": "ok", "reboot_required": False, "state": "unknown"})


@_hub.app.route("/api/version")
def api_version():
    """Return agent version for version synchronization with backend."""
    return jsonify(
        {
            "version": str(_hub.__version__),
        }
    )


@_hub.app.route("/api/debug/memory")
def debug_memory():
    """Return memory profiling information for leak detection."""
    try:
        process = psutil.Process()
        mem_info = process.memory_info()
        current_rss = mem_info.rss
        current_vms = mem_info.vms
        uptime = time.time() - psutil.boot_time()
        delta = (
            max(0, current_rss - _hub._memory_baseline_bytes)
            if _hub._memory_baseline_bytes > 0
            else 0
        )
        return jsonify(
            {
                "current_rss_bytes": current_rss,
                "current_vms_bytes": current_vms,
                "baseline_rss_bytes": _hub._memory_baseline_bytes,
                "delta_from_baseline_bytes": delta,
                "uptime_seconds": uptime,
                "active_threads": threading.active_count(),
                "baseline_set_time": _hub._memory_baseline_set_time,
            }
        )
    except Exception as e:
        _hub.logger.error(f"Memory debug endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


@_hub.app.route("/api/debug/gc", methods=["POST"])
@_hub._require_auth
def debug_gc():
    """Trigger garbage collection and return freed bytes estimate."""
    try:
        import gc

        gc.collect()
        # Get memory before and after to estimate freed bytes
        process = psutil.Process()
        mem_before = process.memory_info().rss
        # Force collect and get stats
        collected = gc.collect()
        mem_after = process.memory_info().rss
        freed_estimate = max(0, mem_before - mem_after)
        return jsonify(
            {
                "objects_collected": collected,
                "freed_bytes_estimate": freed_estimate,
            }
        )
    except Exception as e:
        _hub.logger.error(f"GC endpoint error: {e}")
        return jsonify({"error": str(e)}), 500


@_hub.app.route("/system/reboot", methods=["POST"])
@_hub._require_auth
def system_reboot():
    """Trigger a reboot and process queued shutdown installs first."""
    data = request.get_json(silent=True) or {}
    run_shutdown_queue = bool(data.get("run_shutdown_queue", True))

    def _task():
        queue_result = {
            "success": True,
            "executed": [],
            "failed": [],
            "message": "Skipped shutdown queue",
        }
        if run_shutdown_queue:
            queue_result = _hub._execute_shutdown_queue()
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": "Queued shutdown installs failed",
                    "queue": queue_result,
                }
        if _hub.IS_WINDOWS:
            rc, out = _hub.run_cmd(["shutdown", "/r", "/t", "5"])
        else:
            rc, out = _hub.run_cmd(["shutdown", "-r", "+1"])
        return {
            "success": rc == 0,
            "status": "reboot_scheduled" if rc == 0 else "reboot_failed",
            "rc": rc,
            "output": out,
            "queue": queue_result,
        }

    ok, msg = _hub.run_async_job("reboot", _task)
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "reboot_scheduled"})


@_hub.app.route("/system/shutdown", methods=["POST"])
@_hub._require_auth
def system_shutdown():
    """Trigger a shutdown and process queued shutdown installs first."""
    data = request.get_json(silent=True) or {}
    run_shutdown_queue = bool(data.get("run_shutdown_queue", True))

    def _task():
        queue_result = {
            "success": True,
            "executed": [],
            "failed": [],
            "message": "Skipped shutdown queue",
        }
        if run_shutdown_queue:
            queue_result = _hub._execute_shutdown_queue()
            if not queue_result.get("success"):
                return {
                    "success": False,
                    "message": "Queued shutdown installs failed",
                    "queue": queue_result,
                }
        if _hub.IS_WINDOWS:
            rc, out = _hub.run_cmd(["shutdown", "/s", "/t", "5"])
        else:
            rc, out = _hub.run_cmd(["shutdown", "-h", "+1"])
        return {
            "success": rc == 0,
            "status": "shutdown_scheduled" if rc == 0 else "shutdown_failed",
            "rc": rc,
            "output": out,
            "queue": queue_result,
        }

    ok, msg = _hub.run_async_job("shutdown", _task)
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "shutdown_scheduled"})


@_hub.app.route("/software/manage", methods=["POST"])
@_hub._require_auth
def software_manage():
    """Install or remove generic software."""
    data = request.get_json(silent=True) or {}
    action = data.get("action", "install")  # install | remove
    packages = data.get("packages", [])
    if not packages:
        return jsonify({"error": "No packages specified"}), 400

    def _task():
        if action == "remove":
            return _hub.pkg_mgr.remove(packages)
        return _hub.pkg_mgr.install(packages)

    ok, msg = _hub.run_async_job(f"software_{action}", _task)
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "started", "job": f"software_{action}"})


@_hub.app.route("/software/queue", methods=["GET"])
@_hub._require_auth
def software_queue_list():
    items = _hub._load_shutdown_queue()
    return jsonify({"count": len(items), "items": items})


@_hub.app.route("/software/queue", methods=["POST"])
@_hub._require_auth
def software_queue_add():
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "install").strip().lower()
    packages = [
        str(pkg).strip() for pkg in (data.get("packages") or []) if str(pkg).strip()
    ]
    if action not in {"install", "remove"}:
        return jsonify({"error": "Unsupported action"}), 400
    if not packages:
        return jsonify({"error": "No packages specified"}), 400
    item = _hub._enqueue_shutdown_packages(
        action=action,
        packages=packages,
        requested_by=data.get("requested_by", ""),
        reason=data.get("reason", ""),
    )
    return jsonify(
        {"status": "queued", "item": item, "count": len(_hub._load_shutdown_queue())}
    )


@_hub.app.route("/software/queue", methods=["DELETE"])
@_hub._require_auth
def software_queue_clear():
    _hub._save_shutdown_queue([])
    return jsonify({"status": "cleared"})




@_hub.app.route("/wsus/updates")
@_hub._require_auth
def wsus_updates():
    if not _hub.IS_WINDOWS:
        return jsonify({"error": "WSUS is only available on Windows agents"}), 400
    _hub.WSUS_CACHE["status"] = "scanning"
    _hub.WSUS_CACHE["last_error"] = None
    script = (
        "$s=New-Object -ComObject Microsoft.Update.Session;"
        "$searcher=$s.CreateUpdateSearcher();"
        "$r=$searcher.Search(\"IsInstalled=0 and Type='Software'\");"
        "$r.Updates | Select-Object Title,KBArticleIDs,MsrcSeverity,RebootRequired,IsInstalled,IsDownloaded,LastDeploymentChangeTime,@{Name='MaxDownloadSize';Expression={$_.MaxDownloadSize}},@{Name='UpdateID';Expression={$_.Identity.UpdateID}},@{Name='RevisionNumber';Expression={$_.Identity.RevisionNumber}},@{Name='Categories';Expression={$_.Categories | Select-Object -ExpandProperty Name}},@{Name='CVEIDs';Expression={$_.CveIDs}} | ConvertTo-Json -Depth 6"
    )
    try:
        data = _hub._powershell_json(script, timeout=240)
        if data is None:
            data = []
        if isinstance(data, dict):
            data = [data]
        _hub.WSUS_CACHE["pending"] = data
        _hub.WSUS_CACHE["last_scan"] = datetime.now(timezone.utc).isoformat()
        _hub.WSUS_CACHE["status"] = "idle"
        return jsonify({"count": len(data), "updates": data})
    except Exception as e:
        _hub.WSUS_CACHE["status"] = "error"
        _hub.WSUS_CACHE["last_error"] = str(e)
        return jsonify({"error": str(e)}), 500


@_hub.app.route("/wsus/install", methods=["POST"])
@_hub._require_auth
def wsus_install():
    if not _hub.IS_WINDOWS:
        return jsonify({"error": "WSUS is only available on Windows agents"}), 400

    _hub.WSUS_CACHE["status"] = "installing"
    _hub.WSUS_CACHE["last_error"] = None

    payload = request.get_json(silent=True) or {}
    update_ids = payload.get("update_ids") if isinstance(payload, dict) else None
    if not isinstance(update_ids, list):
        update_ids = []
    update_ids = [str(x).strip() for x in update_ids if str(x).strip()]

    def _task(selected_update_ids=None):
        filter_clause = ""
        if selected_update_ids:
            # build a PowerShell array of IDs and filter
            filter_clause = (
                ";$ids=@("
                + ";".join([f"'{uid}'" for uid in selected_update_ids])
                + ");$sel=@();foreach($u in $r.Updates){if($ids -contains $u.Identity.UpdateID){$sel+=$u}};$updates=$sel"
            )
        else:
            filter_clause = ";$updates=New-Object -ComObject Microsoft.Update.UpdateColl;foreach($u in $r.Updates){[void]$updates.Add($u)}"
        script = (
            "$s=New-Object -ComObject Microsoft.Update.Session;"
            "$searcher=$s.CreateUpdateSearcher();"
            "$r=$searcher.Search(\"IsInstalled=0 and Type='Software'\");"
            f"{filter_clause};"
            "$down=$s.CreateUpdateDownloader();$down.Updates=$updates;[void]$down.Download();"
            "$inst=$s.CreateUpdateInstaller();$inst.Updates=$updates;$res=$inst.Install();"
            "$res | ConvertTo-Json -Depth 6"
        )
        rc, out = _hub._run_powershell(script, timeout=3600)
        success = rc == 0
        if success:
            _hub.WSUS_CACHE["pending"] = []
            _hub.WSUS_CACHE["status"] = "idle"
        else:
            _hub.WSUS_CACHE["status"] = "error"
            _hub.WSUS_CACHE["last_error"] = out
        return {"success": success, "output": out}

    ok, msg = _hub.run_async_job("wsus_install", _task, update_ids)
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "started"})


@_hub.app.route("/wsus/download", methods=["POST"])
@_hub._require_auth
def wsus_download():
    if not _hub.IS_WINDOWS:
        return jsonify({"error": "WSUS is only available on Windows agents"}), 400
    _hub.WSUS_CACHE["status"] = "downloading"
    _hub.WSUS_CACHE["last_error"] = None
    payload = request.get_json(silent=True) or {}
    update_ids = payload.get("update_ids") if isinstance(payload, dict) else None
    if not isinstance(update_ids, list):
        update_ids = []
    update_ids = [str(x).strip() for x in update_ids if str(x).strip()]

    def _task(selected_update_ids=None):
        filter_clause = ""
        if selected_update_ids:
            filter_clause = (
                ";$ids=@("
                + ";".join([f"'{uid}'" for uid in selected_update_ids])
                + ");$sel=@();foreach($u in $r.Updates){if($ids -contains $u.Identity.UpdateID){$sel+=$u}};$updates=$sel"
            )
        else:
            filter_clause = ";$updates=New-Object -ComObject Microsoft.Update.UpdateColl;foreach($u in $r.Updates){[void]$updates.Add($u)}"
        script = (
            "$s=New-Object -ComObject Microsoft.Update.Session;"
            "$searcher=$s.CreateUpdateSearcher();"
            "$r=$searcher.Search(\"IsInstalled=0 and Type='Software'\");"
            f"{filter_clause};"
            "$down=$s.CreateUpdateDownloader();$down.Updates=$updates;$res=$down.Download();"
            "$res | ConvertTo-Json -Depth 6"
        )
        rc, out = _hub._run_powershell(script, timeout=3600)
        success = rc == 0
        if success:
            _hub.WSUS_CACHE["status"] = "idle"
        else:
            _hub.WSUS_CACHE["status"] = "error"
            _hub.WSUS_CACHE["last_error"] = out
        return {"success": success, "output": out}

    ok, msg = _hub.run_async_job("wsus_download", _task, update_ids)
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "started"})


@_hub.app.route("/wsus/status")
def wsus_status():
    if not _hub.IS_WINDOWS:
        return jsonify({"error": "WSUS is only available on Windows agents"}), 400
    rc, out = _hub._run_powershell(
        "Get-Service wuauserv | Select-Object Status,StartType,Name | ConvertTo-Json -Depth 4",
        timeout=30,
    )
    service_payload = None
    if rc == 0:
        try:
            service_payload = json.loads(out)
        except Exception:
            service_payload = {"raw": out}
    return jsonify(
        {
            "service": service_payload,
            "status": _hub.WSUS_CACHE.get("status"),
            "pending_count": len(_hub.WSUS_CACHE.get("pending") or []),
            "last_scan": _hub.WSUS_CACHE.get("last_scan"),
            "last_error": _hub.WSUS_CACHE.get("last_error"),
        }
    )


# === PACKAGE LISTING ===


@_hub.app.route("/packages/installed")
def packages_installed():
    packages = _hub.pkg_mgr.list_installed()
    return jsonify({"packages": packages, "count": len(packages)})


@_hub.app.route("/packages/refresh", methods=["POST"])
@_hub._require_auth
def packages_refresh():
    """Refresh package cache."""
    rc, out = _hub.pkg_mgr.refresh()
    return jsonify({"success": rc == 0, "output": out})


@_hub.app.route("/packages/upgradable")
def packages_upgradable():
    packages = _hub.pkg_mgr.list_upgradable()
    return jsonify({"packages": packages, "count": len(packages)})


@_hub.app.route("/packages/uris", methods=["POST"])
@_hub._require_auth
def packages_uris():
    """Return download URIs for specified packages. Supports apt (deb) and dnf/yum (rpm)."""
    data = request.get_json(silent=True) or {}
    pkg_names = data.get("packages", [])
    uris = []

    if isinstance(_hub.pkg_mgr, _hub.AptManager):
        cmd = (
            ["apt-get", "--print-uris", "-y", "install"] + pkg_names
            if pkg_names
            else ["apt-get", "--print-uris", "-y", "upgrade"]
        )
        rc, out = _hub.run_cmd(cmd, timeout=60)
        for line in out.strip().splitlines():
            line = line.strip()
            if not line.startswith("'") or ".deb" not in line:
                continue
            parts = line.split(" ")
            if len(parts) >= 2:
                url = parts[0].strip("'")
                filename = parts[1]
                size = parts[2] if len(parts) > 2 else "0"
                uris.append({"url": url, "filename": filename, "size": size})

    elif isinstance(_hub.pkg_mgr, _hub.DnfManager):
        # dnf download --url prints download URLs to stdout
        targets = pkg_names if pkg_names else []
        if not targets:
            # Get list of upgradable packages first
            upgradable = _hub.pkg_mgr.list_upgradable()
            targets = [p["name"] for p in upgradable]
        if targets:
            rc, out = _hub.run_cmd(
                ["dnf", "download", "--url", "--resolve"] + targets, timeout=60
            )
            for line in out.strip().splitlines():
                line = line.strip()
                if line.startswith("http://") or line.startswith("https://"):
                    filename = line.split("/")[-1]
                    uris.append({"url": line, "filename": filename, "size": "0"})

    return jsonify({"uris": uris, "count": len(uris)})




# === BASIC ROUTES ===


@_hub.app.route("/status")
def status():
    return jsonify(_hub.JOB_STATUS)


@_hub.app.route("/job/history")
def job_history():
    jobs = []
    log_file = os.path.join(_hub.LOG_DIR, "jobs.jsonl")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                for line in f:
                    try:
                        jobs.append(json.loads(line))
                    except (json.JSONDecodeError, ValueError):
                        # Skip malformed JSON lines
                        pass
        except (IOError, OSError):
            # Log file may be locked or inaccessible
            pass
    return jsonify({"history": jobs[-100:][::-1]})


@_hub.app.route("/history")
def history_alias():
    return job_history()


@_hub.app.route("/snapshot/archive/<name>", methods=["GET"])
@_hub._require_auth
def archive_snapshot(name):
    """Zip a snapshot directory and return it."""
    safe_name = _hub._safe_snapshot_name(name)
    if not safe_name:
        return jsonify({"error": "Invalid name"}), 400

    snap_dir = os.path.join(_hub.SNAPSHOT_DIR, safe_name)
    if not os.path.isdir(snap_dir):
        return jsonify({"error": "Not found"}), 404

    zip_path = os.path.join(_hub.LOG_DIR, f"{safe_name}.zip")
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(snap_dir):
                for file in files:
                    zipf.write(
                        os.path.join(root, file),
                        os.path.relpath(
                            os.path.join(root, file), os.path.join(snap_dir, "..")
                        ),
                    )
        return send_file(zip_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@_hub.app.route("/snapshot/restore_upload", methods=["POST"])
@_hub._require_auth
def restore_upload():
    """Upload a snapshot zip and restore it."""
    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400
    f = request.files["file"]
    name = request.form.get("name") or Path(secure_filename(f.filename)).stem
    safe_name = _hub._safe_snapshot_name(name)
    if not safe_name:
        return jsonify({"error": "Invalid snapshot name"}), 400
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    f.save(tmp_path)
    snap_dir = os.path.join(_hub.SNAPSHOT_DIR, safe_name)
    os.makedirs(snap_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(tmp_path, "r") as zip_ref:
            _hub._safe_extract_zip(zip_ref, os.path.join(_hub.SNAPSHOT_DIR))
        res = _hub._rollback_snapshot(safe_name)
    except Exception as e:
        res = {"success": False, "error": str(e)}
    finally:
        os.remove(tmp_path)
    return jsonify(res), 200 if res.get("success") else 500


@_hub.app.route("/snapshot/restore_url", methods=["POST"])
@_hub._require_auth
def restore_url():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    name = data.get("name")
    if not url:
        return jsonify({"error": "url required"}), 400
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    try:
        urllib.request.urlretrieve(url, tmp_path)
        if not name:
            name = Path(url).stem or f"imported-{int(time.time())}"
        safe_name = _hub._safe_snapshot_name(name)
        if not safe_name:
            return jsonify({"error": "Invalid name"}), 400
        snap_dir = os.path.join(_hub.SNAPSHOT_DIR, safe_name)
        os.makedirs(snap_dir, exist_ok=True)
        with zipfile.ZipFile(tmp_path, "r") as zip_ref:
            _hub._safe_extract_zip(zip_ref, os.path.join(_hub.SNAPSHOT_DIR))
        res = _hub._rollback_snapshot(safe_name)
        return jsonify(res), 200 if res.get("success") else 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            # File may have already been deleted or is in use
            pass


@_hub.app.route("/cleanup", methods=["POST"])
@_hub._require_auth
def cleanup_resources():
    """Delete old snapshots and offline packages."""
    data = request.get_json(silent=True) or {}
    snap_days = data.get("snapshot_retention_days", 30)
    pkg_days = data.get("package_retention_days", 30)

    deleted_snaps = []
    deleted_pkgs = []
    now = time.time()

    # Clean snapshots
    if os.path.isdir(_hub.SNAPSHOT_DIR):
        for d in os.listdir(_hub.SNAPSHOT_DIR):
            path = os.path.join(_hub.SNAPSHOT_DIR, d)
            if os.path.isdir(path):
                if os.path.getmtime(path) < now - (snap_days * 86400):
                    shutil.rmtree(path)
                    deleted_snaps.append(d)

    # Clean offline packages
    if os.path.isdir(_hub.OFFLINE_DIR):
        for f in os.listdir(_hub.OFFLINE_DIR):
            path = os.path.join(_hub.OFFLINE_DIR, f)
            if os.path.isfile(path):
                if os.path.getmtime(path) < now - (pkg_days * 86400):
                    os.remove(path)
                    deleted_pkgs.append(f)

    return jsonify(
        {
            "deleted_snapshots": deleted_snaps,
            "deleted_packages": deleted_pkgs,
            "status": "success",
        }
    )


@_hub.app.route("/devops/run", methods=["POST"])
@_hub._require_auth
def devops_run():
    """Run DevOps workflow from YAML definition."""
    data = request.get_json(silent=True) or {}
    yaml_content = data.get("yaml")
    if not yaml_content:
        return jsonify({"error": "No YAML provided"}), 400
    try:
        workflow = yaml.safe_load(yaml_content)
    except Exception as e:
        return jsonify({"error": f"YAML parse error: {e}"}), 400
    # Example: run steps defined in YAML
    results = []
    for step in workflow.get("steps", []):
        cmd = step.get("run")
        if cmd:
            # Wrap string commands in a shell so pipes/redirects work
            if _hub.IS_WINDOWS:
                shell_cmd = ["cmd.exe", "/c", cmd]
            else:
                shell_cmd = ["bash", "-c", cmd]
            rc, out = _hub.run_cmd(shell_cmd, timeout=step.get("timeout", 600))
            results.append({"step": step.get("name", cmd), "rc": rc, "output": out})
    return jsonify({"results": results})


# === DEVOPS & POLICY ENGINE ===


def apply_service_state(service, state, enable=None):
    """Ensure a service is in the desired state."""
    _hub.logger.info(f"Policy: Ensuring service '{service}' is {state}")

    # Check current status
    is_running = False
    if _hub.IS_WINDOWS:
        # Check via sc query or powershell
        # PowerShell is more reliable for 'status'
        cmd = [
            "powershell",
            "-Command",
            f"Get-Service -Name {service} | Select-Object -ExpandProperty Status",
        ]
        rc, out = _hub.run_cmd(cmd)
        is_running = "Running" in out
    else:
        # Systemd
        cmd = ["systemctl", "is-active", service]
        rc, out = _hub.run_cmd(cmd)
        is_running = rc == 0

    # Apply state
    if state == "running" and not is_running:
        if _hub.IS_WINDOWS:
            _hub.run_cmd(["net", "start", service])
        else:
            _hub.run_cmd(["systemctl", "start", service])
    elif state == "stopped" and is_running:
        if _hub.IS_WINDOWS:
            _hub.run_cmd(["net", "stop", service])
        else:
            _hub.run_cmd(["systemctl", "stop", service])
    elif state == "restarted":
        if _hub.IS_WINDOWS:
            _hub.run_cmd(["net", "stop", service])
            _hub.run_cmd(["net", "start", service])
        else:
            _hub.run_cmd(["systemctl", "restart", service])

    # Apply enable/disable
    if enable is not None:
        if _hub.IS_WINDOWS:
            mode = "auto" if enable else "disabled"
            _hub.run_cmd(["sc", "config", service, f"start={mode}"])
        else:
            action = "enable" if enable else "disable"
            _hub.run_cmd(["systemctl", action, service])


def apply_file_state(path, content=None, state="present", mode=None):
    """Ensure a file exists with specific content/permissions."""
    _hub.logger.info(f"Policy: File '{path}' -> {state}")

    if state == "absent":
        if os.path.exists(path):
            os.remove(path)
    elif state == "present":
        if content is not None:
            with open(path, "w") as f:
                f.write(content)
        elif not os.path.exists(path):
            # Create empty file if content not specified but present required
            open(path, "a").close()

        if mode and not _hub.IS_WINDOWS:
            # Mode like "0644"
            try:
                os.chmod(path, int(mode, 8))
            except Exception as e:
                _hub.logger.warning(f"Failed to chmod {path}: {e}")


def run_script_step(script, shell="bash"):
    """Run a custom script block."""
    _hub.logger.info(f"Policy: Running script ({shell})")

    if _hub.IS_WINDOWS and shell == "bash":
        shell = "powershell"  # Fallback

    suffix = ".ps1" if shell == "powershell" else ".sh"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w") as f:
        f.write(script)
        script_path = f.name

    try:
        if shell == "powershell":
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path]
        else:
            cmd = [shell, script_path]
            os.chmod(script_path, 0o755)

        rc, out = _hub.run_cmd(cmd)
        if rc != 0:
            raise Exception(f"Script failed (rc={rc}): {out}")
        return out
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


@_hub.app.route("/policy/apply", methods=["POST"])
@_hub._require_auth
def apply_policy():
    """Apply a YAML-based configuration policy."""
    data = request.get_json(silent=True) or {}
    policy_yaml = data.get("policy")

    if not policy_yaml:
        return jsonify({"status": "error", "message": "No policy provided"}), 400

    try:
        import yaml

        policy = yaml.safe_load(policy_yaml)
        name = policy.get("name", "Unknown Policy")
        steps = policy.get("steps", [])
        results = []

        _hub.logger.info(f"Applying Policy: {name}")

        for step in steps:
            step_name = step.get("name", "Unnamed Step")
            module = step.get("module")
            try:
                if module == "service":
                    apply_service_state(
                        step.get("service"),
                        step.get("state", "running"),
                        step.get("enable"),
                    )
                elif module == "file":
                    apply_file_state(
                        step.get("path"),
                        step.get("content"),
                        step.get("state", "present"),
                        step.get("mode"),
                    )
                elif module == "script":
                    out = run_script_step(
                        step.get("run") or step.get("script"), step.get("shell", "bash")
                    )
                    results.append(
                        {"step": step_name, "status": "success", "output": out}
                    )
                    continue  # Skip default success append
                elif module == "package":
                    # Re-use existing package manager logic?
                    pkg = step.get("package")
                    state = step.get("state", "installed")
                    if state == "installed":
                        # Simple install wrapper
                        if _hub.IS_WINDOWS:
                            _hub.run_cmd(
                                ["winget", "install", "-e", "--id", pkg]
                            )  # simplistic
                        else:
                            if shutil.which("apt-get"):
                                _hub.run_cmd(["apt-get", "install", "-y", pkg])
                            elif shutil.which("yum"):
                                _hub.run_cmd(["yum", "install", "-y", pkg])
                    elif state == "absent":
                        if _hub.IS_WINDOWS:
                            _hub.run_cmd(["winget", "uninstall", "-e", "--id", pkg])
                        else:
                            if shutil.which("apt-get"):
                                _hub.run_cmd(["apt-get", "remove", "-y", pkg])
                            elif shutil.which("yum"):
                                _hub.run_cmd(["yum", "remove", "-y", pkg])

                results.append({"step": step_name, "status": "success"})
            except Exception as e:
                _hub.logger.error(f"Step '{step_name}' failed: {e}")
                results.append({"step": step_name, "status": "failed", "error": str(e)})
                if step.get("ignore_errors") is not True:
                    return jsonify(
                        {
                            "status": "failed",
                            "step": step_name,
                            "error": str(e),
                            "results": results,
                        }
                    ), 500

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        _hub.logger.error(f"Policy application failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# === LIVE COMMAND RUNNER ===

_BLOCKED_CMDS = re.compile(
    r"\b(rm\s+-rf\s+/|mkfs|dd\s+if=|:(){ :|:&};:|shutdown|halt|poweroff|init\s+0)\b",
    re.IGNORECASE,
)


@_hub.app.route("/run", methods=["POST"])
@_hub._require_auth
def run_command():
    """Execute an ad-hoc shell command. Blocks destructive patterns.

    Accepts optional 'working_dir' to set the cwd for the command.
    'cd /some/path' commands are handled by updating the working_dir
    in the response so the caller can track state client-side.
    """
    data = request.get_json(silent=True) or {}
    cmd = (data.get("command") or "").strip()
    timeout = int(data.get("timeout") or 30)
    working_dir = (data.get("working_dir") or "").strip() or None

    if not cmd:
        return jsonify({"error": "command required"}), 400
    if _BLOCKED_CMDS.search(cmd):
        return jsonify(
            {"error": "Command blocked: contains potentially destructive operation"}
        ), 400
    if timeout < 1 or timeout > 300:
        timeout = 30

    # Validate working_dir exists if provided
    if working_dir and not os.path.isdir(working_dir):
        return jsonify({"error": f"working_dir not found: {working_dir}"}), 400

    # Handle bare 'cd <path>' — resolve the new dir and return it without running a subprocess
    _cd_match = re.match(r"^cd\s+(.+)$", cmd)
    if _cd_match:
        raw_target = _cd_match.group(1).strip().strip("\"'")
        if raw_target == "-":
            new_dir = working_dir or os.getcwd()
        elif os.path.isabs(raw_target):
            new_dir = raw_target
        else:
            base = working_dir or os.getcwd()
            new_dir = os.path.normpath(os.path.join(base, raw_target))
        if not os.path.isdir(new_dir):
            return jsonify(
                {
                    "rc": 1,
                    "output": f"cd: {raw_target}: No such file or directory",
                    "command": cmd,
                    "working_dir": working_dir or "",
                }
            )
        return jsonify({"rc": 0, "output": "", "command": cmd, "working_dir": new_dir})

    if _hub.IS_WINDOWS:
        shell_cmd = ["cmd.exe", "/c", cmd]
    else:
        shell_cmd = ["bash", "-c", cmd]

    rc, out = _hub.run_cmd(shell_cmd, timeout=timeout, cwd=working_dir)
    return jsonify(
        {"rc": rc, "output": out, "command": cmd, "working_dir": working_dir or ""}
    )
