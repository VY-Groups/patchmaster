#!/usr/bin/env python3
"""
Patch-SecOps Solution Backup CLI
A user-friendly command line tool for managing Patch-SecOps Solution backups.
"""
import argparse
import requests
import json
import sys
import os
import time
from datetime import datetime

# Default config
API_URL = os.getenv("PM_API_URL", "http://localhost:8000")
API_TOKEN = os.getenv("PM_API_TOKEN", "") # In real use, this would be managed via auth login

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def log_success(msg):
    print(f"{GREEN}[SUCCESS]{RESET} {msg}")

def log_error(msg):
    print(f"{RED}[ERROR]{RESET} {msg}")

def log_info(msg):
    print(f"{YELLOW}[INFO]{RESET} {msg}")

def get_token():
    if API_TOKEN: return API_TOKEN
    # Simple check for token file
    token_file = os.path.expanduser("~/.patchmaster/token")
    if os.path.exists(token_file):
        with open(token_file, "r") as f:
            return f.read().strip()
    return None

def login(username, password):
    url = f"{API_URL}/api/auth/login"
    try:
        resp = requests.post(url, data={"username": username, "password": password})
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            token_dir = os.path.expanduser("~/.patchmaster")
            os.makedirs(token_dir, exist_ok=True)
            with open(os.path.join(token_dir, "token"), "w") as f:
                f.write(token)
            log_success("Login successful. Token saved.")
            return token
        else:
            log_error(f"Login failed: {resp.text}")
    except Exception as e:
        log_error(f"Connection error: {e}")
    return None

def list_configs(token):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(f"{API_URL}/api/backups/configs", headers=headers)
        if resp.status_code == 200:
            configs = resp.json()
            if not configs:
                print("No backup configurations found.")
                return
            
            print(f"{'ID':<5} {'Name':<20} {'Type':<10} {'Host ID':<10} {'Active':<10}")
            print("-" * 60)
            for c in configs:
                print(f"{c['id']:<5} {c['name']:<20} {c['backup_type']:<10} {c['host_id']:<10} {str(c['is_active']):<10}")
        else:
            log_error(f"Failed to list configs: {resp.text}")
    except Exception as e:
        log_error(f"Error: {e}")

def create_config(token, name, host_id, b_type, source, db_type=None, retention=5, encryption_key=None):
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "host_id": host_id,
        "name": name,
        "backup_type": b_type,
        "source_path": source,
        "db_type": db_type,
        "retention_count": retention,
        "encryption_key": encryption_key
    }
    try:
        resp = requests.post(f"{API_URL}/api/backups/configs", json=data, headers=headers)
        if resp.status_code == 200:
            log_success(f"Backup config '{name}' created successfully (ID: {resp.json()['id']})")
        else:
            log_error(f"Failed to create config: {resp.text}")
    except Exception as e:
        log_error(f"Error: {e}")

def run_backup(token, config_id):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(f"{API_URL}/api/backups/{config_id}/run", headers=headers)
        if resp.status_code == 200:
            log_success(f"Backup triggered successfully. Log ID: {resp.json()['log_id']}")
        else:
            log_error(f"Failed to trigger backup: {resp.text}")
    except Exception as e:
        log_error(f"Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Patch-SecOps Solution Backup CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Login
    login_parser = subparsers.add_parser("login", help="Authenticate with Patch-SecOps Solution")
    login_parser.add_argument("--username", required=True)
    login_parser.add_argument("--password", required=True)

    # List
    subparsers.add_parser("list", help="List backup configurations")

    # Create
    create_parser = subparsers.add_parser("create", help="Create a new backup configuration")
    create_parser.add_argument("--name", required=True, help="Backup job name")
    create_parser.add_argument("--host-id", required=True, type=int, help="Target Host ID")
    create_parser.add_argument("--type", required=True, choices=["file", "database", "vm", "live", "full_system"], help="Backup type")
    create_parser.add_argument("--source", required=True, help="Source path or connection string")
    create_parser.add_argument("--db-type", choices=["postgres", "mysql", "mongodb", "redis", "sqlite"], help="Database type (if type=database)")
    create_parser.add_argument("--retention", type=int, default=5, help="Number of backups to keep (default: 5)")
    create_parser.add_argument("--encrypt", nargs='?', const='__PROMPT__', help="Encryption key for backups. If flag is present but no key provided, you will be prompted.")

    # Run
    run_parser = subparsers.add_parser("run", help="Trigger a backup manually")
    run_parser.add_argument("--id", required=True, type=int, help="Backup Config ID")

    args = parser.parse_args()

    if args.command == "login":
        login(args.username, args.password)
        return

    token = get_token()
    if not token:
        log_error("Not authenticated. Please run 'login' first.")
        sys.exit(1)

    if args.command == "list":
        list_configs(token)
    elif args.command == "create":
        enc_key = args.encrypt
        if enc_key == "__PROMPT__":
            import getpass
            enc_key = getpass.getpass("Enter encryption password: ")
            confirm = getpass.getpass("Confirm encryption password: ")
            if enc_key != confirm:
                log_error("Passwords do not match!")
                sys.exit(1)
        
        create_config(token, args.name, args.host_id, args.type, args.source, args.db_type, args.retention, enc_key)
    elif args.command == "run":
        run_backup(token, args.id)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
