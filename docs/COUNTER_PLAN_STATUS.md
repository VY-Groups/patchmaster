# PatchMaster Counter-Plan — Implementation Status

Mapped from `patchmaster-counter-plan.md` (v2 delta items P1–P6 and capability map).

## Capability map status

| Capability | Status in codebase |
|---|---|
| Agent-based management | Done (agents, heartbeat, tokens) |
| Agentless (SSH/WinRM) | Done (connectors with real SSH exec; WinRM interface + pywinrm) |
| Relay / remote offices | Done (jump + distribution cache + checksum) |
| Scanning and risk score (PMRS) | Done (TCP scan, PMRS with breakdown) |
| Config audit | Done (compliance controls + findings model) |
| Third-party apps | Stub (catalog target = hand-verified list approach) |
| macOS | Partial (OS detection exists; patching path not dedicated) |
| Approve and test before deploy | Done (gates, approval endpoint, evidence) |
| Rollback and signed evidence | Done (gated rollback, hash-chained + Ed25519 bundles) |
| ITSM, change, SLA | Stubs (ServiceNow/Jira/Motadata HTTP connectors) |
| Cluster-aware patching | Done (topology orchestrator + service graph) |
| Air-gap | Done (bundle import with integrity verification) |

## Plan changes (P1.x) status

| ID | Change | Status |
|---|---|---|
| P1.1 | Business hours, no reboot template | Done (policy_templates.py) |
| P1.2 | 24x7 deploy at startup template | Done |
| P1.3 | 24x7 with user intervention | Done |
| P1.4 | Install-after and expiry dates | Done (columns added) |
| P1.5 | Draft/preview/publish flow | Done (deploy_flow.py) |
| P1.6 | Automatic deployment rules | Done (auto_deploy.py + table) |
| P1.7 | Per-OS patch sync schedule | Partial (schedule field exists) |
| P1.8 | Decline policy | Done (declined_patches table) |
| P2 | ITSM connectors | Stubs (HTTP-based) |
| P3 | Noise reduction | Done (dedup + rank) |
| P4 | Catalog target | Approach documented (hand-verified list) |
| P5 | Reports | Names + endpoint (generation wired separately) |
| P6 | AI assistant | Read-only stub |

## Engineering checklist (no-vibe)

| # | Practice | Status |
|---|---|---|
| 1 | Feature starts as spec with acceptance tests | Followed (TDD throughout) |
| 2 | Fake fleet + golden test data before feature code | Done (S0-8 fleet + fixtures) |
| 3 | Small changes, tests first, green CI gates; second reviewer on creds/signing/auth | Followed |
| 4 | AI-written diff reviewed by person before merge | Followed |
| 5 | Reimplement behaviours; no copying competitor layouts/text/assets | Followed (clean-room) |