import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

test('Matrix reception displays the encryption error and clears it after a successful retry', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 1000 })
  let encrypted = true
  const detail = 'Encrypted Matrix rooms are not supported by Galaris (detected: 1). Their messages cannot be decrypted and create no conversation round. Use an unencrypted room.'
  await page.route('**/api/messenger/configuration/test*', route => route.fulfill({ json: {
    provider: 'matrix', ok: !encrypted, connections: [{ connection_id: 91, agent_id: 7, provider: 'matrix',
      ok: !encrypted, identity: '@synthetic:example.test', detail: encrypted ? detail : '@synthetic:example.test',
      receiving: true, last_received_at: null }],
  } }))
  await mount(page, 'core/params/components/MessagingSettingsPanel.vue', { privileges: ['MESSAGING_CONFIG_EDIT'] })
  await page.getByRole('tab', { name: 'Matrix', exact: true }).click()
  const run = page.getByRole('button', { name: 'Test reception', exact: true })
  const error = page.getByRole('alert').filter({ hasText: detail })
  await run.click()
  await expect(error).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('matrix-encryption-error-mobile.png'), fullPage: true })
  encrypted = false
  await run.click()
  await expect(error).toHaveCount(0)
  await expect(page.getByText('@synthetic:example.test', { exact: true })).toBeVisible()
})

test('reception checks are scoped to the selected messaging provider', async ({ page }) => {
  const providers = []
  await page.route('**/api/messenger/configuration/test*', route => {
    const provider = new URL(route.request().url()).searchParams.get('provider')
    providers.push(provider)
    return route.fulfill({ json: { provider, ok: false, connections: [] } })
  })
  await mount(page, 'core/params/components/MessagingSettingsPanel.vue', { privileges: ['MESSAGING_CONFIG_EDIT'] })
  for (const [label, provider] of [['Telegram', 'telegram'], ['Matrix', 'matrix'], ['Nextcloud Talk', 'nextcloud_talk'], ['OneBot 11', 'one_bot'], ['WhatsApp', 'whatsapp'], ['Galaris', 'internal']]) {
    await page.getByRole('tab', { name: label, exact: true }).click()
    await page.getByRole('button', { name: 'Test reception', exact: true }).click()
    await expect.poll(() => providers.at(-1)).toBe(provider)
    await expect(page.getByText('No active agent connection for this messaging provider. Configure an account in Tools → Connections.', { exact: true })).toBeVisible()
  }
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/messenger/configuration/test?provider=telegram', async route => {
    await pending
    await route.fulfill({ json: { provider: 'telegram', ok: true, connections: [
      { provider: 'telegram', connection_id: 97, agent_id: 7, ok: true, detail: 'Late Telegram result', receiving: true },
    ] } })
  })
  await page.getByRole('tab', { name: 'Telegram', exact: true }).click()
  const run = page.getByRole('button', { name: 'Test reception', exact: true })
  const started = page.waitForRequest(request => request.url().endsWith('provider=telegram'))
  await run.click()
  await started
  await page.getByRole('tab', { name: 'Matrix', exact: true }).click()
  await run.click()
  await expect(page.getByText('No test run', { exact: true })).toBeVisible()
  const oldResponse = page.waitForResponse(response => response.url().endsWith('provider=telegram'))
  release()
  await (await oldResponse).finished()
  await expect(page.getByText('No test run', { exact: true })).toBeVisible()
  await expect(page.getByText('Late Telegram result', { exact: true })).toHaveCount(0)
})

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

