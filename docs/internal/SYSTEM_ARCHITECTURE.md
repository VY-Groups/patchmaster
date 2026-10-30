# Patch-SecOps Solution System Architecture & Workflows

## 1. High-Level Architecture (HA Deployment)

This diagram illustrates the **Active-Active** deployment model, suitable for production environments requiring fault tolerance and scalability.

```mermaid
graph TD
    subgraph "Clients"
        User[Admin User]
        Agent[Patch Agents]
    end

    subgraph "Load Balancer Layer"
        LB[Nginx Load Balancer]
        LB -->|Round Robin| Backend1
        LB -->|Round Robin| Backend2
    end

    subgraph "Application Layer"
        Backend1[Backend API 1]
        Backend2[Backend API 2]
    end

    subgraph "Data Layer"
        DB_Primary[(PostgreSQL 17 Primary)]
        DB_Replica[(PostgreSQL 17 Replica)]
        Backend1 --> DB_Primary
        Backend2 --> DB_Primary
        DB_Primary -->|Replication| DB_Replica
    end

    subgraph "Monitoring Stack"
        Prometheus[Prometheus v2.55]
        Grafana[Grafana v11.3]
        
        Prometheus -->|Scrape| Backend1
        Prometheus -->|Scrape| Backend2
        Prometheus -->|Scrape| Agent
        Grafana -->|Query| Prometheus
    end

    User -->|HTTPS| LB
    Agent -->|HTTPS/Heartbeat| LB
```

---

## 2. Patch Execution Workflow

The end-to-end process from initiating a patch job to final verification.

```mermaid
sequenceDiagram
    participant Admin as Admin User
    participant API as Backend API
    participant DB as PostgreSQL
    participant Agent as Target Host
    participant Repo as Package Repo

    Admin->>API: POST /api/jobs/create (Hosts, Packages)
    API->>DB: Create Job (Status=Pending)
    API-->>Admin: Job ID Created

    loop Heartbeat Check
        Agent->>API: POST /api/heartbeat
        API-->>Agent: { "command": "execute_patch", "job_id": 123 }
    end

    Agent->>Agent: Create Snapshot (Pre-Patch)
    Agent->>Repo: Download Packages
    Agent->>Agent: Install Packages (apt/dnf/winget)

    alt Success
        Agent->>API: POST /api/jobs/update (Status=Success)
        API->>DB: Update Job Status
    else Failure
        Agent->>Agent: Rollback Snapshot
        Agent->>API: POST /api/jobs/update (Status=Failed)
        API->>DB: Log Failure Details
    end
```

---

## 3. Monitoring & Alerting Pipeline

How metrics flow from the edge to the dashboard.

```mermaid
flowchart LR
    subgraph "Edge (Agents)"
        A1[Agent 1]
        A2[Agent 2]
        A1 -->|Expose :9100/metrics| Scraper
        A2 -->|Expose :9100/metrics| Scraper
    end

    subgraph "Core (Backend)"
        API[Backend API]
        API -->|Expose :8000/metrics| Scraper
    end

    subgraph "Collection & Storage"
        Scraper[Prometheus Server]
        TSDB[(Time Series DB)]
        Scraper --> TSDB
    end

    subgraph "Visualization & Alerting"
        Grafana[Grafana Dashboard]
        AlertMgr[AlertManager]
        
        TSDB --> Grafana
        TSDB -->|Threshold Breach| AlertMgr
        AlertMgr -->|Email/Slack| Admin
    end
```

---
