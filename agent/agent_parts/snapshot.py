"""Snapshot create/list/rollback routes and snapshot internals (split out of
agent.py, plan.md S0-5).

_rollback_snapshot itself stays in agent.py (tests patch hub state around it);
the helpers it names are re-exported there from this module.
"""
import json
import os
import platform
import re
import shutil
import time
import uuid
from datetime import datetime

try:
    from flask import jsonify, request
except ImportError:
    jsonify = request = None

from . import _hub
from .managers import (
    ApkManager,
    AptManager,
    DnfManager,
    FreeBSDPkgManager,
    PacmanManager,
    ZypperManager,
)

# === SNAPSHOTS (packages / services / full-system images) ===


def _capture_services(selected=None):
    data = {"services": []}
    try:
        if _hub.IS_WINDOWS:
            # Use PowerShell for structured output
            cmd = [
                "powershell",
                "-Command",
                "Get-Service | Select Name,Status,StartType | ConvertTo-Json -Compress",
            ]
            rc, out = _hub.run_cmd(cmd, timeout=60)
            if rc == 0:
                data["services"] = json.loads(out)
        else:
            cmd = [
                "systemctl",
                "list-unit-files",
                "--type=service",
                "--no-legend",
                "--no-pager",
            ]
            rc, out = _hub.run_cmd(cmd, timeout=60)
            if rc == 0:
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        data["services"].append({"name": parts[0], "state": parts[1]})
        if selected:
            sel_lower = {s.lower() for s in selected}
            data["services"] = [
                s for s in data["services"] if s.get("name", "").lower() in sel_lower
            ]
    except Exception as e:
        data["error"] = str(e)
    return data


