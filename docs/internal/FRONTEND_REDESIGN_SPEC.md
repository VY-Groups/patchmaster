# Patch-SecOps Solution Frontend Redesign Specification

## Purpose
This document is the source of truth for the next full Patch-SecOps Solution frontend redesign.

It is written so another AI or frontend engineer can read it once and execute the redesign without guessing the product direction.

This is a frontend-only redesign brief.

## Stitch Source Of Truth

The local Stitch reference library at:

- `C:\Users\test\Desktop\pat-1\stitch`

is the authoritative visual source for the redesign.

This is not optional inspiration.
This is the required implementation target.

For every Stitch subfolder that contains both:

- `code.html`
- `screen.png`

the real frontend must reproduce that page as closely as possible inside the React application.

The implementation must match the Stitch source for:

- layout
- section order
- feature position
- shell composition
- visual hierarchy
- logo treatment
- card structure
- table framing
- control placement
- spacing rhythm
- page tone

### Non-negotiable rule

If a page has a matching Stitch subfolder with `code.html` and `screen.png`, the shipped page must be treated as a React/Tailwind replica of that Stitch page.

### Reference priority

For each page, use references in this order:

1. `screen.png` for final visual truth
2. `code.html` for structure and layout translation
3. current React page for logic and real data wiring

### Logic boundary

The replica requirement applies to:

- visuals
- layout
- page composition
- styling
- component placement

It does not authorize changing:

- backend business logic
- API contracts
- product workflows
- licensing behavior
- deployment behavior

### Missing or partial Stitch references

If a Stitch folder is incomplete, use the closest valid Stitch page in the same workflow family and preserve the same overall visual language.
Do not invent a different design system because one folder is partial.

It does not change:
- backend business logic
- API contracts unless the UI is blocked by missing fields
- licensing model
- deployment workflow
- packaging model
- agent capabilities

It does change:
- layout system
- navigation system
- component system
- information density
- page hierarchy
- interaction patterns
- visual trust
- responsive behavior

---

## 1. Final Design Goal

Patch-SecOps Solution must become:
- a professional enterprise endpoint operations platform
- a serious patch, provisioning, and policy control plane
- a UI suitable for infrastructure, platform, security, and operations teams

Patch-SecOps Solution must not feel like:
- a generic admin template
- a startup CRUD panel
- a sparse dashboard mockup
- a marketing-first app
- a flashy design experiment

The finished frontend must clearly communicate:
- operational control
- fleet awareness
- system trust
- change governance
- enterprise readiness

---

## 2. Approved Visual Direction

The approved visual direction is the Stitch folder implementation target.

That means the redesign must preserve:
- a light enterprise shell
- a clean left navigation
- a simple top bar
- restrained use of color
- readable typography
- low visual noise
- professional visual discipline

### Replica standard

The correct implementation question is:

- "How do we make the real Patch-SecOps Solution page look like its Stitch source?"

not:

- "How do we loosely redesign this screen in the same spirit?"

The redesign must not replace this with:
- a heavy dark security-console aesthetic
- flashy gradients
- decorative visual effects
- overly artistic layouts
- consumer SaaS styling

### What is already good in the sample
- clean shell
- believable enterprise tone
- readable structure
- stable navigation
- simple dashboard baseline
- restrained visual language

### What is not good enough in the sample
- too much empty space
- weak first-view operational depth
- generic forms and tables
- underpowered empty states
- weak vendor-side visual distinction
- mobile layout that looks like desktop compressed into a narrow screen

### Final target
After the redesign, all of the following must be true:
- good reference for tone: `yes`
- good final enterprise UI: `yes`
- good starting shell for serious redesign: `yes`
- faithful Stitch replica in the real app: `yes`

---

## 3. Redesign Objective

Redesign the frontend so it becomes a true enterprise operations cockpit for:
- automatic software distribution
- patch management
- operating system provisioning
- configuration management
- hardware and software inventory
- reports
- license operations
- vendor-side customer and license lifecycle operations

The redesign must preserve the current module map while making the UI:
- denser
- clearer
- more actionable
- more trustworthy
- more globally professional
- more responsive

At the same time, the redesign must translate the Stitch pages into the real application as exact visual targets, not just stylistic guidance.

---

## 4. Core Problems To Solve

### 4.1 Excessive emptiness
The current UI leaves too much unused space on critical pages such as:
- Dashboard
- Hosts
- Reports
- Vendor Portal
- Onboarding
- Provisioning

