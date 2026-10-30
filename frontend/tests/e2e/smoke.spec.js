const { test, expect } = require('@playwright/test');

const licenseStub = {
  valid: true,
  activated: true,
  expired: false,
  tier: 'enterprise',
  tier_label: 'Enterprise (Advance)',
  plan: 'testing',
  days_remaining: 60,
  expires_at: '2099-01-01T00:00:00Z',
  features: [
    'dashboard',
    'hosts',
    'groups',
    'patches',
    'jobs',
    'cve',
    'compliance',
    'audit',
    'notifications',
    'users',
    'license',
    'schedules',
    'monitoring',
    'onboarding',
    'settings',
    'backups',
    'policies',
    'reports',
    'software',
  ],
  max_hosts: 0,
};

const hosts = [
  {
    id: 1,
    hostname: 'web-01',
    name: 'web-01',
    ip: '10.0.0.10',
    os: 'Ubuntu 24.04',
    is_online: true,
    compliance_score: 92,
    cve_count: 1,
    reboot_required: false,
    groups: ['web', 'debian/ubuntu'],
    tags: [{ id: 5, name: 'prod' }],
  },
];

const jobs = [
  {
    id: 101,
    host_id: 1,
    host_name: 'web-01',
    host_ip: '10.0.0.10',
    action: 'upgrade',
    status: 'success',
    initiated_by: 'test-user',
    created_at: '2026-03-22T09:00:00Z',
    started_at: '2026-03-22T09:00:00Z',
    completed_at: '2026-03-22T09:05:00Z',
    output: 'Packages upgraded successfully',
    result: { changed: 4 },
  },
];

const auditLogs = [
  {
    id: 77,
    username: 'test-user',
    action: 'host.patch',
    resource_type: 'host',
    resource_id: 1,
    details: { hostname: 'web-01' },
    created_at: '2026-03-22T10:00:00Z',
  },
];

const channels = [
  {
    id: 11,
    name: 'Ops Webhook',
    channel_type: 'webhook',
    config: { url: 'https://example.invalid/webhook' },
    events: ['job_failed', 'cve_critical'],
    is_enabled: true,
  },
];

const dashboardSummary = {
  risk_score: 38,
  hosts: {
    total: 1,
    online: 1,
    avg_compliance: 92,
    reboot_required: 0,
    total_upgradable: 3,
  },
  cves: {
    critical: 1,
    open_vulnerabilities: 1,
  },
  jobs: {
    success_30d: 6,
    failed_30d: 1,
  },
  needs_attention: [
    { id: 1, hostname: 'web-01', ip: '10.0.0.10', reason: 'critical cve', is_online: true },
  ],
  top_vulnerable_hosts: [
    { id: 1, hostname: 'web-01', ip: '10.0.0.10', critical: 1, high: 0, compliance: 92 },
  ],
  recent_activity: [
    { id: 1, title: 'Patch completed', detail: 'web-01 upgraded successfully', created_at: '2026-03-22T10:00:00Z' },
  ],
  patch_velocity: [
    { label: 'Mon', success: 2, failed: 0 },
    { label: 'Tue', success: 1, failed: 1 },
  ],
};

const cveRows = [
  {
    id: 1,
    cve_id: 'CVE-2026-0001',
    description: 'OpenSSL privilege escalation',
    severity: 'critical',
    cvss_score: 9.8,
    affected_hosts: 1,
    patched_hosts: 0,
  },
];

const cveStats = {
  total_cves: 1,
  by_severity: { critical: 1, high: 0, medium: 0, low: 0 },
  open_vulnerabilities: 1,
  patched_vulnerabilities: 0,
};

const monitoringStatus = {
  licensed: true,
  tier_label: 'Enterprise (Advance)',
  services: {
    prometheus: { installed: true, running: true, port: 9090 },
    'grafana-server.service': { installed: true, running: true, port: 3001 },
  },
};

const monitoringHealth = {
  services: {
    prometheus: { installed: true, running: true, port: 9090 },
    grafana: { installed: true, running: true, port: 3001 },
  },
};

function installSession(page) {
  return page.addInitScript((license) => {
    localStorage.setItem('pm_token', 'test-token');
    localStorage.setItem(
      'pm_user',
      JSON.stringify({ username: 'test-user', role: 'admin', permissions: {} })
    );
    localStorage.setItem('pm_license', JSON.stringify(license));
  }, licenseStub);
}

