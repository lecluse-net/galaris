import { test, expect, mount, jsonRoute } from './fixtures.mjs';

test.beforeEach(async ({ page }) => {
  await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [], total: 0 });
  await jsonRoute(page, '**/api/tools/action-authorizations/runtime-permissions?*', { items: [], total: 0 });
  await jsonRoute(page, '**/api/connections/function-permissions?*', { items: [], total: 0 });
});

test('permanent network permissions can be revoked, with retry after failure', async ({ page }) => {
  await jsonRoute(page, '**/api/agents/selection*', [{ id: 7, label: 'Synthetic agent' }]);
  const row = { id: 'permission-a', agent_id: 7, permission_key: 'browser:v1:post:https://example.test:443',
    question: 'Allow POST to example.test?', allowed: true, approver_user_id: 1, approver_label: 'Synthetic manager', created_at: '2026-09-01T12:00:00Z', answered_at: '2026-09-01T12:01:00Z' };
  let removed = false, failDelete = true;
  const queries = [];
  await page.route('**/api/messenger/permissions*', route => {
    queries.push(Object.fromEntries(new URL(route.request().url()).searchParams));
    const visible = new URL(route.request().url()).searchParams.get('allowed') === 'true' && !removed;
    return route.fulfill({ json: { items: visible ? [row] : [], total: visible ? 1 : 0 } });
  });
  await page.route('**/api/messenger/permissions/permission-a', route => {
    if (failDelete) { failDelete = false; return route.fulfill({ status: 500, json: {} }); }
    removed = true;
    return route.fulfill({ status: 204 });
  });
  await mount(page, 'app/connection/pages/permissions.vue', { privileges: ['PERMISSION_ACCESS', 'PERMISSION_DECIDE', 'PERMISSION_REVOKE'] });
  await page.getByRole('tab', { name: 'Permanent permissions' }).click();
  await expect(page.getByText(row.question)).toBeVisible();
  await expect(page.getByText('Synthetic manager')).toBeVisible();
  expect(queries[0].limit).toBe('50');
  await expect.poll(() => queries.at(-1).allowed).toBe('true');
  await page.getByRole('button', { name: 'Revoke permission' }).click();
  await page.locator('.q-dialog__backdrop').click({ position: { x: 3, y: 3 } });
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Revoke permission' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke permission' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke permission' }).click();
  await expect(page.getByText(row.question)).toHaveCount(0);
});