### 4.2 Generic CRUD feel
Too many screens still feel like:
- plain forms
- simple data tables
- starter admin CRUD patterns

They need to feel like governed enterprise workflows.

### 4.3 Weak first-view operational depth
Important pages should reveal meaningful operational context immediately:
- health
- risk
- readiness
- counts
- last changes
- pending actions

### 4.4 Weak distinction between workspaces
Different work types currently feel too visually similar:
- customer fleet operations
- provisioning and boot control
- policy and change management
- vendor-side licensing operations

### 4.5 Weak mobile and narrow-screen behavior
The sample mobile views show the desktop UI shrinking down directly.
That must not be the shipped responsive behavior.

---

## 5. Design Principles

### 5.1 Operations-first
Every page must answer:
- what is happening
- what is failing
- what changed
- what needs attention
- what the next safe action is

### 5.2 Density with clarity
The redesign must add density without adding chaos.

Use:
- summary strips
- compact metrics
- strong tables
- status badges
- actionable empty states
- detail drawers
- layered workflows

### 5.3 Progressive disclosure
Show essential operational context first.
Move advanced detail into:
- drawers
- tabs
- expandable panels
- side inspection views

### 5.4 Shared system over one-off pages
The redesign must be systemic, not page-by-page cosmetic editing.

Shared patterns must exist for:
- shell
- cards
- tables
- badges
- summaries
- drawers
- action bars
- confirmations
- empty states

### 5.5 International professionalism
All UI text must feel globally professional.
Avoid vague wording, slang, or region-specific assumptions.

### 5.6 Stitch-first fidelity

Every page implementation must begin by checking the corresponding Stitch source.

The engineer or AI doing the redesign must:

- open the matching `screen.png`
- inspect the matching `code.html`
- reproduce the same layout in React
- then bind the real Patch-SecOps Solution logic into that layout

Only after that may they adjust for:

- responsiveness
- accessibility
- shared component reuse
- real data edge cases

---

## 6. Visual System Direction

### 6.1 Style target
The product should visually feel like:
- a modern enterprise operations workspace
- a patch and provisioning control plane
- a disciplined fleet management console

It should not feel like:
- a marketing dashboard
- a pure template
- a consumer productivity app
- a cyberpunk themed SOC wall

### 6.2 Visual character
Use:
- light surfaces
- strong edge alignment
- calm neutrals
- meaningful blue accents
- semantic status colors
- strong spacing discipline
- readable page hierarchy

### 6.3 Preserve from sample
Preserve these traits:
- clean light shell
- compact left navigation
- simple top bar
- restrained styling
- readable typography
- straightforward cards

### 6.4 Improve beyond sample
Improve these traits materially:
- stronger operational density
- better summary cards
- better table architecture
- better empty states
- better emphasis for critical actions
- better workspace separation
- proper responsive reflow

---

## 7. Global Layout Specification

### 7.1 App shell
The shell must contain:
1. Left navigation
2. Top context bar
3. Page header
4. Summary/action strip
5. Main content area
6. Optional right-side detail drawer

### 7.2 Left navigation
The left nav should remain visually close to the approved sample:
- icon plus label rows
- clean active state
- low decorative weight
- clear section rhythm

Recommended navigation groups:
- Overview
- Endpoints
- Software and Patch
- Change Control
- Provisioning
- Reporting
- Platform
- Security and Access
- Vendor Operations

### 7.3 Top context bar
The top bar should display:
- current user
- environment label
- version/build label
- notification entry
- global search or quick command entry if practical
- active scope where relevant

### 7.4 Page header
Each page header must contain:
- title
- one-line purpose
- top-level page actions
- last refresh or last sync where relevant

### 7.5 Summary strip
Each major page should start with a compact summary layer showing:
- counts
- health
- urgency
- recent change signal
- attention state

---

## 8. Shared Component System

## 8.1 Data tables
All operational tables must support:
- sticky header
- sorting
- search
- filter toolbar
- saved views
- row selection
- bulk actions
- export
- pagination
- density modes
- empty state with direct next action

### Table quality target
The final table system must feel much stronger than the approved sample:
- better hierarchy
- stronger scanability
- better status display
- better row actions
- less visual fragility

## 8.2 Status badges
Standard badge vocabulary should include:
- online
- offline
- degraded
- pending
- failed
- queued
- running
- completed
- compliant
- non-compliant
- warning
- blocked

