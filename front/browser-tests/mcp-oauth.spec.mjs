import { test, expect, mount, jsonRoute } from './fixtures.mjs'

test('device authorization completes without a local script and respects the polling interval', async ({ page, context }) => {
  let approved = false
  let connected = false
  let polls = 0
  await page.route('**/api/connections/42/oauth', route => route.fulfill({ json: { connected, pending: false, reconnect_required: false } }))
  await page.route('**/api/connections/42/oauth/start', route => {
    expect(route.request().postDataJSON().browser_origin).toBe('http://localhost:8000')
    return route.fulfill({ json: { method: 'device', authorization_url: '', device: {
      state: 'synthetic-device-state-00000001', user_code: 'SYNTHETIC-CODE', interval: 1,
      verification_uri: 'http://localhost:8000/synthetic-device-provider',
    } } })
  })
  await page.route('**/api/connections/42/oauth/device', route => {
    expect(route.request().postDataJSON()).toEqual({ state: 'synthetic-device-state-00000001' })
    polls++
    connected = approved
    return route.fulfill({ json: { connected, interval: 2 } })
  })
  await context.route('**/synthetic-device-provider', route => route.fulfill({ contentType: 'text/html', body:
    '<p>SYNTHETIC-CODE</p><button onclick="fetch(\'/synthetic-device-approve\', {method: \'POST\'}).then(() => this.textContent = \'Approved\')">Approve synthetic access</button>' }))
  await context.route('**/synthetic-device-approve', route => { approved = true; return route.fulfill({ body: 'Approved' }) })
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: true } })
  await page.clock.install()
  await page.getByRole('button', { name: 'Connect account', exact: true }).click()
  await expect(page.getByText('SYNTHETIC-CODE', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download connection relay', exact: true })).toHaveCount(0)
  await page.clock.runFor(1000)
  await expect.poll(() => polls).toBe(1)
  await page.clock.runFor(1000)
  expect(polls).toBe(1)
  const opening = page.waitForEvent('popup')
  await page.getByRole('link', { name: 'Authorize with the provider', exact: true }).click()
  const provider = await opening
  await provider.getByRole('button', { name: 'Approve synthetic access', exact: true }).click()
  await expect(provider.getByRole('button', { name: 'Approved', exact: true })).toBeVisible()
  await provider.close()
  await page.clock.runFor(1000)
  await expect(page.getByRole('status')).toHaveText('Account connected')
  expect(polls).toBe(2)
})

test('pre-registered client setup appears only after automatic setup is unavailable', async ({ page }) => {
  let starts = 0
  await jsonRoute(page, '**/api/connections/42/oauth', { connected: false, pending: false, reconnect_required: false })
  await page.route('**/api/connections/42/oauth/start', route => {
    starts++
    if (starts === 1) return route.fulfill({ json: { method: 'configure', authorization_url: '',
      redirect_uri: 'http://localhost:8000/connection/oauth-callback' } })
    expect(route.request().postDataJSON().client).toEqual({ client_id: 'synthetic-client', client_secret: 'synthetic-secret' })
    return route.fulfill({ json: { authorization_url: 'http://localhost:8000/synthetic-account-login?state=synthetic-manual-client-state-0001' } })
  })
  await page.route('**/synthetic-account-login?*', route => route.fulfill({ contentType: 'text/html', body: 'Synthetic account sign-in' }))
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: true } })
  await expect(page.getByLabel('Application identifier (Client ID)', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Connect account', exact: true }).click()
  const submit = page.getByRole('button', { name: 'Connect with this application', exact: true })
  await submit.click()
  await expect(page.getByText('Enter the Client ID.', { exact: true })).toBeVisible()
  expect(starts).toBe(1)
  await page.getByLabel('Application identifier (Client ID)', { exact: true }).fill('synthetic-client')
  await page.getByLabel('Application secret (if required)', { exact: true }).fill('synthetic-secret')
  await submit.click()
  await expect(page.getByText('Synthetic account sign-in', { exact: true })).toBeVisible()
  expect(starts).toBe(2)
})

