# Patch-SecOps Solution And Vendor Master Diagrams

## Short Intro
This diagram pack explains the current working model of both tools in a clear operator-friendly way:
- what Patch-SecOps Solution does
- what the Vendor tool does
- how agents, jobs, monitoring, testing, inventory, reports, and licenses flow
- how the product tarball, vendor tarball, and internal recovery files should be used in production with offline PM2 license verification

For the separate license-signing-focused pack, also see:
- `docs/internal/diagrams/license-workflow-diagrams.html`
- `docs/internal/diagrams/license-workflow-diagrams.md`

## 1. Patch-SecOps Solution System Architecture

```mermaid
flowchart TD
    A["Admin / Operator / Auditor"] --> B["Patch-SecOps Solution Web UI"]
    B --> C["FastAPI Backend"]

    C --> D["Dashboard + Search"]
    C --> E["Hosts + Groups + Tags + Site"]
    C --> F["Patch Manager + Software Manager"]
    C --> G["Policies + Maintenance Windows + Ring Rollout + Patch Hooks"]
    C --> H["Jobs + Queue + Rollback + Restore Drills"]
    C --> I["Compliance + CVE + Alerts + Audit"]
    C --> J["Reports + Notifications + Settings"]
    C --> K["Users + Roles + LDAP / AD + License Gates"]
    C --> L["Testing Center + CI/CD + Git + Plugin Integrations"]
    C --> M["Monitoring Control + Mirror Repos + Local Repo"]

    C --> N[("PostgreSQL")]
    C --> O["Agent Download + Registration + Command APIs"]

    O --> P["Linux Agent"]
    O --> Q["Windows Agent"]

    P --> R["Inventory + Heartbeat + Metrics + Package Actions"]
    Q --> S["Inventory + Heartbeat + Metrics + Package Actions"]

    R --> C
    S --> C

    R --> T["Prometheus Targets"]
    S --> T
    T --> U["Prometheus"]
    U --> V["Grafana"]
    V --> B
```

## 2. Patch-SecOps Solution Feature Workspace Map

```mermaid
flowchart LR
    A["Patch-SecOps Solution"] --> B["Dashboard + Analytics"]
    A --> C["Hosts + Groups + Tags + Site"]
    A --> D["Patching + Software Distribution"]
    A --> E["Policies + Ring Rollout + Maintenance Windows"]
    A --> F["Jobs + Queue + Rollback"]
    A --> G["Compliance + CVE + SLA + Alerts"]
    A --> H["Monitoring + Reports + Audit"]
    A --> I["Testing Center + CI/CD + Git"]
    A --> J["Backup + Restore Drills + Agent Updates"]
    A --> K["Users + Roles + LDAP + Settings"]
    A --> L["License + Onboarding + Local / Mirror Repository"]
```

## 3. Patch-SecOps Solution Endpoint Onboarding And Lifecycle

```mermaid
flowchart TD
    A["Operator opens Onboarding page"] --> B["Choose Linux script or Windows installer"]
    B --> C["Set server URL + optional site/location"]
    C --> D["Install agent on endpoint"]
    D --> E["Agent registers with backend"]
    E --> F["Backend stores host identity"]
    E --> G["Backend stores site/location"]
    E --> H["Backend stores hardware baseline"]
    E --> I["Heartbeat starts"]
    I --> J["Host appears in Hosts page"]
    J --> K["Operator groups / tags / sites hosts"]
    K --> L["Host becomes eligible for jobs, policies, monitoring, reports"]
```

## 4. Patch And Software Distribution Workflow

```mermaid
flowchart TD
    A["Operator selects hosts / groups / site"] --> B["Choose patch or software action"]
    B --> C["Configure scope + schedule + reboot strategy"]
    C --> D["Optional safeguards:<br/>dry run, auto snapshot, auto rollback"]
    D --> E["Job created in backend"]
    E --> F["Job queue dispatches to agents"]
    F --> G["Agent runs package / patch action"]
    G --> H["Agent returns output + status"]
    H --> I["Jobs page updates"]
    H --> J["Audit trail updates"]
    H --> K["Compliance / reboot / CVE posture recalculates"]
    K --> L{"Failure?"}
    L -->|Yes| M["Rollback / follow-up remediation"]
    L -->|No| N["Fleet state improved"]
```

## 5. Monitoring, Testing, And Operational Assurance Flow

```mermaid
flowchart TD
    A["Managed hosts"] --> B["Agent metrics and service checks"]
    B --> C["Prometheus target discovery"]
    C --> D["Prometheus collects metrics"]
    D --> E["Grafana dashboards"]
    E --> F["Monitoring page in Patch-SecOps Solution"]

    G["Operator"] --> H["Testing Center"]
    H --> I["Frontend smoke checks"]
    H --> J["Backend health checks"]
    H --> K["External URL checks"]
    I --> L["Testing results stored and shown"]
    J --> L
    K --> L

    M["Reports module"] --> N["Compliance summary"]
    M --> O["Audit exports"]
    M --> P["Patch summary CSV / PDF"]

    F --> Q["Operational visibility"]
    L --> Q
    N --> Q
    O --> Q
    P --> Q
```

## 6. Governance, Access, And License Enforcement Flow

