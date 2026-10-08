import { test, expect, mount, jsonRoute, setPrivileges } from './fixtures.mjs'

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

for (const mobile of [false, true]) {
  for (const defaultState of ['enabled', 'disabled', 'ask']) {
    test(`Global function policies are explicit and connections can inherit (${mobile ? 'mobile' : 'desktop'}, ${defaultState})`, async ({ page }) => {
      await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
      await routes(page)
      await jsonRoute(page, '**/api/connections?*', [connections[4]])
      const locale = mobile ? 'fr' : 'en'
      const labels = mobile
        ? { enabled: 'Activé', disabled: 'Désactivé', ask: 'Sur demande', inherit: 'Hériter', global: 'Global (tous)', connection: 'Cette connexion' }
        : { enabled: 'Enabled', disabled: 'Disabled', ask: 'Ask', inherit: 'Inherit', global: 'Global (all)', connection: 'This connection' }
      const policy = {
        key: 'tool:external_read', name: 'external_read', description: 'Read synthetic content.', capability_kind: 'tool',
        connection_state: 'enabled', global_state: 'default', default_state: defaultState,
        effective_state: 'enabled', effective: true, state_source: 'connection',
      }
      const writes = []
      let finishFirstWrite
      const firstWriteReady = new Promise(resolve => { finishFirstWrite = resolve })
      await page.route('**/api/connections/5/functions', route => route.fulfill({ json: {
        success: true, message: '', functions: [policy, {
          ...policy, key: 'tool:external_list', name: 'external_list',
          connection_state: 'default', global_state: 'enabled',
          effective_state: 'enabled', state_source: 'tool',
        }],
      } }))
      await page.route('**/api/connections/5/capabilities', async route => {
        const request = route.request().postDataJSON()
        writes.push(request)
        if (writes.length === 1) await firstWriteReady
        policy[request.global_policy ? 'global_state' : 'connection_state'] = request.state
        if (request.global_policy && request.inherit_connection) policy.connection_state = 'default'
        const globalState = policy.global_state === 'default' ? policy.default_state : policy.global_state
        policy.effective_state = policy.connection_state === 'default' ? globalState : policy.connection_state
        policy.effective = policy.effective_state !== 'disabled'
        policy.state_source = policy.connection_state === 'default' ? 'tool' : 'connection'
        return route.fulfill({ json: { ...policy, local_override_count: policy.connection_state === 'default' ? 0 : 1 } })
      })
      await mount(page, 'app/connection/components/AuthorizationManager.vue', { locale, privileges })
      const global = page.getByRole('group', { name: `${labels.global}: external_read`, exact: true })
      const local = page.getByRole('group', { name: `${labels.connection}: external_read`, exact: true })
      const otherGlobal = page.getByRole('group', { name: `${labels.global}: external_list`, exact: true })
      // A local override leaves no global button selected, while both groups stay usable.
      for (const button of await global.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      await expect(local.getByRole('button', { name: labels.enabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await global.getByRole('button').all()) await expect(button).toBeEnabled()
      for (const button of await otherGlobal.getByRole('button').all()) await expect(button).toBeEnabled()
      expect(writes).toEqual([])
      const row = page.locator(mobile ? '.authorization-mobile-card' : 'tbody tr').filter({ hasText: 'external_read' })
      await setPrivileges(page, ['CONNECTION_ACCESS'])
      await expect(row.getByRole('group')).toHaveCount(0)
      await expect(row.getByText(labels.inherit, { exact: true })).toHaveCount(0)
      await expect(row.getByText(labels[defaultState], { exact: true }).first()).toBeVisible()
      await setPrivileges(page, privileges)
      await expect(global.getByRole('button')).toHaveCount(3)
      await expect(global.getByRole('button', { name: labels.inherit, exact: true })).toHaveCount(0)
      for (const state of ['enabled', 'disabled', 'ask']) {
        await expect(global.getByRole('button', { name: labels[state], exact: true })).toBeVisible()
        await expect(global.getByRole('button', { name: labels[state], exact: true })).toBeEnabled()
      }
      await expect(local.getByRole('button')).toHaveCount(3)
      await expect(local.getByRole('button', { name: labels.inherit, exact: true })).toHaveCount(0)
      // Clicking a global choice saves it and clears this connection's override together.
      await global.getByRole('button', { name: labels[defaultState], exact: true }).click()
      await expect.poll(() => writes).toEqual([
        { function_name: 'external_read', state: defaultState, capability_kind: 'tool', global_policy: true, inherit_connection: true },
      ])
      for (const group of [global, local]) {
        for (const button of await group.getByRole('button').all()) await expect(button).toBeEnabled()
      }
      await expect(global.getByRole('button', { name: labels[defaultState], exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      for (const button of await otherGlobal.getByRole('button').all()) await expect(button).toBeEnabled()
      // More choices remain usable before the first response. Global writes must
      // still take effect even if the user's final choice is a local override.
      await local.getByRole('button', { name: labels.ask, exact: true }).click()
      await expect(local.getByRole('button', { name: labels.ask, exact: true })).toHaveAttribute('aria-pressed', 'true')
      await global.getByRole('button', { name: labels.disabled, exact: true }).click()
      await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      await local.getByRole('button', { name: labels.enabled, exact: true }).click()
      await expect(local.getByRole('button', { name: labels.enabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await global.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      expect(writes).toHaveLength(1)
      finishFirstWrite()
      await expect(local).toHaveAttribute('aria-busy', 'false')
      expect(writes).toEqual([
        { function_name: 'external_read', state: defaultState, capability_kind: 'tool', global_policy: true, inherit_connection: true },
        { function_name: 'external_read', state: 'ask', capability_kind: 'tool' },
        { function_name: 'external_read', state: 'disabled', capability_kind: 'tool', global_policy: true, inherit_connection: true },
        { function_name: 'external_read', state: 'enabled', capability_kind: 'tool' },
      ])
      expect(policy.global_state).toBe('disabled')
      expect(policy.connection_state).toBe('enabled')
      await expect(local.getByRole('button', { name: labels.enabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      await global.getByRole('button', { name: labels.disabled, exact: true }).focus()
      await page.keyboard.press('Enter')
      await expect(global).toHaveAttribute('aria-busy', 'false')
      expect(writes).toHaveLength(5)
      await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const state of ['enabled', 'ask', 'disabled']) {
        await local.getByRole('button', { name: labels[state], exact: true }).click()
        await expect.poll(() => writes.at(-1)).toEqual({ function_name: 'external_read', state, capability_kind: 'tool' })
        for (const button of await global.getByRole('button').all()) await expect(button).toBeEnabled()
        for (const button of await otherGlobal.getByRole('button').all()) await expect(button).toBeEnabled()
        for (const button of await global.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
        await expect(mobile
          ? row.getByText(labels[state], { exact: true })
          : row.getByRole('cell', { name: labels[state], exact: true })).toBeVisible()
        await global.getByRole('button', { name: labels.disabled, exact: true }).click()
        await expect.poll(() => writes.at(-1)).toEqual({ function_name: 'external_read', state: 'disabled', capability_kind: 'tool', global_policy: true, inherit_connection: true })
        for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
        for (const button of await global.getByRole('button').all()) await expect(button).toBeEnabled()
        await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      }
      for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      await expect(mobile
        ? row.getByText(labels.disabled, { exact: true })
        : row.getByRole('cell', { name: labels.disabled, exact: true })).toBeVisible()
      await expect(global).toHaveAttribute('aria-busy', 'false')
      await mount(page, 'app/connection/components/AuthorizationManager.vue', { locale, privileges })
      await expect(global.getByRole('button', { name: labels.disabled, exact: true })).toHaveAttribute('aria-pressed', 'true')
      for (const button of await local.getByRole('button').all()) await expect(button).toHaveAttribute('aria-pressed', 'false')
      await setPrivileges(page, ['CONNECTION_ACCESS'])
      await expect(row.getByRole('group')).toHaveCount(0)
      await expect(row.getByText(labels.inherit, { exact: true })).toHaveCount(1)
      await expect(row.getByText(labels.disabled, { exact: true }).first()).toBeVisible()
    })
  }
}

for (const mobile of [false, true]) {
  test(`Policy saves survive failures, connection changes and reopening (${mobile ? 'mobile' : 'desktop'})`, async ({ page }) => {
    await page.setViewportSize({ width: mobile ? 390 : 1400, height: 1000 })
    await routes(page)
    const second = { id: 12, tool_id: 5, agent_id: 7, active: true }
    await jsonRoute(page, '**/api/connections?*', [connections[4], second])
    const names = ['external_read', 'external_list']
    const globals = Object.fromEntries(names.map(name => [name, 'enabled']))
    const locals = { 5: { external_read: 'default', external_list: 'default' }, 12: { external_read: 'ask', external_list: 'default' } }
    const resolve = (id, name) => ({
      key: `tool:${name}`, name, description: 'Synthetic capability.', capability_kind: 'tool',
      connection_state: locals[id][name], global_state: globals[name], default_state: 'enabled',
      effective_state: locals[id][name] === 'default' ? globals[name] : locals[id][name],
      effective: (locals[id][name] === 'default' ? globals[name] : locals[id][name]) !== 'disabled',
      state_source: locals[id][name] === 'default' ? 'tool' : 'connection',
    })
    const reads = [], writes = []
    let gate = null, outcome = 'success'
    function holdNextWrite(result = 'success') {
      outcome = result
      let release
      gate = new Promise(resolve => { release = resolve })
      return () => release()
    }
    for (const id of [5, 12]) {
      await page.route(`**/api/connections/${id}/functions`, route => {
        reads.push(id)
        return route.fulfill({ json: { success: true, message: '', functions: names.map(name => resolve(id, name)) } })
      })
      await page.route(`**/api/connections/${id}/capabilities`, async route => {
        const request = route.request().postDataJSON()
        const waiting = gate, result = outcome
        gate = null; outcome = 'success'
        writes.push({ id, ...request })
        if (waiting) await waiting
        if (result !== 'reject') {
          if (request.global_policy) globals[request.function_name] = request.state
          if (!request.global_policy || request.inherit_connection) locals[id][request.function_name] = request.global_policy ? 'default' : request.state
        }
        return route.fulfill(result === 'success'
          ? { json: resolve(id, request.function_name) }
          : { status: 500, json: { detail: 'Synthetic save failure' } })
      })
    }
    await mount(page, 'app/connection/components/AuthorizationManager.vue', { privileges })
    const selector = page.getByRole('combobox').nth(2)
    // Equal labels are intentional: choose by option position to select each connection.
    async function selectConnection(index) {
      await selector.click()
      await page.getByRole('option', { name: 'Alice Example — Optional Tool', exact: true }).nth(index).click()
    }
    await selectConnection(0)
    const global = page.getByRole('group', { name: 'Global (all): external_read', exact: true })
    const local = page.getByRole('group', { name: 'This connection: external_read', exact: true })
    const otherLocal = page.getByRole('group', { name: 'This connection: external_list', exact: true })
    const releaseGlobal = holdNextWrite()
    await global.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    await local.getByRole('button', { name: 'Ask', exact: true }).click()
    await otherLocal.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect(otherLocal).toHaveAttribute('aria-busy', 'false')
    expect(writes.map(write => write.function_name)).toEqual(['external_read', 'external_list'])
    await selectConnection(1)
    await expect(local).toHaveCount(0)
    expect(reads).toEqual([5])
    releaseGlobal()
    await expect(local.getByRole('button', { name: 'Ask', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(reads).toEqual([5, 12])
    expect(locals[5].external_read).toBe('ask')
    expect(globals.external_read).toBe('disabled')
    expect(writes.map(write => write.id)).toEqual([5, 5, 5])
    // A rejected older choice must not discard the newer queued choice.
    const releaseRejected = holdNextWrite('reject')
    await local.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(4)
    await local.getByRole('button', { name: 'Enabled', exact: true }).click()
    await expect(local.getByRole('button', { name: 'Enabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    releaseRejected()
    await expect(local).toHaveAttribute('aria-busy', 'false')
    expect(locals[12].external_read).toBe('enabled')
    await expect(local.getByRole('button', { name: 'Enabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    // An error can occur after persistence. Read back the actual saved rule.
    const releaseLost = holdNextWrite('committed_error')
    await local.getByRole('button', { name: 'Disabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(6)
    releaseLost()
    await expect.poll(() => reads).toEqual([5, 12, 12])
    await expect(local.getByRole('button', { name: 'Disabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await local.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(local).toHaveAttribute('aria-busy', 'false')
    expect(locals[12].external_read).toBe('ask')
    // Reopening the component retains the ordered writes and waits before reading.
    const releaseReopened = holdNextWrite()
    await local.getByRole('button', { name: 'Enabled', exact: true }).click()
    await expect.poll(() => writes.length).toBe(8)
    await local.getByRole('button', { name: 'Disabled', exact: true }).click()
    await jsonRoute(page, '**/api/connections?*', [second])
    await page.evaluate(async privileges => {
      await window.testApp.mount({ component: 'app/connection/components/AuthorizationManager.vue', privileges })
    }, privileges)
    await expect(local).toHaveCount(0)
    expect(reads).toEqual([5, 12, 12])
    releaseReopened()
    await expect(local.getByRole('button', { name: 'Disabled', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(locals[12].external_read).toBe('disabled')
    expect(writes.at(-1)).toMatchObject({ id: 12, state: 'disabled' })
    expect(locals[5].external_list).toBe('disabled')
  })
}

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
  await row.getByRole('group', { name: 'This connection: system_read' }).getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => writes).toEqual([{ function_name: 'system_read', state: 'ask', capability_kind: 'tool' }])
  await expect(row).toContainText('Ask')
})
}