test('leaving a device authorization aborts its pending poll and ignores a late result', async ({ page }) => {
  await jsonRoute(page, '**/api/connections/42/oauth', { connected: false, pending: false, reconnect_required: false })
  await jsonRoute(page, '**/api/connections/84/oauth', { connected: false, pending: false, reconnect_required: false })
  await jsonRoute(page, '**/api/connections/42/oauth/start', { method: 'device', authorization_url: '', device: {
    state: 'synthetic-device-late-state-00001', user_code: 'SYNTHETIC-CODE', interval: 1,
    verification_uri: 'https://oauth.example.test/activate',
  } })
  let received
  let polls = 0
  const pending = new Promise(resolve => { received = resolve })
  await page.route('**/api/connections/42/oauth/device', route => { polls++; received(route) })
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: true } })
  await page.clock.install()
  await page.getByRole('button', { name: 'Connect account', exact: true }).click()
  await expect(page.getByText('SYNTHETIC-CODE', { exact: true })).toBeVisible()
  await page.clock.runFor(1000)
  const request = await pending
  await page.evaluate(() => window.testApp.setProps({ connectionId: 84 }))
  await expect(page.getByRole('status')).toHaveText('No account connected')
  await request.fulfill({ json: { connected: true, interval: 1 } })
  await page.clock.runFor(10_000)
  await expect(page.getByRole('status')).toHaveText('No account connected')
  await expect(page.getByText('SYNTHETIC-CODE', { exact: true })).toHaveCount(0)
  expect(polls).toBe(1)
})

test('local OAuth relay downloads on the browser computer and completes in a new tab', async ({ page, context }) => {
  const state = 'synthetic-local-oauth-state-000001'
  const script = '# Synthetic standalone OAuth relay\n'
  await jsonRoute(page, '**/api/connections/42/oauth', { connected: false, pending: false, reconnect_required: false })
  await jsonRoute(page, '**/api/connections/42/oauth/start', {
    authorization_url: `https://oauth.example.test/authorize?state=${state}`,
    local_script: script,
  })
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: true } })
  await page.getByRole('button', { name: 'Connect account', exact: true }).click()
  await expect(page.getByText('Connect from this computer', { exact: true })).toBeVisible()
  await expect(page.getByRole('status')).toHaveText('Connecting account')
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download connection relay', exact: true }).click()
  const download = await downloading
  expect(download.suggestedFilename()).toBe('galaris-connect.py')
  const stream = await download.createReadStream()
  let contents = ''
  for await (const chunk of stream) contents += chunk.toString()
  expect(contents).toBe(script)

  const callbackPage = await context.newPage()
  const errors = []
  callbackPage.on('pageerror', error => errors.push(error.message))
  let callbacks = 0
  await callbackPage.route('**/api/connections/42/oauth/callback', route => {
    expect(route.request().postDataJSON()).toEqual({ state, code: 'synthetic-relayed-code', error: '', iss: 'https://oauth.example.test' })
    callbacks++
    return route.fulfill({ status: 204 })
  })
  await callbackPage.goto(`/test-support/browser/index.html?state=${state}&code=synthetic-relayed-code&iss=https%3A%2F%2Foauth.example.test`)
  await callbackPage.waitForFunction(() => window.testApp?.mount)
  // The relay opens a separate tab with no copy of the initiator's sessionStorage.
  expect(await callbackPage.evaluate(() => sessionStorage.length)).toBe(0)
  await callbackPage.evaluate(() => window.testApp.mount({ component: 'app/connection/pages/oauth-callback.vue' }))
  await expect(callbackPage.getByRole('status')).toContainText('MCP connection authorized')
  expect(callbackPage.url()).not.toContain('synthetic-relayed-code')
  expect(callbacks).toBe(1)
  expect(await callbackPage.evaluate(state => localStorage.getItem(`galaris:mcp-oauth-local:${state}`), state)).toBeNull()
  expect(errors).toEqual([])
  await callbackPage.close()
})

