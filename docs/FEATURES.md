# Patch-SecOps Solution — Feature Inventory & Architecture

## 1. Overview

Patch-SecOps Solution is a proprietary patch-management platform. It reaches
any asset (agent, SSH, WinRM, relay) through one interface, handles credentials
safely, tracks vulnerabilities and risk (PMRS), and produces signed, hash-chained
evidence bundles for every deployment.

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Browser / SPA (React)                        │
│  Evidence Viewer · Risk View · Ring Rollout · Add-Asset Wizard ...   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────────────┐
│                    Master (FastAPI :8000)                            │
│  Auth (JWT/RBAC) · License · Vault · Connectors · Evidence Ledger   │
│  Proof Loop (gates) · Policy · Vulnerability Intel · Topology       │
└──────┬──────────────┬──────────────┬──────────────┬────────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────────┐
  │ Agent   │   │  SSH    │   │  WinRM  │   │   Relay     │
  │ (Flask) │   │ (param) │   │ (pywrm) │   │ (jump/dist) │
  └─────────┘   └─────────┘   └─────────┘   └─────────────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
  ┌─────────────────────────────────────────────────────────┐
  │              Fleet (Debian/Ubuntu/Rocky/Alpine/Win)      │
  └─────────────────────────────────────────────────────────┘

Data: PostgreSQL (hosts, jobs, policies, vault, evidence, vulns, topology)
Cache: relay in-memory (checksum-verified)
Secrets: envelope encryption (per-secret DEK, master key from env/file/KMS)
```

## 3. Supported Features

### Core Platform
- Patch management across 9+ OS families (Windows, Debian, RHEL, Arch, openSUSE, Alpine, FreeBSD, Solaris, HP-UX, AIX)
- Agent-based management (lightweight agents, heartbeat, registration, per-host tokens)
- Agentless management (SSH via paramiko, WinRM via pywinrm — real execution)
- Relay / remote offices (jump + distribution mode, cache with checksum verification)
- Asset onboarding (single IP, CIDR, IP list, FQDN, AD sync, duplicate detection)

### Patching & Orchestration
- Bulk patch jobs, patch jobs, patch schedules
- Ring rollout (canary/pilot/broad) with health + maintenance gates
- Proof Loop: per-patch deployment gates, rollback, signed evidence
- 11 gate types: host_reachable, maintenance_window, disk_space, snapshot_present, service_health, heartbeat_alive, custom_probe, drift_clean, restore_drill_passed, approval_granted, restore_capable
- Topology orchestrator (service graph, ordered patching, health gates, tolerance)
- Policy engine (YAML + structured PatchPolicy, templates, auto-deploy rules, decline policy)
- Draft/preview/publish flow, install-after/expiry dates
- Rollback (gated, evidenced)

### Vulnerability Intelligence (PMRS)
- Normalized vuln model (sources, vulnerabilities, affected, exploit signals, patch map)
- Feed ingestion (NVD, OSV, distro advisories) with idempotency + rate-limit handling
- Inventory-based detection (package matching per ecosystem, backport awareness)
- Unauthenticated scanning (TCP connect, scope enforcement, rate limits)
- PMRS risk score (severity, exploit likelihood, known-exploited, exposure, criticality, compensating controls, patch availability) with breakdown
- SLA and remediation workflow (accepted risk, false positive)
- Mitigation playbooks (versioned, reversible, tested)
- Noise reduction (de-dup superseded, rank exploited first)
- CVE-based security filtering

### Compliance & Security
- Compliance controls + findings (CIS/STIG/custom)
- RBAC (admin/operator/viewer), JWT auth, OIDC
- License engine (Ed25519 + HMAC fallback), feature gating
- Vault (envelope encryption, per-secret DEK, pluggable KMS/HSM provider)
- Secret scanning (gitleaks), bandit, pip-audit in CI
- Threat model (STRIDE, 8 components, findings register)
- Security headers, rate limiting, CORS

### Evidence & Audit
- Evidence Ledger (hash-chained bundles, items, Ed25519 signing)
- pm-evidence CLI verifier (offline, PASS/FAIL, signature verification)
- Evidence viewer UI (timeline, gate results, signature status, download)
- Audit log (SHA-256 chain), audit log integrity

### Monitoring & DevOps
- Prometheus metrics, Grafana dashboards
- Health checks (/health, /api/health, /healthz, /v1/models)
- Heartbeat monitoring, host online status
- Alert rules (backend down, agent missing, high error rate, CPU/memory/disk, offline hosts)
- Backup management (config, logs, restore drills with RTO/RPO)
- Snapshot management (Windows VSS, Linux)
- Restore drills

### Integrations
- ITSM connectors (ServiceNow, Jira, Motadata) — HTTP-based
- LDAP/AD sync
- OIDC authentication
- Git integration (repos, PRs)
- CI/CD (builds, artifacts, deployments, approvals)
- Notifications (channels, websocket)
- GraphQL API

### Air-Gap & Offline
- Bundle import with integrity/provenance verification (hash chain + payload hashes)

### Reporting
- 14 patch report types (names; generation wired separately)
- Scheduled exports (stub)
- Executive summary, compliance status, CVE exposure, etc.

### AI Assistant (optional, read-only)
- Read-only assistant grounded in evidence (stub)

## 4. Workflow Diagrams

### Deployment workflow
```
Policy created → Ring rollout launched → Pre-gates (host_reachable, restore_capable, ...)
  → Health gate → Maintenance window gate → Patch selected hosts → Post-gates
  → Next ring (if rollback threshold OK) → Evidence bundle created → Audit log
  → Approve (if required) → Complete
