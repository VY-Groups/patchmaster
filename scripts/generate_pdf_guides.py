from pathlib import Path
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable,
    Preformatted,
)

ROOT = Path(r"C:\Users\test\Desktop\pat-1")
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)
TODAY = date(2026, 3, 22).strftime("%d %b %Y")
VERSION = "2.0.0"

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="GuideTitle",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=24,
    leading=28,
    textColor=colors.HexColor("#16213e"),
    alignment=TA_CENTER,
    spaceAfter=10,
))
styles.add(ParagraphStyle(
    name="GuideSubtitle",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=11,
    leading=15,
    textColor=colors.HexColor("#334155"),
    alignment=TA_CENTER,
    spaceAfter=14,
))
styles.add(ParagraphStyle(
    name="H1PM",
    parent=styles["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=17,
    leading=22,
    textColor=colors.HexColor("#0f172a"),
    spaceAfter=8,
    spaceBefore=8,
))
styles.add(ParagraphStyle(
    name="H2PM",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=16,
    textColor=colors.HexColor("#1d4ed8"),
    spaceAfter=6,
    spaceBefore=6,
))
styles.add(ParagraphStyle(
    name="BodyPM",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=10,
    leading=14,
    textColor=colors.HexColor("#1f2937"),
    spaceAfter=5,
))
styles.add(ParagraphStyle(
    name="BulletPM",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=10,
    leading=14,
    leftIndent=14,
    firstLineIndent=-8,
    bulletIndent=0,
    textColor=colors.HexColor("#1f2937"),
    spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="MutedPM",
    parent=styles["BodyText"],
    fontName="Helvetica-Oblique",
    fontSize=9,
    leading=12,
    textColor=colors.HexColor("#475569"),
    spaceAfter=4,
))
styles.add(ParagraphStyle(
    name="CalloutPM",
    parent=styles["BodyText"],
    fontName="Helvetica-Bold",
    fontSize=10,
    leading=14,
    textColor=colors.HexColor("#7c2d12"),
    backColor=colors.HexColor("#fff7ed"),
    borderPadding=8,
    borderColor=colors.HexColor("#fdba74"),
    borderWidth=0.5,
    borderRadius=3,
    spaceAfter=8,
))
styles.add(ParagraphStyle(
    name="CodePM",
    parent=styles["Code"],
    fontName="Courier",
    fontSize=8.5,
    leading=11,
    backColor=colors.HexColor("#f8fafc"),
    borderPadding=7,
    borderColor=colors.HexColor("#cbd5e1"),
    borderWidth=0.5,
    leftIndent=6,
    rightIndent=6,
    spaceAfter=8,
))


def p(text, style="BodyPM"):
    return Paragraph(escape(text).replace("\n", "<br/>"), styles[style])


def bullet(text):
    return Paragraph(escape(text), styles["BulletPM"], bulletText="- ")


def code_block(text):
    return Preformatted(text.strip(), styles["CodePM"])


def section(title, body=None, bullets=None, code=None, note=None):
    story = [Paragraph(escape(title), styles["H1PM"])]
    if body:
        if isinstance(body, str):
            body = [body]
        for para in body:
            story.append(p(para))
    if bullets:
        for item in bullets:
            story.append(bullet(item))
    if note:
        story.append(Paragraph(escape(note), styles["CalloutPM"]))
    if code:
        story.append(code_block(code))
    story.append(Spacer(1, 4))
    return story


def subheading(title):
    return Paragraph(escape(title), styles["H2PM"])


def make_table(rows, col_widths=None):
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def add_cover(story, title, audience, purpose, capability_blurb=None):
    story.extend([
        Spacer(1, 28),
        Paragraph("Patch-SecOps Solution by VYGROUP", styles["GuideTitle"]),
        Paragraph(escape(title), styles["GuideTitle"]),
        Paragraph(escape(f"Audience: {audience}"), styles["GuideSubtitle"]),
        Paragraph(escape(f"Prepared on {TODAY} | Product version {VERSION}"), styles["GuideSubtitle"]),
        HRFlowable(width="70%", color=colors.HexColor("#93c5fd"), thickness=1.5, spaceBefore=8, spaceAfter=12),
        p(purpose, "BodyPM"),
    ])
    if capability_blurb:
        story.append(Paragraph(escape(capability_blurb), styles["CalloutPM"]))
    story.extend([
        Spacer(1, 16),
        p("This guide was generated from the current repository, the internal SOP set, and the monitoring fixes validated during release hardening."),
        PageBreak(),
    ])


def draw_header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(colors.HexColor("#16213e"))
    canvas.rect(0, height - 20 * mm, width, 20 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(18 * mm, height - 12 * mm, doc.title)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(18 * mm, 10 * mm, f"Patch-SecOps Solution by VYGROUP | {TODAY}")
    canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def developer_story():
    story = []
    add_cover(
        story,
        "Developer and Release Guide",
        "Backend, Frontend, DevOps, QA, Release Engineering",
        "This guide explains how Patch-SecOps Solution is structured, how the release is built and validated, what was fixed during monitoring hardening, and what must be checked before a vendor rebuild is promoted.",
        "Launch recommendation: ready for a controlled vendor rebuild and UAT, but still do one fresh-VM acceptance pass before public release.",
    )

    story.extend(section(
        "1. Executive Launch Readiness",
        body=[
            "The repository is in a much stronger state than it was at the start of the monitoring investigation. Backend tests pass, the frontend builds successfully, and the major Grafana/Prometheus provisioning, embed, and datasource issues have been corrected in code.",
            "Based on the evidence gathered so far, Patch-SecOps Solution is ready for a vendor rebuild and final acceptance testing. I would treat it as launch-candidate ready, not blindly public-ready, until the rebuilt artifact is installed on a fresh target and the release checklist below is completed end to end."
        ],
        bullets=[
            "Validated in this workspace: backend test suite passed (30 tests).",
            "Validated in this workspace: production frontend build completed successfully.",
            "Validated on a live bare-metal server: backend, Prometheus, and Grafana all returned healthy responses.",
            "Validated on a live bare-metal server: Grafana dashboards now bind to the intended datasource and the Prometheus datasource URL now uses the prefixed API path.",
            "Not yet fully re-proven in this turn: a completely fresh vendor/customer release tarball installed from scratch after these last datasource URL changes."
        ],
        note="Recommended go/no-go call: GO for vendor rebuild, then run one clean install/UAT cycle before external launch."
    ))

    story.extend(section(
        "2. Product Architecture",
        body="Patch-SecOps Solution ships as a mixed control plane: a FastAPI backend, React frontend, PostgreSQL database, Python-based agents, and an integrated Prometheus/Grafana monitoring stack. The user-facing product and the internal vendor tooling share the repository but are packaged separately."
    ))
    story.append(make_table([
        ["Layer", "Location", "Role"],
        ["Backend API", "backend/", "Auth, jobs, licensing, metrics, agent coordination"],
        ["Frontend UI", "frontend/", "Operator dashboards, workflows, monitoring embeds"],
        ["Agent", "agent/", "Host-side execution for patching, snapshots, software actions"],
        ["Monitoring", "monitoring/", "Grafana dashboards, Prometheus config, provisioning"],
        ["Installers", "packaging/ and scripts/", "Bare-metal and scripted deployment"],
        ["Vendor tooling", "vendor/", "License/customer management, internal operations"],
    ], [36*mm, 44*mm, 90*mm]))
    story.append(Spacer(1, 10))

    story.extend(section(
        "3. Monitoring Fixes Included In This Release Candidate",
        body="The most important release-hardening work in this cycle centered on monitoring. The issues were not in Chromium; they were in service restart handling, datasource provisioning, proxy rewriting, and dashboard datasource selection.",
        bullets=[
            "Grafana restart handling was made safer so service restarts no longer leave the unit in a failed state after a clean SIGTERM.",
            "Provisioning now normalizes Grafana datasources so only one datasource remains default, avoiding startup failure from multiple default datasources.",
            "The monitoring proxy strips the backend token before forwarding upstream and rewrites embed redirects correctly.",
            "Dashboards are now pinned to a stable datasource UID, patchmaster-prometheus, so Grafana stops drifting onto the wrong datasource and showing misleading A-series/demo-like data.",
            "The Grafana datasource now points to the actual prefixed Prometheus endpoint used by this deployment style, which resolves the 404s seen in Host Details panels."
        ],
        note="Root cause summary: the final blocker was datasource/config drift, not browser engine behavior."
    ))

    story.extend(section(
        "4. Build and Release Workflow",
        body="Use the stable build flow from WSL or Linux where possible. Keep the product and vendor artifacts separate and treat the final tarballs as immutable release candidates once checks pass.",
        code=r'''cd /mnt/c/Users/test/Desktop/pat-1
sudo ./scripts/build-stable.sh

# Primary customer artifact
C:\Users\test\Desktop\pat-1\dist\patchmaster-product-2.0.0.tar.gz

# Internal docs / vendor artifacts are packaged separately'''
    ))

    story.append(subheading("Recommended release gates"))
    for item in [
        "Backend tests: python -m pytest tests -q (from backend/).",
        "Frontend build: cmd /c npm run build (from frontend/).",
        "Fresh install on a clean VM with a real license and monitoring enabled.",
        "Login, license upload, monitoring cards, Grafana embed, Prometheus embed, and at least one agent onboarding check.",
        "One patch-job dry run plus one successful test workflow from Testing Center."
    ]:
        story.append(bullet(item))
    story.append(Spacer(1, 8))

    story.extend(section(
        "5. Developer Workflow",
        body=[
            "Work backend-first for service, auth, licensing, and monitoring behavior. Keep blocking I/O out of request handlers and preserve the async contract used across the FastAPI backend.",
            "For frontend changes, prefer same-origin URLs for deployed systems. The monitoring page already does this in MonitoringOpsPage to avoid cross-origin and direct-port surprises in customer environments."
        ],
        bullets=[
            "Backend health and monitoring proxy: backend/api/monitoring.py",
            "Monitoring orchestration: backend/scripts/monitoring-ctl.sh",
            "Bare-metal installer: packaging/install-bare.sh",
            "Server install helper: scripts/install_patchmaster_server.sh",
            "Customer-facing monitoring UI: frontend/src/MonitoringOpsPage.jsx",
            "Grafana dashboards: monitoring/grafana/dashboards/*.json"
        ]
    ))

    story.extend(section(
        "6. Pre-Launch Checklist",
        bullets=[
            "Rebuild the product artifact from the updated repository.",
            "Install the rebuilt artifact on a clean target, not an already-hotfixed server.",
            "Confirm admin login, license activation, and backend health.",
            "Confirm Grafana and Prometheus stay healthy after install and after a backend restart.",
            "Confirm Host Details no longer returns datasource 404 errors.",
            "Confirm dashboards show no data or zero data correctly when no agents are enrolled.",
            "Confirm at least one Linux and one Windows onboarding path are still valid for the intended release tier.",
            "Archive the release checksum, release notes, and known issues for support handoff."
        ],
        note="If any clean-install step needs manual sed/cp hotfixing, stop the launch and bake that change back into the artifact first."
    ))

    story.extend(section(
        "7. Known Residual Risks",
        bullets=[
            "Customer environments with large time drift can still make dashboard time ranges look confusing until clocks are corrected.",
            "Fresh systems with no agents will legitimately show no data in several dashboards; that is healthy behavior and should be documented for support and end users.",
            "The monitoring stack is now working in the validated bare-metal path, but every public release should still be acceptance-tested from a fresh package, not just from repo hotfixes."
        ]
    ))

    story.extend(section(
        "8. Recommended Decision",
        body=[
            "For a vendor rebuild, yes: this is in good enough shape to proceed. The issues we just debugged have concrete fixes in code and the critical server-side behaviors are verified.",
            "For a broad external launch, I recommend one final clean-install acceptance cycle and a short release note describing the monitoring improvements. That gives the vendor team a confident, supportable launch rather than a hopeful one."
        ]
    ))

    return story


def support_story():
    story = []
    add_cover(
        story,
        "Support Runbook",
        "L1, L2, L3, and L4 support teams",
        "This guide gives each support tier a clear operating lane, standard diagnostics, escalation rules, and known-good remediation patterns for Patch-SecOps Solution deployments.",
        "Use this as the day-to-day incident playbook. It is designed to reduce bounce between tiers and make evidence handoff cleaner.",
    )

    story.extend(section(
        "1. Tier Responsibilities",
        body="The goal is to stop avoidable escalations. L1 stabilizes and triages, L2 diagnoses environment and workflow issues, L3 handles deeper service/config/database problems, and L4 owns code-level defects and release-grade fixes."
    ))
    story.append(make_table([
        ["Tier", "Primary focus", "Escalate when"],
        ["L1", "Basic health, login, UI guidance", "Repeatable failure or service unhealthy"],
        ["L2", "Install, license, agent, monitoring checks", "Config drift or log-backed failure"],
        ["L3", "DB, proxy, service internals, recovery", "Code or packaging change needed"],
        ["L4", "Engineering reproduction and release fix", "Source patch and rebuild required"],
    ], [18*mm, 66*mm, 90*mm]))
    story.append(Spacer(1, 10))

    story.extend(section(
        "2. L1 Triage Flow",
        bullets=[
            "Confirm product URL, user impact, environment, and exact version.",
            "Check backend health: curl -fsS http://127.0.0.1:8000/api/health",
            "Check frontend reachability in browser and verify whether the issue affects all users or one workflow.",
            "Capture screenshots, exact error text, and time of incident.",
            "If service-level health is bad, escalate to L2 immediately with outputs attached."
        ],
        code='''curl -fsS http://127.0.0.1:8000/api/health
echo
sudo systemctl status patchmaster-backend --no-pager
sudo systemctl status nginx --no-pager'''
    ))

    story.extend(section(
        "3. L2 Operational Checks",
        bullets=[
            "Validate license status and enabled features before treating a locked feature as a defect.",
            "For monitoring issues, compare /api/monitoring/status and /api/monitoring/health rather than relying only on the UI card state.",
            "Validate Prometheus and Grafana local health independently.",
            "Check whether the issue is no-data, stale data, service down, or authentication/redirect behavior."
        ],
        code='''curl -fsS http://127.0.0.1:8000/api/license/status
echo
curl -fsS http://127.0.0.1:8000/api/monitoring/status
echo
curl -fsS http://127.0.0.1:8000/api/monitoring/health
echo
curl -fsS http://127.0.0.1:3001/api/health
echo
curl -fsS http://127.0.0.1:9090/api/monitoring/embed/prometheus/-/healthy'''
    ))

    story.extend(section(
        "4. L3 Deep-Dive Patterns",
        body="The last release-hardening cycle exposed the patterns below. They are useful examples for future support cases.",
        bullets=[
            "Grafana service restarts can look like crashes even when the root cause is systemd state handling or datasource provisioning.",
            "A 404 inside Grafana panels can mean the datasource URL is wrong, even when Grafana itself is healthy.",
            "Misleading A-series or demo-like values often indicate the dashboard is using the wrong datasource, not real customer data.",
            "When Prometheus history was wiped and live queries returned empty vectors, stale dashboard visuals were proven to be dashboard/datasource issues instead of live backend metrics."
        ],
        code='''sudo journalctl -u grafana-server -n 80 --no-pager -l
sudo grep -R -n "isDefault" /etc/grafana/provisioning/datasources
curl -u admin:$GF_ADMIN_PASSWORD -s http://127.0.0.1:3001/api/dashboards/uid/patchmaster-overview
echo
curl -g 'http://127.0.0.1:9090/api/monitoring/embed/prometheus/api/v1/query?query=patchmaster_hosts_total' '''
    ))

    story.extend(section(
        "5. L4 Engineering Escalation Package",
        bullets=[
            "Exact version/build checksum and install path.",
            "Fresh reproduction steps, not only screenshots.",
            "systemctl status plus journal output for failing services.",
            "Relevant config or provisioning files with sanitized secrets.",
            "Expected result, actual result, and whether the issue reproduces on a clean install."
        ],
        note="L4 should only receive cases that already include evidence. If a ticket says only 'does not work', send it back for L1/L2 completion."
    ))

    story.extend(section(
        "6. Common Support Scenarios",
        body="Use the table below as the short answer key when triaging day-to-day tickets."
    ))
    story.append(make_table([
        ["Symptom", "Likely cause", "Primary owner"],
        ["Monitoring cards show stopped but services are active", "UI/backend status sync or stale health logic", "L2/L3"],
        ["Grafana embed loops", "Monitoring proxy redirect or upstream path rewrite issue", "L3/L4"],
        ["Grafana panels show 404 page not found", "Datasource URL points at wrong Prometheus path", "L3"],
        ["No data in monitoring", "No enrolled agents or no live metrics yet", "L1/L2"],
        ["License blocks monitoring", "Monitoring feature absent or invalid license state", "L2"],
        ["Agent offline", "Connectivity, time skew, token, or service issue", "L1/L2"],
    ], [52*mm, 74*mm, 40*mm]))
    story.append(Spacer(1, 10))

    story.extend(section(
        "7. Handoff Rules",
        bullets=[
            "L1 to L2: include user impact, exact error, health output, service status, and screenshots.",
            "L2 to L3: include config, logs, API outputs, and what was already attempted.",
            "L3 to L4: include root-cause hypothesis, reproduction steps, and the reason a code or packaging change is required."
        ]
    ))

    story.extend(section(
        "8. Operational Truths To Communicate Clearly",
        bullets=[
            "Healthy services with no agents can legitimately show no data.",
            "Monitoring dashboards depend on license state, service state, datasource state, and actual metric presence.",
            "A browser symptom is not automatically a browser bug; in this cycle, Chromium was not the root cause."
        ]
    ))
    return story


def consumer_story():
    story = []
    add_cover(
        story,
        "Customer User Guide",
        "System administrators, DevOps teams, IT operations, security teams",
        "This guide explains how to operate Patch-SecOps Solution in day-to-day use, what the platform is good at, and what to expect from major workflows such as onboarding, patching, monitoring, reporting, and rollback.",
        "Capability brief: Patch-SecOps Solution centralizes Linux and Windows patching, software rollout, compliance reporting, monitoring, backups, and offline-ready operations from a single control plane.",
    )

    story.extend(section(
        "1. What Patch-SecOps Solution Can Do",
        bullets=[
            "Manage Linux and Windows patching from one dashboard.",
            "Group hosts and execute jobs in bulk or by maintenance window.",
            "Track compliance, CVEs, audit activity, and reboot requirements.",
            "Install or remove software across many hosts.",
            "Provide integrated Prometheus and Grafana views for operational visibility.",
            "Support offline and air-gapped workflows through the master node.",
            "Create backups, snapshots, and rollbacks around risky changes."
        ],
        note="Very brief capability summary: Patch-SecOps Solution is strongest as an operator-facing patch and systems operations hub, not just a patch button."
    ))

    story.extend(section(
        "2. First Use Checklist",
        bullets=[
            "Log in to the Patch-SecOps Solution web UI using the admin or delegated operator account.",
            "Upload and validate the license so the correct features appear.",
            "Open Onboarding and copy the platform-appropriate install command for your hosts.",
            "Wait for hosts to appear in the inventory before expecting dashboards to show real data.",
            "Create at least one host group such as Production, Staging, or Development."
        ]
    ))

    story.extend(section(
        "3. Daily Operating Workflow",
        body="A good day-to-day rhythm is: review inventory, check pending updates, decide whether the job is dry-run or live, execute inside an approved window, then review results and reboots.",
        bullets=[
            "Hosts: confirm online/offline state, upgradable package count, and compliance posture.",
            "Patch jobs: use dry run for risky estates and live patching for approved windows.",
            "Post-job review: confirm success, inspect failure logs, and schedule reboots where needed.",
            "Reports: export CVE or compliance outputs for audit or management review."
        ]
    ))

    story.extend(section(
        "4. Monitoring Expectations",
        body=[
            "Monitoring cards show whether the monitoring stack is up, but dashboards only show business data after real hosts and real metrics exist.",
            "If you see No data right after install, that is normal on a clean environment. It usually means no agents have reported metrics yet."
        ],
        bullets=[
            "Prometheus is the metrics collector.",
            "Grafana is the dashboard and visualization layer.",
            "The Monitoring Tools page is where you verify stack health before drilling into dashboards."
        ]
    ))

    story.extend(section(
        "5. Core Features Customers Usually Use Most",
        bullets=[
            "Patch Manager for routine OS and package updates.",
            "Software Manager for approved software rollout or cleanup.",
            "CVE and compliance views for audit and security reporting.",
            "Snapshots and backup tools before risky change windows.",
            "Testing Center and smoke tests to validate the application after maintenance."
        ]
    ))

    story.extend(section(
        "6. Backups, Rollback, and Safety",
        body="Patching is safer when operators use snapshots and backups consistently. Before touching production estates, create a snapshot or backup policy that matches the business recovery objective.",
        bullets=[
            "Use snapshots before risky package or config changes.",
            "Use the backup tooling for file, database, live-sync, or VM-oriented protection where supported.",
            "Treat rollback as a recovery operation, not a daily shortcut. Always inspect why the original job failed."
        ]
    ))

    story.extend(section(
        "7. What To Tell Your Teams",
        bullets=[
            "Patch-SecOps Solution is capable, but it still depends on good maintenance windows, healthy agents, and accurate system time.",
            "No data is not always a fault; on a fresh install it often means the system is clean and waiting for hosts.",
            "Monitoring, compliance, and reporting value grows as more hosts are enrolled and patch activity accumulates."
        ]
    ))

    story.extend(section(
        "8. Quick Start Commands",
        code='''# Linux agent onboarding
curl -sS http://<server>:3000/download/install-agent.sh | sudo MASTER_URL=http://<server>:8000 bash

# Backend health
curl -fsS http://127.0.0.1:8000/api/health

# Monitoring stack health
curl -fsS http://127.0.0.1:3001/api/health
curl -fsS http://127.0.0.1:9090/api/monitoring/embed/prometheus/-/healthy'''
    ))
    return story


def build_pdf(filename, title, story_fn):
    path = OUT / filename
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=title,
        author="OpenAI Codex",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=28 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(story_fn(), onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
    return path


def main():
    outputs = [
        build_pdf("PatchMaster_Developer_Guide_v2.0.0.pdf", "Patch-SecOps Solution Developer Guide", developer_story),
        build_pdf("PatchMaster_Support_Runbook_v2.0.0.pdf", "Patch-SecOps Solution Support Runbook", support_story),
        build_pdf("PatchMaster_Customer_User_Guide_v2.0.0.pdf", "Patch-SecOps Solution Customer User Guide", consumer_story),
    ]
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
