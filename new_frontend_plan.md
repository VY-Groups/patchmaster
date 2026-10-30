# MASTER PROMPT — PATCH-SECOPS PREMIUM SAAS UI/UX, ANIMATIONS & FRONTEND ENGINEERING

## 1. Your Role

Act as a Principal Product Designer, Senior Frontend Architect, Motion Designer, and Enterprise SaaS Engineer.

Your mission is to transform the existing Patch-SecOps application into a polished, premium, production-ready enterprise security SaaS platform.

You must study the attached reference video carefully and recreate its visual language, animations, transitions, timing, and interaction patterns as closely as practical.

This is not a request to create a static mockup. Build a real, interactive frontend that integrates with the existing application.

**Primary objective:** Match the reference video's UI/UX and animation experience while adapting every screen, component, and workflow to Patch-SecOps.

Do not begin by replacing the application or generating an isolated demo. First understand the existing codebase.

---

## 2. Mandatory Discovery Phase

Before writing or modifying code, inspect the complete relevant project structure.

Identify:

- Frontend framework and version.
- Routing and page layout architecture.
- Existing component library and design system.
- CSS strategy, styling conventions, and available animation libraries.
- Backend APIs, authentication, session handling, and authorization.
- Existing dashboard, asset inventory, patching, vulnerability, and job-management modules.
- Existing light/dark theme implementation.
- Data fetching, caching, state management, and loading states.
- Existing tests, linting, formatting, and build commands.
- Current responsive behavior and accessibility implementation.

Inspect the reference video frame by frame where possible.

Identify the following from the actual reference rather than guessing:

1. Sidebar layout and navigation behavior.
2. Page transition patterns.
3. Card entrance animations and stagger timing.
4. Chart and counter animations.
5. Hover, focus, dropdown, and button interactions.
6. Light-to-dark and dark-to-light theme transitions.
7. Any circular reveal, expanding overlay, or other theme-switch animation.
8. Animation duration, easing, delays, direction, and movement distance.
9. How persistent navigation behaves during page transitions.
10. Which elements remain static and which elements animate.

If the video does not clearly demonstrate an interaction, use a restrained, consistent design decision rather than inventing elaborate motion.

After discovery, present a concise architecture assessment and implementation plan. Then proceed with implementation in the available working environment. Do not stop at a plan if you have the tools and permission to modify the project.

---

## 3. Design Direction

Create a clean, premium, modern enterprise SaaS interface.

### Visual characteristics

- Minimal, uncluttered composition.
- White and warm off-white surfaces in light mode.
- Deep neutral surfaces in dark mode.
- Restrained sage-green or muted green accents, inspired by the reference.
- Clear typography and strong information hierarchy.
- Consistent spacing, rounded corners, subtle borders, and restrained shadows.
- Carefully aligned cards, tables, charts, and navigation.
- Elegant status indicators and compact metadata.
- Subtle depth and layering without excessive glassmorphism.
- Consistent iconography.
- Smooth transitions without visual clutter.

Use the reference video as the visual source of truth for styling and motion. Do not substitute an unrelated dashboard template.

Do not copy another product's logo, branding, proprietary illustrations, or product-specific content. Recreate the design principles and motion language using Patch-SecOps branding.

### Design tokens

Create or consolidate a reusable design token system for:

- Colors and semantic status colors.
- Typography and font weights.
- Spacing.
- Border radii.
- Shadows.
- Borders and dividers.
- Sidebar and header dimensions.
- Component heights.
- Z-index layers.
- Animation durations and easing curves.
- Light and dark themes.

Avoid scattered, inconsistent styling values throughout the codebase.

---

## 4. Animation and Motion System — Highest Priority

The animation experience is a core requirement, not a decorative afterthought.

Study the attached video and reproduce its actual motion patterns as closely as practical.

### A. Page transitions

Implement smooth transitions when navigating between application pages.

Depending on what the reference demonstrates:

- Fade content in and out.
- Apply subtle horizontal or vertical movement.
- Use short, restrained enter and exit transitions.
- Maintain visual continuity between related pages.
- Keep the persistent sidebar and top navigation stable where appropriate.
- Avoid unnecessarily remounting the entire application shell.

Coordinate animations with the routing system so that transitions do not produce flicker, blank screens, duplicate content, or broken navigation.

### B. Dashboard entrance animations

For dashboard elements, reproduce the reference's entrance behavior:

