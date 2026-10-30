# PatchMaster Counter-Plan

**Prepared:** 27 October 2026  
**Source:** `patchmaster-counter-plan.xlsx`  
**Purpose:** Consolidated Markdown version of the workbook, covering the capability comparison, competitor observations, planned changes, engineering checklist, and observed Motadata screens.

> **Evidence note:** Competitor facts below are based on demo screenshots and documents shared for this comparison. “Not seen” means not visible in the supplied material; it does **not** prove that a product lacks the feature. Verify observations before using them in external presentations or sales claims.

## 1. Executive summary

PatchMaster's proposed differentiation is to build reliable patch orchestration around **per-patch deployment gates, rollback, signed evidence, risk prioritisation, and auditable deployment workflows**—rather than trying to match every competitor feature immediately.

### Suggested priorities
- **Must:** Agentless management, relay/remote-office support, risk scoring, approval/test gates, rollback and signed evidence, automatic deployment rules, and CVE noise reduction.
- **Should:** Config audit, third-party application catalog, macOS coverage, ITSM integrations, reports, policy templates, deployment scheduling, air-gap support, and cluster-aware patching.
- **Later:** An optional read-only AI assistant, introduced only after the core product and evidence model are reliable.

## 2. Workbook audit and checks

The workbook contains six visible sheets:
1. Summary
2. Capability Map
3. Competitor Gaps
4. Plan Changes
5. No-Vibe Checklist
6. Screens Observed

### Counts checked against the workbook
| Section | Expected item count | Checked |
|---|---:|---|
| Capability Map | 12 | Yes |
| Competitor Gaps | 6 | Yes |
| Plan Changes | 13 | Yes |
| No-Vibe Checklist | 5 | Yes |
| Screens Observed | 6 | Yes |

**Formula review:** The Summary sheet's item-count ranges align with the listed data rows: Capability Map `A5:A16`, Plan Changes `A5:A17`, and No-Vibe Checklist `A5:A9`. Status/priority counts use corresponding data ranges. The completion percentage is calculated as `Done / Total items`.

**Important:** The summary uses Excel formulas, so some spreadsheet viewers may show blank or stale summary values until formulas recalculate. The Markdown copy below records the underlying worksheet data; update the spreadsheet's Status/Priority cells as work progresses.

## 3. Capability map: SecOps vs Motadata vs PatchMaster target

| Capability | SecOps | Motadata (from demo screens) | PatchMaster target | Suggested priority | Status | Owner | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Agent-based management | Yes (lightweight agents for roaming devices) | Yes (agent 8.7.x seen) | Exists today in PatchMaster | Must | Done |  |  |
| Agentless (SSH / WinRM) | Yes | Not seen | Stage 2 | Must | Not started |  |  |
| Relay / remote offices | Yes (jump host, distribution) | Yes (remote offices, file server) | Stage 2 | Must | Not started |  |  |
| Scanning and risk score | Yes (CPR score) | CVE list with severity and exploited flag | Stage 3 (PMRS) | Must | Not started |  |  |
| Config audit | Yes (CIS, STIG, custom) | Not seen | Stage 5 | Should | Not started |  |  |
| Third-party apps | 1,300+ apps | About 85 mostly utilities | Stage 4 (catalog) | Should | Not started |  |  |
| macOS | Yes (Intel and Apple silicon) | Endpoints seen, patching unclear (0 vulnerabilities shown) | Stage 4 | Should | Not started |  |  |
| Approve and test before deploy | Approvals | Pre-approved, manual, or test-and-approve (single global mode) | Stage 1 (gates) | Must | Not started |  |  |
| Rollback and signed evidence | Rollback only | Not seen | Stage 1 (unique differentiator) | Must | Not started |  |  |
| ITSM, change, SLA | Not seen | Strong (releases, changes, SLA, approvals) | Connectors (ServiceNow, Jira, Motadata) | Should | Not started |  |  |
| Cluster-aware patching | Not seen | Not seen | Stage 6 | Should | Not started |  |  |
| Air-gap | Yes (offline content transfer) | Not seen | Stage 7 | Should | Not started |  |  |

