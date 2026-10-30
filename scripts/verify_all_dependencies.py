#!/usr/bin/env python3
"""
Patch-SecOps Solution Comprehensive Dependency & Syntax Verification
Checks all requirements, dependencies, and build scripts across all platforms
"""

import os
import sys
import subprocess
from pathlib import Path

# Colors
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    NC = '\033[0m'

def log(msg): print(f"{Colors.BLUE}[INFO]{Colors.NC} {msg}")
def success(msg): print(f"{Colors.GREEN}[OK]{Colors.NC} {msg}")
def error(msg): print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")
def warn(msg): print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")

# Get project root
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

def check_file_exists(filepath, description):
    """Check if a file exists"""
    path = PROJECT_ROOT / filepath
    if path.exists():
        success(f"{description}: {filepath}")
        return True
    else:
        error(f"{description} MISSING: {filepath}")
        return False

def check_python_syntax(filepath):
    """Check Python file syntax"""
    path = PROJECT_ROOT / filepath
    if not path.exists():
        error(f"File not found: {filepath}")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            success(f"Python syntax OK: {filepath}")
            return True
        else:
            error(f"Python syntax ERROR in {filepath}:")
            print(result.stderr)
            return False
    except Exception as e:
        error(f"Failed to check {filepath}: {e}")
        return False

def check_requirements_file(filepath):
    """Check requirements.txt file"""
    path = PROJECT_ROOT / filepath
    if not path.exists():
        error(f"Requirements file not found: {filepath}")
        return False, []
    
    with open(path, 'r') as f:
        lines = f.readlines()
    
    packages = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            packages.append(line)
    
    success(f"Requirements file OK: {filepath} ({len(packages)} packages)")
    return True, packages

def main():
    print("=" * 70)
    print("Patch-SecOps Solution Comprehensive Verification")
    print("=" * 70)
    print()
    
    errors = []
    warnings = []
    
    # 1. Check Requirements Files
    log("Checking requirements files...")
    agent_req_ok, agent_packages = check_requirements_file("agent/requirements.txt")
    backend_req_ok, backend_packages = check_requirements_file("backend/requirements.txt")
    
    if not agent_req_ok:
        errors.append("agent/requirements.txt missing or invalid")
    if not backend_req_ok:
        errors.append("backend/requirements.txt missing or invalid")
    
    print()
    
    # 2. Check Agent Dependencies
    log("Verifying agent dependencies...")
    required_agent_deps = ['Flask', 'prometheus_client', 'psutil', 'requests', 'pydantic', 'PyYAML']
    for dep in required_agent_deps:
        found = any(dep.lower() in pkg.lower() for pkg in agent_packages)
        if found:
            success(f"Agent dependency found: {dep}")
        else:
            error(f"Agent dependency MISSING: {dep}")
            errors.append(f"Missing agent dependency: {dep}")
    
    print()
    
    # 3. Check Backend Dependencies
    log("Verifying backend dependencies...")
    required_backend_deps = ['fastapi', 'uvicorn', 'pydantic', 'sqlalchemy', 'asyncpg', 'PyJWT', 'passlib', 'prometheus-client']
    for dep in required_backend_deps:
        found = any(dep.lower() in pkg.lower() for pkg in backend_packages)
        if found:
            success(f"Backend dependency found: {dep}")
        else:
            error(f"Backend dependency MISSING: {dep}")
            errors.append(f"Missing backend dependency: {dep}")
    
    print()
    
    # 4. Check Python Files Syntax
    log("Checking Python syntax...")
    python_files = [
        "agent/agent.py",
        "agent/main.py",
        "agent/build_agent_artifacts.py",
        "agent/uninstall_agent.py",
        "backend/main.py",
        "backend/auth.py",
        "backend/database.py",
        "backend/license.py",
    ]
    
    for pyfile in python_files:
        if not check_python_syntax(pyfile):
            errors.append(f"Syntax error in {pyfile}")
    
    print()
    
    # 5. Check Build Scripts
    log("Checking build scripts...")
    build_scripts = [
        "agent/build-deb.sh",
        "agent/build-rpm.sh",
        "agent/build-arch.sh",
        "scripts/collect_wheels.sh",
    ]
    
    for script in build_scripts:
        if check_file_exists(script, "Build script"):
            pass
        else:
            warnings.append(f"Build script missing: {script}")
    
    print()
    
    # 6. Check Critical Files
    log("Checking critical files...")
    critical_files = [
        ("agent/agent.py", "Agent main file"),
        ("agent/main.py", "Agent heartbeat file"),
        ("backend/main.py", "Backend main file"),
        ("frontend/src/App.js", "Frontend main file"),
        ("frontend/src/OnboardingPage.jsx", "Onboarding page"),
    ]
    
    for filepath, description in critical_files:
        if not check_file_exists(filepath, description):
            errors.append(f"Critical file missing: {filepath}")
    
    print()
    
    # 7. Check Package Manager Implementations
    log("Checking package manager implementations...")
    
    # Read agent.py and check for all package managers
    agent_path = PROJECT_ROOT / "agent/agent.py"
    if agent_path.exists():
        with open(agent_path, 'r', encoding='utf-8') as f:
            agent_content = f.read()
        
        package_managers = [
            'AptManager',
            'DnfManager',
            'WinManager',
            'PacmanManager',
            'ZypperManager',
            'ApkManager',
            'FreeBSDPkgManager'
        ]
        
        for pm in package_managers:
            if f"class {pm}" in agent_content:
                success(f"Package manager implemented: {pm}")
            else:
                error(f"Package manager MISSING: {pm}")
                errors.append(f"Missing package manager: {pm}")
    else:
        error("agent/agent.py not found!")
        errors.append("agent/agent.py not found")
    
    print()
    
    # 8. Check Frontend Dependencies
    log("Checking frontend dependencies...")
    package_json = PROJECT_ROOT / "frontend/package.json"
    if package_json.exists():
        success("frontend/package.json found")
        # Could parse and check React, lucide-react, etc.
    else:
        warn("frontend/package.json not found")
        warnings.append("frontend/package.json not found")
    
    print()
    
    # 9. Summary
    print("=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    print()
    
    if not errors and not warnings:
        success("ALL CHECKS PASSED!")
        print()
        print("All dependencies are present and all syntax is correct.")
        print("The build process should work across all platforms.")
        return 0
    
    if warnings:
        print(f"{Colors.YELLOW}WARNINGS ({len(warnings)}):{Colors.NC}")
        for w in warnings:
            print(f"  ! {w}")
        print()
    
    if errors:
        print(f"{Colors.RED}ERRORS ({len(errors)}):{Colors.NC}")
        for e in errors:
            print(f"  - {e}")
        print()
        print(f"{Colors.RED}BUILD PROCESS MAY FAIL!{Colors.NC}")
        print("Please fix the errors above before building.")
        return 1
    
    if warnings and not errors:
        print(f"{Colors.YELLOW}BUILD PROCESS SHOULD WORK WITH WARNINGS{Colors.NC}")
        return 0

if __name__ == "__main__":
    sys.exit(main())