async function stubApi(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();

    let body;
    if (path === '/api/license/status') {
      body = licenseStub;
    } else if (path === '/api/health') {
      body = { status: 'healthy', version: '2.0.0' };
    } else if (path === '/api/auth/me') {
      body = { username: 'test-user', role: 'admin', permissions: {} };
    } else if (path === '/api/hosts/') {
      body = hosts;
    } else if (path === '/api/hosts/1/detail') {
      body = {
        ...hosts[0],
        recent_jobs: jobs,
        active_cves: cveRows,
      };
    } else if (path === '/api/tags/') {
      body = [{ id: 5, name: 'prod' }];
    } else if (path === '/api/dashboard/summary') {
      body = dashboardSummary;
    } else if (path === '/api/jobs/') {
      body = jobs;
    } else if (path === '/api/jobs/101') {
      body = jobs[0];
    } else if (path === '/api/notifications/me') {
      body = [];
    } else if (path === '/api/notifications/channels') {
      body = channels;
    } else if (path === '/api/audit/') {
      body = auditLogs;
    } else if (path === '/api/audit/stats') {
      body = { today: 3, this_week: 12 };
    } else if (path === '/api/cve/') {
      body = cveRows;
    } else if (path === '/api/cve/stats') {
      body = cveStats;
    } else if (path === '/api/monitoring/status') {
      body = monitoringStatus;
    } else if (path === '/api/monitoring/health') {
      body = monitoringHealth;
    } else if (path.endsWith('/ping')) {
      body = { online: true, latency_ms: 18, reboot_required: false };
    } else if (path.endsWith('/packages/upgradable')) {
      body = {
        packages: [
          { name: 'openssl', current_version: '3.0.2', available_version: '3.0.3' },
          { name: 'curl', current_version: '8.0.0', available_version: '8.0.1' },
        ],
      };
    } else if (path.startsWith('/api/notifications/test/')) {
      body = { ok: true };
    } else if (method === 'POST' || method === 'PUT' || method === 'DELETE') {
      body = { ok: true };
    } else {
      body = {};
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await installSession(page);
  await stubApi(page);
});

test('frontend smoke renders dashboard (stubbed API)', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { level: 1, name: /Dashboard/i })).toBeVisible();
  await expect(page.getByRole('button', { name: /Logout/i })).toBeVisible();
  await expect(page.getByText(/Operations command center/i)).toBeVisible();
});

test('frontend smoke clicks through software, jobs, audit, and notifications', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation');

  await nav.getByRole('button', { name: /Software Manager/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Software Manager/i })).toBeVisible();
  await expect(page.getByText(/Select Hosts/i)).toBeVisible();

  await nav.getByRole('button', { name: /Job History/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Job History/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Jobs/i })).toBeVisible();
  await expect(page.getByText(/web-01/i).first()).toBeVisible();
  await expect(page.getByText(/upgrade/i).first()).toBeVisible();

  await nav.getByRole('button', { name: /Audit Trail/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Audit Trail/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Audit Logs/i })).toBeVisible();
  await expect(page.getByText(/host.patch/i)).toBeVisible();

  await nav.getByRole('button', { name: /^Notifications$/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /^Notifications$/i })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Channels \(1\)/i })).toBeVisible();
  await expect(page.getByText(/Ops Webhook/i)).toBeVisible();
});

test('frontend smoke clicks through dashboard, hosts, cve tracker, patch manager, monitoring, and reports', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation');

  await nav.getByRole('button', { name: /Dashboard/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Dashboard/i })).toBeVisible();
  await expect(page.getByText(/Needs attention/i)).toBeVisible();

  await nav.getByRole('button', { name: /^Hosts$/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Hosts/i })).toBeVisible();
  await expect(page.getByText(/Endpoint operations/i)).toBeVisible();
  await expect(page.getByText(/web-01/i).first()).toBeVisible();

  await nav.getByRole('button', { name: /CVE Tracker/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /CVE Tracker/i })).toBeVisible();
  await expect(page.getByText(/Feed operations/i)).toBeVisible();
  await expect(page.getByText(/CVE-2026-0001/i)).toBeVisible();

  await nav.getByRole('button', { name: /Patch Management/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Patch Management/i })).toBeVisible();
  await expect(page.getByText(/Target host and discovery/i)).toBeVisible();

  await nav.getByRole('button', { name: /Monitoring Tools/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Monitoring Tools/i })).toBeVisible();
  await expect(page.getByText(/Workspace/i)).toBeVisible();
  await expect(page.getByText(/Prometheus/i).first()).toBeVisible();

  await nav.getByRole('button', { name: /^Reports$/i }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Reports/i })).toBeVisible();
  await expect(page.getByText(/Governance reporting/i)).toBeVisible();
  await expect(page.getByText(/System Hardening Report/i)).toBeVisible();
});