def _bytes_to_human(value):
    num = float(max(int(value or 0), 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while num >= 1024 and idx < len(units) - 1:
        num /= 1024.0
        idx += 1
    return f"{num:.1f} {units[idx]}"


def _resolve_windows_backup_target(windows_backup_target=None):
    target = (
        windows_backup_target
        or os.getenv("PM_WINDOWS_WBADMIN_TARGET")
        or os.getenv("WBADMIN_BACKUP_TARGET")
        or ""
    ).strip()
    if target:
        return target
    ps_pick = (
        "Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveLetter -ne 'C' "
        "-and $_.DriveType -eq 'Fixed' -and $_.SizeRemaining -gt 10737418240 } "
        "| Sort-Object SizeRemaining -Descending "
        "| Select-Object -ExpandProperty DriveLetter | ConvertTo-Json -Compress"
    )
    rc_pick, out_pick = _hub.run_cmd(["powershell", "-Command", ps_pick], timeout=30)
    if rc_pick == 0 and out_pick.strip():
        try:
            parsed = json.loads(out_pick)
            if isinstance(parsed, list) and parsed:
                return f"{parsed[0]}:"
            if isinstance(parsed, str) and parsed:
                return f"{parsed}:"
        except Exception:
            return ""
    return ""


def _windows_target_free_bytes(target):
    raw = (target or "").strip()
    if len(raw) >= 2 and raw[1] == ":":
        drive_path = f"{raw[0]}:\\"
        try:
            return shutil.disk_usage(drive_path).free
        except Exception:
            return None
    ps = (
        "$t='{target}'; "
        "if (-not (Test-Path -LiteralPath $t)) {{ Write-Output ''; exit 0 }}; "
        "$item = Get-Item -LiteralPath $t; "
        "if ($item -and $item.PSDrive) {{ "
        "  [Console]::WriteLine(($item.PSDrive.Free | ConvertTo-Json -Compress)) "
        "}} else {{ Write-Output '' }}"
    ).format(target=raw.replace("'", "''"))
    rc, out = _hub.run_cmd(["powershell", "-Command", ps], timeout=20)
    if rc != 0 or not out.strip():
        return None
    try:
        parsed = json.loads(out.strip())
        return int(parsed)
    except Exception:
        try:
            return int(out.strip())
        except Exception:
            return None


def _parse_wbadmin_versions(output):
    versions = []
    for line in (output or "").splitlines():
        match = re.search(r"Version identifier:\s*(.+)", line, re.IGNORECASE)
        if match:
            versions.append(match.group(1).strip())
    return versions


def _detect_wbadmin_versions(target):
    if not target:
        return []
    rc, out = _hub.run_cmd(
        ["wbadmin", "get", "versions", f"-backuptarget:{target}"], timeout=120
    )
    if rc != 0:
        return []
    return _parse_wbadmin_versions(out)


def _windows_backup_manifest_path(base_path):
    if os.path.isdir(base_path):
        return os.path.join(base_path, "full_system_windows.json")
    return base_path


def _write_windows_backup_manifest(
    path, target, version_identifier="", command_output="", backup_mode="full_system"
):
    manifest = {
        "kind": "windows_wbadmin_backup",
        "backup_mode": backup_mode,
        "backup_target": target,
        "version_identifier": version_identifier or "",
        "created_at": datetime.now().isoformat(),
        "command_output": (command_output or "")[:800],
    }
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def _load_windows_backup_manifest(path):
    manifest_path = _windows_backup_manifest_path(path)
    if not os.path.exists(manifest_path):
        return None
    with open(manifest_path) as f:
        data = json.load(f)
    if (
        data.get("kind") not in ("", "windows_wbadmin_backup", None)
        and "backup_target" not in data
    ):
        return None
    if not data.get("backup_target"):
        return None
    return data


def _resolve_windows_restore_manifest(source_path):
    manifest = _load_windows_backup_manifest(source_path)
    if not manifest:
        return None, None
    return manifest, _windows_backup_manifest_path(source_path)




def _windows_package_identity(pkg):
    raw = str((pkg or {}).get("id") or (pkg or {}).get("name") or "").strip().lower()
    return raw or None


def _windows_install_snapshot_package(pkg):
    package_id = str((pkg or {}).get("id") or "").strip()
    package_name = str((pkg or {}).get("name") or "").strip()
    version = str((pkg or {}).get("version") or "").strip()
    if package_id:
        cmd = [
            "winget",
            "install",
            "--id",
            package_id,
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        if version:
            cmd += ["--version", version, "--force"]
        return _hub.run_cmd(cmd, timeout=900)
    if package_name:
        cmd = [
            "winget",
            "install",
            "--name",
            package_name,
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
        if version:
            cmd += ["--version", version, "--force"]
        return _hub.run_cmd(cmd, timeout=900)
    return 1, "No Windows package identifier available"


def _windows_remove_snapshot_package(pkg):
    package_id = str((pkg or {}).get("id") or "").strip()
    package_name = str((pkg or {}).get("name") or "").strip()
    if package_id:
        return _hub.run_cmd(
            ["winget", "uninstall", "--id", package_id, "--exact", "--silent"],
            timeout=900,
        )
    if package_name:
        return _hub.run_cmd(
            ["winget", "uninstall", "--name", package_name, "--exact", "--silent"],
            timeout=900,
        )
    return 1, "No Windows package identifier available"


def _snapshot_precheck(mode="packages", windows_backup_target=None):
    normalized_mode = str(mode or "packages").strip().lower()
    pre = {
        "ok": True,
        "mode": normalized_mode,
        "os": platform.system(),
        "checks": [],
    }
    try:
        snap_usage = shutil.disk_usage(_hub.SNAPSHOT_DIR)
        pre["checks"].append(
            {
                "name": "snapshot_storage",
                "path": _hub.SNAPSHOT_DIR,
                "free_bytes": snap_usage.free,
                "free_human": _bytes_to_human(snap_usage.free),
            }
        )
    except Exception as e:
        pre["checks"].append({"name": "snapshot_storage", "error": str(e)})
    if normalized_mode != "full_system":
        return pre
    if _hub.IS_WINDOWS:
        target = _resolve_windows_backup_target(windows_backup_target)
        if not target:
            pre["ok"] = False
            pre["error_code"] = "no_backup_target"
            pre["error"] = (
                "No writable backup target available for Windows full-system image"
            )
            return pre
        free_bytes = _windows_target_free_bytes(target)
        min_required = int(
            (
                os.getenv("PM_WINDOWS_FULL_SNAPSHOT_MIN_FREE_BYTES") or "21474836480"
            ).strip()
        )
        check = {
            "name": "windows_backup_target",
            "target": target,
            "required_bytes": min_required,
            "required_human": _bytes_to_human(min_required),
            "free_bytes": free_bytes,
            "free_human": _bytes_to_human(free_bytes)
            if isinstance(free_bytes, int)
            else "unknown",
        }
        pre["checks"].append(check)
        pre["backup_target"] = target
        if isinstance(free_bytes, int) and free_bytes < min_required:
            pre["ok"] = False
            pre["error_code"] = "no_space"
            pre["error"] = f"Not enough free space on backup target {target}"
        return pre
    root_usage = shutil.disk_usage("/")
    estimated_image = max(int(root_usage.used * 0.35), 8 * 1024 * 1024 * 1024)
    min_required = int(
        max(
            int(estimated_image * 1.2),
            int(
                (
                    os.getenv("PM_LINUX_FULL_SNAPSHOT_MIN_FREE_BYTES") or "21474836480"
                ).strip()
            ),
        )
    )
    pre["checks"].append(
        {
            "name": "linux_full_system_space",
            "path": "/",
            "required_bytes": min_required,
            "required_human": _bytes_to_human(min_required),
            "estimated_image_bytes": estimated_image,
            "estimated_image_human": _bytes_to_human(estimated_image),
            "free_bytes": root_usage.free,
            "free_human": _bytes_to_human(root_usage.free),
        }
    )
    if root_usage.free < min_required:
        pre["ok"] = False
        pre["error_code"] = "no_space"
        pre["error"] = "Not enough free disk space for Linux full-system image"
    return pre


def _full_system_image(name, snap_dir, windows_backup_target=None):
    image_path = os.path.join(snap_dir, "full_image.tar.gz")
    if _hub.IS_WINDOWS:
        target = _resolve_windows_backup_target(windows_backup_target)
        if not target:
            raise Exception(
                "No writable backup target available for Windows full_system snapshot. Set PM_WINDOWS_WBADMIN_TARGET or attach writable drive/share."
            )
        versions_before = set(_detect_wbadmin_versions(target))
        cmd = [
            "wbadmin",
            "start",
            "backup",
            f"-backupTarget:{target}",
            "-allCritical",
            "-quiet",
        ]
        rc, out = _hub.run_cmd(cmd, timeout=7200)
        if rc != 0:
            raise Exception(f"wbadmin failed: {out[:400]}")
        versions_after = _detect_wbadmin_versions(target)
        version_identifier = next(
            (v for v in versions_after if v not in versions_before),
            versions_after[0] if versions_after else "",
        )
        manifest_path = _windows_backup_manifest_path(snap_dir)
        _write_windows_backup_manifest(
            manifest_path,
            target,
            version_identifier=version_identifier,
            command_output=out,
            backup_mode="full_system",
        )
        return {
            "manifest_path": manifest_path,
            "backup_target": target,
            "version_identifier": version_identifier,
            "image_size_bytes": os.path.getsize(manifest_path)
            if os.path.exists(manifest_path)
            else 0,
        }
    else:
        tmp_path = f"/tmp/{name}_full.tar.gz"
        cmd = [
            "tar",
            "czf",
            tmp_path,
            "--exclude=/proc",
            "--exclude=/sys",
            "--exclude=/dev",
            "--exclude=/tmp",
            "--exclude=/run",
            "--exclude=/mnt",
            "--exclude=/media",
            "--exclude=/lost+found",
            "--exclude=/var/lib/patch-agent/snapshots",
            "/",
        ]
        rc, out = _hub.run_cmd(cmd, timeout=7200)
        if rc != 0:
            raise Exception(f"Full system image failed: {out[:400]}")
        shutil.move(tmp_path, image_path)
        return os.path.getsize(image_path)


def _create_snapshot(
    name=None, mode="packages", selected_services=None, windows_backup_target=None
):
    if not name:
        # Bug #11 fix: use uuid suffix to prevent name collision when two snapshots
        # are created within the same second (e.g. concurrent requests)
        name = f"snap-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    mode = mode or "packages"
    snap_dir = os.path.join(_hub.SNAPSHOT_DIR, name)
    os.makedirs(snap_dir, exist_ok=True)
    result = {
        "name": name,
        "path": snap_dir,
        "mode": mode,
        "success": False,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "details": {},
    }
    precheck = _snapshot_precheck(
        mode=mode, windows_backup_target=windows_backup_target
    )
    result["precheck"] = precheck
    if not precheck.get("ok", True):
        result["status"] = "failed"
        result["error"] = precheck.get("error") or "Snapshot precheck failed"
        result["error_code"] = precheck.get("error_code") or "precheck_failed"
        _hub.record_job({"type": "snapshot", **result})
        return result
    try:
        # Save current package list (always)
        packages = _hub.pkg_mgr.list_installed()
        with open(os.path.join(snap_dir, "packages.json"), "w") as f:
            json.dump(packages, f, indent=2)
        result["details"]["packages_count"] = len(packages)

        # Services snapshot (all or selected)
        if mode in ("services", "selected_services", "full_system"):
            svc = _capture_services(
                selected_services if mode == "selected_services" else None
            )
            with open(os.path.join(snap_dir, "services.json"), "w") as f:
                json.dump(svc, f, indent=2)
            result["details"]["services_count"] = len(svc.get("services", []))

        # OS-specific repo/source configs for Linux
        if not _hub.IS_WINDOWS:
            sources_dir = os.path.join(snap_dir, "sources")
            os.makedirs(sources_dir, exist_ok=True)

            # Debian/Ubuntu sources
            if os.path.exists("/etc/apt/sources.list"):
                shutil.copy2("/etc/apt/sources.list", sources_dir)
            if os.path.isdir("/etc/apt/sources.list.d"):
                for sf in os.listdir("/etc/apt/sources.list.d"):
                    shutil.copy2(
                        os.path.join("/etc/apt/sources.list.d", sf), sources_dir
                    )

            # RHEL/CentOS/Rocky/Alma repos
            if os.path.isdir("/etc/yum.repos.d"):
                for rf in os.listdir("/etc/yum.repos.d"):
                    shutil.copy2(os.path.join("/etc/yum.repos.d", rf), sources_dir)

            # Arch Linux pacman config and mirrorlist
            if isinstance(_hub.pkg_mgr, _hub.PacmanManager):
                if os.path.exists("/etc/pacman.conf"):
                    shutil.copy2("/etc/pacman.conf", sources_dir)
                if os.path.exists("/etc/pacman.d/mirrorlist"):
                    shutil.copy2("/etc/pacman.d/mirrorlist", sources_dir)

                # Save explicitly installed packages list (useful for Arch)
                rc, explicit_pkgs = _hub.run_cmd(["pacman", "-Qqe"], timeout=30)
                if rc == 0:
                    with open(
                        os.path.join(snap_dir, "explicit_packages.txt"), "w"
                    ) as f:
                        f.write(explicit_pkgs)
                    result["details"]["explicit_packages_count"] = len(
                        explicit_pkgs.strip().split("\n")
                    )

            # openSUSE zypper repos
            if isinstance(_hub.pkg_mgr, _hub.ZypperManager):
                if os.path.isdir("/etc/zypp/repos.d"):
                    for rf in os.listdir("/etc/zypp/repos.d"):
                        shutil.copy2(os.path.join("/etc/zypp/repos.d", rf), sources_dir)
                if os.path.exists("/etc/zypp/zypp.conf"):
                    shutil.copy2("/etc/zypp/zypp.conf", sources_dir)

            # Alpine Linux apk repositories
            if isinstance(_hub.pkg_mgr, _hub.ApkManager):
                if os.path.exists("/etc/apk/repositories"):
                    shutil.copy2("/etc/apk/repositories", sources_dir)
                if os.path.exists("/etc/apk/world"):
                    shutil.copy2("/etc/apk/world", sources_dir)

            # FreeBSD pkg configuration
            if isinstance(_hub.pkg_mgr, _hub.FreeBSDPkgManager):
                if os.path.exists("/usr/local/etc/pkg.conf"):
                    shutil.copy2("/usr/local/etc/pkg.conf", sources_dir)
                if os.path.isdir("/usr/local/etc/pkg/repos"):
                    for rf in os.listdir("/usr/local/etc/pkg/repos"):
                        shutil.copy2(
                            os.path.join("/usr/local/etc/pkg/repos", rf), sources_dir
                        )

        # Full system image (optional)
        image_size = 0
        if mode == "full_system":
            if _hub.IS_WINDOWS:
                try:
                    image_meta = _full_system_image(
                        name, snap_dir, windows_backup_target=windows_backup_target
                    )
                    image_size = int(image_meta.get("image_size_bytes") or 0)
                    result["details"]["image_path"] = image_meta.get("manifest_path")
                    result["details"]["image_size_bytes"] = image_size
                    if image_meta.get("backup_target"):
                        result["details"]["backup_target"] = image_meta["backup_target"]
                    if image_meta.get("version_identifier"):
                        result["details"]["version_identifier"] = image_meta[
                            "version_identifier"
                        ]
                except Exception as e:
                    fallback_enabled = (
                        os.getenv("PM_WINDOWS_FULL_SNAPSHOT_FALLBACK", "1") or "1"
                    ).strip() != "0"
                    if not fallback_enabled:
                        raise e
                    result["details"]["full_system_error"] = str(e)
                    result["details"]["fallback_mode"] = "packages"
                    result["details"]["warning"] = (
                        "Full-system image failed; snapshot saved in packages mode"
                    )
                    result["mode"] = "packages"
                    result["status"] = "degraded"
                    mode = "packages"
            else:
                image_size = _full_system_image(name, snap_dir)
                result["details"]["image_path"] = os.path.join(
                    snap_dir, "full_image.tar.gz"
                )
                result["details"]["image_size_bytes"] = image_size

        meta = {
            "name": name,
            "created": datetime.now().isoformat(),
            "packages_count": result["details"].get("packages_count", 0),
            "services_count": result["details"].get("services_count", 0),
            "mode": mode,
            "os": platform.system(),
            "image_size_bytes": image_size,
        }
        with open(os.path.join(snap_dir, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        result["success"] = True
        if result.get("status") == "running":
            result["status"] = "success"
        result["created"] = meta["created"]
        _hub.logger.info("Snapshot '%s' (%s) created for %s", name, mode, platform.system())
    except Exception as e:
        result["error"] = str(e)
        result["status"] = "failed"
        _hub.logger.error("Snapshot creation failed: %s", e)
    _hub.record_job({"type": "snapshot", **result})
    return result


def _restore_full_snapshot(meta, snap_dir):
    if _hub.IS_WINDOWS:
        manifest_path = _windows_backup_manifest_path(snap_dir)
        if not os.path.exists(manifest_path):
            return {
                "success": False,
                "error": "Windows full-system backup manifest not found",
            }
        try:
            return _hub._restore_windows_backup_manifest(manifest_path)
        except Exception as e:
            return {"success": False, "error": str(e)}
    img_path = os.path.join(snap_dir, "full_image.tar.gz")
    if not os.path.exists(img_path):
        return {"success": False, "error": "Full image not found"}
    # Linux restore (dangerous): untar to /
    cmd = ["tar", "xzf", img_path, "-C", "/", "--numeric-owner", "--overwrite"]
    rc, out = _hub.run_cmd(cmd, timeout=7200)
    return {"success": rc == 0, "rc": rc, "output": out[:800]}



@_hub.app.route("/snapshot/create", methods=["POST"])
@_hub._require_auth
def api_create_snapshot():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode") or "packages"
    services = data.get("services") or []
    backup_target = data.get("backup_target")
    if isinstance(backup_target, str):
        backup_target = backup_target.strip()
    else:
        backup_target = None
    result = _create_snapshot(
        data.get("name"),
        mode=mode,
        selected_services=services,
        windows_backup_target=backup_target,
    )
    return jsonify(result), 200 if result["success"] else 500


@_hub.app.route("/snapshot/precheck", methods=["POST"])
@_hub._require_auth
def api_snapshot_precheck():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode") or "packages"
    backup_target = data.get("backup_target")
    if isinstance(backup_target, str):
        backup_target = backup_target.strip()
    else:
        backup_target = None
    result = _snapshot_precheck(mode=mode, windows_backup_target=backup_target)
    return jsonify(result), 200 if result.get("ok") else 400


@_hub.app.route("/snapshot/list", methods=["GET"])
def api_list_snapshots():
    snapshots = []
    if os.path.isdir(_hub.SNAPSHOT_DIR):
        for name in sorted(os.listdir(_hub.SNAPSHOT_DIR), reverse=True):
            meta_file = os.path.join(_hub.SNAPSHOT_DIR, name, "meta.json")
            if os.path.exists(meta_file):
                try:
                    with open(meta_file) as f:
                        meta = json.load(f)
                    # augment with size if image exists
                    img_path = os.path.join(_hub.SNAPSHOT_DIR, name, "full_image.vhdx")
                    if not os.path.exists(img_path):
                        img_path = os.path.join(_hub.SNAPSHOT_DIR, name, "full_image.tar.gz")
                    if os.path.exists(img_path):
                        meta["image_size_bytes"] = os.path.getsize(img_path)
                        meta["image_path"] = img_path
                    else:
                        manifest_path = _windows_backup_manifest_path(
                            os.path.join(_hub.SNAPSHOT_DIR, name)
                        )
                        if os.path.exists(manifest_path):
                            meta["image_size_bytes"] = os.path.getsize(manifest_path)
                            meta["image_path"] = manifest_path
                    snapshots.append(meta)
                except Exception:
                    snapshots.append({"name": name, "created": "unknown"})
            else:
                snapshots.append({"name": name, "created": "unknown"})
    return jsonify({"snapshots": snapshots, "count": len(snapshots)})


def _safe_snapshot_name(name):
    """Validate snapshot name to prevent path traversal."""
    if not name or not isinstance(name, str):
        return None
    safe = os.path.basename(name)
    if not safe or safe.startswith(".") or "/" in name or "\\" in name:
        return None
    return safe


@_hub.app.route("/snapshot/rollback", methods=["POST"])
@_hub._require_auth
def api_rollback_snapshot():
    data = request.get_json(silent=True) or {}
    # Accept either 'name' directly or 'ref_job_id' (sent by backend rollback endpoint)
    name = data.get("name") or data.get("ref_job_id")
    name = _safe_snapshot_name(str(name)) if name else None
    if not name:
        return jsonify({"error": "valid snapshot name or ref_job_id required"}), 400
    result = _hub._rollback_snapshot(name)
    return jsonify(result), 200 if result["success"] else 500


@_hub.app.route("/snapshot/delete", methods=["POST"])
@_hub._require_auth
def api_delete_snapshot():
    data = request.get_json(silent=True) or {}
    name = _safe_snapshot_name(data.get("name"))
    if not name:
        return jsonify({"error": "valid snapshot name required"}), 400
    snap_dir = os.path.join(_hub.SNAPSHOT_DIR, name)
    if not os.path.realpath(snap_dir).startswith(os.path.realpath(_hub.SNAPSHOT_DIR)):
        return jsonify({"error": "invalid snapshot name"}), 400
    if os.path.isdir(snap_dir):
        shutil.rmtree(snap_dir)
        return jsonify({"deleted": True, "name": name})
    return jsonify({"error": "snapshot not found"}), 404

