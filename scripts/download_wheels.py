#!/usr/bin/env python3
"""
Download Missing Wheels Script
Downloads any missing Python wheels needed for offline builds
"""
import os
import sys
import subprocess
from pathlib import Path

def log(msg):
    print(f"[WheelDownloader] {msg}")

def get_project_root():
    """Get the project root directory"""
    script_dir = Path(__file__).parent
    return script_dir.parent

def download_wheels(requirements_file, output_dir):
    """Download wheels for a requirements file"""
    if not os.path.exists(requirements_file):
        log(f"Requirements file not found: {requirements_file}")
        return False
    
    log(f"Downloading wheels from: {requirements_file}")
    log(f"Output directory: {output_dir}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    cmd = [
        sys.executable, "-m", "pip", "download",
        "-r", requirements_file,
        "-d", output_dir,
        "--no-deps"  # Download only the packages listed, not their dependencies
    ]
    
    try:
        subprocess.run(cmd, check=True)
        log(f"✅ Successfully downloaded wheels to {output_dir}")
        return True
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to download wheels: {e}")
        return False

def download_all_wheels():
    """Download all required wheels for the project"""
    project_root = get_project_root()
    wheels_dir = project_root / "vendor" / "wheels"
    
    log("=" * 70)
    log("DOWNLOADING MISSING WHEELS")
    log("=" * 70)
    log("")
    
    # Check if wheels directory exists
    if not wheels_dir.exists():
        log(f"Creating wheels directory: {wheels_dir}")
        wheels_dir.mkdir(parents=True, exist_ok=True)
    
    # Count existing wheels
    existing_wheels = list(wheels_dir.glob("*.whl"))
    log(f"Found {len(existing_wheels)} existing wheels in {wheels_dir}")
    log("")
    
    # Download wheels for each requirements file
    requirements_files = [
        ("Agent", project_root / "agent" / "requirements.txt"),
        ("Backend", project_root / "backend" / "requirements.txt"),
    ]
    
    success_count = 0
    total_count = len(requirements_files)
    
    for name, req_file in requirements_files:
        log(f"Processing {name} requirements...")
        if download_wheels(str(req_file), str(wheels_dir)):
            success_count += 1
        log("")
    
    # Count final wheels
    final_wheels = list(wheels_dir.glob("*.whl"))
    new_wheels = len(final_wheels) - len(existing_wheels)
    
    log("=" * 70)
    log("DOWNLOAD SUMMARY")
    log("=" * 70)
    log(f"Requirements processed: {success_count}/{total_count}")
    log(f"Total wheels now: {len(final_wheels)}")
    log(f"New wheels downloaded: {new_wheels}")
    log("")
    
    if success_count == total_count:
        log("✅ All wheels downloaded successfully!")
        return 0
    else:
        log("⚠️  Some downloads failed. Check the output above.")
        return 1

def main():
    """Main entry point"""
    log("Python Wheel Downloader for Patch-SecOps Solution")
    log("")
    
    # Check if pip is available
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], 
                      capture_output=True, check=True)
    except subprocess.CalledProcessError:
        log("ERROR: pip is not available")
        log("Please install pip: python -m ensurepip --upgrade")
        return 1
    
    return download_all_wheels()

if __name__ == "__main__":
    sys.exit(main())