- Metric cards appear with subtle opacity and position changes.
- Cards animate with a small, consistent stagger where appropriate.
- Charts render smoothly when first displayed.
- Progress indicators animate toward their actual values.
- Numeric counters animate only when appropriate.
- Supporting labels and metadata appear in a controlled sequence if the reference uses staggered motion.

Do not make the dashboard replay every entrance animation whenever an unrelated state changes.

Do not animate numbers in a way that misrepresents security metrics or implies an improvement that did not occur.

### C. Theme-switch animation

Treat theme switching as one of the most important visual interactions.

Reproduce the actual theme-switch effect shown in the reference video.

If the reference uses a circular reveal or expanding mask:

- Implement a comparable origin-aware reveal effect.
- Use the theme-toggle location as the origin when technically supported.
- Transition surfaces, text, borders, shadows, charts, navigation, and overlays consistently.
- Avoid flashing white screens, incorrect intermediate colors, and mismatched components.
- Ensure the theme change remains functional if the animation API is unavailable.

If the reference instead uses a crossfade or another transition, reproduce that behavior rather than substituting a different effect.

Requirements:

- Light and dark themes must both be fully styled.
- Theme preference must persist across navigation and reloads.
- Respect system theme preferences when no user preference is saved.
- Prevent a visible theme flash during initial rendering.
- Support keyboard access to the theme toggle.
- Respect `prefers-reduced-motion`.

### D. Hover and micro-interactions

Create consistent, restrained feedback for:

- Sidebar items.
- Buttons and icon buttons.
- Dashboard cards.
- Table rows.
- Tabs and filter chips.
- Dropdowns and popovers.
- Dialogs and confirmation panels.
- Tooltips.
- Status indicators where animation is meaningful.

Use subtle transitions for opacity, color, background, border, and small positional changes.

Avoid exaggerated bouncing, spinning, elastic movement, unnecessary parallax, or constant pulsing.

### E. Timing and easing

Derive motion timing from the reference video wherever possible.

Create reusable motion tokens rather than assigning unrelated durations to every component.

Animations should feel coordinated, intentional, and premium.

Prefer GPU-friendly properties such as opacity and transform. Avoid expensive animations that repeatedly trigger layout or paint.

Use CSS transitions, CSS animations, the Web Animations API, or an existing animation library according to the current project's architecture. Do not add a new dependency without a clear reason.

### F. Reduced-motion behavior

When the user prefers reduced motion:

- Remove unnecessary movement.
- Disable or simplify elaborate reveal animations.
- Preserve visual feedback and clear state changes.
- Avoid hiding content behind animations.
- Keep all functionality available.

### G. Performance

- Avoid layout shifts.
- Avoid animating large, expensive surfaces unnecessarily.
- Do not block navigation or data loading until animations finish.
- Cancel or clean up animations when components unmount.
- Handle rapid repeated theme switches safely.
- Ensure animations do not interfere with forms, dropdowns, keyboard navigation, or API requests.

---

## 5. Patch-SecOps Application Shell

Build or refine a reusable application shell consisting of:

### Sidebar

- Patch-SecOps logo and product name.
- Overview.
- Assets.
- Patch Management.
- Vulnerabilities.
- Jobs and Schedules.
- Compliance.
- Reports.
- Integrations.
- Credentials.
- Audit Logs.
- Administration and Settings.

Organize sections into logical groups.

Use clear active, hover, focus, expanded, and collapsed states.

Support a compact sidebar if consistent with the reference and useful for the existing application.

### Top navigation

Include appropriate existing or planned controls for:

- Current page title and breadcrumbs.
- Global search.
- Tenant or workspace selection.
- Notifications.
- Help.
- Light/dark theme switch.
- User profile and account menu.

Do not display controls as functional if they have no real implementation. Connect each implemented control to the existing routing, state, or backend behavior.

### Main content

Use a consistent content grid with responsive widths, predictable spacing, and suitable maximum content widths.

Maintain alignment between page headings, action buttons, filters, cards, and data tables.

---

## 6. Product Pages and Functional Requirements

### A. Security Overview

Create a dashboard with meaningful security and infrastructure metrics, such as:

- Total managed assets.
- Online and offline assets.
- Patch compliance percentage.
- Pending critical patches.
- Open vulnerability findings.
- Failed jobs.
- Agent health.
- Recent security and patch activity.
- Patch compliance trends.
- Recent remediation activity.

Use the reference's card and chart styling.

Metrics must come from real backend data when available. Use clearly identified fixtures or demo data only during development.

Do not fabricate live security status or imply that an operation succeeded when it has not.

### B. Asset Inventory

Provide a searchable, filterable inventory of Windows and Linux assets.