for (const scenario of ['listed', 'hidden', 'concurrent', 'edited']) {
test(`OAuth reuses an existing connection and its saved parameters (${scenario})`, async ({ page }) => {
  const existing = { id: 42, agent_id: 7, tool_id: 19, active: false }
  const writes = []
  let starts = 0
  let lookups = 0
  let savedRegion = 'us'
  await page.route('**/api/connections/overview?*', route => route.fulfill({ json: scenario === 'listed'
    ? [{ ...existing, params: { region: savedRegion, secret: null }, configured_params: ['secret'] }] : [] }))
  await jsonRoute(page, '**/api/tools', [{ id: 19, code: 'synthetic_mcp', label: 'Synthetic MCP', has_mcp: true,
    mcp_config: { type: 'http', auth: { type: 'none' } },
    global_params: { secret: { configured: true, value: null, forced: false } }, connection_schema: { params: {
      region: { type: 'string', label: 'Service region', default: 'eu', required: false },
      secret: { type: 'password', label: 'Service secret', required: false },
    } } }])
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await page.route('**/api/connections?*', route => {
    const params = new URL(route.request().url()).searchParams
    const targeted = params.get('agent_id') === '7' && params.get('tool_id') === '19'
    if (targeted) lookups++
    return route.fulfill({ json: scenario === 'listed' || (targeted && (scenario !== 'concurrent' || lookups > 1)) ? [existing] : [] })
  })
  await page.route('**/api/connections', route => {
    writes.push({ method: route.request().method(), body: route.request().postDataJSON() })
    return route.fulfill({ status: 409, json: { detail: 'A synthetic connection already exists' } })
  })
  await page.route('**/api/connections/42', route => {
    const body = route.request().postDataJSON()
    writes.push({ method: route.request().method(), body })
    Object.assign(existing, body)
    return route.fulfill({ json: existing })
  })
  await page.route('**/api/connections/42/params?*', route => route.fulfill({ json: {
    connection_id: 42, tool_id: 19, agent_id: 7,
    params: { region: savedRegion, secret: null }, configured_params: ['region', 'secret'],
  } }))
  await page.route('**/api/connections/42/params/bulk', route => {
    const body = route.request().postDataJSON()
    writes.push({ method: route.request().method(), body })
    savedRegion = body.params.region
    return route.fulfill({ json: [] })
  })
  await jsonRoute(page, '**/api/connections/42/oauth', { connected: false, pending: false, reconnect_required: false })
  await page.route('**/api/connections/42/oauth/start', route => {
    starts++
    return route.fulfill(starts === 1
      ? { status: 400, json: { detail: 'Synthetic authorization provider failure' } }
      : { json: { authorization_url: 'http://localhost:8000/synthetic-account-login?state=synthetic-reused-account-state-0001' } })
  })
  await page.route('**/synthetic-account-login?*', route => route.fulfill({ contentType: 'text/html', body: 'Synthetic account sign-in' }))
  await mount(page, 'app/connection/components/ConnectionList.vue', {
    privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL'],
  })
  await page.getByRole('button', { name: 'New Connection', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic Agent', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Tool', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic MCP', exact: true }).click()
  await dialog.getByRole('button', { name: 'Connect account', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Synthetic authorization provider failure')
  await expect(dialog.getByLabel('Service region', { exact: true })).toHaveValue('us')
  if (scenario === 'edited') await dialog.getByLabel('Service region', { exact: true }).fill('ap')
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('Synthetic account sign-in', { exact: true })).toBeVisible()
  expect(starts).toBe(2)
  expect(writes).toEqual([
    ...(scenario === 'concurrent' ? [{ method: 'POST', body: { agent_id: 7, tool_id: 19, active: true } }] : []),
    { method: 'PATCH', body: { active: true } },
    ...(scenario === 'edited' ? [
      { method: 'PATCH', body: { agent_id: 7, tool_id: 19, active: true } },
      { method: 'POST', body: { connection_id: 42, params: { region: 'ap' } } },
    ] : []),
  ])
})
}

// Transport compatibility is owned by the connection, without Tool OAuth settings.
test('OAuth retries a parameter save without recreating the connection or losing the draft', async ({ page }) => {
  const connections = []
  await page.route('**/api/connections/overview?*', route => route.fulfill({ json: connections.map(connection => ({ ...connection, params: {}, configured_params: [] })) }))
  let creations = 0
  let parameterWrites = 0
  let starts = 0
  await jsonRoute(page, '**/api/tools', [{ id: 19, code: 'synthetic_mcp', label: 'Synthetic MCP', has_mcp: true,
    mcp_config: { type: 'http', auth: { type: 'none' } },
    connection_schema: { params: { region: { type: 'string', label: 'Service region', required: false } } } }])
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
  await jsonRoute(page, '**/api/mail/approvers', [])
  await page.route('**/api/connections?*', route => route.fulfill({ json: connections }))
  await page.route('**/api/connections', route => {
    creations++
    const connection = { id: 42, ...route.request().postDataJSON() }
    connections.push(connection)
    return route.fulfill({ json: connection })
  })
  await page.route('**/api/connections/42', route => route.fulfill({ json: { id: 42, ...route.request().postDataJSON() } }))
  await page.route('**/api/connections/42/params/bulk', route => {
    parameterWrites++
    expect(route.request().postDataJSON().params).toEqual({ region: 'us' })
    return route.fulfill(parameterWrites === 1
      ? { status: 503, json: { detail: 'Synthetic parameter save failure' } }
      : { json: [] })
  })
  await jsonRoute(page, '**/api/connections/42/params?*', { connection_id: 42, tool_id: 19, agent_id: 7,
    params: { region: 'us' }, configured_params: ['region'] })
  await page.route('**/api/connections/42/oauth/start', route => {
    starts++
    return route.fulfill(starts === 1
      ? { status: 400, json: { detail: 'Synthetic authorization provider failure' } }
      : { json: { authorization_url: 'http://localhost:8000/synthetic-account-login?state=synthetic-new-account-state-0001' } })
  })
  await page.route('**/synthetic-account-login?*', route => route.fulfill({ contentType: 'text/html', body: 'Synthetic account sign-in' }))
  await mount(page, 'app/connection/components/ConnectionList.vue', {
    privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL'],
  })
  await page.getByRole('button', { name: 'New Connection', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic Agent', exact: true }).click()
  await dialog.getByRole('combobox', { name: 'Tool', exact: true }).click()
  await page.getByRole('option', { name: 'Synthetic MCP', exact: true }).click()
  await dialog.getByLabel('Service region', { exact: true }).fill('us')
  await dialog.getByRole('button', { name: 'Connect account', exact: true }).click()
  const alert = dialog.getByRole('alert').filter({ has: page.getByRole('button', { name: 'Retry', exact: true }) })
  await expect(alert).toContainText('Synthetic parameter save failure')
  expect(starts).toBe(0)
  await alert.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(alert).toContainText('Synthetic authorization provider failure')
  await expect(dialog.getByLabel('Service region', { exact: true })).toHaveValue('us')
  await alert.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByText('Synthetic account sign-in', { exact: true })).toBeVisible()
  expect(creations).toBe(1)
  expect(parameterWrites).toBe(2)
  expect(starts).toBe(2)
})

for (const transport of ['http', 'sse', 'stdio']) {
  test(`account authorization belongs to the ${transport} connection`, async ({ page }) => {
    await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
    await jsonRoute(page, '**/api/connections/42/oauth', { connected: false, pending: false, reconnect_required: false })
    await mount(page, 'app/connection/components/ConnectionForm.vue', {
      privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL'],
      props: {
        connection: { id: 42, agent_id: 7, tool_id: 19, active: true },
        agentOptions: [{ value: 7, label: 'Synthetic agent', agentDriver: 'internal' }],
        toolOptions: [{ id: 19, label: 'Synthetic MCP' }],
        tools: [{ id: 19, code: 'synthetic_mcp', label: 'Synthetic MCP', has_mcp: true,
          mcp_config: { type: transport, auth: { type: 'none' } }, connection_schema: { params: {} } }],
      },
    })
    const button = page.getByRole('button', { name: 'Connect account', exact: true })
    if (transport === 'stdio') await expect(button).toHaveCount(0)
    else await expect(button).toBeEnabled()
  })
}

for (const changeConnection of [false, true]) {
test(`account authorization saves first and retries errors (connection changes: ${changeConnection})`, async ({ page }) => {
  await jsonRoute(page, '**/api/agents?*', [{ id: 7, first_name: 'Synthetic', last_name: 'Agent', agent_driver: 'internal' }])
  await jsonRoute(page, '**/api/connections/84/oauth', { connected: false, pending: false, reconnect_required: false })
  const starts = []
  await page.route('**/api/connections/*/oauth/start', route => {
    starts.push(new URL(route.request().url()).pathname)
    return route.fulfill({ json: { authorization_url: 'http://localhost:8000/synthetic-account-login?state=synthetic-account-state-000001' } })
  })
  await page.route('**/synthetic-account-login?*', route => route.fulfill({ contentType: 'text/html', body: 'Synthetic account sign-in' }))
  await mount(page, 'app/connection/components/ConnectionForm.vue', {
    privileges: ['CONNECTION_ACCESS', 'CONNECTION_EDIT', 'AGENT_MANAGE_ALL'],
    props: {
      defaultAgentId: 7, defaultToolId: 19,
      agentOptions: [{ value: 7, label: 'Synthetic agent', agentDriver: 'internal' }],
      toolOptions: [{ id: 19, label: 'Synthetic MCP' }],
      tools: [{ id: 19, code: 'synthetic_mcp', label: 'Synthetic MCP', has_mcp: true,
        mcp_config: { type: 'http', auth: { type: 'none' } }, connection_schema: { params: {} } }],
    },
  })
  await page.evaluate(() => window.testApp.setProps({ persistForAction: async payload => {
    window.connectionSaveAttempts ??= 0
    window.connectionSaveAttempts++
    if (window.connectionSaveAttempts === 1) throw new Error('Synthetic save failure')
    if (payload.data.agent_id !== 7 || payload.data.tool_id !== 19 || !payload.data.active) throw new Error('Incorrect connection')
    if (window.connectionSaveAttempts === 2) return new Promise(resolve => {
      window.releaseConnectionSave = () => resolve({ id: 42, ...payload.data })
    })
    if (payload.id !== 84) throw new Error('A stale save changed the current connection')
    return { id: payload.id, ...payload.data }
  } }))
  const connect = page.getByRole('button', { name: 'Connect account', exact: true })
  await connect.click()
  await expect(page.getByRole('alert').filter({ has: page.getByRole('button', { name: 'Retry', exact: true }) })).toBeVisible()
  expect(starts).toEqual([])
  await connect.click()
  await page.waitForFunction(() => !!window.releaseConnectionSave)
  if (changeConnection) await page.evaluate(() => window.testApp.setProps({ connection: { id: 84, agent_id: 7, tool_id: 19, active: true } }))
  await page.evaluate(() => window.releaseConnectionSave())
  if (changeConnection) {
    await expect(connect).toBeEnabled()
    expect(starts).toEqual([])
    await connect.click()
  }
  await expect(page.getByText('Synthetic account sign-in', { exact: true })).toBeVisible()
  expect(starts).toEqual([`/api/connections/${changeConnection ? 84 : 42}/oauth/start`])
})
}

for (const width of [1440, 390]) {
  test(`OAuth authorizes through the browser and disconnects after reopening (${width})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = 'synthetic-oauth-browser-state-000001'
    let connected = false
    let callbacks = 0
    await page.route('**/api/connections/42/oauth', route => {
      if (route.request().method() === 'DELETE') {
        connected = false
        return route.fulfill({ status: 204 })
      }
      return route.fulfill({ json: { connected, pending: false, reconnect_required: false,
        redirect_uri: 'https://galaris.example.test/connection/oauth-callback' } })
    })
    await page.route('**/api/connections/42/oauth/start', route => route.fulfill({ json: {
      authorization_url: `http://localhost:8000/synthetic-oauth-provider?state=${state}`,
    } }))
    await page.route('**/synthetic-oauth-provider?*', route => route.fulfill({ contentType: 'text/html', body:
      `<a href="/test-support/browser/index.html?state=${state}&code=synthetic-code">Approve synthetic access</a>` }))
    await page.route('**/api/connections/42/oauth/callback', route => {
      const body = route.request().postDataJSON()
      expect(body).toEqual({ state, code: 'synthetic-code', error: '', iss: '' })
      connected = true
      callbacks++
      return route.fulfill({ status: 204 })
    })
    const component = 'app/connection/components/McpOAuthConnection.vue'
    const options = { props: { connectionId: 42, canEdit: true } }
    await mount(page, component, options)
    await expect(page.getByRole('status')).toHaveText('No account connected')
    await page.getByRole('button', { name: 'Connect account' }).focus()
    await page.keyboard.press('Enter')
    await page.getByRole('link', { name: 'Approve synthetic access' }).click()
    await page.waitForFunction(() => window.testApp?.mount)
    await page.evaluate(() => window.testApp.mount({ component: 'app/connection/pages/oauth-callback.vue' }))
    await expect(page.getByRole('status')).toContainText('MCP connection authorized')
    expect(page.url()).not.toContain('synthetic-code')
    expect(callbacks).toBe(1)
    await mount(page, component, options)
    await expect(page.getByRole('status')).toHaveText('Account connected')
    await page.getByRole('button', { name: 'Disconnect account' }).click()
    await expect(page.getByRole('status')).toHaveText('No account connected')
    await mount(page, component, options)
    await expect(page.getByRole('status')).toHaveText('No account connected')
    await page.screenshot({ path: `/artifacts/mcp-oauth-${width}.png` })
  })
}