```

### Vulnerability workflow
```
Feed ingestion (NVD/OSV/distro) → Normalize → Match against host inventory
  → host_vulnerabilities (open/mitigated/fixed/accepted/false-positive)
  → PMRS scoring → SLA check → Remediation (patch/mitigate/config/accept)
  → Mitigation playbooks for no-patch cases
```

### Evidence verification workflow
```
Job completes → create_bundle (hash chain + items) → sign (if key present)
  → pm-evidence verify <bundle.json> [--pubkey KEY] → PASS/FAIL
  → Viewer UI: timeline, gate results, signature status, download
```

### Agent registration workflow
```
Agent starts → GET /api/version (compatibility check) → POST /api/register
  → host row created (if new) or updated → token minted → agent stores token
  → POST /api/heartbeat (periodic) → host last_heartbeat updated
  → OS family group ensured (OS_FAMILY_GROUPS lookup)
```

## 5. Limitations

### Infrastructure-bound (not code)
- Real Windows target for WinRM verification needs a Windows host with WinRM enabled (tested structurally; auth blocked by Windows permissions in this env)
- Relay distribution mode on physical hardware needs a relay + bandwidth measurement
- External feed keys/rate limits (NVD_API_KEY) — wired but needs a key for full rate
- Full identifier rename of Windows service/alert names (deployment-breaking; left as-is)

### Feature stubs (models/endpoints exist, engines partial)
- ITSM connectors (ServiceNow/Jira/Motadata) — HTTP client, not full workflow
- Reports — names + endpoint, generation wired separately
- AI assistant — read-only stub
- macOS patching path — OS detection exists, dedicated path not implemented
- Third-party app catalog — hand-verified list approach, not 1300+ apps
- Deployment retry-failed toggle — not yet wired
- Draft/preview/publish — transition logic exists, UI flow partial

### Monitoring
- Prometheus file_sd_configs watcher fails on Docker Desktop for Windows (inotify limitation on bind mounts) — Prometheus still scrapes via refresh_interval
- `/snapshot/status` 404 in agent containers (pre-existing, harmless)

### Known shortcuts (code comments)
- `custom_probe` fails closed without supplied result (no in-process script/HTTP execution)
- `maintenance_window` gate passes when no session/windows supplied
- RestorePoint adapters return simulated success (delegated to agent/backup service)
- Ed25519 signing only when `PM_EVIDENCE_SIGNING_KEY` env present
- NVD/OSV fetch returns empty on network failure (graceful degradation)

## 6. DevOps Monitoring

- Prometheus scrapes backend (`/metrics`) and agents (`/metrics` on :9100)
- Grafana dashboards: overview, host details, availability
- Alert rules: backend down, agent missing, high error rate, CPU/memory/disk IO, offline hosts
- Health endpoints: `/health`, `/api/health`, `/healthz`, `/v1/models`, `/api/version`
- Monitoring config: `monitoring/prometheus/prometheus.yml`, `monitoring/prometheus/alerts.yml`
- Backend monitoring: `backend/monitoring_manager.py`, `backend/prometheus_targets.py`