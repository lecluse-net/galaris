import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [390, 1440]) test(`Calendar connection owns its interval without loading calendars (${width})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const tool = { id: 8, code: 'synthetic_calendar', label: 'Synthetic Calendar', has_calendar: true,
    calendar_config: { settings: { source_kind: 'caldav' }, param_map: { sync_interval_hours: 'sync_interval_hours' } },
    global_params: {}, connection_schema: { params: { sync_interval_hours: { type: 'integer', required: false, default: '2',
      label: 'Synchronization interval (hours)', description: 'Shared interval for this connection' } } } }
  const props = { connection: { id: 42, agent_id: 7, tool_id: 8, active: true }, connectionParams: { sync_interval_hours: '2' }, tools: [tool],
    agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }], toolOptions: [{ id: 8, label: 'Synthetic Calendar' }] }
  await mount(page, 'app/connection/components/ConnectionForm.vue', { privileges: ['CONNECTION_EDIT', 'CALENDAR_EDIT'], props })
  const input = page.getByRole('spinbutton', { name: 'Synchronization interval (hours)', exact: true })
  await expect(input).toHaveValue('2')
  await input.fill('3')
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.testApp.events.find(event => event.name === 'submit')?.value))
    .toMatchObject({ id: 42, data: { tool_id: 8, agent_id: 7 }, params: { sync_interval_hours: '3' } })
  await mount(page, 'app/connection/components/ConnectionForm.vue', {
    privileges: ['CONNECTION_EDIT'], props: { ...props, connectionParams: { sync_interval_hours: '3' } },
  })
  await expect(page.getByRole('spinbutton', { name: 'Synchronization interval (hours)', exact: true })).toHaveValue('3')
  for (const dark of [false, true]) {
    await page.evaluate(dark => window.testApp.dark(dark), dark)
    await page.screenshot({ path: testInfo.outputPath(`connection-interval-${dark ? 'dark' : 'light'}.png`), fullPage: true, animations: 'disabled' })
  }
})

for (const width of [390, 1440]) test(`One Mail provider retains multiple accounts for the same agent (${width})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const tool = { id: 8, code: 'synthetic_mail', label: 'Synthetic Mail', can_disable: true, has_mail: true,
    mail_config: { param_map: { email_address: 'email' }, settings: {} }, global_params: {},
    connection_schema: { params: { email: { type: 'string', label: 'Mailbox address', required: true } } } }
  const accounts = [{ id: 42, tool_id: 8, agent_id: 7, active: true, params: { email: 'first@example.org' }, configured_params: [] }]
  await jsonRoute(page, '**/api/connections/tool-options', [tool])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await jsonRoute(page, '**/api/mail/status', { enabled: true })
  await page.route('**/api/connections/overview?*', route => route.fulfill({ json: accounts }))
  const writes = []
  await page.route('**/api/connections', async route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    const account = { ...body, id: 43, configured_params: [] }
    accounts.push(account)
    await route.fulfill({ status: 201, json: account })
  })
  await mount(page, 'app/connection/components/ConnectionList.vue', { privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT'] })
  await expect(page.getByText('first@example.org', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'New Connection', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Alice Example', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Tool', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic Mail', exact: true }).click()
  await dialog.getByLabel('Mailbox address *', { exact: true }).fill('second@example.org')
  await dialog.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(1)
  expect(writes[0]).toMatchObject({ tool_id: 8, agent_id: 7, params: { email: 'second@example.org' } })
  await expect(page.getByText('first@example.org', { exact: true })).toBeVisible()
  await expect(page.getByText('second@example.org', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('same-provider-mail-accounts.png'), fullPage: true })
})

for (const width of [390, 1440]) test(`Mail folders can be listed, checked and saved with retry (${width})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const folderParam = width === 390 ? 'visible_folders' : 'allowed_mailboxes'
  await jsonRoute(page, '**/api/mail/approvers', [])
  let fail = true
  await page.route('**/api/mail/connections/42/mailboxes', route => {
    if (fail) { fail = false; return route.fulfill({ status: 502 }) }
    return route.fulfill({ json: [
      { name: 'INBOX', label: 'INBOX', delimiter: '/', selectable: true },
      { name: 'Projects', label: 'Projects', delimiter: '/', selectable: false },
      { name: 'Projects/Active, Shared', label: 'Projects/Active, Shared', delimiter: '/', selectable: true },
      { name: 'Sent', label: 'Sent', delimiter: '/', selectable: true },
    ] })
  })
  const tool = { id: 8, code: 'mail', label: 'Mail', can_edit: false, global_params: {},
    connection_schema: { params: { [folderParam]: { type: 'string', widget: 'mail_folder_tree', required: false, default: '',
      description: 'Allowed IMAP folders' } } } }
  await mount(page, 'app/connection/components/ConnectionForm.vue', {
    privileges: ['CONNECTION_EDIT'],
    props: { connection: { id: 42, agent_id: 7, tool_id: 8, active: true, name: '' },
      connectionParams: { [folderParam]: 'INBOX' }, tools: [tool],
      agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }],
      toolOptions: [{ id: 8, label: 'Mail' }] },
  })
  await expect(page.locator('.mail-folder-access').getByRole('alert')).toContainText('Unable to load folders')
  await expect(page.getByRole('checkbox', { name: 'INBOX', exact: true })).toBeChecked()
  await page.getByRole('button', { name: 'Reload folders', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: 'Projects', exact: true })).toBeDisabled()
  await page.getByRole('checkbox', { name: 'Projects/Active, Shared', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Sent', exact: true }).check()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect.poll(() => page.evaluate(name => window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params[name], folderParam))
    .toBe('["INBOX","Projects/Active, Shared","Sent"]')
  await page.screenshot({ path: testInfo.outputPath('mail-folders-light.png'), fullPage: true, animations: 'disabled' })
  await page.evaluate(() => window.testApp.dark(true))
  await page.screenshot({ path: testInfo.outputPath('mail-folders-dark.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('checkbox', { name: 'Access to all folders', exact: true }).check()
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect.poll(() => page.evaluate(name => window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params[name], folderParam))
    .toBe('[]')
  for (const name of ['INBOX', 'Projects/Active, Shared', 'Sent']) {
    await page.getByRole('checkbox', { name, exact: true }).uncheck()
  }
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.locator('.mail-folder-access').getByRole('alert')).toContainText('Select at least one folder')
  expect(await page.evaluate(() => window.testApp.events.filter(event => event.name === 'submit').length)).toBe(2)
})

test('Mail folder discovery follows the selected account and ignores late responses', async ({ page }) => {
  let release
  let started = false
  await page.route('**/api/mail/connections/42/mailboxes', async route => {
    started = true
    await new Promise(resolve => { release = resolve })
    await route.fulfill({ json: [{ name: 'Other account', label: 'Other account', selectable: true }] }).catch(() => {})
  })
  await jsonRoute(page, '**/api/mail/connections/43/mailboxes', [{ name: 'Selected account', label: 'Selected account', selectable: true }])
  await mount(page, 'app/connection/components/MailFolderAccess.vue', { props: { connectionId: 42, modelValue: 'INBOX' } })
  await expect.poll(() => started).toBe(true)
  await page.evaluate(() => window.testApp.setProps({ connectionId: 43, modelValue: '["Selected account"]' }))
  await expect(page.getByRole('checkbox', { name: 'Selected account', exact: true })).toBeChecked()
  release()
  await expect(page.getByRole('checkbox', { name: 'Other account', exact: true })).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const width of [390, 1440]) {
  test(`Connections load together, refresh on reopening and recover from errors (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const connection = { id: 42, tool_id: 8, agent_id: 7, active: true }
    const params = { host: 'initial.example.test', token: null }
    const tool = { id: 8, code: 'synthetic_connector', label: 'Synthetic connector', can_disable: true, can_edit: true,
      has_function_permissions: true,
      connection_schema: { params: { host: { type: 'string', label: 'Service host', required: false }, token: { type: 'password', label: 'Token', required: false } } }, global_params: {} }
    await jsonRoute(page, '**/api/tools', [tool])
    await jsonRoute(page, '**/api/tools/capabilities', [])
    await jsonRoute(page, '**/api/connections/tool-options', [tool])
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    for (const endpoint of ['mail/approvers', 'file-share/bridges', 'messenger/bridges']) {
      await jsonRoute(page, `**/api/${endpoint}`, [])
    }
    await jsonRoute(page, '**/api/mail/status', { enabled: false })
    let overviewReads = 0
    let parameterReads = 0
    let failNext = false
    await page.route('**/api/connections/overview?*', route => {
      overviewReads++
      if (failNext) {
        failNext = false
        return route.fulfill({ status: 503, json: { detail: 'Synthetic read failure' } })
      }
      return route.fulfill({ json: [{ ...connection, params, configured_params: ['token'] }] })
    })
    await page.route('**/api/connections/42/params?*', route => {
      parameterReads++
      return route.fulfill({ json: { connection_id: 42, tool_id: 8, agent_id: 7, params, configured_params: ['token'] } })
    })
    await page.route('**/api/connections/42', route => {
      Object.assign(connection, route.request().postDataJSON())
      return route.fulfill({ json: connection })
    })
    await page.route('**/api/connections/42/params/bulk', route => {
      Object.assign(params, route.request().postDataJSON().params)
      return route.fulfill({ json: [] })
    })
    await mount(page, 'app/tools/pages/index.vue', {
      route: '/tools?tab=connections',
      privileges: ['TOOL_ACCESS', 'TOOL_EDIT', 'CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL', 'PERMISSION_ACCESS'],
    })
    const rows = page.locator(width < 1024 ? '.connection-mobile-card' : '.connection-table tbody tr')
    await expect(rows).toContainText('initial.example.test')
    expect(overviewReads).toBe(1)
    expect(parameterReads).toBe(0)
    // Filtering uses the same complete snapshot, with no per-row parameter fan-out.
    await page.getByRole('combobox', { name: 'Filter by tool', exact: true }).click()
    await page.getByRole('option', { name: 'Synthetic connector', exact: true }).click()
    await expect(rows).toContainText('initial.example.test')
    expect(overviewReads).toBe(1)
    await page.getByRole('tab', { name: 'Tools', exact: true }).click()
    params.host = 'reopened.example.test'
    await page.getByRole('tab', { name: 'Connections', exact: true }).click()
    await expect(rows).toContainText('reopened.example.test')
    expect(overviewReads).toBe(2)
    expect(parameterReads).toBe(0)
    await page.getByRole('tab', { name: 'Tools', exact: true }).click()
    failNext = true
    await page.getByRole('tab', { name: 'Connections', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Error while loading available connections')
    await expect(rows).toContainText('reopened.example.test')
    await page.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await page.getByRole('button', { name: 'All', exact: true }).click()
    await rows.getByRole('switch').click()
    await expect.poll(() => connection.active).toBe(false)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(parameterReads).toBe(0)
    await rows.getByRole('switch').click()
    await expect.poll(() => connection.active).toBe(true)
    await rows.getByText('reopened.example.test', { exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Service host', { exact: true })).toHaveValue('reopened.example.test')
    expect(parameterReads).toBe(1)
    const policies = { connections: [{ tool_id: 8, tool_code: tool.code, tool_label: tool.label, connection_id: 42,
      active: true, can_disable: true, parameters: {} }], capabilities: [{ id: '8:tool:lookup', tool_id: 8, tool_label: tool.label,
      connection_id: 42, name: 'lookup', description: 'Synthetic lookup', capability_kind: 'tool', connection_state: 'default',
      global_state: 'default', default_state: 'ask', effective_state: 'ask', policy_state: 'ask', policy_source: 'software',
      available: true, runtime_supported: true }], unavailable_catalogs: [] }
    let catalogReads = 0
    await page.route('**/api/tools/agents/7/permissions?connection_id=42', route => { catalogReads++; return route.fulfill({ json: policies }) })
    await expect(dialog.getByRole('tab', { name: 'Permissions', exact: true })).toBeVisible()
    expect(catalogReads).toBe(0)
    await dialog.getByRole('tab', { name: 'Permissions', exact: true }).click()
    await expect(dialog.getByText('lookup', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('Service host', { exact: true })).toBeHidden()
    await expect(dialog.getByRole('group', { name: 'Local (this connection)', exact: true }).getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
    await expect(dialog.getByRole('group', { name: 'Global (all)', exact: true }).getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
    expect(catalogReads).toBe(1)
    await page.screenshot({ path: testInfo.outputPath('connection-permissions-light.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('connection-permissions-dark.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(false))
    await dialog.getByRole('tab', { name: 'Settings', exact: true }).click()
    await expect.poll(() => page.evaluate(() => window.testApp.router.currentRoute.value.fullPath)).toBe('/tools?tab=connections')
    await page.screenshot({ path: testInfo.outputPath('connection-dialog-light.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('connection-dialog-dark.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(false))
    await dialog.getByRole('button', { name: 'Close', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    // The explicit edit action remains usable from the keyboard.
    await rows.getByRole('button', { name: 'Edit', exact: true }).press('Enter')
    await expect(dialog.getByLabel('Service host', { exact: true })).toHaveValue('reopened.example.test')
    expect(parameterReads).toBe(2)
    await dialog.getByLabel('Service host', { exact: true }).fill('saved.example.test')
    await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(rows).toContainText('saved.example.test')
    await jsonRoute(page, '**/api/connections/42/test', { status: 'success', checks: [{ protocol: 'mcp', status: 'success', message: 'Synthetic authenticated MCP check' }] })
    await rows.getByRole('button', { name: 'Test', exact: true }).press('Enter')
    await expect(page.getByRole('dialog')).toContainText('Connection working')
    await expect(page.getByRole('dialog')).toContainText('Synthetic authenticated MCP check')
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    expect(params.token).toBeNull()
    await expect(page.getByRole('link', { name: 'Scopes and permissions', exact: true })).toHaveAttribute('href', '/permissions')
    let refreshes = 0
    await page.route('**/api/connections/refresh-tools', route => {
      refreshes++
      if (refreshes === 1) return route.fulfill({ status: 503, json: { detail: 'Synthetic catalogue failure' } })
      const partial = refreshes === 2
      return route.fulfill({ json: { complete: !partial, created: 0, agents_scanned: 2,
        agents_refreshed: partial ? 1 : 2, agent_failures: partial ? 1 : 0, source_failures: 0,
        tools_discovered: 7, documents_indexed: 7, embeddings_refreshed: 0, documents_pruned: 0,
        semantic_available: true, degradation_reason: null } })
    })
    const refresh = page.getByRole('button', { name: /Create missing internal connections/ })
    await refresh.click()
    const failure = page.getByRole('alert').filter({ hasText: 'Error while refreshing connections and tool catalogs' })
    await expect(failure).toBeVisible()
    await expect(rows).toContainText('saved.example.test')
    await failure.getByRole('button', { name: 'Retry', exact: true }).press('Enter')
    await expect(failure).toHaveCount(0)
    await expect(page.getByRole('status').filter({ hasText: 'Partial refresh: 1/2' })).toBeVisible()
    await refresh.click()
    await expect(page.getByRole('status').filter({ hasText: 'Refresh complete:' })).toContainText('7 tool(s) discovered')
    expect(refreshes).toBe(3)
    await page.getByRole('combobox', { name: 'Filter by agent', exact: true }).click()
    await page.getByRole('option', { name: 'Alice Example', exact: true }).click()
    await expect(page.getByRole('link', { name: 'Scopes and permissions', exact: true })).toHaveAttribute('href', '/permissions?agent_id=7')
    await expect(page.locator('.q-notification')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('connections-loaded.png'), fullPage: true, animations: 'disabled' })
    await page.evaluate(() => window.testApp.dark(true))
    await page.screenshot({ path: testInfo.outputPath('connections-loaded-dark.png'), fullPage: true, animations: 'disabled' })
  })
}