## 8.3 Summary cards
Summary cards must be:
- compact
- readable
- consistent
- meaningful

They must not be decorative boxes with little value.

## 8.4 Action bars
Major pages need a standard action bar for:
- refresh
- add/create
- bulk actions
- export
- filter reset
- context actions

## 8.5 Drawers
Use right-side drawers for complex record inspection:
- host detail
- job detail
- policy detail
- provisioning run detail
- boot relay detail
- license detail
- customer detail

Avoid centered modals for complex operational records.

## 8.6 Confirmation flows
Risky actions must show:
- impacted target count
- action summary
- timing context
- rollback or recovery note where relevant
- final confirmation step

## 8.7 Timelines
Use timeline components for:
- host activity
- deployment history
- provisioning history
- policy execution history
- license lifecycle

---

## 9. Page-By-Page Requirements

## 9.0 Stitch Page Mapping

The following Stitch folders are the canonical visual references for the corresponding product pages and workspaces:

| Product surface | React surface | Primary Stitch source |
|---|---|---|
| Dashboard | `frontend/src/DashboardOpsPage.jsx` | `stitch/patchmaster_dashboard/` |
| Hosts | `frontend/src/HostsOpsPage.jsx` | `stitch/host_management/` |
| Patch Management | `frontend/src/PatchManagerOpsPage.jsx` | `stitch/patch_manager/` and `stitch/patching_command_center_v2/` |
| CVE Tracker | `frontend/src/CVEOpsPage.jsx` | `stitch/cve_tracker_remediation/` |
| Monitoring | `frontend/src/MonitoringOpsPage.jsx` | `stitch/monitoring_operations_v2/` with `stitch/monitoring_operations/` as fallback |
| Backup and Recovery | `frontend/src/BackupManagerPage.jsx` and related restore views | `stitch/backup_dr_manager/` |
| Policy Manager | `frontend/src/PolicyManagerPage.jsx` | `stitch/policy_yaml_editor/` |
| Users and RBAC | `frontend/src/UsersOpsPage.jsx` | `stitch/user_rbac_management/` |
| Live Terminal | `frontend/src/LiveCommandPage.jsx` | `stitch/live_command_terminal/` |
| Host Timeline | `frontend/src/HostTimelinePage.jsx` | `stitch/host_timeline/` |
| Bulk Patch | `frontend/src/BulkPatchPage.jsx` | `stitch/bulk_patch_operations/` |
| CI/CD Pipelines | `frontend/src/CICDOpsPage.jsx` | `stitch/ci_cd_pipelines/` |
| Alerts | `frontend/src/AlertsCenterPage.jsx` | `stitch/alerts_center/` |
| Audit Trail / Compliance | `frontend/src/AuditPage.jsx` and related compliance views | `stitch/audit_compliance_reports/` |
| License | `frontend/src/LicenseOpsPage.jsx` | `stitch/license_tier_management/` |
| Software Manager | `frontend/src/SoftwarePage.jsx` | `stitch/software_kiosk/` |
| Network Boot | `frontend/src/NetworkBootPage.jsx` | `stitch/network_boot_manager/` |
| Mirror Repositories | `frontend/src/MirrorRepoOpsPage.jsx` | `stitch/mirror_repositories/` |
| Maintenance Windows | `frontend/src/MaintenanceWindowsPage.jsx` | `stitch/maintenance_windows/` |
| Infrastructure summary / advanced dashboards | relevant dashboard or analytics surfaces | `stitch/infrastructure_dashboard_v2/` |
| Host repository / package inventory views | relevant repository surfaces | `stitch/host_repository_v2/` |
| Operations Queue | `frontend/src/OpsQueuePage.jsx` | `stitch/operations_queue/` |
| Local Repository | `frontend/src/LocalRepoOpsPage.jsx` | `stitch/local_repo_manager/` |
| Analytics / SLA | `frontend/src/AnalyticsOpsPage.jsx` and related SLA views | `stitch/analytics_sla_ops/` |
| Agent Updates | `frontend/src/AgentUpdatePage.jsx` | `stitch/agent_update_center/` |

If two Stitch folders both apply to one real workspace, use the more feature-complete page structure while preserving the exact shared visual language of the Stitch references.

## 9.1 Dashboard
Source:
- `frontend/src/DashboardOpsPage.jsx`

### Goal
Turn Dashboard into a fleet control surface.

