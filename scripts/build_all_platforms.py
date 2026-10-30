#!/usr/bin/env python3
"""
Patch-SecOps Solution Platform Build Suite
Builds agent packages for all supported platforms using Docker
"""
import subprocess
import sys
from pathlib import Path

VERSION = "2.0.0"

# Platform configurations - focus on builds that work
PLATFORMS = {
    'ubuntu': {
        'image': 'ubuntu:22.04',
        'setup_cmd': 'apt-get update && apt-get install -y python3 python3-pip python3-venv dpkg-dev fakeroot',
        'build_script': 'agent/build-deb.sh',
        'output': 'agent-latest.deb'
    },
    'debian': {
        'image': 'debian:12',
        'setup_cmd': 'apt-get update && apt-get install -y python3 python3-pip python3-venv dpkg-dev fakeroot',
        'build_script': 'agent/build-deb.sh',
        'output': 'agent-latest.deb'
    },
    'arch': {
        'image': 'archlinux:latest',
        'setup_cmd': 'pacman -Sy --noconfirm python python-pip python-virtualenv base-devel fakeroot zstd tar',
        'build_script': 'agent/build-arch.sh',
        'output': 'agent-latest.pkg.tar.zst'
    },
    'alpine': {
        'image': 'alpine:latest',
        'setup_cmd': 'apk add python3 py3-pip bash tar gzip apk-tools',
        'build_script': 'agent/build-apk.sh',
        'output': 'agent-latest.apk'
    },
    'opensuse': {
        'image': 'opensuse/tumbleweed',
        'setup_cmd': 'zypper refresh && zypper install -y python311 python311-pip rpm-build tar gzip',
        'build_script': 'agent/build-rpm.sh',
        'output': 'agent-latest.rpm'
    },
    'almalinux': {
        'image': 'almalinux:9',
        'setup_cmd': 'dnf install -y python3 python3-pip rpm-build tar gzip',
        'build_script': 'agent/build-rpm.sh',
        'output': 'agent-latest.rpm'
    },
}

def log(msg, level="INFO"):
    colors = {
        "INFO": "\033[94m",
        "OK": "\033[92m",
        "WARN": "\033[93m",
        "FAIL": "\033[91m",
        "RESET": "\033[0m"
    }
    color = colors.get(level, colors["INFO"])
    reset = colors["RESET"]
    print(f"{color}[{level}]{reset} {msg}", flush=True)

def run_wsl_command_stream(command, timeout=600):
    """Run a command in Ubuntu WSL with real-time output streaming"""
    full_cmd = f'echo "sona" | wsl -d Ubuntu -- bash -c "{command}"'
    
    try:
        process = subprocess.Popen(
            ["powershell", "-Command", full_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace'
        )
        
        output_lines = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                if "[sudo]" not in line and "password for" not in line:
                    print(line, end='', flush=True)
                output_lines.append(line)
        
        return process.returncode, ''.join(output_lines)
    except subprocess.TimeoutExpired:
        log(f"Command timed out after {timeout}s", "WARN")
        process.kill()
        return -1, "Timeout"
    except Exception as e:
        log(f"Error: {e}", "FAIL")
        return -1, str(e)

def build_platform_agent(platform_name, config, project_path):
    """Build agent for a specific platform using Docker"""
    if not config['build_script']:
        log(f"Skipping {platform_name.upper()} - no build script", "WARN")
        return None  # Return None for skipped platforms
    
    log(f"Building {platform_name.upper()} package...", "INFO")
    log("-" * 70, "INFO")
    sys.stdout.flush()
    
    wsl_path = project_path.replace('\\', '/').replace('C:', '/mnt/c').replace('c:', '/mnt/c')
    
    # Build complete command as single string
    full_cmd = f"{config['setup_cmd']} && cd /workspace && bash {config['build_script']}"
    docker_cmd = f'sudo -S docker run --pull=never --rm -v {wsl_path}:/workspace {config["image"]} sh -c \'{full_cmd}\''
    
    log(f"Building in {config['image']}...", "INFO")
    rc, output = run_wsl_command_stream(docker_cmd)
    
    if rc == 0:
        log(f"{platform_name.upper()} build PASSED!", "OK")
        return True
    else:
        log(f"{platform_name.upper()} build FAILED", "FAIL")
        return False

def main():
    print("=" * 70)
    print(f"Patch-SecOps Solution Platform Build Suite v{VERSION}")
    print("Builds agent packages using Docker containers")
    print("=" * 70)
    print()
    
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    log(f"Project root: {project_root}", "INFO")
    print()
    
    build_results = {}
    
    for platform_name, config in PLATFORMS.items():
        success = build_platform_agent(platform_name, config, str(project_root))
        build_results[platform_name] = success
        print()
    
    # Summary
    log("=" * 70, "INFO")
    log("BUILD SUMMARY", "INFO")
    log("=" * 70, "INFO")
    print()
    
    build_passed = sum(1 for v in build_results.values() if v is True)
    build_failed = sum(1 for v in build_results.values() if v is False)
    build_skipped = sum(1 for v in build_results.values() if v is None)
    build_total = len([v for v in build_results.values() if v is not None])
    
    for platform, success in build_results.items():
        if success is None:
            log(f"  {platform.upper():15} : SKIP", "WARN")
        elif success:
            log(f"  {platform.upper():15} : PASS", "OK")
        else:
            log(f"  {platform.upper():15} : FAIL", "FAIL")
    
    print()
    log(f"Builds: {build_passed}/{build_total} platforms passed", "INFO")
    if build_skipped > 0:
        log(f"Skipped: {build_skipped} platforms (no build script)", "WARN")
    print()
    
    if build_passed == build_total and build_total > 0:
        log("All builds passed!", "OK")
        log(f"Packages saved to: backend/static/", "INFO")
        return 0
    elif build_passed > 0:
        log(f"{build_passed} builds passed, {build_failed} failed", "WARN")
        log(f"Packages saved to: backend/static/", "INFO")
        return 0  # Partial success is still success
    else:
        log("All builds failed", "FAIL")
        return 1

if __name__ == "__main__":
    sys.exit(main())
