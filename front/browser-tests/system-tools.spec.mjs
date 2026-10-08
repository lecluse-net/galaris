import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const tools = [
  ...['galaris', 'conversation', 'memory', 'file_sharing'].map((code, index) => ({
    id: index + 1, code, label: code, description: 'System service description.',
    can_disable: false, can_edit: false, conversation_enabled: true,
    connection_schema: { params: {} }, global_params: {},
  })),
  { id: 5, code: 'matrix', label: 'Optional Tool', description: '**Team handbook** for this connector.',
    can_disable: true, can_edit: true, conversation_enabled: true, connection_schema: { params: {} }, global_params: {} },
  { id: 6, code: 'empty', label: 'No description', description: '', can_disable: true,
    can_edit: true, conversation_enabled: false, connection_schema: { params: {} }, global_params: {} },
]
const connections = tools.slice(0, 5).map(tool => ({ id: tool.id, tool_id: tool.id, agent_id: 7, active: true }))
const privileges = ['TOOL_ACCESS', 'TOOL_EDIT', 'CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL']

for (const [locale, description, publicLabel, askChoice, allowChoice, saveLabel] of [
  ['fr', 'Permettre les demandes d’accès au réseau local (bloqué par défaut)', 'Accès aux sites publics', 'Autorisation par site', 'Sites publics autorisés', 'Modifier'],
  ['en', 'Allow local network permission requests (blocked by default)', 'Public site access', 'Per-site approval', 'Public sites allowed', 'Edit'],
  ['zh', '允许请求本地网络访问权限（默认阻止）', '公共网站访问', '按网站审批', '允许公共网站', '编辑'],
]) {
  test(`Browser connection descriptions are translated (${locale})`, async ({ page }) => {
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    const params = Object.fromEntries(['allow_local_network', 'network_filter_mode', 'network_filter', 'permission_methods'].map(name => [name, {
      type: name === 'allow_local_network' ? 'boolean' : 'string', required: false, description: 'Server description',
    }]))
    params.allow_local_network.default = 'false'
    params.public_access_mode = { type: 'string', required: false, default: 'ask', description: 'Server description',
      label: 'tools.connectionParamLabels.public_access_mode',
      options: ['allow', 'ask'].map(value => ({ value, label: `tools.connectionParamOptions.browser.public_access_mode.${value}` })) }
    await mount(page, 'app/connection/components/ConnectionForm.vue', {
      locale, privileges,
      props: {
        connection: { id: 42, agent_id: 7, tool_id: 8, active: true }, connectionParams: {},
        agentOptions: [{ value: 7, label: 'Synthetic Agent', agentDriver: 'internal' }],
        toolOptions: [{ id: 8, label: 'Browser' }],
        tools: [{ id: 8, label: 'Browser', code: 'browser', connection_schema: { params } }],
      },
    })
    await expect(page.getByText(description, { exact: true })).toBeVisible()
    await expect(page.locator('.param-desc').filter({ hasText: 'tools.connectionParamDescriptions' })).toHaveCount(0)
    await expect(page.getByText('Server description', { exact: true })).toHaveCount(0)
    const access = page.getByRole('combobox', { name: publicLabel, exact: true })
    await expect(access).toHaveValue(askChoice)
    await access.press('ArrowDown')
    await page.getByRole('option', { name: allowChoice, exact: true }).click()
    await page.getByRole('button', { name: saveLabel, exact: true }).click()
    await expect.poll(() => page.evaluate(() => {
      const params = window.testApp.events.filter(event => event.name === 'submit').at(-1)?.value.params
      return params && { public_access_mode: params.public_access_mode, allow_local_network: params.allow_local_network }
    })).toEqual({ public_access_mode: 'allow', allow_local_network: 'false' })
  })
}