Useful fields include:

- Hostname.
- Operating system and version.
- IP address where authorized.
- Tenant and site/group.
- Agent or agentless management mode.
- Last check-in.
- Connection status.
- Patch compliance.
- Outstanding critical findings.

Support sorting, pagination, filters, row actions, bulk selection where authorized, and an asset details view.

### C. Asset Details and Diagnostics

Provide an asset detail page with sections or tabs for:

- Overview.
- System inventory.
- Installed software.
- Patch status.
- Vulnerabilities.
- Agent health.
- Connection diagnostics.
- Recent jobs.
- Audit history.

For agentless assets, distinguish network connectivity, authentication, remote command execution, and inventory collection as separate diagnostic stages.

### D. Patch Management

Provide:

- Available and missing patches.
- Severity and urgency indicators.
- Patch applicability.
- Target asset groups.
- Deployment scheduling.
- Job progress.
- Reboot requirements.
- Failure details.
- Rollback or recovery information where supported.

Require appropriate authorization and confirmation for disruptive actions.

### E. Vulnerability Management

Provide:

- Finding severity.
- Affected assets.
- Vulnerability identifiers where available.
- Remediation recommendations.
- Patch or remediation status.
- Filters and sorting.
- Links to related assets and jobs.

Avoid implying that a vulnerability has been fixed before verification.

### F. Jobs and Schedules

Provide a consistent job lifecycle:

- Queued.
- Running.
- Succeeded.
- Failed.
- Cancelled.
- Timed out.

Show target, action, start time, duration, progress where meaningful, sanitized errors, and relevant logs.

Support job details, scheduling, retries, and cancellation only where the backend permits them.

### G. Credentials and Connections

Provide a secure interface for managing credential profiles and testing connections.

Support the application's actual authentication methods, including applicable local Windows accounts, domain accounts, and SSH credentials.

Requirements:

- Never display stored passwords or private keys.
- Never expose secrets in logs, browser storage, URLs, or API responses.
- Use backend-managed encrypted secret storage.
- Apply tenant and role authorization.
- Show clear connection-test outcomes.
- Distinguish unreachable hosts from authentication failures and remote execution failures.

Do not store secrets in frontend configuration files or hardcode credentials.

### H. Administration, Reports, and Audit

Use the same design system for:

- Tenant and organization settings.
- User and role administration.
- Audit logs.
- Integrations.
- Compliance reports.
- Export workflows.
- Subscription and usage screens if supported by the existing product roadmap.

Do not invent backend capabilities merely to fill a page.

---

## 7. SaaS Security and Multi-Tenancy

Patch-SecOps is an enterprise security product. UI polish must never weaken security.

Enforce the following:

- Tenant-scoped asset and job access.
- Role-based authorization.
- Server-side permission checks.
- Secure authentication and session handling.
- Backend validation of all submitted operations.
- Safe rendering of untrusted data.
- Sanitized error messages.
- Auditability of sensitive operations.
- Appropriate confirmation for high-impact actions.

A hidden button is not an authorization mechanism.

Never trust a tenant ID, asset ID, role, or permission merely because it came from frontend state.

Do not expose secrets, authentication tokens, private keys, or sensitive environment variables to client-side code.

---

## 8. Technical Implementation Rules

1. Preserve the existing framework and architecture unless a change is demonstrably necessary.
2. Reuse existing components, API clients, routes, and authentication logic.
3. Build reusable components for cards, buttons, tables, badges, charts, modals, dropdowns, filters, and page headers.
4. Separate presentation from business logic.
5. Use existing API contracts rather than inventing endpoints.
6. Preserve working agent-based and agentless workflows.
7. Do not replace real backend data with hardcoded demo data.
8. Do not remove existing features simply because they are not visible in the reference.
9. Avoid unnecessary dependencies and major framework migrations.
10. Keep the code readable, typed where the current stack supports typing, and maintainable.
11. Use semantic HTML and accessible interaction patterns.
12. Implement appropriate loading, empty, error, success, and permission-denied states.
13. Keep responsive behavior consistent across the application.
14. Do not suppress errors merely to make the interface appear successful.
15. Never claim a feature is complete without testing it.

If a referenced page does not yet have a backend API, create a clearly defined integration boundary and a development-only mock where appropriate. Make the mock status explicit.

---

## 9. Responsive Design

Ensure the interface works well on:

- Desktop monitors.
- Standard laptops.
- Smaller laptop screens.
- Tablets.

Adapt the sidebar, card grid, tables, dialogs, and navigation to available width.

