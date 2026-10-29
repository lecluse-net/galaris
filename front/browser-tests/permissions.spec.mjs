import { test, expect, mount, jsonRoute } from './fixtures.mjs'

const privileges = ['PERMISSION_ACCESS', 'PERMISSION_DECIDE', 'PERMISSION_REVOKE']
const names = {
  functions: 'Tool functions and prompts',
  network: 'Contacts and network access: requests and decisions', runtime: 'Harness action type decisions',
}
const empty = { connections: [], capabilities: [], unavailable_catalogs: [] }
const capability = (name, extra = {}) => ({ id: `14:tool:${name}`, tool_id: 14, tool_label: 'Synthetic topics', connection_id: 9,
  name, description: 'Synthetic capability', capability_kind: 'tool', connection_state: 'default', global_state: 'default',
  default_state: 'ask', effective_state: 'ask', policy_state: 'ask', policy_source: 'software', available: true, runtime_supported: true, ...extra })
const connection = { tool_id: 14, tool_code: 'topic', tool_label: 'Synthetic topics', description: 'Synthetic connection', connection_id: 9,
  active: true, can_disable: true, parameters: {} }
const decision = { id: 'remembered-contact', agent_id: 7, permission_key: 'messenger-contact:9:synthetic',
  question: 'Contact with Synthetic Visitor', allowed: false, can_decide: true, active: true, approver_label: 'Synthetic manager' }

async function setup(page, options = {}) {
  await jsonRoute(page, '**/api/agents/selection?scope=management', [{ id: 7, label: 'Synthetic agent' }, { id: 8, label: 'Other synthetic agent' }])
  await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [], total: 0 })
  await jsonRoute(page, '**/api/tools/action-authorizations/runtime-policies?*', [])
  await jsonRoute(page, '**/api/messenger/permissions?*', { items: [], total: 0, counts: {} })
  await jsonRoute(page, '**/api/tools/agents/*/permissions', empty)
  if (options.routes) await options.routes()
  await mount(page, 'app/connection/pages/permissions.vue', { route: options.route ?? '/permissions?agent_id=7', privileges: options.privileges ?? (options.readonly ? ['PERMISSION_ACCESS'] : privileges) })
}

