const { test, expect } = require('@playwright/test');

const REAL_BASE_URL = (process.env.PLAYWRIGHT_REAL_BASE_URL || '').trim();
const REAL_USER = (process.env.PLAYWRIGHT_REAL_USER || '').trim();
const REAL_PASSWORD = (process.env.PLAYWRIGHT_REAL_PASSWORD || '').trim();
const REAL_EXPECTED_PAGES = (process.env.PLAYWRIGHT_REAL_EXPECTED_PAGES || 'Dashboard,Hosts,Job History,Notifications')
  .split(',')
  .map((value) => value.trim())
  .filter(Boolean);

const configured = Boolean(REAL_BASE_URL && REAL_USER && REAL_PASSWORD);

test.describe('authenticated real backend smoke', () => {
  test.skip(!configured, 'Set PLAYWRIGHT_REAL_BASE_URL, PLAYWRIGHT_REAL_USER, and PLAYWRIGHT_REAL_PASSWORD to enable this live smoke flow.');

  test('logs into a running PatchMaster instance and opens core pages', async ({ page }) => {
    await page.goto(REAL_BASE_URL, { waitUntil: 'domcontentloaded' });

    const logoutButton = page.getByRole('button', { name: /Logout/i });
    if (await logoutButton.count()) {
      await expect(logoutButton).toBeVisible({ timeout: 15000 });
    } else {
      await page.getByPlaceholder(/e\.g\. admin/i).fill(REAL_USER);
      await page.locator('input[type="password"]').first().fill(REAL_PASSWORD);
      await page.getByRole('button', { name: 'Sign In', exact: true }).click();
      await expect(logoutButton).toBeVisible({ timeout: 20000 });
    }

    const nav = page.getByRole('navigation');
    const dashboardHeading = page.getByRole('heading', { level: 1, name: /Dashboard/i });
    if (await dashboardHeading.count()) {
      await expect(dashboardHeading).toBeVisible({ timeout: 15000 });
    }

    for (const label of REAL_EXPECTED_PAGES) {
      const navButton = nav.getByRole('button', { name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'i') });
      if ((await navButton.count()) === 0) continue;
      await navButton.click();
      await expect(page.getByRole('heading', { level: 1, name: new RegExp(label, 'i') })).toBeVisible({ timeout: 15000 });
    }
  });
});
