# Patch-SecOps Solution Production Hardening Runbook

## Scope

This runbook covers enterprise hardening for:
- API permission tightening
- schema migration rollout
- operational readiness for M4/M5/M6 features

## 1) Pre-Deployment Checklist

- Confirm maintenance window for backend restart.
- Snapshot/backup database before migration.
- Verify license supports required features in target environment.
- Verify outbound network routes for plugin/webhook endpoints.
- Verify agent connectivity for restore drill and patch workflows.

## 2) Apply Schema Migration

Migrations are applied automatically: on startup the backend runs the alembic
chain (`backend/alembic/versions/`), which bootstraps the model schema and then
runs the dated scripts in `backend/migrations/` in date order. Nothing to apply
by hand.

To apply or inspect them manually (same commands the backend runs):

```bash
cd backend
python -m alembic current          # where this database is
python -m alembic upgrade head     # apply everything pending
python -m alembic history          # the chain, including the converted scripts
```

Validation SQL (confirm the enterprise rollout tables exist):

```sql
SELECT tablename
FROM pg_tables
WHERE schemaname='public'
  AND tablename IN (
    'plugin_integrations',
    'plugin_delivery_logs',
    'ring_rollout_policies',
    'ring_rollout_runs',
    'restore_drill_runs'
  );
```

## 3) API Security Verification

Verify hardened role access:
- ops queue read: admin/operator/auditor
- plugin inventory/logs read: admin/operator/auditor
- ring rollout read/audit: admin/operator/auditor
- restore drill read/insights/configs: admin/operator/auditor
- mutation endpoints: admin/operator (or admin where defined)

## 4) Post-Deployment Smoke Tests

- Create plugin integration, run test dispatch, confirm queue job + delivery log.
- Launch ring rollout policy in dry-run, verify gate decisions + audit trail.
- Trigger restore drill, verify:
  - queue job created
  - RTO/RPO recorded
  - within_sla computed
  - insights endpoint updated

## 5) Observability and Alerts

- Alert on failed queue jobs (`failed` status growth).
- Alert on plugin delivery failure rate > threshold.
- Alert on restore drill SLA breach count increase.
- Track ring rollout failure gates:
  - rollback threshold
  - maintenance gate
  - health gate

## 6) Rollback Plan

- If migration fails: restore DB snapshot, redeploy previous backend image.
- If feature regression is isolated:
  - disable affected flows via role restrictions or feature controls
  - keep queue system running for unaffected operations
- Keep incident notes with request_id/trace_token for every failure path.

## 7) Operational Cadence

- Weekly: run restore drill for each critical backup config.
- Weekly: replay failed plugin deliveries after endpoint fixes.
- Per rollout: require approval checkpoints for production ring promotions.
- Monthly: export audit evidence from ring rollout and restore drill histories.