Avoid horizontal page overflow, clipped controls, inaccessible dropdowns, and unreadable data tables.

Preserve the reference's visual hierarchy as the layout adapts.

Mobile support should be considered where useful, but do not sacrifice the efficiency of the primary desktop administration workflow.

---

## 10. Accessibility

Implement:

- Keyboard navigation.
- Visible focus states.
- Correct semantic elements.
- Accessible labels for icon-only buttons.
- Sufficient contrast in both themes.
- Accessible dialogs and menus.
- Screen-reader-friendly status messages.
- Reduced-motion support.
- Clear error and validation messaging.

Animations must not be the only way to communicate state changes.

---

## 11. Testing and Validation

Before declaring the implementation complete, test the actual application.

### Visual validation

Compare the implementation with the reference video.

Review:

- Layout proportions.
- Sidebar and header behavior.
- Card dimensions and spacing.
- Typography.
- Colors and contrast.
- Border radii and shadows.
- Page transitions.
- Theme-switch animation.
- Chart and counter behavior.
- Hover interactions.

Where possible, capture screenshots and compare equivalent application states.

### Functional validation

Verify:

- All implemented routes.
- Active navigation states.
- Theme persistence.
- Light and dark theme rendering.
- Search and filters.
- Tables and pagination.
- Dialogs and dropdowns.
- Forms and validation.
- API error handling.
- Loading and empty states.
- Tenant and role boundaries.
- Existing authentication.
- Existing agent and agentless workflows.

### Motion validation

Verify:

- Animations play at the intended times.
- Navigation does not flicker.
- Rapid interactions do not break the UI.
- No unnecessary entrance-animation replay occurs.
- Theme switching works during ongoing transitions.
- Reduced-motion settings are respected.
- Content remains usable if animation fails.

### Engineering validation

Run the project's available:

- Build.
- Type checks.
- Lint.
- Unit tests.
- Relevant integration tests.

Report actual results. Do not claim a test passed if it was not run.

---

## 12. Execution Workflow

Work in the following sequence.

### Phase 1 — Inspect

Study the reference video and inspect the existing repository.

Identify the current stack, reusable components, routes, backend contracts, and implementation risks.

### Phase 2 — Plan

Produce a concise plan that identifies:

- Existing functionality to preserve.
- Components to reuse.
- Components to improve.
- Animation implementation approach.
- Required changes to theme and routing.
- Testing strategy.

### Phase 3 — Establish the design system

Implement or consolidate design tokens, theme variables, typography, spacing, reusable components, and motion conventions.

### Phase 4 — Implement the application shell

Build or refine the sidebar, top navigation, content container, theme toggle, and shared transitions.

### Phase 5 — Implement key pages

Prioritize:

1. Security Overview.
2. Asset Inventory.
3. Asset Details and Diagnostics.
4. Patch Management.
5. Vulnerabilities.
6. Jobs and Schedules.
7. Credentials and Integrations.
8. Reports, Audit Logs, and Administration.

Reuse the same design system throughout.

### Phase 6 — Integrate and test

Connect existing APIs, preserve business logic, validate permissions, test animations, and run the available engineering checks.

### Phase 7 — Final review

Provide a summary of:

- Files changed.
- Components created or reused.
- Animations implemented.
- Pages completed.
- Backend integrations.
- Tests actually executed.
- Known limitations.
- Remaining work.

Do not declare the entire product complete if only the dashboard has been implemented.

---

## 13. Definition of Done

The implementation is complete only when:

- The application has a cohesive premium Patch-SecOps design.
- The reference video's visual and motion language is reproduced as closely as practical.
- The actual theme-switch animation is implemented.
- Navigation, cards, charts, and micro-interactions behave consistently.
- Light and dark themes work throughout the implemented pages.
- The frontend remains responsive and accessible.
- Existing backend and authentication functionality are preserved.
- Tenant boundaries and sensitive operations remain secure.
- Real data is used where available, and demo data is clearly labelled.
- Relevant build and test checks have been executed and their results reported.
- No critical interaction is merely decorative or falsely reports success.

## Final Instruction

Prioritize fidelity to the attached reference video's design and animation over generic dashboard conventions.

Do not produce a static-only prototype. Do not redesign the product into an unrelated visual style. Do not rewrite working systems unnecessarily.

Inspect first, plan intelligently, implement incrementally, validate visually and functionally, and report honestly.

**The desired result is a premium, production-oriented Patch-SecOps SaaS interface with the same overall visual character, transition quality, animation rhythm, and theme-switch experience as the supplied reference video.**