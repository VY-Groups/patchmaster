"""Package manager abstraction (split out of agent.py, plan.md S0-5).

run_cmd / IS_WINDOWS are read through the _hub proxy at call time so tests
patching agent.agent.run_cmd (or agent.run_cmd) keep working.
"""
import json
import os
import platform
import re

from . import _hub

# --- Package Manager Abstraction ---


class BasePackageManager:
    def list_installed(self):
        raise NotImplementedError()

    def list_upgradable(self):
        raise NotImplementedError()

    def refresh(self):
        raise NotImplementedError()

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        raise NotImplementedError()

    def remove(self, packages):
        raise NotImplementedError()

    def _filter_security_packages(self, packages):
        """
        Query backend to filter packages to only those with CVEs.
        Used on platforms without native security classification.

        Args:
            packages: List of package dicts with 'name' key or list of strings

        Returns:
            List of package names that have security vulnerabilities
        """
        try:
            import requests
            import logging

            # Get controller URL and token from environment
            controller_url = os.getenv("CONTROLLER_URL", "http://localhost:3000")
            token = os.getenv("AGENT_TOKEN", "")

            # Get host ID from local cache
            host_id = self._get_host_id()
            if not host_id:
                logging.warning("No host_id found, cannot filter security packages")
                # Fallback: return all packages
                return [
                    p if isinstance(p, str) else p.get("name", "") for p in packages
                ]

            # Extract package names
            pkg_names = []
            for p in packages:
                if isinstance(p, str):
                    pkg_names.append(p)
                elif isinstance(p, dict):
                    pkg_names.append(p.get("name", ""))

            pkg_names = [n for n in pkg_names if n]

            if not pkg_names:
                return []

            # Query backend CVE filter API
            response = requests.post(
                f"{controller_url}/api/cve/filter-security",
                json={
                    "host_id": host_id,
                    "packages": pkg_names,
                    "severity_threshold": "medium",
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                security_pkgs = data.get("security_packages", [])
                logging.info(
                    f"CVE filter: {len(security_pkgs)}/{len(pkg_names)} packages have security issues"
                )
                return security_pkgs
            else:
                # Fallback: install all packages if backend query fails
                logging.warning(
                    f"CVE filter failed with status {response.status_code}, installing all packages"
                )
                return pkg_names

        except Exception as e:
            # Fallback: install all packages if query fails
            logging.warning(f"CVE filter error: {e}, installing all packages")
            return [p if isinstance(p, str) else p.get("name", "") for p in packages]

    def _get_host_id(self):
        """Get host ID from local cache or registration"""
        try:
            # Try multiple locations
            for path in [
                "/var/lib/patch-agent/host_id",
                "/etc/patch-agent/host_id",
                "host_id",
            ]:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        return f.read().strip()
        except Exception:
            pass
        return None


class AptManager(BasePackageManager):
    def list_installed(self):
        rc, out = _hub.run_cmd(
            ["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${Status}\n"],
            timeout=30,
        )
        if rc != 0:
            return []
        packages = []
        for line in out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and "installed" in parts[2].lower():
                packages.append(
                    {"name": parts[0], "version": parts[1], "status": parts[2].strip()}
                )
        return packages

    def list_upgradable(self):
        rc, out = _hub.run_cmd(["apt", "list", "--upgradable"], timeout=30)
        if rc != 0:
            return []
        packages = []
        for line in out.strip().splitlines():
            if (
                not line.strip()
                or line.startswith("Listing")
                or line.startswith("WARNING")
                or "/" not in line
            ):
                continue
            try:
                name_src = line.split("/")[0].strip()
                rest = line.split(" ")
                candidate = rest[1] if len(rest) > 1 else ""
                current = ""
                if "[upgradable from:" in line:
                    current = line.split("[upgradable from:")[1].strip(" ]")
                packages.append(
                    {
                        "name": name_src,
                        "current_version": current,
                        "available_version": candidate,
                    }
                )
            except (IndexError, ValueError):
                continue
        return packages

    def refresh(self):
        return _hub.run_cmd(["apt-get", "update", "-qq"], timeout=120)

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        if local:
            # Use apt-get instead of dpkg for better dependency handling
            # apt-get can install local .deb files and resolve dependencies
            return _hub.run_cmd(
                ["apt-get", "install", "-y", "-qq", "--allow-downgrades"] + packages,
                timeout=600,
            )
        if security_only and not packages:
            cmd = [
                "apt-get",
                "upgrade",
                "-y",
                "-qq",
                "-o",
                "Dir::Etc::SourceList=/etc/apt/sources.list.d/security.list",
                "-o",
                "Dir::Etc::SourceParts=/dev/null",
            ]
        elif not packages:
            cmd = ["apt-get", "upgrade", "-y", "-qq"]
        else:
            cmd = ["apt-get", "install", "-y", "-qq"]
        if exclude_kernel:
            cmd += [
                "--exclude=linux-image*",
                "--exclude=linux-headers*",
                "--exclude=linux-modules*",
            ]
        if extra_flags:
            cmd += [f for f in extra_flags if isinstance(f, str)]
        return _hub.run_cmd(cmd + packages, timeout=600)

    def remove(self, packages):
        return _hub.run_cmd(["apt-get", "remove", "-y", "-qq"] + packages, timeout=600)

    def check_reboot(self):
        return os.path.exists("/var/run/reboot-required")


class DnfManager(BasePackageManager):
    def __init__(self):
        # Detect whether to use dnf or yum (Amazon Linux 2 uses yum, AL2023+ uses dnf)
        self.cmd = "dnf" if os.path.exists("/usr/bin/dnf") else "yum"

    def list_installed(self):
        rc, out = _hub.run_cmd(
            [
                "rpm",
                "-qa",
                "--queryformat",
                "%{NAME}\t%{VERSION}-%{RELEASE}\tinstalled\n",
            ],
            timeout=30,
        )
        if rc != 0:
            return []
        packages = []
        for line in out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                packages.append(
                    {"name": parts[0], "version": parts[1], "status": parts[2]}
                )
        return packages

    def list_upgradable(self):
        rc, out = _hub.run_cmd([self.cmd, "check-update", "--quiet"], timeout=60)
        # dnf/yum check-update returns 100 if updates are available
        if rc not in [0, 100]:
            return []
        packages = []
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3 and "." in parts[0]:
                name = parts[0].rsplit(".", 1)[0]
                packages.append(
                    {
                        "name": name,
                        "current_version": "unknown",
                        "available_version": parts[1],
                    }
                )
        return packages

    def refresh(self):
        return _hub.run_cmd([self.cmd, "makecache"], timeout=120)

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        if local:
            # Use localinstall for both yum and dnf
            return _hub.run_cmd([self.cmd, "localinstall", "-y"] + packages, timeout=600)
        if security_only and not packages:
            cmd = [self.cmd, "upgrade", "-y", "--security"]
        elif not packages:
            cmd = [self.cmd, "upgrade", "-y"]
        else:
            cmd = [self.cmd, "install", "-y"]
        if exclude_kernel:
            cmd += ["--exclude=kernel*"]
        if extra_flags:
            cmd += [f for f in extra_flags if isinstance(f, str)]
        return _hub.run_cmd(cmd + packages, timeout=600)

    def remove(self, packages):
        return _hub.run_cmd([self.cmd, "remove", "-y"] + packages, timeout=600)

    def check_reboot(self):
        # Check if reboot is required (works for both yum and dnf)
        if self.cmd == "dnf":
            # dnf needs-restarting -r returns 1 if reboot needed
            rc, _ = _hub.run_cmd(["dnf", "needs-restarting", "-r"], timeout=30)
            return rc == 1
        else:
            # For yum (Amazon Linux 2), check if kernel was updated
            rc, out = _hub.run_cmd(["rpm", "-q", "--last", "kernel"], timeout=30)
            if rc == 0:
                lines = out.strip().splitlines()
                if len(lines) > 1:
                    # Multiple kernels installed, likely needs reboot
                    return True
            # Also check for /var/run/reboot-required (some systems create this)
            return os.path.exists("/var/run/reboot-required")


class WinManager(BasePackageManager):
    def list_installed(self):
        # Using PowerShell to list installed applications (WMI/Get-Package)
        ps_cmd = "Get-Package | Select-Object Name, Version | ConvertTo-Json"
        rc, out = _hub.run_cmd(["powershell", "-Command", ps_cmd], timeout=60)
        if rc != 0:
            return []
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            return [
                {"name": d["Name"], "version": d["Version"], "status": "installed"}
                for d in data
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def list_upgradable(self):
        rc, out = _hub.run_cmd(["winget", "upgrade"], timeout=60)
        if rc != 0:
            return []
        packages = []
        lines = out.strip().splitlines()
        # Find the header line to determine column positions
        header_idx = next(
            (i for i, l in enumerate(lines) if "Id" in l and "Version" in l), -1
        )
        if header_idx < 0:
            return packages
        for line in lines[header_idx + 2 :]:  # skip header + separator
            line = line.rstrip()
            if not line or line.startswith("-"):
                continue
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) >= 4:
                packages.append(
                    {
                        "name": parts[0],
                        "id": parts[1] if len(parts) > 1 else "",
                        "current_version": parts[2] if len(parts) > 2 else "",
                        "available_version": parts[3] if len(parts) > 3 else "",
                    }
                )
        return packages

    def refresh(self):
        return _hub.run_cmd(["winget", "source", "update"], timeout=60)

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        results = []
        last_rc, last_out = 0, ""
        for pkg in packages:
            if pkg.endswith(".msi"):
                rc, out = _hub.run_cmd(
                    ["msiexec", "/i", pkg, "/quiet", "/norestart"], timeout=600
                )
            elif pkg.endswith(".exe"):
                rc, out = _hub.run_cmd([pkg, "/S"], timeout=600)
            else:
                rc, out = _hub.run_cmd(
                    [
                        "winget",
                        "install",
                        "--id",
                        pkg,
                        "--silent",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ],
                    timeout=600,
                )
            results.append((rc, out))
            if rc != 0:
                last_rc, last_out = rc, out
        # Return first failure if any, otherwise last success
        failed = [(rc, out) for rc, out in results if rc != 0]
        if failed:
            return failed[0]
        return results[-1] if results else (0, "")

    def remove(self, packages):
        results = []
        for pkg in packages:
            rc, out = _hub.run_cmd(
                ["winget", "uninstall", "--id", pkg, "--silent"], timeout=600
            )
            results.append((rc, out))
        failed = [(rc, out) for rc, out in results if rc != 0]
        if failed:
            return failed[0]
        return results[-1] if results else (0, "")

    def check_reboot(self):
        # Check registry for pending reboot
        ps_cmd = """
        $r1 = Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired';
        $r2 = Test-Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\PendingFileRenameOperations';
        if ($r1 -or $r2) { exit 1 } else { exit 0 }
        """
        rc, _ = _hub.run_cmd(["powershell", "-Command", ps_cmd], timeout=30)
        return rc == 1


class PacmanManager(BasePackageManager):
    """Package manager for Arch Linux using pacman with AUR support via yay"""

    def __init__(self):
        """Initialize and check for AUR helper availability"""
        self.aur_helper = self._detect_aur_helper()

    def _detect_aur_helper(self):
        """Detect which AUR helper is available (yay, paru, or none)"""
        # Check for yay (most popular)
        rc, _ = _hub.run_cmd(["which", "yay"], timeout=5)
        if rc == 0:
            return "yay"

        # Check for paru (alternative)
        rc, _ = _hub.run_cmd(["which", "paru"], timeout=5)
        if rc == 0:
            return "paru"

        # No AUR helper found
        return None

    def _is_aur_package(self, package):
        """Check if a package is from AUR"""
        if not self.aur_helper:
            return False

        # Check if package exists in official repos
        rc, _ = _hub.run_cmd(["pacman", "-Si", package], timeout=5)
        if rc == 0:
            return False  # Package is in official repos

        # Check if package exists in AUR
        if self.aur_helper == "yay":
            rc, _ = _hub.run_cmd(["yay", "-Si", package], timeout=10)
        elif self.aur_helper == "paru":
            rc, _ = _hub.run_cmd(["paru", "-Si", package], timeout=10)
        else:
            return False

        return rc == 0  # Package found in AUR

    def list_installed(self):
        """List all installed packages (including AUR packages)"""
        rc, out = _hub.run_cmd(["pacman", "-Q"], timeout=30)
        if rc != 0:
            return []

        result = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                pkg_name = parts[0]
                pkg_version = parts[1]

                # Check if it's an AUR package
                is_aur = False
                if self.aur_helper:
                    rc_check, _ = _hub.run_cmd(["pacman", "-Qi", pkg_name], timeout=5)
                    if rc_check == 0:
                        # Check the repository field
                        rc_repo, repo_out = _hub.run_cmd(
                            ["pacman", "-Qi", pkg_name], timeout=5
                        )
                        if rc_repo == 0 and "Repository" in repo_out:
                            # If repository is "None" or not found, it's likely AUR
                            for repo_line in repo_out.split("\n"):
                                if repo_line.startswith("Repository"):
                                    if (
                                        "None" in repo_line
                                        or "local" in repo_line.lower()
                                    ):
                                        is_aur = True
                                    break

                result.append(
                    {
                        "name": pkg_name,
                        "version": pkg_version,
                        "status": "installed",
                        "source": "aur" if is_aur else "official",
                    }
                )
        return result

    def list_upgradable(self):
        """List packages with available updates (including AUR packages)"""
        result = []

        # First sync databases
        _hub.run_cmd(["pacman", "-Sy"], timeout=60)

        # Get official repo updates
        rc, out = _hub.run_cmd(["pacman", "-Qu"], timeout=30)
        if rc == 0:
            for line in out.strip().split("\n"):
                if not line.strip():
                    continue
                # Format: package_name old_version -> new_version
                parts = line.split()
                if len(parts) >= 4 and parts[2] == "->":
                    pkg_name = parts[0]
                    old_version = parts[1]
                    new_version = parts[3]
                    result.append(
                        {
                            "name": pkg_name,
                            "current_version": old_version,
                            "candidate_version": new_version,
                            "source": "official",
                        }
                    )

        # Get AUR updates if helper is available
        if self.aur_helper:
            if self.aur_helper == "yay":
                rc, out = _hub.run_cmd(["yay", "-Qua"], timeout=60)
            elif self.aur_helper == "paru":
                rc, out = _hub.run_cmd(["paru", "-Qua"], timeout=60)
            else:
                rc = 1

            if rc == 0:
                for line in out.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] == "->":
                        pkg_name = parts[0]
                        old_version = parts[1]
                        new_version = parts[3]
                        result.append(
                            {
                                "name": pkg_name,
                                "current_version": old_version,
                                "candidate_version": new_version,
                                "source": "aur",
                            }
                        )

        return result

    def refresh(self):
        """Sync package databases (including AUR if helper available)"""
        # Sync official repos
        rc, out = _hub.run_cmd(["pacman", "-Sy"], timeout=120)

        # Sync AUR database if helper available
        if self.aur_helper:
            if self.aur_helper == "yay":
                _hub.run_cmd(["yay", "-Sy"], timeout=120)
            elif self.aur_helper == "paru":
                _hub.run_cmd(["paru", "-Sy"], timeout=120)

        return rc == 0

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        """Install packages (supports both official repos and AUR)"""

        # NEW: Security-only filtering via backend CVE database
        if security_only and not local and not packages:
            # Get all upgradable packages
            upgradable = self.list_upgradable()
            if not upgradable:
                return 0, "No upgradable packages"

            # Query backend for security packages
            security_pkgs = self._filter_security_packages(upgradable)
            if not security_pkgs:
                return 0, "No security updates available"

            packages = security_pkgs

        if not packages:
            return 0, "No packages specified"

        # Filter kernel packages if requested
        if exclude_kernel:
            packages = [p for p in packages if not p.startswith("linux")]

        if not packages:
            return 0, "All packages filtered out"

        # Separate AUR and official packages
        aur_packages = []
        official_packages = []

        if not local and self.aur_helper:
            for pkg in packages:
                if self._is_aur_package(pkg):
                    aur_packages.append(pkg)
                else:
                    official_packages.append(pkg)
        else:
            official_packages = packages

        results = []

        # Install official packages with pacman
        if official_packages:
            if local:
                cmd = ["pacman", "-U", "--noconfirm"]
            else:
                cmd = ["pacman", "-S", "--noconfirm"]

            if extra_flags:
                cmd.extend(extra_flags)

            cmd.extend(official_packages)
            rc, out = _hub.run_cmd(cmd, timeout=3600)
            results.append((rc, out))

        # Install AUR packages with helper
        if aur_packages and self.aur_helper:
            if self.aur_helper == "yay":
                cmd = ["yay", "-S", "--noconfirm"]
            elif self.aur_helper == "paru":
                cmd = ["paru", "-S", "--noconfirm"]

            if extra_flags:
                cmd.extend(extra_flags)

            cmd.extend(aur_packages)
            rc, out = _hub.run_cmd(cmd, timeout=3600)
            results.append((rc, out))

        # Return combined results
        if not results:
            return 0, "No packages to install"

        # If any installation failed, return the first failure
        for rc, out in results:
            if rc != 0:
                return rc, out

        # All succeeded
        return results[-1] if results else (0, "Success")

    def remove(self, packages):
        """Remove packages (works for both official and AUR packages)"""
        if not packages:
            return 0, "No packages specified"

        # pacman can remove both official and AUR packages
        cmd = ["pacman", "-R", "--noconfirm"] + packages
        rc, out = _hub.run_cmd(cmd, timeout=600)
        return rc, out

    def check_reboot(self):
        """Check if system reboot is required"""
        # Check if kernel or systemd was updated
        # Compare running kernel with installed kernel

        # Get running kernel version
        rc, running_kernel = _hub.run_cmd(["uname", "-r"], timeout=5)
        if rc != 0:
            return False

        running_kernel = running_kernel.strip()

        # Get installed kernel version
        rc, out = _hub.run_cmd(["pacman", "-Q", "linux"], timeout=5)
        if rc != 0:
            # Try linux-lts
            rc, out = _hub.run_cmd(["pacman", "-Q", "linux-lts"], timeout=5)

        if rc == 0:
            # Parse version from "linux X.Y.Z-arch1-1"
            parts = out.strip().split()
            if len(parts) >= 2:
                installed_version = parts[1]
                # Check if versions differ
                if installed_version not in running_kernel:
                    return True

        # Check if systemd was updated (requires reboot)
        # For simplicity, check if systemd service needs restart
        rc, _ = _hub.run_cmd(["systemctl", "is-system-running"], timeout=5)
        if rc not in [0, 1]:  # 0=running, 1=degraded (both ok)
            return True

        return False

    def install_aur_helper(self):
        """Install yay AUR helper if not present (requires manual intervention)"""
        if self.aur_helper:
            return 0, f"AUR helper '{self.aur_helper}' already installed"

        # Check if git and base-devel are installed
        rc, _ = _hub.run_cmd(["pacman", "-Q", "git"], timeout=5)
        if rc != 0:
            return (
                1,
                "git is required but not installed. Install with: pacman -S git base-devel",
            )

        # Note: Installing yay requires building from AUR, which needs a non-root user
        # This is typically done manually or via a setup script
        return (
            1,
            "AUR helper installation requires manual setup. See: https://github.com/Jguer/yay#installation",
        )


class ZypperManager(BasePackageManager):
    """Package manager for openSUSE using zypper"""

    def list_installed(self):
        """List all installed packages"""
        rc, out = _hub.run_cmd(
            [
                "rpm",
                "-qa",
                "--queryformat",
                "%{NAME}\t%{VERSION}-%{RELEASE}\tinstalled\n",
            ],
            timeout=30,
        )
        if rc != 0:
            return []

        result = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                result.append(
                    {
                        "name": parts[0],
                        "version": parts[1],
                        "status": parts[2] if len(parts) > 2 else "installed",
                    }
                )
        return result

    def list_upgradable(self):
        """List packages with available updates"""
        rc, out = _hub.run_cmd(["zypper", "list-updates"], timeout=60)
        if rc != 0:
            return []

        result = []
        in_table = False
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            # Skip header lines
            if "S | Repository" in line or "--|--" in line:
                in_table = True
                continue
            if not in_table:
                continue

            # Parse table format: v | repo | name | current -> available
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                pkg_name = parts[2]
                versions = parts[3].split("->")
                if len(versions) == 2:
                    result.append(
                        {
                            "name": pkg_name,
                            "current_version": versions[0].strip(),
                            "candidate_version": versions[1].strip(),
                        }
                    )
        return result

    def refresh(self):
        """Refresh package repositories"""
        rc, out = _hub.run_cmd(["zypper", "refresh"], timeout=120)
        return rc == 0

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        """Install packages"""
        if not packages:
            return 0, "No packages specified"

        # Filter kernel packages if requested
        if exclude_kernel:
            packages = [p for p in packages if not p.startswith("kernel-")]

        if not packages:
            return 0, "All packages filtered out"

        # Build command
        if local:
            cmd = ["zypper", "--non-interactive", "install", "--allow-unsigned-rpm"]
        else:
            cmd = ["zypper", "--non-interactive", "install"]

        # Security-only updates
        if security_only and not local:
            cmd = ["zypper", "--non-interactive", "patch", "--category", "security"]
            rc, out = _hub.run_cmd(cmd, timeout=3600)
            return rc, out

        # Add extra flags
        if extra_flags:
            cmd.extend(extra_flags)

        cmd.extend(packages)
        rc, out = _hub.run_cmd(cmd, timeout=3600)
        return rc, out

    def remove(self, packages):
        """Remove packages"""
        if not packages:
            return 0, "No packages specified"

        cmd = ["zypper", "--non-interactive", "remove"] + packages
        rc, out = _hub.run_cmd(cmd, timeout=600)
        return rc, out

    def check_reboot(self):
        """Check if system reboot is required"""
        # Check for reboot-needed file
        if os.path.exists("/var/run/reboot-needed"):
            return True

        # Check with zypper ps
        rc, out = _hub.run_cmd(["zypper", "ps", "-s"], timeout=10)
        if rc == 0 and "reboot" in out.lower():
            return True

        # Check if kernel was updated
        rc, running_kernel = _hub.run_cmd(["uname", "-r"], timeout=5)
        if rc != 0:
            return False

        running_kernel = running_kernel.strip()

        # Get installed kernel version
        rc, out = _hub.run_cmd(["rpm", "-q", "kernel-default"], timeout=5)
        if rc == 0:
            # Parse version from rpm output
            for line in out.strip().split("\n"):
                if "kernel-default" in line:
                    # Extract version from package name
                    if running_kernel not in line:
                        return True

        return False


class ApkManager(BasePackageManager):
    """Package manager for Alpine Linux using apk"""

    def list_installed(self):
        """List all installed packages"""
        rc, out = _hub.run_cmd(["apk", "info", "-v"], timeout=30)
        if rc != 0:
            return []

        result = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            # Format: package-name-version
            # Split on last dash to separate name and version
            parts = line.rsplit("-", 2)
            if len(parts) >= 2:
                pkg_name = "-".join(parts[:-2]) if len(parts) > 2 else parts[0]
                pkg_version = "-".join(parts[-2:])
                result.append(
                    {"name": pkg_name, "version": pkg_version, "status": "installed"}
                )
        return result

    def list_upgradable(self):
        """List packages with available updates"""
        rc, out = _hub.run_cmd(["apk", "version", "-l", "<"], timeout=30)
        if rc != 0:
            return []

        result = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            # Format: package-name-current < package-name-available
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "<":
                # Extract package name and versions
                current = parts[0]
                available = parts[2]

                # Parse package name (remove version)
                pkg_parts = current.rsplit("-", 2)
                if len(pkg_parts) >= 2:
                    pkg_name = (
                        "-".join(pkg_parts[:-2]) if len(pkg_parts) > 2 else pkg_parts[0]
                    )
                    current_ver = "-".join(pkg_parts[-2:])

                    avail_parts = available.rsplit("-", 2)
                    avail_ver = (
                        "-".join(avail_parts[-2:])
                        if len(avail_parts) >= 2
                        else available
                    )

                    result.append(
                        {
                            "name": pkg_name,
                            "current_version": current_ver,
                            "candidate_version": avail_ver,
                        }
                    )
        return result

    def refresh(self):
        """Update package index"""
        rc, out = _hub.run_cmd(["apk", "update"], timeout=120)
        return rc == 0

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        """Install packages"""

        # NEW: Security-only filtering via backend CVE database
        if security_only and not local and not packages:
            # Get all upgradable packages
            upgradable = self.list_upgradable()
            if not upgradable:
                return 0, "No upgradable packages"

            # Query backend for security packages
            security_pkgs = self._filter_security_packages(upgradable)
            if not security_pkgs:
                return 0, "No security updates available"

            packages = security_pkgs

        if not packages:
            return 0, "No packages specified"

        # Filter kernel packages if requested
        if exclude_kernel:
            packages = [p for p in packages if not p.startswith("linux-")]

        if not packages:
            return 0, "All packages filtered out"

        # Build command
        cmd = ["apk", "add"]

        # Add extra flags
        if extra_flags:
            cmd.extend(extra_flags)
        else:
            cmd.append("--no-interactive")

        cmd.extend(packages)

        rc, out = _hub.run_cmd(cmd, timeout=3600)
        return rc, out

    def remove(self, packages):
        """Remove packages"""
        if not packages:
            return 0, "No packages specified"

        cmd = ["apk", "del", "--no-interactive"] + packages
        rc, out = _hub.run_cmd(cmd, timeout=600)
        return rc, out

    def check_reboot(self):
        """Check if system reboot is required"""
        # Check if kernel was updated
        rc, running_kernel = _hub.run_cmd(["uname", "-r"], timeout=5)
        if rc != 0:
            return False

        running_kernel = running_kernel.strip()

        # Get installed kernel version
        rc, out = _hub.run_cmd(["apk", "info", "-v", "linux-lts"], timeout=5)
        if rc != 0:
            # Try other kernel packages
            rc, out = _hub.run_cmd(["apk", "info", "-v", "linux-virt"], timeout=5)

        if rc == 0:
            # Check if installed version differs from running
            if running_kernel not in out:
                return True

        return False


class FreeBSDPkgManager(BasePackageManager):
    """Package manager for FreeBSD using pkg"""

    def list_installed(self):
        """List all installed packages"""
        rc, out = _hub.run_cmd(["pkg", "info"], timeout=30)
        if rc != 0:
            return []

        result = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            # Format: package-name-version  Description
            parts = line.split()
            if len(parts) >= 1:
                # Split package-version
                pkg_full = parts[0]
                pkg_parts = pkg_full.rsplit("-", 1)
                if len(pkg_parts) == 2:
                    result.append(
                        {
                            "name": pkg_parts[0],
                            "version": pkg_parts[1],
                            "status": "installed",
                        }
                    )
        return result

    def list_upgradable(self):
        """List packages with available updates"""
        rc, out = _hub.run_cmd(["pkg", "version", "-l", "<"], timeout=30)
        if rc != 0:
            return []

        result = []
        for line in out.strip().split("\n"):
            if not line.strip():
                continue
            # Format: package-name-version < needs updating (index has newer version)
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "<":
                pkg_full = parts[0]
                pkg_parts = pkg_full.rsplit("-", 1)
                if len(pkg_parts) == 2:
                    result.append(
                        {
                            "name": pkg_parts[0],
                            "current_version": pkg_parts[1],
                            "candidate_version": "newer",  # pkg doesn't show exact version
                        }
                    )
        return result

    def refresh(self):
        """Update package repository catalog"""
        rc, out = _hub.run_cmd(["pkg", "update", "-f"], timeout=120)
        return rc == 0

    def install(
        self,
        packages,
        local=False,
        security_only=False,
        exclude_kernel=False,
        extra_flags=None,
    ):
        """Install packages"""

        # NEW: Security-only filtering via backend CVE database
        if security_only and not local and not packages:
            # Get all upgradable packages
            upgradable = self.list_upgradable()
            if not upgradable:
                return 0, "No upgradable packages"

            # Query backend for security packages
            security_pkgs = self._filter_security_packages(upgradable)
            if not security_pkgs:
                return 0, "No security updates available"

            packages = security_pkgs

        if not packages:
            return 0, "No packages specified"

        # Filter kernel packages if requested
        if exclude_kernel:
            packages = [p for p in packages if not p.startswith("kernel")]

        if not packages:
            return 0, "All packages filtered out"

        # Build command
        cmd = ["pkg", "install", "-y"]

        # Add extra flags
        if extra_flags:
            cmd.extend(extra_flags)

        cmd.extend(packages)

        rc, out = _hub.run_cmd(cmd, timeout=3600)
        return rc, out

    def remove(self, packages):
        """Remove packages"""
        if not packages:
            return 0, "No packages specified"

        cmd = ["pkg", "delete", "-y"] + packages
        rc, out = _hub.run_cmd(cmd, timeout=600)
        return rc, out

    def check_reboot(self):
        """Check if system reboot is required"""
        # Check if kernel was updated
        rc, running_kernel = _hub.run_cmd(["uname", "-r"], timeout=5)
        if rc != 0:
            return False

        running_kernel = running_kernel.strip()

        # Check if there's a newer kernel installed
        rc, out = _hub.run_cmd(["pkg", "info", "FreeBSD-kernel"], timeout=5)
        if rc == 0:
            # Parse version from output
            for line in out.strip().split("\n"):
                if "Version" in line:
                    version = line.split(":")[-1].strip()
                    if version not in running_kernel:
                        return True

        return False


def get_pkg_manager():
    if _hub.IS_WINDOWS:
        return WinManager()

    # Check for Solaris (uses IPS/pkg)
    if _check_solaris():
        return _hub.SolarisManager() if _hub.SolarisManager else BasePackageManager()

    # Check for HP-UX (uses SD-UX/swinstall)
    if _check_hpux():
        return _hub.HPUXManager() if _hub.HPUXManager else BasePackageManager()

    # Check for AIX (uses installp/NIM)
    if _check_aix():
        return _hub.AIXManager() if _hub.AIXManager else BasePackageManager()

    # Check for FreeBSD (uses pkg)
    if platform.system() == "FreeBSD" or os.path.exists("/usr/local/sbin/pkg"):
        return FreeBSDPkgManager()

    # Check for Alpine Linux (uses apk)
    if os.path.exists("/sbin/apk") or os.path.exists("/usr/sbin/apk"):
        if os.path.exists("/etc/alpine-release"):
            return ApkManager()
        # Also check os-release
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release") as f:
                    content = f.read().lower()
                    if "id=alpine" in content:
                        return ApkManager()
            except (IOError, OSError):
                pass

    # Check for openSUSE (uses zypper)
    if os.path.exists("/usr/bin/zypper"):
        return ZypperManager()

    # Check for Arch Linux (uses pacman)
    if os.path.exists("/usr/bin/pacman"):
        # Verify it's actually Arch Linux
        if os.path.exists("/etc/arch-release"):
            return PacmanManager()
        # Also check os-release for Arch-based distros (Manjaro, EndeavourOS, etc.)
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release") as f:
                    content = f.read().lower()
                    if (
                        "id=arch" in content
                        or "id_like=arch" in content
                        or "id=manjaro" in content
                    ):
                        return PacmanManager()
            except (IOError, OSError):
                pass

    # Check for Amazon Linux (uses yum/dnf)
    if os.path.exists("/etc/system-release"):
        try:
            with open("/etc/system-release") as f:
                content = f.read().lower()
                if "amazon linux" in content:
                    # Amazon Linux 2023+ uses dnf, AL2 uses yum
                    if os.path.exists("/usr/bin/dnf"):
                        return DnfManager()
                    elif os.path.exists("/usr/bin/yum"):
                        return DnfManager()  # DnfManager handles both yum and dnf
        except (IOError, OSError):
            pass

    # Standard detection
    if os.path.exists("/usr/bin/apt-get"):
        return AptManager()
    if os.path.exists("/usr/bin/dnf"):
        return DnfManager()  # Fedora, RHEL 8+, CentOS 8+
    if os.path.exists("/usr/bin/yum"):
        return DnfManager()  # Fallback for RHEL/CentOS

    return BasePackageManager()


def _check_solaris() -> bool:
    """Check if running on Solaris/OpenSolaris."""
    try:
        # Check kernel name
        rc, out = _hub.run_cmd(["uname", "-s"], timeout=5)
        if rc == 0:
            system = out.strip().lower()
            if "sunos" in system or "solaris" in system:
                return True

        # Check for Solaris-specific files
        if os.path.exists("/usr/sbin/unixd"):
            return True
        if os.path.exists("/etc/release"):
            try:
                with open("/etc/release") as f:
                    content = f.read().lower()
                    if "solaris" in content or "opensolaris" in content:
                        return True
            except (IOError, OSError):
                pass
    except (IOError, OSError):
        pass
    return False


def _check_hpux() -> bool:
    """Check if running on HP-UX."""
    try:
        # Check kernel name
        rc, out = _hub.run_cmd(["uname", "-s"], timeout=5)
        if rc == 0:
            system = out.strip().lower()
            if "hp-ux" in system or "hpux" in system:
                return True

        # Check for HP-UX-specific files
        if os.path.exists("/usr/sbin/swagentd"):
            return True
        if os.path.exists("/usr/sbin/swinstall"):
            return True
    except (IOError, OSError):
        pass
    return False


def _check_aix() -> bool:
    """Check if running on AIX."""
    try:
        # Check kernel name
        rc, out = _hub.run_cmd(["uname", "-s"], timeout=5)
        if rc == 0:
            system = out.strip().lower()
            if system == "aix":
                return True

        # Check for AIX-specific files
        if os.path.exists("/etc/AIX"):
            return True
        if os.path.exists("/usr/sbin/nimclient"):
            return True
    except (IOError, OSError):
        pass
    return False


def get_solaris_manager():
    """Get SolarisManager if on Solaris, else None."""
    if _hub.SolarisManager and _check_solaris():
        return _hub.SolarisManager()
    return None


def get_hpux_manager():
    """Get HPUXManager if on HP-UX, else None."""
    if _hub.HPUXManager and _check_hpux():
        return _hub.HPUXManager()
    return None


def get_aix_manager():
    """Get AIXManager if on AIX, else None."""
    if _hub.AIXManager and _check_aix():
        return _hub.AIXManager()
    return None


def detect_package_manager():
    """Detect and return the appropriate package manager.

    Returns:
        A tuple of (manager_name, manager_instance) for the detected OS.
    """
    if _hub.IS_WINDOWS:
        return ("windows", WinManager())

    if _check_solaris() and _hub.SolarisManager:
        return ("solaris", _hub.SolarisManager())
    if _check_hpux() and _hub.HPUXManager:
        return ("hpux", _hub.HPUXManager())
    if _check_aix() and _hub.AIXManager:
        return ("aix", _hub.AIXManager())

    if platform.system() == "FreeBSD" or os.path.exists("/usr/local/sbin/pkg"):
        return ("freebsd", FreeBSDPkgManager())

    if os.path.exists("/sbin/apk") or os.path.exists("/usr/sbin/apk"):
        if os.path.exists("/etc/alpine-release"):
            return ("alpine", ApkManager())
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release") as f:
                    content = f.read().lower()
                    if "id=alpine" in content:
                        return ("alpine", ApkManager())
            except (IOError, OSError):
                pass

    if os.path.exists("/usr/bin/zypper"):
        return ("opensuse", ZypperManager())

    if os.path.exists("/usr/bin/pacman"):
        if os.path.exists("/etc/arch-release"):
            return ("arch", PacmanManager())
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release") as f:
                    content = f.read().lower()
                    if (
                        "id=arch" in content
                        or "id_like=arch" in content
                        or "id=manjaro" in content
                    ):
                        return ("arch", PacmanManager())
            except (IOError, OSError):
                pass

    if os.path.exists("/usr/bin/apt-get"):
        return ("debian", AptManager())
    if os.path.exists("/usr/bin/dnf"):
        return ("rhel", DnfManager())
    if os.path.exists("/usr/bin/yum"):
        return ("rhel", DnfManager())

    return ("unknown", BasePackageManager())