test('read-only viewers cannot delete and a late unfiltered response cannot restore hidden decisions', async ({ page }) => {
  const row = { id: 'synthetic', agent_id: 7, permission_key: 'synthetic:permission', question: 'Synthetic approval',
    allowed: true, approver_user_id: 1, approver_label: 'Manager', created_at: '2026-09-01T12:00:00Z', answered_at: '2026-09-01T12:01:00Z' };
  let release;
  await page.route('**/api/messenger/permissions*', async route => {
    if (new URL(route.request().url()).searchParams.has('pending')) {
      await new Promise(resolve => { release = resolve; });
      await route.fulfill({ json: { items: [row], total: 1 } }).catch(() => {});
    } else await route.fulfill({ json: { items: [], total: 0 } });
  });
  await mount(page, 'app/connection/pages/permissions.vue', { privileges: ['CONNECTION_ACCESS'] });
  await expect.poll(() => typeof release).toBe('function');
  await page.getByRole('tab', { name: 'Permanent permissions' }).click();
  release();
  await expect(page.getByText(row.question)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Revoke permission' })).toHaveCount(0);
  await page.unroute('**/api/messenger/permissions*');
  await jsonRoute(page, '**/api/messenger/permissions*', { items: [row], total: 1 });
  await page.getByRole('button', { name: 'Refresh', exact: true }).first().click();
  await expect(page.getByText(row.question)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Revoke permission' })).toHaveCount(0);
});

for (const width of [390, 1440]) test(`pending approvals are answered without listing one-time grants at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 });
  const row = { id: 'once', agent_id: 7, source: 'mcp', runtime: 'internal', capability_name: 'file_write',
    status: 'pending', preview: 'Write a synthetic note', can_answer: true, can_remember: true };
  let granted = false;
  const queries = [];
  await page.route('**/api/tools/action-authorizations?*', route => {
    queries.push(Object.fromEntries(new URL(route.request().url()).searchParams));
    return route.fulfill({ json: { items: row.status === 'pending' ? [row] : [], total: row.status === 'pending' ? 1 : 0 } });
  });
  await page.route('**/api/tools/action-authorizations/once', route => route.fulfill({ json: row }));
  await page.route('**/api/tools/action-authorizations/once/answer', route => {
    granted = route.request().postDataJSON().remember === true;
    row.status = 'approved'; row.can_answer = false; row.can_remember = false;
    return route.fulfill({ json: { accepted: true } });
  });
  const permission = { id: 'function', agent_id: 7, tool_label: 'Synthetic files', capability_name: 'file_write', connection_id: 9, active: true, can_revoke: true };
  await page.route('**/api/connections/function-permissions?*', route => route.fulfill({ json: { items: granted ? [permission] : [], total: granted ? 1 : 0 } }));
  await jsonRoute(page, '**/api/messenger/permissions?*', { items: [], total: 0 });
  const writes = [];
  await page.route('**/api/connections/9/functions/file_write', route => {
    writes.push(route.request().postDataJSON()); granted = false;
    return route.fulfill({ json: { effective_state: 'ask' } });
  });
  await mount(page, 'app/connection/pages/permissions.vue', { privileges: ['PERMISSION_ACCESS', 'PERMISSION_DECIDE', 'PERMISSION_REVOKE'] });
  await expect(page.getByText(row.preview)).toBeVisible();
  expect(queries[0].status).toBe('pending');
  await page.getByRole('button', { name: 'Review request' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Allow this action', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Review request' })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Permanent permissions' }).click();
  await expect(page.getByText('file_write', { exact: true })).toHaveCount(0);
  row.status = 'pending'; row.can_answer = true; row.can_remember = true;
  await page.getByRole('tab', { name: 'Pending approvals' }).click();
  await page.getByRole('button', { name: 'Review request' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Always allow this function' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('tab', { name: 'Permanent permissions' }).click();
  await expect(page.getByText(width < 1024 ? 'Synthetic files · file_write' : 'file_write')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('permanent-permissions.png'), fullPage: true });
  await page.getByRole('button', { name: 'Revoke consent', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke consent', exact: true }).click();
  await expect.poll(() => writes).toEqual([{ state: 'ask', capability_kind: 'tool' }]);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('file_write', { exact: true })).toHaveCount(0);
});

test('pending network requests can be answered from Permissions with recovery after failure', async ({ page }) => {
  const row = { id: 'network', agent_id: 7, question: 'Allow synthetic network access?', can_answer: true,
    allowed: null, options: [{ id: 'allow', label: 'Allow and remember' }, { id: 'deny', label: 'Deny and remember' }] };
  const answers = [];
  let pending = true;
  await page.route('**/api/messenger/permissions?*', route => route.fulfill({ json: { items: pending ? [row] : [], total: pending ? 1 : 0 } }));
  await page.route('**/api/messenger/permissions/network/answer', route => {
    answers.push(route.request().postDataJSON());
    if (answers.length === 1) return route.fulfill({ status: 409, json: {} });
    pending = false;
    return route.fulfill({ json: { accepted: true } });
  });
  await mount(page, 'app/connection/pages/permissions.vue', { privileges: ['PERMISSION_DECIDE', 'PERMISSION_REVOKE'] });
  await page.getByRole('button', { name: 'Allow and remember', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.getByRole('button', { name: 'Allow and remember', exact: true }).click();
  await expect(page.getByText(row.question)).toHaveCount(0);
  expect(answers).toEqual([{ option_id: 'allow' }, { option_id: 'allow' }]);
});
