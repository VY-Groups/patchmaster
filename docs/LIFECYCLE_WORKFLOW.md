# Patch-SecOps Solution — Lifecycle & Workflow Diagrams

## 1. Overall Platform Lifecycle

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Onboard    │───▶│  Discover   │───▶│  Assess     │───▶│  Remediate  │
│  Assets     │    │  Vulns      │    │  Risk       │    │  (Patch)    │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                               │
       ┌───────────────────────────────────────────────────────┘
       ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Verify     │───▶│  Evidence   │───▶│  Report     │───▶│  Monitor    │
│  (Gates)    │    │  (Signed)   │    │  (Export)   │    │  (Ongoing)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

## 2. Asset Onboarding Workflow

```
Input: single IP / CIDR / IP list / FQDN / AD sync
  │
  ▼
┌──────────────────┐
│ Duplicate check  │── duplicate ──▶ skip
│ (ip, hostname)   │
└────────┬─────────┘
         │ new
         ▼
┌──────────────────┐
│ Transport mode   │── agent / agentless / both
│ selection        │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Connectivity     │── fail ──▶ mark unreachable
│ test             │
└────────┬─────────┘
         │ pass
         ▼
┌──────────────────┐
│ Store asset      │── site, group, tags, criticality, owner
│ (hosts table)    │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Credential       │── vault store (scope: host)
│ assignment       │
└──────────────────┘
```

## 3. Agent Registration & Heartbeat Workflow

```
Agent starts
  │
  ▼
GET /api/version  ── mismatch ──▶ warn (continue)
  │
  ▼
POST /api/register (hostname, ip, os, arch, agent_version, site)
  │
  ├── host exists ──▶ update fields, mint token if needed
  │
  └── new host ──▶ create row, mint per-host token
  │
  ▼
Store agent_token locally (chmod 0600)
  │
  ▼
Periodic: POST /api/heartbeat (host_id, agent_token)
  │
  ├── 200 OK ──▶ update last_heartbeat, is_online=True
  │
  ├── 401 ──▶ clear token, re-register
  │
  └── 404 ──▶ re-register
  │
  ▼
OS family group ensured (OS_FAMILY_GROUPS lookup)
```

## 4. Vulnerability Detection Workflow

```
Feed ingestion (NVD/OSV/distro advisories) — incremental, idempotent
  │
  ▼
Normalize → VulnSource, Vulnerability, VulnAffected, ExploitSignal
  │
  ▼
Inventory collection (OS, kernel, packages, Windows updates)
  │
  ▼
Matching engine (per ecosystem: dpkg, rpm, apk, pacman, semver, Windows KB)
  │
  ├── backport awareness: distro advisory beats upstream version
  │
  ▼
host_vulnerabilities (host, vuln, component, installed, fixed, first/last seen, status)
  │
  ▼
PMRS scoring (severity + exploit + known-exploited + exposure + criticality + patch avail − compensating controls)
  │
  ▼
SLA check → violation detection → owner assignment
  │
  ▼
Remediation options: patch / mitigate / config change / accept / false-positive
```

## 5. Unauthenticated Scanning Workflow

```
Scan request (target, scope, rate limit)
  │
  ▼
enforce_scope(target, allowed) ── out of scope ──▶ ScopeViolation (refuse)
  │
  ▼
TCP connect scan (semaphore rate limit, non-intrusive)
  │
  ▼
Banner grab + service identification
  │
  ▼
TLS inspection (protocol, ciphers, cert expiry, hostname mismatch)
  │
  ▼
HTTP security header checks
  │
  ▼
Output → host_vulnerabilities (source: network_scan)
```

## 6. Patch Deployment Workflow (Proof Loop)

```
Policy selected → Ring rollout launched
  │
  ▼
Pre-gates: host_reachable, restore_capable, maintenance_window, disk_space, ...
  │
  ├── required gate fails ──▶ HOLD or ROLLBACK (per policy)
  │
  ▼
Snapshot/restore point created (if capability != none)
  │
  ├── no capability + no override ──▶ HOLD (irreversible rule)
  │
  ▼
Health gate (online, compliance score, CVE count)
  │
  ▼
Maintenance window gate
  │
  ▼
Patch selected hosts (batch_percent)
  │
  ▼
Post-gates: service_health, drift_clean, restore_drill_passed, approval_granted
  │
  ├── required gate fails ──▶ HOLD or ROLLBACK
  │
  ▼
Rollback threshold check (max_failed_percent)
  │
  ├── exceeded ──▶ ROLLBACK
  │
  ▼
Next ring (if more rings) ──▶ repeat
  │
  ▼
Evidence bundle created (hash chain + items)
  │
  ▼
Sign (Ed25519, if key present)
  │
  ▼
Audit log entry
  │
  ▼
Approval (if required) ──▶ await → approved → resume
  │
  ▼
Complete (success/failed/held/rolled_back)
```

## 7. Evidence Verification Workflow

```
Job completes
  │
  ▼
create_bundle (job_id, items) ── previous_bundle_hash (chain) ── bundle_hash
  │
  ▼
Sign with Ed25519 (if PM_EVIDENCE_SIGNING_KEY set)
  │
  ▼
Store in evidence_bundles + evidence_items
  │
  ▼
Export (JSON) ──▶ pm-evidence verify <bundle.json> [--pubkey KEY]
  │
  ├── bundle_hash recomputed == stored? ── no ──▶ FAIL
  ├── item_count matches? ── no ──▶ FAIL
  ├── payload_hash matches? ── no ──▶ FAIL
  ├── required steps present? ── no ──▶ FAIL
  ├── signature valid (if pubkey)? ── no ──▶ FAIL
  │
  └── all pass ──▶ PASS
  │
  ▼
Viewer UI: timeline, gate results, signature status, download, verify button
```