async function routes(page) {
  await jsonRoute(page, '**/api/tools', tools)
  await jsonRoute(page, '**/api/file-share/bridges', [])
  await jsonRoute(page, '**/api/messenger/bridges', [])
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Alice', last_name: 'Example', agent_driver: 'internal' }])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await jsonRoute(page, '**/api/connections?*', connections)
  for (const connection of connections) {
    await jsonRoute(page, `**/api/connections/${connection.id}/params?*`, { ...connection, connection_id: connection.id, params: {}, configured_params: [] })
    await jsonRoute(page, `**/api/connections/${connection.id}/functions`, {
      success: true, message: '', functions: [{
        name: connection.id === 5 ? 'external_read' : 'system_read', description: 'Read authorized content.',
        key: connection.id === 5 ? 'tool:external_read' : 'tool:system_read', capability_kind: 'tool',
        default_state: 'enabled', effective_state: 'enabled', state_source: 'connection',
        connection_state: connection.id === 5 ? 'default' : 'enabled',
        global_state: connection.id === 5 ? 'default' : 'enabled', effective: true,
      }],
    })
  }
}

for (const mobile of [false, true]) {
  test(`Tool descriptions reopen and system switches remain read-only (${mobile ? 'mobile' : 'desktop'})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    await mount(page, 'app/tools/components/ToolsList.vue', { privileges })
    const rows = page.locator(mobile ? '.tool-mobile-card' : 'tbody tr')
    for (const name of ['Galaris', 'Conversation', 'Memory', 'File sharing']) {
      const row = rows.filter({ has: page.getByRole('button', { name, exact: true }) })
      await expect(row.getByRole('switch')).toBeDisabled()
      await expect(row.getByRole('img', { name: 'Mandatory system service' })).toBeVisible()
    }
    await rows.filter({ has: page.getByRole('button', { name: 'Galaris', exact: true }) }).getByText('galaris', { exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Coordinate agents')
    const headings = page.getByRole('dialog').getByRole('heading', { level: 2 })
    await expect(headings.first()).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('tool-description.png'), animations: 'disabled' })
    await headings.last().scrollIntoViewIfNeeded()
    await expect(headings.last()).toBeVisible()
    await page.getByRole('button', { name: 'Close', exact: true }).click()
    await page.getByRole('button', { name: 'Optional Tool', exact: true }).click()
    await expect(page.getByRole('dialog').locator('strong')).toHaveText('Team handbook')
    // The backdrop closes the description, and reopening retains its content.
    await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.getByRole('button', { name: 'Optional Tool', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('Team handbook')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: 'No description', exact: true })).toHaveCount(0)
    await page.getByText('No description', { exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(rows.filter({ hasText: 'Optional Tool' }).getByRole('switch')).toBeEnabled()
  })

  test(`System connections stay visible without edit or delete actions (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    await mount(page, 'app/connection/components/ConnectionList.vue', { privileges })
    const rows = page.locator(mobile ? '.connection-mobile-card' : 'tbody tr')
    await expect(rows).toHaveCount(5)
    for (let i = 0; i < 4; i++) {
      const row = rows.nth(i)
      await expect(row.getByRole('switch')).toBeDisabled()
      await expect(row.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
      await expect(row.getByRole('button')).toHaveCount(0)
    }
    await expect(rows.nth(4).getByRole('switch')).toBeEnabled()
  })
}

for (const mobile of [false, true]) {
test(`System functions have editable one-action policies while their service remains mandatory (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
  await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
  await routes(page)
  const writes = []
  await page.route('**/api/connections/1/capabilities', route => {
    writes.push(route.request().postDataJSON())
    return route.fulfill({ json: { name: 'system_read', connection_state: 'ask', global_state: 'enabled',
      effective: true, effective_state: 'ask', default_state: 'enabled', state_source: 'connection' } })
  })
  await mount(page, 'app/connection/components/AuthorizationManager.vue', { privileges })
  const selector = page.getByRole('combobox').nth(2)
  await selector.click()
  await page.getByRole('option', { name: 'Alice Example — Galaris', exact: true }).click()
  await expect(page.getByText('system_read', { exact: true })).toBeVisible()
  const row = page.locator(mobile ? '.authorization-mobile-card' : 'tbody tr')
  await expect(page.getByText('This system service and its connection are mandatory.', { exact: false })).toBeVisible()
  await row.getByRole('combobox', { name: 'This connection: system_read' }).click()
  await page.getByRole('option', { name: 'Ask', exact: true }).click()
  await expect.poll(() => writes).toEqual([{ function_name: 'system_read', state: 'ask', capability_kind: 'tool' }])
  await expect(row).toContainText('Ask')
})
}
