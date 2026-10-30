#!/usr/bin/env python3
"""
PatchMaster Agent Uninstaller
Cross-platform uninstaller for Windows and Linux
Can be compiled to .exe using PyInstaller
"""
import os
import sys
import platform
import subprocess
import shutil
import time

IS_WINDOWS = platform.system() == "Windows"

def is_admin():
    """Check if running with admin/root privileges"""
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        return os.geteuid() == 0

def log(msg):
    """Print log message"""
    print(f"[UNINSTALL] {msg}")

def run_cmd(cmd, ignore_errors=True):
    """Run command and return success status"""
    try:
        if IS_WINDOWS:
            # reason: every run_cmd caller passes a hardcoded literal command (no interpolation)
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # nosec B602
        else:
            result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        if not ignore_errors:
            log(f"Error running command: {e}")
        return False

def stop_windows_service():
    """Stop and remove Windows service"""
    log("Stopping Windows service...")
    run_cmd("net stop PatchMasterAgent")
    run_cmd("sc delete PatchMasterAgent")
    log("Windows service stopped and removed")

def stop_linux_service():
    """Stop and disable Linux systemd services"""
    log("Stopping Linux services...")
    run_cmd(["systemctl", "stop", "patch-agent.service"])
    run_cmd(["systemctl", "stop", "patch-agent-heartbeat.service"])
    run_cmd(["systemctl", "disable", "patch-agent.service"])
    run_cmd(["systemctl", "disable", "patch-agent-heartbeat.service"])
    run_cmd(["systemctl", "daemon-reload"])
    
    # Kill any remaining processes
    run_cmd(["pkill", "-f", "patch-agent"])
    run_cmd(["pkill", "-f", "patch-agent-heartbeat"])
    log("Linux services stopped and disabled")

def remove_windows_package():
    """Remove Windows installation"""
    log("Removing Windows installation...")
    
    # Try Windows Installer (MSI)
    run_cmd('wmic product where name="PatchMaster Agent" call uninstall /nointeractive')
    
    # Remove directories
    dirs_to_remove = [
        r"C:\Program Files\PatchMaster-Agent",
        r"C:\ProgramData\PatchMaster-Agent",
    ]
    
    for dir_path in dirs_to_remove:
        if os.path.exists(dir_path):
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
                log(f"Removed: {dir_path}")
            except Exception as e:
                log(f"Could not remove {dir_path}: {e}")
    
    # Remove from registry (startup)
    run_cmd('reg delete "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" /v PatchMasterAgent /f')
    
    # Remove scheduled tasks
    run_cmd('schtasks /delete /tn "PatchMaster*" /f')
    
    log("Windows installation removed")

def remove_linux_package():
    """Remove Linux package"""
    log("Removing Linux package...")
    
    # Try different package managers
    if shutil.which("apt-get"):
        run_cmd(["apt-get", "remove", "-y", "patch-agent"])
        run_cmd(["apt-get", "purge", "-y", "patch-agent"])
    elif shutil.which("dnf"):
        run_cmd(["dnf", "remove", "-y", "patch-agent"])
    elif shutil.which("yum"):
        run_cmd(["yum", "remove", "-y", "patch-agent"])
    elif shutil.which("rpm"):
        run_cmd(["rpm", "-e", "patch-agent"])
    
    # Remove directories
    dirs_to_remove = [
        "/opt/patch-agent",
        "/etc/patch-agent",
        "/var/log/patch-agent",
        "/var/lib/patch-agent",
        "/usr/local/bin/patch-agent",
    ]
    
    for dir_path in dirs_to_remove:
        if os.path.exists(dir_path):
            try:
                if os.path.isdir(dir_path):
                    shutil.rmtree(dir_path, ignore_errors=True)
                else:
                    os.remove(dir_path)
                log(f"Removed: {dir_path}")
            except Exception as e:
                log(f"Could not remove {dir_path}: {e}")
    
    # Remove systemd service files
    service_files = [
        "/etc/systemd/system/patch-agent.service",
        "/etc/systemd/system/patch-agent-heartbeat.service",
        "/usr/lib/systemd/system/patch-agent.service",
        "/usr/lib/systemd/system/patch-agent-heartbeat.service",
    ]
    
    for service_file in service_files:
        if os.path.exists(service_file):
            try:
                os.remove(service_file)
                log(f"Removed: {service_file}")
            except Exception as e:
                log(f"Could not remove {service_file}: {e}")
    
    run_cmd(["systemctl", "daemon-reload"])
    log("Linux package removed")

def confirm_uninstall():
    """Ask user for confirmation"""
    print("\n" + "="*60)
    print("  PatchMaster Agent Uninstaller")
    print("="*60)
    print("\nThis will completely remove the PatchMaster Agent from this system.")
    print("\nThe following will be removed:")
    if IS_WINDOWS:
        print("  - PatchMaster Agent Windows Service")
        print("  - C:\\Program Files\\PatchMaster-Agent")
        print("  - C:\\ProgramData\\PatchMaster-Agent")
        print("  - Registry entries")
        print("  - Scheduled tasks")
    else:
        print("  - patch-agent systemd services")
        print("  - /opt/patch-agent")
        print("  - /var/lib/patch-agent")
        print("  - /var/log/patch-agent")
        print("  - Package from system")
    
    print("\n" + "="*60)
    response = input("\nAre you sure you want to continue? (yes/no): ").strip().lower()
    return response in ['yes', 'y']

def main():
    """Main uninstall process"""
    # Check if running as admin/root
    if not is_admin():
        if IS_WINDOWS:
            print("ERROR: This program must be run as Administrator")
            print("Right-click the EXE and select 'Run as administrator'")
        else:
            print("ERROR: This script must be run as root (use sudo)")
        sys.exit(1)
    
    # Confirm uninstall
    if not confirm_uninstall():
        print("\nUninstall cancelled.")
        sys.exit(0)
    
    print("\nStarting uninstall process...\n")
    time.sleep(1)
    
    try:
        if IS_WINDOWS:
            # Windows uninstall
            stop_windows_service()
            remove_windows_package()
        else:
            # Linux uninstall
            stop_linux_service()
            remove_linux_package()
        
        print("\n" + "="*60)
        print("  ✓ PatchMaster Agent successfully uninstalled!")
        print("="*60)
        print("\nThe agent has been completely removed from this system.")
        print("You can now safely close this window.\n")
        
    except Exception as e:
        print(f"\n✗ Error during uninstall: {e}")
        print("Some components may not have been removed.")
        print("Please check the output above for details.\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