### Must show
- total hosts
- online hosts
- pending patches
- active policies
- failed jobs
- provisioning activity
- relay readiness
- backup readiness
- license state
- recent critical activity
- system health

### Layout
- top summary band
- primary activity area
- health/readiness side panel
- lower section for site or scope breakdown

### Empty state
Must guide setup:
- onboard first host
- configure package or mirror sources
- review policy baseline
- configure provisioning

### Upgrade over sample
Keep the same clean shell tone, but remove blankness and make the page feel decisively operational.

## 9.2 Hosts
Source:
- `frontend/src/HostsOpsPage.jsx`

### Goal
Make Hosts the central fleet workspace.

### Required columns
- status
- hostname
- IP
- site
- OS
- last seen
- patch posture
- policy
- group or tags
- agent version
- boot mode
- Secure Boot
- provisioning state

### Required capabilities
- filter toolbar
- bulk actions
- saved views
- risk indicator
- quick row actions
- detail drawer

### Host detail drawer must include
- identity
- inventory
- patch state
- installed software summary
- last jobs
- provisioning history
- timeline
- actions

### Upgrade over sample
The current shell is fine, but the final page must support real fleet management, not just static host listing.

## 9.3 Onboarding
Source:
- `frontend/src/OnboardingOpsPage.jsx`

### Goal
Turn onboarding into a real operations workspace.

### Must include
- Linux onboarding tab
- Windows onboarding tab
- site preassignment
- group preassignment
- policy preassignment
- relay context where relevant
- generated install commands
- registration activity
- trust/health checklist

### Must not feel like
- a simple instructions page

### Upgrade over sample
The sample onboarding surface is too sparse and must become a guided workflow page.

## 9.4 Software Manager
Source:
- `frontend/src/SoftwarePage.jsx`

### Goal
Make software distribution feel governed and operational.

### Must include
- approved catalog
- request queue
- approval status
- install/remove action
- target host scope
- shutdown-queued state
- success/failure summary

### Visual priority
Emphasize:
- pending approvals
- deferred actions
- blocked actions
- execution outcomes

## 9.5 Patch Management
Source:
- `frontend/src/PatchManagerOpsPage.jsx`

### Goal
Make this the strongest operational page in the product.

### Must include
- patch summary
- pending count
- critical count
- affected hosts
- ring targeting
- maintenance awareness
- rollout progress
- restart required state
- blocked and failed actions

### Layout
- summary strip
- candidates table
- rollout targeting panel
- recent rollout history

## 9.6 Maintenance Windows
Source:
- `frontend/src/MaintenanceWindowsPage.jsx`

### Goal
Treat maintenance windows as change governance.

### Must include
- upcoming windows
- affected counts
- linked tasks
- overlap/conflict warnings
- change history

### Upgrade over sample
The sample page is too light. It must feel like a governed operational workspace.

## 9.7 Ring Rollout
Source:
- `frontend/src/RingRolloutPage.jsx`

### Goal
Make rollout waves visible and auditable.

### Must include
- ring definitions
- target counts
- progress by ring
- guardrail summary
- success/failure by wave
- rollback access

## 9.8 Policy Manager
Source:
- `frontend/src/PolicyManagerPage.jsx`

### Goal
Make policy management feel revision-based and enterprise-grade.

### Must include
- active revision
- draft revision
- dry-run result
- apply result
- rollback actions
- per-host impact
- execution history
- audit linkage

### Visual rule
This must not look like a plain settings form.

## 9.9 Provisioning Center
Source:
- `frontend/src/ProvisioningPage.jsx`

### Goal
Make image-based provisioning feel production-ready.

### Must include
- templates
- source host
- OS/platform
- site scope
- archive size
- checksum
- target counts
- recent runs
- result summary

### Interactions
- create template
- queue provisioning
- inspect rollout
- inspect per-target result

### Upgrade over sample
The sample provisioning surface is too minimal. It must communicate value and readiness immediately.

## 9.10 Boot Relays / Network Boot
Source:
- `frontend/src/NetworkBootPage.jsx`

### Goal
Make this a managed bare-metal deployment console.

### Must include
- boot networks
- boot profiles
- managed relays
- relay health
- sync state
- validate state
- artifact version
- assignments
- boot sessions
- first-boot enrollment status

### Visual separation required
Separate clearly:
- network definition
- profile definition
- relay operations
- live session evidence

