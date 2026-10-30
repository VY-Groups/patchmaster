# Patch-SecOps Solution v2.0.0 - Major Release Changelog

## 🚀 Key Infrastructure Upgrades
This release transitions the entire platform to the latest stable enterprise-grade components, ensuring maximum performance, security, and observability.

### **1. Database: PostgreSQL 17**
- **Upgrade**: Migrated from PostgreSQL 15 to **PostgreSQL 17-alpine**.
- **Impact**:
  - improved query planning and execution speed.
  - Faster VACUUM operations for large datasets.
  - Better JSON handling for audit logs and package lists.
- **Affected Files**:
  - `docker-compose.prod.yml`
  - `docker-compose.ha.yml`
  - `packaging/install-bare.sh` (Added official PGDG repo)

### **2. Monitoring Stack: The Observability Trinity**
We have implemented a full-stack monitoring solution that covers Application, System, and Infrastructure metrics.

#### **A. Grafana v11.3.1 (Latest Stable)**
- **Upgrade**: From v10.4.1 to **v11.3.1**.
- **New Features**:
  - **Host Details Dashboard**: A new drill-down view showing CPU, RAM, Disk usage, and specific patch history per agent.
  - **Executive Overview**: Real-time compliance scores and unpatched CVE tracking.
- **Configuration**:
  - Pre-provisioned datasources (Prometheus).
  - Dashboards are automatically loaded from `monitoring/grafana/dashboards/`.

#### **B. Prometheus v2.55.1 (Latest Stable)**
- **Upgrade**: From v2.51.0 to **v2.55.1**.
- **Enhancements**:
  - **System Metrics**: Now scrapes CPU, Memory, Disk, and Uptime from all agents via the `/metrics` endpoint.
  - **Optimized Storage**: Better compression for time-series data.
- **Configuration**:
  - Scrapes both Backend (`:8000/metrics`) and Agents (`:9100/metrics`).

### **3. Agent Enhancements**
- **System Vitals**: The Agent now uses `psutil` to capture real-time system metrics (CPU, RAM, Disk).
- **Dependencies**: Added `psutil` and `PyYAML` to `agent/requirements.txt`.
- **Versioning**: Bumped internal version to `2.0.0`.

### **4. High Availability (HA) & Disaster Recovery**
- **Architecture**: Validated Active-Passive and Active-Active configurations.
- **Load Balancer**: Nginx configured for round-robin distribution with health checks.
- **Database Replication**: Support for Primary-Replica setup in `docker-compose.ha.yml`.

---

## 🛠️ Summary of Modified Files

| File Path | Change Description |
|-----------|-------------------|
| `docker-compose.prod.yml` | Updated images for Postgres (17), Grafana (11.3), Prometheus (2.55). |
| `docker-compose.ha.yml` | Updated HA database images to Postgres 17. |
| `packaging/install-bare.sh` | Added Postgres 17 repo, updated Grafana/Prometheus install steps. |
| `agent/agent.py` | Added `psutil` integration for system metrics export. |
| `agent/requirements.txt` | Added `psutil`, `PyYAML`. |
| `backend/api/metrics.py` | Enhanced backend metrics export. |
| `monitoring/grafana/dashboards/` | Added `patchmaster-host-details.json`. |

---

## ✅ Validation Status
- **Build**: `./scripts/build-release.sh` completed successfully.
- **Tests**: Agent metrics export verified. Database migrations verified compatible with PG17.
