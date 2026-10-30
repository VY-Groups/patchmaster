"""Offline package upload/install routes and worker (split out of agent.py,
plan.md S0-5)."""
import glob
import os
import threading
import time
import uuid

try:
    from flask import jsonify, request
except ImportError:
    jsonify = request = None

from . import _hub



# === OFFLINE PATCHING ===


@_hub.app.route("/offline/upload", methods=["POST"])
@_hub._require_auth
def offline_upload():
    try:
        files = request.files.getlist("file")
        if not files:
            _hub.logger.warning("offline_upload: no files provided in request")
            return jsonify({"error": "no files provided"}), 400

        # Ensure OFFLINE_DIR exists
        os.makedirs(_hub.OFFLINE_DIR, exist_ok=True)

        saved = []
        # Support .deb, .rpm, .msi, .exe
        valid_exts = (".deb", ".rpm", ".msi", ".exe")
        for f in files:
            if not f.filename or not any(
                f.filename.lower().endswith(ext) for ext in valid_exts
            ):
                _hub.logger.warning(f"offline_upload: skipping invalid file {f.filename}")
                continue
            safe_name = os.path.basename(f.filename)
            dest = os.path.join(_hub.OFFLINE_DIR, safe_name)
            if not os.path.realpath(dest).startswith(os.path.realpath(_hub.OFFLINE_DIR)):
                _hub.logger.warning(
                    f"offline_upload: path traversal attempt blocked for {safe_name}"
                )
                continue
            try:
                f.save(dest)
                saved.append(safe_name)
                _hub.logger.info(
                    f"offline_upload: saved {safe_name} ({os.path.getsize(dest)} bytes)"
                )
            except Exception as save_err:
                _hub.logger.error(f"offline_upload: failed to save {safe_name}: {save_err}")
                continue

        _hub.logger.info(
            f"offline_upload: successfully saved {len(saved)} file(s) to {_hub.OFFLINE_DIR}"
        )
        return jsonify({"uploaded": saved, "count": len(saved), "path": _hub.OFFLINE_DIR})
    except Exception as e:
        _hub.logger.error(f"offline_upload: unexpected error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@_hub.app.route("/offline/list", methods=["GET"])
def offline_list():
    pkgs = []
    if os.path.isdir(_hub.OFFLINE_DIR):
        for f in sorted(os.listdir(_hub.OFFLINE_DIR)):
            fpath = os.path.join(_hub.OFFLINE_DIR, f)
            pkgs.append(
                {
                    "name": f,
                    "size": os.path.getsize(fpath),
                    "size_mb": round(os.path.getsize(fpath) / 1048576, 2),
                }
            )
    return jsonify({"pkgs": pkgs, "count": len(pkgs)})


def _run_offline_task(
    pkg_files, auto_snapshot, auto_rollback, auto_reboot=False, post_patch_script=None
):
    _hub.patch_gauge.set(1)
    result = {
        "success": False,
        "snapshot": None,
        "install_output": "",
        "rollback": None,
        "files": [os.path.basename(f) for f in pkg_files],
        "reboot_required": False,
        "post_script_output": "",
    }
    try:
        if auto_snapshot:
            snap = _hub._create_snapshot(
                f"pre-offline-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            )
            result["snapshot"] = snap

        rc, out = _hub.pkg_mgr.install(pkg_files, local=True)
        result["install_output"] += out

        patch_success = rc == 0
        if not patch_success and auto_rollback:
            if result.get("snapshot", {}).get("success"):
                rb = _hub._rollback_snapshot(result["snapshot"]["name"])
                result["rollback"] = rb

        result["success"] = patch_success
        _hub.patch_gauge.set(2 if patch_success else 3)
        if patch_success:
            _hub.last_patch_ts.set(time.time())

        # Post-install script
        if post_patch_script and patch_success:
            rc_post, out_post = _hub.run_cmd(["bash", "-c", post_patch_script], timeout=120)
            result["post_script_output"] = out_post

        # Reboot check
        checker = getattr(_hub.pkg_mgr, "check_reboot", None)
        if callable(checker):
            result["reboot_required"] = bool(checker())
        if result["reboot_required"] and auto_reboot and patch_success:
            result["reboot_scheduled"] = True
            threading.Timer(
                10.0,
                lambda: _hub.run_cmd(
                    ["shutdown", "/r", "/t", "30"]
                    if _hub.IS_WINDOWS
                    else ["shutdown", "-r", "+1"]
                ),
            ).start()

    except Exception as e:
        result["error"] = str(e)
        _hub.patch_gauge.set(3)
    return result


@_hub.app.route("/offline/install", methods=["POST"])
@_hub._require_auth
def offline_install():
    data = request.get_json(silent=True) or {}
    auto_snapshot = data.get("auto_snapshot", True)
    auto_rollback = data.get("auto_rollback", True)
    auto_reboot = bool(data.get("auto_reboot", False))
    post_patch_script = str(data.get("post_patch_script") or "").strip() or None
    selected = data.get("files", [])

    pkg_files = []
    if selected:
        for f in selected:
            safe = os.path.basename(f)
            full = os.path.join(_hub.OFFLINE_DIR, safe)
            if os.path.exists(full) and os.path.realpath(full).startswith(
                os.path.realpath(_hub.OFFLINE_DIR)
            ):
                pkg_files.append(full)
    else:
        for ext in ("*.deb", "*.rpm", "*.msi", "*.exe"):
            pkg_files.extend(glob.glob(os.path.join(_hub.OFFLINE_DIR, ext)))

    if not pkg_files:
        return jsonify({"error": "no package files found"}), 400

    ok, msg = _hub.run_async_job(
        "offline_install",
        _run_offline_task,
        pkg_files,
        auto_snapshot,
        auto_rollback,
        auto_reboot,
        post_patch_script,
    )
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "started", "job": "offline_install"})


@_hub.app.route("/offline/clear", methods=["POST"])
@_hub._require_auth
def offline_clear():
    removed = []
    for ext in ("*.deb", "*.rpm", "*.msi", "*.exe"):
        for f in glob.glob(os.path.join(_hub.OFFLINE_DIR, ext)):
            os.remove(f)
            removed.append(os.path.basename(f))
    return jsonify({"cleared": removed, "count": len(removed)})