### Non-negotiable
This page must not look like planning or roadmap content.
It must feel active and operational.

## 9.11 Reports
Source:
- `frontend/src/ReportsOpsPage.jsx`

### Goal
Turn reports into a reporting workspace.

### Must include
- preset reports
- filters
- date range
- site scope
- scheduled reports
- recent exports
- compliance summaries

## 9.12 Users / Access
Source:
- `frontend/src/UsersOpsPage.jsx`

### Goal
Make access control feel role-driven and auditable.

### Must include
- users
- roles
- directory integration status
- recent access changes
- account state
- admin actions

## 9.13 Integrations
Source:
- `frontend/src/PluginIntegrationsPage.jsx`

### Goal
Make integrations feel trustworthy and manageable.

### Must include
- connected systems
- plugin state
- sync state
- last error
- health or credential state

## 9.14 License Operations
Source:
- `frontend/src/LicenseOpsPage.jsx`

### Goal
Show license state clearly without exposing secrets.

### Must include
- validity
- tier
- features
- expiry
- binding required or not
- masked hardware binding fingerprint
- activation history summary

### Must not show
- raw private secrets
- confusing low-level technical wording

## 9.15 Vendor Operations
Relevant surfaces:
- vendor internal portal
- any frontend views used for customer and license operations

### Goal
Make vendor workflows clearly different from customer fleet workflows.

### Must include
- customer table
- testing/POC license issuance
- hardware or MAC ID recording
- binding verification state
- final license issuance
- renew/revoke flow
- notes
- license timeline

### Styling rule
Keep the product family look, but visually differentiate this workspace enough that the operator clearly knows they are in Vendor operations.

---

## 10. Login Experience

### Goal
Make login feel secure, clear, and professional.

### Requirements
- clean layout
- product identity
- concise trust-focused message
- version/build label
- good error treatment
- no generic marketing tone

### Visual rule
If an image is used, it must support enterprise credibility and not dominate the form.

---

## 11. Empty State Rules

Every major page must have an actionable empty state.

Each empty state must include:
- what is missing
- why it matters
- recommended next action
- direct action button or command

Example for Hosts:
- onboard first Linux host
- onboard first Windows host
- import/register a host

---

## 12. Notification And Feedback Model

### Must include
- toast for quick low-risk success/failure
- persistent in-page error surfaces for important failures
- activity streams where operationally useful
- warning banners on risky pages

### Toasts are not enough for
- rollout failures
- provisioning failures
- policy apply failures
- multi-host execution failures

These must also be visible in-page.

---

## 13. Responsive Behavior

### Priority
Desktop is the primary operating surface.

Tablet and narrow screens must still feel intentionally designed.
Phone support should prioritize:
- essential read access
- approvals
- quick status review
- limited safe actions

### Requirements
- collapsible navigation
- reflowed page spacing
- stacked summaries
- priority-based responsive tables
- usable drawers on narrow screens
- no tiny unreadable desktop shrink
- no full desktop grids squeezed into phone width

### Explicit rule from approved sample review
The final mobile experience must not look like the desktop page simply compressed vertically.

---

## 14. Accessibility And International Quality

The redesign must include:
- keyboard accessibility
- visible focus states
- semantic headings
- accessible table behavior
- strong contrast
- color not used as the only meaning signal
- consistent terminology
- globally professional English
- predictable date/time presentation

---

## 15. Frontend Architecture Requirements

### Rebuild goals
- create reusable shell primitives
- create reusable summary components
- create reusable table system
- create reusable badge system
- create reusable drawer system
- create reusable action bar system
- unify spacing and interaction patterns

### Do not do
- isolated page cosmetics
- one-off local styles for each module
- modal-heavy complex workflows
- random redesigns that drift from the approved sample tone

### Required implementation mindset
This is not a skin pass.
This is a systemic frontend rebuild on top of existing product logic.

---

## 16. Implementation Mapping To Current Files

Primary files:
- `frontend/src/App.js`
- `frontend/src/App.css`
- `frontend/src/OpsPages.css`
- `frontend/src/DashboardOpsPage.jsx`
- `frontend/src/HostsOpsPage.jsx`
- `frontend/src/OnboardingOpsPage.jsx`
- `frontend/src/SoftwarePage.jsx`
- `frontend/src/PatchManagerOpsPage.jsx`
- `frontend/src/MaintenanceWindowsPage.jsx`
- `frontend/src/RingRolloutPage.jsx`
- `frontend/src/PolicyManagerPage.jsx`
- `frontend/src/ProvisioningPage.jsx`
- `frontend/src/NetworkBootPage.jsx`
- `frontend/src/ReportsOpsPage.jsx`
- `frontend/src/UsersOpsPage.jsx`
- `frontend/src/LicenseOpsPage.jsx`
- `frontend/src/PluginIntegrationsPage.jsx`
- `frontend/src/ToastSystem.jsx`

