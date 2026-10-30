"""Backup trigger/restore routes and backup backends (split out of agent.py,
plan.md S0-5).

backup_full_system stays in agent.py (tests patch hub state around it).
"""
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from datetime import datetime

try:
    from flask import jsonify, request
except ImportError:
    jsonify = request = None

from . import _hub


# === BACKUP FEATURES ===


def backup_database(db_type, connection_string, output_file):
    _hub.logger.info(f"Backing up database {db_type} to {output_file}")

    if db_type == "postgres":
        cmd = ["pg_dump", "--format=c", "--file", output_file, connection_string]
        rc, out = _hub.run_cmd(cmd)
        if rc != 0:
            raise Exception(f"pg_dump failed: {out}")

    elif db_type == "mysql":
        # Parse the connection string into argv elements (same pattern as redis above).
        # Supports both DSN-style flags ("--host=db --user=root mydb") and a bare
        # database name.  shlex.split preserves quoted values and avoids shell=True.
        import shlex

        conn_args = shlex.split(connection_string) if connection_string else []
        with open(output_file, "wb") as out_fh:
            process = subprocess.run(
                ["mysqldump"] + conn_args,
                stdout=out_fh,
                stderr=subprocess.PIPE,
            )
        if process.returncode != 0:
            raise Exception(
                f"mysqldump failed: {process.stderr.decode(errors='replace')}"
            )

    elif db_type == "mongodb":
        cmd = ["mongodump", f"--uri={connection_string}", f"--archive={output_file}"]
        rc, out = _hub.run_cmd(cmd)
        if rc != 0:
            raise Exception(f"mongodump failed: {out}")

    elif db_type == "redis":
        # Redis RDB backup
        # connection_string expected as extra cli args e.g. '-h HOST -p PORT -a PASS' or empty for local
        import shlex

        extra_args = shlex.split(connection_string) if connection_string else []
        cmd = ["redis-cli"] + extra_args + ["--rdb", output_file]
        rc, out = _hub.run_cmd(cmd)
        if rc != 0:
            raise Exception(f"redis backup failed: {out}")

    elif db_type == "sqlite":
        # connection_string is the path to the sqlite file
        if not os.path.exists(connection_string):
            raise FileNotFoundError(f"SQLite DB not found: {connection_string}")
        shutil.copy2(connection_string, output_file)

    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    return output_file


def backup_files(source_path, output_file):
    _hub.logger.info(f"Backing up files from {source_path} to {output_file}")
    if os.path.isdir(source_path):
        base_name = output_file.replace(".zip", "")
        shutil.make_archive(base_name, "zip", source_path)
        final_path = base_name + ".zip"
        if final_path != output_file and os.path.exists(final_path):
            if os.path.exists(output_file):
                os.remove(output_file)
            shutil.move(final_path, output_file)
    elif os.path.isfile(source_path):
        shutil.copy2(source_path, output_file)
    else:
        raise FileNotFoundError(f"Source path {source_path} not found")
    return output_file


def backup_vm(vm_name, output_file):
    _hub.logger.info(f"VM Backup requested for {vm_name}")
    # Real implementation would interface with VBoxManage, virsh, or Hyper-V
    # Here we mock it but add capability check

    # Example: Check for VBoxManage
    if shutil.which("VBoxManage"):
        # cmd = ["VBoxManage", "snapshot", vm_name, "take", f"backup_{int(time.time())}"]
        # run_cmd(cmd)
        pass

    with open(output_file, "w") as f:
        f.write(f"VM Backup Metadata for {vm_name} at {datetime.now()}\n")
        f.write("Status: Success (Mock)\n")
    return output_file


def backup_live(source_path, output_file):
    if _hub.IS_WINDOWS:
        # Use list form to avoid shell=True injection on source/destination
        cmd = ["robocopy", source_path, output_file, "/MIR", "/R:0", "/W:0"]
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        # robocopy exit codes 0-7 are success/informational; 8+ indicate errors
        if proc.returncode >= 8:
            raise Exception(
                f"robocopy failed (rc={proc.returncode}): {proc.stdout[:400]}"
            )
    else:
        src = source_path if source_path.endswith("/") else source_path + "/"
        dst = output_file if output_file.endswith("/") else output_file + "/"
        # Use rsync for efficient live sync
        cmd = ["rsync", "-av", "--update", "--delete", src, dst]
        rc, out = _hub.run_cmd(cmd)
        if rc != 0:
            raise Exception(f"rsync failed: {out}")
    return output_file




