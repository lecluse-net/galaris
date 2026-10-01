import { test, expect, mount, jsonRoute } from './fixtures.mjs';

test.beforeEach(async ({ page }) => {
  await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [], total: 0 });
});

test('remembered approvals and denials can be filtered and removed, with retry after failure', async ({ page }) => {
  await jsonRoute(page, '**/api/agents/selection*', [{ id: 7, label: 'Synthetic agent' }]);
  const row = { id: 'permission-a', agent_id: 7, permission_key: 'browser:v1:post:https://example.test:443',
    question: 'Allow POST to example.test?', allowed: false, approver_user_id: 1, approver_label: 'Synthetic manager', created_at: '2026-09-01T12:00:00Z', answered_at: '2026-09-01T12:01:00Z' };
  let removed = false, failDelete = true;
  const queries = [];
  await page.route('**/api/messenger/permissions*', route => {
    queries.push(Object.fromEntries(new URL(route.request().url()).searchParams));
    return route.fulfill({ json: { items: removed ? [] : [row], total: removed ? 0 : 1 } });
  });
  await page.route('**/api/messenger/permissions/permission-a', route => {
    if (failDelete) { failDelete = false; return route.fulfill({ status: 500, json: {} }); }
    removed = true;
    return route.fulfill({ status: 204 });
  });
  await mount(page, 'app/connection/pages/permissions.vue', { privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'] });
  await expect(page.getByText(row.question)).toBeVisible();
  await expect(page.getByText('Synthetic manager')).toBeVisible();
  expect(queries[0].limit).toBe('50');
  await page.getByRole('combobox', { name: 'Decision', exact: true }).click();
  await page.getByRole('option', { name: 'Denied', exact: true }).click();
  await expect.poll(() => queries.at(-1).allowed).toBe('false');
  await page.getByRole('button', { name: 'Delete decision' }).click();
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Delete decision' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete decision' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Delete decision' }).click();
  await expect(page.getByText(row.question)).toHaveCount(0);
});

test('read-only viewers cannot delete and a late unfiltered response cannot restore hidden decisions', async ({ page }) => {
  const row = { id: 'synthetic', agent_id: 7, permission_key: 'synthetic:permission', question: 'Synthetic approval',
    allowed: true, approver_user_id: 1, approver_label: 'Manager', created_at: '2026-09-01T12:00:00Z', answered_at: '2026-09-01T12:01:00Z' };
  let release;
  await page.route('**/api/messenger/permissions*', async route => {
    if (!new URL(route.request().url()).searchParams.has('allowed')) {
      await new Promise(resolve => { release = resolve; });
      await route.fulfill({ json: { items: [row], total: 1 } }).catch(() => {});
    } else await route.fulfill({ json: { items: [], total: 0 } });
  });
  await mount(page, 'app/connection/pages/permissions.vue', { privileges: ['CONNECTION_ACCESS'] });
  await expect.poll(() => typeof release).toBe('function');
  await page.getByRole('combobox', { name: 'Decision', exact: true }).click();
  await page.getByRole('option', { name: 'Denied', exact: true }).click();
  release();
  await expect(page.getByText(row.question)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Delete decision' })).toHaveCount(0);
  await page.unroute('**/api/messenger/permissions*');
  await jsonRoute(page, '**/api/messenger/permissions*', { items: [row], total: 1 });
  await page.getByRole('combobox', { name: 'Decision', exact: true }).click();
  await page.getByRole('option', { name: 'Allowed', exact: true }).click();
  await expect(page.getByText(row.question)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete decision' })).toHaveCount(0);
});