## 4. Competitor gaps and hypotheses to verify

These are comparison hypotheses based on the supplied evidence, not confirmed statements about the full competitor products.

| Competitor | Observation | Basis | Verify before use? |
| --- | --- | --- | --- |
| Motadata | Agent-only; endpoint list shows agent version 8.7.x | Endpoint and deployment screens | Yes |
| Motadata | One global approval mode (Pre Approved / Manually Approve / Test and Approve); no per-patch gates or signed evidence seen | Patch Control screen | Yes |
| Motadata | Third-party catalog of about 85 apps, mostly small utilities | Application Updates list (85 items) | Yes |
| Motadata | Thousands of CVEs per endpoint with only severity and an exploited flag to rank them | Endpoints list (total vulnerabilities column) | Yes |
| Motadata | macOS endpoints show 0 vulnerabilities | Endpoints list | Yes |
| Motadata | Demo deployment run: 85.71% download success but 0% install success; retry-failed was disabled | Remote deployment run PDR-124 analytics | Yes |

## 5. Changes to add to `plan.md` (v2 delta)

| ID | Change | Detail | Suggested stage / area | Suggested priority | Status | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| P1.1 | Policy template: business hours, no reboot | Motadata parity (policy named 'Business Hours Deployment - No Reboot') | Stage 4 | Should | Not started |  |
| P1.2 | Policy template: 24x7 deploy at startup | Motadata parity | Stage 4 | Should | Not started |  |
| P1.3 | Policy template: 24x7 with user intervention allowed | Motadata parity | Stage 4 | Should | Not started |  |
| P1.4 | Install-after and expiry dates on deployments | Motadata parity (expiry defaults to 15 days) | Stage 4 | Should | Not started |  |
| P1.5 | Draft / preview / publish flow for deployments | Motadata parity | Stage 4 | Should | Not started |  |
| P1.6 | Automatic deployment rules by category, severity and OS | Motadata parity | Stage 4 | Must | Not started |  |
| P1.7 | Per-OS patch sync schedule | Motadata parity (daily sync per category and OS) | Stage 3 / 7 (content) | Should | Not started |  |
| P1.8 | Decline policy | Motadata parity | Stage 4 | Should | Not started |  |
| P2 | ITSM connectors, not your own ITSM | Auto-create a change in ServiceNow, Jira or Motadata; attach the evidence bundle; take approvals from the ticket. Also lets you sell to Motadata customers. | Stage 8 (integrations) | Should | Not started |  |
| P3 | Noise reduction | Rank exploited and reachable CVEs first; de-duplicate across superseded patches | Stage 3 | Must | Not started |  |
| P4 | Catalog target | Start with a hand-verified list of the most-used apps and grow it; do not chase 1,300 at the start | Stage 4 | Should | Not started |  |
| P5 | Reports | Match Motadata's 14 patch reports, with scheduled exports | Stage 8 | Should | Not started |  |
| P6 | AI assistant | Optional and late; read-only at first and grounded in your evidence | After Stage 8 | Later | Not started |  |

## 6. Engineering checklist: build without vibe coding

Treat this as a release discipline, not a one-time checklist. Each item should have verifiable evidence attached to the relevant pull request or change.

| # | Practice | Evidence required | Status | Owner |
| --- | --- | --- | --- | --- |
| 1 | Each feature starts as a one-page spec with acceptance tests; competitor screens become flow-level test scenarios | Spec file plus failing tests committed first | Not started |  |
| 2 | Build the fake fleet and golden test data before the feature code | Fixture repository and seed-data generator | Not started |  |
| 3 | Small changes, tests first, green CI gates; second reviewer on credentials, signing and auth code | CI run link and reviewer sign-off | Not started |  |
| 4 | Every Mimo task carries the no-vibe-coding rule and Ponytail/REA output as evidence; a person reads every AI-written diff before it merges | Pasted plugin output in the change description | Not started |  |
| 5 | Reimplement behaviours only; do not copy another vendor's layout, text or assets | Short clean-room note per feature | Not started |  |