```mermaid
flowchart TD
    A["User login"] --> B["Local auth or LDAP / AD"]
    B --> C["Role + permission evaluation"]
    C --> D["Feature menu visibility"]
    C --> E["API permission checks"]

    F["License activation"] --> G["License status endpoint"]
    G --> H["Feature gate evaluation"]
    H --> D
    H --> E

    E --> I["User actions executed"]
    I --> J["Audit log written"]
    J --> K["Reports / forensic review / accountability"]
```

## 7. Vendor Tool Architecture

```mermaid
flowchart TD
    A["Vendor Admin (Argon2 Auth)"] --> B["Vendor UI Portal<br/>(Command Horizon)"]
    A --> C["generate-license.py CLI"]

    B --> D["Customer Management"]
    B --> E["Purchase Records"]
    B --> F["Plans + Tiers + Feature Bundles"]
    B --> G["License Issue / Regenerate / Revoke"]
    B --> H["Reports + Revenue Views"]

    D --> I[("PostgreSQL 17 Database<br/>(Vendor Target)")]
    E --> I
    F --> I
    G --> I
    H --> I

    B --> J["Signing Material Loader"]
    C --> J
    J --> K["LICENSE_SIGN_PRIVATE_KEY"]
    J --> L["LICENSE_ENCRYPT_PUBLIC_KEY"]
    K --> M["Generate signed and encrypted PM2 license"]
    L --> M
    M --> N["Customer delivery"]
```

## 8. Vendor Customer And License Lifecycle

```mermaid
flowchart TD
    A["Create customer"] --> B["Create purchase record"]
    B --> C["Choose plan / tier / features"]
    C --> D["Issue POC or testing license"]
    D --> E["Customer runs Patch-SecOps Solution POC or testing"]
    E --> F["Customer shares verified hardware or MAC ID"]
    F --> G["Vendor records binding ID and final terms"]
    G --> H["Generate final bound PM2 license"]
    H --> I["Customer activates final license in Patch-SecOps Solution"]
    I --> J["Support, renewal, reissue, and reporting continue"]
```

## 9. Build, Packaging, And Deployment Relationship

```mermaid
flowchart TD
    A["Run build-stable.sh"] --> B["Create product tarball"]
    A --> C["Create vendor tarball"]
    A --> D["Create product runtime license bundle"]
    A --> E["Create private authority bundle"]
    A --> F["Export developer folder"]

    B --> G["Patch-SecOps Solution server install"]
    C --> H["Vendor server install"]
    D --> I["Internal recovery copy only"]
    E --> J["Internal recovery copy only"]
    F --> K["Developer-only rebuild and test assets"]

    G --> L["Patch-SecOps Solution verifies and decrypts licenses"]
    H --> M["Vendor signs and encrypts licenses"]
    M --> L
```

## 10. Runtime Relationship Between Both Tools

```mermaid
flowchart LR
    A["Vendor Server"] --> B["Issue testing license or final PM2 license"]
    B --> C["Customer"]
    C --> D["Patch-SecOps Solution Server"]
    D --> E["Activate, verify, and decrypt locally"]

    F["Vendor portal database"] -. "no runtime dependency" .-> D
    D -. "no runtime dependency" .-> F
```

## 11. Security And Trust Boundary

```mermaid
flowchart TD
    A["Customer-safe product package"] --> B["Contains runtime verification and decryption bundle only"]
    C["Internal vendor tarball"] --> D["Contains private signing authority"]
    E["Internal dist/private files"] --> F["Recovery only"]
    B --> G["Patch-SecOps Solution can verify"]
    D --> H["Vendor can sign"]
    G --> I["Customer cannot mint new valid licenses"]
    H --> J["Signing remains limited to trusted vendor/operator side"]
```

## 12. Exact Usage Instructions

### Internal Build
1. From the repo root run `bash scripts/build-stable.sh`
2. Keep `dist/private/patchmaster-license-authority.env` private
3. Do not share files from `dist/private/` with customers

### Patch-SecOps Solution Server Install
1. Copy `dist/patchmaster-product-2.0.0.tar.gz` to the Patch-SecOps Solution server
2. Extract the tarball
3. Run `bash packaging/install-bare.sh --with-monitoring`
4. Let Patch-SecOps Solution install with the bundled runtime license bundle

### Vendor Server Install
1. Copy `vendor/dist/patchmaster-vendor-2.0.0.tar.gz` to the Vendor server
2. Extract the tarball
3. Run `bash install-vendor.sh`
4. Let Vendor install with the bundled private authority

### After Both Installs
1. Issue a testing license first if you need the customer hardware or MAC ID for final binding
2. Record the verified hardware or MAC ID in the Vendor portal
3. Generate the final `PM2-...` license from the Vendor tool
4. Paste that final `PM2-...` key into Patch-SecOps Solution

### Important Rules
- Patch-SecOps Solution and Vendor must share the same license authority set
- customers should receive only customer-safe product artifacts
- the private authority must stay only with your trusted operator/vendor side
- Vendor and Patch-SecOps Solution are standalone after install, but trust must come from aligned license authority material
- Patch-SecOps Solution license verification is local; Vendor public internet exposure is not required