## 8. Credential Vault Workflow

```
store(name, type, scope, value)
  │
  ▼
Generate per-secret DEK (Fernet key)
  │
  ▼
Encrypt value with DEK → ciphertext
  │
  ▼
Wrap DEK with master key (env/file/KMS) → wrapped_dek
  │
  ▼
Store Credential (wrapped_dek, ciphertext, scope, expiry)
  │
  ▼
retrieve(type, scope, scope_id)
  │
  ▼
Resolve most specific scope (host > group > site > global)
  │
  ▼
Unwrap DEK → decrypt ciphertext → plaintext
  │
  ▼
Use in connector (decrypted only in memory, never logged)
  │
  ▼
Audit entry (who/what/why, no secret value)
```

## 9. Connector Workflow

```
connector_for(host, mode, credentials)
  │
  ├── mode=agent ──▶ AgentConnector (agent proxy)
  ├── mode=ssh ──▶ SshConnector (paramiko)
  ├── mode=winrm ──▶ WinRmConnector (pywinrm)
  └── mode=relay ──▶ RelayConnector (jump)
  │
  ▼
connect() ── fail ──▶ simulated fallback
  │
  ▼
run(template) ── resolve template name → command → execute → CommandResult
  │
  ▼
put_file / get_file / facts / close
```

## 10. Relay Workflow

```
Relay registers with master (one-time enrolment token)
  │
  ▼
Jump mode: relay connector traffic to isolated segment
  │
  Distribution mode: cache patch content locally
  │
  ▼
Asset requests patch ──▶ relay cache hit? ── yes ──▶ serve (checksum verify)
  │                                    └── no ──▶ fetch from master ──▶ cache ──▶ serve
  │
  ▼
Resilience: relay works through short master outages (cached content)
  │
  ▼
Capacity: bandwidth caps, cache quotas, retention, pre-seeding
```

## 11. Compliance Workflow

```
Compliance control defined (control_id, framework, severity, automated_check)
  │
  ▼
run_controls(controls, hosts, checker)
  │
  ▼
Per control per host: checker(host, control) → passed/failed
  │
  ▼
ComplianceFinding (control_id, host_id, status, evidence, remediation)
  │
  ▼
Status: open → mitigated → fixed → accepted → false_positive
  │
  ▼
Remediation: patch / mitigation / config change / accept / none available
```

## 12. Topology Orchestration Workflow

```
Service graph (nodes + dependencies)
  │
  ▼
patch_service(service, members, patch_fn, tolerance)
  │
  ▼
For each member (in dependency order):
  patch → verify → if fail, count
  │
  ├── failures > tolerance ──▶ STOP (recoverable state)
  │
  └── continue
  │
  ▼
Result: success/stopped, failed count, per-member results
```

## 13. Air-Gap Workflow

```
Offline bundle produced (signed, hash-chained)
  │
  ▼
validate_bundle (hash chain + payload hashes + structure)
  │
  ├── invalid ──▶ reject
  │
  ▼
import_bundle (record as evidence)
  │
  ▼
Content verification (checksum) before deployment
  │
  ▼
Deploy from local repository state
```

## 14. Mitigation Playbook Workflow

```
Vulnerability with no patch (or risky patch)
  │
  ▼
Select playbook (versioned, reversible, tested)
  │
  ▼
apply_playbook(playbook, host, executor)
  │
  ▼
For each step: execute → if fail + stop_on_failure → break
  │
  ▼
Result: ok per step, overall ok
  │
  ▼
Evidence record (like a patch)
```

## 15. Auto-Deploy Rule Workflow

```
Patch available → evaluate_rules(rules, patch, host)
  │
  ▼
For each rule: check enabled, categories, severities, os_platforms, include/exclude apps
  │
  ▼
Matching rules → trigger deployment
  │
  ▼
Draft/preview/publish flow: draft → preview → published
```

## 16. ITSM Integration Workflow

```
Deployment event → ITSM connector (ServiceNow/Jira/Motadata)
  │
  ▼
create_change(title, description, evidence_ref)
  │
  ▼
attach_evidence(change_id, evidence_ref)
  │
  ▼
Approval history preserved in ticket
  │
  ▼
Evidence bundle attached to change record
```

## 17. Feed Ingestion Workflow

```
Scheduler triggers sync_source(plugin, session, since)
  │
  ▼
plugin.fetch(since) ── network ──▶ raw records (or empty on failure)
  │
  ▼
plugin.normalize(raw) → {cve_id, title, summary}
  │
  ▼
Idempotent upsert (no duplicates)
  │
  ▼
Health page: last sync, record counts, errors, staleness warnings
```

## 18. Scanning Workflow

```
Scan request (target, allowed scope, ports, rate limit)
  │
  ▼
enforce_scope(target, allowed) ── out of scope ──▶ ScopeViolation
  │
  ▼
TCP connect scan (semaphore rate limit)
  │
  ▼
Banner grab + service identification
  │
  ▼
TLS inspection (protocol, ciphers, cert expiry, hostname)
  │
  ▼
HTTP security header checks
  │
  ▼
Output → host_vulnerabilities (source: network_scan)
```