for (const [provider, service] of [['Telegram', 'telegram'], ['Matrix', 'matrix']]) {
test(`${provider} setup creates secret connection parameters once and recovers from errors`, async ({ page }, testInfo) => {
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
  await mount(page, 'core/params/components/MessagingSettingsPanel.vue', { privileges: ['TOOL_EDIT', 'CONNECTION_ACCESS'] })
  await page.getByRole('tab', { name: provider, exact: true }).click()
  const guide = page.getByRole('region', { name: 'Setup guide', exact: true })
  await expect(guide.getByRole('link', { name: 'Configure agent accounts', exact: true })).toHaveAttribute('href', '/tools?tab=connections')
  const create = page.getByRole('button', { name: `Create ${provider} Tool`, exact: true })
  await expect(guide.getByRole('alert')).toContainText(`Unable to prepare the ${provider} Tool`)
  await expect(create).toHaveCount(0)
  fail = false
  await guide.getByRole('button', { name: 'Retry', exact: true }).focus()
  await page.keyboard.press('Enter')
  if (service === 'matrix') {
    await expect(create).toBeDisabled()
    await expect(guide.getByRole('status')).toContainText('Enter the Matrix homeserver URL')
    expect(writes).toHaveLength(0)
    await page.evaluate(() => window.testApp.patchStore('core/params/stores/paramsStore.ts', 'useParamsStore', {
      params: [{ name: 'MESSENGER_MATRIX_HOMESERVER', value: 'https://matrix.example.test' }],
    }))
  }
  await expect(create).toBeEnabled()
  await create.click()
  await expect(guide.getByRole('link', { name: 'Open tools and connections', exact: true })).toBeVisible()
  expect(writes).toHaveLength(1)
  expect(writes[0]).toMatchObject({ code: service, label: provider,
    messenger_config: { service, settings: service === 'matrix' ? { homeserver: 'https://matrix.example.test' } : {}, param_map: { token: 'token' } },
  })
  expect(writes[0]).toMatchObject(service === 'telegram' ? {
    connection_schema: { params: { token: { type: 'password', required: true, default: '' } } },
  } : {
    messenger_config: { param_map: { user_id: 'user_id', token: 'token', password: 'password' } },
    connection_schema: { params: {
      user_id: { type: 'string', required: true, default: '' },
      token: { type: 'password', required: false, default: '' },
      password: { type: 'password', required: false, default: '' },
    } },
  })
  await page.screenshot({ path: testInfo.outputPath(`${service}-tool-ready-mobile.png`), fullPage: true })
  // Reopening checks persisted configuration before offering another creation.
  await page.getByRole('tab', { name: 'WhatsApp', exact: true }).click()
  await page.getByRole('tab', { name: provider, exact: true }).click()
  await expect(guide.getByRole('link', { name: 'Open tools and connections', exact: true })).toBeVisible()
  await expect(create).toHaveCount(0)
  expect(writes).toHaveLength(1)
  await setPrivileges(page, [])
  await expect(page.getByRole('link', { name: 'Open tools and connections', exact: true })).toHaveCount(0)
})

test(`${provider} setup preserves an existing Tool with conflicting configuration`, async ({ page }) => {
  const requests = []
  await page.route('**/api/tools', route => {
    requests.push(route.request().method())
    return route.fulfill({ json: [{ id: 83, code: service, label: 'Synthetic existing Tool',
      messenger_config: null, connection_schema: { params: {} } }] })
  })
  await mount(page, `app/tools/components/${provider}ToolSetup.vue`, { privileges: [] })
  await expect(page.getByRole('button', { name: `Create ${provider} Tool` })).toHaveCount(0)
  await setPrivileges(page, ['TOOL_EDIT'])
  await expect(page.getByRole('status')).toContainText('already used by a Tool with different settings')
  await expect(page.getByRole('button', { name: `Create ${provider} Tool` })).toHaveCount(0)
  expect(requests).toEqual(['GET'])
})

test(`${provider} setup never offers creation when another code already uses the bridge`, async ({ page }) => {
  const requests = []
  let release
  const pending = new Promise(resolve => { release = resolve })
  await page.route('**/api/tools', async route => {
    requests.push(route.request().method())
    await pending
    await route.fulfill({ json: [{ id: 84, code: 'synthetic_legacy_messaging', label: 'Existing channel',
      messenger_config: { service, settings: {}, param_map: { token: 'bot_secret' } },
      connection_schema: { params: { bot_secret: { type: 'password', required: true, default: '' } } } }] })
  })
  await mount(page, `app/tools/components/${provider}ToolSetup.vue`, { privileges: ['TOOL_EDIT'] })
  const create = page.getByRole('button', { name: `Create ${provider} Tool`, exact: true })
  await expect(create).toHaveCount(0)
  release()
  // Existing channels no longer show a confirmation message; keep the usable action.
  await expect(page.getByRole('link', { name: 'Open tools and connections', exact: true })).toBeVisible()
  await expect(create).toHaveCount(0)
  expect(requests).toEqual(['GET'])
})

test(`${provider} setup rechecks the bridge before creation to avoid a newly configured Tool`, async ({ page }) => {
  let checks = 0
  const writes = []
  await page.route('**/api/tools', route => {
    if (route.request().method() !== 'GET') writes.push(route.request().method())
    checks += 1
    return route.fulfill({ json: checks === 1 ? [] : [{ id: 85, code: 'synthetic_added_later', label: 'New channel',
      messenger_config: { service, settings: {}, param_map: {} } }] })
  })
  await mount(page, `app/tools/components/${provider}ToolSetup.vue`, { privileges: ['TOOL_EDIT'] })
  if (service === 'matrix') await page.evaluate(() => window.testApp.setProps({
    settings: { MESSENGER_MATRIX_HOMESERVER: 'https://matrix.example.test' },
  }))
  await page.getByRole('button', { name: `Create ${provider} Tool`, exact: true }).click()
  await expect(page.getByRole('link', { name: 'Open tools and connections', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: `Create ${provider} Tool` })).toHaveCount(0)
  expect(writes).toEqual([])
})
}

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
