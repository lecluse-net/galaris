import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

for (const locale of ['fr', 'en', 'zh']) {
  test(`network warnings follow the bridge and address without blocking local outbound bridges (${locale})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mount(page, 'core/util/components/NetworkAccessNotice.vue', {
      locale, dark: true, props: { kind: 'whatsapp', origin: 'http://localhost:8484' },
    })
    await expect(page.getByRole('alert')).toContainText('http://localhost:8484')
    await expect(page.getByRole('alert')).toContainText('/api/whatsapp/webhook/TOOL_ID')
    await page.screenshot({ path: testInfo.outputPath('local-whatsapp-mobile-dark.png') })
    await page.evaluate(() => window.testApp.setProps({ origin: 'https://galaris.internal' }))
    await expect(page.getByRole('alert')).toContainText('https://galaris.internal')
    await page.evaluate(() => window.testApp.setProps({ origin: 'http://galaris.example.com' }))
    await expect(page.getByRole('alert')).toBeVisible()
    await page.evaluate(() => window.testApp.setProps({ origin: 'https://galaris.example.com' }))
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect(page.getByRole('note')).toBeVisible()
    await page.evaluate(() => window.testApp.setProps({ origin: 'https://[fd12::1]', kind: 'one_bot' }))
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('alert')).toContainText('https://[fd12::1]')
    await expect(page.getByRole('alert')).toContainText('localhost')
    for (const kind of ['telegram', 'matrix', 'nextcloud_talk']) {
      await page.evaluate(kind => window.testApp.setProps({ kind, origin: 'http://localhost:8484' }), kind)
      await expect(page.getByRole('alert')).toHaveCount(0)
      await expect(page.getByRole('note')).toBeVisible()
    }
    await page.evaluate(() => window.testApp.setProps({ kind: 'unknown' }))
    await expect(page.getByRole('note')).toHaveCount(0)
  })
}

test('messaging preferences switch network notices with the selected provider', async ({ page }, testInfo) => {
  await mount(page, 'core/params/components/MessagingSettingsPanel.vue', { privileges: ['PARAMS_EDIT'] })
  await page.getByRole('tab', { name: 'WhatsApp', exact: true }).click()
  await expect(page.getByRole('alert', { name: 'WhatsApp', exact: true })).toContainText('http://localhost:8000')
  await expect(page.getByRole('alert', { name: 'WhatsApp', exact: true })).toContainText('Meta')
  await page.screenshot({ path: testInfo.outputPath('whatsapp-preferences-desktop-light.png'), fullPage: true })
  await page.getByRole('tab', { name: 'Telegram', exact: true }).click()
  await expect(page.getByRole('alert', { name: 'WhatsApp', exact: true })).toHaveCount(0)
  await expect(page.getByRole('note')).toContainText('long polling')
  await page.getByRole('tab', { name: 'OneBot 11', exact: true }).click()
  await expect(page.getByRole('alert', { name: 'OneBot 11', exact: true })).toContainText('VPN')
  await expect(page.getByRole('alert', { name: 'OneBot 11', exact: true })).toContainText('http://localhost:8000')
})

test('Telegram setup creates a secret connection parameter once and recovers from errors', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 1000 })
  let fail = true
  const tools = []
  const writes = []
  await page.route('**/api/tools', route => {
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary failure' } })
    if (route.request().method() === 'GET') return route.fulfill({ json: tools })
    const body = route.request().postDataJSON()
    writes.push(body)
    tools.push({ id: 82, ...body })
    return route.fulfill({ json: tools[0] })
  })
  await mount(page, 'core/params/components/MessagingSettingsPanel.vue', { privileges: ['TOOL_EDIT'] })
  await page.getByRole('tab', { name: 'Telegram', exact: true }).click()
  const guide = page.getByRole('region', { name: 'Setup guide', exact: true })
  await guide.getByText('Setup guide', { exact: true }).click()
  const create = page.getByRole('button', { name: 'Create Telegram Tool', exact: true })
  await create.focus()
  await page.keyboard.press('Enter')
  await expect(guide.getByRole('alert')).toContainText('Unable to prepare the Telegram Tool')
  await expect(create).toBeEnabled()
  fail = false
  await create.click()
  await expect(guide.getByRole('status')).toContainText('The Telegram Tool is ready')
  expect(writes).toHaveLength(1)
  expect(writes[0]).toMatchObject({ code: 'telegrem', label: 'Telegram',
    messenger_config: { service: 'telegram', settings: {}, param_map: { token: 'token' } },
    connection_schema: { params: { token: { type: 'password', required: true, default: '' } } },
  })
  await page.screenshot({ path: testInfo.outputPath('telegram-tool-ready-mobile.png'), fullPage: true })
  // Reopening checks persisted configuration before offering another creation.
  await page.getByRole('tab', { name: 'WhatsApp', exact: true }).click()
  await page.getByRole('tab', { name: 'Telegram', exact: true }).click()
  await guide.getByText('Setup guide', { exact: true }).click()
  await create.click()
  await expect(guide.getByRole('status')).toContainText('The Telegram Tool is ready')
  expect(writes).toHaveLength(1)
  await setPrivileges(page, [])
  await expect(page.getByRole('link', { name: 'Open tools and connections', exact: true })).toHaveCount(0)
})

test('Telegram setup preserves an existing Tool with conflicting configuration', async ({ page }) => {
  const requests = []
  await page.route('**/api/tools', route => {
    requests.push(route.request().method())
    return route.fulfill({ json: [{ id: 83, code: 'telegrem', label: 'Synthetic existing Tool',
      messenger_config: null, connection_schema: { params: {} } }] })
  })
  await mount(page, 'app/tools/components/TelegramToolSetup.vue', { privileges: [] })
  await expect(page.getByRole('button', { name: 'Create Telegram Tool' })).toHaveCount(0)
  await setPrivileges(page, ['TOOL_EDIT'])
  await page.getByRole('button', { name: 'Create Telegram Tool' }).click()
  await expect(page.getByRole('status')).toContainText('already used by a Tool with different settings')
  expect(requests).toEqual(['GET'])
})

test('the Tool messaging warning allows saving and remains accurate on reopening', async ({ page }) => {
  const tool = { id: 81, code: 'synthetic_messaging', label: 'Synthetic messaging', can_edit: true, can_disable: true,
    conversation_enabled: false, connection_schema: { params: {} }, global_params: {}, has_messenger: true,
    messenger_config: { service: 'whatsapp', settings: {}, param_map: {} } }
  let saved = tool
  const writes = []
  await page.route('**/api/tools', route => route.fulfill({ json: [saved] }))
  await jsonRoute(page, '**/api/file-share/bridges', [])
  await jsonRoute(page, '**/api/messenger/bridges', [
    { service: 'whatsapp', label: 'WhatsApp', settings: [], params: [] },
    { service: 'telegram', label: 'Telegram', settings: [], params: [] },
  ])
  await page.route('**/api/tools/81', route => {
    const data = route.request().postDataJSON()
    writes.push(data)
    saved = { ...tool, ...data }
    return route.fulfill({ json: saved })
  })
  await mount(page, 'app/tools/components/ToolsList.vue', { privileges: ['TOOL_ACCESS', 'TOOL_EDIT'] })
  const edit = page.locator('tbody tr').filter({ hasText: tool.label }).getByRole('button', { name: 'Edit tool', exact: true })
  await edit.click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('tab', { name: 'Messaging', exact: true }).click()
  await expect(dialog.getByRole('alert', { name: 'WhatsApp', exact: true })).toContainText('Meta')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toHaveLength(1)
  expect(writes[0].messenger_config.service).toBe('whatsapp')
  await edit.click()
  await dialog.getByRole('tab', { name: 'Messaging', exact: true }).click()
  await expect(dialog.getByRole('alert', { name: 'WhatsApp', exact: true })).toBeVisible()
  const select = dialog.getByRole('combobox', { name: 'Messaging service (bridge) *', exact: true })
  await select.click()
  await page.getByRole('option', { name: 'Telegram', exact: true }).click()
  await expect(dialog.getByRole('alert', { name: 'WhatsApp', exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('note')).toContainText('long polling')
  await page.locator('.q-dialog__backdrop').click({ position: { x: 2, y: 2 } })
  await expect(dialog).toHaveCount(0)
})
