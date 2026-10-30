# Standard Operating Procedure: End User (Deep Dive)

**Audience:** System Administrators, DevOps Engineers, and IT Operators.
**Purpose:** Comprehensive guide to operating Patch-SecOps Solution without external training. Covers daily workflows, edge cases, and disaster recovery.
**Version:** 2.1.0

---

## 📚 Table of Contents
1. [Dashboard Overview](#1-dashboard-overview)
2. [Patch Management (The Core Workflow)](#2-patch-management-the-core-workflow)
3. [Software Manager & Bulk Operations](#3-software-manager--bulk-operations)
4. [Air-Gapped / Offline Patching](#4-air-gapped--offline-patching)
5. [Snapshots & Disaster Recovery](#5-snapshots--disaster-recovery)
6. [CVE Tracking & Compliance](#6-cve-tracking--compliance)
7. [Agent Management](#7-agent-management)

---

## 1. Dashboard Overview

### **Login & First Steps**
- **URL:** `http://<your-server-ip>:3000`
- **Default Credentials:** `admin` / `patchmaster` (Force change on first login).
- **Key Indicators:**
  - **Compliance Score**: % of servers with 0 critical updates pending.
  - **Reboot Required**: Servers waiting for a restart to apply kernel patches.
  - **Online/Offline**: Real-time agent status (Heartbeat every 60s).

### **Navigation Bar**
- **Hosts**: The inventory of all managed servers.
- **Groups**: Logical grouping (e.g., "Prod-Web", "Dev-DB") for bulk actions.
- **Patches**: The central hub for applying updates.
- **Jobs**: A history of every action taken by the system.

---

## 2. Patch Management (The Core Workflow)

### **Step 1: Identifying Targets**
1. Navigate to **Hosts**.
2. Use the **Filter** bar:
   - Type `windows` to see only Windows servers.
   - Type `critical` (if tagged) or sort by "Upgradable" count.
3. Check the **Compliance** column. Green (90%+) is good; Red (<70%) needs immediate attention.

### **Step 2: Reviewing Updates**
1. Click on a specific **Host IP** or select multiple and go to **Patch Manager**.
2. Click **"Check Updates"**.
   - *Behind the scenes*: This runs `apt update` or `dnf check-update` on the agent without installing anything.
3. Review the list:
   - **Security**: Updates tagged with CVEs.
   - **Feature**: Standard version bumps.
   - **Kernel**: Updates that will require a reboot.

### **Step 3: Execution Strategy**
You have three execution modes:

#### **A. Standard Patching (Online Servers)**
1. Select packages (or "Select All").
2. **Hold Packages**: Enter names of packages to *exclude* (e.g., `docker-ce`, `nginx`).
   - *Why?* Sometimes you want to pin a specific version for compatibility.
3. **Options**:
   - `[x] Auto-Snapshot`: **ALWAYS ENABLE** for production. Takes a filesystem state before touching apt/dnf.
   - `[x] Auto-Rollback`: Reverts if the exit code is non-zero.
   - `[ ] Dry Run`: Simulates the install to check for dependency errors.
4. Click **"Download & Patch"**.

#### **B. Dry Run (Simulation)**
Use this when you are unsure if an update will break dependencies.
1. Check `[x] Dry Run`.
2. Click **"Simulate"**.
3. View the logs. It will show exactly which files *would* be changed.

#### **C. Scheduled Patching**
*(Requires Standard/Enterprise License)*
1. Go to **Schedules**.
2. Create a "Maintenance Window" (e.g., Sunday 2 AM).
3. Assign a **Group** ("Prod-DB").
4. The system will auto-execute patches during this window.

### **Step 4: Post-Patch Verification**
1. Watch the **Job Logs** window.
   - `Downloading...` -> `Installing...` -> `Configuring...`
2. Look for **"Success"** status.
3. If **"Reboot Required"** appears:
   - Go to **Hosts**.
   - Click **"Reboot"** (Admin only) or schedule a maintenance window.

---

## 3. Software Manager & Bulk Operations

**Purpose**: Install tools across the entire fleet in one click.

### **Scenario: Installing a Monitoring Agent (e.g., htop)**
1. Go to **Software Manager**.
2. **Select Hosts**: Click "Select All" or manually pick servers.
3. **Action**: `Install`.
4. **Package Names**: `htop, curl, vim`.
5. Click **"Execute"**.
   - *Windows Agents*: Will try `winget install htop`.
   - *Linux Agents*: Will try `apt/dnf install htop`.

### **Scenario: Removing Unauthorized Software**
1. **Action**: `Remove`.
2. **Package Names**: `bittorrent-client`.
3. Click **"Execute"**.

---

## 4. Air-Gapped / Offline Patching

**Scenario**: You have a "Secure Zone" server with NO internet access.

### **Workflow:**
1. **The Master Node** (which *does* have internet) acts as the gateway.
2. Go to **Offline Patching**.
3. **Select Host**: Choose the air-gapped server.
4. **Fetch Updates**: The Master Node asks the Agent "What do you need?".
5. **Download (Master)**: The Master Node downloads the `.deb/.rpm` files from the public internet to its local storage (`/var/lib/patchmaster/offline`).
6. **Push (Master -> Agent)**: The Master Node sends the files over the internal LAN to the Agent.
7. **Install (Agent)**: The Agent installs from its local folder (`/var/lib/patch-agent/offline-pkgs`).

**Critical Note**: Ensure the Master Node has firewall rules allowing it to talk to the Air-Gapped Agent on port 5000 (Agent API).

---

## 5. Snapshots & Disaster Recovery

### **Creating a Snapshot**
*When to use*: Before a risky configuration change or major upgrade.
1. Go to **Snapshots**.
2. Select Host.
3. Enter Name: `Pre-Upgrade-v2`.
4. Click **"Create"**.
   - *Linux*: Uses `timeshift` (if BTRFS/RSYNC enabled) or standard package list backups.
   - *Windows*: Creates a System Restore Point.

### **Restoring (Rollback)**
*When to use*: If the server fails to boot services after a patch.
1. Select the Snapshot `Pre-Upgrade-v2`.
2. Click **"Rollback"**.
3. **Wait**: The server may reboot automatically.
4. **Verify**: Check "Health" status after 5 minutes.

### **Archiving (Long-Term Storage)**
1. Click **"Archive"**.
2. The system zips the snapshot data.
3. Download the ZIP file to your local machine or S3 bucket for compliance retention.

---

## 6. CVE Tracking & Compliance

### **Understanding the Report**
1. Go to **CVE Tracker**.
2. **Critical (Red)**: Remote Code Execution (RCE) risks. Patch immediately.
3. **High (Orange)**: Privilege Escalation risks. Patch within 7 days.
4. **Medium (Blue)**: DoS or local risks. Patch in next window.

### **Exporting for Auditors**
1. Click **"Export CSV"**.
2. The file contains: `CVE-ID`, `Severity`, `Affected Host IP`, `Status (Patched/Vulnerable)`.
3. Send this file to your Security Officer.

---

## 7. Agent Management

---

## 8. Backup & Recovery (CLI)

Patch-SecOps Solution v2.0 includes a powerful CLI for managing backups.

### **Quick Start**
The tool is installed at `/usr/local/bin/patchmaster-backup`.

1. **Login**:
   ```bash
   patchmaster-backup login --username admin --password <your-password>
   ```

2. **Create a Backup Job**:
   ```bash
   # File Backup
   patchmaster-backup create --name "WebConfig" --host-id 1 --type file --source "/etc/nginx"

   # Database Backup (PostgreSQL)
   patchmaster-backup create --name "ProdDB" --host-id 1 --type database --source "postgresql://user:pass@localhost/db" --db-type postgres
   ```

3. **Trigger Backup**:
   ```bash
   patchmaster-backup run --id <config_id>
   ```

### **Supported Types**
- **file**: Zip archive of a folder.
- **database**: Native dump (Postgres, MySQL, Mongo, Redis).
- **live**: Real-time sync (rsync/robocopy).
- **vm**: Hypervisor snapshot.

### **Installing New Agents**
1. Go to **Onboarding**.
2. Copy the command for your OS.
   - **Linux**: `curl -fsSL ... | sudo bash`
   - **Windows**: `iwr ... | iex`
3. Run on the target server.
4. It should appear in **Hosts** list within 60 seconds.

### **Troubleshooting Offline Agents**
If an agent shows **"Offline"**:
1. Check if the server is powered on.
2. SSH/RDP into the server.
3. Check service:
   - Linux: `systemctl status patch-agent`
   - Windows: `Get-Service patch-agent`
4. Check logs:
   - Linux: `/var/log/patch-agent/agent.log`
   - Windows: `C:\ProgramData\patch-agent\logs\agent.log`