for (const editable of [true, false]) test(`management scopes remain visible and ${editable ? 'editable with retry' : 'read-only without global delegation'}`, async ({ page }) => {
  const scope = { value: 'team', configured: null, default: 'team', description: '',
    options: [{ value: 'none', label: '' }, { value: 'team', label: '' }, { value: 'all', label: '' }] }
  const writes = []
  let fail = true
  await setup(page, { privileges: [...privileges, 'CONNECTION_EDIT', ...(editable ? ['AGENT_MANAGE_ALL'] : [])], routes: async () => {
    await page.route('**/api/tools/agents/7/permissions', route => route.fulfill({ json: {
      ...empty, connections: [{ ...connection, can_disable: false, management_scope: scope, parameters: { 'tools.management_scope': scope.value } }],
    } }))
    await page.route('**/api/connections/9/management-scope', route => {
      const data = route.request().postDataJSON(); writes.push(data)
      if (fail) { fail = false; return route.fulfill({ status: 500, json: {} }) }
      scope.configured = data.value; scope.value = data.value ?? scope.default
      return route.fulfill({ status: 204 })
    })
  } })
  const panel = page.getByRole('region', { name: names.functions })
  const select = panel.getByRole('group', { name: 'Scope for Synthetic topics (tools.management_scope)', exact: true })
  await expect(select).toBeVisible()
  await expect(select.getByRole('button', { name: 'Default: Team', exact: true })).toHaveAttribute('aria-pressed', 'true')
  if (!editable) { for (const button of await select.getByRole('button').all()) await expect(button).toBeDisabled(); expect(writes).toEqual([]); return }
  await expect(select.getByRole('button', { name: 'Personal', exact: true })).toHaveCount(0)
  await select.getByRole('button', { name: 'All', exact: true }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(select.getByRole('button', { name: 'Default: Team', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await select.getByRole('button', { name: 'All', exact: true }).click()
  await expect(select.getByRole('button', { name: 'All', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Refresh', exact: true }).first().click()
  await expect(select.getByRole('button', { name: 'All', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await select.getByRole('button', { name: 'Default: Team', exact: true }).click()
  await expect(select.getByRole('button', { name: 'Default: Team', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(writes).toEqual([{ value: 'all' }, { value: 'all' }, { value: null }])
})

for (const width of [390, 1440]) test(`one searchable dashboard manages inherited, blocked and pending rights at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 })
  const functions = Array.from({ length: 53 }, (_, index) => capability(index === 52 ? 'needle_function' : `synthetic_function_${index}`))
  functions.push(...['enabled', 'disabled', 'ask'].map(state => capability(`other_${state}`, {
    id: `17:tool:other_${state}`, tool_id: 17, tool_label: 'Synthetic second Tool', connection_id: 10,
    effective_state: state, policy_state: state,
  })))
  const connections = [connection,
    { ...connection, tool_id: 17, tool_code: 'second', tool_label: 'Synthetic second Tool', connection_id: 10 },
    { ...connection, tool_id: 15, tool_label: 'Disconnected service', connection_id: null, active: false }]
  connections.push(...Array.from({ length: 51 }, (_, index) => ({ ...connection,
    tool_id: 100 + index, connection_id: 100 + index, tool_code: `additional_${index}`, tool_label: `Additional synthetic Tool ${index}`,
  })))
  const calls = [], writes = [], activations = []
  const policy = { id: 'runtime-ask', agent_id: 7, runtime: 'hermes', capability_name: 'write_file', allowed: null,
    remembered: false, active: false, can_decide: true, can_revoke: false }
  await setup(page, { privileges: [...privileges, 'CONNECTION_EDIT'], routes: async () => {
    await page.route('**/api/tools/agents/7/permissions', route => {
      calls.push(route.request().url())
      return route.fulfill({ json: { connections, capabilities: functions, unavailable_catalogs: ['Offline external service'] } })
    })
    await jsonRoute(page, '**/api/tools/action-authorizations/runtime-policies?*', [policy])
    await page.route('**/api/connections/10', route => {
      const { active } = route.request().postDataJSON(); activations.push(active); connections[1].active = active
      for (const row of functions.filter(row => row.tool_id === 17)) row.effective_state = active ? row.policy_state : 'disabled'
      return route.fulfill({ json: { id: 10, tool_id: 17, agent_id: 7, active } })
    })
    await page.route('**/api/connections/9/capabilities', route => {
      const data = route.request().postDataJSON(); writes.push(data)
      const row = functions.find(item => item.name === data.function_name)
      row.connection_state = data.state
      row.effective_state = row.policy_state = data.state === 'default' ? row.default_state : data.state
      row.policy_source = data.state === 'default' ? 'software' : 'connection'
      return route.fulfill({ json: { ...row, name: row.name, effective: row.effective_state !== 'disabled' } })
    })
  } })
  await expect(page.getByRole('tab')).toHaveCount(0)
  for (const name of Object.values(names)) await expect(page.getByRole('region', { name, exact: true })).toBeVisible()
  await expect(page.getByText('Disconnected service', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Connect', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Configure', exact: true })).toHaveCount(0)
  const functionsPanel = page.getByRole('region', { name: names.functions })
  await expect(functionsPanel.getByRole('status').filter({ hasText: 'Offline external service' })).toBeVisible()
  const toolList = functionsPanel.getByRole('complementary', { name: 'Tool', exact: true })
  await toolList.getByRole('button', { name: 'Additional synthetic Tool 50', exact: true }).click()
  await expect(functionsPanel.getByRole('group', { name: 'Additional synthetic Tool 50', exact: true })).toBeVisible()
  await expect(toolList.getByRole('button', { name: 'Disconnected service', exact: true })).toHaveCount(0)
  await toolList.getByRole('button', { name: 'Synthetic second Tool', exact: true }).click()
  for (const state of ['enabled', 'disabled', 'ask']) await expect(functionsPanel.getByText(`other_${state}`, { exact: true })).toBeVisible()
  await expect(functionsPanel.getByText('synthetic_function_0', { exact: true })).toHaveCount(0)
  const filters = page.getByRole('group', { name: 'Loaded results', exact: true })
  await expect(page.getByRole('combobox', { name: 'Decision', exact: true })).toHaveCount(0)
  const deniedFilter = filters.getByRole('button', { name: 'Denied', exact: true })
  await deniedFilter.focus(); await page.keyboard.press('Enter')
  await expect(deniedFilter).toHaveAttribute('aria-pressed', 'true')
  await expect(functionsPanel.getByText('other_disabled', { exact: true })).toBeVisible()
  await expect(functionsPanel.getByText('other_enabled', { exact: true })).toHaveCount(0)
  await expect(functionsPanel.getByText('other_ask', { exact: true })).toHaveCount(0)
  await deniedFilter.click()
  await expect(deniedFilter).toHaveAttribute('aria-pressed', 'false')
  await expect(functionsPanel.getByText('other_enabled', { exact: true })).toBeVisible()
  await filters.getByRole('button', { name: 'Allowed', exact: true }).click()
  await expect(functionsPanel.getByText('other_enabled', { exact: true })).toBeVisible()
  await expect(functionsPanel.getByText('other_disabled', { exact: true })).toHaveCount(0)
  const askFilter = filters.getByRole('button', { name: 'On request', exact: true })
  await askFilter.focus(); await page.keyboard.press('Space')
  await expect(askFilter).toHaveAttribute('aria-pressed', 'true')
  await expect(filters.getByRole('button', { name: 'Allowed', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await expect(functionsPanel.getByText('other_ask', { exact: true })).toBeVisible()
  await expect(functionsPanel.getByText('other_enabled', { exact: true })).toHaveCount(0)
  const pendingFilter = filters.getByRole('button', { name: 'Pending', exact: true })
  await pendingFilter.click()
  await expect(functionsPanel.getByText('other_ask', { exact: true })).toHaveCount(0)
  await pendingFilter.click()
  await expect(pendingFilter).toHaveAttribute('aria-pressed', 'false')
  await expect(functionsPanel.getByText('other_ask', { exact: true })).toBeVisible()
  await toolList.getByRole('button', { name: 'Synthetic topics', exact: true }).focus()
  await page.keyboard.press('Enter')
  const search = page.getByRole('textbox', { name: 'Search functions, tools, contacts or policies', exact: true })
  await search.fill('needle')
  const item = width < 1024 ? functionsPanel.getByRole('article', { name: 'needle_function', exact: true }) : functionsPanel.locator('tr').filter({ hasText: 'needle_function' })
  await expect(item).toBeVisible()
  await expect.poll(() => calls.length).toBe(1)
  expect(writes).toEqual([]); expect(activations).toEqual([])
  await expect(item.getByRole('button', { name: 'Inherit', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await item.getByRole('button', { name: 'Deny', exact: true }).click()
  await expect.poll(() => writes).toEqual([{ function_name: 'needle_function', capability_kind: 'tool', state: 'disabled' }])
  await expect(item).toContainText('Denied')
  await expect(item.getByRole('button', { name: 'Deny', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await item.getByRole('button', { name: 'Inherit', exact: true }).click()
  await expect.poll(() => writes.at(-1).state).toBe('default')
  await expect(item).toContainText('On request')
  await expect(item.getByRole('button', { name: 'Inherit', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await search.fill('')
  await toolList.getByRole('button', { name: 'Synthetic second Tool', exact: true }).click()
  await expect(item).toHaveCount(0)
  const tool = functionsPanel.getByRole('group', { name: 'Synthetic second Tool', exact: true })
  const active = tool.getByRole('group', { name: 'Active connection', exact: true })
  await expect(active.getByRole('button', { name: 'Active', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await active.getByRole('button', { name: 'Inactive', exact: true }).click()
  await expect(active.getByRole('button', { name: 'Inactive', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(toolList.getByRole('button', { name: 'Synthetic second Tool', exact: true })).toHaveAttribute('aria-current', 'true')
  await active.getByRole('button', { name: 'Active', exact: true }).click()
  await expect(active.getByRole('button', { name: 'Active', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(activations).toEqual([false, true])
  await search.fill('needle')
  await expect(item).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('permissions-dashboard.png'), fullPage: true, animations: 'disabled' })
})

test('Harness policies keep the stored toggle selected through errors, allow, deny and withdrawal', async ({ page }) => {
  const policy = { id: 'runtime-policy', agent_id: 7, runtime: 'hermes', capability_name: 'write_file', allowed: null,
    remembered: false, active: false, can_decide: true, can_revoke: true }
  const writes = []
  let fail = true
  await setup(page, { routes: async () => {
    await page.route('**/api/tools/action-authorizations/runtime-policies?*', route => route.fulfill({ json: [policy] }))
    await page.route('**/api/tools/action-authorizations/runtime-policies', route => {
      const data = route.request().postDataJSON(); writes.push(data.allowed)
      if (fail) { fail = false; return route.fulfill({ status: 409, json: {} }) }
      policy.allowed = data.allowed; policy.remembered = true; policy.active = true
      return route.fulfill({ json: { accepted: true } })
    })
    await page.route('**/api/tools/action-authorizations/runtime-permissions/runtime-policy', route => {
      writes.push(null); policy.allowed = null; policy.remembered = false; policy.active = false
      return route.fulfill({ json: { revoked: true } })
    })
  } })
  const panel = page.getByRole('region', { name: names.runtime })
  await expect(panel.getByRole('button', { name: 'On request', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(writes).toEqual([])
  await panel.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'On request', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Allow', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'Deny', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Deny', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'On request', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'On request', exact: true })).toHaveAttribute('aria-pressed', 'true')
  expect(writes).toEqual([true, true, false, null])
})

test('contact decisions can be changed and withdrawn with retry, while read-only viewers cannot manage them', async ({ page }) => {
  let removed = false, fail = true
  const row = { ...decision }
  const queries = [], changes = []
  await setup(page, { routes: async () => {
    await page.route('**/api/messenger/permissions?*', route => {
      queries.push(Object.fromEntries(new URL(route.request().url()).searchParams))
      return route.fulfill({ json: { items: removed ? [] : [row], total: removed ? 0 : 1, counts: { [row.allowed ? 'allowed' : 'denied']: removed ? 0 : 1 } } })
    })
    await page.route('**/api/messenger/permissions/remembered-contact', route => {
      if (route.request().method() === 'PUT') { changes.push(route.request().postDataJSON()); row.allowed = true; return route.fulfill({ json: { accepted: true } }) }
      if (fail) { fail = false; return route.fulfill({ status: 500, json: {} }) }
      removed = true; return route.fulfill({ status: 204 })
    })
  } })
  const panel = page.getByRole('region', { name: names.network })
  await expect(panel).toContainText('Denied')
  expect(queries[0].limit).toBe('50')
  await panel.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect.poll(() => changes).toEqual([{ allowed: true }])
  await expect(panel).toContainText('Allowed')
  await expect(panel.getByRole('button', { name: 'Allow', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'On request', exact: true }).click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Allow', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await panel.getByRole('button', { name: 'On request', exact: true }).click()
  await expect(panel.getByText(row.question, { exact: true })).toHaveCount(0)
})

test('changing agent discards late responses and never exposes decisions or management actions from the previous context', async ({ page }) => {
  let release
  const searches = []
  await setup(page, { readonly: true, routes: async () => {
    await page.route('**/api/messenger/permissions?*', async route => {
      const query = new URL(route.request().url()).searchParams
      searches.push(Object.fromEntries(query))
      if (query.get('agent_id') === '7') {
        await new Promise(resolve => { release = resolve })
        await route.fulfill({ json: { items: [decision], total: 1, counts: { denied: 1 } } }).catch(() => {})
      } else await route.fulfill({ json: { items: [{ ...decision, id: 'other', agent_id: 8, question: 'Other agent contact' }], total: 1, counts: { denied: 1 } } })
    })
  } })
  await expect.poll(() => typeof release).toBe('function')
  await page.getByRole('combobox', { name: 'Agent', exact: true }).click()
  await page.getByRole('option', { name: 'Other synthetic agent', exact: true }).click()
  release()
  await expect(page.getByText('Other agent contact', { exact: true })).toBeVisible()
  await expect(page.getByText(decision.question, { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Allow', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Remove decision', exact: true })).toHaveCount(0)
  await page.getByRole('textbox', { name: 'Search functions, tools, contacts or policies', exact: true }).fill('contact')
  await expect.poll(() => searches.at(-1).q).toBe('contact')
  expect(searches.at(-1).agent_id).toBe('8')
})

test('pending approvals stay usable and a one-time decision does not change a function policy', async ({ page }) => {
  const row = { id: 'synthetic-action', agent_id: 7, source: 'mcp', runtime: 'internal', capability_name: 'topic_create',
    status: 'pending', preview: 'Create a synthetic topic', can_answer: true, can_remember: true }
  const writes = []
  await setup(page, { route: '/permissions?request=synthetic-action', routes: async () => {
    await page.route('**/api/tools/action-authorizations?*', route => route.fulfill({ json: { items: row.status === 'pending' ? [row] : [], total: row.status === 'pending' ? 1 : 0 } }))
    await page.route('**/api/tools/action-authorizations/synthetic-action', route => route.fulfill({ json: row }))
    await page.route('**/api/tools/action-authorizations/synthetic-action/answer', route => {
      writes.push(route.request().postDataJSON()); row.status = 'approved'; row.can_answer = false
      return route.fulfill({ json: { accepted: true } })
    })
    await jsonRoute(page, '**/api/tools/agents/7/permissions', { ...empty, connections: [connection], capabilities: [capability('topic_create')] })
  } })
  await expect(page.getByRole('combobox', { name: 'Agent', exact: true })).toHaveValue('Synthetic agent')
  await expect(page.getByRole('dialog')).toContainText('Create a synthetic topic')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).first().click()
  await page.getByRole('button', { name: 'Review request', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Allow this action', exact: true }).click()
  await expect.poll(() => writes).toEqual([{ approved: true }])
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).first().click()
  await expect(page.getByRole('button', { name: 'Review request', exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: names.functions })).toContainText('On request')
})

test('a catalogue failure stays visible and retry restores its functions', async ({ page }) => {
  let failed = true
  await setup(page, { routes: async () => {
    await page.route('**/api/tools/agents/7/permissions', route => route.fulfill(failed ? { status: 503, json: {} } : {
      json: { ...empty, connections: [connection], capabilities: [capability('recovered_function')] },
    }))
  } })
  const panel = page.getByRole('region', { name: names.functions })
  await expect(panel.getByRole('alert')).toBeVisible()
  failed = false
  await panel.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(panel.getByText('recovered_function', { exact: true })).toBeVisible()
})

test('custom settings filter before pagination and reset restores inherited rights without changing the agent', async ({ page }) => {
  const functions = Array.from({ length: 53 }, (_, index) => capability(`inherited_${index}`))
  functions.push(
    capability('local_allowed', { connection_state: 'enabled', global_state: 'disabled', policy_state: 'enabled', effective_state: 'enabled', policy_source: 'connection' }),
    capability('same_as_global', { connection_state: 'enabled', global_state: 'enabled', policy_state: 'enabled', effective_state: 'enabled', policy_source: 'connection' }),
    capability('software_override', { connection_state: 'ask', default_state: 'enabled', policy_source: 'connection' }),
  )
  functions.push(...Array.from({ length: 60 }, (_, index) => capability(`inactive_local_${index}`, {
    id: `18:tool:inactive_local_${index}`, tool_id: 18, connection_id: 11, tool_label: 'Disabled synthetic Tool',
    connection_state: 'enabled', default_state: 'ask', policy_state: 'enabled', effective_state: 'disabled', policy_source: 'connection',
  })))
  functions.push(capability('global_blocked', { id: '19:tool:global_blocked', tool_id: 19, connection_id: 12,
    tool_label: 'Global synthetic Tool', connection_state: 'default', global_state: 'disabled',
    policy_state: 'disabled', effective_state: 'disabled', policy_source: 'tool' }))
  const pending = Array.from({ length: 51 }, (_, index) => ({ ...decision, id: `pending-${index}`, allowed: null,
    question: `Pending synthetic contact ${index}`, can_answer: false, options: [] }))
  const queries = []
  await setup(page, { routes: async () => {
    await jsonRoute(page, '**/api/tools/agents/7/permissions', { ...empty, capabilities: functions, connections: [connection,
      { ...connection, tool_id: 17, connection_id: 10, tool_label: 'Scoped synthetic Tool', management_scope: {
        configured: 'all', value: 'all', default: 'team', description: '', options: [{ value: 'team', label: '' }, { value: 'all', label: '' }],
      } },
      { ...connection, tool_id: 18, connection_id: 11, tool_label: 'Disabled synthetic Tool', active: false,
        parameters: { public_access_mode: 'ask' }, parameter_sources: { public_access_mode: 'tool' } },
      { ...connection, tool_id: 19, connection_id: 12, tool_label: 'Global synthetic Tool' },
    ] })
    await jsonRoute(page, '**/api/tools/action-authorizations?*', { items: [{ id: 'pending-action', agent_id: 7,
      source: 'mcp', status: 'pending', preview: 'Pending synthetic action', can_answer: false }], total: 1 })
    await jsonRoute(page, '**/api/tools/action-authorizations/runtime-policies?*', [
      { id: 'default-action', runtime: 'internal', capability_name: 'default_runtime', allowed: null, remembered: false },
      { id: 'remembered-action', runtime: 'internal', capability_name: 'remembered_runtime', allowed: false, remembered: true, active: true },
    ])
    await page.route('**/api/messenger/permissions?*', route => {
      const query = Object.fromEntries(new URL(route.request().url()).searchParams); queries.push(query)
      let rows = [...pending, decision].filter(row => !query.q || row.question.toLowerCase().includes(query.q.toLowerCase()))
      const counts = { allowed: 0, denied: rows.filter(row => row.allowed === false).length, pending: rows.filter(row => row.allowed === null).length }
      if (query.pending === 'false') rows = rows.filter(row => row.allowed !== null)
      if (query.pending === 'true') rows = rows.filter(row => row.allowed === null)
      if (query.allowed) rows = rows.filter(row => row.allowed === (query.allowed === 'true'))
      return route.fulfill({ json: { items: rows.slice(Number(query.offset), Number(query.offset) + Number(query.limit)), total: rows.length, counts } })
    })
  } })
  const tools = page.getByRole('region', { name: names.functions, exact: true })
  const runtime = page.getByRole('region', { name: names.runtime, exact: true })
  const network = page.getByRole('region', { name: names.network, exact: true })
  const filters = page.getByRole('group', { name: 'Loaded results', exact: true })
  const customSettings = filters.getByRole('button', { name: 'Custom settings', exact: true })
  await expect(customSettings.getByText('6', { exact: true })).toBeVisible()
  await expect(tools.getByText('inherited_0', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Pending approvals', exact: true })).toContainText('Pending synthetic action')
  await customSettings.focus(); await page.keyboard.press('Space')
  await expect(customSettings).toHaveAttribute('aria-pressed', 'true')
  await expect(customSettings.getByText('6', { exact: true })).toBeVisible()
  const toolList = tools.getByRole('complementary', { name: 'Tool', exact: true })
  await expect(toolList.getByRole('button', { name: 'Global synthetic Tool', exact: true })).toHaveCount(0)
  await toolList.getByRole('button', { name: 'Disabled synthetic Tool', exact: true }).click()
  const disabledTool = tools.getByRole('group', { name: 'Disabled synthetic Tool', exact: true })
  await expect(disabledTool.getByRole('button', { name: 'Inactive', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(disabledTool.getByText('inactive_local_0', { exact: true })).toHaveCount(0)
  await expect(disabledTool).not.toContainText('Public sites')
  await toolList.getByRole('button', { name: 'Synthetic topics', exact: true }).click()
  await expect(tools.getByText('local_allowed', { exact: true })).toBeVisible()
  await expect(tools.getByText('software_override', { exact: true })).toBeVisible()
  await expect(tools.getByText('same_as_global', { exact: true })).toHaveCount(0)
  await expect(tools.getByText('inherited_0', { exact: true })).toHaveCount(0)
  await expect(runtime.getByText('remembered_runtime', { exact: true })).toBeVisible()
  await expect(runtime.getByText('default_runtime', { exact: true })).toHaveCount(0)
  await expect(network.getByText(decision.question, { exact: true })).toBeVisible()
  await expect(network.getByText('Pending synthetic contact 0', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Pending approvals', exact: true })).not.toContainText('Pending synthetic action')
  await tools.getByRole('complementary', { name: 'Tool', exact: true }).getByRole('button', { name: 'Scoped synthetic Tool', exact: true }).click()
  await expect(tools.getByRole('group', { name: 'Scope for Scoped synthetic Tool (tools.management_scope)', exact: true })
    .getByRole('button', { name: 'All', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await tools.getByRole('complementary', { name: 'Tool', exact: true }).getByRole('button', { name: 'Synthetic topics', exact: true }).click()
  await filters.getByRole('button', { name: 'Allowed', exact: true }).click()
  await expect(tools.getByText('local_allowed', { exact: true })).toBeVisible()
  await expect(customSettings.getByText('6', { exact: true })).toBeVisible()
  await expect(tools.getByText('software_override', { exact: true })).toHaveCount(0)
  const search = page.getByRole('textbox', { name: 'Search functions, tools, contacts or policies', exact: true })
  await search.fill('queued_before_reset')
  await page.getByRole('button', { name: 'Reset filters', exact: true }).click()
  const resetQueryIndex = queries.length
  await expect(customSettings).toHaveAttribute('aria-pressed', 'false')
  await expect(search).toHaveValue('')
  await expect(filters.getByRole('button', { name: 'Allowed', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await expect(tools.getByText('inherited_0', { exact: true })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Agent', exact: true })).toHaveValue('Synthetic agent')
  await search.fill('local_allowed')
  await expect.poll(() => queries.at(-1)?.q).toBe('local_allowed')
  await expect(customSettings.getByText('1', { exact: true })).toBeVisible()
  expect(queries.slice(resetQueryIndex).some(query => query.q === 'queued_before_reset')).toBe(false)
  await page.getByRole('button', { name: 'Reset filters', exact: true }).click()
  await expect(runtime.getByText('default_runtime', { exact: true })).toBeVisible()
  await expect(customSettings.getByText('6', { exact: true })).toBeVisible()
})