## 7. Motadata screens observed

Some text in the supplied screen-share images was blurry or cropped; confirm details in a fresh demo before relying on them.

| Area | What the screen shows |
| --- | --- |
| Patch Repository | Daily sync of patch categories per OS (Windows, Mac, many Linux distributions) from the vendor's central repository; must be current before scans and deployments. |
| Patch Control | Approval policy: Pre Approved, Manually Approve, or Test and Approve; plus a separate decline policy. |
| Create Patch Deployment | Name, install-after, expiry (15 days by default), install or uninstall, add patches (KB number, download size, UUID), target remote offices or endpoints, one of 9 deployment policies, notify-to, retry-failed toggle; Preview, Save as Draft, Publish. |
| Automatic Patch Deployment | Rules by patch category, severity (Critical, Important, Moderate, Low, Unspecified), OS platform, include or exclude applications, remote offices and endpoints. Two rules seen; one enabled. |
| Deployment run (PDR-124) | Install job under the IT Department policy; download status 85.71% success, install 0% success, 4 failed, retry-failed disabled. |
| Application Updates | About 85 third-party apps with search and per-row delete (Zoom, Wireshark, VS Code, Firefox, 7-Zip, PuTTY, Notepad++ and others). |

## 8. Suggested implementation sequence

This sequence is a recommendation based on the priorities in the workbook, not a confirmed commitment or timeline.

1. **Stage 1 — Safe deployment foundation:** Per-patch approval/test gates, rollback workflow, signed evidence, and auditable deployment records.
2. **Stage 2 — Fleet reach:** Agentless SSH/WinRM support and relay/distribution for remote offices.
3. **Stage 3 — Risk-first patching:** CVE risk scoring, prioritisation of exploited/reachable vulnerabilities, de-duplication of superseded patches, and reliable patch-content sync.
4. **Stage 4 — Deployment policy and catalog:** Automatic deployment rules, draft/preview/publish, policy templates, expiry/install-after dates, decline policy, and third-party application catalog.
5. **Stage 5 — Configuration compliance:** CIS/STIG/custom configuration audit.
6. **Stage 6 — Cluster-aware orchestration:** Coordinate patching around clustered workloads and availability constraints.
7. **Stage 7 — Offline/air-gap capability:** Controlled offline content transfer and content validation.
8. **Stage 8 — Integrations and reporting:** ITSM connectors, change-ticket evidence, scheduled reports/exports. Consider the read-only AI assistant only after these foundations are stable.

## 9. Acceptance criteria to make this actionable

- Each feature has a one-page specification, explicit acceptance tests, and a named owner before implementation.
- Deployment gates are testable at the **individual patch / deployment** level where required—not only as one global setting.
- Rollback and signed evidence are validated in automated tests, including failure scenarios.
- CVE prioritisation explains why an item is ranked highly and avoids duplicate alerts for superseded patches.
- Deployment jobs expose separate download and installation outcomes, actionable failure reasons, and retry behaviour.
- Third-party app updates are sourced, versioned, and verified; catalog size is not treated as a quality metric by itself.
- Offline content imports verify integrity and provenance before the content can be deployed.
- ITSM integrations preserve approval history and attach deployment evidence to the change record.
- AI-generated code is reviewed by a person before merge; credentials, signing, and authentication changes receive a second reviewer.
- Competitor observations are recorded as clean-room behavioural requirements. Do not copy competitor layouts, text, or visual assets.

## 10. Maintenance notes

- Keep this Markdown file and the Excel workbook aligned when priorities, owners, or statuses change.
- Update `Status` and `Owner` as work progresses; use notes to link specifications, tests, CI runs, and review evidence.
- Re-check competitor claims against current product documentation or a fresh demo before external use.
- The workbook's original status values are preserved here; no implementation status has been inferred or changed.
