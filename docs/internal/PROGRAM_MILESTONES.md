# Patch-SecOps Solution Program Milestones

## Milestone Status

### M1 — Global Tracing + Error Envelope
Status: Completed

Scope delivered:
- Request tracing middleware across API surface (`X-Request-ID`, `X-Trace-Token`)
- Standardized error envelope for:
  - HTTP exceptions
  - Validation errors
  - Unhandled server exceptions
- Correlation-friendly payload fields:
  - `request_id`
  - `trace_token`
  - structured `error` object

Primary implementation:
- `backend/main.py`

Acceptance outcome:
- API responses include trace headers.
- Error responses are diagnosable and consistent across endpoints.

---

### M2 — Unified Operations Queue Backend
Status: Completed

Scope delivered:
- Central queue module for long-running tasks:
  - enqueue
  - worker execution
  - status tracking
  - cancel pending jobs
- Queue API:
  - `GET /api/ops-queue/jobs`
  - `GET /api/ops-queue/jobs/{job_id}`
  - `POST /api/ops-queue/jobs/{job_id}/cancel`
- Startup worker initialization in backend app lifecycle.

Integrated backend domains:
- Mirror sync / retention / bootstrap
- Backups run
- Bulk patch run
- Testing run
- Report generation

Primary implementation:
- `backend/api/ops_queue.py`
- integration in `backend/main.py`
- integration updates in:
  - `backend/api/mirror_repos.py`
  - `backend/api/backups.py`
  - `backend/api/bulk_patch.py`
  - `backend/api/testing.py`
  - `backend/api/reports.py`

Acceptance outcome:
- Heavy operations now share one backend control plane and consistent job model.

---

### M3 — Unified Operations Queue UI + Cross-Module Auto-Jump
Status: Completed

Scope delivered:
- New Operations Queue frontend dashboard:
  - queue list
  - status filter
  - job detail
  - cancel pending
  - copy diagnostics JSON
- Navigation entry and route integration.
- Cross-module auto-jump to queue detail after operation submit:
  - backups
  - bulk patch
  - testing
  - mirror sync/retention
  - report generation

Primary implementation:
- `frontend/src/OpsQueuePage.jsx`
- `frontend/src/App.js`
- module connectors:
  - `frontend/src/BackupManagerPage.jsx`
  - `frontend/src/BulkPatchPage.jsx`
  - `frontend/src/TestingPage.js`
  - `frontend/src/MirrorRepoOpsPage.jsx`
  - `frontend/src/ReportsOpsPage.jsx`

Acceptance outcome:
- Operators can submit and immediately monitor operations from one queue workspace.

---

## Current Baseline Verification

- Backend tests: pass
- Frontend production build: pass

## Enterprise Hardening Pass

Status: Completed

Delivered:
- API permission tightening on queue/plugin/ring-rollout/restore-drill read paths (auditable roles only)
- Consolidated schema migration script for enterprise rollout feature tables
- Production hardening runbook with migration, security verification, smoke tests, and rollback plan

Primary implementation:
- `backend/api/ops_queue.py`
- `backend/api/plugins.py`
- `backend/api/ring_rollout.py`
- `backend/api/restore_drills.py`
- `backend/migrations/20260329_enterprise_rollout_foundation.sql`
- `docs/internal/PRODUCTION_HARDENING_RUNBOOK.md`

---

## Next Program Milestones (Proposed)

### M4 — Plugin SDK v1 (Webhook + Ticket + CMDB)
Status: Phase-2 completed

Scope delivered:
- Plugin registry model and management API
- Signed webhook dispatch (`X-PM-Timestamp`, `X-PM-Signature`)
- Retry + backoff with delivery logs
- Queue-integrated async dispatch using Operations Queue control plane
- Connector endpoint scaffolding:
  - webhook
  - jira
  - servicenow
  - cmdb
- Dedicated Plugin Integrations UI:
  - create integrations
  - dispatch events
  - trigger test deliveries
  - view delivery logs
  - replay failed/specific deliveries
  - auto-link to Operations Queue jobs

Primary implementation:
- `backend/models/db_models.py` (plugin registry + delivery log models)
- `backend/api/plugins.py` (registry API + dispatcher + replay/test endpoints)
- `backend/main.py` (router registration)
- `frontend/src/PluginIntegrationsPage.jsx` (phase-2 UI workspace)
- `frontend/src/App.js` (navigation + route integration)

### M5 — Ring Rollout Policy Engine (Patch + Config)
Status: Phase-3 completed

Scope delivered:
- Ring rollout data model:
  - rollout policies
  - rollout runs
  - status lifecycle and queue linkage
- Rollout API:
  - policy CRUD
  - launch rollout
  - run history/status retrieval
- Queue-integrated execution for staged ring progression
- Guardrail enforcement before each ring:
  - maintenance window gate
  - health gate checks
  - rollback threshold gate
- Approval checkpoints:
  - run approval endpoint
  - run rejection endpoint
  - resume-on-approval queue handoff
- Explicit gate decision log on ring run summaries
- Policy audit trail API and UI view
- First UI controls:
  - create policy
  - configure rings/guardrails JSON
  - launch rollout action
  - monitor rollout runs
  - auto-link launched rollout job to Operations Queue
  - approve/reject pending checkpoints
  - gate decision log view per run
  - policy audit trail table

Primary implementation:
- `backend/models/db_models.py` (ring rollout policy/run models)
- `backend/api/ring_rollout.py` (phase-1 API + queue execution)
- `backend/main.py` (router registration)
- `frontend/src/RingRolloutPage.jsx` (phase-1 controls)
- `frontend/src/RingRolloutPage.jsx` (phase-3 controls: approvals + gate log + audit trail)
- `frontend/src/App.js` (navigation + route integration)

Remaining scope for next M5 phases:
- Progressive runtime success validation (agent feedback gate before next ring)

### M6 — Restore Drill + SLA Linkage
Status: Completed

Scope delivered:
- Restore-drill job model with queue integration
- Restore-drill launch API and run history APIs
- RTO/RPO measurement capture per drill run
- SLA pass/breach evaluation against target RTO/RPO
- Restore-drill insights endpoint for reporting aggregation
- First reporting UI for drill metrics and SLA trend visibility
- Operations Queue auto-link from drill launch actions

Primary implementation:
- `backend/models/db_models.py` (`RestoreDrillRun`)
- `backend/api/restore_drills.py` (queue flow + insights API)
- `backend/main.py` (router registration)
- `frontend/src/RestoreDrillPage.jsx` (drill + reporting view)
- `frontend/src/App.js` (navigation + route integration)
