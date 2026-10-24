import { test, expect, mount, jsonRoute } from './fixtures.mjs'

for (const width of [390, 1440]) {
  test(`Connections load together, refresh on reopening and recover from errors (${width})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const connection = { id: 42, tool_id: 8, agent_id: 7, active: true }
    const params = { host: 'initial.example.test', token: null }
    const tool = { id: 8, code: 'synthetic_connector', label: 'Synthetic connector', can_disable: true, can_edit: true,
      connection_schema: { params: { host: { type: 'string', label: 'Service host', required: false }, token: { type: 'password', label: 'Token', required: false } } }, global_params: {} }
    await jsonRoute(page, '**/api/tools', [tool])
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
      privileges: ['TOOL_ACCESS', 'TOOL_EDIT', 'CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL'],
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
    await rows.getByRole('button', { name: 'Edit', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByLabel('Service host', { exact: true })).toHaveValue('reopened.example.test')
    await dialog.getByLabel('Service host', { exact: true }).fill('saved.example.test')
    await dialog.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(rows).toContainText('saved.example.test')
    expect(params.token).toBeNull()
    await page.screenshot({ path: testInfo.outputPath('connections-loaded.png'), fullPage: true, animations: 'disabled' })
  })
}
