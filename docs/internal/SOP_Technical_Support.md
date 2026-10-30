# Standard Operating Procedure: Technical Support (Deep Dive)

**Audience:** Support Engineers (L1/L2/L3)
**Purpose:** Advanced troubleshooting, database diagnostics, and system recovery.
**Version:** 2.1.0

---

## 📚 Table of Contents
1. [System Architecture & Data Flow](#1-system-architecture--data-flow)
2. [Triage Decision Tree](#2-triage-decision-tree)
3. [Deep Dive: Database Diagnostics](#3-deep-dive-database-diagnostics)
4. [Deep Dive: Log Analysis](#4-deep-dive-log-analysis)
5. [Common Scenarios & Resolution Paths](#5-common-scenarios--resolution-paths)
6. [Escalation Protocol](#6-escalation-protocol)

---

## 1. System Architecture & Data Flow

Understanding the flow is critical for pinpointing failures.

**Flow**: `[User Browser]` -> `[Nginx (Reverse Proxy)]` -> `[FastAPI Backend]` <-> `[PostgreSQL]`
                                                                    ^
                                                                    |
                                                              `[Agent (Python)]`

- **Ports**:
  - Frontend: 3000 (HTTP) / 443 (HTTPS)
  - Backend: 8000
  - Agent API: 5000 (Local only)
  - PostgreSQL: 5432

---

## 2. Triage Decision Tree

### **Q1: Is the issue affecting ALL users/hosts?**
- **YES**: It's a Master Node issue (Backend/DB/Nginx). -> **Go to Section 4 (Logs)**.
- **NO**: It's a specific Agent or Network issue. -> **Go to Q2**.

### **Q2: Is the Agent reporting "Offline"?**
- **YES**: Check Agent Connectivity.
  - SSH to Agent.
  - Run `curl -v http://<MASTER_IP>:8000/api/health`.
  - If timeout: Firewall/Network issue.
  - If 401 Unauthorized: Token/Time drift issue.
- **NO**: Agent is online but failing tasks. -> **Go to Q3**.

### **Q3: Are Patch Jobs failing?**
- **YES**: Check Job Logs.
  - "Lock file error": Another apt/dnf process is running.
  - "Dependency error": Manual intervention required on host.
  - "Disk full": Check `/var`.

---

## 3. Deep Dive: Database Diagnostics

**Accessing DB**:
```bash
# Docker
docker exec -it patchmaster-db-1 psql -U patchmaster patchmaster

# Bare Metal
su - postgres -c "psql patchmaster"
```

### **Common Queries**

**1. Check Stuck Jobs**
```sql
SELECT id, status, created_at, host_id FROM jobs 
WHERE status = 'running' AND created_at < NOW() - INTERVAL '1 hour';
```
*Fix*: `UPDATE jobs SET status = 'failed' WHERE id = ...;`

**2. Find Duplicate Hosts**
```sql
SELECT hostname, ip, COUNT(*) FROM hosts GROUP BY hostname, ip HAVING COUNT(*) > 1;
```

**3. Reset Admin Password**
```sql
-- Hash for "patchmaster": $2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW
UPDATE users SET password_hash = '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW' WHERE username = 'admin';
```

---

## 4. Deep Dive: Log Analysis

**Locations**:
- Backend: `/opt/patchmaster/logs/backend.log` (or `docker logs patchmaster-backend-1`)
- Nginx: `/var/log/nginx/error.log`
- Agent: `/var/log/patch-agent/agent.log`

### **Error Patterns**

**Pattern**: `502 Bad Gateway` (Nginx)
- **Meaning**: Backend service is down.
- **Check**: `systemctl status patchmaster-backend`.
- **Root Cause**: Often a syntax error in config or DB connection failure.

**Pattern**: `401 Unauthorized` (Agent Log)
- **Meaning**: The JWT token used by the Agent is invalid.
- **Root Cause**:
  1. System clock skew (>5 mins difference between Master and Agent).
  2. Agent was deleted from Master but service is still running.
- **Fix**: Re-register agent (`rm /var/lib/patch-agent/token && systemctl restart patch-agent`).

**Pattern**: `Lock file is held by process ...` (Agent Log)
- **Meaning**: `apt` or `dnf` is running in background (unattended-upgrades?).
- **Fix**: Kill the process or wait. Disable auto-updates on the host if Patch-SecOps Solution is managing it.

---

## 5. Common Scenarios & Resolution Paths

### **Scenario A: "License Invalid / Expired"**
1. **Symptom**: Dashboard shows banner, features locked.
2. **Diagnosis**: Check "License" page.
   - If "Signature Invalid": The `LICENSE_SIGN_KEY` in `.env` doesn't match the key used to generate the license.
   - If "Expired": Date passed.
3. **Resolution**:
   - Verify server time (`date`).
   - Request new key from Vendor.
   - Update `license.key` file and restart backend.

### **Scenario B: Database Corruption (PostgreSQL)**
1. **Symptom**: 500 Errors, "relation does not exist".
2. **Diagnosis**: Check postgres logs (`/var/log/postgresql/`).
3. **Resolution**:
   - Stop backend.
   - Restore from backup:
     ```bash
     gunzip -c /var/backups/patchmaster-YYYY.../db_backup.sql.gz | psql patchmaster
     ```
   - Run migrations (if applicable).

### **Scenario C: Agent "Flapping" (Online/Offline)**
1. **Symptom**: Host status toggles every minute.
2. **Diagnosis**:
   - Duplicate IP/Hostname? (Cloned VMs with same Agent Token).
3. **Resolution**:
   - Reset Agent Token on the clone:
     ```bash
     rm /etc/patch-agent/token
     systemctl restart patch-agent
     ```

---

## 6. Escalation Protocol

If L1/L2 cannot resolve:

1. **Gather Evidence**:
   - Tarball of `/opt/patchmaster/logs/`.
   - Output of `docker ps` or `systemctl status`.
   - Browser Console Logs (Network tab).
2. **Create Ticket**:
   - **Severity**: Critical (System Down) vs Major (Feature Broken).
   - **Environment**: OS Version, Patch-SecOps Solution Version.
3. **Assign to Engineering (L3)**.