@_hub.app.route("/backup/trigger", methods=["POST"])
@_hub._require_auth
def trigger_backup():
    data = request.get_json(silent=True) or {}
    b_type = data.get("type")
    log_id = data.get("log_id")

    # Input Sanitization
    allowed_types = ["database", "file", "vm", "live", "full_system"]
    if b_type not in allowed_types:
        return jsonify({"status": "error", "message": "Invalid backup type"}), 400

    source = data.get("source")
    dest = data.get("destination")
    db_type = data.get("db_type")

    # Async Execution Wrapper
    def run_backup_task(data, dest):
        started_at = time.time()
        try:
            # Retention Policy
            retention_count = data.get("retention_count", 5)
            # Find old backups of SAME type and prefix
            prefix = f"backup_{b_type}_"
            backups = sorted(
                [
                    os.path.join(_hub.SNAPSHOT_DIR, f)
                    for f in os.listdir(_hub.SNAPSHOT_DIR)
                    if f.startswith(prefix)
                ]
            )
            while len(backups) >= retention_count:
                oldest = backups.pop(0)
                try:
                    if os.path.isdir(oldest):
                        shutil.rmtree(oldest)
                    else:
                        os.remove(oldest)
                    _hub.logger.info(f"Retention: Deleted old backup {oldest}")
                except Exception as e:
                    _hub.logger.error(f"Failed to delete old backup {oldest}: {e}")

            if b_type == "database":
                backup_database(db_type, source, dest)
            elif b_type == "file":
                backup_files(source, dest)
            elif b_type == "vm":
                backup_vm(source, dest)
            elif b_type == "live":
                backup_live(source, dest)
            elif b_type == "full_system":
                _hub.backup_full_system(dest)

            # Encryption (Optional)
            enc_key = data.get("encryption_key")
            if enc_key and b_type != "live":
                enc_dest = dest + ".enc"
                cmd = [
                    "openssl",
                    "enc",
                    "-aes-256-cbc",
                    "-salt",
                    "-pbkdf2",
                    "-in",
                    dest,
                    "-out",
                    enc_dest,
                    "-k",
                    enc_key,
                ]
                rc, out = _hub.run_cmd(cmd)
                if rc == 0:
                    os.remove(dest)
                    dest = enc_dest
                else:
                    _hub.logger.error(f"Encryption failed: {out}")
                    raise Exception(f"Encryption failed: {out}")

            _hub.logger.info(f"Backup completed successfully: {dest}")
            _hub._report_backup_result(
                log_id=log_id,
                status="success",
                output_file=dest,
                duration_seconds=max(time.time() - started_at, 0.0),
                file_size_bytes=_hub._path_size_bytes(dest),
            )
        except Exception as e:
            _hub.logger.error(f"Backup job failed: {e}")
            _hub._report_backup_result(
                log_id=log_id,
                status="failed",
                output_file=dest,
                duration_seconds=max(time.time() - started_at, 0.0),
                file_size_bytes=_hub._path_size_bytes(dest),
                message=str(e),
            )

    if not dest:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not os.path.exists(_hub.SNAPSHOT_DIR):
            os.makedirs(_hub.SNAPSHOT_DIR)
        dest = os.path.join(_hub.SNAPSHOT_DIR, f"backup_{b_type}_{ts}")
        if b_type == "file":
            dest += ".zip"
        if b_type == "database":
            dest += ".dump"
        if b_type == "vm":
            dest += ".img"
        if b_type == "full_system":
            dest += ".json" if _hub.IS_WINDOWS else ".tar.gz"

    # Start in background thread
    threading.Thread(target=run_backup_task, args=(data, dest), daemon=True).start()

    return jsonify(
        {
            "status": "started",
            "output_file": dest,
            "message": "Backup job started in background",
        }
    )


@_hub.app.route("/backup/restore", methods=["POST"])
@_hub._require_auth
def restore_backup():
    """Restore a backup file to a target path.

    Accepts JSON body:
      - source_path: path to the backup file/directory on this host
      - target_path: destination path to restore to (defaults to source_path from config)
      - backup_type: 'file', 'database', 'live', etc. (optional, inferred from extension)
    """
    data = request.get_json(silent=True) or {}
    source_path = data.get("source_path") or data.get("storage_path") or ""
    target_path = data.get("target_path") or source_path

    if not source_path:
        return jsonify({"error": "source_path is required"}), 400

    manifest, manifest_path = (
        _hub._resolve_windows_restore_manifest(source_path) if _hub.IS_WINDOWS else (None, None)
    )

    # Restore is a privileged backend-mediated operation. Accept only local,
    # absolute filesystem paths and let archive extraction safety enforce that
    # members stay under the chosen target root.
    for label, path_value in (("source_path", source_path),):
        if "://" in path_value:
            return jsonify({"error": f"{label} must be a local filesystem path"}), 400
        if not os.path.isabs(path_value):
            return jsonify({"error": f"{label} must be an absolute path"}), 400

    if not os.path.exists(source_path):
        return jsonify({"error": f"source_path not found: {source_path}"}), 404

    try:
        if manifest:
            backup_target_override = (
                str(data.get("backup_target") or "").strip() or None
            )
            if backup_target_override and "://" in backup_target_override:
                return jsonify(
                    {"error": "backup_target must be a local drive letter or UNC path"}
                ), 400
            result = _hub._restore_windows_backup_manifest(
                manifest_path, target_override=backup_target_override
            )
            if not result.get("success"):
                return jsonify(result), 500
            _hub.logger.info("Windows backup restore completed from %s", source_path)
            return jsonify(
                {
                    "status": "success",
                    "source": source_path,
                    "backup_target": result.get("backup_target"),
                    "version": result.get("version"),
                    "attempts": result.get("attempts", []),
                }
            )

        if "://" in target_path:
            return jsonify(
                {"error": "target_path must be a local filesystem path"}
            ), 400
        if not os.path.isabs(target_path):
            return jsonify({"error": "target_path must be an absolute path"}), 400

        if os.path.isdir(source_path):
            if os.path.exists(target_path):
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
            shutil.copytree(source_path, target_path)
        elif source_path.endswith(".zip"):
            os.makedirs(target_path, exist_ok=True)
            with zipfile.ZipFile(source_path, "r") as zf:
                _hub._safe_extract_zip(zf, target_path)
        elif source_path.endswith((".tar.gz", ".tgz")):
            os.makedirs(target_path, exist_ok=True)
            with tarfile.open(source_path, "r:gz") as tf:
                _hub._safe_extract_tar(tf, target_path)
        else:
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            shutil.copy2(source_path, target_path)

        _hub.logger.info(f"Restore completed: {source_path} -> {target_path}")
        return jsonify(
            {"status": "success", "source": source_path, "target": target_path}
        )
    except Exception as e:
        _hub.logger.error(f"Restore failed: {e}")
        return jsonify({"error": str(e)}), 500