for (const detail of ['Synthetic provider unavailable', '   ']) {
test(`OAuth displays provider failures and retries authorization (detail: ${JSON.stringify(detail)})`, async ({ page }) => {
  await page.route('**/api/connections/42/oauth', route => route.fulfill({ json: {
    connected: false, pending: false, reconnect_required: true, redirect_uri: 'https://galaris.example.test/connection/oauth-callback',
  } }))
  let attempts = 0
  await page.route('**/api/connections/42/oauth/start', route => {
    attempts++
    return route.fulfill({ status: 400, json: { detail } })
  })
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: true } })
  await expect(page.getByRole('status')).toHaveText('Reconnect your account')
  await page.getByRole('button', { name: 'Connect account' }).click()
  await expect(page.getByRole('alert')).toContainText(detail.trim() || 'HTTP 400')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect.poll(() => attempts).toBe(2)
  await expect(page.getByRole('alert')).toContainText(detail.trim() || 'HTTP 400')
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: false } })
  await expect(page.getByRole('status')).toHaveText('Reconnect your account')
  await expect(page.getByRole('button', { name: 'Connect account' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Disconnect account' })).toHaveCount(0)
})
}

test('closing the OAuth panel ignores a late authorization response', async ({ page }) => {
  await page.route('**/api/connections/42/oauth', route => route.fulfill({ json: {
    connected: false, pending: false, reconnect_required: false, redirect_uri: 'https://galaris.example.test/connection/oauth-callback',
  } }))
  let received
  const pending = new Promise(resolve => { received = resolve })
  await page.route('**/api/connections/42/oauth/start', route => received(route))
  const unexpected = []
  await page.route('**/synthetic-late-provider*', route => {
    unexpected.push(route.request().url())
    return route.fulfill({ body: 'Unexpected navigation' })
  })
  await mount(page, 'app/connection/components/McpOAuthConnection.vue', { props: { connectionId: 42, canEdit: true } })
  await page.getByRole('button', { name: 'Connect account' }).click()
  const request = await pending
  await page.evaluate(() => window.testApp.unmount())
  const finished = page.waitForEvent('requestfinished', request => request.url().endsWith('/oauth/start'))
  await request.fulfill({ json: { authorization_url: 'http://localhost:8000/synthetic-late-provider?state=synthetic-late-state-00001' } })
  await finished
  // Mounting again proves the original component's queued work has settled.
  await page.evaluate(() => window.testApp.mount({ component: 'app/connection/components/McpOAuthConnection.vue', props: { connectionId: 42, canEdit: true } }))
  await expect(page.getByRole('status')).toHaveText('No account connected')
  expect(unexpected).toEqual([])
})
