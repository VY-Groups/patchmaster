# Patch-SecOps Solution High Availability & Disaster Recovery (HA/DR) Guide

This guide details how to deploy Patch-SecOps Solution in an Enterprise **Active-Passive** (DC/DR) or **Active-Active** (HA Cluster) configuration.

---

## 🏗️ Architecture Overview

### 1. Data Center (DC) - Primary Site
**Configuration**: High Availability (HA) Cluster
- **Load Balancer (VIP)**: Nginx/HAProxy (Active/Passive with Keepalived).
- **Application Nodes**: 2+ Backend instances running in Active-Active mode.
- **Database**: PostgreSQL Cluster (Primary + Sync Replica).
- **Storage**: Shared NFS/EFS mount for `/static` (Package Repository).

### 2. Disaster Recovery (DR) - Secondary Site
**Configuration**: Cold Standby (Passive)
- **Application Nodes**: 1+ Backend instance (Stopped or Read-Only).
- **Database**: PostgreSQL Async Replica (Streaming Replication from DC).
- **Storage**: Async replication from DC (Rsync/NetApp SnapMirror).

---

## 🚀 Deployment Steps (DC - Primary Site)

### 1. Database Setup (PostgreSQL HA)
We recommend using **Patroni** or **pg_auto_failover** for automated failover.
For manual HA:
1. **Node 1 (Primary)**:
   ```bash
   # postgresql.conf
   wal_level = replica
   max_wal_senders = 10
   archive_mode = on
   archive_command = 'cp %p /var/lib/postgresql/data/archive/%f'
   ```
2. **Node 2 (Sync Replica)**:
   ```bash
   pg_basebackup -h <PRIMARY_IP> -D /var/lib/postgresql/data -U replicator -P -v -R -X stream
   ```

### 2. Shared Storage (NFS)
The `backend/static` directory MUST be shared across all application nodes to ensure uploaded packages are available everywhere.
```bash
# On NFS Server
/export/patchmaster_static *(rw,sync,no_root_squash)

# On App Nodes
mount -t nfs <NFS_IP>:/export/patchmaster_static /opt/patchmaster/backend/static
```

### 3. Application Cluster (Docker Compose)
Use the provided `docker-compose.ha.yml` to spin up the cluster.

```bash
# .env
DATABASE_URL=postgresql+asyncpg://user:pass@<PG_VIP>:5432/patchmaster
```

```bash
docker-compose -f docker-compose.ha.yml up -d
```

### 4. Load Balancer (Nginx)
Configure Nginx to balance traffic between App Node 1 and App Node 2.
See `packaging/nginx-ha.conf`.

---

## 🛡️ Disaster Recovery (DR) Strategy

### Failover Procedure (DC -> DR)
**Trigger**: Complete outage of DC (Power, Network, Fire).

1. **Promote DR Database**:
   ```bash
   # On DR DB Node
   pg_ctl promote -D /var/lib/postgresql/data
   ```
2. **Update DNS**: Point `patchmaster.corp.local` to DR Load Balancer VIP.
3. **Start Application**:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```
4. **Verify**: Login and check "Job History".

### Failback (DR -> DC)
1. Resync Data: Use `pg_rewind` to sync the old Primary with the new DR Primary.
2. Demote DR to Replica.
3. Switch DNS back to DC.

---

## 🔌 Agent Configuration for HA

Agents should NOT point to a single IP. They must use a **DNS Name** that resolves to the Load Balancer VIP.

**Correct**:
```bash
# /etc/patch-agent/config.yaml
controller_url: "https://patchmaster.corp.local"
```

**Incorrect**:
```bash
controller_url: "http://192.168.1.10:8000"
```

If the Load Balancer fails, **Keepalived** should move the VIP to the standby LB.
If the DNS fails, add multiple entries to `/etc/hosts` on agents (not recommended, but works as fallback).