Supporting files that may also need updates:
- `frontend/src/MonitoringOpsPage.jsx`
- `frontend/src/NotificationsPage.jsx`
- `frontend/src/AuditPage.jsx`
- `frontend/src/HostTimelinePage.jsx`
- `frontend/src/OpsQueuePage.jsx`
- `frontend/src/BackupManagerPage.jsx`
- `frontend/src/RestoreDrillPage.jsx`

---

## 17. Execution Plan

This is the required implementation order.

### Mandatory execution rule

For every page in each work package:

1. inspect the mapped Stitch `screen.png`
2. inspect the mapped Stitch `code.html`
3. recreate that layout in React/Tailwind
4. wire the real Patch-SecOps Solution data into it
5. verify the resulting page still matches the Stitch reference visually

### Work package 1: Shell and design system
- rebuild app shell
- rebuild navigation
- define spacing system
- define summary cards
- define badge system
- define table system
- define drawer system
- define action bars
- define responsive rules

### Work package 2: Core fleet pages
- dashboard
- hosts
- onboarding

### Work package 3: Change execution pages
- software manager
- patch management
- maintenance windows
- ring rollout
- policy manager

### Work package 4: Infrastructure operations pages
- provisioning center
- boot relays
- reports

### Work package 5: Platform and governance pages
- users and access
- integrations
- notifications
- audit-linked views
- license operations

### Work package 6: Vendor and final polish
- vendor operations styling
- login
- consistency pass
- responsive pass
- accessibility pass

---

## 18. Acceptance Criteria

The redesign is complete only when all of the following are true:

1. The UI keeps the approved clean light-shell tone.
2. The product no longer feels like a generic admin template.
3. The dashboard gives immediate operational visibility.
4. Hosts supports real fleet workflows.
5. Software, patch, policy, and provisioning pages feel task-oriented, not CRUD-oriented.
6. Vendor operations feel clearly distinct from customer operations.
7. Empty states are actionable and useful.
8. Shared patterns exist for shell, cards, tables, badges, drawers, and action bars.
9. The product is information-dense without feeling cluttered.
10. The UI is internationally professional.
11. The responsive behavior no longer looks like compressed desktop pages.
12. The final result feels like an enterprise endpoint-management control plane.
13. Each implemented page is visually faithful to its mapped Stitch source.
14. Stitch `screen.png` references are recognizably reproduced in the final app shell.

### Final yes-check
The redesign is successful only if the answer to all four is `yes`:
- good reference for tone: yes
- good final enterprise UI: yes
- good starting shell for serious redesign: yes
- faithful Stitch replica in the real app: yes

---

## 19. Non-Goals

This redesign does not require:
- changing the product name
- changing the packaging model
- changing the licensing workflow
- changing the deployment scripts
- rewriting backend business logic without cause

---

## 20. AI Handoff Instruction

When another AI reads this file, it must treat this document as the controlling brief.

### The AI must
1. preserve backend logic and current feature coverage
2. inspect the mapped Stitch `screen.png` before changing each page
3. inspect the mapped Stitch `code.html` before changing each page
4. preserve the approved clean light-shell visual tone
5. redesign the frontend systemically, not page-by-page randomly
6. implement shared systems before page polish
7. make the product denser and more operational without drifting visually from Stitch
8. fix responsive behavior properly
9. keep the module structure recognizable

### The AI must not
- replace the approved light-shell direction with a dark cyber style
- turn the product into a marketing site
- reduce information density
- ship desktop pages simply shrunk for mobile
- redesign pages in isolation without shared patterns
- treat Stitch as loose inspiration only
- move major sections or controls away from their Stitch positions without a real product constraint

### Required output from the next AI implementation pass
- updated shell
- updated shared components
- updated pages
- responsive behavior improvements
- consistency across all major workspaces
- frontend build verification
- concise summary of what changed

### Definition of done
The redesign is done only when this document's acceptance criteria are fully satisfied.
