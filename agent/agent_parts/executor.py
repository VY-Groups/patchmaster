"""Patch execution route and worker (split out of agent.py, plan.md S0-5)."""
import re
import threading
import time
import uuid

try:
    from flask import jsonify, request
except ImportError:
    jsonify = request = None

from . import _hub


# === PATCH EXECUTION with snapshot + rollback ===


def _run_patch_task(
    packages,
    hold,
    dry_run,
    auto_snapshot,
    auto_rollback,
    security_only=False,
    exclude_kernel=False,
    auto_reboot=False,
    pre_patch_script=None,
    post_patch_script=None,
    extra_flags=None,
):
    _hub.patch_gauge.set(1)
    result = {
        "success": False,
        "snapshot": None,
        "patch_output": "",
        "rollback": None,
        "dry_run": dry_run,
        "reboot_required": False,
        "pre_script_output": "",
        "post_script_output": "",
        "verification": {},
    }
    try:
        # Pre-patch script
        if pre_patch_script and not dry_run:
            rc_pre, out_pre = _hub.run_cmd(["bash", "-c", pre_patch_script], timeout=120)
            result["pre_script_output"] = out_pre
            if rc_pre != 0:
                result["error"] = (
                    f"Pre-patch script failed (rc={rc_pre}): {out_pre[:500]}"
                )
                _hub.patch_gauge.set(3)
                return result

        if auto_snapshot and not dry_run:
            snap_result = _hub._create_snapshot(
                f"pre-patch-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            )
            result["snapshot"] = snap_result

        # Hold packages (Apt only for now)
        if hasattr(_hub.pkg_mgr, "hold"):
            for pkg in hold:
                _hub.run_cmd(["apt-mark", "hold", pkg])

        # Capture versions before patch for verification
        before_versions = {}
        if packages and not dry_run:
            for pkg in packages:
                installed = _hub.pkg_mgr.list_installed()
                match = next((p for p in installed if p["name"] == pkg), None)
                if match:
                    before_versions[pkg] = match.get("version", "")

        _hub.pkg_mgr.refresh()
        rc, out = _hub.pkg_mgr.install(
            packages,
            security_only=security_only,
            exclude_kernel=exclude_kernel,
            extra_flags=extra_flags or [],
        )
        result["patch_output"] += out
        patch_success = rc == 0

        if hasattr(_hub.pkg_mgr, "unhold"):
            for pkg in hold:
                _hub.run_cmd(["apt-mark", "unhold", pkg])

        # Post-patch verification: check versions changed
        if patch_success and packages and not dry_run:
            after_installed = _hub.pkg_mgr.list_installed()
            after_map = {p["name"]: p.get("version", "") for p in after_installed}
            verification = {}
            for pkg in packages:
                before = before_versions.get(pkg, "")
                after = after_map.get(pkg, "")
                verification[pkg] = {
                    "before": before,
                    "after": after,
                    "updated": bool(after and after != before),
                }
            result["verification"] = verification

        if not patch_success and auto_rollback and not dry_run:
            if result.get("snapshot", {}).get("success"):
                rb = _hub._rollback_snapshot(result["snapshot"]["name"])
                result["rollback"] = rb
                _hub.record_job(
                    {
                        "type": "patch_rollback",
                        "patch_snapshot": result["snapshot"]["name"],
                        **rb,
                    }
                )

        result["success"] = patch_success
        _hub.patch_gauge.set(2 if patch_success else 3)
        if patch_success:
            _hub.last_patch_ts.set(time.time())

        # Post-patch script
        if post_patch_script and patch_success and not dry_run:
            rc_post, out_post = _hub.run_cmd(["bash", "-c", post_patch_script], timeout=120)
            result["post_script_output"] = out_post

        # Reboot check
        checker = getattr(_hub.pkg_mgr, "check_reboot", None)
        if callable(checker):
            result["reboot_required"] = bool(checker())
        if result["reboot_required"] and auto_reboot and patch_success and not dry_run:
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


@_hub.app.route("/patch/execute", methods=["POST"])
@_hub._require_auth
def execute_patch():
    data = request.get_json(silent=True) or {}
    _valid_pkg = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+\-_]+$")
    packages = [
        p.strip()
        for p in data.get("packages", [])
        if isinstance(p, str) and _valid_pkg.match(p.strip())
    ]
    hold = [
        h.strip()
        for h in data.get("hold", [])
        if isinstance(h, str) and _valid_pkg.match(h.strip())
    ]
    dry_run = data.get("dry_run", False)
    auto_snapshot = data.get("auto_snapshot", True)
    auto_rollback = data.get("auto_rollback", True)
    security_only = bool(data.get("security_only", False))
    exclude_kernel = bool(data.get("exclude_kernel", False))
    auto_reboot = bool(data.get("auto_reboot", False))
    pre_patch_script = str(data.get("pre_patch_script") or "").strip() or None
    post_patch_script = str(data.get("post_patch_script") or "").strip() or None
    extra_flags = [
        str(f)
        for f in (data.get("extra_flags") or [])
        if isinstance(f, str) and f.strip().startswith("-")
    ]

    ok, msg = _hub.run_async_job(
        "patch",
        _run_patch_task,
        packages,
        hold,
        dry_run,
        auto_snapshot,
        auto_rollback,
        security_only,
        exclude_kernel,
        auto_reboot,
        pre_patch_script,
        post_patch_script,
        extra_flags,
    )
    if not ok:
        return jsonify({"error": msg}), 409
    return jsonify({"status": "started", "job": "patch"})
